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
    import theme
    from core_engine import AssistantEngine
    from i18n import Translator
except ImportError:
    sys.path.insert(0, os.path.dirname(sys.executable))
    import brain
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

        self.t = Translator("ar")
        self.mode = brain.load_config().get("ui_theme", "dark")
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

        self.title("nezuko")
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
        return self.t.lang == "ar"

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
        self._line("✻", "nezuko", c["accent"], size=15, bold=True)
        self._line("", self.t.t("app_subtitle"), c["faint"], indent=1, size=11)
        self._blank(10)

        ready = [r for r in self._brain_rows() if r["has_key"] and r["enabled"]]
        if ready:
            self._line("", "اكتب أي حاجة بالعامية — مفيش أوامر تتحفظ.",
                       c["dim"], indent=1, size=12)
        else:
            self._line("", "الأوامر المباشرة شغالة (help / env_check).",
                       c["dim"], indent=1, size=12)
            self._line("", "عشان أفهم كلامك العادي، دوس ⚙ وظبّط مخ مجاني.",
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
            parts.append(f"{left:,} متبقي")
        else:
            parts.append("مفيش مخ · دوس ⚙")
        cfg = brain.load_config()
        if cfg.get("deep_mode"):
            parts.append("عميق")
        if cfg.get("local_only"):
            parts.append("محلي بس")
        if self.voice_enabled:
            parts.append("صوت")
        if self._plugin_count:
            parts.append(f"{self._plugin_count} إضافة")
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
        elif cmd in ("lang", "language"):
            self._toggle_lang()
        elif cmd in ("quit", "exit"):
            self._on_close()
        else:
            self._add_assistant(
                "/settings  /clear  /theme  /voice  /lang  /quit", "warn"
            )

    def _new_chat(self):
        for row in self._rows:
            row.destroy()
        self._rows.clear()
        self._thinking = None
        self.engine.chat_history.clear()
        self.stream._parent_canvas.yview_moveto(0.0)
        self._banner()

    def _attach_file(self):
        path = filedialog.askopenfilename(title="إرفاق ملف")
        if not path:
            return
        self._add_user(f"📎 {path}")
        self._last_command_name = "probe"
        self._show_thinking()
        self.engine.submit(f"probe {shlex.quote(path)}")

    def _scan_file(self):
        path = filedialog.askopenfilename(title="فحص أمني")
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
        self.t.toggle()
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
        if spec.kind == "dir":
            path = filedialog.askdirectory(title=spec.prompt or "اختار مجلد")
        else:
            path = filedialog.askopenfilename(title=spec.prompt or "اختار ملف")
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
    """قايمة إعدادات بتتنقل فيها بالكيبورد، زي قوايم الطرفية:
    ↑ ↓ للتنقل، Enter للتغيير، Esc للخروج."""

    def __init__(self, app: AssistantApp):
        super().__init__(app)
        self.app = app
        self.c = app.c
        self.cursor = 0
        self.editing = None

        self.title("settings")
        self.geometry("620x560")
        self.configure(fg_color=self.c["bg"])
        self.transient(app)
        self.protocol("WM_DELETE_WINDOW", self.close)

        self._build()
        self.bind("<Up>", lambda e: self._move(-1))
        self.bind("<Down>", lambda e: self._move(1))
        self.bind("<Return>", lambda e: self._activate())
        self.bind("<Escape>", lambda e: self._on_escape())
        self.after(80, self._focus)

    def _focus(self):
        self.lift()
        self.focus_force()

    # ── بنود القايمة ───────────────────────────────────────────────────
    def _items(self) -> list[dict]:
        cfg = brain.load_config()
        items = [{"kind": "head", "label": "المخ"}]
        for prov in sorted(brain.PROVIDERS.values(), key=lambda p: -p.quality):
            if prov.needs_key:
                has = bool(brain.get_key(prov.name))
                value = "متظبط" if has else "—"
            else:
                value = "شغال" if brain.is_local_alive(prov) else "مش شغال"
            items.append({
                "kind": "key" if prov.needs_key else "info",
                "label": prov.label, "value": value, "prov": prov,
            })
        items += [
            {"kind": "head", "label": "الأوضاع"},
            {"kind": "toggle", "label": "الوضع العميق", "cfg": "deep_mode",
             "value": "شغال" if cfg.get("deep_mode") else "مقفول",
             "note": "كذا نموذج يجاوبوا وأقواهم يدمجهم · ~4× الحصة"},
            {"kind": "toggle", "label": "محلي بس", "cfg": "local_only",
             "value": "شغال" if cfg.get("local_only") else "مقفول",
             "note": "بيقفل كل السحابي · محتاج Ollama"},
            {"kind": "head", "label": "الواجهة"},
            {"kind": "theme", "label": "الثيم", "value": self.app.mode},
            {"kind": "voice", "label": "الصوت",
             "value": "شغال" if self.app.voice_enabled else "مقفول"},
            {"kind": "lang", "label": "اللغة",
             "value": "العربية" if self.app._rtl else "English"},
        ]
        return items

    def _selectable(self) -> list[int]:
        return [i for i, it in enumerate(self.data) if it["kind"] != "head"]

    def _build(self):
        c = self.c
        for w in self.winfo_children():
            w.destroy()
        self.data = self._items()

        wrap = ctk.CTkScrollableFrame(self, fg_color=c["bg"], corner_radius=0,
                                      scrollbar_button_color=c["border"])
        wrap.pack(fill="both", expand=True, padx=22, pady=(18, 4))

        sel = self._selectable()
        if self.cursor >= len(sel):
            self.cursor = max(0, len(sel) - 1)
        active = sel[self.cursor] if sel else -1

        for idx, item in enumerate(self.data):
            if item["kind"] == "head":
                ctk.CTkLabel(
                    wrap, text=item["label"], text_color=c["faint"],
                    font=self.app._font(11, True), anchor=self.app._anchor,
                ).pack(fill="x", pady=(14, 4))
                continue

            is_active = idx == active
            row = ctk.CTkFrame(
                wrap, fg_color=c["panel_hi"] if is_active else "transparent",
                corner_radius=4,
            )
            row.pack(fill="x", pady=1)

            ctk.CTkLabel(
                row, text="❯" if is_active else " ", width=14,
                text_color=c["accent"], font=self.app._font(12, True),
            ).pack(side=self.app._side, padx=(6, 2), pady=5)

            ctk.CTkLabel(
                row, text=item["label"], text_color=c["text"],
                font=self.app._font(12), anchor=self.app._anchor,
            ).pack(side=self.app._side, fill="x", expand=True)

            vcolor = c["green"] if item["value"] in ("متظبط", "شغال") else c["dim"]
            ctk.CTkLabel(
                row, text=item["value"], text_color=vcolor,
                font=self.app._font(12),
            ).pack(side="left" if self.app._rtl else "right", padx=10)

            if is_active and item.get("note"):
                ctk.CTkLabel(
                    wrap, text=item["note"], text_color=c["faint"],
                    font=self.app._font(10), anchor=self.app._anchor,
                ).pack(fill="x", padx=22, pady=(0, 2))

            if is_active and item["kind"] == "key":
                self._key_editor(wrap, item["prov"])

        ctk.CTkLabel(
            self, text="↑ ↓ تنقل   ·   Enter تغيير   ·   Esc خروج",
            text_color=c["faint"], font=self.app._font(10),
        ).pack(pady=(2, 12))

    def _key_editor(self, parent, prov):
        c = self.c
        box = ctk.CTkFrame(parent, fg_color="transparent")
        box.pack(fill="x", padx=22, pady=(2, 6))

        self.editing = ctk.CTkEntry(
            box, height=30, corner_radius=4, show="•",
            placeholder_text="الصق المفتاح واضغط Enter",
            fg_color=c["panel"], border_color=c["border"], border_width=1,
            text_color=c["text"], placeholder_text_color=c["faint"],
            font=self.app._font(11), justify="left",
        )
        self.editing.pack(fill="x")
        self.editing._prov = prov
        self.editing.bind("<Return>", lambda e: self._save_key())

        ctk.CTkLabel(
            box, text=prov.signup, text_color=c["accent"],
            font=self.app._font(10), anchor=self.app._anchor,
        ).pack(fill="x", pady=(3, 0))
        if prov.trains_on_input:
            ctk.CTkLabel(
                box, text="🔓 الخطة المجانية بتستخدم كلامك للتدريب",
                text_color=c["yellow"], font=self.app._font(10),
                anchor=self.app._anchor,
            ).pack(fill="x")

    # ── التنقل والتفعيل ────────────────────────────────────────────────
    def _move(self, delta: int):
        sel = self._selectable()
        if sel:
            self.cursor = (self.cursor + delta) % len(sel)
        self._build()

    def _activate(self):
        if self.editing is not None and self.editing.winfo_exists() and \
                self.editing.get().strip():
            self._save_key()
            return
        sel = self._selectable()
        if not sel:
            return
        item = self.data[sel[self.cursor]]
        kind = item["kind"]

        if kind == "toggle":
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
        self._build()
        self.app._refresh_status()

    def _save_key(self):
        if self.editing is None or not self.editing.winfo_exists():
            return
        value = self.editing.get().strip()
        prov = self.editing._prov
        if value:
            how = brain.set_key(prov.name, value)
            note = "مخزن أسرار النظام" if how == "keyring" else "ملف محلي"
            self.app._add_assistant(f"مفتاح {prov.label} اتحفظ في {note}", "ok")
        self.editing = None
        self._build()
        self.app._refresh_status()

    def _on_escape(self):
        """Esc بيقفل القايمة — إلا لو إنت فعلاً بتكتب في خانة مفتاح،
        ساعتها بيلغي الكتابة الأول.

        الشرط على التركيز مهم: خانة المفتاح بتتبني لمجرد إن المؤشر
        واقف على مزوّد، فلو اكتفينا بوجودها كان Esc هيحتاج ضغطتين
        على أي سطر مزوّد حتى لو مكتبتش فيه حاجة.
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
