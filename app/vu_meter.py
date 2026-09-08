from __future__ import annotations

import math
import time

from PySide6.QtCore import QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPaintEvent
from PySide6.QtWidgets import QSizePolicy, QWidget


class VuMeter(QWidget):
    """A source RMS meter with a fast attack and gentle release, in dBFS."""

    _FLOOR_DB = -60.0
    _SEGMENTS = 20

    def __init__(self, side: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._level_db = self._FLOOR_DB
        self._target_db = self._FLOOR_DB
        self._last_sample = 0.0
        self._last_tick = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._advance)
        self.setFixedHeight(56)
        self.setMinimumWidth(140)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAccessibleName(f"Deck {side} source VU meter")
        self.setToolTip(f"Deck {side.upper()} source level (RMS dBFS), before gain and crossfader")

    def sizeHint(self) -> QSize:
        return QSize(170, 56)

    def set_level(self, rms: float) -> None:
        rms = max(0.0, min(1.0, rms)) if math.isfinite(rms) else 0.0
        self._target_db = max(self._FLOOR_DB, 20.0 * math.log10(rms)) if rms > 0 else self._FLOOR_DB
        self._last_sample = time.monotonic()
        if not self._timer.isActive() and self._target_db > self._FLOOR_DB:
            self._last_tick = self._last_sample
            self._timer.start()

    def reset(self) -> None:
        self._timer.stop()
        self._level_db = self._target_db = self._FLOOR_DB
        self.update()

    def _advance(self) -> None:
        now = time.monotonic()
        elapsed = max(0.0, now - self._last_tick)
        self._last_tick = now
        if now - self._last_sample > 0.25:
            self._target_db = self._FLOOR_DB
        response = 0.075 if self._target_db > self._level_db else 0.3
        self._level_db += (self._target_db - self._level_db) * (1.0 - math.exp(-elapsed / response))
        if self._target_db == self._FLOOR_DB and self._level_db < self._FLOOR_DB + 0.1:
            self.reset()
        else:
            self.update()

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#080b10"))
        painter.drawRoundedRect(QRectF(self.rect()), 6, 6)

        font = painter.font()
        font.setPointSize(8)
        painter.setFont(font)
        painter.setPen(QColor("#aab8cc"))
        painter.drawText(self.rect().adjusted(7, 3, -7, -36), Qt.AlignmentFlag.AlignLeft, "VU")
        reading = f"{self._level_db:.0f} dBFS" if self._level_db > self._FLOOR_DB + 0.1 else "-- dBFS"
        painter.drawText(self.rect().adjusted(7, 3, -7, -36), Qt.AlignmentFlag.AlignRight, reading)

        width = self.width() - 14
        segment_width = (width - (self._SEGMENTS - 1) * 2) / self._SEGMENTS
        for index in range(self._SEGMENTS):
            threshold = self._FLOOR_DB + (index + 1) * -self._FLOOR_DB / self._SEGMENTS
            color = "#ff4b5c" if threshold > -6 else "#ffcf33" if threshold > -15 else "#24dd83"
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(color if self._level_db >= threshold else "#202a37"))
            painter.drawRoundedRect(QRectF(7 + index * (segment_width + 2), 23, segment_width, 13), 1, 1)

        painter.setPen(QColor("#718198"))
        scale = self.rect().adjusted(7, 38, -7, -2)
        painter.drawText(scale, Qt.AlignmentFlag.AlignLeft, "-60")
        painter.drawText(scale, Qt.AlignmentFlag.AlignCenter, "-30")
        painter.drawText(scale, Qt.AlignmentFlag.AlignRight, "0")
