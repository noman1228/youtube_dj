from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.main_window import MainWindow
from app.models import Track


class KaraokeRemotePlaylistTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.main = MainWindow()
        self.karaoke = self.main._get_karaoke_window()
        self.load_calls: list[tuple[str, bool]] = []
        self.karaoke.engine.load = lambda track, autoplay=False: self.load_calls.append(
            (track.title, autoplay)
        )

        self.karaoke.tracks = [
            Track(
                title="First song",
                webpage_url="https://example.test/first",
                karaoke_artist="Singer One",
            ),
            Track(
                title="Played song",
                webpage_url="https://example.test/played",
                karaoke_artist="Singer Two",
                played=True,
            ),
        ]
        for index, track in enumerate(self.karaoke.tracks):
            self.karaoke.playlist.addItem(self.karaoke._make_item(index, track))
        self.karaoke.queueChanged.emit()

    def tearDown(self) -> None:
        self.main.close()

    def test_main_window_mirrors_karaoke_queue(self) -> None:
        self.assertEqual(self.main.karaoke_playlist.count(), 2)
        self.assertIn("Singer One", self.main.karaoke_playlist.item(0).text())
        self.assertTrue(self.main.karaoke_playlist.item(1).font().strikeOut())

    def test_double_click_target_replays_exact_entry(self) -> None:
        item = self.main.karaoke_playlist.item(1)
        self.main._play_karaoke_queue_item(item)

        self.assertEqual(self.karaoke.current_index, 1)
        self.assertFalse(self.karaoke.tracks[1].played)
        self.assertEqual(self.load_calls, [("Played song", True)])
        self.assertEqual(self.main.karaoke_playlist.currentRow(), 1)


if __name__ == "__main__":
    unittest.main()
