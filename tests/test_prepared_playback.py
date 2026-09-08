from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtWidgets import QApplication

from app.media import PreparedMedia, QtMediaDeckEngine, ResolveTask, _prepared_cache
from app.models import Track


class PreparedPlaybackTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        _prepared_cache.clear()
        self.engine = QtMediaDeckEngine()
        self.engine._pool = Mock()
        self.engine._player = Mock(spec=QMediaPlayer)
        self.engine._player.position.return_value = 0
        self.engine._player.duration.return_value = 240_000
        self.engine._player.playbackState.return_value = QMediaPlayer.PlaybackState.PlayingState
        self.engine._track = Track("Prepared song", "https://example.invalid/track", source="YouTube")
        self.engine._user_stopped = False

    def tearDown(self):
        self.engine.stop()
        self.engine._prepared_media = None
        _prepared_cache.clear()

    def asset(self, suffix="webm"):
        directory = tempfile.TemporaryDirectory(prefix="encoremix-test-")
        path = Path(directory.name) / f"track.{suffix}"
        path.write_bytes(b"offline fixture, never decoded")
        return PreparedMedia(directory, path, 240, "PREPARED AUDIO")

    def test_every_prepared_type_plays_local_without_network_watchdog(self):
        for suffix in ("webm", "mp4", "m3u8"):
            with self.subTest(suffix=suffix):
                self.engine._autoplay_after_resolve = True
                self.engine._resolved(0, self.engine._track, self.asset(suffix), 240, "READY")
                url = self.engine._player.setSource.call_args.args[0]
                self.assertTrue(url.isLocalFile())
                self.assertFalse(self.engine._is_remote_track())
                self.assertFalse(self.engine._stall_timer.isActive())
                with patch.object(self.engine, "_begin_resolve") as resolve:
                    self.engine._stream_timed_out()
                    resolve.assert_not_called()
                self.assertFalse(self.engine._retry_timer.isActive())

    def test_prepared_decoder_error_never_reconnects_or_resolves(self):
        self.engine._resolved(0, self.engine._track, self.asset(), 240, "READY")
        errors = Mock()
        self.engine.error.connect(errors)
        with patch.object(self.engine, "_begin_resolve") as resolve:
            self.engine._player_error(QMediaPlayer.Error.ResourceError, "decoder failed")
            self.engine._retry_stream()
            resolve.assert_not_called()
        errors.assert_called_once()
        self.assertFalse(self.engine._retry_timer.isActive())

    def test_ready_asset_is_pinned_even_after_cache_eviction(self):
        asset = self.asset()
        path = asset.path
        self.engine._resolved(0, self.engine._track, asset, 240, "READY")
        _prepared_cache.clear()
        del asset
        self.assertTrue(path.is_file())
        self.engine.stop()
        self.engine.play()
        self.assertTrue(path.is_file())
        self.engine._pool.start.assert_not_called()

    def test_playing_state_does_not_start_fade_until_position_moves(self):
        started = Mock()
        self.engine.playbackStarted.connect(started)
        self.engine._ready = True
        self.engine._play_requested = True
        self.engine._playback_state_changed(QMediaPlayer.PlaybackState.PlayingState)
        started.assert_not_called()
        self.engine._position_changed(100)
        self.engine._position_changed(200)
        started.assert_called_once()
        self.assertTrue(self.engine.has_playback_progress())
        self.engine._last_progress_at = time.monotonic() - 2
        self.assertFalse(self.engine.has_playback_progress())

    def test_seek_requires_fresh_progress(self):
        self.engine._ready = True
        self.engine._play_requested = True
        self.engine._position_changed(100)
        self.engine.seek_ms(5000)
        self.engine._position_changed(5000)
        self.assertFalse(self.engine.has_playback_progress())
        self.engine._position_changed(5100)
        self.assertTrue(self.engine.has_playback_progress())

    def test_stale_resolve_cannot_replace_audible_source(self):
        asset = self.asset()
        self.engine._generation = 2
        self.engine._resolved(1, self.engine._track, asset, 240, "READY")
        self.engine._player.setSource.assert_not_called()

    def test_prefetch_has_no_effect_on_current_player(self):
        next_track = Track("Next", "https://example.invalid/next")
        self.engine.prefetch(next_track)
        task = self.engine._prefetch_task
        self.engine._prefetched(task.generation, next_track, self.asset(), 240, "READY")
        self.engine._player.setSource.assert_not_called()
        self.engine._player.stop.assert_not_called()
        self.engine._player.play.assert_not_called()
        self.assertIsNotNone(self.engine._prefetched_media)

    def test_stop_cancels_current_and_speculative_preparation(self):
        self.engine.load(self.engine._track)
        self.engine.prefetch(Track("Next", "https://example.invalid/next"))
        current = list(self.engine._resolve_tasks.values())[0]
        next_task = self.engine._prefetch_task
        self.engine.stop()
        self.assertTrue(current.cancelled.is_set())
        self.assertTrue(next_task.cancelled.is_set())
        self.assertFalse(self.engine.is_preparing())

    def test_cached_track_load_skips_extractor_and_download(self):
        track = self.engine._track
        asset = self.asset()
        _prepared_cache[(track.webpage_url, False, None)] = asset
        task = ResolveTask(1, track)
        resolved = Mock()
        task.signals.resolved.connect(resolved)
        with patch("yt_dlp.YoutubeDL") as extractor:
            task.run()
        extractor.assert_not_called()
        self.assertIs(resolved.call_args.args[2], asset)

    def test_preparation_failure_does_not_publish_partial_file(self):
        track = self.engine._track
        task = ResolveTask(1, track)
        resolved = Mock()
        failed = Mock()
        task.signals.resolved.connect(resolved)
        task.signals.failed.connect(failed)
        with patch("yt_dlp.YoutubeDL") as cls, patch("app.media.prepare_media", side_effect=RuntimeError("missing fragment")):
            cls.return_value.__enter__.return_value.extract_info.return_value = {
                "url": "https://example.invalid/audio", "duration": 240,
            }
            task.run()
        resolved.assert_not_called()
        failed.assert_called_once()
        self.assertEqual(len(_prepared_cache), 0)


if __name__ == "__main__":
    unittest.main()
