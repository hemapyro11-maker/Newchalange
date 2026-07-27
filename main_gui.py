"""
Y99 Filter Bot — واجهة حديثة
"""
import json
import os
import sys
import tkinter as tk

if sys.platform == "win32":
    import winsound
else:
    winsound = None

# ── تحقق من المتطلبات ──────────────────────────────────────────────────
try:
    import customtkinter as ctk
except ImportError:
    import subprocess
    import sys
    subprocess.check_call([sys.executable, "-m", "pip", "install", "customtkinter"])
    import customtkinter as ctk

try:
    from bot_core import Y99Bot
except ImportError:
    # لو شغّلنا exe
    sys.path.insert(0, os.path.dirname(sys.executable))
    from bot_core import Y99Bot

# ── Theme ───────────────────────────────────────────────────────────────
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

BG        = "#0f1117"
CARD      = "#1a1d27"
ACCENT    = "#4f6ef7"
ACCENT2   = "#7c3aed"
GREEN     = "#22c55e"
RED       = "#ef4444"
ORANGE    = "#f97316"
GRAY      = "#6b7280"
TEXT      = "#f1f5f9"
TEXT_DIM  = "#94a3b8"
BORDER    = "#2d3148"

LOG_COLORS = {
    "white":     TEXT,
    "gray":      TEXT_DIM,
    "green":     GREEN,
    "red":       RED,
    "orange":    ORANGE,
    "cyan":      "#22d3ee",
    "salmon":    "#fca5a5",
    "lightblue": "#93c5fd",
}

CONFIG_FILE = "y99_settings.json"


def _config_path() -> str:
    base = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) \
        else os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, CONFIG_FILE)


