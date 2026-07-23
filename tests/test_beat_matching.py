from __future__ import annotations

import os
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.beat import (
    BeatInfo,
    BeatTracker,
    bar_fade_seconds,
    delay_to_next_beat_ms,
    matched_playback_rate,
    normalized_target_bpm,
    phase_error_cycles,
)
from app.main_window import MainWindow


class BeatMathTest(unittest.TestCase):
    def test_regular_pulses_estimate_120_bpm(self) -> None:
        tracker = BeatTracker()
        for time_ms in range(0, 10_000, 50):
            tracker.add_level(time_ms, 0.9 if time_ms % 500 == 0 else 0.05)
        info = tracker.info()
        self.assertIsNotNone(info)
        self.assertAlmostEqual(info.bpm, 120.0, places=1)
        self.assertGreater(info.confidence, 0.8)

    def test_stronger_downbeats_win_over_weaker_offbeats(self) -> None:
        tracker = BeatTracker()
        for time_ms in range(0, 10_000, 50):
            if time_ms % 500 == 0:
                level = 0.9
            elif time_ms % 500 == 250:
                level = 0.42
            else:
                level = 0.05
            tracker.add_level(time_ms, level)
        info = tracker.info()
        self.assertIsNotNone(info)
        self.assertAlmostEqual(info.bpm, 120.0, places=1)
        self.assertEqual(info.phase_ms, 0)

    def test_tempo_and_bar_math_is_bounded(self) -> None:
        self.assertEqual(matched_playback_rate(120, 1.0, 100), 1.2)
        self.assertAlmostEqual(matched_playback_rate(100, 1.0, 120), 5 / 6)
        self.assertEqual(normalized_target_bpm(90, 180), 90)
        self.assertEqual(bar_fade_seconds(4, 120), 8.0)
        self.assertEqual(delay_to_next_beat_ms(2_250, 0, 120, 1.0), 250)
        self.assertAlmostEqual(phase_error_cycles(250, 0, 120, 125, 0, 120), 0.25)


class BeatTransitionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.main = MainWindow()
        self.source = self.main.left.engine
        self.target = self.main.right.engine
        self.calls: list[tuple[str, float | int | bool]] = []
        self.target.pause = lambda: self.calls.append(("pause", True))
        self.target.seek_ms = lambda value: self.calls.append(("seek", value))
        self.target.set_playback_rate = lambda value: self.calls.append(("rate", value))
        self.target.set_analysis_muted = lambda value: self.calls.append(("mute", value))
        self.target.is_playing = lambda: True
        def play_target() -> None:
            self.calls.append(("play", True))
            # Exercise backends that report PlayingState before play() returns.
            self.main._deck_started("right")

        self.target.play = play_target
        self.source.current_times = lambda: (2_000, 180_000)
        self.source.playback_rate = lambda: 1.0
        self.source.is_playing = lambda: True
        self.main._pending_transition = ("left", "right")
        self.main._beat_analysis_target = "right"
        self.main._beat_analysis_started = time.monotonic() - 5.0

    def tearDown(self) -> None:
        self.main.close()

    def test_confident_analysis_launches_beat_transition(self) -> None:
        self.source.beat_info = lambda: BeatInfo(120.0, 0, 0.9)
        self.target.beat_info = lambda: BeatInfo(100.0, 100, 0.9)

        self.main._beat_analysis_tick()

        self.assertIn(("rate", 1.2), self.calls)
        self.assertIn(("seek", 100), self.calls)
        self.assertTrue(self.main._transition_beat_matched)
        self.assertEqual(self.main._transition_duration, 8.0)
        self.main._beat_launch_timer.stop()
        self.main._launch_pending_transition()
        self.assertFalse(self.main._transition_active)
        # A delayed Qt PlayingState callback must not bypass phase settling.
        self.main._deck_started("right")
        self.assertFalse(self.main._transition_active)
        self.main._beat_settle_timer.stop()
        self.main._settle_beat_transition()
        self.main._beat_mix_start_timer.stop()
        self.main._start_aligned_transition()
        self.assertTrue(self.main._transition_active)
        self.assertIn(("mute", False), self.calls)
        self.assertIn(("play", True), self.calls)

    def test_four_bar_fade_advances_from_source_beats(self) -> None:
        self.source.beat_info = lambda: BeatInfo(120.0, 0, 0.9)
        self.target.beat_info = lambda: BeatInfo(120.0, 0, 0.9)
        self.main._beat_analysis_tick()
        self.main._beat_launch_timer.stop()
        self.main._launch_pending_transition()
        self.main._beat_settle_timer.stop()
        self.main._settle_beat_transition()
        self.main._beat_mix_start_timer.stop()
        self.main._start_aligned_transition()

        self.calls.clear()
        self.source.current_times = lambda: (2_500, 180_000)
        self.main._fade_tick()

        self.assertEqual(self.main._transition_total_beats, 16)
        self.assertEqual(self.main.crossfader.value(), 531)
        self.assertIn("BEAT 2/16", self.main.status.text())
        self.assertFalse(any(name == "rate" for name, _value in self.calls))

    def test_incoming_deck_returns_to_original_bpm_after_mix(self) -> None:
        self.source.beat_info = lambda: BeatInfo(120.0, 0, 0.9)
        self.target.beat_info = lambda: BeatInfo(100.0, 0, 0.9)
        self.main._beat_analysis_tick()
        self.main._beat_launch_timer.stop()
        self.main._launch_pending_transition()
        self.main._beat_settle_timer.stop()
        self.main._settle_beat_transition()
        self.main._beat_mix_start_timer.stop()
        self.main._start_aligned_transition()

        self.source.current_times = lambda: (10_000, 180_000)
        self.main._fade_tick()

        self.assertIn(("rate", 1.0), self.calls)
        self.assertEqual(self.calls.count(("rate", 1.0)), 1)
        self.assertIn("ORIGINAL BPM", self.main.status.text())

    def test_beat_toggle_switches_duration_control(self) -> None:
        self.assertFalse(self.main.fade_bars.isHidden())
        self.assertTrue(self.main.fade_seconds.isHidden())

        self.main.beat_match.setChecked(False)

        self.assertTrue(self.main.fade_bars.isHidden())
        self.assertFalse(self.main.fade_seconds.isHidden())

    def test_uncertain_analysis_uses_timed_fallback(self) -> None:
        self.source.beat_info = lambda: None
        self.target.beat_info = lambda: None

        self.main._beat_analysis_tick()

        self.assertFalse(self.main._transition_beat_matched)
        self.assertIn(("rate", 1.0), self.calls)
        self.assertIn(("seek", 0), self.calls)
        self.assertIn("TIMED MIX", self.main.status.text())


if __name__ == "__main__":
    unittest.main()
