"""Jarvis command center: local telemetry and actions sharing one assistant engine.

No network calls, model requests, simulated task counts or fabricated connections.
"""
from __future__ import annotations

import datetime
import json
import pathlib
import sys

from PySide6.QtCore import Qt, QRectF, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QListWidget,
                              QPushButton, QProgressBar, QVBoxLayout, QWidget)
from jarvis_hud import Reactor


class Sphere(Reactor):
    """Original wireframe sphere; animation follows actual engine activity."""
    def paintEvent(self, event):
        import math
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.translate(self.width()/2, self.height()/2)
        scale = min(self.width()/520, self.height()/250); p.scale(scale, scale)
        cyan = QColor("#53d9ed") if self.state != "offline" else QColor("#efb569")
        faint = QColor(cyan); faint.setAlpha(45)
        glow = QRadialGradient(0, 0, 130)
        glow.setColorAt(0, QColor(35, 154, 208, 80)); glow.setColorAt(1, QColor(0, 25, 45, 0))
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(glow); p.drawEllipse(QRectF(-130,-130,260,260))
        p.setBrush(Qt.BrushStyle.NoBrush); p.setPen(QPen(faint, 1))
        for i in range(55):
            x = ((i*97)%490)-245; y = ((i*71)%236)-118
            p.drawPoint(x,y)
        p.drawEllipse(QRectF(-98,-98,196,196))
        for latitude in range(-75, 90, 15):
            angle = math.radians(latitude); y=98*math.sin(angle); width=196*math.cos(angle)
            p.drawEllipse(QRectF(-width/2,y-7,width,14))
        for longitude in range(0,180,15):
            width = 196*abs(math.cos(math.radians(longitude+self.phase/8)))
            p.drawEllipse(QRectF(-width/2,-98,width,196))
        for angle in (-15, 15, 0):
            p.save(); p.rotate(angle); p.drawEllipse(QRectF(-210,-39,420,78)); p.restore()
        p.setPen(QPen(cyan, 1))
        for i in range(7):
            angle = math.radians(i*51+self.phase)
            x,y=190*math.cos(angle),45*math.sin(angle)
            p.setBrush(cyan);p.drawEllipse(QRectF(x-2,y-2,4,4))
        p.setBrush(Qt.BrushStyle.NoBrush)
        font=QFont("Segoe UI");font.setPixelSize(28);font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing,6);font.setBold(True)
        p.setFont(font); p.drawText(QRectF(-160,-27,320,48),Qt.AlignmentFlag.AlignCenter,"JARVIS")
        font.setPixelSize(11); font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing,3);p.setFont(font)
        p.drawText(QRectF(-120,23,240,28),Qt.AlignmentFlag.AlignCenter,"AI CORE")
        p.setPen(QPen(faint,1))
        for i in range(6):p.drawEllipse(QRectF(-120-i*7,92-i*2,240+i*14,20+i*4))


class Gauge(QWidget):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.title, self.value = title, None
        self.setMinimumSize(90, 104)

    def set_value(self, value):
        self.value = value
        self.setAccessibleName(f"{self.title}: {round(value)}%" if value is not None else f"{self.title}: unavailable")
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        size = min(self.width() - 16, self.height() - 32)
        rect = QRectF((self.width()-size)/2, 5, size, size)
        p.setPen(QPen(QColor("#153446"), 6))
        p.drawEllipse(rect)
        p.setPen(QPen(QColor("#48d5eb"), 6))
        if self.value is not None:
            p.drawArc(rect, 90*16, -int(max(0, min(100, self.value))*3.6*16))
        font = QFont("Segoe UI"); font.setPixelSize(18); font.setBold(True)
        p.setFont(font); p.setPen(QColor("#d8edf5"))
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, f"{round(self.value)}%" if self.value is not None else "—")
        font.setPixelSize(12); p.setFont(font)
        p.drawText(QRectF(0, size+14, self.width(), 24), Qt.AlignmentFlag.AlignCenter, self.title)


def read_state(path, default):
    try:
        if path.stat().st_size > 2*1024*1024:
            return default
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


