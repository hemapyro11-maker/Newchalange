"""Nezuko's bilingual chat workspace: conversations, composer and tools."""
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
MAX_STREAM_LINES = 4000  # سقف أسطر خام في صندوق المحادثة، بديل MAX_ROWS بعد التحويل لـ CTkTextbox


# ── اختصارات تحرير قياسية (نسخ/لصق/تحديد الكل/كليك يمين) ────────────
#
# CTkEntry و CTkTextbox متبنيين على ودجتس Tk عادية (tk.Entry / tk.Text)
# اللي *مالهاش* ربط افتراضي لـ Ctrl+A كـ "تحديد الكل" على ويندوز — في
# Tk الافتراضي Control-a معناها "روح لأول السطر" (أسلوب Emacs)، وده
# بيبان للمستخدم إنه "مش شغال" لأنه مش اللي متوقعه. نفس الحكاية مفيش
# قايمة كليك يمين افتراضية خالص. الدالتين دول بيضيفوا السلوك القياسي
# اللي أي برنامج ويندوز عادي بيعمله.

def _attach_entry_shortcuts(widget) -> None:
    """لصندوق إدخال قابل للتعديل (CTkEntry): نسخ/قص/لصق/تحديد الكل +
    قايمة كليك يمين."""
    entry = widget._entry if hasattr(widget, "_entry") else widget

    def select_all(_event=None):
        entry.selection_range(0, "end")
        entry.icursor("end")
        return "break"

    def copy(_event=None):
        try:
            sel = entry.selection_get()
        except Exception:
            return "break"
        entry.clipboard_clear()
        entry.clipboard_append(sel)
        return "break"

    def cut(_event=None):
        copy()
        try:
            entry.delete("sel.first", "sel.last")
        except Exception:
            pass
        return "break"

    def paste(_event=None):
        try:
            entry.insert("insert", entry.clipboard_get())
        except Exception:
            pass
        return "break"

    for seq in ("<Control-a>", "<Control-A>"):
        entry.bind(seq, select_all)
    for seq in ("<Control-c>", "<Control-C>"):
        entry.bind(seq, copy)
    for seq in ("<Control-x>", "<Control-X>"):
        entry.bind(seq, cut)
    for seq in ("<Control-v>", "<Control-V>"):
        entry.bind(seq, paste)

    menu = [None]

    def show_menu(event):
        import tkinter as tk
        m = tk.Menu(entry, tearoff=0)
        m.add_command(label="Cut", command=cut)
        m.add_command(label="Copy", command=copy)
        m.add_command(label="Paste", command=paste)
        m.add_separator()
        m.add_command(label="Select All", command=select_all)
        menu[0] = m
        try:
            m.tk_popup(event.x_root, event.y_root)
        finally:
            m.grab_release()

    entry.bind("<Button-3>", show_menu)


