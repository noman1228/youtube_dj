from __future__ import annotations

import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QInputDialog

from app.deck_widget import DeckWidget
from app.karaoke_window import KaraokeWindow
from app.models import Track


class QueuePrefetchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.deck = DeckWidget("left")
        self.karaoke = KaraokeWindow()
        for widget in (self.deck, self.karaoke):
            engine = widget.engine
            engine.prefetch = Mock()
            engine.load = Mock(side_effect=lambda track, autoplay=False, current=engine: setattr(current, "_track", track))
            engine.stop = Mock()
        self.first = Track("First", "https://example.invalid/first", duration_seconds=180)
        self.second = Track("Second", "https://example.invalid/second", duration_seconds=180)
        self.third = Track("Third", "https://example.invalid/third", duration_seconds=180)

    def tearDown(self) -> None:
        self.karaoke.projector.deleteLater()
        self.karaoke.deleteLater()
        self.deck.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def _populate(self, widget, tracks: list[Track], index: int = 0) -> None:
        widget.tracks = tracks
        for row, track in enumerate(tracks):
            widget.playlist.addItem(widget._make_item(row, track))
        if isinstance(widget, DeckWidget):
            widget.load_index(index)
        else:
            widget._load_index(index)

    def test_loaded_decks_prepare_next_unplayed_track_and_wrap_queue(self) -> None:
        skipped = Track("Played", "https://example.invalid/played", played=True)
        for widget in (self.deck, self.karaoke):
            with self.subTest(widget=type(widget).__name__):
                self._populate(widget, [self.first, skipped, self.second])
                widget.engine.prefetch.assert_called_with(self.second)
                self.assertIs(widget.engine.track, self.first)
                widget.engine.stop.assert_not_called()
                if isinstance(widget, DeckWidget):
                    widget.load_index(2)
                else:
                    widget._load_index(2)
                widget.engine.prefetch.assert_called_with(self.first)

    def test_adding_music_prepares_next_without_reloading_active_deck(self) -> None:
        self.deck.add_track(self.first)
        self.deck.engine.load.reset_mock()
        self.deck.add_track(self.second)
        self.deck.engine.prefetch.assert_called_with(self.second)
        self.deck.engine.load.assert_not_called()
        self.deck.engine.stop.assert_not_called()
        self.assertIs(self.deck.engine.track, self.first)

    def test_adding_singer_prepares_next_without_reloading_active_karaoke(self) -> None:
        self._populate(self.karaoke, [self.first])
        self.karaoke.engine.load.reset_mock()
        with patch.object(QInputDialog, "getText", return_value=("Next singer", True)):
            self.karaoke._add_result("karaoke", self.second)
        prepared = self.karaoke.engine.prefetch.call_args.args[0]
        self.assertEqual(prepared.webpage_url, self.second.webpage_url)
        self.karaoke.engine.load.assert_not_called()
        self.karaoke.engine.stop.assert_not_called()
        self.assertIs(self.karaoke.engine.track, self.first)

    def test_removing_queued_track_updates_prefetch_without_stopping_current(self) -> None:
        for widget in (self.deck, self.karaoke):
            with self.subTest(widget=type(widget).__name__):
                self._populate(widget, [self.first, self.second, self.third])
                widget.engine.load.reset_mock()
                widget.playlist.setCurrentRow(1)
                if isinstance(widget, DeckWidget):
                    widget.remove_selected()
                else:
                    widget._remove_selected()
                widget.engine.prefetch.assert_called_with(self.third)
                widget.engine.load.assert_not_called()
                widget.engine.stop.assert_not_called()

    def test_reordering_music_prefetches_new_next_track(self) -> None:
        self._populate(self.deck, [self.first, self.second, self.third])
        self.deck.engine.load.reset_mock()
        item = self.deck.playlist.takeItem(2)
        self.deck.playlist.insertItem(1, item)
        self.deck._sync_order_from_widget()
        self.deck.engine.prefetch.assert_called_with(self.third)
        self.deck.engine.load.assert_not_called()
        self.deck.engine.stop.assert_not_called()

    def test_only_current_track_does_not_duplicate_preparation(self) -> None:
        for widget in (self.deck, self.karaoke):
            with self.subTest(widget=type(widget).__name__):
                self._populate(widget, [self.first])
                widget.engine.prefetch.assert_called_with(None)


if __name__ == "__main__":
    unittest.main()
