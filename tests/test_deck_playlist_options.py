from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import PropertyMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.main_window import MainWindow
from app.models import Track


class DeckPlaylistOptionsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.path = Path(directory) / "playlists.json"
        self.enterContext(patch.object(MainWindow, "_playlist_path", new_callable=PropertyMock, return_value=self.path))
        # Keep Qt's queued startup restore separate from the explicit restore
        # checks below; never resolve media or touch the user's saved playlists.
        with patch.object(MainWindow, "_load_playlists"):
            self.main = MainWindow()
        self.loads = {
            deck.side: self.enterContext(patch.object(deck.engine, "load"))
            for deck in (self.main.left, self.main.right)
        }
        self.track = Track("Selected song", "file:///selected.wav", source="Local file")

    def tearDown(self) -> None:
        self.main.close()

    def test_default_double_click_loads_without_playing_on_both_decks(self) -> None:
        for deck in (self.main.left, self.main.right):
            with self.subTest(side=deck.side):
                self.assertFalse(deck.play_on_double_click.isChecked())
                deck.add_track(self.track, load_if_empty=False)
                deck.playlist.itemDoubleClicked.emit(deck.playlist.item(0))
                self.loads[deck.side].assert_called_once_with(self.track, autoplay=False)

    def test_each_deck_controls_only_its_own_double_click(self) -> None:
        self.main.left.play_on_double_click.setChecked(True)
        for deck in (self.main.left, self.main.right):
            deck.add_track(self.track, load_if_empty=False)
            deck.playlist.itemDoubleClicked.emit(deck.playlist.item(0))
        self.loads["left"].assert_called_once_with(self.track, autoplay=True)
        self.loads["right"].assert_called_once_with(self.track, autoplay=False)

    def test_enabled_option_does_not_change_automatic_loading(self) -> None:
        deck = self.main.left
        deck.play_on_double_click.setChecked(True)
        deck.add_track(self.track)
        self.loads["left"].assert_called_once_with(self.track, autoplay=False)
        self.loads["left"].reset_mock()
        deck.set_tracks([self.track])
        self.loads["left"].assert_called_once_with(self.track, autoplay=False)

    def test_explicit_play_and_next_still_start_playback_when_option_is_off(self) -> None:
        deck = self.main.left
        deck.add_track(self.track, load_if_empty=False)
        deck.play_button.click()
        self.loads["left"].assert_called_once_with(self.track, autoplay=True)
        self.loads["left"].reset_mock()
        deck.next_button.click()
        self.loads["left"].assert_called_once_with(self.track, autoplay=True)

    def test_changing_option_saves_immediately_without_loading_a_song(self) -> None:
        self.main.right.play_on_double_click.setChecked(True)
        saved = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(saved["play_on_double_click"], {"left": False, "right": True})
        self.main.left.play_on_double_click.setChecked(True)
        self.main.right.play_on_double_click.setChecked(False)
        saved = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(saved["play_on_double_click"], {"left": True, "right": False})
        for load in self.loads.values():
            load.assert_not_called()

    def test_restore_preserves_preferences_and_loads_tracks_without_autoplay(self) -> None:
        saved = {
            "left": [self.track.to_dict()], "right": [self.track.to_dict()],
            "play_on_double_click": {"left": True, "right": False},
        }
        self.path.write_text(json.dumps(saved), encoding="utf-8")
        self.main._load_playlists()
        self.assertTrue(self.main.left.play_on_double_click.isChecked())
        self.assertFalse(self.main.right.play_on_double_click.isChecked())
        for load in self.loads.values():
            load.assert_called_once_with(self.track, autoplay=False)
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), saved)

    def test_older_sessions_default_both_options_to_off(self) -> None:
        self.path.write_text(json.dumps({"left": [], "right": []}), encoding="utf-8")
        self.main._load_playlists()
        self.assertFalse(self.main.left.play_on_double_click.isChecked())
        self.assertFalse(self.main.right.play_on_double_click.isChecked())

    def test_played_track_still_requires_reenabling(self) -> None:
        deck = self.main.left
        deck.play_on_double_click.setChecked(True)
        played = Track("Already played", "file:///played.wav", played=True)
        deck.add_track(played, load_if_empty=False)
        deck.playlist.itemDoubleClicked.emit(deck.playlist.item(0))
        self.loads["left"].assert_not_called()


if __name__ == "__main__":
    unittest.main()
