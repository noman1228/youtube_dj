from __future__ import annotations

import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QInputDialog

from app.main_window import MainWindow
from app.models import Track


class KaraokeRemotePlaylistTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.enterContext(patch.object(MainWindow, "_load_playlists"))
        self.enterContext(patch.object(MainWindow, "_save_playlists"))
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
        with patch.object(QInputDialog, "getText", return_value=("CLOSE", True)):
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

    def test_playback_flashes_remote_despite_alternating_status_text(self) -> None:
        with patch.object(self.karaoke.engine, "is_playing", return_value=True):
            self.karaoke.engine.stateChanged.emit("PLAYING")
            self.assertEqual(self.main.karaoke_remote_title.text(), "KARAOKE PLAYING")
            self.assertTrue(self.main._karaoke_blink_timer.isActive())
            self.assertTrue(self.main.karaoke_remote.property("flashOn"))
            self.main._karaoke_blink_timer.timeout.emit()
            self.assertFalse(self.main.karaoke_remote.property("flashOn"))
            self.karaoke.engine.stateChanged.emit("1080P · AAC/MPEG-4")
            self.assertTrue(self.main.karaoke_remote.property("playing"))
            self.assertFalse(self.main.karaoke_remote.property("flashOn"))
            self.main._karaoke_blink_timer.timeout.emit()
            self.assertTrue(self.main.karaoke_remote.property("flashOn"))

    def test_pause_stop_end_and_failure_clear_playback_highlight(self) -> None:
        for state in ("PAUSED", "LOADED", "RECONNECTING 1/3", "PLAYBACK ERROR"):
            with self.subTest(state=state):
                with patch.object(self.karaoke.engine, "is_playing", return_value=True):
                    self.karaoke.engine.stateChanged.emit("PLAYING")
                with patch.object(self.karaoke.engine, "is_playing", return_value=False):
                    self.karaoke.engine.stateChanged.emit(state)
                self.assertFalse(self.main._karaoke_blink_timer.isActive())
                self.assertFalse(self.main.karaoke_remote.property("playing"))
                self.assertFalse(self.main.karaoke_remote.property("flashOn"))
                self.assertEqual(self.main.karaoke_remote_title.text(), "KARAOKE REMOTE")

    def test_blink_timer_detects_stopped_player_without_status_signal(self) -> None:
        with patch.object(self.karaoke.engine, "is_playing", return_value=True):
            self.karaoke.engine.stateChanged.emit("PLAYING")
        with patch.object(self.karaoke.engine, "is_playing", return_value=False):
            self.main._karaoke_blink_timer.timeout.emit()
        self.assertFalse(self.main._karaoke_blink_timer.isActive())
        self.assertFalse(self.main.karaoke_remote.property("playing"))

    def test_projector_close_requires_exact_confirmation(self) -> None:
        self.karaoke.open_projector()
        closed = Mock()
        self.karaoke.projector.closed.connect(closed)
        self.assertFalse(self.karaoke.projector.windowFlags() & Qt.WindowType.WindowCloseButtonHint)
        for reply in (("", True), ("close", True), ("CLOSE", False)):
            with self.subTest(reply=reply), patch.object(QInputDialog, "getText", return_value=reply):
                self.assertFalse(self.karaoke.projector.close())
                self.assertTrue(self.karaoke.projector.isVisible())
                closed.assert_not_called()
        with patch.object(QInputDialog, "getText", return_value=("CLOSE", True)) as prompt:
            self.assertTrue(self.karaoke.projector.close())
        self.assertIs(prompt.call_args.args[0], self.main)
        self.assertFalse(self.karaoke.projector.isVisible())
        closed.assert_called_once()
        self.assertFalse(self.main.karaoke_projector_button.isChecked())

    def test_remote_close_cancel_restores_checked_button(self) -> None:
        self.main.karaoke_projector_button.click()
        with patch.object(QInputDialog, "getText", return_value=("", False)):
            self.main.karaoke_projector_button.click()
        self.assertTrue(self.karaoke.projector.isVisible())
        self.assertTrue(self.main.karaoke_projector_button.isChecked())
        self.assertEqual(self.main.karaoke_projector_button.text(), "CLOSE PROJECTOR")
        with patch.object(QInputDialog, "getText", return_value=("CLOSE", True)):
            self.main.karaoke_projector_button.click()
        self.assertFalse(self.karaoke.projector.isVisible())
        self.assertFalse(self.main.karaoke_projector_button.isChecked())

    def test_closing_or_escaping_lab_keeps_projector_and_playback(self) -> None:
        self.main.show()
        self.karaoke.show()
        self.karaoke.open_projector()
        with patch.object(self.karaoke.engine, "stop") as stop, patch.object(QInputDialog, "getText") as prompt:
            self.karaoke.close()
            self.app.processEvents()
            self.assertTrue(self.karaoke.projector.isVisible())
            self.karaoke.show()
            QTest.keyClick(self.karaoke, Qt.Key.Key_Escape)
            self.app.processEvents()
            self.assertFalse(self.karaoke.isVisible())
            self.assertTrue(self.karaoke.projector.isVisible())
            stop.assert_not_called()
            prompt.assert_not_called()

    def test_main_exit_can_be_cancelled_before_stopping_playback(self) -> None:
        self.main.show()
        self.karaoke.open_projector()
        with patch.object(self.karaoke.engine, "stop") as stop:
            with patch.object(QInputDialog, "getText", return_value=("", False)):
                self.assertFalse(self.main.close())
            self.assertTrue(self.main.isVisible())
            self.assertTrue(self.karaoke.projector.isVisible())
            stop.assert_not_called()
            with patch.object(QInputDialog, "getText", return_value=("CLOSE", True)):
                self.assertTrue(self.main.close())
            stop.assert_called_once()
            self.assertFalse(self.karaoke.projector.isVisible())

    def test_opening_existing_projector_preserves_fullscreen(self) -> None:
        self.karaoke.open_projector()
        self.karaoke.projector.toggle_fullscreen()
        self.karaoke.open_projector()
        self.assertTrue(self.karaoke.projector.isFullScreen())
        QTest.keyClick(self.karaoke.projector, Qt.Key.Key_Escape)
        self.assertFalse(self.karaoke.projector.isFullScreen())
        self.assertTrue(self.karaoke.projector.isVisible())


if __name__ == "__main__":
    unittest.main()
