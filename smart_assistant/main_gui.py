"""
main_gui.py — واجهة نيزوكو على طراز الطرفية (terminal-style)

الشكل مستوحى من واجهات الوكلاء في الطرفية: عمود واحد بيمشي من فوق
لتحت، خط مونوسبيس في كل حتة، خلفية داكنة، وحدود رفيعة. مفيش سايدبار
ولا كروت مدوّرة — المحادثة نفسها هي الواجهة.

اصطلاحات العرض:
    ›  سطر كتبته إنت
    ⏺  رد نيزوكو
    ⎿  نتيجة أداة اتنفذت (مزاحة تحت الأمر بتاعها)
    ⏵  سطر الحالة تحت (المخ النشط + الحصة المتبقية)

الإعدادات قايمة بتتنقل فيها بالكيبورد (↑ ↓ Enter Esc) زي قوايم
الطرفية، مش نافذة كروت.

RTL: العربي بيقلب اتجاه الأسطر — العلامة (› ⏺ ⎿) بتيجي على اليمين
والنص بيتظبط يمين. التبديل للإنجليزي بيعيد بناء الواجهة بالاتجاه
المعكوس بدل ما يحاول يعكس كل ودجت لوحده.
"""
import os
import shlex
import sys
from tkinter import filedialog

try:
    import customtkinter as ctk
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "customtkinter"])
    import customtkinter as ctk

try:
    import brain
    import hooks
    import permissions
    import sessions
    import theme
    from core_engine import AssistantEngine
    from i18n import Translator
except ImportError:
    sys.path.insert(0, os.path.dirname(sys.executable))
    import brain
    import hooks
    import permissions
    import sessions
    import theme
    from core_engine import AssistantEngine
    from i18n import Translator

ctk.set_appearance_mode("dark")

MAX_ROWS = 300
MAX_CHARS = 6000

GLYPH_USER = "›"
GLYPH_REPLY = "⏺"
GLYPH_RESULT = "⎿"
GLYPH_STATUS = "⏵"


class AssistantApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        cfg = brain.load_config()
        self.t = Translator(cfg.get("ui_lang", "en"))
        self.mode = cfg.get("ui_theme", "dark")
        self.c = theme.palette(self.mode)
        self.mono = theme.pick_mono(self)

        self.engine = AssistantEngine(on_log=self._on_log, on_status=self._on_status)
        self.engine.on_need_file = self._on_need_file
        self.voice_enabled = False
        self._last_command_name = ""
        self._rows: list = []
        self._plugin_count = 0
        self._thinking = None
        self._settings = None

        self.title(self.t.t("app_title"))
        self.geometry("1000x700")
        self.minsize(720, 480)

        self._build()
        self.engine.start()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<Escape>", lambda e: self._close_settings())
        self.after(350, self._banner)

    # ── مساعدات ────────────────────────────────────────────────────────
    @property
    def _rtl(self) -> bool:
        return self.t.is_rtl

    @property
    def _side(self) -> str:
        return "right" if self._rtl else "left"

    @property
    def _anchor(self) -> str:
        return "e" if self._rtl else "w"

    @property
    def _justify(self) -> str:
        return "right" if self._rtl else "left"

    def _font(self, size: int = 13, bold: bool = False) -> ctk.CTkFont:
        return ctk.CTkFont(family=self.mono, size=size,
                           weight="bold" if bold else "normal")

    # ── البناء ─────────────────────────────────────────────────────────
    def _build(self):
        c = self.c
        self.configure(fg_color=c["bg"])

        self.root = ctk.CTkFrame(self, fg_color=c["bg"], corner_radius=0)
        self.root.pack(fill="both", expand=True)

        self.stream = ctk.CTkScrollableFrame(
            self.root, fg_color=c["bg"], corner_radius=0,
            scrollbar_button_color=c["border"],
            scrollbar_button_hover_color=c["dim"],
        )
        self.stream.pack(fill="both", expand=True, padx=26, pady=(18, 6))

        bottom = ctk.CTkFrame(self.root, fg_color=c["bg"], corner_radius=0)
        bottom.pack(fill="x", padx=26, pady=(0, 14))

        # صندوق الإدخال — حد رفيع وزوايا شبه مربعة، زي إطار الطرفية
        box = ctk.CTkFrame(
            bottom, fg_color=c["panel"], corner_radius=6,
            border_width=1, border_color=c["border"],
        )
        box.pack(fill="x")

        self.prompt_mark = ctk.CTkLabel(
            box, text=GLYPH_USER, width=16, text_color=c["accent"], font=self._font(14, True),
        )
        self.prompt_mark.pack(side=self._side, padx=(12, 2), pady=8)

        self.entry = ctk.CTkEntry(
            box, fg_color="transparent", border_width=0, height=34,
            font=self._font(13), text_color=c["text"],
            placeholder_text_color=c["faint"], justify=self._justify,
        )
        self.entry.pack(side=self._side, fill="x", expand=True, padx=(2, 10), pady=4)
        self.entry.bind("<Return>", lambda e: self._send())
        self.entry.focus_set()

        # شريط أدوات نصي مختصر — أفعال بحرف واحد، مفيش أزرار ضخمة
        tools = ctk.CTkFrame(bottom, fg_color="transparent")
        tools.pack(fill="x", pady=(6, 0))

        self.status_label = ctk.CTkLabel(
            tools, text="", text_color=c["faint"], font=self._font(11),
            anchor=self._anchor,
        )
        self.status_label.pack(side=self._side, fill="x", expand=True)

        opposite = "left" if self._rtl else "right"
        self.tool_btns = []
        for glyph, cb, key in (
            ("⚙", self._open_settings, "settings"),
            ("🎤", self._listen, "mic"),
            ("🛡", self._scan_file, "scan"),
            ("📎", self._attach_file, "attach"),
        ):
            b = ctk.CTkButton(
                tools, text=glyph, width=26, height=22, corner_radius=4,
                fg_color="transparent", hover_color=c["panel_hi"],
                text_color=c["dim"], font=self._font(12), command=cb,
            )
            b.pack(side=opposite, padx=2)
            b._key = key
            self.tool_btns.append(b)

        self._refresh_status()

    # ── أسطر المحادثة ──────────────────────────────────────────────────
    def _line(self, glyph: str, text: str, color: str, *,
              indent: int = 0, size: int = 13, bold: bool = False):
        """سطر واحد في الشريط: علامة + نص، بالاتجاه الصح."""
        row = ctk.CTkFrame(self.stream, fg_color="transparent")
        row.pack(fill="x", pady=1)

        pad = (indent * 16)
        if glyph:
            ctk.CTkLabel(
                row, text=glyph, width=18, text_color=color,
                font=self._font(size, True), anchor="n",
            ).pack(side=self._side, padx=(pad, 4) if self._rtl else (pad, 4), anchor="n")

        body = text if len(text) <= MAX_CHARS else text[:MAX_CHARS] + "\n…"
        ctk.CTkLabel(
            row, text=body, text_color=color, font=self._font(size, bold),
            justify=self._justify, anchor=self._anchor, wraplength=760 - pad,
        ).pack(side=self._side, fill="x", expand=True,
               padx=(0, pad) if not self._rtl else (pad, 0))

        self._rows.append(row)
        while len(self._rows) > MAX_ROWS:
            self._rows.pop(0).destroy()
        self.after(20, self._scroll_bottom)
        return row

    def _blank(self, height: int = 6):
        f = ctk.CTkFrame(self.stream, fg_color="transparent", height=height)
        f.pack(fill="x")
        self._rows.append(f)

    def _add_user(self, text: str):
        self._blank()
        self._line(GLYPH_USER, text, self.c["accent"])

    def _add_assistant(self, text: str, level: str = "info", badge: str = ""):
        c = self.c
        color = {
            "info": c["text"], "ok": c["green"],
            "warn": c["yellow"], "error": c["red"],
        }.get(level, c["text"])
        self._blank()
        self._line(GLYPH_REPLY, text, color)
        if badge:
            self._line("", badge, c["faint"], indent=1, size=10)

    def _add_result(self, text: str, level: str = "info"):
        """نتيجة أداة — مزاحة تحت السطر اللي فوقها بعلامة ⎿."""
        c = self.c
        color = {"ok": c["green"], "warn": c["yellow"], "error": c["red"]}.get(
            level, c["dim"]
        )
        self._line(GLYPH_RESULT, text, color, indent=1, size=12)

    def _banner(self):
        c = self.c
        self._line("✻", self.t.t("app_title"), c["accent"], size=15, bold=True)
        self._line("", self.t.t("app_subtitle"), c["faint"], indent=1, size=11)
        self._blank(10)

        ready = [r for r in self._brain_rows() if r["has_key"] and r["enabled"]]
        if ready:
            self._line("", self.t.t("greet_ready"),
                       c["dim"], indent=1, size=12)
        else:
            self._line("", self.t.t("greet_commands"),
                       c["dim"], indent=1, size=12)
            self._line("", self.t.t("greet_setup"),
                       c["yellow"], indent=1, size=12)
        self._blank(10)

    def _scroll_bottom(self):
        canvas = self.stream._parent_canvas
        canvas.configure(scrollregion=canvas.bbox("all"))
        canvas.yview_moveto(1.0)

    def _show_thinking(self):
        if self._thinking is None:
            self._thinking = self._line("", "…", self.c["faint"], indent=1, size=12)

    def _hide_thinking(self):
        if self._thinking is not None:
            if self._thinking in self._rows:
                self._rows.remove(self._thinking)
            self._thinking.destroy()
            self._thinking = None

    # ── سطر الحالة ─────────────────────────────────────────────────────
    def _brain_rows(self) -> list[dict]:
        try:
            return brain.get_brain().status()
        except Exception:  # noqa: BLE001
            return []

    def _refresh_status(self):
        rows = self._brain_rows()
        ready = [r for r in rows if r["has_key"] and r["enabled"]]
        parts = []
        if ready:
            left = sum(max(0, r["rpd"] - r["used_today"]) for r in ready)
            parts.append(f"{ready[0]['label'].lower()}")
            if len(ready) > 1:
                parts.append(f"+{len(ready) - 1}")
            parts.append(self.t.t("quota_left", n=f"{left:,}"))
        else:
            parts.append(self.t.t("no_brain"))
        cfg = brain.load_config()
        if cfg.get("deep_mode"):
            parts.append(self.t.t("mode_deep"))
        if cfg.get("local_only"):
            parts.append(self.t.t("mode_local"))
        if self.voice_enabled:
            parts.append(self.t.t("mode_voice"))
        if self._plugin_count:
            parts.append(self.t.t("plugins_loaded", n=self._plugin_count))
        self.status_label.configure(text=f"{GLYPH_STATUS}  " + "  ·  ".join(parts))

    # ── الأفعال ────────────────────────────────────────────────────────
    def _send(self):
        text = self.entry.get().strip()
        if not text:
            return
        self.entry.delete(0, "end")
        if text.startswith("/"):
            self._slash(text[1:].strip().lower())
            return
        self._add_user(text)
        self._last_command_name = text.split(maxsplit=1)[0].lower()
        self._show_thinking()
        self.engine.submit(text)

    def _slash(self, cmd: str):
        """أوامر الواجهة نفسها — بتبدأ بـ / زي الطرفية، ومبتلمسش المحرك."""
        if cmd in ("settings", "config", ""):
            self._open_settings()
        elif cmd == "clear":
            self._new_chat()
        elif cmd == "theme":
            self._toggle_theme()
        elif cmd == "voice":
            self._toggle_voice()
        elif cmd in ("resume", "sessions"):
            self._open_settings()
            if self._settings is not None:
                self._settings.page = "sessions"
                self._settings.cursor = 0
                self._settings._build()
        elif cmd in ("lang", "language"):
            self._toggle_lang()
        elif cmd in ("quit", "exit"):
            self._on_close()
        else:
            self._add_assistant(
                self.t.t("slash_unknown"), "warn"
            )

    def _resume_session(self, session_id: str, messages: list[dict]):
        """بيفتح محادثة محفوظة: بيرسمها من الأول وبيكمّل عليها."""
        for row in self._rows:
            row.destroy()
        self._rows.clear()
        self._thinking = None
        self.engine.session_id = session_id
        self.engine.chat_history = list(messages)
        self.stream._parent_canvas.yview_moveto(0.0)
        self._line("✻", self.t.t("resumed"), self.c["accent"], size=13, bold=True)
        self._blank(8)
        for msg in messages:
            if msg.get("role") == "user":
                self._add_user(msg.get("content", ""))
            else:
                self._add_assistant(msg.get("content", ""))

    def _new_chat(self):
        for row in self._rows:
            row.destroy()
        self._rows.clear()
        self._thinking = None
        self.engine.chat_history.clear()
        self.engine.session_id = sessions.new_id()
        self.stream._parent_canvas.yview_moveto(0.0)
        self._banner()

    def _attach_file(self):
        path = filedialog.askopenfilename(title=self.t.t("attach_title"))
        if not path:
            return
        self._add_user(f"📎 {path}")
        self._last_command_name = "probe"
        self._show_thinking()
        self.engine.submit(f"probe {shlex.quote(path)}")

    def _scan_file(self):
        path = filedialog.askopenfilename(title=self.t.t("scan_title"))
        if not path:
            return
        self._add_user(f"🛡 {path}")
        self._last_command_name = "security_report"
        self._show_thinking()
        self.engine.submit(f"security_report {shlex.quote(path)}")

    def _listen(self):
        self._add_user("🎤 …")
        self._last_command_name = "listen_run"
        self._show_thinking()
        self.engine.submit("listen_run")

    def _toggle_voice(self):
        self.voice_enabled = not self.voice_enabled
        self._refresh_status()

    def _toggle_theme(self):
        self.mode = "light" if self.mode == "dark" else "dark"
        cfg = brain.load_config()
        cfg["ui_theme"] = self.mode
        brain.save_config(cfg)
        ctk.set_appearance_mode(self.mode)
        self._rebuild()

    def _toggle_lang(self):
        cfg = brain.load_config()
        cfg["ui_lang"] = self.t.toggle()
        brain.save_config(cfg)
        self._rebuild()

    def _rebuild(self):
        """اتجاه اللغة والثيم بيغيّروا التخطيط نفسه، فبنعيد البناء بدل
        ما نحاول نعدّل كل ودجت لوحده."""
        self._close_settings()
        self.c = theme.palette(self.mode)
        for child in self.winfo_children():
            child.destroy()
        self._rows.clear()
        self._thinking = None
        self._build()
        self._banner()

    def _speak(self, text: str):
        snippet = " ".join(text.split()).replace('"', "").replace("'", "")
        if len(snippet) > 300:
            snippet = snippet[:300] + "..."
        if snippet:
            self._last_command_name = "speak"
            self.engine.submit(f"speak {snippet}")

    def _on_close(self):
        self.engine.stop()
        self.destroy()

    # ── ربط اختيار الملف ───────────────────────────────────────────────
    def _on_need_file(self, spec, callback):
        self._safe_after(self._pick_file, spec, callback)

    def _pick_file(self, spec, callback):
        self._hide_thinking()
        # spec.prompt مفتاح ترجمة مش نص جاهز — عشان نافذة الاختيار
        # تتكلم بلغة الواجهة زي أي حاجة تانية
        title = self.t.t(spec.prompt) if spec.prompt else self.t.t(
            "pick_dir" if spec.kind == "dir" else "pick_file"
        )
        if spec.kind == "dir":
            path = filedialog.askdirectory(title=title)
        else:
            path = filedialog.askopenfilename(title=title)
        if path:
            self._add_user(f"📄 {path}")
            self._show_thinking()
        callback(path)

    # ── ردود المحرك (من thread تاني) ───────────────────────────────────
    def _safe_after(self, fn, *args):
        """`after` بترمي RuntimeError لو النافذة اتقفلت — بيحصل فعليًا
        وقت الخروج لما الـ worker يطلع وينادي on_status بعد التدمير."""
        try:
            self.after(0, fn, *args)
        except RuntimeError:
            pass

    def _on_log(self, msg: str, level: str = "info"):
        self._safe_after(self._render_log, msg, level)
        if level == "info" and self.voice_enabled and \
                self._last_command_name not in ("speak", "voice_status"):
            self._safe_after(self._speak, msg)

    def _render_log(self, msg: str, level: str):
        # تحميل الإضافات بيطبع عشرات الأسطر عند كل تشغيل — بيتعدّوا في
        # سطر الحالة بدل ما يغرقوا أول شاشة. النص الكامل في log_history.
        if level == "ok" and "plugin loaded:" in msg:
            self._plugin_count += 1
            self._refresh_status()
            return

        self._hide_thinking()
        badge = ""
        if "\n— " in msg:
            msg, _, badge = msg.rpartition("\n— ")
        # سطر بيبدأ بـ ↪ معناه أمر اتنفذ — بنعرضه كأداة مش كرد
        if msg.startswith("↪"):
            self._blank()
            self._line(GLYPH_REPLY, msg.lstrip("↪ ").strip(), self.c["blue"])
            return
        self._add_assistant(msg, level, badge)
        self._refresh_status()

    def _on_status(self, status: str):
        self._safe_after(lambda: self._refresh_status())

    # ── الإعدادات ──────────────────────────────────────────────────────
    def _open_settings(self):
        if self._settings is not None:
            return
        self._settings = SettingsPanel(self)

    def _close_settings(self):
        if self._settings is not None:
            self._settings.close()
            self._settings = None


