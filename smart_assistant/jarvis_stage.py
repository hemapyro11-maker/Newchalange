"""Native animated voice stage. No browser, video loop or model for decoration."""
import math
import time
from PySide6.QtCore import Qt, QRectF, QTimer
from PySide6.QtGui import QColor, QPainter, QPen, QRadialGradient, QPainterPath
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QProgressBar
from jarvis_hud import Reactor


class Atmosphere(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.timer = QTimer(self)
        self.timer.setInterval(40)
        self.timer.timeout.connect(self.update)
        self.started = time.monotonic()

    def showEvent(self, event):
        super().showEvent(event)
        self.timer.start()

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        phase = time.monotonic() - self.started
        glow = QRadialGradient(w*.5, h*.48, max(w,h)*.7)
        glow.setColorAt(0, QColor('#075b82'))
        glow.setColorAt(.55, QColor('#073047'))
        glow.setColorAt(1, QColor('#030c17'))
        p.fillRect(self.rect(), glow)
        for i in range(6):
            path = QPainterPath()
            for x in range(0, w+16, 16):
                y = h*.52 + math.sin(x/max(w,1)*6 + phase*.25+i*.5)*(35+i*11)
                if x == 0: path.moveTo(x,y)
                else: path.lineTo(x,y)
            p.setPen(QPen(QColor(57,209,240,35 if i%2 else 70),1))
            p.drawPath(path)
        for i in range(52):
            x = (i*173.7 + phase*(2+i%3)) % max(w,1)
            y = (i*97.3) % max(h,1)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(120,220,245,30+int(35*(1+math.sin(phase+i)))))
            p.drawEllipse(QRectF(x,y,2,2))


class VoiceOrb(Reactor):
    def paintEvent(self, event):
        p=QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.translate(self.width()/2,self.height()/2)
        r=min(self.width(),self.height())*.33
        phase=time.monotonic()*12
        pulse=1+.035*math.sin(time.monotonic()*3) if self.state=='speaking' else 1
        r*=pulse
        gradient=QRadialGradient(0,0,r*1.6)
        gradient.setColorAt(0,QColor(40,225,255,65)); gradient.setColorAt(.6,QColor(25,165,220,25)); gradient.setColorAt(1,QColor(0,150,220,0))
        p.setPen(Qt.PenStyle.NoPen);p.setBrush(gradient);p.drawEllipse(QRectF(-r*1.6,-r*1.6,r*3.2,r*3.2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        for factor,color,width in ((1.04,'#d2b46c',2),(1,'#72e3ef',1),(.92,'#3085a9',1),(.62,'#2388a8',1)):
            p.setPen(QPen(QColor(color),width)); rr=r*factor
            p.drawEllipse(QRectF(-rr,-rr,rr*2,rr*2))
        p.setPen(QPen(QColor('#e0cb89'),3))
        p.drawArc(QRectF(-r*1.06,-r*1.06,r*2.12,r*2.12),int(phase*16),52*16)
        p.drawArc(QRectF(-r*.86,-r*.86,r*1.72,r*1.72),int(-phase*16),90*16)
        p.setPen(QPen(QColor(80,220,240,90),1))
        for index in range(5):
            p.save();p.rotate(index*36+phase*.1)
            p.drawEllipse(QRectF(-r*.78,-r*.24,r*1.56,r*.48));p.restore()
        p.setPen(QColor('#b3f7ff'));font=self.font();font.setPixelSize(27);font.setLetterSpacing(font.SpacingType.AbsoluteSpacing,5);p.setFont(font)
        p.drawText(QRectF(-r,-22,r*2,40),Qt.AlignmentFlag.AlignCenter,getattr(self,'persona','JARVIS'))


class VoiceStage(QWidget):
    def __init__(self, desktop):
        super().__init__();self.desktop=desktop
        self.setObjectName('voiceStage')
        self.backdrop=Atmosphere(self)
        layout=QVBoxLayout(self);layout.setContentsMargins(30,24,30,24)
        top=QHBoxLayout();self.caption=QLabel('VOICE / COMMAND CENTER');top.addWidget(self.caption);top.addStretch()
        self.summary=QLabel();top.addWidget(self.summary);layout.addLayout(top)
        layout.addStretch(1)
        self.reactor=VoiceOrb();self.reactor.setMinimumHeight(320);layout.addWidget(self.reactor,3)
        self.core_status=QLabel();self.core_status.setAlignment(Qt.AlignmentFlag.AlignCenter);layout.addWidget(self.core_status)
        self.voice_state=QLabel();self.voice_state.setAlignment(Qt.AlignmentFlag.AlignCenter);layout.addWidget(self.voice_state)
        self.subtitle=QLabel();self.subtitle.setWordWrap(True);self.subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter);self.subtitle.setMaximumHeight(120);layout.addWidget(self.subtitle)
        controls=QHBoxLayout();controls.addStretch()
        for en,ar,callback in [('Talk now','اتكلم دلوقتي',desktop.listen),('Continuous conversation','محادثة مستمرة',desktop.toggle_conversation),('Hey Jarvis','Hey Jarvis',desktop.toggle_wake),('Stop','توقف',desktop.stop_voice)]:
            button=QPushButton(desktop.tr_pair(en,ar));button.clicked.connect(callback);controls.addWidget(button)
        controls.addStretch();layout.addLayout(controls)
        self.level=QProgressBar();self.level.setFixedWidth(320);self.level.setRange(0,100);self.level.setFormat(desktop.tr_pair('Microphone %p%','المايك %p%'));layout.addWidget(self.level,0,Qt.AlignmentFlag.AlignHCenter)
        self.score=QLabel();self.score.setAlignment(Qt.AlignmentFlag.AlignCenter);layout.addWidget(self.score)
        layout.addStretch(1)
        self.telemetry=QLabel();self.telemetry.setAlignment(Qt.AlignmentFlag.AlignCenter);layout.addWidget(self.telemetry)
        self.timer=QTimer(self);self.timer.timeout.connect(self.refresh)
        try:
            import psutil
            self.psutil=psutil
        except ImportError:self.psutil=None
        self.refresh()

    def resizeEvent(self,event):
        self.backdrop.setGeometry(self.rect());self.backdrop.lower();super().resizeEvent(event)

    def showEvent(self,event):
        super().showEvent(event);self.timer.start(1000)

    def hideEvent(self,event):
        self.timer.stop();super().hideEvent(event)

    def refresh(self):
        d=self.desktop
        self.reactor.persona=getattr(d,'persona','jarvis').upper()
        self.summary.setText(f'{d.health} · {len(d.engine.registry.list_commands())} tools')
        self.voice_state.setText(d.tr_pair('Say Hey Jarvis, wait for the greeting, then speak.','قول Hey Jarvis، استنى التحية، وبعدها اتكلم.') if d.wake_enabled else d.tr_pair('Press Talk now, or enable Hey Jarvis.','اضغط اتكلم دلوقتي، أو فعّل Hey Jarvis.'))
        if self.psutil:
            mem=self.psutil.virtual_memory()
            self.telemetry.setText(f'CPU {self.psutil.cpu_percent():.0f}%   ·   RAM {mem.percent:.0f}%   ·   Ollama / Qwen 3.5   ·   {d.wake_state}')

    def set_metrics(self,metrics):
        rms=max(1,metrics.get('rms',0))
        self.level.setValue(max(0,min(100,round((20*math.log10(rms/32768)+60)/60*100))))
        self.score.setText(f"Wake {metrics.get('score',0):.2f} / {metrics.get('threshold',.5):.2f}")
