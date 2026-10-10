"""Small native vector status display; no web view or external assets."""
from PySide6.QtCore import Qt, QTimer, QRectF
from PySide6.QtGui import QColor, QPainter, QPen, QFont, QIcon, QPixmap, QRadialGradient
from PySide6.QtWidgets import QWidget


class Reactor(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.state = "ready"
        self.color = QColor("#53d9ed")
        self.phase = 0
        self.setMinimumSize(320, 170)
        self.brain_health = "loading"
        self.wake_enabled = False
        self.setAccessibleName("Jarvis activity indicator")
        self.timer = QTimer(self)
        self.timer.setInterval(80)
        self.timer.timeout.connect(self.advance)

    def set_state(self, state):
        self.state = state
        self.setAccessibleDescription("Current activity: " + state)
        self.sync_timer()
        self.update()

    def sync_timer(self):
        if self.isVisible() and self.state not in {"ready", "offline", "waiting"}:
            self.timer.start()
        else:
            self.timer.stop()

    def showEvent(self, event):
        super().showEvent(event)
        self.sync_timer()

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)

    def advance(self):
        self.phase = (self.phase + 3) % 360
        self.update()

    def paintEvent(self, event):
        import math
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor("#f1b76c") if self.state == "offline" else self.color
        faint = QColor(color); faint.setAlpha(30)
        p.setPen(QPen(faint, 1))
        # Schematic grid and corner brackets make this a console, not a chat card.
        for x in range(0, self.width(), 32): p.drawLine(x, 0, x, self.height())
        for y in range(0, self.height(), 32): p.drawLine(0, y, self.width(), y)
        p.setPen(QPen(color, 2))
        for x, y, sx, sy in ((1,1,1,1),(self.width()-2,1,-1,1),
                             (1,self.height()-2,1,-1),(self.width()-2,self.height()-2,-1,-1)):
            p.drawLine(x,y,x+24*sx,y); p.drawLine(x,y,x,y+24*sy)
        p.translate(self.width()/2, self.height()/2)
        p.scale(min(self.width()/650, self.height()/330), min(self.width()/650, self.height()/330))
        glow = QRadialGradient(0, 0, 145)
        glow.setColorAt(0, QColor(40, 180, 235, 65))
        glow.setColorAt(0.55, QColor(40, 180, 235, 22))
        glow.setColorAt(1, QColor(40, 180, 235, 0))
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(glow)
        p.drawEllipse(QRectF(-145,-145,290,290))
        p.setBrush(Qt.BrushStyle.NoBrush)
        for radius in (143, 137, 112, 86):
            p.setPen(QPen(faint, 1)); p.drawEllipse(QRectF(-radius,-radius,radius*2,radius*2))
        for index in range(120):
            p.save(); p.rotate(index*3)
            p.setPen(QPen(color if index % 5 == 0 else faint, 1))
            p.drawLine(0,-137,0,-128 if index%5==0 else -133); p.restore()
        for radius, offset, segments, sweep in ((121,self.phase,4,65),(104,-self.phase,3,95),(91,self.phase,8,28)):
            p.setPen(QPen(color, 2 if radius != 104 else 4))
            for n in range(segments):
                p.drawArc(QRectF(-radius,-radius,radius*2,radius*2), int((offset+n*360/segments)*16),sweep*16)
        # Wireframe core with crossed orbital paths.
        p.setPen(QPen(faint, 1))
        for angle in (0,45,90,135):
            p.save();p.rotate(angle+self.phase/4)
            p.drawEllipse(QRectF(-74,-30,148,60));p.restore()
        p.setPen(QPen(color, 1));p.drawEllipse(QRectF(-74,-74,148,148))
        for index in range(12):
            angle = math.radians(index*30+self.phase)
            x,y=74*math.cos(angle),74*math.sin(angle)
            p.setBrush(color);p.drawEllipse(QRectF(x-2,y-2,4,4))
        p.setBrush(Qt.BrushStyle.NoBrush)
        font=QFont("Segoe UI");font.setPixelSize(19 if self.height()>250 else 26);font.setWeight(QFont.Weight.DemiBold)
        p.setFont(font);p.setPen(color)
        p.drawText(QRectF(-80,-20,160,32),Qt.AlignmentFlag.AlignCenter,"J.A.R.V.I.S." if self.height()>250 else "JARVIS")
        font.setPixelSize(10);p.setFont(font)
        p.drawText(QRectF(-70,18,140,24),Qt.AlignmentFlag.AlignCenter,self.state.upper().replace("_"," "))
        # Labels reflect application state. These are not fabricated CPU/audio meters.
        font.setPixelSize(11);p.setFont(font)
        labels = ((-310,-96,"LOCAL CORE",self.brain_health.upper()),
                  (190,-96,"VOICE LINK","WAKE ON" if self.wake_enabled else "MANUAL"),
                  (-310,64,"EXECUTION",self.state.upper().replace("_"," ")),
                  (190,64,"INPUT","AR / EN"))
        for x,y,title,value in (labels if self.height()>250 else ()):
            p.setPen(QPen(faint,1));p.drawLine(x,y+38,x+112,y+38)
            p.setPen(color);p.drawText(QRectF(x,y,120,18),title)
            p.drawText(QRectF(x,y+19,120,18),value)
        p.setPen(QPen(faint,1))
        for sign in (-1,1):
            p.drawLine(sign*151,-71,sign*179,-71)
            p.drawLine(sign*179,-71,sign*188,-58)
            p.drawLine(sign*151,85,sign*179,85)
            p.drawLine(sign*179,85,sign*188,72)


def app_icon():
    canvas = QPixmap(64, 64)
    canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor("#0c1925"))
    painter.setPen(QPen(QColor("#53d9ed"), 3))
    painter.drawEllipse(5, 5, 54, 54)
    painter.drawEllipse(14, 14, 36, 36)
    painter.setFont(QFont("Segoe UI", 19, QFont.Weight.Bold))
    painter.drawText(canvas.rect(), Qt.AlignmentFlag.AlignCenter, "J")
    painter.end()
    return QIcon(canvas)