class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Y99 Filter Bot")
        self.geometry("780x640")
        self.minsize(700, 580)
        self.configure(fg_color=BG)
        self.resizable(True, True)

        self.bot: Y99Bot | None = None
        self.running = False
        self._found_f = False

        self._build_ui()
        self._load_settings()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── UI ──────────────────────────────────────────────────────────────
    def _build_ui(self):
        # ── Header ──
        header = ctk.CTkFrame(self, fg_color=CARD, corner_radius=0, height=64)
        header.pack(fill="x", padx=0, pady=0)
        header.pack_propagate(False)

        ctk.CTkLabel(
            header, text="Y99", font=ctk.CTkFont(size=22, weight="bold"),
            text_color=ACCENT
        ).place(x=24, rely=0.5, anchor="w")

        ctk.CTkLabel(
            header, text="Filter Bot",
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color=TEXT
        ).place(x=68, rely=0.5, anchor="w")

        ctk.CTkLabel(
            header, text="يبعت M، لو الرد F يفضل — لو M يتخطى",
            font=ctk.CTkFont(size=12), text_color=TEXT_DIM
        ).place(relx=1.0, x=-24, rely=0.5, anchor="e")

        # ── Status bar ──
        self.status_frame = ctk.CTkFrame(self, fg_color=CARD, corner_radius=10, height=48)
        self.status_frame.pack(fill="x", padx=16, pady=(12, 0))
        self.status_frame.pack_propagate(False)

        self.status_dot = ctk.CTkLabel(
            self.status_frame, text="●", font=ctk.CTkFont(size=14),
            text_color=GRAY
        )
        self.status_dot.place(x=16, rely=0.5, anchor="w")

        self.status_label = ctk.CTkLabel(
            self.status_frame, text="جاهز للتشغيل",
            font=ctk.CTkFont(size=13, weight="bold"), text_color=TEXT_DIM
        )
        self.status_label.place(x=36, rely=0.5, anchor="w")

        # ── Stats row ──
        stats_row = ctk.CTkFrame(self, fg_color="transparent")
        stats_row.pack(fill="x", padx=16, pady=(10, 0))

        self.stat_total  = self._stat_card(stats_row, "إجمالي الشاتات", "0", ACCENT)
        self.stat_skip   = self._stat_card(stats_row, "تم التخطي",     "0", RED)
        self.stat_stayed = self._stat_card(stats_row, "بنات (F)",       "0", GREEN)

        for w in (self.stat_total, self.stat_skip, self.stat_stayed):
            w.pack(side="left", expand=True, fill="x", padx=4)

        # ── Settings ──
        settings_frame = ctk.CTkFrame(self, fg_color=CARD, corner_radius=10)
        settings_frame.pack(fill="x", padx=16, pady=(10, 0))

        ctk.CTkLabel(
            settings_frame, text="⚙  الإعدادات",
            font=ctk.CTkFont(size=12, weight="bold"), text_color=TEXT_DIM
        ).grid(row=0, column=0, columnspan=4, sticky="w", padx=14, pady=(10, 4))

        # رسالة البداية
        ctk.CTkLabel(settings_frame, text="الرسالة:", text_color=TEXT_DIM,
                     font=ctk.CTkFont(size=12)).grid(row=1, column=0, padx=(14,4), pady=8)
        self.msg_var = ctk.StringVar(value="M")
        ctk.CTkEntry(settings_frame, textvariable=self.msg_var, width=60,
                     fg_color=BG, border_color=BORDER).grid(row=1, column=1, padx=4)

        # انتظار اتصال
        ctk.CTkLabel(settings_frame, text="انتظار اتصال (ث):", text_color=TEXT_DIM,
                     font=ctk.CTkFont(size=12)).grid(row=1, column=2, padx=(16,4))
        self.connect_var = ctk.StringVar(value="5")
        ctk.CTkEntry(settings_frame, textvariable=self.connect_var, width=50,
                     fg_color=BG, border_color=BORDER).grid(row=1, column=3, padx=4)

        # انتظار رد
        ctk.CTkLabel(settings_frame, text="انتظار رد (ث):", text_color=TEXT_DIM,
                     font=ctk.CTkFont(size=12)).grid(row=1, column=4, padx=(16,4))
        self.reply_var = ctk.StringVar(value="8")
        ctk.CTkEntry(settings_frame, textvariable=self.reply_var, width=50,
                     fg_color=BG, border_color=BORDER).grid(row=1, column=5, padx=(4,14), pady=8)

        # صوت التنبيه
        self.sound_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            settings_frame, text="🔊  صوت لما نلاقي F", variable=self.sound_var,
            font=ctk.CTkFont(size=12), text_color=TEXT_DIM,
            fg_color=ACCENT, hover_color="#3b5bdb", checkmark_color=TEXT,
        ).grid(row=2, column=0, columnspan=6, sticky="w", padx=14, pady=(0, 10))

        # ── Buttons ──
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill="x", padx=16, pady=(10, 0))

        self.start_btn = ctk.CTkButton(
            btn_row, text="▶  تشغيل", font=ctk.CTkFont(size=14, weight="bold"),
            fg_color=ACCENT, hover_color="#3b5bdb", corner_radius=10, height=42,
            command=self._toggle
        )
        self.start_btn.pack(side="left", expand=True, fill="x", padx=(0, 6))

        self.next_btn = ctk.CTkButton(
            btn_row, text="⏭  شات جديد", font=ctk.CTkFont(size=14, weight="bold"),
            fg_color=CARD, hover_color=BORDER, corner_radius=10, height=42,
            text_color=TEXT_DIM, state="disabled",
            command=self._request_next
        )
        self.next_btn.pack(side="left", expand=True, fill="x", padx=(6, 0))

        # ── Log ──
        log_header = ctk.CTkFrame(self, fg_color="transparent")
        log_header.pack(fill="x", padx=16, pady=(12, 4))
        ctk.CTkLabel(log_header, text="📋  السجل",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=TEXT_DIM).pack(side="left")
        ctk.CTkButton(log_header, text="مسح", width=60, height=24,
                      fg_color=CARD, hover_color=BORDER,
                      text_color=TEXT_DIM, font=ctk.CTkFont(size=11),
                      command=self._clear_log).pack(side="right")

        log_frame = ctk.CTkFrame(self, fg_color=CARD, corner_radius=10)
        log_frame.pack(fill="both", expand=True, padx=16, pady=(0, 16))

        self.log_box = tk.Text(
            log_frame, bg=CARD, fg=TEXT, insertbackground=TEXT,
            relief="flat", bd=0, font=("Consolas", 11),
            state="disabled", wrap="word",
            selectbackground=ACCENT, selectforeground=TEXT,
        )
        self.log_box.pack(fill="both", expand=True, padx=10, pady=10)

        # Tag colors for log
        for name, color in LOG_COLORS.items():
            self.log_box.tag_config(name, foreground=color)

        scrollbar = ctk.CTkScrollbar(log_frame, command=self.log_box.yview)
        scrollbar.pack(side="right", fill="y")
        self.log_box.configure(yscrollcommand=scrollbar.set)

    def _stat_card(self, parent, label, value, color):
        frame = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=10, height=70)
        frame.pack_propagate(False)

        val_label = ctk.CTkLabel(
            frame, text=value,
            font=ctk.CTkFont(size=28, weight="bold"),
            text_color=color
        )
        val_label.pack(pady=(8, 0))

        ctk.CTkLabel(
            frame, text=label,
            font=ctk.CTkFont(size=11),
            text_color=TEXT_DIM
        ).pack()

        frame._val_label = val_label
        return frame

    # ── Actions ─────────────────────────────────────────────────────────
    def _toggle(self):
        if not self.running:
            self._start_bot()
        else:
            self._stop_bot()

    def _read_settings(self):
        """يرجع dict إعدادات صحيحة، أو None لو فيه قيمة غلط (مع تسجيل سبب الخطأ)."""
        try:
            wait_connect = int(self.connect_var.get().strip() or 5)
            wait_reply   = int(self.reply_var.get().strip() or 8)
        except ValueError:
            self.__append_log("⚠  قيم الانتظار لازم تكون أرقام صحيحة", "orange")
            return None
        if wait_connect <= 0 or wait_reply <= 0:
            self.__append_log("⚠  قيم الانتظار لازم تكون أكبر من صفر", "orange")
            return None
        return {
            "send_msg":     self.msg_var.get().strip() or "M",
            "wait_connect": wait_connect,
            "wait_reply":   wait_reply,
        }

    def _load_settings(self):
        try:
            with open(_config_path(), "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return
        self.msg_var.set(str(data.get("send_msg", self.msg_var.get())))
        self.connect_var.set(str(data.get("wait_connect", self.connect_var.get())))
        self.reply_var.set(str(data.get("wait_reply", self.reply_var.get())))
        self.sound_var.set(bool(data.get("sound_on", True)))

    def _save_settings(self, settings: dict):
        data = dict(settings)
        data["sound_on"] = self.sound_var.get()
        try:
            with open(_config_path(), "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _start_bot(self):
        settings = self._read_settings()
        if settings is None:
            return
        self._save_settings(settings)
        self.bot = Y99Bot(
            settings,
            on_log=self._on_log,
            on_stats=self._on_stats,
            on_status=self._on_status,
        )
        self.bot.start()
        self.running = True
        self.start_btn.configure(text="⏹  إيقاف", fg_color=RED, hover_color="#b91c1c")
        self._set_status("running", "جارٍ التشغيل...", ACCENT)

    def _stop_bot(self):
        if self.bot:
            self.bot.stop()
        self.running = False
        self.start_btn.configure(text="▶  تشغيل", fg_color=ACCENT, hover_color="#3b5bdb")
        self._reset_next_btn()
        self._set_status("stopped", "متوقف", GRAY)

    def _request_next(self):
        if self.bot:
            self.bot.request_next()
        self._reset_next_btn()
        self._set_status("running", "جارٍ التشغيل...", ACCENT)

    def _reset_next_btn(self):
        # next_btn بيتلوّن أخضر لما نلاقي F (زر شغّال). أي حالة تانية
        # (running/stopped/error) لازم ترجّعه لشكله العادي المقفول —
        # وإلا هيفضل أخضر "شغّال شكلاً" حتى وهو disabled فعليًا.
        self.next_btn.configure(state="disabled", fg_color=CARD, hover_color=BORDER,
                                 text_color=TEXT_DIM, text="⏭  شات جديد")
        self._found_f = False

    def _clear_log(self):
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

    def _on_close(self):
        if self.bot:
            self.bot.stop()
        self.destroy()

    # ── Callbacks (from bot thread) ─────────────────────────────────────
    def _on_log(self, msg: str, color: str = "white"):
        self.after(0, self.__append_log, msg, color)

    def __append_log(self, msg, color):
        self.log_box.configure(state="normal")
        tag = color if color in LOG_COLORS else "white"
        self.log_box.insert("end", msg + "\n", tag)
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _on_stats(self, total, skipped, stayed):
        self.after(0, self.__update_stats, total, skipped, stayed)

    def __update_stats(self, total, skipped, stayed):
        self.stat_total._val_label.configure(text=str(total))
        self.stat_skip._val_label.configure(text=str(skipped))
        self.stat_stayed._val_label.configure(text=str(stayed))

    def _on_status(self, status: str):
        self.after(0, self.__update_status, status)

    def __update_status(self, status):
        if status == "running":
            self._set_status("running", "جارٍ التشغيل...", ACCENT)
            self._reset_next_btn()
        elif status == "found_f":
            self._set_status("found_f", "✅  لقينا F! اضغط شات جديد لما تخلص", GREEN)
            self.next_btn.configure(state="normal", fg_color=GREEN,
                                     hover_color="#16a34a", text_color="white",
                                     text="⏭  شات جديد")
            self._found_f = True
            self._play_found_sound()
        elif status == "starting":
            self._set_status("starting", "جارٍ الفتح...", ORANGE)
        elif status == "stopped":
            self.running = False
            self.start_btn.configure(text="▶  تشغيل", fg_color=ACCENT, hover_color="#3b5bdb")
            self._reset_next_btn()
            self._set_status("stopped", "متوقف", GRAY)
        elif status == "error":
            self.running = False
            self.start_btn.configure(text="▶  تشغيل", fg_color=ACCENT, hover_color="#3b5bdb")
            self._reset_next_btn()
            self._set_status("error", "حدث خطأ", RED)

    def _set_status(self, key, text, color):
        self.status_dot.configure(text_color=color)
        self.status_label.configure(text=text, text_color=color)

    def _play_found_sound(self, times_left=3):
        if not self.sound_var.get():
            return
        try:
            if winsound:
                winsound.MessageBeep(winsound.MB_ICONASTERISK)
            else:
                self.bell()
        except Exception:
            pass
        if times_left > 1:
            self.after(350, lambda: self._play_found_sound(times_left - 1))


# ── Entry ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = App()
    app.mainloop()
