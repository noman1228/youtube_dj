from __future__ import annotations

import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QUrl
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtWidgets import QApplication

from app.media import QtMediaDeckEngine, _effective_duration_ms
from app.hls import HlsVideoSource
from app.models import Track


class MediaRecoveryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.engine = QtMediaDeckEngine()
        # Exercise recovery without starting a decoder or touching the network.
        self.engine._player = Mock(spec=QMediaPlayer)
        self.engine._player.position.return_value = 0
        self.engine._player.duration.return_value = 0
        self.engine._player.playbackState.return_value = QMediaPlayer.PlaybackState.StoppedState
        self.engine._track = Track(
            title="Network stream",
            webpage_url="https://www.youtube.com/watch?v=test",
            source="YouTube",
        )
        self.engine._user_stopped = False

    def tearDown(self) -> None:
        self.engine.stop()
        if self.engine._playlist_server:
            self.engine._playlist_server.close()

    def test_karaoke_failure_steps_down_without_resolving_again(self) -> None:
        from app.hls import select_hls_video
        manifest = ('#EXTM3U\n#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="a",URI="audio.m3u8"\n'
                    '#EXT-X-STREAM-INF:RESOLUTION=1920x1080,AUDIO="a"\nhigh.m3u8\n'
                    '#EXT-X-STREAM-INF:RESOLUTION=1280x720,AUDIO="a"\nlow.m3u8\n')
        engine = self.engine
        engine._video = True
        engine._video_height = 1080
        engine._hls_source = select_hls_video(manifest, 'https://example.invalid/master.m3u8')
        engine._play_requested = True
        engine._player.position.return_value = 12345
        engine._player_error(QMediaPlayer.Error.NetworkError, 'buffer failure')
        self.assertEqual(engine._video_max_height, 1079)
        with patch.object(engine, '_begin_resolve') as resolve:
            engine._retry_stream()
        resolve.assert_not_called()
        self.assertEqual(engine._video_height, 720)
        self.assertEqual(engine._retry_position_ms, 12345)
        engine._resume_after_reconnect(QMediaPlayer.MediaStatus.LoadedMedia)
        engine._player.setPosition.assert_called_with(12345)

    def test_new_karaoke_track_starts_uncapped(self) -> None:
        self.engine._video_max_height = 719
        with patch.object(self.engine, '_begin_resolve'):
            self.engine.load(self.engine._track)
        self.assertIsNone(self.engine._video_max_height)

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

    def test_unavailable_format_reports_once_without_reconnecting(self) -> None:
        errors = Mock()
        self.engine.error.connect(errors)
        self.engine._resolving = True
        message = "Requested format is not available. Use --list-formats for a list of available formats"

        self.engine._resolve_failed(self.engine._generation, message)
        self.engine._resolve_failed(self.engine._generation, message)

        errors.assert_called_once()
        self.assertIn(message, errors.call_args.args[0])
        self.assertTrue(self.engine._failure_reported)
        self.assertFalse(self.engine._retry_timer.isActive())
        self.assertEqual(self.engine._retry_attempt, 0)

    def test_resolution_timeout_still_retries(self) -> None:
        errors = Mock()
        self.engine.error.connect(errors)
        self.engine._resolving = True

        self.engine._resolve_failed(self.engine._generation, "The read operation timed out")

        errors.assert_not_called()
        self.assertTrue(self.engine._retry_timer.isActive())
        self.assertEqual(self.engine._retry_attempt, 1)

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

    def test_resolved_duration_wins_over_short_stream_segment(self) -> None:
        self.assertEqual(_effective_duration_ms(10_000, 240_000), 240_000)

    def test_longer_backend_duration_preserves_subsecond_metadata_tail(self) -> None:
        self.assertEqual(_effective_duration_ms(240_750, 240_000), 240_750)

    def test_manifest_window_cannot_override_resolved_duration(self) -> None:
        self.assertEqual(_effective_duration_ms(600_000, 240_000), 240_000)

    def test_play_during_resolution_does_not_restart_resolver(self) -> None:
        self.engine._resolving = True
        self.engine._ready = False
        generation = self.engine._generation

        self.engine.play()

        self.assertEqual(self.engine._generation, generation)
        self.assertTrue(self.engine._autoplay_after_resolve)

    def test_three_second_end_reconnects_instead_of_finishing_song(self) -> None:
        ended = Mock()
        self.engine.ended.connect(ended)
        self.engine._ready = True
        self.engine._play_requested = True
        self.engine._resolved_duration_ms = 240_000
        self.engine._player.position.return_value = 3_000
        self.engine._player.duration.return_value = 3_000

        self.engine._media_status_changed(QMediaPlayer.MediaStatus.EndOfMedia)

        ended.assert_not_called()
        self.assertTrue(self.engine._retry_timer.isActive())
        self.assertEqual(self.engine._retry_attempt, 1)
        self.assertEqual(self.engine._retry_position_ms, 3_000)
        self.assertTrue(self.engine._play_requested)

    def test_position_reset_before_early_end_preserves_resume_position(self) -> None:
        self.engine._ready = True
        self.engine._play_requested = True
        self.engine._resolved_duration_ms = 240_000
        self.engine._player.position.return_value = 3_000
        self.engine._position_changed(3_000)
        self.engine._player.position.return_value = 0
        self.engine._position_changed(0)

        self.engine._media_status_changed(QMediaPlayer.MediaStatus.EndOfMedia)

        self.assertEqual(self.engine._retry_position_ms, 3_000)
        self.assertEqual(self.engine._retry_attempt, 1)

    def test_end_at_full_duration_finishes_normally(self) -> None:
        ended = Mock()
        self.engine.ended.connect(ended)
        self.engine._resolved_duration_ms = 240_000
        self.engine._player.position.return_value = 240_000
        self.engine._play_requested = True

        self.engine._media_status_changed(QMediaPlayer.MediaStatus.EndOfMedia)

        ended.assert_called_once_with()
        self.assertFalse(self.engine._retry_timer.isActive())
        self.assertFalse(self.engine._play_requested)

    def test_end_within_two_seconds_of_full_duration_finishes_normally(self) -> None:
        ended = Mock()
        self.engine.ended.connect(ended)
        self.engine._resolved_duration_ms = 240_000
        self.engine._player.position.return_value = 238_500

        self.engine._media_status_changed(QMediaPlayer.MediaStatus.EndOfMedia)

        ended.assert_called_once_with()
        self.assertEqual(self.engine._retry_attempt, 0)

    def test_local_file_end_does_not_request_network_recovery(self) -> None:
        ended = Mock()
        self.engine.ended.connect(ended)
        self.engine._track.source = "Local file"
        self.engine._resolved_duration_ms = 240_000
        self.engine._player.position.return_value = 3_000

        self.engine._media_status_changed(QMediaPlayer.MediaStatus.EndOfMedia)

        ended.assert_called_once_with()
        self.assertFalse(self.engine._retry_timer.isActive())

    def test_unknown_duration_end_finishes_normally(self) -> None:
        ended = Mock()
        self.engine.ended.connect(ended)
        self.engine._player.position.return_value = 3_000
        self.engine._player.duration.return_value = 3_000

        self.engine._media_status_changed(QMediaPlayer.MediaStatus.EndOfMedia)

        ended.assert_called_once_with()
        self.assertEqual(self.engine._retry_attempt, 0)

    def test_delayed_end_after_stop_does_not_finish_or_restart_song(self) -> None:
        ended = Mock()
        self.engine.ended.connect(ended)
        self.engine.stop()

        self.engine._media_status_changed(QMediaPlayer.MediaStatus.EndOfMedia)

        ended.assert_not_called()
        self.assertFalse(self.engine._retry_timer.isActive())

    def test_delayed_end_during_resolution_does_not_finish_song(self) -> None:
        ended = Mock()
        self.engine.ended.connect(ended)
        self.engine._resolving = True

        self.engine._media_status_changed(QMediaPlayer.MediaStatus.EndOfMedia)

        ended.assert_not_called()
        self.assertEqual(self.engine._retry_attempt, 0)

    def test_end_after_retry_exhaustion_does_not_advance(self) -> None:
        ended = Mock()
        self.engine.ended.connect(ended)
        self.engine._retry_attempt = self.engine._MAX_STREAM_RETRIES
        self.engine._schedule_stream_retry("socket reset")

        self.engine._media_status_changed(QMediaPlayer.MediaStatus.EndOfMedia)

        ended.assert_not_called()
        self.assertFalse(self.engine._retry_timer.isActive())

    def test_stream_that_never_starts_reconnects_after_timeout(self) -> None:
        self.engine._ready = True

        self.engine.play()

        self.assertTrue(self.engine._stall_timer.isActive())
        self.assertEqual(self.engine._stall_timer.interval(), 20_000)
        self.engine._stream_timed_out()
        self.assertEqual(self.engine._retry_attempt, 1)
        self.assertTrue(self.engine._retry_timer.isActive())
        self.assertFalse(self.engine._stall_timer.isActive())

    def test_position_progress_refreshes_timeout_but_duplicate_does_not(self) -> None:
        self.engine._ready = True
        self.engine.play()
        self.engine._player.position.return_value = 3_000

        with patch.object(self.engine._stall_timer, "start") as start:
            self.engine._position_changed(3_000)
            self.engine._position_changed(3_000)

        start.assert_called_once()

    def test_pause_cancels_timeout_and_late_timeout_does_not_reconnect(self) -> None:
        self.engine._ready = True
        self.engine.play()

        self.engine.pause()
        self.engine._stream_timed_out()

        self.assertFalse(self.engine._stall_timer.isActive())
        self.assertEqual(self.engine._retry_attempt, 0)

    def test_stop_cancels_timeout_and_late_timeout_does_not_reconnect(self) -> None:
        self.engine._ready = True
        self.engine.play()

        self.engine.stop()
        self.engine._stream_timed_out()

        self.assertFalse(self.engine._stall_timer.isActive())
        self.assertEqual(self.engine._retry_attempt, 0)

    def test_local_file_playback_does_not_start_network_timeout(self) -> None:
        self.engine._ready = True
        self.engine._track.source = "Local file"

        self.engine.play()
        self.engine._stream_timed_out()

        self.assertFalse(self.engine._stall_timer.isActive())
        self.assertEqual(self.engine._retry_attempt, 0)

    def test_preloaded_stream_without_autoplay_does_not_timeout(self) -> None:
        self.engine._resolved(
            self.engine._generation, self.engine._track,
            "https://example.invalid/audio", 240, "AUDIO STREAM",
        )

        self.engine._stream_timed_out()

        self.engine._player.play.assert_not_called()
        self.assertFalse(self.engine._stall_timer.isActive())
        self.assertEqual(self.engine._retry_attempt, 0)

    def test_selected_hls_playlist_uses_loopback_player_source(self) -> None:
        source = HlsVideoSource("https://example.invalid/master.m3u8", b"#EXTM3U\n", 720)

        self.engine._resolved(self.engine._generation, self.engine._track, source, 217, "720P VIDEO + AUDIO")

        self.engine._player.setSource.assert_called_once()
        url = self.engine._player.setSource.call_args.args[0]
        self.assertEqual(url.host(), "127.0.0.1")
        self.assertTrue(url.path().endswith(".m3u8"))
        self.assertEqual(self.engine._video_height, 720)
        self.engine._player.setSourceDevice.assert_not_called()

    def test_pause_during_resolution_cancels_eventual_autoplay(self) -> None:
        self.engine._resolving = True
        self.engine._autoplay_after_resolve = True
        self.engine._play_requested = True

        self.engine.pause()
        self.engine._resolved(
            self.engine._generation, self.engine._track,
            "https://example.invalid/audio", 240, "AUDIO STREAM",
        )

        self.engine._player.play.assert_not_called()
        self.assertFalse(self.engine._autoplay_after_resolve)
        self.assertFalse(self.engine._stall_timer.isActive())

    def test_play_during_pending_retry_keeps_scheduled_delay(self) -> None:
        self.engine._schedule_stream_retry("socket reset")

        with patch.object(self.engine, "_begin_resolve") as resolve:
            self.engine.play()

        resolve.assert_not_called()
        self.engine._player.play.assert_not_called()
        self.assertTrue(self.engine._play_requested)
        self.assertTrue(self.engine._retry_timer.isActive())
        self.assertEqual(self.engine._retry_attempt, 1)

    def test_repeated_early_end_stops_after_retry_budget(self) -> None:
        errors = Mock()
        ended = Mock()
        self.engine.error.connect(errors)
        self.engine.ended.connect(ended)
        self.engine._resolved_duration_ms = 240_000
        self.engine._play_requested = True

        for _ in range(self.engine._MAX_STREAM_RETRIES + 1):
            self.engine._retry_pending = False
            self.engine._retry_timer.stop()
            self.engine._ready = True
            self.engine._player.position.return_value = 3_000
            self.engine._media_status_changed(QMediaPlayer.MediaStatus.EndOfMedia)

        errors.assert_called_once()
        ended.assert_not_called()
        self.assertEqual(self.engine._retry_attempt, self.engine._MAX_STREAM_RETRIES)
        self.assertFalse(self.engine._retry_timer.isActive())

    def test_manual_play_after_exhaustion_restores_recovery_budget(self) -> None:
        self.engine._ready = False
        self.engine._retry_attempt = self.engine._MAX_STREAM_RETRIES
        self.engine._schedule_stream_retry("socket reset")

        with patch.object(self.engine, "_begin_resolve") as resolve:
            self.engine.play()

        resolve.assert_called_once_with(self.engine._track, autoplay=True)
        self.assertFalse(self.engine._failure_reported)
        self.assertEqual(self.engine._retry_attempt, 0)
        self.engine._player_error(QMediaPlayer.Error.NetworkError, "socket reset again")
        self.assertEqual(self.engine._retry_attempt, 1)

    def test_stale_media_status_preserves_resume_until_ready(self) -> None:
        recovery_states = {
            "_retry_pending": True,
            "_resolving": True,
            "_ready": False,
            "_user_stopped": True,
            "_failure_reported": True,
        }
        statuses = (
            QMediaPlayer.MediaStatus.LoadedMedia,
            QMediaPlayer.MediaStatus.BufferedMedia,
        )
        for attribute, value in recovery_states.items():
            with self.subTest(state=attribute):
                self.engine._player.setPosition.reset_mock()
                self.engine._retry_position_ms = 3_000
                self.engine._ready = True
                setattr(self.engine, attribute, value)

                for status in statuses:
                    self.engine._resume_after_reconnect(status)

                self.assertEqual(self.engine._retry_position_ms, 3_000)
                self.engine._player.setPosition.assert_not_called()
                setattr(self.engine, attribute, not value)

                for status in statuses:
                    self.engine._resume_after_reconnect(status)

                self.engine._player.setPosition.assert_called_once_with(3_000)
                self.assertEqual(self.engine._retry_position_ms, 0)

    def test_synchronous_source_failure_does_not_emit_loaded_or_autoplay(self) -> None:
        loaded = Mock()
        states: list[str] = []
        self.engine.loaded.connect(loaded)
        self.engine.stateChanged.connect(states.append)
        self.engine._resolving = True
        self.engine._play_requested = True
        self.engine._autoplay_after_resolve = True

        def fail_source(source: QUrl) -> None:
            if not source.isEmpty():
                self.engine._player_error(
                    QMediaPlayer.Error.NetworkError, "synchronous source failure"
                )

        self.engine._player.setSource.side_effect = fail_source
        self.engine._resolved(
            self.engine._generation, self.engine._track,
            "https://example.invalid/audio", 240, "AUDIO STREAM",
        )

        loaded.assert_not_called()
        self.engine._player.play.assert_not_called()
        self.assertTrue(self.engine._retry_pending)
        self.assertFalse(self.engine._ready)
        self.assertEqual(self.engine._retry_attempt, 1)
        self.assertEqual(states[-1], "RECONNECTING 1/3")


if __name__ == "__main__":
    unittest.main()
