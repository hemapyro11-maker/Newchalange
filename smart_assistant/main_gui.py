"""
main_gui.py — واجهة المساعد الذكي (Smart Assistant)
وحدة مستقلة بالكامل: واجهة عصرية بـ CustomTkinter، Dark Mode، ودعم عربي/إنجليزي.
"""
import os
import sys
import tkinter as tk

try:
    import customtkinter as ctk
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "customtkinter"])
    import customtkinter as ctk

try:
    from core_engine import AssistantEngine
    from i18n import Translator
except ImportError:
    # لو شغّلنا exe
    sys.path.insert(0, os.path.dirname(sys.executable))
    from core_engine import AssistantEngine
    from i18n import Translator

# ── Theme ───────────────────────────────────────────────────────────────
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

BG        = "#0f1117"
CARD      = "#1a1d27"
ACCENT    = "#4f6ef7"
GREEN     = "#22c55e"
RED       = "#ef4444"
ORANGE    = "#f97316"
GRAY      = "#6b7280"
TEXT      = "#f1f5f9"
TEXT_DIM  = "#94a3b8"
BORDER    = "#2d3148"

LOG_COLORS = {
    "info":  TEXT,
    "warn":  ORANGE,
    "error": RED,
    "ok":    GREEN,
}


class AssistantApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.t = Translator("ar")
        self.engine = AssistantEngine(on_log=self._on_log, on_status=self._on_status)

        self.geometry("820x620")
        self.minsize(700, 520)
        self.configure(fg_color=BG)
        self.resizable(True, True)

        self._build_ui()
        self.engine.start()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── UI ──────────────────────────────────────────────────────────────
    def _build_ui(self):
        # ── Header ──
        self.header = ctk.CTkFrame(self, fg_color=CARD, corner_radius=0, height=64)
        self.header.pack(fill="x")
        self.header.pack_propagate(False)

        self.title_label = ctk.CTkLabel(
            self.header, font=ctk.CTkFont(size=22, weight="bold"), text_color=ACCENT
        )
        self.title_label.place(x=24, rely=0.5, anchor="w")

        self.subtitle_label = ctk.CTkLabel(
            self.header, font=ctk.CTkFont(size=12), text_color=TEXT_DIM
        )
        self.subtitle_label.place(relx=1.0, x=-120, rely=0.5, anchor="e")

        self.lang_btn = ctk.CTkButton(
            self.header, width=90, height=32, fg_color=BORDER, hover_color=ACCENT,
            command=self._toggle_lang
        )
        self.lang_btn.place(relx=1.0, x=-16, rely=0.5, anchor="e")

        # ── Status bar ──
        self.status_frame = ctk.CTkFrame(self, fg_color=CARD, corner_radius=10, height=48)
        self.status_frame.pack(fill="x", padx=16, pady=(12, 0))
        self.status_frame.pack_propagate(False)

        self.status_dot = ctk.CTkLabel(
            self.status_frame, text="●", font=ctk.CTkFont(size=14), text_color=GRAY
        )
        self.status_dot.place(x=16, rely=0.5, anchor="w")

        self.status_label = ctk.CTkLabel(
            self.status_frame, font=ctk.CTkFont(size=13, weight="bold"), text_color=TEXT_DIM
        )
        self.status_label.place(x=36, rely=0.5, anchor="w")

        self.start_btn = ctk.CTkButton(
            self.status_frame, width=120, height=32, fg_color=ACCENT, hover_color="#3b5bdb",
            command=self._toggle_engine
        )
        self.start_btn.place(relx=1.0, x=-16, rely=0.5, anchor="e")

        # ── Command input row ──
        input_row = ctk.CTkFrame(self, fg_color="transparent")
        input_row.pack(fill="x", padx=16, pady=(12, 0))

        self.cmd_entry = ctk.CTkEntry(
            input_row, fg_color=CARD, border_color=BORDER, height=42,
            font=ctk.CTkFont(size=13)
        )
        self.cmd_entry.pack(side="left", expand=True, fill="x", padx=(0, 8))
        self.cmd_entry.bind("<Return>", lambda e: self._send_command())

        self.send_btn = ctk.CTkButton(
            input_row, width=100, height=42, fg_color=ACCENT, hover_color="#3b5bdb",
            font=ctk.CTkFont(size=13, weight="bold"), command=self._send_command
        )
        self.send_btn.pack(side="left")

        # ── Log ──
        log_header = ctk.CTkFrame(self, fg_color="transparent")
        log_header.pack(fill="x", padx=16, pady=(14, 4))

        self.log_title_label = ctk.CTkLabel(
            log_header, font=ctk.CTkFont(size=12, weight="bold"), text_color=TEXT_DIM
        )
        self.log_title_label.pack(side="left")

        self.clear_btn = ctk.CTkButton(
            log_header, width=70, height=24, fg_color=CARD, hover_color=BORDER,
            text_color=TEXT_DIM, font=ctk.CTkFont(size=11), command=self._clear_log
        )
        self.clear_btn.pack(side="right")

        log_frame = ctk.CTkFrame(self, fg_color=CARD, corner_radius=10)
        log_frame.pack(fill="both", expand=True, padx=16, pady=(0, 16))

        self.log_box = tk.Text(
            log_frame, bg=CARD, fg=TEXT, insertbackground=TEXT,
            relief="flat", bd=0, font=("Consolas", 11),
            state="disabled", wrap="word",
            selectbackground=ACCENT, selectforeground=TEXT,
        )
        self.log_box.pack(fill="both", expand=True, padx=10, pady=10)
        for name, color in LOG_COLORS.items():
            self.log_box.tag_config(name, foreground=color)

        scrollbar = ctk.CTkScrollbar(log_frame, command=self.log_box.yview)
        scrollbar.pack(side="right", fill="y")
        self.log_box.configure(yscrollcommand=scrollbar.set)

        self._apply_lang()

    # ── i18n ────────────────────────────────────────────────────────────
    def _apply_lang(self):
        t = self.t
        self.title(t.t("app_title"))
        self.title_label.configure(text=t.t("app_title"))
        self.subtitle_label.configure(text=t.t("app_subtitle"))
        self.lang_btn.configure(text=t.t("lang_toggle"))
        self.status_label.configure(
            text=t.t("status_running") if self.engine.is_running() else t.t("status_stopped")
        )
        self.start_btn.configure(text=t.t("stop") if self.engine.is_running() else t.t("start"))
        self.cmd_entry.configure(
            placeholder_text=t.t("input_placeholder"),
            justify="right" if t.lang == "ar" else "left",
        )
        self.send_btn.configure(text=t.t("send"))
        self.log_title_label.configure(text=f"📋  {t.t('log_title')}")
        self.clear_btn.configure(text=t.t("clear_log"))

    def _toggle_lang(self):
        self.t.toggle()
        self._apply_lang()

    # ── Actions ─────────────────────────────────────────────────────────
    def _toggle_engine(self):
        if self.engine.is_running():
            self.engine.stop()
        else:
            self.engine.start()
            self._apply_lang()

    def _send_command(self):
        text = self.cmd_entry.get().strip()
        if not text:
            return
        self.__append_log(f"›  {text}", "info")
        self.engine.submit(text)
        self.cmd_entry.delete(0, "end")

    def _clear_log(self):
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

    def _on_close(self):
        self.engine.stop()
        self.destroy()

    # ── Callbacks (from engine thread) ────────────────────────────────
    def _on_log(self, msg: str, level: str = "info"):
        self.after(0, self.__append_log, msg, level)

    def __append_log(self, msg, level):
        self.log_box.configure(state="normal")
        tag = level if level in LOG_COLORS else "info"
        self.log_box.insert("end", msg + "\n", tag)
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

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