class SettingsPanel(ctk.CTkToplevel):
    """قايمة إعدادات بصفحات، بتتنقل فيها بالكيبورد زي قوايم الطرفية.

    ↑ ↓ تنقل · Enter تغيير · ← رجوع · Esc خروج

    الصفحات بتغطي كل أنظمة نيزوكو الفرعية في مكان واحد بدل ما تكون
    متفرقة على أوامر مختلفة: المخ، الموصلات (MCP)، الإضافات، المهارات،
    الماكروهات، الجلسات، الصلاحيات، الأحداث (hooks)، والواجهة.
    """

    # مفاتيح بس — الأسماء المعروضة بتتسحب من i18n وقت الرسم
    PAGES = (
        "home", "brain", "connectors", "plugins", "skills",
        "macros", "sessions", "permissions", "hooks", "interface",
    )

    def __init__(self, app: AssistantApp):
        super().__init__(app)
        self.app = app
        self.c = app.c
        self.page = "home"
        self.cursor = 0
        self.editing = None

        self.title(self._tr("settings"))
        self.geometry("700x620")
        self.configure(fg_color=self.c["bg"])
        self.transient(app)
        self.protocol("WM_DELETE_WINDOW", self.close)

        self._build()
        self.bind("<Up>", lambda e: self._move(-1))
        self.bind("<Down>", lambda e: self._move(1))
        self.bind("<Return>", lambda e: self._activate())
        self.bind("<Left>", lambda e: self._back())
        self.bind("<BackSpace>", lambda e: self._back())
        self.bind("<Escape>", lambda e: self._on_escape())
        self.after(80, self._focus)

    def _tr(self, key: str, **fmt) -> str:
        return self.app.t.t(key, **fmt)

    def _focus(self):
        self.lift()
        self.focus_force()

    # ── بنود كل صفحة ───────────────────────────────────────────────────
    def _items(self) -> list[dict]:
        return getattr(self, f"_page_{self.page}")()

    def _page_home(self) -> list[dict]:
        rows = self.app._brain_rows()
        ready = sum(1 for r in rows if r["has_key"] and r["enabled"])
        cfg = brain.load_config()
        mgr = getattr(self.app.engine, "connector_manager", None)
        connected = sum(
            1 for v in getattr(mgr, "servers", {}).values()
            if v.get("status") == "connected"
        ) if mgr else 0
        return [
            {"kind": "head", "label": self._tr("sec_sections")},
            {"kind": "goto", "label": self._tr("page_brain"), "page": "brain",
             "value": f"{ready} {self._tr('ready')}" if ready else self._tr("none")},
            {"kind": "goto", "label": self._tr("page_connectors"), "page": "connectors",
             "value": self._tr("tools_count", n=connected) if connected else self._tr("not_set")},
            {"kind": "goto", "label": self._tr("page_plugins"), "page": "plugins",
             "value": str(len(self.app.engine._loaded_plugins))},
            {"kind": "goto", "label": self._tr("page_skills"), "page": "skills",
             "value": str(len(self.app.engine.skills.get("commands", {})))},
            {"kind": "goto", "label": self._tr("page_macros"), "page": "macros", "value": ""},
            {"kind": "goto", "label": self._tr("page_sessions"), "page": "sessions",
             "value": str(len(sessions.list_all()))},
            {"kind": "goto", "label": self._tr("page_permissions"), "page": "permissions",
             "value": str(len(permissions.allowed()))},
            {"kind": "goto", "label": self._tr("page_hooks"), "page": "hooks",
             "value": str(sum(len(v) for v in hooks.load().values()))},
            {"kind": "goto", "label": self._tr("page_interface"), "page": "interface",
             "value": self.app.mode},
            {"kind": "head", "label": self._tr("sec_modes")},
            {"kind": "toggle", "label": self._tr("deep_mode"), "cfg": "deep_mode",
             "value": self._tr("on") if cfg.get("deep_mode") else self._tr("off"),
             "note": self._tr("deep_note")},
            {"kind": "toggle", "label": self._tr("auto_deep"), "cfg": "auto_deep",
             "value": self._tr("on") if cfg.get("auto_deep") else self._tr("off"),
             "note": self._tr("auto_note")},
            {"kind": "toggle", "label": self._tr("verify_mode"), "cfg": "verify_mode",
             "value": self._tr("on") if cfg.get("verify_mode") else self._tr("off"),
             "note": self._tr("verify_note")},
            {"kind": "toggle", "label": self._tr("local_only"), "cfg": "local_only",
             "value": self._tr("on") if cfg.get("local_only") else self._tr("off"),
             "note": self._tr("local_note")},
        ]

    def _page_brain(self) -> list[dict]:
        items = [{"kind": "head", "label": self._tr("free_providers")}]
        for prov in sorted(brain.PROVIDERS.values(), key=lambda p: -p.quality):
            if prov.needs_key:
                value = self._tr("configured") if brain.get_key(prov.name) else self._tr("not_set")
                kind = "key"
            else:
                value = self._tr("running_word") if brain.is_local_alive(prov) else self._tr("not_running")
                kind = "info"
            items.append({"kind": kind, "label": prov.label,
                          "value": value, "prov": prov})
        return items

    def _page_connectors(self) -> list[dict]:
        mgr = getattr(self.app.engine, "connector_manager", None)
        items = [{"kind": "head", "label": self._tr("mcp_servers")}]
        if mgr is None:
            items.append({"kind": "info", "label": self._tr("mcp_missing"),
                          "value": "pip install mcp"})
            return items
        try:
            configured = mgr.load_config()
        except Exception:  # noqa: BLE001
            configured = {}
        if not configured:
            items.append({"kind": "info", "label": self._tr("mcp_none"),
                          "value": "connectors.json"})
            items.append({"kind": "info",
                          "label": self._tr("mcp_hint"),
                          "value": ""})
            return items
        for name in sorted(configured):
            state = mgr.servers.get(name, {})
            status = state.get("status", "disconnected")
            tools = len(state.get("tools", []))
            items.append({
                "kind": "connector", "label": name, "connector": name,
                "value": self._tr("tools_count", n=tools) if status == "connected" else status,
            })
        return items

    def _page_plugins(self) -> list[dict]:
        eng = self.app.engine
        items = [{"kind": "head", "label": self._tr("loaded_n", n=len(eng._loaded_plugins))}]
        for name in eng._loaded_plugins:
            items.append({"kind": "info", "label": name, "value": "✓"})
        pending = []
        try:
            base = sessions._base_dir() / "plugins_pending"
            pending = sorted(p.stem for p in base.glob("*.py")) if base.is_dir() else []
        except Exception:  # noqa: BLE001
            pending = []
        if pending:
            items.append({"kind": "head", "label": self._tr("pending_approval")})
            for name in pending:
                items.append({"kind": "info", "label": name,
                              "value": f"approve_plugin {name}"})
        items.append({"kind": "head", "label": self._tr("sec_actions")})
        items.append({"kind": "cmd", "label": self._tr("reload_plugins"),
                      "cmd": "reload_plugins", "value": ""})
        return items

    def _page_skills(self) -> list[dict]:
        skills = self.app.engine.skills
        commands = skills.get("commands", {})
        top = sorted(commands.items(), key=lambda kv: -kv[1].get("count", 0))[:15]
        items = [
            {"kind": "head",
             "label": self._tr("top_commands", n=len(commands))},
        ]
        for name, info in top:
            items.append({"kind": "info", "label": name,
                          "value": f"{info.get('count', 0)}×"})
        items.append({"kind": "head", "label": self._tr("local_dictionary")})
        items.append({"kind": "cmd", "label": self._tr("dict_coverage"),
                      "cmd": "brain_dict", "value": ""})
        items.append({"kind": "cmd", "label": self._tr("think_playbooks"),
                      "cmd": "think_playbooks list", "value": ""})
        return items

    def _page_macros(self) -> list[dict]:
        items = [{"kind": "head", "label": self._tr("custom_commands")}]
        try:
            d = sessions._base_dir() / "commands"
            names = sorted(p.stem for p in d.glob("*.txt")) if d.is_dir() else []
        except Exception:  # noqa: BLE001
            names = []
        if names:
            for name in names:
                items.append({"kind": "info", "label": name, "value": "✓"})
        else:
            items.append({"kind": "info",
                          "label": self._tr("no_macros"),
                          "value": ""})
        items.append({"kind": "cmd", "label": self._tr("reload_macros"),
                      "cmd": "reload_macros", "value": ""})
        return items

    def _page_sessions(self) -> list[dict]:
        items = [{"kind": "head", "label": self._tr("saved_chats")}]
        rows = sessions.list_all()
        if not rows:
            items.append({"kind": "info", "label": self._tr("no_sessions"),
                          "value": ""})
        for s in rows[:25]:
            items.append({
                "kind": "session", "label": s["title"], "session": s["id"],
                "value": f"{s['turns']}× · {sessions.relative_time(s['updated'])}",
                "note": self._tr("session_hint"),
            })
        if rows:
            items.append({"kind": "head", "label": self._tr("sec_actions")})
            items.append({"kind": "wipe_sessions", "label": self._tr("wipe_sessions"),
                          "value": f"{len(rows)}"})
        return items

    def _page_permissions(self) -> list[dict]:
        allowed = sorted(permissions.allowed())
        items = [
            {"kind": "head", "label": self._tr("auto_allowed")},
        ]
        if not allowed:
            items.append({
                "kind": "info", "label": self._tr("nothing_allowed"), "value": "✓",
                "note": self._tr("safe_default_note"),
            })
        for name in allowed:
            items.append({"kind": "revoke", "label": name, "value": self._tr("allowed_word"),
                          "note": self._tr("revoke_hint")})
        if allowed:
            items.append({"kind": "head", "label": self._tr("sec_actions")})
            items.append({"kind": "wipe_perms", "label": self._tr("wipe_perms"),
                          "value": str(len(allowed))})
        items.append({"kind": "head", "label": self._tr("never_allowed")})
        items.append({
            "kind": "info", "label": "، ".join(sorted(permissions.never_allowed())),
            "value": "",
            "note": self._tr("never_note"),
        })
        return items

    def _page_hooks(self) -> list[dict]:
        data = hooks.load()
        items = []
        for event in hooks.EVENTS:
            items.append({"kind": "head", "label": event})
            for cmd in data[event]:
                items.append({"kind": "unhook", "label": cmd, "value": self._tr("bound"),
                              "event": event, "note": self._tr("unhook_hint")})
            if not data[event]:
                items.append({"kind": "info", "label": "—", "value": ""})
        items.append({"kind": "head", "label": self._tr("sec_actions")})
        items.append({"kind": "info", "label": self._tr("hook_hint"),
                      "value": ""})
        return items

    def _page_interface(self) -> list[dict]:
        return [
            {"kind": "head", "label": self._tr("sec_appearance")},
            {"kind": "theme", "label": self._tr("theme"), "value": self.app.mode},
            {"kind": "lang", "label": self._tr("language"),
             "value": "العربية" if self.app._rtl else "English"},
            {"kind": "voice", "label": self._tr("voice"),
             "value": self._tr("on") if self.app.voice_enabled else self._tr("off")},
            {"kind": "head", "label": self._tr("sec_ui_commands")},
            {"kind": "info", "label": "/settings /clear /theme /voice /lang /quit",
             "value": ""},
        ]

    # ── الرسم ──────────────────────────────────────────────────────────
    def _selectable(self) -> list[int]:
        return [i for i, it in enumerate(self.data)
                if it["kind"] not in ("head", "info")]

    def _build(self):
        c = self.c
        for w in self.winfo_children():
            w.destroy()
        self.data = self._items()
        self.editing = None

        title = self._tr(f"page_{self.page}")
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=22, pady=(16, 2))
        ctk.CTkLabel(
            header, text=f"⚙ {title}", text_color=c["accent"],
            font=self.app._font(14, True), anchor=self.app._anchor,
        ).pack(fill="x")
        if self.page != "home":
            ctk.CTkLabel(
                header, text=self._tr("back_home"), text_color=c["faint"],
                font=self.app._font(10), anchor=self.app._anchor,
            ).pack(fill="x")

        wrap = ctk.CTkScrollableFrame(self, fg_color=c["bg"], corner_radius=0,
                                      scrollbar_button_color=c["border"])
        wrap.pack(fill="both", expand=True, padx=22, pady=(6, 4))

        sel = self._selectable()
        if self.cursor >= len(sel):
            self.cursor = max(0, len(sel) - 1)
        active = sel[self.cursor] if sel else -1

        for idx, item in enumerate(self.data):
            if item["kind"] == "head":
                ctk.CTkLabel(
                    wrap, text=item["label"], text_color=c["faint"],
                    font=self.app._font(10, True), anchor=self.app._anchor,
                ).pack(fill="x", pady=(12, 3))
                continue

            is_active = idx == active
            row = ctk.CTkFrame(
                wrap, fg_color=c["panel_hi"] if is_active else "transparent",
                corner_radius=4,
            )
            row.pack(fill="x", pady=1)

            mark = "❯" if is_active else (" " if item["kind"] != "goto" else "·")
            ctk.CTkLabel(
                row, text=mark, width=14, text_color=c["accent"],
                font=self.app._font(11, True),
            ).pack(side=self.app._side, padx=(6, 2), pady=4)

            label_color = c["text"] if item["kind"] != "info" else c["dim"]
            ctk.CTkLabel(
                row, text=item["label"], text_color=label_color,
                font=self.app._font(11), anchor=self.app._anchor,
                wraplength=420,
            ).pack(side=self.app._side, fill="x", expand=True)

            if item.get("value"):
                good = item["value"] in ("متظبط", "شغال", "مسموح", "✓")
                ctk.CTkLabel(
                    row, text=item["value"],
                    text_color=c["green"] if good else c["dim"],
                    font=self.app._font(10),
                ).pack(side="left" if self.app._rtl else "right", padx=10)

            if is_active and item.get("note"):
                ctk.CTkLabel(
                    wrap, text=item["note"], text_color=c["faint"],
                    font=self.app._font(9), anchor=self.app._anchor,
                    wraplength=560,
                ).pack(fill="x", padx=20, pady=(0, 2))

            if is_active and item["kind"] == "key":
                self._key_editor(wrap, item["prov"])

        hint = self._tr("nav_hint")
        if self.page != "home":
            hint = self._tr("nav_hint_sub")
        ctk.CTkLabel(
            self, text=hint, text_color=c["faint"], font=self.app._font(9),
        ).pack(pady=(2, 10))

    def _key_editor(self, parent, prov):
        c = self.c
        box = ctk.CTkFrame(parent, fg_color="transparent")
        box.pack(fill="x", padx=20, pady=(2, 6))

        self.editing = ctk.CTkEntry(
            box, height=28, corner_radius=4, show="•",
            placeholder_text=self._tr("paste_key"),
            fg_color=c["panel"], border_color=c["border"], border_width=1,
            text_color=c["text"], placeholder_text_color=c["faint"],
            font=self.app._font(10), justify="left",
        )
        self.editing.pack(fill="x")
        self.editing._prov = prov
        self.editing.bind("<Return>", lambda e: self._save_key())
        # customtkinter's CTkEntry لا يضمن دايمًا Ctrl+V الافتراضي (بيعتمد
        # على نظام التشغيل ولاي-آوت الكيبورد)، فبنعمل paste يدوي مضمون
        # بيستبدل محتوى الحقل بالكامل بمحتوى الحافظة (مناسب لحقل مفتاح واحد).
        self.editing.bind("<Control-v>", self._paste_into_editing)
        self.editing.bind("<Control-V>", self._paste_into_editing)
        self.editing.bind("<Button-3>", self._paste_into_editing)  # كليك يمين

        ctk.CTkLabel(
            box, text=prov.signup, text_color=c["accent"],
            font=self.app._font(9), anchor=self.app._anchor,
        ).pack(fill="x", pady=(2, 0))
        if prov.trains_on_input:
            ctk.CTkLabel(
                box, text=self._tr("trains_warning"),
                text_color=c["yellow"], font=self.app._font(9),
                anchor=self.app._anchor,
            ).pack(fill="x")

    def _paste_into_editing(self, event=None):
        if self.editing is None or not self.editing.winfo_exists():
            return "break"
        try:
            clip = self.editing.clipboard_get()
        except Exception:
            return "break"  # الحافظة فاضية أو مفيهاش نص
        clip = clip.strip()
        if not clip:
            return "break"
        self.editing.delete(0, "end")
        self.editing.insert(0, clip)
        return "break"  # يمنع أي معالجة افتراضية تانية تتعارض

    # ── التنقل ─────────────────────────────────────────────────────────
    def _move(self, delta: int):
        sel = self._selectable()
        if sel:
            self.cursor = (self.cursor + delta) % len(sel)
        self._build()

    def _back(self):
        if self.page != "home":
            self.page = "home"
            self.cursor = 0
            self._build()

    def _current(self) -> dict | None:
        sel = self._selectable()
        return self.data[sel[self.cursor]] if sel else None

    def _activate(self):
        if self.editing is not None and self.editing.winfo_exists() and \
                self.editing.get().strip():
            self._save_key()
            return
        item = self._current()
        if item is None:
            return
        kind = item["kind"]

        if kind == "goto":
            self.page = item["page"]
            self.cursor = 0
        elif kind == "toggle":
            cfg = brain.load_config()
            cfg[item["cfg"]] = not cfg.get(item["cfg"])
            brain.save_config(cfg)
        elif kind == "theme":
            self.app._toggle_theme()
            self.c = self.app.c
            self.configure(fg_color=self.c["bg"])
        elif kind == "voice":
            self.app._toggle_voice()
        elif kind == "lang":
            self.app._toggle_lang()
            self.c = self.app.c
        elif kind == "key":
            if self.editing is not None and self.editing.winfo_exists():
                self.editing.focus_set()
                return
        elif kind == "cmd":
            self.app.engine.submit(item["cmd"])
            self.close()
            return
        elif kind == "connector":
            self._toggle_connector(item["connector"])
        elif kind == "session":
            self._resume(item["session"])
            return
        elif kind == "wipe_sessions":
            n = sessions.delete_all()
            self.app._add_assistant(self._tr("wiped_sessions", n=n), "ok")
        elif kind == "revoke":
            permissions.revoke(item["label"])
        elif kind == "wipe_perms":
            n = permissions.revoke_all()
            self.app._add_assistant(self._tr("wiped_perms", n=n), "ok")
        elif kind == "unhook":
            hooks.remove(item["event"], item["label"])
        self._build()
        self.app._refresh_status()

    def _toggle_connector(self, name: str):
        mgr = getattr(self.app.engine, "connector_manager", None)
        if mgr is None:
            return
        state = mgr.servers.get(name, {}).get("status")
        if state == "connected":
            mgr.disconnect(name)
        else:
            mgr.connect(name)

    def _resume(self, session_id: str):
        messages = sessions.load(session_id)
        if messages is None:
            self.app._add_assistant(self._tr("no_sessions"), "error")
            self.close()
            return
        self.app._resume_session(session_id, messages)
        self.close()

    def _save_key(self):
        if self.editing is None or not self.editing.winfo_exists():
            return
        value = self.editing.get().strip()
        prov = self.editing._prov
        if value:
            how = brain.set_key(prov.name, value)
            key = "key_saved_keyring" if how == "keyring" else "key_saved_plain"
            self.app._add_assistant(self._tr(key, p=prov.label), "ok")
        self.editing = None
        self._build()
        self.app._refresh_status()

    def _on_escape(self):
        """Esc بيقفل — إلا لو بتكتب فعلاً في خانة مفتاح.

        الشرط على التركيز مهم: الخانة بتتبني لمجرد إن المؤشر واقف على
        مزوّد، فلو اكتفينا بوجودها كان Esc هيحتاج ضغطتين على أي مزوّد.
        """
        ed = self.editing
        if ed is not None and ed.winfo_exists() and self.focus_get() is ed:
            self.focus_set()
            return
        self.close()

    def close(self):
        self.app._settings = None
        self.destroy()


if __name__ == "__main__":
    app = AssistantApp()
    app.mainloop()
