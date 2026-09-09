from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication, QMessageBox

from app.beat import BeatInfo
from app.logo_pulse import beat_pulse
from app.main_window import MainWindow


class BeatPulseTest(unittest.TestCase):
    def test_pulse_peaks_on_the_source_beat_grid(self) -> None:
        info = BeatInfo(120, 100, 0.9)
        self.assertEqual(beat_pulse(100, info), 1.0)
        self.assertEqual(beat_pulse(600, info), 1.0)
        self.assertEqual(beat_pulse(350, info), 0.0)
        self.assertAlmostEqual(beat_pulse(75, info), beat_pulse(125, info))
        self.assertGreater(beat_pulse(125, info), beat_pulse(175, info))

    def test_missing_confidence_or_invalid_tempo_stays_still(self) -> None:
        for info in (BeatInfo(120, 0, 0.2), BeatInfo(0, 0, 1), BeatInfo(float("nan"), 0, 1)):
            self.assertEqual(beat_pulse(0, info), 0.0)


class ProjectorLogoPulseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.enterContext(patch.object(MainWindow, "_load_playlists"))
        self.enterContext(patch.object(MainWindow, "_save_playlists"))
        self.main = MainWindow()
        self.main.show()
        self.karaoke = self.main._get_karaoke_window()
        self.karaoke.open_projector()
        self.display = self.karaoke.projector.video
        self.controller = self.main._logo_pulse
        self.controller._timer.stop()
        self.left = self.main.left.engine
        self.right = self.main.right.engine
        self.left_playing = self.enterContext(patch.object(self.left, "is_playing", return_value=True))
        self.right_playing = self.enterContext(patch.object(self.right, "is_playing", return_value=True))
        self.left_position = self.enterContext(patch.object(self.left, "current_times", return_value=(100, 60000)))
        self.right_position = self.enterContext(patch.object(self.right, "current_times", return_value=(350, 60000)))
        for engine in (self.left, self.right):
            self.enterContext(patch.object(engine, "beat_info", return_value=BeatInfo(120, 100, 0.9)))

    def tearDown(self) -> None:
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            self.main.close()

    def test_pulse_follows_audible_deck_through_crossfade(self) -> None:
        self.main.crossfader.setValue(0)
        self.controller._tick()
        self.assertIs(self.controller._source, self.left)
        self.assertEqual(self.display._beat_pulse, 1.0)
        self.main.crossfader.setValue(1000)
        self.controller._tick()
        self.assertIs(self.controller._source, self.right)
        self.assertEqual(self.display._beat_pulse, 0.0)
        self.right_position.return_value = (600, 60000)
        self.controller._tick()
        self.assertEqual(self.display._beat_pulse, 1.0)

    def test_gain_and_silent_analysis_exclude_inaudible_decks(self) -> None:
        self.main.crossfader.setValue(500)
        self.main.left.gain.setValue(0)
        self.controller._tick()
        self.assertIs(self.controller._source, self.right)
        self.right.set_analysis_muted(True)
        self.controller._tick()
        self.assertIsNone(self.controller._source)
        self.assertEqual(self.display._beat_pulse, 0.0)

    def test_paused_decks_leave_logo_still(self) -> None:
        self.controller._tick()
        self.left_playing.return_value = False
        self.right_playing.return_value = False
        self.controller._tick()
        self.assertEqual(self.display._beat_pulse, 0.0)
        self.assertIsNone(self.controller._source)

    def test_nearly_equal_mix_keeps_current_beat_grid(self) -> None:
        self.main.crossfader.setValue(1000)
        self.controller._tick()
        self.main.crossfader.setValue(495)
        self.controller._tick()
        self.assertIs(self.controller._source, self.right)

    def test_hidden_projector_and_video_disable_pulse(self) -> None:
        self.controller._tick()
        self.display.set_idle(False)
        self.controller._tick()
        self.assertEqual(self.display._beat_pulse, 0.0)
        self.assertEqual(self.controller._timer.interval(), 250)
        self.karaoke.projector.hide()
        self.controller._tick()
        self.assertIsNone(self.controller._source)

    def test_glow_and_pulse_render_without_changing_video(self) -> None:
        self.app.processEvents()
        self.display.set_beat_pulse(0)
        resting = self.display.grab().toImage()
        self.display.set_beat_pulse(1)
        pulsing = self.display.grab().toImage()
        self.assertNotEqual(resting, pulsing)
        self.assertFalse(self.display._glow_image.isNull())
        glow = self.display._glow_image
        self.assertTrue(any(
            glow.pixelColor(x, y).alpha() > 0
            for y in range(0, glow.height(), 8) for x in range(0, glow.width(), 8)
        ))
        frame = QImage(self.display.size(), QImage.Format.Format_RGB32)
        frame.fill(QColor("#e03020"))
        self.display.set_image(frame)
        self.display.set_idle(False)
        self.display.set_beat_pulse(0)
        plain_video = self.display.grab().toImage()
        self.display.set_beat_pulse(1)
        self.assertEqual(plain_video, self.display.grab().toImage())
