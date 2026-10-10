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
    QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout, QLabel, QCalendarWidget,
    QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QPushButton, QDoubleSpinBox,
    QScrollArea, QSizePolicy, QSpinBox, QSplitter, QStackedWidget, QTextBrowser, QTextEdit,
    QVBoxLayout, QWidget)

import brain
import companion
import sessions
import theme
import wake_word
import audio_health
from jarvis_hud import Reactor, app_icon
from jarvis_stage import VoiceStage as CommandCenter
from workspace_views import WorkspaceView
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
        self.setPlaceholderText("اكتب أو اتكلم مع جارفيس…  /  Ask Jarvis anything…")
        self.setAccessibleName("Message Jarvis")

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
    wake = Signal()
    wake_status = Signal(str)
    wake_metrics = Signal(dict)
    reply = Signal(str, int, bool)


class Desktop(QMainWindow):
    def __init__(self, *, start_engine=True):
        super().__init__()
        cfg = brain.load_config()
        if not companion.enabled(cfg):
            cfg = companion.activate(cfg)
            brain.save_config(cfg)
        self.ar = cfg.get("ui_lang") == "ar"
        self.persona = cfg.get("assistant_persona", "jarvis")
        if 'assistant_persona' not in cfg:
            cfg['assistant_persona']='jarvis'
            cfg['english_voice_voice']='am_michael'
            brain.save_config(cfg)
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
        self.wake_listener = None
        self.wake_enabled = False
        self.wake_state = "off"
        self.wake_epoch = 0
        self.events = Events(self)
        self.events.log.connect(self.render_log)
        self.events.status.connect(self.set_status)
        self.events.health.connect(self.brain_ready)
        self.events.pick.connect(self.pick_file)
        self.events.preview.connect(self.show_preview)
        self.events.reply.connect(self.on_reply)
        self.events.wake.connect(self.on_wake)
        self.events.wake_status.connect(self.on_wake_status)
        self.events.wake_metrics.connect(lambda metrics: self.dashboard.set_metrics(metrics))
        self.engine = AssistantEngine(on_log=self.events.log.emit,
                                      on_status=self.events.status.emit, defer_plugins=True)
        self.engine._voice_cancel = threading.Event()
        self.engine.on_preview = self.events.preview.emit
        self.engine.on_reply = self.events.reply.emit
        self.engine.on_need_file = self.events.pick.emit
        self.setWindowTitle("Jarvis · " + __version__)
        self.setWindowIcon(app_icon())
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
        if start_engine and cfg.get("wake_word_enabled", False):
            self.toggle_wake()

    def tr_pair(self, en, ar):
        return ar if self.ar else en

    def button(self, text, callback, layout, *, name=None):
        button = QPushButton(text.replace("&", "&&"))
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
        self.sidebar.setMaximumWidth(220)
        left = QVBoxLayout(self.sidebar)
        left.setContentsMargins(14, 22, 14, 16)
        brand = QLabel(self.persona.upper())
        self.brand=brand
        brand.setObjectName("brand")
        left.addWidget(brand)
        subtitle = QLabel(self.tr_pair("PERSONAL ASSISTANT", "مساعدك الشخصي"))
        subtitle.setObjectName("muted")
        left.addWidget(subtitle)
        self.button(self.tr_pair("+  New chat", "+  محادثة جديدة"), self.new_chat, left)
        self.button(self.tr_pair("Command Center", "مركز التحكم"), self.show_dashboard, left)
        for en,ar,section in (("Conversations","المحادثات","chats"),("Tools & skills","الأدوات والمهارات","tools"),("Projects & files","المشاريع والملفات","projects"),("Tasks & scheduled","المهام والجدولة","tasks"),("Connectors","المنصات المتصلة","connectors")):
            self.button(self.tr_pair(en,ar),lambda _=False,s=section:self.show_workspace(s),left)
        self.button(self.tr_pair("Memory","الذاكرة"),self.memory_dialog,left)
        recent = QLabel(self.tr_pair("Recent chats", "المحادثات السابقة"))
        recent.setObjectName("muted")
        left.addWidget(recent)
        self.recent = QListWidget()
        self.recent.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.recent.itemClicked.connect(self.resume)
        left.addWidget(self.recent, 1)
        self.persona_picker=QComboBox()
        self.persona_picker.addItem("Jarvis", "jarvis");self.persona_picker.addItem("Jen", "jen")
        self.persona_picker.setCurrentIndex(1 if self.persona=='jen' else 0)
        self.persona_picker.currentIndexChanged.connect(self.change_persona)
        left.addWidget(self.persona_picker)
        self.button(self.tr_pair("Voice library", "مكتبة الأصوات"), self.settings, left)
        self.button(self.tr_pair("Settings", "الإعدادات"), self.settings, left)
        self.splitter.addWidget(self.sidebar)

        self.main = QWidget()
        center = QVBoxLayout(self.main)
        center.setContentsMargins(28, 16, 28, 18)
        header = QHBoxLayout()
        self.title = QLabel(self.persona.title())
        self.title.setObjectName("workspaceTitle")
        header.addWidget(self.title)
        header.addStretch()
        self.state_label = QLabel()
        self.state_label.setObjectName("muted")
        header.addWidget(self.state_label)
        search = QLineEdit()
        search.setPlaceholderText(self.tr_pair("Search tools & memory…", "ابحث في الأدوات والذاكرة…"))
        search.setMaximumWidth(240)
        search.returnPressed.connect(lambda: self.search_dialog(search.text()))
        header.addWidget(search)
        self.button(self.tr_pair("Copy chat", "نسخ المحادثة"), self.copy_chat, header)
        self.conversation = self.button(self.tr_pair("Start conversation", "ابدأ محادثة صوتية"),
                                        self.toggle_conversation, header)
        center.addLayout(header)
        self.pages = QStackedWidget()
        self.chat_page = QWidget()
        chat_layout = QVBoxLayout(self.chat_page)
        chat_layout.setContentsMargins(0, 0, 0, 0)
        self.chat_reactor = Reactor()
        self.chat_reactor.setFixedHeight(160)
        chat_layout.addWidget(self.chat_reactor)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.transcript = QWidget()
        self.transcript.setMaximumWidth(900)
        self.transcript_layout = QVBoxLayout(self.transcript)
        self.transcript_layout.setContentsMargins(18, 28, 18, 18)
        self.transcript_layout.setSpacing(20)
        self.welcome = QFrame()
        self.welcome.setObjectName("welcome")
        welcome_layout = QVBoxLayout(self.welcome)
        greeting = QLabel(self.tr_pair("SYSTEM / JARVIS", "جارفيس · جاهز لأوامرك"))
        greeting.setObjectName("greeting")
        welcome_layout.addWidget(greeting)
        description = QLabel(self.tr_pair("Talk, create, and build with Jarvis.", "اتكلم، اصنع فيديوهات، واشتغل على مشاريعك مع جارفيس."))
        description.setWordWrap(True)
        description.setObjectName("muted")
        welcome_layout.addWidget(description)
        missions = QHBoxLayout()
        welcome_layout.addLayout(missions)
        for en, ar in (("Plan a video", "خطط لفيديو"), ("Review my project", "راجع مشروعي"),
                       ("Help me choose a voice", "ساعدني أختار صوت")):
            self.button(self.tr_pair(en, ar), lambda _=False, text=self.tr_pair(en, ar): self.seed(text), missions)
        self.transcript_layout.addWidget(self.welcome)
        self.transcript_layout.addStretch()
        self.scroll.setWidget(self.transcript)
        self.scroll.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        chat_layout.addWidget(self.scroll, 1)
        self.dashboard = CommandCenter(self)
        self.reactor = self.dashboard.reactor
        self.core_status = self.dashboard.core_status
        self.core_status.setObjectName("coreStatus")
        dashboard_scroll = QScrollArea()
        dashboard_scroll.setWidgetResizable(True)
        dashboard_scroll.setFrameShape(QFrame.Shape.NoFrame)
        dashboard_scroll.setWidget(self.dashboard)
        self.pages.addWidget(dashboard_scroll)
        self.pages.addWidget(self.chat_page)
        self.workspaces={}
        for section in ('chats','tools','projects','tasks','connectors'):
            page=WorkspaceView(self,section);self.workspaces[section]=page;self.pages.addWidget(page)
        center.addWidget(self.pages, 1)
        self.progress = QLabel()
        self.progress.setObjectName("muted")
        self.progress.setWordWrap(True)
        center.addWidget(self.progress)
        composer = QFrame()
        self.composer_frame = composer
        composer.setObjectName("composer")
        composer_layout = QVBoxLayout(composer)
        composer_layout.setContentsMargins(12, 8, 12, 8)
        self.entry = Composer()
        self.entry.submitted.connect(self.send)
        composer_layout.addWidget(self.entry)
        controls = QHBoxLayout()
        self.button("＋", self.attach_file, controls)
        controls.addStretch()
        self.brain_label = QLabel("Jarvis · Local")
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
        self.hint = hint
        center.addWidget(hint)
        self.splitter.addWidget(self.main)

        self.tools = QWidget()
        self.tools.setObjectName("tools")
        self.tools.setMinimumWidth(220)
        self.tools.setMaximumWidth(300)
        right = QVBoxLayout(self.tools)
        right.setContentsMargins(18, 24, 18, 18)
        system_caption = QLabel(self.tr_pair("LOCAL INTELLIGENCE", "عقل محلي · خصوصية"))
        system_caption.setObjectName("muted")
        system_caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        right.addWidget(system_caption)
        right.addWidget(QLabel(self.tr_pair("Outputs", "النتائج")))
        self.button(self.tr_pair("Create a file or video", "إنشاء ملف أو فيديو"),
                    lambda: self.seed(self.tr_pair("Help me make a video", "ساعديني أعمل فيديو")), right)
        self.button(self.tr_pair("Open outputs folder", "فتح مجلد النتائج"), self.open_outputs, right)
        right.addWidget(QLabel(self.tr_pair("Sources", "المصادر")))
        self.sources = QListWidget()
        self.sources.setMaximumHeight(140)
        right.addWidget(self.sources)
        for en, ar, callback in (("Attach file", "إرفاق ملف", self.attach_file),
            ("Repair Jarvis", "إصلاح جارفيس", lambda: self.command("self_repair")),
            ("Tools & plugins", "الأدوات والإضافات", self.tools_dialog),
            ("Memory", "الذاكرة", self.memory_dialog),
            ("Connectors", "المنصات المتصلة", lambda: self.command("connectors list"))):
            self.button(self.tr_pair(en, ar), callback, right)
        right.addStretch()
        self.wake_button = self.button(self.tr_pair("Enable Hey Jarvis", "فعّل نداء Hey Jarvis"),
                                       self.toggle_wake, right)
        self.wake_button.setToolTip(self.tr_pair("Local wake detection while Jarvis is open. Click again to stop.",
                                                "نداء محلي أثناء فتح جارفيس. اضغط تاني لإيقاف الاستماع."))
        right.addWidget(QLabel(self.tr_pair("One local brain · No subscription", "عقل محلي واحد · بدون اشتراك")))
        self.splitter.addWidget(self.tools)
        self.splitter.setSizes([220, 980, 280])
        self.splitter.setCollapsible(1, False)
        self.tools.hide()
        self.composer_frame.hide()
        self.hint.hide()
        self.add_menu()

    def show_dashboard(self):
        self.pages.setCurrentIndex(0)
        self.tools.hide()
        self.composer_frame.hide()
        self.hint.hide()
        self.dashboard.refresh()

    def show_chat(self):
        self.pages.setCurrentIndex(1)
        self.composer_frame.show()
        self.hint.show()

    def show_workspace(self, section):
        page=self.workspaces[section];page.refresh()
        self.pages.setCurrentWidget(page);self.composer_frame.hide();self.hint.hide();self.tools.hide()

    def change_persona(self):
        self.persona=self.persona_picker.currentData()
        cfg=brain.load_config();cfg['assistant_persona']=self.persona
        cfg['english_voice_voice']='af_heart' if self.persona=='jen' else 'am_michael'
        brain.save_config(cfg)
        self.brand.setText(self.persona.upper())
        self.title.setText(self.persona.title())
        self.dashboard.refresh()

    def add_menu(self):
        file_menu = self.menuBar().addMenu(self.tr_pair("File", "ملف"))
        edit_menu = self.menuBar().addMenu(self.tr_pair("Edit", "تحرير"))
        view_menu = self.menuBar().addMenu(self.tr_pair("View", "عرض"))
        actions = ((file_menu, "New chat", "Ctrl+N", self.new_chat),
                   (file_menu, "Save chat", "Ctrl+S", self.save_chat),
                   (file_menu, "Export chat", "Ctrl+Shift+S", self.export_chat),
                   (edit_menu, "Settings", "Ctrl+,", self.settings),
                   (edit_menu, "Focus composer", "Ctrl+L", self.focus_composer),
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
            QWidget#sidebar {{background:{c['panel']};border-right:1px solid {c['accent']};}}
            QWidget#tools {{background:{c['panel']};border-left:1px solid {c['border']};}}
            QLabel#brand {{color:{c['accent']};font-size:23px;font-weight:600;padding-bottom:6px;}}
            QLabel#workspaceTitle {{font-size:20px;font-weight:600;}}
            QLabel#coreStatus {{color:{c['accent']};font-size:17px;font-weight:600;}}
            QLabel#greeting {{font-size:23px;font-weight:600;padding-top:2px;}}
            QFrame#welcome {{border:1px solid {c['border']};border-left:3px solid {c['accent']};padding:8px;}}
            QFrame#dashboardPanel {{background:{c['panel']};border:1px solid {c['border']};border-radius:4px;}}
            QLabel#panelTitle {{color:{c['accent']};font-size:13px;font-weight:600;letter-spacing:1px;}}
            QLabel#dashboardTitle {{color:{c['accent']};font-size:22px;font-weight:600;}}
            QLabel#dashboardClock {{color:{c['accent']};font-size:16px;}}
            QWidget#commandCenter QPushButton {{background:{c['panel_hi']};border:1px solid {c['border']};border-radius:4px;}}
            QWidget#commandCenter QPushButton {{padding:5px 8px;font-size:14px;}}
            QWidget#voiceStage QPushButton {{background:rgba(5,30,46,180);border:1px solid #31758b;border-radius:14px;padding:10px 18px;text-align:center;}}
            QWidget#voiceStage QPushButton:hover {{border-color:#b9dcde;background:#12405a;}}
            QProgressBar {{border:1px solid {c['border']};border-radius:4px;text-align:center;min-height:22px;}}
            QProgressBar::chunk {{background:{c['accent']};}}
            QLabel#muted {{color:{c['dim']};font-size:14px;}}
            QLabel#hint {{color:{c['faint']};font-size:12px;}}
            QFrame#composer {{background:{c['panel_hi']};border:1px solid {c['border']};border-radius:4px;}}
            QTextEdit, QTextBrowser {{border:0;background:transparent;selection-background-color:#285c92;}}
            QPushButton {{background:transparent;border:0;border-radius:8px;padding:9px 10px;text-align:left;}}
            QPushButton:hover {{background:{c['panel_hi']};color:{c['accent']};}}
            QPushButton:focus {{border:1px solid {c['accent']};}}
            QPushButton#send {{background:{c['accent']};color:{c['bg']};border-radius:18px;text-align:center;min-width:28px;}}
            QMenuBar,QMenu {{background:{c['panel']};color:{c['text']};}}
            QMenuBar::item:selected,QMenu::item:selected {{background:{c['panel_hi']};}}
            QSplitter::handle {{background:{c['border']};width:1px;}}
            QListWidget {{border:0;background:transparent;outline:0;}}
            QListWidget::item {{padding:9px;border-radius:7px;}}
            QListWidget::item:selected {{background:{c['panel_hi']};}}
            QLineEdit,QComboBox,QSpinBox,QDoubleSpinBox {{background:{c['panel_hi']};border:1px solid {c['border']};padding:7px;border-radius:6px;}}
            QScrollBar:vertical {{background:transparent;width:8px;}}
            QScrollBar::handle:vertical {{background:{c['border']};border-radius:4px;min-height:30px;}}
            QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical {{height:0;}}
        """)
        text_font = QFont("Segoe UI")
        text_font.setPixelSize(self.text_size)
        self.entry.setFont(text_font)
        self.reactor.color = QColor(c['accent'])
        self.reactor.update()
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

    def add_message(self, role, text, *, level="info", record=True, navigate=True):
        if navigate:self.show_chat()
        self.welcome.hide()
        if record:
            self.messages.append((role, text))
        card = QFrame()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 10, 14, 12)
        if role == "user":
            card.setStyleSheet(f"QFrame {{background:{theme.palette(self.mode)['panel_hi']};border-radius:14px;}}")
        head = QHBoxLayout()
        label = QLabel(self.tr_pair("You", "أنت") if role == "user" else
                       self.tr_pair("Activity", "النشاط") if role == "tool" else self.persona.title())
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
        self.show_chat()
        self.entry.setPlainText(text)
        self.entry.setFocus()

    def focus_composer(self):
        self.show_chat()
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
            self.last_command = "voice_reply"
            heard=text.splitlines()[0].split(":", 1)[1].strip()
            self.dashboard.subtitle.setText(heard)
            self.add_message("user", heard, navigate=False)
            return
        final = "\n— " in text and not any(m in text for m in ("🔧", "↪", "اكتب y", "write y", "❓"))
        body = text.rpartition("\n— ")[0] if "\n— " in text else text
        tool = body.lstrip().startswith("↪") or text.startswith("🔊")
        self.add_message("tool" if tool else "assistant", body.strip(), level=level, navigate=False)
        if level == "error" and self.voice and self.last_command != "speak":
            self.continuous = False
            # A failed voice backend must not recursively speak its own error.
        self.refresh_sessions()
        self.update_status()

    def on_reply(self, text, generation, voice_turn):
        """Speak one validated answer, never a draft, tool log or earlier session."""
        if self.closed or generation != self.engine._generation or not text.strip():
            return
        if voice_turn or brain.load_config().get('read_replies_aloud',False):
            self.dashboard.subtitle.setText(text[:500])
            self.speak(text)

    def speak(self, text):
        self.tts_pending = True
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
        if self.wake_listener:
            listener = self.wake_listener
            listener.allow(False)
            self.engine.run_task("microphone handoff", lambda ctx: listener.released.wait(1.0))
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
        if self.wake_listener:
            self.wake_listener.allow(self.wake_enabled and self.voice_idle(require_brain=False) and not self.continuous)
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

    def stop_voice(self):
        self.continuous=False
        self.voice=False
        self.engine.cancel()
        self.engine._voice_cancel.set()
        self.tts_pending=False
        self.voice_ready_since=0
        if sys.platform=='win32':
            import ctypes
            ctypes.windll.winmm.PlaySoundW(None,None,0)
        self.activity='ready'
        self.update_status()

    def voice_idle(self, *, require_brain=True):
        return (not self.closed and self.activity == "ready" and (self.health == "ready" or not require_brain)
                and not self.tts_pending and self.engine._queue.empty()
                and not self.engine._pending_intent and not self.engine._pending_args
                and not self.dialog_open)

    def toggle_wake(self):
        self.wake_epoch += 1
        epoch = self.wake_epoch
        self.wake_enabled = not self.wake_enabled
        cfg = brain.load_config()
        cfg["wake_word_enabled"] = self.wake_enabled
        brain.save_config(cfg)
        previous = self.wake_listener
        if previous:
            previous.close()
            self.wake_listener = None
        self.wake_state = "off"
        if self.wake_enabled:
            try:
                device = wake_word.configured_input(cfg)
                def detector_factory(folder):
                    if previous and not previous.released.wait(2):
                        raise RuntimeError("Previous microphone session is still closing")
                    state = audio_health.microphone_state(cfg.get("microphone_device", ""))
                    if state.get("muted"):
                        raise RuntimeError("Windows microphone is muted. Settings → Unmute Windows microphone.")
                    if state.get("available") and state.get("volume") == 0:
                        raise RuntimeError("Windows microphone input volume is zero. Raise its input level in Windows.")
                    return wake_word.load_detector(folder)
                self.wake_listener = wake_word.WakeListener(brain._base_dir() / "wake_models",
                    lambda: self.events.wake.emit() if epoch == self.wake_epoch else None,
                    lambda state: self.events.wake_status.emit(state) if epoch == self.wake_epoch else None,
                    device=device, threshold=cfg.get("wake_threshold", 0.5), frames=cfg.get("wake_frames", 1),
                    detector_factory=detector_factory,
                    on_metrics=lambda data: self.events.wake_metrics.emit(data) if epoch == self.wake_epoch else None)
                self.wake_listener.start()
            except Exception as exc:
                self.on_wake_status("error:" + str(exc)[:240])
        self.update_status()

    def on_wake_status(self, status):
        if self.closed:
            return
        self.wake_state = status
        if status.startswith("error:"):
            self.wake_enabled = False
            if self.wake_listener:
                self.wake_listener.close()
                self.wake_listener = None
            self.add_message("tool", self.tr_pair("Wake detection couldn't start. Check the microphone and wake models.",
                                                  "تعذّر تشغيل النداء. راجع المايك ونماذج النداء.") + "\n" + status[6:], level="warn")
        self.update_status()

    def on_wake(self):
        if not self.wake_enabled or not self.voice_idle(require_brain=False) or self.continuous:
            return
        self.voice = True
        self.engine._voice_cancel.clear()
        self.activity = "queued"
        self.last_command = "listen_run"
        language = wake_word.acknowledgement_language(brain.load_config())
        generation = self.engine._generation
        def acknowledge(ctx):
            if generation == self.engine._generation and not self.engine._voice_cancel.is_set():
                self.engine._set_status("speaking")
                if not wake_word.play_acknowledgement(language):
                    self.engine._log(self.tr_pair("Wake detected, but the acknowledgement could not play. Check the output device.",
                                                "النداء اتسمع، لكن صوت الرد القصير فشل. راجع سماعات الجهاز."), "warn")
        self.engine.run_task("wake acknowledgement", acknowledge)
        self.engine.listen()
        self.update_status()

    def set_status(self, status):
        self.activity = status
        if status == "ready" and self.engine._queue.empty():
            self.tts_pending = False
        self.update_status()

    def brain_ready(self, ready):
        self.health = "ready" if ready else "not_ready"
        self.update_status()

    def update_status(self):
        self.wake_button.setText(self.tr_pair("● Hey Jarvis · Stop", "● Hey Jarvis · إيقاف")
                                 if self.wake_enabled and self.wake_state == "waiting" else
                                 self.tr_pair("Wake enabled · Stop", "النداء مفعّل · إيقاف") if self.wake_enabled else
                                 self.tr_pair("Enable Hey Jarvis", "فعّل نداء Hey Jarvis"))
        self.state_label.setText(self.tr_pair("● Ready", "● جاهزة") if self.health == "ready" else
                                self.tr_pair("Loading local brain…", "تحميل العقل المحلي…") if self.health == "loading" else
                                self.tr_pair("Local brain needs attention", "العقل المحلي محتاج مراجعة"))
        labels = {"thinking": ("Thinking…", "بفكر…"), "listening": ("Listening…", "بسمعك…"),
                  "loading_tools": ("Loading tools…", "بحمّل الأدوات…"),
                  "transcribing": ("Understanding your speech…", "بفهم كلامك…"),
                  "speaking": ("Speaking…", "بتكلم…"), "reading": ("Reading…", "بقرأ…"),
                  "updating": ("Updating…", "بعدّل…"), "rendering": ("Rendering video…", "بجهز الفيديو…"),
                  "repairing": ("Checking and repairing…", "بفحص وأصلّح…"),
                  "running_tool": ("Running a tool…", "بشغّل أداة…"),
                  "queued": ("Preparing…", "بحضّر…"), "working": ("Working…", "شغالة…"), "ready": ("", "")}
        en, ar = labels.get(self.activity, (self.activity, self.activity))
        self.progress.setText(self.tr_pair(en, ar))
        reactor_state = self.activity
        if self.health != "ready" and self.activity == "ready":
            reactor_state = "starting" if self.health == "loading" else "offline"
        elif self.activity == "ready" and self.wake_enabled and self.wake_state == "waiting":
            reactor_state = "waiting"
        self.reactor.brain_health = self.health
        self.reactor.wake_enabled = self.wake_enabled
        self.reactor.set_state(reactor_state)
        self.chat_reactor.brain_health = self.health
        self.chat_reactor.wake_enabled = self.wake_enabled
        self.chat_reactor.set_state(reactor_state)
        self.core_status.setText(self.progress.text() or
            (self.tr_pair("Hey Jarvis · standing by", "Hey Jarvis · مستني النداء") if reactor_state == "waiting" else
             self.state_label.text()))
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
        sessions.save(self.engine.session_id, self.engine.chat_history)
        self.engine.new_session()
        self.engine._voice_cancel.set()
        self.tts_pending = False
        self.last_command = ""
        self.activity = "ready"
        self.continuous = False
        self.voice_ready_since = 0
        self.clear_preview()
        for card, _ in self.cards:
            card.deleteLater()
        self.cards.clear()
        self.messages.clear()
        self.welcome.show()
        self.show_chat()
        self.entry.clear()
        self.entry.setFocus()
        self.refresh_sessions()

    def show_preview(self, text, generation):
        if self.closed or generation != self.engine._generation:
            return
        if self.continuous or self.last_command == 'voice_reply':
            return
        if not text:
            self.clear_preview()
            return
        self.welcome.hide()
        self.show_chat()
        if self.preview_browser is None:
            font = QFont("Segoe UI")
            font.setPixelSize(self.text_size)
            self.preview_browser = MessageText("", font)
            self.transcript_layout.insertWidget(self.transcript_layout.count()-1, self.preview_browser)
        # Draft stays separate from final chat/history/speech until validation.
        self.preview_browser.setPlainText(text)
        readable_blocks(self.preview_browser.document())
        self.preview_browser.fit()
        self.progress.setText(self.tr_pair("Jarvis is writing…", "جارفيس بتكتب…"))
        self.scroll_bottom()

    def clear_preview(self):
        if self.preview_browser is not None:
            self.preview_browser.deleteLater()
            self.preview_browser = None

    def refresh_sessions(self):
        self.recent.blockSignals(True)
        self.recent.clear()
        for entry in sessions.list_all()[:20]:
            item = QListWidgetItem(entry.get("title", "Chat"))
            item.setData(Qt.ItemDataRole.UserRole, entry["id"])
            item.setToolTip(entry.get("title", "Chat"))
            self.recent.addItem(item)
            if entry["id"] == self.engine.session_id:
                self.recent.setCurrentItem(item)
        self.recent.blockSignals(False)

    def resume(self, item):
        sid = item.data(Qt.ItemDataRole.UserRole)
        messages = sessions.load(sid)
        if messages is None:
            return
        self.new_chat()
        self.engine.new_session(sid, messages)
        for msg in messages:
            if msg["role"] in {"user", "assistant"}:
                content=msg['content']
                if msg['role']=='assistant':
                    body,tool,question=self.engine._split_directives(content)
                    content=(body+'\n'+question).strip() if question else body
                if content.strip():self.add_message(msg["role"],content)

    def markdown(self):
        return "# Jarvis conversation\n\n" + "\n\n".join(
            f"## {role.title()}\n\n{text}" for role, text in self.messages)

    def copy_chat(self):
        QApplication.clipboard().setText(self.markdown())

    def save_chat(self):
        sessions.save(self.engine.session_id, self.engine.chat_history)
        self.progress.setText(self.tr_pair("Conversation saved", "اتحفظت المحادثة"))

    def export_chat(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export chat", "Jarvis-chat.md", "Markdown (*.md)")
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

    def search_dialog(self, query=""):
        dialog = QDialog(self)
        dialog.setWindowTitle(self.tr_pair("Search Jarvis", "البحث في جارفيس"))
        dialog.resize(700, 500)
        layout = QVBoxLayout(dialog)
        search = QLineEdit(query); layout.addWidget(search)
        listing = QListWidget(); layout.addWidget(listing)
        commands = self.engine.registry.list_commands()
        rows = [("Tool · " + c.name + "\n" + c.description, c.name + " ") for c in commands]
        rows += [("Memory · " + str(note), None) for note in self.engine.memory.read()]
        rows += [("Chat · " + text[:500], None) for _, text in self.messages]
        def populate(text):
            listing.clear()
            for label, command in rows:
                if text.casefold() in label.casefold():
                    item = QListWidgetItem(label); item.setData(Qt.ItemDataRole.UserRole, command)
                    listing.addItem(item)
        def choose(item):
            if item.data(Qt.ItemDataRole.UserRole):
                self.seed(item.data(Qt.ItemDataRole.UserRole)); dialog.accept()
        listing.itemDoubleClicked.connect(choose)
        search.textChanged.connect(populate); populate(query)
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

    def calendar_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle(self.tr_pair("Local calendar", "التقويم المحلي"))
        layout = QVBoxLayout(dialog)
        calendar = QCalendarWidget()
        layout.addWidget(calendar)
        date = QLabel()
        def selected():
            date.setText(calendar.selectedDate().toString("yyyy-MM-dd"))
        calendar.selectionChanged.connect(selected)
        selected(); layout.addWidget(date)
        self.button(self.tr_pair("View scheduled jobs", "عرض المهام المجدولة"),
                    lambda: (dialog.accept(), self.command("schedule list")), layout)
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
        form_container = QWidget()
        form = QFormLayout(form_container)
        settings_scroll = QScrollArea()
        settings_scroll.setWidgetResizable(True)
        settings_scroll.setWidget(form_container)
        layout.addWidget(settings_scroll, 1)
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
        speech.setChecked(cfg.get('read_replies_aloud',False))
        form.addRow(speech)
        stt = QComboBox()
        stt.addItems(["base", "small", "turbo"])
        stt.setCurrentText(cfg.get("stt_model", "base"))
        form.addRow(self.tr_pair("Speech recognition", "التعرف على الكلام"), stt)
        stt_language = QComboBox()
        for label, value in (("العربية", "ar"), ("English", "en"),
                             (self.tr_pair("Automatic", "تلقائي"), "auto")):
            stt_language.addItem(label, value)
        stt_language.setCurrentIndex(max(0, stt_language.findData(cfg.get("stt_language", "auto"))))
        form.addRow(self.tr_pair("Microphone language", "لغة المايك"), stt_language)
        microphone = QComboBox()
        microphone.addItem(self.tr_pair("Windows default", "مايك ويندوز الافتراضي"), "")
        try:
            for label, index in wake_word.input_devices():
                microphone.addItem(label, label)
        except Exception as exc:
            microphone.setToolTip(str(exc)[:240])
        selected = cfg.get("microphone_device", "")
        if selected and microphone.findData(selected) < 0:
            microphone.addItem(selected + " · disconnected", selected)
        microphone.setCurrentIndex(max(0, microphone.findData(selected)))
        form.addRow(self.tr_pair("Input microphone", "مايك الإدخال"), microphone)
        audio_state = QLabel()
        audio_state.setWordWrap(True)
        def check_audio():
            state = audio_health.microphone_state(microphone.currentData())
            audio_state.setText((self.tr_pair("Windows microphone", "مايك ويندوز") +
                                f": {'MUTED' if state.get('muted') else 'ON'} · {state['volume']}%")
                               if state.get("available") else state.get("detail", "Unavailable"))
        check_audio()
        microphone.currentIndexChanged.connect(check_audio)
        form.addRow(audio_state)
        def unmute_input():
            state = audio_health.microphone_state(microphone.currentData(), unmute=True)
            if not state.get("available"):
                audio_state.setText(state.get("detail", "Could not unmute microphone"))
                return
            check_audio()
            if cfg.get("wake_word_enabled") and not self.wake_enabled:
                self.toggle_wake()
        unmute_button = QPushButton(self.tr_pair("Unmute Windows microphone", "فك كتم مايك ويندوز"))
        unmute_button.clicked.connect(unmute_input)
        form.addRow(unmute_button)
        wake_language = QComboBox()
        wake_language.addItem("English · I am here", "en")
        wake_language.addItem("العربية · أيوه، معاك", "ar")
        wake_language.setCurrentIndex(max(0, wake_language.findData(cfg.get("wake_ack_language", "en"))))
        form.addRow(self.tr_pair("Wake greeting language", "لغة الرد القصير للنداء"), wake_language)
        sensitivity = QDoubleSpinBox()
        sensitivity.setRange(0.1, 0.95); sensitivity.setSingleStep(0.05)
        sensitivity.setValue(cfg.get("wake_threshold", 0.5))
        sensitivity.setToolTip(self.tr_pair("Lower threshold hears softer calls; may trigger on other sounds.", "القيمة الأقل تسمع النداء الخافت، لكنها ممكن تلتقط أصوات تانية."))
        form.addRow(self.tr_pair("Wake threshold", "درجة قبول النداء"), sensitivity)
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
                       stt_model=stt.currentText(), stt_language=stt_language.currentData(),
                       microphone_device=microphone.currentData(), wake_threshold=sensitivity.value(),
                       wake_ack_language=wake_language.currentData(),
                       voice_latency_mode=latency.currentData(),
                       voice_local_only=latency.currentData() == "studio",
                       read_replies_aloud=speech.isChecked(),
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
            if self.wake_enabled:
                self.toggle_wake()
                self.toggle_wake()
        finally:
            self.dialog_open = False

    def closeEvent(self, event):
        self.closed = True
        if self.wake_listener:
            self.wake_listener.close()
        self.timer.stop()
        self.dashboard.timer.stop()
        self.continuous = False
        self.engine._voice_cancel.set()
        self.engine.shutdown()
        super().closeEvent(event)


def run():
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Jarvis")
    window = Desktop()
    window.showMaximized()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run())
