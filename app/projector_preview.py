from __future__ import annotations

from PySide6.QtCore import QPoint, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget


class ProjectorPreview(QWidget):
    """Render the projector's exact output at monitor size, without another player."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._source: QWidget | None = None
        self.setFixedHeight(132)
        self.setAccessibleName("Live projector preview")
        self.setToolTip("Live projector output, including the logo, glow and singer overlay")
        self._timer = QTimer(self)
        self._timer.setInterval(67)
        self._timer.timeout.connect(self.update)

    def set_source(self, source: QWidget) -> None:
        self._source = source
        self.update()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._timer.start()

    def hideEvent(self, event) -> None:
        self._timer.stop()
        super().hideEvent(event)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        font = painter.font()
        font.setPointSize(8)
        painter.setFont(font)
        painter.setPen(QColor("#8f9db2"))
        painter.drawText(self.rect().adjusted(0, 0, 0, -114), Qt.AlignmentFlag.AlignCenter, "PROJECTOR PREVIEW")
        monitor = QRectF(self.rect().adjusted(0, 20, 0, 0))
        painter.fillRect(monitor, QColor("#000000"))
        source = self._source
        if source is None or not source.isVisible():
            painter.drawText(monitor, Qt.AlignmentFlag.AlignCenter, "PROJECTOR CLOSED")
        else:
            scale = min(monitor.width() / max(1, source.width()), monitor.height() / max(1, source.height()))
            painter.save()
            painter.setClipRect(monitor)
            painter.translate(monitor.center().x() - source.width() * scale / 2,
                              monitor.center().y() - source.height() * scale / 2)
            painter.scale(scale, scale)
            # QWidget.render redirects painting into this small target, keeping
            # video, logo animation and text identical to the projector.
            source.render(painter, QPoint())
            painter.restore()
        painter.setPen(QColor("#34445f"))
        painter.drawRect(monitor.adjusted(0, 0, -1, -1))
