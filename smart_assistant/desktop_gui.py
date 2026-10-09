"""Native Unicode chat surface. Qt shapes Arabic and handles bidi before wrapping.

The assistant, tools and voice workers stay in core_engine; this module only
marshals their events to the GUI thread. No reshaping or visual-order storage.
"""
from __future__ import annotations

import pathlib
import shlex
import sys
import threading
import time
import unicodedata

from PySide6.QtCore import Qt, QObject, Signal, QTimer, QUrl
from PySide6.QtGui import (QAction, QColor, QDesktopServices, QFont, QKeySequence,
                          QTextBlockFormat, QTextCursor, QTextDocument)
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog,
    QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QPushButton,
    QScrollArea, QSizePolicy, QSpinBox, QSplitter, QTextBrowser, QTextEdit,
    QVBoxLayout, QWidget)

import brain
import companion
import sessions
import theme
from core_engine import AssistantEngine
from version import __version__


def paragraph_direction(text: str):
    """First strong character controls the paragraph; embedded English stays LTR."""
    for char in text:
        direction = unicodedata.bidirectional(char)
        if direction in {"R", "AL"}:
            return Qt.LayoutDirection.RightToLeft
        if direction == "L":
            return Qt.LayoutDirection.LeftToRight
    return Qt.LayoutDirection.LayoutDirectionAuto


