from __future__ import annotations

import os
import struct
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QByteArray, QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtMultimedia import QAudioBuffer, QAudioFormat
from PySide6.QtWidgets import QApplication

from app.media import _audio_buffer_level
from app.waveform_widget import WaveformWidget


class WaveformTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_int16_buffer_produces_normalized_level(self) -> None:
        audio_format = QAudioFormat()
        audio_format.setSampleRate(48_000)
        audio_format.setChannelCount(2)
        audio_format.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        data = QByteArray(struct.pack("<hhhh", 4096, -4096, 4096, -4096))
        buffer = QAudioBuffer(data, audio_format, 250_000)

        level = _audio_buffer_level(buffer)

        self.assertIsNotNone(level)
        self.assertAlmostEqual(level, 0.3, places=2)

    def test_samples_map_across_track_timeline(self) -> None:
        waveform = WaveformWidget("left")
        waveform.reset(100_000)
        waveform.add_sample(0, 0.25)
        waveform.add_sample(50_000, 0.5)
        waveform.add_sample(99_999, 0.75)

        self.assertTrue(waveform._known[0])
        self.assertTrue(waveform._known[256])
        self.assertTrue(waveform._known[-1])

    def test_waveform_seek_is_clamped(self) -> None:
        waveform = WaveformWidget("right")
        waveform.resize(400, 72)
        waveform.reset(120_000)
        requests: list[float] = []
        waveform.seekRequested.connect(requests.append)

        waveform._seek_at(-100)
        waveform._seek_at(200)
        waveform._seek_at(1_000)

        self.assertEqual(requests[0], 0.0)
        self.assertAlmostEqual(requests[1], 0.5, delta=0.03)
        self.assertEqual(requests[2], 1.0)

    @staticmethod
    def _mouse(waveform: WaveformWidget, kind: QEvent.Type, x: float) -> None:
        button = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseMove else Qt.MouseButton.LeftButton
        buttons = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseButtonRelease else Qt.MouseButton.LeftButton
        event = QMouseEvent(kind, QPointF(x, 30), QPointF(x, 30), button, buttons, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(waveform, event)

    def test_drag_previews_without_seeking_until_release(self) -> None:
        waveform = WaveformWidget("left")
        waveform.resize(400, 72)
        waveform.reset(120_000)
        waveform.set_position(10_000, 120_000)
        requests: list[float] = []
        waveform.seekRequested.connect(requests.append)

        self._mouse(waveform, QEvent.Type.MouseButtonPress, 50)
        for x in range(60, 350, 10):
            self._mouse(waveform, QEvent.Type.MouseMove, x)
        waveform.set_position(11_000, 120_000)

        self.assertEqual(requests, [])
        self.assertAlmostEqual(waveform._seek_preview_fraction, (340 - 8) / 383)
        self.assertEqual(waveform._position_ms, 11_000)
        self._mouse(waveform, QEvent.Type.MouseButtonRelease, 360)
        self.assertEqual(len(requests), 1)
        self.assertAlmostEqual(requests[0], (360 - 8) / 383)
        self.assertIsNone(waveform._seek_preview_fraction)

    def test_click_commits_once_and_reset_cancels_drag(self) -> None:
        waveform = WaveformWidget("right")
        waveform.resize(400, 72)
        waveform.reset(120_000)
        requests: list[float] = []
        waveform.seekRequested.connect(requests.append)

        self._mouse(waveform, QEvent.Type.MouseButtonPress, 200)
        self._mouse(waveform, QEvent.Type.MouseButtonRelease, 200)
        self.assertEqual(len(requests), 1)
        self.assertAlmostEqual(requests[0], (200 - 8) / 383)

        self._mouse(waveform, QEvent.Type.MouseButtonPress, 300)
        waveform.reset(60_000)
        self._mouse(waveform, QEvent.Type.MouseButtonRelease, 300)
        self.assertEqual(len(requests), 1)

    def test_drag_release_outside_widget_clamps_once(self) -> None:
        waveform = WaveformWidget("right")
        waveform.resize(400, 72)
        waveform.reset(120_000)
        requests: list[float] = []
        waveform.seekRequested.connect(requests.append)

        self._mouse(waveform, QEvent.Type.MouseButtonPress, 200)
        self._mouse(waveform, QEvent.Type.MouseMove, 1_000)
        self._mouse(waveform, QEvent.Type.MouseButtonRelease, 1_000)
        self.assertEqual(requests, [1.0])


if __name__ == "__main__":
    unittest.main()
