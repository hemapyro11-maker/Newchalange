"""Small native vector status display; no web view or external assets."""
from PySide6.QtCore import Qt, QTimer, QRectF
from PySide6.QtGui import QColor, QPainter, QPen, QFont, QIcon, QPixmap
from PySide6.QtWidgets import QWidget


class Reactor(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.state = "ready"
        self.color = QColor("#53d9ed")
        self.phase = 0
        self.setMinimumSize(170, 170)
        self.setMaximumHeight(210)
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
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate(self.width()/2, self.height()/2)
        scale = min(self.width(), self.height()) / 210
        painter.scale(scale, scale)
        color = QColor("#f1b76c") if self.state == "offline" else self.color
        faint = QColor(color)
        faint.setAlpha(55)
        painter.setPen(QPen(faint, 1))
        painter.drawEllipse(QRectF(-88, -88, 176, 176))
        for index in range(48):
            painter.save()
            painter.rotate(index*7.5)
            painter.drawLine(0, -84, 0, -79 if index % 4 else -73)
            painter.restore()
        painter.setPen(QPen(color, 3))
        for radius, offset in ((66, self.phase), (52, -self.phase)):
            rect = QRectF(-radius, -radius, radius*2, radius*2)
            for segment in range(3):
                painter.drawArc(rect, int((offset + segment*120)*16), 88*16)
        painter.setPen(QPen(faint, 8))
        painter.drawEllipse(QRectF(-35, -35, 70, 70))
        painter.setPen(QPen(color, 1))
        painter.drawEllipse(QRectF(-30, -30, 60, 60))
        font = QFont("Segoe UI")
        font.setPixelSize(22)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.drawText(QRectF(-30, -30, 60, 60), Qt.AlignmentFlag.AlignCenter, "J")


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