def readable_blocks(document, *, spacing=True):
    block = document.begin()
    while block.isValid():
        cursor = QTextCursor(block)
        fmt = block.blockFormat()
        fmt.setLayoutDirection(paragraph_direction(block.text()))
        # Code blocks must retain their native monospaced formatting/alignment.
        if not fmt.nonBreakableLines():
            fmt.setAlignment(Qt.AlignmentFlag.AlignRight if paragraph_direction(block.text()) ==
                             Qt.LayoutDirection.RightToLeft else Qt.AlignmentFlag.AlignLeft)
        if spacing:
            fmt.setLineHeight(145, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
            fmt.setBottomMargin(10)
        cursor.setBlockFormat(fmt)
        block = block.next()


class Composer(QTextEdit):
    submitted = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptRichText(False)
        self.setFixedHeight(86)
        self.setPlaceholderText("اكتب أو اتكلم مع نيزكو…  /  Ask Nezuko anything…")
        self.setAccessibleName("Message Nezuko")

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (
                event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            self.submitted.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class MessageText(QTextBrowser):
    """Native selection/copy and Markdown, with no external image loading."""
    def __init__(self, text, font, *, markdown=False, parent=None):
        super().__init__(parent)
        self.raw = text
        self.setFont(font)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.document().setDocumentMargin(4)
        # Disable raw HTML in Markdown; source content cannot inject UI elements.
        if markdown:
            self.document().setMarkdown(text, QTextDocument.MarkdownFeature.MarkdownNoHTML)
        else:
            self.setPlainText(text)
        readable_blocks(self.document())
        self.document().documentLayout().documentSizeChanged.connect(self.fit)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.anchorClicked.connect(self.open_link)
        self.fit()

    def loadResource(self, kind, url):
        # Markdown images are data, not authority to read files or make requests.
        return None

    def open_link(self, url):
        if url.scheme() in {"https", "http"}:
            QDesktopServices.openUrl(url)

    def fit(self, *_):
        self.setFixedHeight(max(38, int(self.document().size().height()) + 10))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.document().setTextWidth(max(40, self.viewport().width()))
        self.fit()


class Events(QObject):
    log = Signal(str, str)
    status = Signal(str)
    health = Signal(bool)
    pick = Signal(object, object)
    preview = Signal(str, int)


class Desktop(QMainWindow):
    def __init__(self, *, start_engine=True):
        super().__init__()
        cfg = brain.load_config()
        if not companion.enabled(cfg):
            cfg = companion.activate(cfg)
            brain.save_config(cfg)
        self.ar = cfg.get("ui_lang") == "ar"
        self.mode = cfg.get("ui_theme", "dark")
        self.text_size = max(16, min(26, int(cfg.get("chat_font_size", 19))))
        self.messages = []
        self.cards = []
        self.preview_browser = None
        self.closed = False
        self.activity = "starting"
        self.health = "loading"
        self.voice = False
        self.continuous = False
        self.tts_pending = False
        self.voice_ready_since = 0.0
        self.last_command = ""
        self.dialog_open = False
        self.events = Events(self)
        self.events.log.connect(self.render_log)
        self.events.status.connect(self.set_status)
        self.events.health.connect(self.brain_ready)
        self.events.pick.connect(self.pick_file)
        self.events.preview.connect(self.show_preview)
        self.engine = AssistantEngine(on_log=self.events.log.emit,
                                      on_status=self.events.status.emit)
        self.engine._voice_cancel = threading.Event()
        self.engine.on_preview = self.events.preview.emit
        self.engine.on_need_file = self.events.pick.emit
        self.setWindowTitle("Nezuko · " + __version__)
        self.resize(1480, 900)
        self.setMinimumSize(980, 640)
        self.build()
        self.apply_theme()
        self.refresh_sessions()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.voice_tick)
        self.timer.start(300)
        if start_engine:
            self.engine.start()
            brain.prewarm_local_async(self.events.health.emit)
        else:
            self.activity = "ready"
        self.update_status()

    def tr_pair(self, en, ar):
        return ar if self.ar else en

    def button(self, text, callback, layout, *, name=None):
        button = QPushButton(text)
        if name:
            button.setObjectName(name)
        button.clicked.connect(callback)
        layout.addWidget(button)
        return button

    def build(self):
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.setCentralWidget(self.splitter)
        self.sidebar = QWidget()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setMinimumWidth(190)
        self.sidebar.setMaximumWidth(280)
        left = QVBoxLayout(self.sidebar)
        left.setContentsMargins(14, 22, 14, 16)
        brand = QLabel("Nezuko  ⌄")
        brand.setObjectName("brand")
        left.addWidget(brand)
        self.button(self.tr_pair("＋  New chat", "＋  محادثة جديدة"), self.new_chat, left)
        for en, ar, cmd in (("Projects", "المشاريع", "project"),
                            ("Scheduled", "المهام المجدولة", "schedule list"),
                            ("Connectors", "المنصات المتصلة", "connectors list"),
                            ("Skills", "المهارات", "skills")):
            self.button(self.tr_pair(en, ar), lambda _=False, c=cmd: self.command(c), left)
        self.button(self.tr_pair("Tools & plugins", "الأدوات والإضافات"), self.tools_dialog, left)
        recent = QLabel(self.tr_pair("Recent chats", "المحادثات السابقة"))
        recent.setObjectName("muted")
        left.addWidget(recent)
        self.recent = QListWidget()
        self.recent.itemClicked.connect(self.resume)
        left.addWidget(self.recent, 1)
        self.button(self.tr_pair("Voice library", "مكتبة الأصوات"), self.settings, left)
        self.button(self.tr_pair("⚙  Settings", "⚙  الإعدادات"), self.settings, left)
        self.splitter.addWidget(self.sidebar)

        self.main = QWidget()
        center = QVBoxLayout(self.main)
        center.setContentsMargins(28, 16, 28, 18)
        header = QHBoxLayout()
        self.title = QLabel(self.tr_pair("Nezuko workspace", "مساحة نيزكو"))
        header.addWidget(self.title)
        header.addStretch()
        self.state_label = QLabel()
        self.state_label.setObjectName("muted")
        header.addWidget(self.state_label)
        self.button(self.tr_pair("Copy chat", "نسخ المحادثة"), self.copy_chat, header)
        self.conversation = self.button(self.tr_pair("Start conversation", "ابدأ محادثة صوتية"),
                                        self.toggle_conversation, header)
        center.addLayout(header)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.transcript = QWidget()
        self.transcript.setMaximumWidth(900)
        self.transcript_layout = QVBoxLayout(self.transcript)
        self.transcript_layout.setContentsMargins(18, 28, 18, 18)
        self.transcript_layout.setSpacing(20)
        self.transcript_layout.addStretch()
        self.scroll.setWidget(self.transcript)
        self.scroll.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        center.addWidget(self.scroll, 1)
        self.progress = QLabel()
        self.progress.setObjectName("muted")
        self.progress.setWordWrap(True)
        center.addWidget(self.progress)
        composer = QFrame()
        composer.setObjectName("composer")
        composer_layout = QVBoxLayout(composer)
        composer_layout.setContentsMargins(12, 8, 12, 8)
        self.entry = Composer()
        self.entry.submitted.connect(self.send)
        composer_layout.addWidget(self.entry)
        controls = QHBoxLayout()
        self.button("＋", self.attach_file, controls)
        controls.addStretch()
        self.brain_label = QLabel("Nezuko · Local")
        self.brain_label.setObjectName("muted")
        controls.addWidget(self.brain_label)
        self.mic = self.button("🎙", self.listen, controls)
        self.mic.setToolTip(self.tr_pair("Speak and receive a voice reply", "اتكلم واستقبل رد صوتي"))
        self.button("➤", self.send, controls, name="send")
        composer_layout.addLayout(controls)
        center.addWidget(composer)
        hint = QLabel(self.tr_pair("Enter send · Shift+Enter new line · Ctrl+Enter send · Ctrl+S save",
                                    "Enter إرسال · Shift+Enter سطر جديد · Ctrl+Enter إرسال · Ctrl+S حفظ"))
        hint.setObjectName("hint")
        center.addWidget(hint)
        self.splitter.addWidget(self.main)

        self.tools = QWidget()
        self.tools.setObjectName("tools")
        self.tools.setMinimumWidth(220)
        self.tools.setMaximumWidth(300)
        right = QVBoxLayout(self.tools)
        right.setContentsMargins(18, 24, 18, 18)
        right.addWidget(QLabel(self.tr_pair("Outputs", "النتائج")))
        self.button(self.tr_pair("Create a file or video", "إنشاء ملف أو فيديو"),
                    lambda: self.seed(self.tr_pair("Help me make a video", "ساعديني أعمل فيديو")), right)
        self.button(self.tr_pair("Open outputs folder", "فتح مجلد النتائج"), self.open_outputs, right)
        right.addWidget(QLabel(self.tr_pair("Sources", "المصادر")))
        self.sources = QListWidget()
        self.sources.setMaximumHeight(140)
        right.addWidget(self.sources)
        for en, ar, callback in (("Attach file", "إرفاق ملف", self.attach_file),
            ("Repair Nezuko", "إصلاح نيزكو", lambda: self.command("self_repair")),
            ("Tools & plugins", "الأدوات والإضافات", self.tools_dialog),
            ("Memory", "الذاكرة", self.memory_dialog),
            ("Connectors", "المنصات المتصلة", lambda: self.command("connectors list"))):
            self.button(self.tr_pair(en, ar), callback, right)
        right.addStretch()
        right.addWidget(QLabel(self.tr_pair("One local brain · No subscription", "عقل محلي واحد · بدون اشتراك")))
        self.splitter.addWidget(self.tools)
        self.splitter.setSizes([220, 980, 280])
        self.splitter.setCollapsible(1, False)
        self.add_menu()

    def add_menu(self):
        file_menu = self.menuBar().addMenu(self.tr_pair("File", "ملف"))
        edit_menu = self.menuBar().addMenu(self.tr_pair("Edit", "تحرير"))
        view_menu = self.menuBar().addMenu(self.tr_pair("View", "عرض"))
        actions = ((file_menu, "New chat", "Ctrl+N", self.new_chat),
                   (file_menu, "Save chat", "Ctrl+S", self.save_chat),
                   (file_menu, "Export chat", "Ctrl+Shift+S", self.export_chat),
                   (edit_menu, "Settings", "Ctrl+,", self.settings),
                   (edit_menu, "Focus composer", "Ctrl+L", self.entry.setFocus),
                   (view_menu, "Larger text", "Ctrl+=", lambda: self.resize_text(1)),
                   (view_menu, "Smaller text", "Ctrl+-", lambda: self.resize_text(-1)),
                   (view_menu, "Sidebar", "Ctrl+B", lambda: self.sidebar.setVisible(not self.sidebar.isVisible())),
                   (view_menu, "Tools", "Ctrl+Shift+O", lambda: self.tools.setVisible(not self.tools.isVisible())))
        for menu, text, shortcut, callback in actions:
            action = QAction(text, self)
            action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(callback)
            menu.addAction(action)

    def apply_theme(self):
        c = theme.palette(self.mode)
        font = QFont("Segoe UI", 10)
        font.setPixelSize(15)
        self.setFont(font)
        self.setStyleSheet(f"""
            QMainWindow, QWidget {{background:{c['bg']};color:{c['text']};font-family:'Segoe UI';}}
            QLabel {{background:transparent;}}
            QWidget#sidebar {{background:{c['panel']};}}
            QWidget#tools {{background:{c['panel']};border-left:1px solid {c['border']};}}
            QLabel#brand {{font-size:21px;font-weight:600;padding-bottom:14px;}}
            QLabel#muted {{color:{c['dim']};font-size:13px;}}
            QLabel#hint {{color:{c['faint']};font-size:12px;}}
            QFrame#composer {{background:{c['panel_hi']};border:1px solid {c['border']};border-radius:18px;}}
            QTextEdit, QTextBrowser {{border:0;background:transparent;selection-background-color:#285c92;}}
            QPushButton {{background:transparent;border:0;border-radius:8px;padding:9px 10px;text-align:left;}}
            QPushButton:hover {{background:{c['panel_hi']};}}
            QPushButton#send {{background:#2864b7;color:white;border-radius:18px;text-align:center;min-width:28px;}}
            QListWidget {{border:0;background:transparent;outline:0;}}
            QListWidget::item {{padding:9px;border-radius:7px;}}
            QListWidget::item:selected {{background:{c['panel_hi']};}}
            QLineEdit,QComboBox,QSpinBox {{background:{c['panel_hi']};border:1px solid {c['border']};padding:7px;border-radius:6px;}}
            QScrollBar:vertical {{background:transparent;width:8px;}}
            QScrollBar::handle:vertical {{background:{c['border']};border-radius:4px;min-height:30px;}}
            QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical {{height:0;}}
        """)
        text_font = QFont("Segoe UI")
        text_font.setPixelSize(self.text_size)
        self.entry.setFont(text_font)
        for card, browser in self.cards:
            browser.setFont(text_font)
            browser.document().setDefaultFont(text_font)
            browser.fit()

    def resize_text(self, delta):
        self.text_size = max(16, min(26, self.text_size + delta))
        cfg = brain.load_config()
        cfg["chat_font_size"] = self.text_size
        brain.save_config(cfg)
        self.apply_theme()

    def add_message(self, role, text, *, level="info", record=True):
        if record:
            self.messages.append((role, text))
        card = QFrame()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 10, 14, 12)
        if role == "user":
            card.setStyleSheet(f"QFrame {{background:{theme.palette(self.mode)['panel_hi']};border-radius:14px;}}")
        head = QHBoxLayout()
        label = QLabel(self.tr_pair("You", "أنت") if role == "user" else
                       self.tr_pair("Activity", "النشاط") if role == "tool" else "Nezuko")
        label.setObjectName("muted")
        head.addWidget(label)
        head.addStretch()
        self.button(self.tr_pair("Copy", "نسخ"), lambda: QApplication.clipboard().setText(text), head)
        layout.addLayout(head)
        font = QFont("Segoe UI")
        font.setPixelSize(self.text_size if role != "tool" else self.text_size - 2)
        browser = MessageText(text, font, markdown=role == "assistant")
        if level == "error":
            browser.setStyleSheet("color:#ef8585;")
        layout.addWidget(browser)
        self.transcript_layout.insertWidget(self.transcript_layout.count()-1, card)
        self.cards.append((card, browser))
        # Bound long-running chat memory while retaining the saved session on disk.
        if len(self.cards) > 300:
            old, _ = self.cards.pop(0)
            old.deleteLater()
            self.messages = self.messages[-300:]
        QTimer.singleShot(20, self.scroll_bottom)

    def scroll_bottom(self):
        self.scroll.verticalScrollBar().setValue(self.scroll.verticalScrollBar().maximum())

    def seed(self, text):
        self.entry.setPlainText(text)
        self.entry.setFocus()

    def send(self):
        text = self.entry.toPlainText().strip()
        if not text:
            return
        if text == "/settings":
            self.entry.clear()
            self.settings()
            return
        if text == "/clear":
            self.entry.clear()
            self.new_chat()
            return
        self.entry.clear()
        self.command(text)

    def command(self, text):
        self.add_message("user", text)
        self.last_command = text.split(maxsplit=1)[0] if text else ""
        self.activity = "thinking"
        self.update_status()
        self.engine.submit(text)

    def render_log(self, text, level):
        if self.closed:
            return
        if "plugin loaded:" in text or text.startswith("🔊 spoken with"):
            return
        self.clear_preview()
        if "voice recording cancelled" in text or (self.continuous and "did not hear clear speech" in text):
            return
        if text.startswith(("🎤 سمعتك:", "🎤 I heard:")):
            self.add_message("user", text.splitlines()[0].split(":", 1)[1].strip())
            return
        final = "\n— " in text and not any(m in text for m in ("🔧", "↪", "اكتب y", "write y", "❓"))
        body = text.rpartition("\n— ")[0] if "\n— " in text else text
        tool = body.lstrip().startswith("↪") or self.last_command == "speak"
        self.add_message("tool" if tool else "assistant", body.strip(), level=level)
        if final and level == "info" and self.voice and self.last_command not in {"speak", "voice_status"}:
            self.speak(body)
        elif level == "error" and self.voice and self.last_command != "speak":
            self.continuous = False
            self.speak(self.tr_pair("I couldn't complete that. The details are in the chat.",
                                    "مقدرتش أكمل الطلب. التفاصيل موجودة في الشات."))
        self.refresh_sessions()
        self.update_status()

    def speak(self, text):
        self.tts_pending = True
        self.last_command = "speak"
        # Keep all words and punctuation, including apostrophes.
        chunk = ""
        for word in text.split():
            if len(chunk) + len(word) > 240 and chunk:
                self.engine.speak(chunk)
                chunk = ""
            chunk = (chunk + " " + word).strip()
        if chunk:
            self.engine.speak(chunk)

    def listen(self):
        if self.activity != "ready" or not self.engine._queue.empty():
            return
        self.voice = True
        self.engine._voice_cancel.clear()
        self.last_command = "listen_run"
        self.activity = "listening"
        self.update_status()
        self.engine.listen()

    def toggle_conversation(self):
        self.continuous = not self.continuous
        if self.continuous:
            self.voice = True
            self.voice_ready_since = 0
        else:
            self.engine._voice_cancel.set()
        self.update_status()

    def voice_tick(self):
        if self.closed or not self.continuous:
            return
        ready = (self.activity == "ready" and self.health == "ready" and not self.tts_pending
                 and self.engine._queue.empty() and not self.engine._pending_intent
                 and not self.engine._pending_args
                 and not self.dialog_open)
        if ready:
            if not self.voice_ready_since:
                self.voice_ready_since = time.monotonic()
            elif time.monotonic() - self.voice_ready_since > 0.8:
                self.voice_ready_since = 0
                self.listen()
        else:
            self.voice_ready_since = 0

    def set_status(self, status):
        self.activity = status
        if status == "ready" and self.engine._queue.empty():
            self.tts_pending = False
        self.update_status()

    def brain_ready(self, ready):
        self.health = "ready" if ready else "not_ready"
        self.update_status()

    def update_status(self):
        self.state_label.setText(self.tr_pair("● Ready", "● جاهزة") if self.health == "ready" else
                                self.tr_pair("Loading local brain…", "تحميل العقل المحلي…") if self.health == "loading" else
                                self.tr_pair("Local brain needs attention", "العقل المحلي محتاج مراجعة"))
        labels = {"thinking": ("Thinking…", "بفكر…"), "listening": ("Listening…", "بسمعك…"),
                  "transcribing": ("Understanding your speech…", "بفهم كلامك…"),
                  "speaking": ("Speaking…", "بتكلم…"), "reading": ("Reading…", "بقرأ…"),
                  "updating": ("Updating…", "بعدّل…"), "rendering": ("Rendering video…", "بجهز الفيديو…"),
                  "repairing": ("Checking and repairing…", "بفحص وأصلّح…"),
                  "running_tool": ("Running a tool…", "بشغّل أداة…"),
                  "queued": ("Preparing…", "بحضّر…"), "working": ("Working…", "شغالة…"), "ready": ("", "")}
        en, ar = labels.get(self.activity, (self.activity, self.activity))
        self.progress.setText(self.tr_pair(en, ar))
        self.conversation.setText(self.tr_pair("End conversation", "إنهاء المحادثة") if self.continuous else
                                  self.tr_pair("Start conversation", "ابدأ محادثة صوتية"))

    def attach_file(self):
        path, _ = QFileDialog.getOpenFileName(self, self.tr_pair("Attach file", "إرفاق ملف"))
        if path:
            self.sources.addItem(pathlib.Path(path).name)
            self.command("probe " + shlex.quote(path))

    def pick_file(self, spec, callback):
        self.dialog_open = True
        try:
            path = QFileDialog.getExistingDirectory(self, "Choose folder") if spec.kind == "dir" else \
                   QFileDialog.getOpenFileName(self, "Choose file")[0]
            callback(path or "")
        finally:
            self.dialog_open = False

    def new_chat(self):
        self.engine.new_session()
        self.engine._voice_cancel.set()
        self.tts_pending = False
        self.clear_preview()
        for card, _ in self.cards:
            card.deleteLater()
        self.cards.clear()
        self.messages.clear()
        self.entry.clear()
        self.refresh_sessions()

    def show_preview(self, text, generation):
        if self.closed or generation != self.engine._generation:
            return
        if not text:
            self.clear_preview()
            return
        if self.preview_browser is None:
            font = QFont("Segoe UI")
            font.setPixelSize(self.text_size)
            self.preview_browser = MessageText("", font)
            self.transcript_layout.insertWidget(self.transcript_layout.count()-1, self.preview_browser)
        # Draft stays separate from final chat/history/speech until validation.
        self.preview_browser.setPlainText(text)
        readable_blocks(self.preview_browser.document())
        self.preview_browser.fit()
        self.progress.setText(self.tr_pair("Nezuko is writing…", "نيزكو بتكتب…"))
        self.scroll_bottom()

    def clear_preview(self):
        if self.preview_browser is not None:
            self.preview_browser.deleteLater()
            self.preview_browser = None

    def refresh_sessions(self):
        self.recent.clear()
        for entry in sessions.list_all()[:20]:
            item = QListWidgetItem(entry.get("title", "Chat"))
            item.setData(Qt.ItemDataRole.UserRole, entry["id"])
            self.recent.addItem(item)

    def resume(self, item):
        sid = item.data(Qt.ItemDataRole.UserRole)
        messages = sessions.load(sid)
        if messages is None:
            return
        self.new_chat()
        self.engine.new_session(sid, messages)
        for msg in messages:
            if msg["role"] in {"user", "assistant"}:
                self.add_message(msg["role"], msg["content"])

    def markdown(self):
        return "# Nezuko conversation\n\n" + "\n\n".join(
            f"## {role.title()}\n\n{text}" for role, text in self.messages)

    def copy_chat(self):
        QApplication.clipboard().setText(self.markdown())

    def save_chat(self):
        sessions.save(self.engine.session_id, self.engine.chat_history)
        self.progress.setText(self.tr_pair("Conversation saved", "اتحفظت المحادثة"))

    def export_chat(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export chat", "Nezuko-chat.md", "Markdown (*.md)")
        if path:
            pathlib.Path(path).write_text(self.markdown(), encoding="utf-8")

    def open_outputs(self):
        # Packaged app stores outputs/config beside the exe; source uses cwd.
        folder = pathlib.Path(sys.executable).parent if getattr(sys, "frozen", False) else pathlib.Path.cwd()
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def tools_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle(self.tr_pair("Tools & plugins", "الأدوات والإضافات"))
        dialog.resize(780, 600)
        layout = QVBoxLayout(dialog)
        search = QLineEdit()
        search.setPlaceholderText(self.tr_pair("Search tools…", "ابحث عن أداة…"))
        layout.addWidget(search)
        listing = QListWidget()
        layout.addWidget(listing)
        commands = self.engine.registry.list_commands()
        def populate(query=""):
            listing.clear()
            for command in commands:
                if query.casefold() in (command.name + " " + command.description).casefold():
                    item = QListWidgetItem(command.name + "\n" + command.description)
                    item.setData(Qt.ItemDataRole.UserRole, command.name)
                    listing.addItem(item)
        search.textChanged.connect(populate)
        listing.itemDoubleClicked.connect(lambda item: (self.seed(item.data(Qt.ItemDataRole.UserRole)+" "), dialog.accept()))
        populate()
        self.dialog_open = True
        try:
            dialog.exec()
        finally:
            self.dialog_open = False

    def memory_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle(self.tr_pair("Saved memory", "الذاكرة المحفوظة"))
        dialog.resize(650, 450)
        layout = QVBoxLayout(dialog)
        listing = QListWidget()
        listing.addItems(self.engine.memory.read())
        layout.addWidget(listing)
        def forget():
            row = listing.currentRow()
            if row >= 0:
                self.engine.memory.forget(str(row+1))
                listing.takeItem(row)
        self.button(self.tr_pair("Delete selected note", "حذف المعلومة المختارة"), forget, layout)
        self.dialog_open = True
        try:
            dialog.exec()
        finally:
            self.dialog_open = False

    def settings(self):
        cfg = brain.load_config()
        dialog = QDialog(self)
        dialog.setWindowTitle(self.tr_pair("Settings", "الإعدادات"))
        dialog.resize(650, 600)
        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        layout.addLayout(form)
        size = QSpinBox()
        size.setRange(16, 26)
        size.setValue(self.text_size)
        form.addRow(self.tr_pair("Text size", "حجم الخط"), size)
        mode = QComboBox()
        mode.addItems(["dark", "light"])
        mode.setCurrentText(self.mode)
        form.addRow(self.tr_pair("Appearance", "المظهر"), mode)
        lang = QComboBox()
        lang.addItem("English", "en")
        lang.addItem("العربية", "ar")
        lang.setCurrentIndex(1 if self.ar else 0)
        form.addRow(self.tr_pair("Interface language", "لغة الواجهة"), lang)
        speech = QCheckBox(self.tr_pair("Read replies aloud", "اقرأ الردود بالصوت"))
        speech.setChecked(self.voice)
        form.addRow(speech)
        stt = QComboBox()
        stt.addItems(["base", "small", "turbo"])
        stt.setCurrentText(cfg.get("stt_model", "base"))
        form.addRow(self.tr_pair("Speech recognition", "التعرف على الكلام"), stt)
        latency = QComboBox()
        latency.addItem(self.tr_pair("Fast Salma · Internet", "سلمى السريعة · إنترنت"), "instant")
        latency.addItem(self.tr_pair("Local studio · Slower", "استوديو محلي · أبطأ"), "studio")
        latency.setCurrentIndex(1 if cfg.get("voice_latency_mode") == "studio" else 0)
        form.addRow(self.tr_pair("Arabic voice mode", "طريقة الصوت العربي"), latency)
        arabic = QComboBox()
        arabic.addItems(["Omnia", "Asmaa", "Hanan", "Yasmin", "Esraa", "Sarah"])
        arabic.setCurrentText(cfg.get("human_voice_speaker", "Omnia"))
        form.addRow(self.tr_pair("Studio Arabic voice", "الصوت العربي للاستوديو"), arabic)
        english = QComboBox()
        for name, value in (("US · Heart", "af_heart"), ("US · Bella", "af_bella"),
                            ("US · Nicole", "af_nicole"), ("UK · Emma", "bf_emma"),
                            ("UK · Isabella", "bf_isabella"), ("US · Michael", "am_michael")):
            english.addItem(name, value)
        english.setCurrentIndex(max(0, english.findData(cfg.get("english_voice_voice", "af_heart"))))
        form.addRow(self.tr_pair("English voice", "الصوت الإنجليزي"), english)
        layout.addWidget(QLabel(self.tr_pair("The local brain stays on Qwen 3.5. Larger speech models need more CPU time.",
                                             "العقل المحلي ثابت على Qwen 3.5. نماذج السمع الأكبر أبطأ على المعالج.")))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        self.dialog_open = True
        try:
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            cfg.update(chat_font_size=size.value(), ui_theme=mode.currentText(), ui_lang=lang.currentData(),
                       stt_model=stt.currentText(), voice_latency_mode=latency.currentData(),
                       voice_local_only=latency.currentData() == "studio",
                       human_voice_speaker=arabic.currentText(), english_voice_voice=english.currentData())
            brain.save_config(cfg)
            self.text_size = size.value()
            self.mode = mode.currentText()
            self.voice = speech.isChecked()
            if not self.voice:
                self.continuous = False
                self.engine._voice_cancel.set()
            # Language affects the whole shell; safely rebuild without losing chat/engine.
            if self.ar != (lang.currentData() == "ar"):
                self.ar = lang.currentData() == "ar"
                old = self.takeCentralWidget()
                self.menuBar().clear()
                saved = list(self.messages)
                self.messages.clear()
                self.cards.clear()
                self.build()
                for role, text in saved:
                    self.add_message(role, text)
                old.deleteLater()
                self.refresh_sessions()
            self.apply_theme()
            self.update_status()
        finally:
            self.dialog_open = False

    def closeEvent(self, event):
        self.closed = True
        self.timer.stop()
        self.continuous = False
        self.engine._voice_cancel.set()
        self.engine.shutdown()
        super().closeEvent(event)


def run():
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Nezuko")
    window = Desktop()
    window.showMaximized()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run())
