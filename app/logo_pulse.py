from __future__ import annotations

import math
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QTimer

from .beat import BeatInfo
from .media import QtMediaDeckEngine

if TYPE_CHECKING:
    from .karaoke_window import ProjectorVideoWidget


def beat_pulse(position_ms: int, info: BeatInfo) -> float:
    """A brief, smooth pulse centered on each beat in source time."""
    if not math.isfinite(info.bpm) or info.bpm <= 0 or info.confidence < 0.45:
        return 0.0
    phase = ((position_ms - info.phase_ms) / (60_000.0 / info.bpm)) % 1.0
    distance = min(phase, 1.0 - phase)
    return max(0.0, 1.0 - distance / 0.35) ** 3


class LogoPulseController(QObject):
    def __init__(
        self, engines: tuple[QtMediaDeckEngine, ...], display: ProjectorVideoWidget,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._engines = engines
        self._display = display
        self._source: QtMediaDeckEngine | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        self._source = None
        self._display.set_beat_pulse(0.0)

    def _tick(self) -> None:
        if not self._display.isVisible() or not self._display.logo_visible:
            self._timer.setInterval(250)
            self._display.set_beat_pulse(0.0)
            self._source = None
            return
        self._timer.setInterval(33)
        audible = {
            engine: engine.output_volume() for engine in self._engines
            if engine.is_playing() and engine.output_volume() > 0.001
        }
        if not audible:
            self._source = None
            self._display.set_beat_pulse(0.0)
            return
        source = max(audible, key=audible.get)
        # Retain the current deck near the center to prevent jitter between
        # two beat grids while both decks have almost equal output gain.
        if self._source in audible and audible[self._source] >= audible[source] - 0.05:
            source = self._source
        self._source = source
        info = source.beat_info()
        position_ms, _duration_ms = source.current_times()
        # Player position already incorporates playback speed and seeks.
        self._display.set_beat_pulse(beat_pulse(position_ms, info) if info else 0.0)