def _attach_readonly_textbox_shortcuts(widget) -> None:
    """لصندوق نص للقراءة بس (زي شريط المحادثة): تحديد الكل/نسخ + كليك
    يمين، من غير لصق أو تعديل (الودجت disabled أصلاً)."""
    text = widget._textbox if hasattr(widget, "_textbox") else widget

    def select_all(_event=None):
        text.tag_add("sel", "1.0", "end")
        return "break"

    def copy(_event=None):
        try:
            sel = text.get("sel.first", "sel.last")
        except Exception:
            return "break"
        text.clipboard_clear()
        text.clipboard_append(sel)
        return "break"

    for seq in ("<Control-a>", "<Control-A>"):
        text.bind(seq, select_all)
    for seq in ("<Control-c>", "<Control-C>"):
        text.bind(seq, copy)

    def show_menu(event):
        import tkinter as tk
        m = tk.Menu(text, tearoff=0)
        m.add_command(label="Copy", command=copy)
        m.add_separator()
        m.add_command(label="Select All", command=select_all)
        try:
            m.tk_popup(event.x_root, event.y_root)
        finally:
            m.grab_release()

    text.bind("<Button-3>", show_menu)

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
        self.ui_font = theme.pick_ui(self)

        self.engine = AssistantEngine(on_log=self._on_log, on_status=self._on_status)
        self.engine.on_need_file = self._on_need_file
        self.voice_enabled = False
        self._last_command_name = ""
        self._plugin_count = 0
        self._thinking = None
        self._settings = None
        self._activity = "starting"

        self.title(self.t.t("app_title"))
        self.geometry("1480x900")
        self.minsize(1100, 680)

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
        return ctk.CTkFont(family=self.ui_font, size=size,
                           weight="bold" if bold else "normal")

    # ── البناء ─────────────────────────────────────────────────────────
    def _build(self):
        c = self.c
        self.configure(fg_color=c["bg"])
        self._rows = []  # lightweight rendering history; also useful to GUI diagnostics

        self.app_menu = ctk.CTkFrame(self, height=32, fg_color=c["panel"], corner_radius=0)
        self.app_menu.pack(fill="x")
        self.app_menu.pack_propagate(False)
        for label, callback in (
            ("File", self._new_chat), ("Edit", self._copy_chat),
            ("View", self._toggle_theme), ("Help", lambda: self._seed_prompt("help")),
        ):
            ctk.CTkButton(
                self.app_menu, text=label, command=callback, width=48, height=28,
                fg_color="transparent", hover_color=c["panel_hi"], corner_radius=4,
                text_color=c["dim"], font=self._font(11),
            ).pack(side="left", padx=(6, 0), pady=2)

        self.root = ctk.CTkFrame(self, fg_color=c["bg"], corner_radius=0)
        self.root.pack(fill="both", expand=True)
        self.root.grid_rowconfigure(0, weight=1)
        self.root.grid_columnconfigure(1, weight=1, minsize=560)

        # Left navigation mirrors a modern coding assistant: identity, new chat,
        # recent conversations and settings stay visible instead of hiding in commands.
        self.sidebar = ctk.CTkFrame(
            self.root, width=258, fg_color="#171717" if self.mode == "dark" else "#f2f2ef",
            corner_radius=0, border_width=0,
        )
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_propagate(False)
        ctk.CTkLabel(
            self.sidebar, text="◈  " + self.t.t("app_title") + " ⌄", text_color=c["text"],
            font=self._font(17, True), anchor=self._anchor,
        ).pack(fill="x", padx=16, pady=(20, 14))
        for icon, label, callback in (
            ("✎", self.t.t("new_chat"), self._new_chat),
            ("⌂", self.t.t("nav_projects"), self._choose_project),
            ("◷", self.t.t("nav_scheduled"), lambda: self._open_settings_page("macros")),
            ("⬡", self.t.t("tool_plugins"), lambda: self._open_settings_page("plugins")),
            ("◎", self.t.t("nav_explore"), lambda: self._open_settings_page("skills")),
        ):
            ctk.CTkButton(
                self.sidebar, text=f"{icon}  {label}", command=callback,
                height=34, corner_radius=7, fg_color="transparent", hover_color=c["panel_hi"],
                text_color=c["dim"], font=self._font(12), anchor=self._anchor,
            ).pack(fill="x", padx=8, pady=1)
        ctk.CTkLabel(
            self.sidebar, text=self.t.t("recent_chats"), text_color=c["faint"],
            font=self._font(11, True), anchor=self._anchor,
        ).pack(fill="x", padx=18, pady=(24, 8))
        self.session_list = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        self.session_list.pack(fill="both", expand=True, padx=8)
        self._refresh_session_list()
        ctk.CTkButton(
            self.sidebar, text="♬  " + self.t.t("voice"), command=self._toggle_voice,
            height=34, corner_radius=8, fg_color="transparent", hover_color=c["panel_hi"],
            text_color=c["dim"], font=self._font(12), anchor=self._anchor,
        ).pack(fill="x", padx=10, pady=(2, 0))
        ctk.CTkButton(
            self.sidebar, text="⚙  " + self.t.t("settings"), command=self._open_settings,
            height=38, corner_radius=8, fg_color="transparent", hover_color=c["panel_hi"],
            text_color=c["dim"], font=self._font(12), anchor=self._anchor,
        ).pack(fill="x", padx=10, pady=(4, 14))

        self.main = ctk.CTkFrame(self.root, fg_color=c["bg"], corner_radius=0)
        self.main.grid(row=0, column=1, sticky="nsew")
        self.main.grid_rowconfigure(1, weight=1)
        self.main.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(self.main, height=64, fg_color=c["bg"], corner_radius=0,
                              border_width=1, border_color=c["border"])
        header.grid(row=0, column=0, sticky="ew")
        header.grid_propagate(False)
        ctk.CTkLabel(
            header, text=self.t.t("workspace_title"), text_color=c["text"],
            font=self._font(16, True), anchor=self._anchor,
        ).pack(side=self._side, padx=20, pady=18)
        badge_side = "left" if self._rtl else "right"
        self.mode_badge = ctk.CTkLabel(
            header, text=self.t.t("coding_auto") if permissions.automatic() else self.t.t("coding_ask"),
            fg_color=c["panel"], text_color=c["dim"],
            corner_radius=8, font=self._font(10), padx=10, pady=5,
        )
        self.mode_badge.pack(side=badge_side, padx=(4, 16), pady=17)
        ctk.CTkButton(
            header, text="⧉  " + self.t.t("share_chat"), command=self._copy_chat,
            width=92, height=30, corner_radius=7, fg_color="transparent",
            hover_color=c["panel_hi"], text_color=c["dim"], font=self._font(11),
        ).pack(side=badge_side, padx=2, pady=17)
        self.activity_label = ctk.CTkLabel(
            header, text="", text_color=c["green"], font=self._font(11, True),
        )
        self.activity_label.pack(side=badge_side, padx=10, pady=17)

        self.stream = ctk.CTkTextbox(
            self.main, fg_color=c["bg"], corner_radius=0,
            wrap="word", activate_scrollbars=True,
            scrollbar_button_color=c["border"],
            scrollbar_button_hover_color=c["dim"],
            font=self._font(14),
        )
        self.stream.grid(row=1, column=0, sticky="nsew", padx=(60, 48), pady=(18, 4))
        self.stream.configure(state="disabled")  # للقراءة بس — المستخدم بيكتب في self.entry
        _attach_readonly_textbox_shortcuts(self.stream)
        self._tag_cache: set = set()

        bottom = ctk.CTkFrame(self.main, fg_color=c["bg"], corner_radius=0)
        bottom.grid(row=2, column=0, sticky="ew", padx=(60, 48), pady=(4, 18))

        # صندوق الإدخال — حد رفيع وزوايا شبه مربعة، زي إطار الطرفية
        box = ctk.CTkFrame(
            bottom, fg_color=c["panel"], corner_radius=14,
            border_width=1, border_color=c["border"],
        )
        box.pack(fill="x")

        self.prompt_mark = ctk.CTkLabel(
            box, text="✦", width=22, text_color=c["accent"], font=self._font(15, True),
        )
        self.prompt_mark.pack(side=self._side, padx=(12, 2), pady=8)

        send_side = "left" if self._rtl else "right"
        self.send_button = ctk.CTkButton(
            box, text="➤", command=self._send, width=38, height=38,
            corner_radius=19, fg_color="#2463b4", hover_color="#3478d4",
            text_color="#ffffff", font=self._font(15, True),
        )
        self.send_button.pack(side=send_side, padx=7, pady=7)

        self.talk_button = ctk.CTkButton(
            box, text="🎙", command=self._listen,
            width=38, height=38, corner_radius=19, fg_color="transparent",
            hover_color=c["panel_hi"], text_color=c["text"], font=self._font(16, True),
        )
        self.talk_button.pack(side=send_side, padx=(0, 2), pady=7)

        self.entry = ctk.CTkEntry(
            box, fg_color="transparent", border_width=0, height=46,
            font=self._font(14), text_color=c["text"], placeholder_text=self.t.t("input_placeholder"),
            placeholder_text_color=c["faint"], justify=self._justify,
        )
        self.entry.pack(side=self._side, fill="x", expand=True, padx=(2, 10), pady=4)
        self.entry.bind("<Return>", lambda e: self._send())
        _attach_entry_shortcuts(self.entry)
        self.entry.focus_set()

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
            ("🎤", self._listen, "mic"), ("📎", self._attach_file, "attach"),
        ):
            b = ctk.CTkButton(
                tools, text=glyph, width=26, height=22, corner_radius=4,
                fg_color="transparent", hover_color=c["panel_hi"],
                text_color=c["dim"], font=self._font(12), command=cb,
            )
            b.pack(side=opposite, padx=2)
            b._key = key
            self.tool_btns.append(b)

        # Codex-style outputs rail: generated work, sources and tools stay visible.
        self.tools_panel = ctk.CTkFrame(
            self.root, width=300, fg_color=c["panel"], corner_radius=18,
            border_width=1, border_color=c["border"],
        )
        self.tools_panel.grid(row=0, column=2, sticky="nsew", padx=(0, 12), pady=12)
        self.tools_panel.grid_propagate(False)
        output_head = ctk.CTkFrame(self.tools_panel, fg_color="transparent")
        output_head.pack(fill="x", padx=12, pady=(14, 4))
        ctk.CTkLabel(
            output_head, text=self.t.t("outputs"), text_color=c["text"],
            font=self._font(16, True), anchor=self._anchor,
        ).pack(side=self._side, padx=4)
        ctk.CTkButton(
            output_head, text="＋", command=lambda: self._seed_prompt(
                "اعمل ملف جديد " if self._rtl else "Create a new file "),
            width=30, height=28, corner_radius=6, fg_color="transparent",
            hover_color=c["panel_hi"], text_color=c["dim"], font=self._font(15),
        ).pack(side="left" if self._rtl else "right")
        ctk.CTkLabel(
            self.tools_panel, text=self.t.t("create_output"), text_color=c["faint"],
            font=self._font(10), anchor=self._anchor, wraplength=210,
        ).pack(fill="x", padx=16, pady=(0, 14))
        ctk.CTkButton(
            self.tools_panel, text="＋  " + self.t.t("create_output"),
            command=lambda: self._seed_prompt("اعمل فيديو احترافي عن " if self._rtl else "Create a professional video about "),
            height=40, corner_radius=8, fg_color="transparent", hover_color=c["panel_hi"],
            border_width=1, border_color=c["border"], text_color=c["dim"],
            font=self._font(11), anchor=self._anchor,
        ).pack(fill="x", padx=12, pady=(0, 12))
        ctk.CTkLabel(self.tools_panel, text=self.t.t("sources"), text_color=c["text"],
                     font=self._font(12, True), anchor=self._anchor).pack(fill="x", padx=16, pady=(3, 2))
        ctk.CTkLabel(self.tools_panel, text=self.t.t("sources_empty"), text_color=c["faint"],
                     font=self._font(10), anchor=self._anchor, wraplength=250,
                     justify=self._justify).pack(fill="x", padx=16, pady=(0, 12))
        for section, entries in (
            (self.t.t("tool_files"), (("📎", "attach", self._attach_file), ("🛡", "scan", self._scan_file))),
            (self.t.t("tool_voice"), (("🎤", "mic", self._listen), ("🔊", "voices", lambda: self._open_settings_page("voices")))),
            (self.t.t("tool_workspace"), (("🩺", "repair", self._repair), ("🔌", "connectors", lambda: self._open_settings_page("connectors")), ("🧩", "plugins", lambda: self._open_settings_page("plugins")), ("⚡", "skills", lambda: self._open_settings_page("skills")))),
        ):
            ctk.CTkLabel(self.tools_panel, text=section, text_color=c["faint"],
                         font=self._font(10, True), anchor=self._anchor).pack(fill="x", padx=16, pady=(8, 4))
            for icon, key, callback in entries:
                ctk.CTkButton(
                    self.tools_panel, text=f"{icon}  {self.t.t('tool_' + key)}", command=callback,
                    height=38, corner_radius=8, fg_color="transparent", hover_color=c["panel_hi"],
                    text_color=c["dim"], font=self._font(12), anchor=self._anchor,
                ).pack(fill="x", padx=8, pady=1)

        self._refresh_status()

    def _refresh_session_list(self):
        if not hasattr(self, "session_list"):
            return
        for child in self.session_list.winfo_children():
            child.destroy()
        rows = sessions.list_all()[:9]
        if not rows:
            ctk.CTkLabel(self.session_list, text=self.t.t("no_sessions"), text_color=self.c["faint"],
                         font=self._font(10), anchor=self._anchor).pack(fill="x", padx=10)
            return
        for item in rows:
            title = item.get("title") or self.t.t("untitled")
            ctk.CTkButton(
                self.session_list, text="◌  " + title[:28],
                command=lambda sid=item["id"]: self._open_saved_session(sid),
                height=34, corner_radius=7, fg_color="transparent", hover_color=self.c["panel_hi"],
                text_color=self.c["dim"], font=self._font(11), anchor=self._anchor,
            ).pack(fill="x", pady=1)

    def _open_saved_session(self, session_id: str):
        messages = sessions.load(session_id)
        if messages is not None:
            self._resume_session(session_id, messages)

    def _open_settings_page(self, page: str):
        self._open_settings()
        if self._settings is not None:
            self._settings.page = page
            self._settings.cursor = 0
            self._settings._build()

    def _choose_project(self):
        path = filedialog.askdirectory(title=self.t.t("pick_dir"))
        if path:
            self._add_user(f"⌂ {path}")
            self._last_command_name = "project"
            self._show_thinking()
            self.engine.submit(f"project {shlex.quote(path)}")

    def _copy_chat(self):
        try:
            content = self.stream.get("1.0", "end-1c").strip()
        except Exception:
            content = ""
        if content:
            self.clipboard_clear()
            self.clipboard_append(content)
            self._activity = "ready"
            self._refresh_status()

    def _seed_prompt(self, text: str):
        self.entry.delete(0, "end")
        self.entry.insert(0, text)
        self.entry.focus_set()

    # ── أسطر المحادثة ──────────────────────────────────────────────────
    def _stream_tag(self, color: str, size: int, bold: bool) -> str:
        """بيرجع اسم تاج بلون/حجم/تخانة معينين، وبيعرّفه أول مرة بس."""
        name = f"c_{color.lstrip('#')}_{size}_{int(bold)}"
        if name not in self._tag_cache:
            text = self.stream._textbox
            text.tag_configure(
                name, foreground=color, font=self._font(size, bold),
                justify="right" if self._rtl else "left",
                lmargin1=4, lmargin2=4, spacing1=1, spacing3=1,
            )
            self._tag_cache.add(name)
        return name

    def _line(self, glyph: str, text: str, color: str, *,
              indent: int = 0, size: int = 13, bold: bool = False):
        """سطر واحد في شريط المحادثة: علامة + نص، متحدد وقابل للنسخ."""
        pad = 4 + indent * 16
        name = f"c_{color.lstrip('#')}_{size}_{int(bold)}_i{indent}"
        if name not in self._tag_cache:
            text_widget = self.stream._textbox
            text_widget.tag_configure(
                name, foreground=color, font=self._font(size, bold),
                justify="right" if self._rtl else "left",
                lmargin1=pad, lmargin2=pad, spacing1=2, spacing3=2,
            )
            self._tag_cache.add(name)

        body = text if len(text) <= MAX_CHARS else text[:MAX_CHARS] + "\n…"
        rendered = f"{glyph}  {body}" if glyph else body

        self.stream.configure(state="normal")
        start = self.stream.index("end-1c")
        self.stream.insert("end", rendered + "\n", name)
        self.stream.configure(state="disabled")
        self._rows.append((glyph, body, color))
        if len(self._rows) > MAX_ROWS:
            del self._rows[:len(self._rows) - MAX_ROWS]
        self._trim_stream()
        self.after(20, self._scroll_bottom)
        return start  # مرجع نصي (index) للسطر ده — يستخدم مع _show_thinking/_hide_thinking

    def _blank(self, height: int = 6):
        self.stream.configure(state="normal")
        self.stream.insert("end", "\n")
        self.stream.configure(state="disabled")

    def _trim_stream(self):
        """بيقص الأسطر القديمة جدًا لو عدّت سقف معقول، عشان الذاكرة."""
        text = self.stream._textbox
        total = int(text.index("end-1c").split(".")[0])
        if total > MAX_STREAM_LINES:
            over = total - MAX_STREAM_LINES
            self.stream.configure(state="normal")
            self.stream.delete("1.0", f"{over + 1}.0")
            self.stream.configure(state="disabled")

    def _clear_stream(self):
        self.stream.configure(state="normal")
        self.stream.delete("1.0", "end")
        self.stream.configure(state="disabled")
        self._rows.clear()

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
        self.stream.see("end")

    def _show_thinking(self):
        if self._thinking is None:
            self.stream.configure(state="normal")
            self._thinking_start = self.stream.index("end-1c")
            self.stream.mark_set("thinking_start", self._thinking_start)
            self.stream.mark_gravity("thinking_start", "left")
            self.stream.configure(state="disabled")
            self._thinking = self._line("", self.t.t("activity_thinking"), self.c["faint"], indent=1, size=12)

    def _hide_thinking(self):
        if self._thinking is not None:
            self.stream.configure(state="normal")
            try:
                self.stream.delete("thinking_start", "thinking_start + 1 line")
            except Exception:
                pass  # لو الـ mark راح لأي سبب، مفيش حاجة نشيلها
            self.stream.configure(state="disabled")
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
        parts.append(self.engine.project_dir.name)
        if self.engine.coding_mode == "plan":
            parts.append(self.t.t("coding_plan"))
        else:
            parts.append(self.t.t("coding_auto") if permissions.automatic() else self.t.t("coding_ask"))
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
        if permissions.automatic():
            parts.append(self.t.t("mode_auto"))
        if self._plugin_count:
            parts.append(self.t.t("plugins_loaded", n=self._plugin_count))
        self.status_label.configure(text=f"{GLYPH_STATUS}  " + "  ·  ".join(parts))
        if hasattr(self, "activity_label"):
            key = f"activity_{self._activity}"
            self.activity_label.configure(text="●  " + self.t.t(key))
        if hasattr(self, "mode_badge"):
            self.mode_badge.configure(
                text=self.t.t("coding_plan") if self.engine.coding_mode == "plan"
                else (self.t.t("coding_auto") if permissions.automatic()
                      else self.t.t("coding_ask"))
            )

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
        elif cmd in ("clear", "new"):
            self._new_chat()
        elif cmd == "cancel":
            self.engine.cancel()
            self._hide_thinking()
        elif cmd in ("plan", "code"):
            self.engine.submit("mode plan" if cmd == "plan" else "mode ask")
        elif cmd == "project":
            path = filedialog.askdirectory(title=self.t.t("pick_dir"))
            if path:
                self.engine.submit(f"project {shlex.quote(path)}")
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
        self._clear_stream()
        self._thinking = None
        self.engine.new_session(session_id, messages)
        self._line("✻", self.t.t("resumed"), self.c["accent"], size=13, bold=True)
        self._blank(8)
        for msg in messages:
            if msg.get("role") == "user":
                self._add_user(msg.get("content", ""))
            else:
                self._add_assistant(msg.get("content", ""))

    def _new_chat(self):
        self._clear_stream()
        self._thinking = None
        self.engine.new_session()
        self._banner()
        self._refresh_session_list()

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
        # Pressing the conversation microphone implies a two-way voice session.
        # Keep voice enabled so the assistant reads its answer back automatically.
        self.voice_enabled = True
        self._refresh_status()
        self._add_user("🎤 …")
        self._last_command_name = "listen_run"
        self._show_thinking()
        self.engine.submit("listen_run")

    def _repair(self):
        self._add_user("🩺 " + self.t.t("tool_repair"))
        self._last_command_name = "self_repair"
        self._show_thinking()
        self.engine.submit("self_repair")

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
        self._thinking = None
        self._build()
        self._banner()

    def _speak(self, text: str):
        text = text.rpartition("\n— ")[0] if "\n— " in text else text
        snippet = " ".join(text.split()).replace('"', "").replace("'", "")
        # Short conversational turns begin speaking much sooner and feel more
        # natural than waiting to synthesize a long formatted answer.
        if len(snippet) > 180:
            cut = max(snippet.rfind(mark, 0, 180) for mark in (".", "!", "?", "؟", "،"))
            snippet = snippet[:cut + 1] if cut >= 60 else snippet[:180] + "..."
        if snippet:
            self._last_command_name = "speak"
            self.engine.submit(f"speak {snippet}")

    def _on_close(self):
        self.engine.shutdown()
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
        is_final_model_reply = "\n— " in msg and not any(
            marker in msg for marker in ("🔧", "↪", "اكتب y", "write y", "❓")
        )
        if level == "info" and self.voice_enabled and is_final_model_reply and \
                self._last_command_name not in ("speak", "voice_status"):
            self._safe_after(self._speak, msg)

    def _render_log(self, msg: str, level: str):
        # تحميل الإضافات بيطبع عشرات الأسطر عند كل تشغيل — بيتعدّوا في
        # سطر الحالة بدل ما يغرقوا أول شاشة. النص الكامل في log_history.
        if level == "ok" and "plugin loaded:" in msg:
            self._plugin_count = len(self.engine._loaded_plugins)
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
        self._activity = status
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
        "macros", "sessions", "permissions", "hooks", "interface", "voices",
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
            {"kind": "goto", "label": self._tr("page_voices"), "page": "voices",
             "value": f"{cfg.get('human_voice_speaker', 'Omnia')} · {cfg.get('english_voice_voice', 'af_heart')}"},
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
        items.append({"kind": "cmd", "label": self._tr("mcp_doctor"),
                      "cmd": "connectors doctor", "value": ""})
        for preset in ("github", "gmail", "canva"):
            if preset not in configured:
                items.append({"kind": "cmd", "label": self._tr("mcp_add", name=preset),
                              "cmd": f"connectors add {preset}", "value": ""})
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
        items.append({"kind": "cmd", "label": self._tr("plugin_doctor"),
                      "cmd": "plugin_doctor", "value": ""})
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
            {"kind": "toggle", "label": self._tr("automatic_actions"),
             "cfg": "auto_approve",
             "value": self._tr("on") if permissions.automatic() else self._tr("off"),
             "note": self._tr("automatic_actions_note")},
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
            {"kind": "goto", "label": self._tr("page_voices"), "page": "voices", "value": "›"},
            {"kind": "head", "label": self._tr("sec_ui_commands")},
            {"kind": "info", "label": "/settings /clear /theme /voice /lang /quit",
             "value": ""},
        ]

    def _page_voices(self) -> list[dict]:
        cfg = brain.load_config()
        arabic = cfg.get("human_voice_speaker", "Omnia")
        english = cfg.get("english_voice_voice", "af_heart")
        items = [
            {"kind": "head", "label": self._tr("arabic_voices")},
            {"kind": "info", "label": self._tr("voice_ar_note"), "value": ""},
        ]
        for name in ("Omnia", "Asmaa", "Hanan", "Yasmin", "Esraa", "Sarah"):
            items.append({"kind": "voice_choice", "label": name,
                          "cfg": "human_voice_speaker", "choice": name,
                          "value": "✓" if name == arabic else ""})
        items.append({"kind": "voice_preview", "label": self._tr("voice_preview_ar"),
                      "lang": "ar", "value": "▶"})
        items.extend([
            {"kind": "head", "label": self._tr("english_voices")},
            {"kind": "info", "label": self._tr("voice_en_note"), "value": ""},
        ])
        english_names = (
            ("af_heart", "Heart · US"), ("af_bella", "Bella · US"),
            ("af_nova", "Nova · US"), ("af_sarah", "Sarah · US"),
            ("af_sky", "Sky · US"), ("af_nicole", "Nicole · US"),
            ("bf_emma", "Emma · UK"), ("bf_isabella", "Isabella · UK"),
            ("bf_alice", "Alice · UK"), ("bf_lily", "Lily · UK"),
        )
        for value, label in english_names:
            items.append({"kind": "voice_choice", "label": label,
                          "cfg": "english_voice_voice", "choice": value,
                          "value": "✓" if value == english else ""})
        items.append({"kind": "voice_preview", "label": self._tr("voice_preview_en"),
                      "lang": "en", "value": "▶"})
        return items

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
        _attach_entry_shortcuts(self.editing)
        self.editing.focus_set()

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
        elif kind == "voice_choice":
            cfg = brain.load_config()
            cfg[item["cfg"]] = item["choice"]
            brain.save_config(cfg)
        elif kind == "voice_preview":
            sample = ("أهلاً، أنا نيزوكو. هساعدك بهدوء وبصوت مصري طبيعي."
                      if item["lang"] == "ar" else
                      "Hi, I'm Nezuko. I'll help you calmly, naturally, and one step at a time.")
            self.app.engine.submit(f"speak {sample} lang={item['lang']}")
            self.close()
            return
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