class CommandCenter(QWidget):
    def __init__(self, desktop):
        super().__init__()
        self.desktop = desktop
        self.metrics = {}
        self.psutil = None
        self.cpu_primed = False
        try:
            import psutil
            self.psutil = psutil
            psutil.cpu_percent(interval=None)
        except ImportError:
            pass
        self.setObjectName("commandCenter")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 8, 4, 8)
        layout.setSpacing(8)
        banner = QHBoxLayout()
        title = QLabel(self.tr("COMMAND CENTER", "مركز تحكم جارفيس"))
        title.setObjectName("dashboardTitle")
        banner.addWidget(title); banner.addStretch()
        self.clock = QLabel(); self.clock.setObjectName("dashboardClock")
        banner.addWidget(self.clock); layout.addLayout(banner)
        grid = QGridLayout(); grid.setSpacing(8); layout.addLayout(grid)
        grid.setColumnStretch(0, 3); grid.setColumnStretch(1, 6); grid.setColumnStretch(2, 4)

        overview, body = self.panel(self.tr("AI CORE OVERVIEW", "حالة العقل والمساعد"))
        self.overview = QLabel(); self.overview.setWordWrap(True); body.addWidget(self.overview)
        self.action(body, self.tr("AI core settings", "إعدادات العقل والصوت"), desktop.settings)
        grid.addWidget(overview, 0, 0)

        core, body = self.panel("J A R V I S  /  AI CORE")
        self.reactor = Sphere(); self.reactor.setFixedHeight(170); body.addWidget(self.reactor)
        self.core_status = QLabel(); self.core_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.core_status.setWordWrap(True); body.addWidget(self.core_status)
        grid.addWidget(core, 0, 1)

        feed, body = self.panel(self.tr("LIVE INTELLIGENCE FEED", "أحداث جارفيس الحية"))
        self.feed = QListWidget(); self.feed.setMinimumHeight(110); body.addWidget(self.feed)
        self.action(body, self.tr("View conversation", "فتح المحادثة"), desktop.show_chat)
        grid.addWidget(feed, 0, 2)

        modules, body = self.panel(self.tr("TOOLS & MODULES · ONE SHARED BRAIN", "الأدوات والوحدات · عقل واحد"))
        buttons = QGridLayout(); body.addLayout(buttons)
        for i, (en, ar, prompt) in enumerate((
                ("Code & projects", "البرمجة والمشاريع", "راجع المشروع الحالي وساعدني في تطويره"),
                ("Research & browser", "البحث والمتصفح", "ساعدني أبحث على الإنترنت"),
                ("Video studio", "استوديو الفيديو", "ساعدني أصنع فيديو جديد"),
                ("Audio & voices", "الصوت والأصوات", "ساعدني أجهز تسجيل صوتي"),
                ("System repair", "إصلاح النظام", None),
                ("Tools library", "مكتبة الأدوات", None))):
            english_prompts = ("Review the current project and help me improve it", "Help me research on the internet",
                               "Help me create a new video", "Help me prepare a voice recording")
            selected_prompt = self.tr(english_prompts[i], prompt) if prompt else None
            callback = (lambda _=False, p=selected_prompt: desktop.seed(p)) if prompt else (
                (lambda: desktop.command("self_repair")) if i == 4 else desktop.tools_dialog)
            button = QPushButton(self.tr(en, ar).replace("&", "&&")); button.clicked.connect(callback)
            buttons.addWidget(button, i//2, i%2)
        grid.addWidget(modules, 1, 0)

        quick, body = self.panel(self.tr("QUICK COMMANDS", "أوامر سريعة"))
        for en, ar, callback in (("Start voice chat", "ابدأ محادثة صوتية", desktop.toggle_conversation),
                                 ("Enable / stop Hey Jarvis", "تشغيل / إيقاف النداء", desktop.toggle_wake),
                                 ("Scheduled tasks", "المهام المجدولة", lambda: desktop.command("schedule list")),
                                 ("Browse workflows", "عرض سير العمل", lambda: desktop.command("jarvis_workflow"))):
            self.action(body, self.tr(en, ar), callback)
        grid.addWidget(quick, 1, 2)

        system, body = self.panel(self.tr("SYSTEM MONITOR", "مراقبة الجهاز"))
        gauges = QHBoxLayout(); body.addLayout(gauges)
        self.gauges = [Gauge(name) for name in ("CPU", "RAM", "Disk C:")]
        for gauge in self.gauges: gauges.addWidget(gauge)
        self.disk_detail = QLabel(); self.disk_detail.setWordWrap(True); body.addWidget(self.disk_detail)
        grid.addWidget(system, 2, 0)

        memory, body = self.panel(self.tr("MEMORY INSIGHTS", "الذاكرة والمعرفة"))
        self.memory = QLabel(); self.memory.setWordWrap(True); body.addWidget(self.memory)
        self.action(body, self.tr("View saved memory", "عرض الذاكرة المحفوظة"), desktop.memory_dialog)
        grid.addWidget(memory, 2, 1)

        model, body = self.panel(self.tr("LOCAL MODEL & CONNECTIONS", "النموذج والمنصات"))
        self.model = QLabel(); self.model.setWordWrap(True); body.addWidget(self.model)
        self.action(body, self.tr("Manage connectors", "إدارة المنصات المتصلة"), lambda: desktop.command("connectors list"))
        grid.addWidget(model, 2, 2)

        timeline, body = self.panel(self.tr("MISSION TIMELINE", "المهام وسير العمل"))
        self.timeline = QListWidget(); self.timeline.setMaximumHeight(100); body.addWidget(self.timeline)
        self.action(body, self.tr("Manage tasks", "إدارة المهام"), lambda: desktop.command("todo list"))
        grid.addWidget(timeline, 1, 1)

        voice, body = self.panel(self.tr("VOICE STATUS · LOCAL WAKE", "حالة الصوت والنداء المحلي"))
        line = QHBoxLayout(); body.addLayout(line)
        self.voice_state = QLabel(); self.voice_state.setWordWrap(True); line.addWidget(self.voice_state, 2)
        self.level = QProgressBar(); self.level.setRange(0, 100); self.level.setFormat(self.tr("Microphone %p%", "المايك %p%"))
        line.addWidget(self.level, 1)
        self.score = QLabel(); self.score.setWordWrap(True); line.addWidget(self.score, 1)
        self.action(line, self.tr("Microphone settings", "إعدادات المايك"), desktop.settings)
        self.action(line, self.tr("Talk to Jarvis", "اتكلم مع جارفيس"), desktop.listen)
        grid.addWidget(voice, 3, 0, 1, 3)
        self.refresh()
        self.timer = QTimer(self); self.timer.timeout.connect(self.refresh); self.timer.start(1000)

    def tr(self, en, ar):
        return self.desktop.tr_pair(en, ar)

    def panel(self, title):
        frame = QFrame(); frame.setObjectName("dashboardPanel")
        body = QVBoxLayout(frame); body.setContentsMargins(10, 10, 10, 10); body.setSpacing(6)
        label = QLabel(title); label.setObjectName("panelTitle"); label.setWordWrap(True); body.addWidget(label)
        return frame, body

    def action(self, body, text, callback):
        button = QPushButton(text.replace("&", "&&")); button.clicked.connect(callback); body.addWidget(button)

    def set_metrics(self, metrics):
        self.metrics = metrics
        # Linear peak/RMS clipping is misleading at speech levels; logarithmic dBFS meter.
        import math
        rms = max(1, metrics.get("rms", 0))
        self.level.setValue(max(0, min(100, round((20*math.log10(rms/32768)+60)/60*100))))
        self.score.setText(self.tr("Wake confidence", "درجة النداء") +
                           f": {metrics.get('score', 0):.2f} · peak {metrics.get('peak_score', 0):.2f} / {metrics.get('threshold', .5):.2f}")

    def refresh(self):
        d = self.desktop
        self.clock.setText(datetime.datetime.now().strftime("%a, %d %b %Y\n%I:%M:%S %p"))
        commands = d.engine.registry.list_commands()
        memory = d.engine.memory.read()
        self.overview.setText(self.tr("AI core", "العقل") + ": " + d.health + "\n\n" +
                              self.tr("Activity", "النشاط") + ": " + d.activity + "\n\n" +
                              self.tr("Voice", "الصوت") + ": " + d.wake_state + "\n\n" +
                              self.tr("Available tools", "الأدوات المتاحة") + f": {len(commands)}")
        self.memory.setText(self.tr("Saved notes", "معلومات محفوظة") + f": {len(memory)}\n\n" +
                            self.tr("Conversation turns", "رسائل المحادثة") + f": {len(d.engine.chat_history)}\n\n" +
                            self.tr("Memory is explicit and editable.", "الذاكرة محفوظة محليًا ويمكن تعديلها."))
        self.model.setText("Ollama · Qwen 3.5\n" + self.tr("One local brain", "عقل محلي واحد") +
                           ": " + d.health + "\n\n" + self.tr("Cloud models are disabled in local mode. Connections require setup.",
                           "نماذج السحابة متوقفة في الوضع المحلي. المنصات تحتاج إعداد الاتصال."))
        history = list(d.engine.log_history)[-6:]
        self.feed.clear()
        self.feed.addItems([str(message)[:180] for _, message in reversed(history)] or
                          [self.tr("No recent engine events", "لا توجد أحداث جديدة")])
        base = pathlib.Path(sys.executable).parent if getattr(sys, "frozen", False) else pathlib.Path(__file__).resolve().parent
        todos = read_state(base / "todo.json", [])
        schedule = read_state(base / "schedule.json", {})
        entries = [str(t.get("text", "")) for t in todos if isinstance(t, dict) and not t.get("done")] if isinstance(todos, list) else []
        jobs = schedule.get("jobs", []) if isinstance(schedule, dict) else []
        entries += [f"{j.get('next_run', '')} · {j.get('command', '')}" for j in jobs if isinstance(j, dict) and j.get("enabled")]
        self.timeline.clear(); self.timeline.addItems(entries[:30] or [self.tr("No pending tasks", "لا توجد مهام معلقة")])
        self.voice_state.setText("Hey Jarvis · " + d.wake_state)
        self.voice_state.setToolTip(self.tr("Say the phrase, pause for the acknowledgement, then speak.", "قول النداء، استنى الرد القصير، وبعدين اتكلم."))
        if d.wake_state != "waiting":
            self.level.setValue(0)
        if self.psutil:
            try:
                cpu = self.psutil.cpu_percent(interval=None)
                ram = self.psutil.virtual_memory().percent
                disk = self.psutil.disk_usage(pathlib.Path.home().anchor)
                for gauge, value in zip(self.gauges, (cpu if self.cpu_primed else None, ram, disk.percent)):
                    gauge.set_value(value)
                self.cpu_primed = True
                self.disk_detail.setText(self.tr("Disk free", "المساحة المتاحة") + f": {disk.free/1024**3:.1f} GB")
            except OSError:
                for gauge in self.gauges: gauge.set_value(None)

