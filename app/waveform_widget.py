from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget


class WaveformWidget(QWidget):
    """Compact track overview built from audio decoded during playback."""

    seekRequested = Signal(float)
    _BIN_COUNT = 512
    _MAX_SAMPLES = 20_000

    def __init__(self, side: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._accent = QColor("#00d8ff" if side == "left" else "#ff2fa7")
        self._levels = [0.0] * self._BIN_COUNT
        self._known = [False] * self._BIN_COUNT
        self._samples: list[tuple[int, float]] = []
        self._duration_ms = 0
        self._position_ms = 0
        self._seek_preview_fraction: float | None = None
        self.setMinimumHeight(68)
        self.setMaximumHeight(82)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Waveform builds during playback. Click or drag to seek.")

    def sizeHint(self) -> QSize:
        return QSize(320, 72)

    def reset(self, duration_ms: int = 0) -> None:
        self._levels = [0.0] * self._BIN_COUNT
        self._known = [False] * self._BIN_COUNT
        self._samples.clear()
        self._duration_ms = max(0, duration_ms)
        self._position_ms = 0
        self._seek_preview_fraction = None
        self.update()

    def add_sample(self, time_ms: int, level: float) -> None:
        sample = (max(0, time_ms), max(0.0, min(1.0, level)))
        self._samples.append(sample)
        if len(self._samples) > self._MAX_SAMPLES:
            del self._samples[: len(self._samples) - self._MAX_SAMPLES]
        if self._duration_ms > 0:
            if self._place_sample(*sample):
                self.update()

    def set_position(self, position_ms: int, duration_ms: int) -> None:
        position_ms = max(0, position_ms)
        duration_ms = max(0, duration_ms)
        if duration_ms and duration_ms != self._duration_ms:
            self._duration_ms = duration_ms
            self._rebuild()
        self._position_ms = position_ms
        self.update()

    def _place_sample(self, time_ms: int, level: float) -> bool:
        index = min(
            self._BIN_COUNT - 1,
            max(0, int(time_ms / self._duration_ms * self._BIN_COUNT)),
        )
        was_known = self._known[index]
        previous = self._levels[index]
        self._levels[index] = max(previous, level)
        self._known[index] = True
        return not was_known or self._levels[index] > previous

    def _rebuild(self) -> None:
        self._levels = [0.0] * self._BIN_COUNT
        self._known = [False] * self._BIN_COUNT
        if self._duration_ms > 0:
            for sample in self._samples:
                self._place_sample(*sample)

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.fillRect(self.rect(), QColor("#080b10"))
        frame = self.rect().adjusted(0, 0, -1, -1)
        painter.setPen(QPen(QColor("#34445f"), 1))
        painter.drawRoundedRect(frame, 8, 8)

        graph = frame.adjusted(8, 7, -8, -7)
        center_y = graph.center().y()
        painter.setPen(QPen(QColor("#263247"), 1))
        painter.drawLine(graph.left(), center_y, graph.right(), center_y)

        graph_width = max(1, graph.width())
        fraction = self._seek_preview_fraction
        if fraction is None:
            fraction = (
                max(0.0, min(1.0, self._position_ms / self._duration_ms))
                if self._duration_ms > 0 else 0.0
            )
        played_index = min(self._BIN_COUNT, int(fraction * self._BIN_COUNT))
        for index, level in enumerate(self._levels):
            if not self._known[index]:
                continue
            x = graph.left() + round(index / max(1, self._BIN_COUNT - 1) * graph_width)
            amplitude = max(1, round(level * (graph.height() / 2 - 2)))
            color = QColor(self._accent)
            color.setAlpha(235 if index <= played_index else 125)
            painter.setPen(QPen(color, 1))
            painter.drawLine(x, center_y - amplitude, x, center_y + amplitude)

        if not any(self._known):
            painter.setPen(QColor("#66758c"))
            painter.drawText(graph, Qt.AlignmentFlag.AlignCenter, "WAVEFORM READY ON PLAY")

        if self._duration_ms > 0:
            playhead_x = graph.left() + round(fraction * graph_width)
            painter.setPen(QPen(QColor("#ffffff"), 2))
            painter.drawLine(playhead_x, graph.top(), playhead_x, graph.bottom())

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._duration_ms > 0:
            self._preview_seek(event.position().x())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton and self._seek_preview_fraction is not None:
            self._preview_seek(event.position().x())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._seek_preview_fraction is not None:
            self._seek_preview_fraction = None
            # Commit once. Seeking for every pointer movement repeatedly
            # flushes the decoder and interrupts the audible track.
            self._seek_at(event.position().x())
            self.update()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _fraction_at(self, x: float) -> float:
        return max(0.0, min(1.0, (x - 8) / max(1, self.width() - 17)))

    def _preview_seek(self, x: float) -> None:
        self._seek_preview_fraction = self._fraction_at(x)
        self.update()

    def _seek_at(self, x: float) -> None:
        if self._duration_ms <= 0:
            return
        self.seekRequested.emit(self._fraction_at(x))
