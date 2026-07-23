from __future__ import annotations

import os
import struct
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QByteArray
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


if __name__ == "__main__":
    unittest.main()
