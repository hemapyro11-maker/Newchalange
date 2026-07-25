"""
main_gui.py — واجهة نيزوكو (Nezuko)
واجهة عصرية بـ CustomTkinter: سايدبار + محادثة على شكل فقاعات (bubbles)
زي واجهات الدردشة الحديثة، مع دعم عربي/إنجليزي وصوت اختياري.
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
    # تلميحات (tooltips) عند تمرير الماوس فوق الأزرار — تحسين واجهة اختياري
    # بس، مش أساسي زي customtkinter نفسها: لو مش متثبت، الواجهة تشتغل
    # عادي من غيره من غير أي تلميحات (شوف _set_tooltip تحت).
    from CTkToolTip import CTkToolTip
except ImportError:
    CTkToolTip = None

try:
    from core_engine import AssistantEngine
    from i18n import Translator
except ImportError:
    # لو شغّلنا exe
    sys.path.insert(0, os.path.dirname(sys.executable))
    from core_engine import AssistantEngine
    from i18n import Translator

# ── Theme ───────────────────────────────────────────────────────────────
# لوحة ألوان دافئة عصرية (مستوحاة من واجهات الدردشة الحديثة) — هوية
# نيزوكو الخاصة، مش نسخة من أي براند تاني.
ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")

BG            = "#f1ece1"
SIDEBAR       = "#e7e0d0"
SIDEBAR_HOVER = "#dbd2bd"
CARD          = "#ffffff"
CARD_BORDER   = "#ddd3ba"
ACCENT        = "#c1633f"
ACCENT_HOVER  = "#a8532f"
ACCENT_SOFT   = "#f3ddd0"
TEXT          = "#332e27"
TEXT_DIM      = "#8a8272"
TEXT_ON_ACCENT = "#fdf9f4"
GREEN         = "#4b8b6b"
RED           = "#c1483d"
ORANGE        = "#c98a3e"
GRAY          = "#a49d8c"

USER_BUBBLE      = "#332e27"
USER_BUBBLE_TEXT = "#fdf9f4"
ASSISTANT_BUBBLE = CARD

LEVEL_ACCENT = {
    "info":  TEXT_DIM,
    "ok":    GREEN,
    "warn":  ORANGE,
    "error": RED,
}
LEVEL_ICON = {
    "info":  "🧵",
    "ok":    "✅",
    "warn":  "⚠️",
    "error": "❌",
}

MAX_BUBBLES = 300  # يمنع الأداء من التدهور في جلسة طويلة جدًا
MAX_BUBBLE_LINES = 25
MAX_BUBBLE_CHARS = 1600


class AssistantApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.t = Translator("ar")
        self.engine = AssistantEngine(on_log=self._on_log, on_status=self._on_status)
        self.voice_enabled = False
        self._last_command_name = ""
        self._bubble_rows: list[ctk.CTkFrame] = []
        self._tooltips: dict[str, CTkToolTip] = {}

        self.geometry("1040x700")
        self.minsize(840, 560)
        self.configure(fg_color=BG)
        self.resizable(True, True)

        self._build_ui()
        self.engine.start()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── UI ──────────────────────────────────────────────────────────────
    def _build_ui(self):
        root = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        root.pack(fill="both", expand=True)

        self._build_sidebar(root)
        self._build_main(root)

        self._apply_lang()

    def _build_sidebar(self, root):
        self.sidebar = ctk.CTkFrame(root, fg_color=SIDEBAR, corner_radius=0, width=248)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        brand_row = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        brand_row.pack(fill="x", padx=20, pady=(24, 4))

        self.avatar = ctk.CTkLabel(
            brand_row, text="🌸", width=40, height=40, corner_radius=12,
            fg_color=ACCENT, text_color=TEXT_ON_ACCENT, font=ctk.CTkFont(size=18, weight="bold"),
        )
        self.avatar.pack(side="left")

        title_col = ctk.CTkFrame(brand_row, fg_color="transparent")
        title_col.pack(side="left", padx=(10, 0), fill="x", expand=True)

        self.title_label = ctk.CTkLabel(
            title_col, font=ctk.CTkFont(size=17, weight="bold"), text_color=TEXT, anchor="w"
        )
        self.title_label.pack(fill="x")

        self.subtitle_label = ctk.CTkLabel(
            title_col, font=ctk.CTkFont(size=11), text_color=TEXT_DIM, anchor="w"
        )
        self.subtitle_label.pack(fill="x")

        ctk.CTkFrame(self.sidebar, fg_color=CARD_BORDER, height=1).pack(fill="x", padx=20, pady=16)

        # ── Quick actions ──
        self.actions_label = ctk.CTkLabel(
            self.sidebar, font=ctk.CTkFont(size=11, weight="bold"), text_color=TEXT_DIM, anchor="w"
        )
        self.actions_label.pack(fill="x", padx=20, pady=(0, 6))

        self.attach_btn = self._sidebar_button("📎", command=self._attach_file)
        self.scan_btn = self._sidebar_button("🛡️", command=self._scan_file)
        self.voice_btn = self._sidebar_button("🔇", command=self._toggle_voice)
        self.lang_btn = self._sidebar_button("🌐", command=self._toggle_lang)
        self.clear_btn = self._sidebar_button("🗑️", command=self._clear_log)

        # ── Spacer ──
        ctk.CTkFrame(self.sidebar, fg_color="transparent").pack(fill="both", expand=True)

        ctk.CTkFrame(self.sidebar, fg_color=CARD_BORDER, height=1).pack(fill="x", padx=20, pady=(0, 16))

        status_row = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        status_row.pack(fill="x", padx=20, pady=(0, 20))

        self.status_dot = ctk.CTkLabel(status_row, text="●", font=ctk.CTkFont(size=13), text_color=GRAY)
        self.status_dot.pack(side="left")

        self.status_label = ctk.CTkLabel(
            status_row, font=ctk.CTkFont(size=12, weight="bold"), text_color=TEXT_DIM
        )
        self.status_label.pack(side="left", padx=(6, 0))

        self.start_btn = ctk.CTkButton(
            self.sidebar, height=36, fg_color=ACCENT, hover_color=ACCENT_HOVER,
            text_color=TEXT_ON_ACCENT, corner_radius=10,
            font=ctk.CTkFont(size=12, weight="bold"), command=self._toggle_engine,
        )
        self.start_btn.pack(fill="x", padx=20, pady=(0, 20))

    def _sidebar_button(self, icon: str, command) -> ctk.CTkButton:
        btn = ctk.CTkButton(
            self.sidebar, height=38, corner_radius=10,
            fg_color="transparent", hover_color=SIDEBAR_HOVER,
            text_color=TEXT, anchor="w", font=ctk.CTkFont(size=13),
            command=command,
        )
        btn._nezuko_icon = icon  # يتقرا في _apply_lang عشان نبني النص الكامل (أيقونة + تسمية)
        btn.pack(fill="x", padx=12, pady=2)
        return btn

    def _build_main(self, root):
        main = ctk.CTkFrame(root, fg_color=BG, corner_radius=0)
        main.pack(side="left", fill="both", expand=True)

        self.chat_scroll = ctk.CTkScrollableFrame(main, fg_color=BG, corner_radius=0)
        self.chat_scroll.pack(fill="both", expand=True, padx=(8, 8), pady=(16, 0))

        # ── Input bar (pill-shaped, عايم فوق أسفل المحادثة) ──
        input_wrap = ctk.CTkFrame(main, fg_color="transparent")
        input_wrap.pack(fill="x", padx=24, pady=20)

        self.input_bar = ctk.CTkFrame(input_wrap, fg_color=CARD, corner_radius=24, border_width=1, border_color=CARD_BORDER)
        self.input_bar.pack(fill="x")

        self.cmd_entry = ctk.CTkEntry(
            self.input_bar, fg_color="transparent", border_width=0, height=48,
            font=ctk.CTkFont(size=14), text_color=TEXT,
        )
        self.cmd_entry.pack(side="left", fill="x", expand=True, padx=(20, 8), pady=4)
        self.cmd_entry.bind("<Return>", lambda e: self._send_command())

        self.send_btn = ctk.CTkButton(
            self.input_bar, width=44, height=40, corner_radius=20,
            fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color=TEXT_ON_ACCENT,
            font=ctk.CTkFont(size=15, weight="bold"), text="➤", command=self._send_command,
        )
        self.send_btn.pack(side="right", padx=(0, 6), pady=4)

    # ── Chat bubbles ────────────────────────────────────────────────────
    def _truncate_for_bubble(self, text: str) -> str:
        # فقاعة طويلة جدًا (زي مخرجات help أو تقرير أمان كامل) بتتقطع —
        # مش بس تجميل، ده كمان بيتجنب مشكلة رسم حقيقية في CustomTkinter
        # مع إطارات طويلة جدًا جوه CTkScrollableFrame (الخلفية البيضاء
        # مش بترسم صح للمحتوى اللي بيعدّي ارتفاع معين).
        lines = text.splitlines()
        if len(lines) <= MAX_BUBBLE_LINES and len(text) <= MAX_BUBBLE_CHARS:
            return text
        truncated = "\n".join(lines[:MAX_BUBBLE_LINES])[:MAX_BUBBLE_CHARS]
        remaining = len(lines) - MAX_BUBBLE_LINES
        note = f"\n… ({remaining} سطر تاني مقطوع، شوف السجل الكامل)" if remaining > 0 else "\n… (النص اتقطع)"
        return truncated + note

    def _add_bubble(self, text: str, role: str, level: str = "info"):
        row = ctk.CTkFrame(self.chat_scroll, fg_color="transparent")
        row.pack(fill="x", pady=5)

        is_user = role == "user"
        if not is_user:
            text = self._truncate_for_bubble(text)
        bubble = ctk.CTkFrame(
            row, corner_radius=16,
            fg_color=USER_BUBBLE if is_user else ASSISTANT_BUBBLE,
            border_width=0 if is_user else 1,
            border_color=CARD_BORDER,
        )
        bubble.pack(side="right" if is_user else "left", padx=8)

        if not is_user:
            accent = LEVEL_ACCENT.get(level, TEXT_DIM)
            ctk.CTkFrame(bubble, fg_color=accent, width=3, corner_radius=2).pack(side="left", fill="y", padx=(0, 0), pady=8)

        text_color = USER_BUBBLE_TEXT if is_user else TEXT
        prefix = "" if is_user else f"{LEVEL_ICON.get(level, '🧵')}  "
        label = ctk.CTkLabel(
            bubble, text=prefix + text, text_color=text_color,
            font=ctk.CTkFont(size=13, family="Consolas" if not is_user else None),
            justify="right" if self.t.lang == "ar" else "left",
            anchor="e" if self.t.lang == "ar" else "w",
            wraplength=560,
        )
        label.pack(padx=16, pady=10)
        # نحدد حجم الفقاعة صراحةً من قياس الليبل الحقيقي بدل ما نستنى
        # auto-size — أضمن وأسرع من الاعتماد على حدث Configure.
        label.update_idletasks()
        extra_width = 32 if is_user else 35  # padx(16+16) + شريط اللون الجانبي (3px) للفقاعات غير المستخدم
        bubble.configure(width=label.winfo_reqwidth() + extra_width, height=label.winfo_reqheight() + 20)

        self._bubble_rows.append(row)
        if len(self._bubble_rows) > MAX_BUBBLES:
            oldest = self._bubble_rows.pop(0)
            oldest.destroy()

        self.after(30, self._scroll_chat_to_bottom)

    def _set_tooltip(self, key: str, widget, message: str):
        # بننشئ CTkToolTip واحد لكل ودجت ونحدّث نصه بعدين (configure)
        # بدل ما نعمل واحد جديد كل مرة — إعادة الإنشاء بتسرّب نوافذ
        # tooltip قديمة معلّقة. من غير مكتبة CTkToolTip (اختيارية)،
        # الدالة دي مبتعملش حاجة والواجهة تشتغل عادي من غيرها.
        if CTkToolTip is None:
            return
        existing = self._tooltips.get(key)
        if existing is not None:
            existing.configure(message=message)
            return
        self._tooltips[key] = CTkToolTip(widget, message=message, delay=0.4)

    # ── i18n ────────────────────────────────────────────────────────────
    def _apply_lang(self):
        t = self.t
        self.title(t.t("app_title"))
        self.title_label.configure(text=t.t("app_title"))
        self.subtitle_label.configure(text=t.t("app_subtitle"))
        self.actions_label.configure(text=t.t("quick_actions"))

        self.attach_btn.configure(text=f"{self.attach_btn._nezuko_icon}  {t.t('attach_file')}")
        self.scan_btn.configure(text=f"{self.scan_btn._nezuko_icon}  {t.t('scan_file')}")
        voice_icon = "🔊" if self.voice_enabled else "🔇"
        self.voice_btn._nezuko_icon = voice_icon
        self.voice_btn.configure(
            text=f"{voice_icon}  {t.t('voice_toggle_on') if self.voice_enabled else t.t('voice_toggle_off')}",
            text_color=ACCENT if self.voice_enabled else TEXT,
        )
        self.lang_btn.configure(text=f"{self.lang_btn._nezuko_icon}  {t.t('lang_toggle')}")
        self.clear_btn.configure(text=f"{self.clear_btn._nezuko_icon}  {t.t('clear_log')}")

        is_running = self.engine.is_running()
        self.status_label.configure(
            text=t.t("status_running") if is_running else t.t("status_stopped")
        )
        self.start_btn.configure(text=t.t("stop") if is_running else t.t("start"))
        self.cmd_entry.configure(
            placeholder_text=t.t("input_placeholder"),
            justify="right" if t.lang == "ar" else "left",
        )

        self._set_tooltip("send", self.send_btn, t.t("tooltip_send"))
        self._set_tooltip("attach", self.attach_btn, t.t("tooltip_attach"))
        self._set_tooltip("scan", self.scan_btn, t.t("tooltip_scan"))
        self._set_tooltip("voice", self.voice_btn, t.t("tooltip_voice_on") if self.voice_enabled else t.t("tooltip_voice_off"))
        self._set_tooltip("lang", self.lang_btn, t.t("tooltip_lang"))
        self._set_tooltip("clear", self.clear_btn, t.t("tooltip_clear"))
        self._set_tooltip("start", self.start_btn, t.t("tooltip_stop") if is_running else t.t("tooltip_start"))

    def _toggle_lang(self):
        self.t.toggle()
        self._apply_lang()

    def _toggle_voice(self):
        self.voice_enabled = not self.voice_enabled
        self._apply_lang()

    # ── Actions ─────────────────────────────────────────────────────────
    def _toggle_engine(self):
        if self.engine.is_running():
            self.engine.stop()
        else:
            self.engine.start()
            self._apply_lang()

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
        self._add_bubble(f"📎  {path}", "user")
        self._last_command_name = "probe"
        self.engine.submit(f"probe {shlex.quote(path)}")

    def _scan_file(self):
        # من غير أي فلتر نوع ملف — الهدف إن أي ملف أيًا كان امتداده أو
        # حجمه يتقدر يترفع للفحص. virus_scan (جزء من security_report)
        # بيفحص عبر ClamAV بالستريمنج، من غير ما يتحمّل الملف في ذاكرة
        # بايثون خالص، فمفيش مشكلة مع ملفات كبيرة.
        path = filedialog.askopenfilename(
            title=self.t.t("scan_file"),
            filetypes=[("All files", "*.*")],
        )
        if not path:
            return
        self._add_bubble(f"{self.t.t('scanning_file')}  {path}", "user")
        self._last_command_name = "security_report"
        self.engine.submit(f"security_report {shlex.quote(path)}")

    def _send_command(self):
        text = self.cmd_entry.get().strip()
        if not text:
            return
        self._add_bubble(text, "user")
        self._last_command_name = text.split(maxsplit=1)[0].lower()
        self.engine.submit(text)
        self.cmd_entry.delete(0, "end")

    def _speak_async(self, text: str):
        # بتتنادى من _on_log لما الصوت شغال — بتبعت نتيجة الأمر الأخيرة
        # لأمر speak نفسه عشان نيزوكو "تقرا" الرد بصوتها. بننضّف الاقتباسات
        # عشان shlex.split جوه core_engine._dispatch ميوقعش في نص فيه
        # علامات اقتباس فردية (زي مسار ملف أو snippet كود)، وبنقصّر
        # النص الطويل عشان مانطلبش TTS لتقرير كامل صفحات.
        snippet = " ".join(text.split()).replace('"', "").replace("'", "")
        if len(snippet) > 300:
            snippet = snippet[:300] + "..."
        if not snippet:
            return
        self._last_command_name = "speak"
        self.engine.submit(f"speak {snippet}")

    def _clear_log(self):
        for row in self._bubble_rows:
            row.destroy()
        self._bubble_rows.clear()
        # CTkScrollableFrame بيحدّث الـ scrollregion بس لما يحصل حدث
        # <Configure> على الفريم الداخلي، وده مش مضمون يحصل فورًا بعد
        # destroy() لـ 19 فقاعة دفعة واحدة. من غير التحديث الصريح ده،
        # الـ scrollregion بتفضل زي ما كانت (كبيرة) فلما فقاعة جديدة
        # تتضاف بعد المسح، yview_moveto(1.0) بيسكرول لمكان فاضي بدل
        # ما يوريها — الفقاعة فعليًا موجودة بس برّه حدود العرض المرئي.
        canvas = self.chat_scroll._parent_canvas
        canvas.configure(scrollregion=canvas.bbox("all"))
        canvas.yview_moveto(0.0)

    def _scroll_chat_to_bottom(self):
        canvas = self.chat_scroll._parent_canvas
        canvas.configure(scrollregion=canvas.bbox("all"))
        canvas.yview_moveto(1.0)

    def _on_close(self):
        self.engine.stop()
        self.destroy()

    # ── Callbacks (from engine thread) ────────────────────────────────
    def _on_log(self, msg: str, level: str = "info"):
        self.after(0, self._add_bubble, msg, "assistant", level)
        # بس نتيجة أمر فعلي (level="info") بتتقال بصوت — مش رسائل تحميل
        # الإضافات ("ok") ولا الأخطاء/التحذيرات. وبنستثني نتيجة speak/
        # voice_status نفسها عشان نيزوكو ماتفضلش تقرا تأكيد إنها قالت
        # حاجة لغاية ما تدخل في حلقة نطق بلا نهاية.
        if level == "info" and self.voice_enabled and self._last_command_name not in ("speak", "voice_status"):
            self._speak_async(msg)

    def _on_status(self, status: str):
        self.after(0, self.__update_status, status)

    def __update_status(self, status: str):
        color = {"running": ACCENT, "stopped": GRAY}.get(status, GRAY)
        self.status_dot.configure(text_color=color)
        self._apply_lang()


# ── Entry ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = AssistantApp()
    app.mainloop()
