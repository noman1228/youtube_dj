from __future__ import annotations

import os
import time
import unittest
from unittest.mock import patch

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
        for method in ("_load_playlists", "_save_playlists"):
            patcher = patch.object(MainWindow, method, new=lambda self: None)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.main = MainWindow()
        self.source = self.main.left.engine
        self.target = self.main.right.engine
        self.calls: list[tuple[str, float | int | bool]] = []
        self.target.pause = lambda: self.calls.append(("pause", True))
        self.target.seek_ms = lambda value: self.calls.append(("seek", value))
        self.target.set_playback_rate = lambda value: self.calls.append(("rate", value))
        self.target.set_analysis_muted = lambda value: self.calls.append(("mute", value))
        self.target.is_playing = lambda: True
        self.target.is_preparing = lambda: False
        self.target.has_playback_progress = lambda: True
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

    def test_incoming_deck_restores_original_tempo_after_mix(self) -> None:
        self.source.beat_info = lambda: BeatInfo(120.0, 0, 0.9)
        self.target.beat_info = lambda: BeatInfo(100.0, 0, 0.9)
        self.main._beat_analysis_tick()
        self.main._beat_launch_timer.stop()
        self.main._launch_pending_transition()
        self.main._beat_settle_timer.stop()
        self.main._settle_beat_transition()
        self.main._beat_mix_start_timer.stop()
        self.main._start_aligned_transition()

        self.calls.clear()
        self.source.current_times = lambda: (10_000, 180_000)
        self.main._fade_tick()

        self.assertEqual([call for call in self.calls if call[0] == "rate"], [("rate", 1.0)])
        self.assertEqual(self.main.crossfader.value(), self.main._CROSSFADER_MAX)
        self.assertIn("ORIGINAL TEMPO", self.main.status.text())
        self.main._fade_tick()
        self.assertEqual([call for call in self.calls if call[0] == "rate"], [("rate", 1.0)])

    def test_preparing_incoming_media_does_not_expire_analysis_start(self) -> None:
        self.main._beat_analysis_started = 0.0
        self.main._beat_analysis_requested = 100.0
        self.target.is_preparing = lambda: True
        with patch("app.main_window.time.monotonic", return_value=120.0):
            self.main._beat_analysis_tick()
        self.assertEqual(self.main._pending_transition, ("left", "right"))
        self.target.is_preparing = lambda: False
        with patch("app.main_window.time.monotonic", return_value=125.0):
            self.main._beat_analysis_tick()
        self.assertEqual(self.main._pending_transition, ("left", "right"))
        with patch("app.main_window.time.monotonic", return_value=132.0):
            self.main._beat_analysis_tick()
        self.assertIsNone(self.main._pending_transition)

    def test_aligned_transition_waits_for_audio_after_seek(self) -> None:
        self.main._transition_beat_matched = True
        self.main._beat_phase_settling = True
        self.target.has_playback_progress = lambda: False
        self.main._start_aligned_transition()
        self.assertFalse(self.main._transition_active)
        self.assertTrue(self.main._beat_phase_settling)
        self.assertNotIn(("mute", False), self.calls)
        self.assertTrue(self.main._beat_mix_start_timer.isActive())
        self.main._beat_mix_start_timer.stop()
        self.target.has_playback_progress = lambda: True
        self.main._start_aligned_transition()
        self.assertTrue(self.main._transition_active)
        self.assertIn(("mute", False), self.calls)

    def test_timed_mix_holds_gains_and_does_not_jump_after_buffering(self) -> None:
        with patch("app.main_window.time.monotonic", return_value=100.0):
            self.main._begin_transition("left", "right", duration=8.0)
        with patch("app.main_window.time.monotonic", return_value=102.0):
            self.main._fade_tick()
            held_gain = self.main.crossfader.value()
            self.target.has_playback_progress = lambda: False
            self.main._fade_tick()
        with patch("app.main_window.time.monotonic", return_value=110.0):
            self.main._fade_tick()
        self.assertEqual(self.main.crossfader.value(), held_gain)
        self.assertTrue(self.main._transition_active)
        self.assertIn("MIX HELD", self.main.status.text())
        self.target.has_playback_progress = lambda: True
        with patch("app.main_window.time.monotonic", return_value=111.0):
            self.main._fade_tick()
        self.assertEqual(self.main.crossfader.value(), held_gain)
        with patch("app.main_window.time.monotonic", return_value=113.0):
            self.main._fade_tick()
        self.assertGreater(self.main.crossfader.value(), held_gain)

    def test_beat_mix_holds_outgoing_gain_when_incoming_stops(self) -> None:
        self.source.beat_info = lambda: BeatInfo(120.0, 0, 0.9)
        self.main._transition_total_beats = 16
        self.main._begin_transition("left", "right", duration=8.0, beat_matched=True)
        self.source.current_times = lambda: (2_500, 180_000)
        self.main._fade_tick()
        held_gain = self.main.crossfader.value()
        self.target.is_playing = lambda: False
        self.main._fade_tick()
        self.source.current_times = lambda: (4_500, 180_000)
        self.main._fade_tick()
        self.assertEqual(self.main.crossfader.value(), held_gain)
        self.source.current_times = lambda: (5_000, 180_000)
        self.target.is_playing = lambda: True
        self.main._fade_tick()
        self.assertEqual(self.main.crossfader.value(), held_gain)
        self.assertTrue(self.main._transition_active)

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

    def test_automix_ignores_unreliable_or_too_early_duration(self) -> None:
        self.main._pending_transition = None
        self.main._beat_analysis_target = None
        self.main._request_automix = lambda side: self.calls.append(("mix", side))
        self.main.crossfader.setValue(0)
        self.source.is_playing = lambda: True
        self.main.left.current_remaining_ms = lambda: None

        self.main._automation_tick()
        self.assertNotIn(("mix", "left"), self.calls)

        self.main.left.current_remaining_ms = lambda: 10_000
        self.source.current_times = lambda: (1_000, 11_000)
        self.main._automation_tick()
        self.assertNotIn(("mix", "left"), self.calls)

        self.source.current_times = lambda: (170_000, 180_000)
        self.main._automation_tick()
        self.assertIn(("mix", "left"), self.calls)


if __name__ == "__main__":
    unittest.main()
