from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, QThread
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMenu

from app.main_window import MainWindow
from app.models import Track
from app.song_suggestions import SongSuggestions, SuggestionTask, suggestion_pool


class SongSuggestionsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.seed = Track("Seed", "https://youtu.be/seed")
        self.context = Mock(return_value=(self.seed, "left", False, set()))
        self.panel = SongSuggestions(self.context)
        self.panel._timer.stop()
        self.panel._pool = Mock()
        self.panel._pool.tryStart.return_value = True

    def tearDown(self):
        self.panel.shutdown()
        self.panel.deleteLater()

    def settle(self):
        self.panel._tick()
        self.panel._settled_at -= 16
        self.panel._tick()

    def test_lowest_thread_priority_and_no_launch_until_settled(self):
        self.assertEqual(suggestion_pool().threadPriority(), QThread.Priority.IdlePriority)
        self.assertEqual(suggestion_pool().maxThreadCount(), 1)
        self.panel._tick()
        self.panel._pool.tryStart.assert_not_called()
        self.panel._settled_at -= 16
        self.panel._tick()
        self.panel._pool.tryStart.assert_called_once()

    def test_busy_work_resets_settle_delay(self):
        self.panel._tick()
        self.panel._settled_at -= 16
        self.context.return_value = (self.seed, "left", True, set())
        self.panel._tick()
        self.context.return_value = (self.seed, "left", False, set())
        self.panel._tick()
        self.panel._pool.tryStart.assert_not_called()

    def test_seed_change_cancels_and_discards_old_response(self):
        self.settle()
        task = self.panel._task
        self.context.return_value = (Track("New", "https://youtu.be/new"), "right", False, set())
        self.panel._tick()
        self.assertTrue(task.cancelled.is_set())
        self.panel._finished(task.request, [self.seed])
        self.assertEqual(self.panel.list.count(), 0)
        self.assertIsNone(self.panel._task)
        self.panel._settled_at -= 16
        self.panel._tick()
        self.assertEqual(self.panel._task.track.title, "New")

    def test_response_checks_current_track_even_before_next_tick(self):
        self.settle()
        task = self.panel._task
        self.context.return_value = (None, "", False, set())
        self.panel._finished(task.request, [self.seed])
        self.assertEqual(self.panel.list.count(), 0)

    def test_five_results_exclude_queued_tracks_and_do_not_refetch(self):
        self.settle()
        self.context.return_value = (self.seed, "left", False, {"0"})
        tracks = [Track(str(i), f"https://youtu.be/{i}") for i in range(7)]
        self.panel._finished(self.panel._request, tracks)
        self.assertEqual(self.panel.list.count(), 5)
        self.assertEqual(self.panel.list.item(0).text(), "1")
        self.panel._tick()
        self.panel._pool.tryStart.assert_called_once()

    def test_failure_is_quiet_and_not_retried_continuously(self):
        self.settle()
        self.panel._finished(self.panel._request, [])
        self.panel._tick()
        self.panel._pool.tryStart.assert_called_once()
        self.assertEqual(self.panel.status.text(), "No new suggestions")

    def test_shutdown_cancels_without_waiting(self):
        self.settle()
        task = self.panel._task
        self.panel.shutdown()
        self.assertTrue(task.cancelled.is_set())
        self.panel._finished(task.request, [self.seed])
        self.assertEqual(self.panel.list.count(), 0)

    def test_left_click_opens_menu_and_each_destination_is_explicit(self):
        added = Mock()
        self.panel.addRequested.connect(added)
        self.panel._show_tracks([self.seed], set())
        self.panel.resize(230, 240)
        self.panel.show()
        self.app.processEvents()
        for side in ("left", "right"):
            item = self.panel.list.item(0)
            QTest.mouseClick(self.panel.list.viewport(), Qt.MouseButton.LeftButton,
                             pos=self.panel.list.visualItemRect(item).center())
            self.app.processEvents()
            menu = next(menu for menu in self.panel.findChildren(QMenu) if menu.isVisible())
            actions = {action.text(): action for action in menu.actions()}
            self.assertEqual(set(actions), {"Add to Left Deck", "Add to Right Deck"})
            actions[f"Add to {side.title()} Deck"].trigger()
            added.assert_called_with(side, self.seed)
            menu.close()
            self.app.processEvents()

    def test_worker_requests_five_metadata_results_with_short_timeout(self):
        task = SuggestionTask(1, self.seed, set())
        done = Mock()
        task.signals.done.connect(done)
        with patch("ytmusicapi.YTMusic") as client:
            client.return_value.get_watch_playlist.return_value = {
                "tracks": [{"videoId": str(i), "title": str(i)} for i in range(20)],
            }
            task.run()
            session = client.call_args.kwargs["requests_session"]
            self.assertEqual(session.request.keywords["timeout"], 5)
        self.assertEqual(len(done.call_args.args[1]), 5)
        client.return_value.get_watch_playlist.assert_called_once_with(videoId="seed", radio=True, limit=0)

    def test_context_follows_audible_deck_and_defers_to_other_work(self):
        def engine(track, factor):
            return Mock(track=track, _gain=100, _crossfade_factor=factor,
                        _prefetch_task=None, _waveform_analysis=None,
                        has_playback_progress=Mock(return_value=True),
                        is_preparing=Mock(return_value=False),
                        _pool=Mock(activeThreadCount=Mock(return_value=0)))
        right_track = Track("Right", "https://youtu.be/right")
        left = SimpleNamespace(side="left", engine=engine(self.seed, 1), tracks=[self.seed])
        right = SimpleNamespace(side="right", engine=engine(right_track, 0), tracks=[right_track])
        main = SimpleNamespace(left=left, right=right, _transition_active=False,
                               _pending_transition=None, _manual_crossfade=False,
                               _search_dialog=None, _karaoke_window=None)
        track, side, busy, excluded = MainWindow._suggestion_context(main)
        self.assertIs(track, self.seed)
        self.assertEqual(side, "left")
        self.assertFalse(busy)
        self.assertEqual(excluded, {"seed", "right"})
        right.engine._crossfade_factor = 1
        left.engine._crossfade_factor = 0
        self.assertIs(MainWindow._suggestion_context(main)[0], right_track)
        for source in ("load", "prefetch", "analysis", "search", "transition"):
            with self.subTest(source=source):
                right.engine.is_preparing.return_value = source == "load"
                right.engine._prefetch_task = object() if source == "prefetch" else None
                right.engine._waveform_analysis = SimpleNamespace(_active=object(), _pending={}) if source == "analysis" else None
                main._search_dialog = SimpleNamespace(_active_tasks={1: object()}, _pool=Mock()) if source == "search" else None
                main._transition_active = source == "transition"
                self.assertTrue(MainWindow._suggestion_context(main)[2])

    def test_adding_to_playlist_does_not_load_or_play_and_copies_track(self):
        deck = Mock(tracks=[])
        main = Mock(left=deck)
        MainWindow._add_suggestion(main, "left", self.seed)
        track = deck.add_track.call_args.args[0]
        self.assertIsNot(track, self.seed)
        self.assertEqual(track.webpage_url, self.seed.webpage_url)
        self.assertFalse(deck.add_track.call_args.kwargs["load_if_empty"])
        deck.engine.load.assert_not_called()
        deck.engine.play.assert_not_called()


if __name__ == "__main__":
    unittest.main()
