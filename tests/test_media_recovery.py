from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtWidgets import QApplication

from app.media import QtMediaDeckEngine
from app.models import Track


class MediaRecoveryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.engine = QtMediaDeckEngine()
        self.engine._track = Track(
            title="Network stream",
            webpage_url="https://www.youtube.com/watch?v=test",
            source="YouTube",
        )
        self.engine._user_stopped = False

    def tearDown(self) -> None:
        self.engine.stop()

    def test_network_error_schedules_only_one_reconnect(self) -> None:
        states: list[str] = []
        errors: list[str] = []
        self.engine.stateChanged.connect(states.append)
        self.engine.error.connect(errors.append)

        self.engine._player_error(QMediaPlayer.Error.NetworkError, "socket reset")
        self.engine._player_error(QMediaPlayer.Error.NetworkError, "duplicate error")

        self.assertTrue(self.engine._retry_timer.isActive())
        self.assertEqual(self.engine._retry_attempt, 1)
        self.assertEqual(states[-1], "RECONNECTING 1/3")
        self.assertEqual(errors, [])

    def test_end_of_media_does_not_advance_during_reconnect(self) -> None:
        ended_count = 0

        def ended() -> None:
            nonlocal ended_count
            ended_count += 1

        self.engine.ended.connect(ended)
        self.engine._retry_pending = True
        self.engine._media_status_changed(QMediaPlayer.MediaStatus.EndOfMedia)
        self.assertEqual(ended_count, 0)

    def test_retry_exhaustion_reports_one_safe_failure(self) -> None:
        errors: list[str] = []
        self.engine.error.connect(errors.append)
        self.engine._retry_attempt = self.engine._MAX_STREAM_RETRIES

        self.engine._schedule_stream_retry("socket reset")
        self.engine._schedule_stream_retry("duplicate error")

        self.assertEqual(len(errors), 1)
        self.assertIn("stopped safely", errors[0])

    def test_stale_player_error_is_ignored_during_fresh_resolution(self) -> None:
        self.engine._resolving = True
        self.engine._player_error(QMediaPlayer.Error.NetworkError, "stale socket error")
        self.assertEqual(self.engine._retry_attempt, 0)
        self.assertFalse(self.engine._retry_timer.isActive())

    def test_stop_cancels_pending_autoplay(self) -> None:
        self.engine._autoplay_after_resolve = True
        self.engine._play_requested = True
        self.engine.stop()
        self.assertFalse(self.engine._autoplay_after_resolve)
        self.assertFalse(self.engine._play_requested)

    def test_delayed_error_after_stop_does_not_restart_stream(self) -> None:
        self.engine.stop()
        self.engine._player_error(QMediaPlayer.Error.NetworkError, "late error")
        self.assertEqual(self.engine._retry_attempt, 0)
        self.assertFalse(self.engine._retry_timer.isActive())


if __name__ == "__main__":
    unittest.main()
