"""
main_gui.py — واجهة نيزوكو (Nezuko)

واجهة محادثة نظيفة بـ CustomTkinter، مبنية على مبدأين اتعلمناهم من
الواجهات الحديثة:

1. **رد المساعدة مالوش فقاعة** — نص عادي على الخلفية مباشرة، وفقاعة
   لرسايل المستخدم بس. ده مش بس أنضف بصريًا، ده كمان بيحل باج حقيقي
   كان في النسخة القديمة: الفقاعات كانت بياخدوا مقاس صريح محسوب من
   `winfo_reqheight()` وبيطلعوا فاضيين وكبار أوي حوالين سطر واحد.
   من غير فقاعة أصلاً، مفيش مقاس نحسبه غلط.

2. **RTL حقيقي** — العربي مش بس نص متظبط يمين. الأيقونة بتيجي على
   يمين النص (مش شماله)، والمحاذاة `e` مش `w`، ورسايل المستخدم على
   اليمين. النسخة القديمة كانت بتحط الأيقونة بادئة مع `anchor="w"`،
   وده تخطيط إنجليزي مركّب على نص عربي.
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
    from CTkToolTip import CTkToolTip
except ImportError:
    CTkToolTip = None

try:
    import brain
    from core_engine import AssistantEngine
    from i18n import Translator
except ImportError:
    sys.path.insert(0, os.path.dirname(sys.executable))
    import brain
    from core_engine import AssistantEngine
    from i18n import Translator

# ── الثيم ───────────────────────────────────────────────────────────────
ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")

BG             = "#faf9f5"   # خلفية دافئة هادية
SIDEBAR        = "#f0eee6"
SIDEBAR_HOVER  = "#e6e2d6"
CARD           = "#ffffff"
BORDER         = "#e3ded0"
ACCENT         = "#c1633f"   # هوية نيزوكو
ACCENT_HOVER   = "#a8532f"
ACCENT_SOFT    = "#f6e6dc"
TEXT           = "#1f1e1d"
TEXT_DIM       = "#7d7566"
TEXT_FAINT     = "#a49d8c"
TEXT_ON_ACCENT = "#fdfbf7"
USER_BUBBLE    = "#eae6da"
GREEN          = "#4b8b6b"
RED            = "#c1483d"
ORANGE         = "#c98a3e"

LEVEL_COLOR = {"info": TEXT, "ok": GREEN, "warn": ORANGE, "error": RED}
LEVEL_ICON = {"info": "", "ok": "✓", "warn": "!", "error": "✕"}

MAX_ROWS = 200
MAX_CHARS = 4000


class AssistantApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.t = Translator("ar")
        self.engine = AssistantEngine(on_log=self._on_log, on_status=self._on_status)
        self.engine.on_need_file = self._on_need_file
        self.voice_enabled = False
        self._last_command_name = ""
        self._rows: list[ctk.CTkFrame] = []
        self._tooltips: dict = {}
        self._thinking_row = None
        self._plugin_count = 0

        self.title("نيزوكو")
        self.geometry("1120x760")
        self.minsize(900, 600)
        self.configure(fg_color=BG)

        self._build_ui()
        self.engine.start()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(400, self._greet)

    @property
    def _rtl(self) -> bool:
        return self.t.lang == "ar"

    # ── بناء الواجهة ────────────────────────────────────────────────────
    def _build_ui(self):
        root = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        root.pack(fill="both", expand=True)
        # السايدبار على اليمين في العربي — مش على الشمال
        self._build_sidebar(root)
        self._build_chat(root)
        self._apply_lang()

    def _build_sidebar(self, root):
        self.sidebar = ctk.CTkFrame(root, fg_color=SIDEBAR, corner_radius=0, width=252)
        self.sidebar.pack(side="right" if self._rtl else "left", fill="y")
        self.sidebar.pack_propagate(False)

        brand = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        brand.pack(fill="x", padx=18, pady=(22, 18))
        side = "right" if self._rtl else "left"

        ctk.CTkLabel(
            brand, text="🌸", width=36, height=36, corner_radius=10,
            fg_color=ACCENT, text_color=TEXT_ON_ACCENT,
            font=ctk.CTkFont(size=16),
        ).pack(side=side)

        titles = ctk.CTkFrame(brand, fg_color="transparent")
        titles.pack(side=side, padx=(0, 10) if self._rtl else (10, 0), fill="x", expand=True)
        anchor = "e" if self._rtl else "w"
        self.title_label = ctk.CTkLabel(
            titles, text="نيزوكو", anchor=anchor, text_color=TEXT,
            font=ctk.CTkFont(size=16, weight="bold"),
        )
        self.title_label.pack(fill="x")
        self.subtitle_label = ctk.CTkLabel(
            titles, anchor=anchor, text_color=TEXT_DIM, font=ctk.CTkFont(size=11),
        )
        self.subtitle_label.pack(fill="x")

        self.new_chat_btn = ctk.CTkButton(
            self.sidebar, height=38, corner_radius=10,
            fg_color=CARD, hover_color=SIDEBAR_HOVER, text_color=TEXT,
            border_width=1, border_color=BORDER,
            font=ctk.CTkFont(size=13), command=self._new_chat,
        )
        self.new_chat_btn.pack(fill="x", padx=14, pady=(0, 16))

        self.tools_label = self._section_label()
        self.attach_btn = self._nav_button("📎", self._attach_file)
        self.scan_btn = self._nav_button("🛡️", self._scan_file)
        self.mic_btn = self._nav_button("🎤", self._listen)

        ctk.CTkFrame(self.sidebar, fg_color=BORDER, height=1).pack(fill="x", padx=18, pady=14)

        self.settings_label = self._section_label()
        self.brain_btn = self._nav_button("🧠", self._open_settings)
        self.voice_btn = self._nav_button("🔇", self._toggle_voice)
        self.lang_btn = self._nav_button("🌐", self._toggle_lang)

        ctk.CTkFrame(self.sidebar, fg_color="transparent").pack(fill="both", expand=True)

        status_row = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        status_row.pack(fill="x", padx=18, pady=(0, 8))
        self.status_dot = ctk.CTkLabel(
            status_row, text="●", font=ctk.CTkFont(size=12), text_color=TEXT_FAINT, width=12,
        )
        self.status_dot.pack(side=side)
        self.status_label = ctk.CTkLabel(
            status_row, text_color=TEXT_DIM, font=ctk.CTkFont(size=11),
        )
        self.status_label.pack(side=side, padx=(0, 6) if self._rtl else (6, 0))

        self.brain_label = ctk.CTkLabel(
            self.sidebar, text_color=TEXT_FAINT, font=ctk.CTkFont(size=10),
            anchor=anchor, wraplength=210, justify="right" if self._rtl else "left",
        )
        self.brain_label.pack(fill="x", padx=18, pady=(0, 16))

    def _section_label(self) -> ctk.CTkLabel:
        lbl = ctk.CTkLabel(
            self.sidebar, anchor="e" if self._rtl else "w",
            text_color=TEXT_FAINT, font=ctk.CTkFont(size=10, weight="bold"),
        )
        lbl.pack(fill="x", padx=20, pady=(0, 4))
        return lbl

    def _nav_button(self, icon: str, command) -> ctk.CTkButton:
        """زرار سايدبار. الأيقونة بتتحط في _apply_lang على الجنب الصح
        حسب اللغة — يمين النص في العربي، شماله في الإنجليزي."""
        btn = ctk.CTkButton(
            self.sidebar, height=34, corner_radius=8,
            fg_color="transparent", hover_color=SIDEBAR_HOVER, text_color=TEXT,
            anchor="e" if self._rtl else "w", font=ctk.CTkFont(size=13),
            command=command,
        )
        btn._icon = icon
        btn.pack(fill="x", padx=12, pady=1)
        return btn

    def _build_chat(self, root):
        main = ctk.CTkFrame(root, fg_color=BG, corner_radius=0)
        main.pack(side="right" if self._rtl else "left", fill="both", expand=True)

        self.chat = ctk.CTkScrollableFrame(main, fg_color=BG, corner_radius=0)
        self.chat.pack(fill="both", expand=True, padx=40, pady=(24, 0))

        wrap = ctk.CTkFrame(main, fg_color="transparent")
        wrap.pack(fill="x", padx=40, pady=(8, 24))

        self.input_bar = ctk.CTkFrame(
            wrap, fg_color=CARD, corner_radius=22, border_width=1, border_color=BORDER,
        )
        self.input_bar.pack(fill="x")

        self.send_btn = ctk.CTkButton(
            self.input_bar, width=36, height=36, corner_radius=18,
            fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color=TEXT_ON_ACCENT,
            font=ctk.CTkFont(size=14, weight="bold"),
            text="↑", command=self._send,
        )
        self.send_btn.pack(side="left" if self._rtl else "right", padx=(8, 8), pady=6)

        self.mic_inline = ctk.CTkButton(
            self.input_bar, width=32, height=32, corner_radius=16,
            fg_color="transparent", hover_color=ACCENT_SOFT, text_color=TEXT_DIM,
            font=ctk.CTkFont(size=14), text="🎤", command=self._listen,
        )
        self.mic_inline.pack(side="left" if self._rtl else "right", pady=6)

        self.entry = ctk.CTkEntry(
            self.input_bar, fg_color="transparent", border_width=0, height=44,
            font=ctk.CTkFont(size=14), text_color=TEXT,
        )
        self.entry.pack(side="right" if self._rtl else "left", fill="x", expand=True,
                        padx=(14, 6), pady=4)
        self.entry.bind("<Return>", lambda e: self._send())
        self.entry.focus_set()

        self.hint = ctk.CTkLabel(
            wrap, text_color=TEXT_FAINT, font=ctk.CTkFont(size=10),
            anchor="e" if self._rtl else "w",
        )
        self.hint.pack(fill="x", padx=8, pady=(6, 0))

    # ── الرسايل ─────────────────────────────────────────────────────────
    def _add_user(self, text: str):
        row = ctk.CTkFrame(self.chat, fg_color="transparent")
        row.pack(fill="x", pady=(10, 2))
        bubble = ctk.CTkFrame(row, fg_color=USER_BUBBLE, corner_radius=16)
        # رسالة المستخدم على اليمين في العربي
        bubble.pack(side="right" if self._rtl else "left", padx=2)
        ctk.CTkLabel(
            bubble, text=text[:MAX_CHARS], text_color=TEXT,
            font=ctk.CTkFont(size=13), wraplength=520,
            justify="right" if self._rtl else "left",
            anchor="e" if self._rtl else "w",
        ).pack(padx=16, pady=10)
        self._track(row)

    def _add_assistant(self, text: str, level: str = "info", badge: str = ""):
        """رد المساعدة: نص على الخلفية من غير فقاعة.

        ده اللي بيحل باج الفقاعات الفاضية الكبيرة — مفيش إطار بمقاس
        محسوب بالإيد، فمفيش مقاس يطلع غلط.
        """
        row = ctk.CTkFrame(self.chat, fg_color="transparent")
        row.pack(fill="x", pady=(10, 2))
        inner = ctk.CTkFrame(row, fg_color="transparent")
        inner.pack(side="right" if self._rtl else "left", fill="x", expand=True)

        icon = LEVEL_ICON.get(level, "")
        body = f"{icon} {text}".strip() if icon else text
        if len(body) > MAX_CHARS:
            body = body[:MAX_CHARS] + "\n… (النص اتقطع — شوف السجل الكامل)"

        ctk.CTkLabel(
            inner, text=body, text_color=LEVEL_COLOR.get(level, TEXT),
            font=ctk.CTkFont(size=13), wraplength=640,
            justify="right" if self._rtl else "left",
            anchor="e" if self._rtl else "w",
        ).pack(fill="x", padx=2)

        if badge:
            ctk.CTkLabel(
                inner, text=badge, text_color=TEXT_FAINT,
                font=ctk.CTkFont(size=10),
                anchor="e" if self._rtl else "w",
            ).pack(fill="x", padx=2, pady=(2, 0))
        self._track(row)

    def _track(self, row):
        self._rows.append(row)
        while len(self._rows) > MAX_ROWS:
            self._rows.pop(0).destroy()
        self.after(30, self._scroll_bottom)

    def _show_thinking(self):
        if self._thinking_row is not None:
            return
        row = ctk.CTkFrame(self.chat, fg_color="transparent")
        row.pack(fill="x", pady=(10, 2))
        ctk.CTkLabel(
            row, text="نيزوكو بتفكر…", text_color=TEXT_FAINT,
            font=ctk.CTkFont(size=12), anchor="e" if self._rtl else "w",
        ).pack(side="right" if self._rtl else "left", padx=2)
        self._thinking_row = row
        self.after(30, self._scroll_bottom)

    def _hide_thinking(self):
        if self._thinking_row is not None:
            self._thinking_row.destroy()
            self._thinking_row = None

    def _scroll_bottom(self):
        canvas = self.chat._parent_canvas
        canvas.configure(scrollregion=canvas.bbox("all"))
        canvas.yview_moveto(1.0)

    # ── الترجمة والحالة ─────────────────────────────────────────────────
    def _icon_text(self, btn, label: str) -> str:
        """الأيقونة بعد النص في العربي، وقبله في الإنجليزي."""
        return f"{label}  {btn._icon}" if self._rtl else f"{btn._icon}  {label}"

    def _apply_lang(self):
        t = self.t
        self.title(t.t("app_title"))
        self.title_label.configure(text=t.t("app_title"))
        self.subtitle_label.configure(text=t.t("app_subtitle"))
        self.tools_label.configure(text=t.t("quick_actions"))
        self.settings_label.configure(text=t.t("settings"))
        self.new_chat_btn.configure(text=t.t("new_chat"))

        self.attach_btn.configure(text=self._icon_text(self.attach_btn, t.t("attach_file")))
        self.scan_btn.configure(text=self._icon_text(self.scan_btn, t.t("scan_file")))
        self.mic_btn.configure(text=self._icon_text(self.mic_btn, t.t("listen")))
        self.brain_btn.configure(text=self._icon_text(self.brain_btn, t.t("brain_settings")))
        self.lang_btn.configure(text=self._icon_text(self.lang_btn, t.t("lang_toggle")))

        self.voice_btn._icon = "🔊" if self.voice_enabled else "🔇"
        self.voice_btn.configure(
            text=self._icon_text(
                self.voice_btn,
                t.t("voice_toggle_on") if self.voice_enabled else t.t("voice_toggle_off"),
            ),
            text_color=ACCENT if self.voice_enabled else TEXT,
        )

        running = self.engine.is_running()
        self.status_label.configure(text=t.t("status_running") if running else t.t("status_stopped"))
        self.status_dot.configure(text_color=GREEN if running else TEXT_FAINT)
        self.entry.configure(
            placeholder_text=t.t("input_placeholder"),
            justify="right" if self._rtl else "left",
        )
        self.hint.configure(text=t.t("input_hint"))
        self._refresh_brain_label()

        self._tip(self.send_btn, "send", t.t("tooltip_send"))
        self._tip(self.attach_btn, "attach", t.t("tooltip_attach"))
        self._tip(self.scan_btn, "scan", t.t("tooltip_scan"))
        self._tip(self.mic_btn, "mic", t.t("tooltip_mic"))
        self._tip(self.mic_inline, "mic2", t.t("tooltip_mic"))
        self._tip(self.brain_btn, "brain", t.t("tooltip_brain"))
        self._tip(self.lang_btn, "lang", t.t("tooltip_lang"))
        self._tip(
            self.voice_btn, "voice",
            t.t("tooltip_voice_on") if self.voice_enabled else t.t("tooltip_voice_off"),
        )

    def _refresh_brain_label(self):
        try:
            rows = brain.get_brain().status()
        except Exception:  # noqa: BLE001
            self.brain_label.configure(text="")
            return
        ready = [r for r in rows if r["has_key"] and r["enabled"]]
        if not ready:
            self.brain_label.configure(
                text="⚠️ مفيش مخ متظبط — دوس 🧠 عشان تظبط واحد مجاني",
                text_color=ORANGE,
            )
            return
        left = sum(max(0, r["rpd"] - r["used_today"]) for r in ready)
        names = "، ".join(r["label"] for r in ready[:2])
        self.brain_label.configure(
            text=f"🧠 {names} — متبقي ~{left:,} طلب النهارده", text_color=TEXT_FAINT,
        )

    def _tip(self, widget, key: str, message: str):
        if CTkToolTip is None:
            return
        existing = self._tooltips.get(key)
        if existing is not None:
            existing.configure(message=message)
            return
        self._tooltips[key] = CTkToolTip(widget, message=message, delay=0.5)

    # ── الأفعال ─────────────────────────────────────────────────────────
    def _greet(self):
        rows = []
        try:
            rows = brain.get_brain().status()
        except Exception:  # noqa: BLE001
            pass
        ready = [r for r in rows if r["has_key"] and r["enabled"]]
        if ready:
            self._add_assistant(
                "أهلاً! أنا نيزوكو. اكتبلي أي حاجة بالعامية عادي — "
                "أفحصلك ملف، أظبطلك فيديو، أحللك قناة، أو نتكلم بس.\n"
                "مش لازم تحفظ أوامر."
            )
        else:
            self._add_assistant(
                "أهلاً! أنا نيزوكو.\n\n"
                "الأوامر المباشرة شغالة دلوقتي (زي env_check أو help)، بس عشان "
                "أفهم كلامك العادي محتاجة مخ.\n"
                "دوس 🧠 في الجنب — التظبيط مجاني بالكامل وبياخد دقيقتين.",
                level="warn",
            )

    def _new_chat(self):
        for row in self._rows:
            row.destroy()
        self._rows.clear()
        self._hide_thinking()
        self.engine.chat_history.clear()
        canvas = self.chat._parent_canvas
        canvas.configure(scrollregion=canvas.bbox("all"))
        canvas.yview_moveto(0.0)
        self._greet()

    def _send(self):
        text = self.entry.get().strip()
        if not text:
            return
        self._add_user(text)
        self._last_command_name = text.split(maxsplit=1)[0].lower()
        self.entry.delete(0, "end")
        self._show_thinking()
        self.engine.submit(text)

    def _attach_file(self):
        path = filedialog.askopenfilename(
            title=self.t.t("attach_file"),
            filetypes=[
                ("Media", "*.mp4 *.mov *.mkv *.avi *.webm *.mp3 *.wav *.m4a *.flac *.jpg *.jpeg *.png"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return
        self._add_user(f"📎 {path}")
        self._last_command_name = "probe"
        self._show_thinking()
        self.engine.submit(f"probe {shlex.quote(path)}")

    def _scan_file(self):
        path = filedialog.askopenfilename(
            title=self.t.t("scan_file"), filetypes=[("All files", "*.*")],
        )
        if not path:
            return
        self._add_user(f"🛡️ {path}")
        self._last_command_name = "security_report"
        self._show_thinking()
        self.engine.submit(f"security_report {shlex.quote(path)}")

    def _listen(self):
        self._add_user("🎤 …")
        self._last_command_name = "listen_run"
        self._show_thinking()
        self.engine.submit("listen_run")

    def _on_need_file(self, spec, callback):
        """المحرك عرف الأمر بس ناقصه ملف — بنفتح نافذة اختيار بدل ما
        نسأل المستخدم يكتب المسار. ده بيتنادى من thread المحرك، فلازم
        يترحّل للـ main thread قبل ما نلمس أي حاجة في Tk."""
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

    def _toggle_voice(self):
        self.voice_enabled = not self.voice_enabled
        self._apply_lang()

    def _toggle_lang(self):
        self.t.toggle()
        # السايدبار وترتيب العناصر بيعتمدوا على اتجاه اللغة، فبنعيد بناء
        # الواجهة كلها بدل ما نحاول نعكس كل ودجت لوحده
        for child in self.winfo_children():
            child.destroy()
        self._tooltips.clear()
        self._rows.clear()
        self._thinking_row = None
        self._build_ui()
        self._greet()

    def _speak(self, text: str):
        snippet = " ".join(text.split()).replace('"', "").replace("'", "")
        if len(snippet) > 300:
            snippet = snippet[:300] + "..."
        if not snippet:
            return
        self._last_command_name = "speak"
        self.engine.submit(f"speak {snippet}")

    def _on_close(self):
        self.engine.stop()
        self.destroy()

    # ── ردود المحرك (بتيجي من thread تاني) ──────────────────────────────
    def _safe_after(self, fn, *args):
        """`after` بتترمي RuntimeError لو النافذة اتقفلت خلاص.

        بيحصل فعليًا عند الخروج: `engine.stop()` بيخلي الـ worker يطلع
        وينادي `on_status("stopped")`، وساعتها النافذة ممكن تكون
        اتدمّرت — فبيطلع traceback في وش المستخدم وهو بيقفل البرنامج.
        """
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
        # رسايل تحميل الإضافات (٣٤ رسالة عند كل تشغيل) مالهاش لازمة في
        # المحادثة — بتغرق أول شاشة يشوفها المستخدم. بنعدّها ونعرضها
        # كسطر واحد في السايدبار؛ النص الكامل موجود في engine.log_history.
        if level == "ok" and "plugin loaded:" in msg:
            self._plugin_count += 1
            self.subtitle_label.configure(
                text=f"{self._plugin_count} إضافة جاهزة" if self._rtl
                else f"{self._plugin_count} plugins ready"
            )
            return

        self._hide_thinking()
        badge = ""
        # المحرك بيحط توقيع المزوّد في آخر سطر بالشكل "— <label>"
        if "\n— " in msg:
            msg, _, badge = msg.rpartition("\n— ")
        self._add_assistant(msg, level, badge)
        self._refresh_brain_label()

    def _on_status(self, status: str):
        self._safe_after(self._render_status, status)

    def _render_status(self, status: str):
        running = status == "running"
        self.status_dot.configure(text_color=GREEN if running else TEXT_FAINT)
        self.status_label.configure(
            text=self.t.t("status_running") if running else self.t.t("status_stopped")
        )

    # ── نافذة الإعدادات ─────────────────────────────────────────────────
    def _open_settings(self):
        SettingsWindow(self)


class SettingsWindow(ctk.CTkToplevel):
    """نافذة إعدادات المخ: مفاتيح المزوّدين المجانيين، الوضع، والخصوصية."""

    def __init__(self, app: AssistantApp):
        super().__init__(app)
        self.app = app
        self.title("إعدادات المخ")
        self.geometry("620x640")
        self.configure(fg_color=BG)
        self.transient(app)
        self._entries: dict[str, ctk.CTkEntry] = {}
        self._build()
        self.after(120, self.lift)

    def _build(self):
        wrap = ctk.CTkScrollableFrame(self, fg_color=BG)
        wrap.pack(fill="both", expand=True, padx=18, pady=18)

        ctk.CTkLabel(
            wrap, text="🧠 مخ نيزوكو", font=ctk.CTkFont(size=18, weight="bold"),
            text_color=TEXT, anchor="e",
        ).pack(fill="x", pady=(0, 4))
        ctk.CTkLabel(
            wrap, anchor="e", justify="right", text_color=TEXT_DIM,
            font=ctk.CTkFont(size=12), wraplength=540,
            text=("كل المزوّدين دول ليهم خطة مجانية دايمة من غير كارت ائتمان.\n"
                  "ضيف واحد على الأقل — ولو ضيفت أكتر، بيتبدلوا تلقائي "
                  "لما واحد يقف أو توصل لحده."),
        ).pack(fill="x", pady=(0, 14))

        for prov in sorted(brain.PROVIDERS.values(), key=lambda p: -p.quality):
            self._provider_card(wrap, prov)

        ctk.CTkFrame(wrap, fg_color=BORDER, height=1).pack(fill="x", pady=14)
        self._modes(wrap)

        ctk.CTkButton(
            wrap, text="حفظ وإغلاق", height=40, corner_radius=10,
            fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color=TEXT_ON_ACCENT,
            font=ctk.CTkFont(size=13, weight="bold"), command=self._save,
        ).pack(fill="x", pady=(16, 4))

    def _provider_card(self, parent, prov):
        card = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=12,
                            border_width=1, border_color=BORDER)
        card.pack(fill="x", pady=5)

        head = ctk.CTkFrame(card, fg_color="transparent")
        head.pack(fill="x", padx=14, pady=(12, 2))

        has = (not prov.needs_key and brain.is_local_alive(prov)) or \
            (prov.needs_key and bool(brain.get_key(prov.name)))
        ctk.CTkLabel(
            head, text="✅" if has else "⬜", font=ctk.CTkFont(size=13), width=24,
        ).pack(side="right")
        ctk.CTkLabel(
            head, text=prov.label, anchor="e", text_color=TEXT,
            font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(side="right", fill="x", expand=True)

        meta = f"{prov.rpd} طلب/يوم · سياق {prov.context:,} توكن"
        if prov.trains_on_input:
            meta += " · 🔓 بيستخدم كلامك للتدريب"
        if prov.name in brain.LOCAL_PROVIDERS:
            meta = "محلي بالكامل · بياناتك متخرجش من الجهاز"
        ctk.CTkLabel(
            card, text=meta, anchor="e", text_color=TEXT_DIM,
            font=ctk.CTkFont(size=10),
        ).pack(fill="x", padx=14)

        if prov.needs_key:
            entry = ctk.CTkEntry(
                card, height=34, corner_radius=8, show="•",
                placeholder_text="الصق المفتاح هنا",
                fg_color=BG, border_color=BORDER, text_color=TEXT,
            )
            entry.pack(fill="x", padx=14, pady=(8, 4))
            if brain.get_key(prov.name):
                entry.insert(0, "••••••••••••")
            self._entries[prov.name] = entry

        if prov.signup:
            ctk.CTkLabel(
                card, text=f"↗ {prov.signup}", anchor="e",
                text_color=ACCENT, font=ctk.CTkFont(size=10),
            ).pack(fill="x", padx=14, pady=(0, 12))

    def _modes(self, parent):
        cfg = brain.load_config()

        ctk.CTkLabel(
            parent, text="الأوضاع", anchor="e", text_color=TEXT,
            font=ctk.CTkFont(size=14, weight="bold"),
        ).pack(fill="x", pady=(0, 6))

        self.deep_var = ctk.BooleanVar(value=bool(cfg.get("deep_mode")))
        ctk.CTkSwitch(
            parent, text="الوضع العميق — كذا نموذج يجاوبوا وأقواهم يدمجهم",
            variable=self.deep_var, progress_color=ACCENT,
            font=ctk.CTkFont(size=12), text_color=TEXT,
        ).pack(fill="x", pady=4)
        ctk.CTkLabel(
            parent, text="أدق بس أبطأ، وبياخد ~4 أضعاف الحصة. للأسئلة المهمة بس.",
            anchor="e", text_color=TEXT_DIM, font=ctk.CTkFont(size=10),
        ).pack(fill="x", padx=8, pady=(0, 10))

        self.local_var = ctk.BooleanVar(value=bool(cfg.get("local_only")))
        ctk.CTkSwitch(
            parent, text="محلي بس — مفيش أي كلام يخرج من الجهاز",
            variable=self.local_var, progress_color=GREEN,
            font=ctk.CTkFont(size=12), text_color=TEXT,
        ).pack(fill="x", pady=4)
        ctk.CTkLabel(
            parent, text="بيقفل كل المزوّدين السحابيين. محتاج Ollama متثبت ومشغّل.",
            anchor="e", text_color=TEXT_DIM, font=ctk.CTkFont(size=10),
        ).pack(fill="x", padx=8)

    def _save(self):
        saved = []
        for name, entry in self._entries.items():
            value = entry.get().strip()
            if value and not value.startswith("••"):
                brain.set_key(name, value)
                saved.append(brain.PROVIDERS[name].label)
        cfg = brain.load_config()
        cfg["deep_mode"] = bool(self.deep_var.get())
        cfg["local_only"] = bool(self.local_var.get())
        brain.save_config(cfg)

        self.app._refresh_brain_label()
        if saved:
            self.app._add_assistant(f"✅ اتحفظ مفتاح: {'، '.join(saved)}", "ok")
        self.destroy()


if __name__ == "__main__":
    app = AssistantApp()
    app.mainloop()
