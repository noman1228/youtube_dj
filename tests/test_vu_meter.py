from __future__ import annotations

import math
import os
import struct
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QByteArray
from PySide6.QtMultimedia import QAudioBuffer, QAudioFormat
from PySide6.QtWidgets import QApplication

from app.deck_widget import DeckWidget
from app.media import _audio_buffer_level
from app.models import Track


def audio_buffer(samples, sample_format=QAudioFormat.SampleFormat.Int16, channels=2, time_us=0):
    codes = {
        QAudioFormat.SampleFormat.UInt8: "B",
        QAudioFormat.SampleFormat.Int16: "h",
        QAudioFormat.SampleFormat.Int32: "i",
        QAudioFormat.SampleFormat.Float: "f",
    }
    audio_format = QAudioFormat()
    audio_format.setSampleRate(48000)
    audio_format.setChannelCount(channels)
    audio_format.setSampleFormat(sample_format)
    data = QByteArray(struct.pack("<" + codes[sample_format] * len(samples), *samples))
    return QAudioBuffer(data, audio_format, time_us)


class SourceLevelTest(unittest.TestCase):
    def test_rms_is_not_amplified_for_meter(self) -> None:
        cases = (
            (QAudioFormat.SampleFormat.UInt8, [192, 64]),
            (QAudioFormat.SampleFormat.Int16, [16384, -16384]),
            (QAudioFormat.SampleFormat.Int32, [1073741824, -1073741824]),
            (QAudioFormat.SampleFormat.Float, [0.5, -0.5]),
        )
        for sample_format, samples in cases:
            with self.subTest(sample_format=sample_format):
                buffer = audio_buffer(samples, sample_format)
                self.assertAlmostEqual(_audio_buffer_level(buffer, scale=1.0), 0.5)
                self.assertEqual(_audio_buffer_level(buffer), 1.0)

    def test_long_stereo_buffer_includes_both_channels(self) -> None:
        for frame in ((0, 16384), (16384, 0)):
            with self.subTest(frame=frame):
                buffer = audio_buffer(frame * 2048)
                self.assertAlmostEqual(_audio_buffer_level(buffer, scale=1.0), 0.5 / math.sqrt(2))

    def test_empty_and_nonfinite_samples_are_safe(self) -> None:
        self.assertIsNone(_audio_buffer_level(QAudioBuffer(), scale=1.0))
        buffer = audio_buffer([float("nan"), float("inf")], QAudioFormat.SampleFormat.Float)
        self.assertEqual(_audio_buffer_level(buffer, scale=1.0), 0.0)


class DeckVuMeterTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.left = DeckWidget("left")
        self.right = DeckWidget("right")

    def tearDown(self) -> None:
        for deck in (self.left, self.right):
            deck.vu_meter.reset()
            deck.engine.stop()
            deck.close()

    def test_each_decoder_drives_only_its_own_meter_before_mixing(self) -> None:
        with patch.object(self.left.engine, "is_playing", return_value=True), patch.object(
            self.right.engine, "is_playing", return_value=True
        ):
            self.left.gain.setValue(0)
            self.left.set_crossfade_factor(0)
            left_output = self.left.engine._audio_buffer_output
            right_output = self.right.engine._audio_buffer_output
            left_output.audioBufferReceived.emit(audio_buffer([16384, -16384]))
            self.assertAlmostEqual(self.left.vu_meter._target_db, 20 * math.log10(0.5))
            self.assertEqual(self.right.vu_meter._target_db, -60)
            right_output.audioBufferReceived.emit(audio_buffer([4096, -4096]))
            self.assertAlmostEqual(self.right.vu_meter._target_db, 20 * math.log10(0.125))
            self.assertAlmostEqual(self.left.vu_meter._target_db, 20 * math.log10(0.5))

    def test_pause_and_stop_clear_meter_and_ignore_late_buffers(self) -> None:
        for state in ("PAUSED", "LOADED", "RECONNECTING 1/3", "PLAYBACK ERROR"):
            with self.subTest(state=state):
                with patch.object(self.left.engine, "is_playing", return_value=True):
                    self.left.engine.audioLevelChanged.emit(0.5)
                self.assertTrue(self.left.vu_meter._timer.isActive())
                with patch.object(self.left.engine, "is_playing", return_value=False):
                    self.left.engine.stateChanged.emit(state)
                    self.left.engine.audioLevelChanged.emit(0.8)
                self.assertEqual(self.left.vu_meter._level_db, -60)
                self.assertEqual(self.left.vu_meter._target_db, -60)
                self.assertFalse(self.left.vu_meter._timer.isActive())

    def test_song_change_resets_meter(self) -> None:
        self.left.vu_meter.set_level(0.9)
        self.left.tracks = [Track("Next song", "file:///fixture.wav")]
        self.left.playlist.addItem(self.left._make_item(0, self.left.tracks[0]))
        with patch.object(self.left.engine, "load"):
            self.left.load_index(0)
        self.assertEqual(self.left.vu_meter._target_db, -60)
        self.assertFalse(self.left.vu_meter._timer.isActive())

    def test_status_description_does_not_clear_playing_meter(self) -> None:
        with patch.object(self.left.engine, "is_playing", return_value=True):
            self.left.engine.audioLevelChanged.emit(0.5)
            self.left.engine.stateChanged.emit("192 KBPS · AAC")
        self.assertGreater(self.left.vu_meter._target_db, -60)

    def test_meter_smooths_samples_and_decays_when_buffers_stop(self) -> None:
        meter = self.left.vu_meter
        with patch("app.vu_meter.time.monotonic", return_value=10.0):
            meter.set_level(0.5)
        with patch("app.vu_meter.time.monotonic", return_value=10.1):
            meter._advance()
        self.assertGreater(meter._level_db, -60)
        self.assertLess(meter._level_db, meter._target_db)
        with patch("app.vu_meter.time.monotonic", return_value=14.0):
            meter._advance()
        self.assertEqual(meter._level_db, -60)
        self.assertFalse(meter._timer.isActive())


if __name__ == "__main__":
    unittest.main()
