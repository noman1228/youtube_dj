from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QFrame, QScrollArea

from app.main_window import MainWindow
from app.theme import APP_STYLE


class CenterLayoutTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        for method in ("_load_playlists", "_save_playlists"):
            patcher = patch.object(MainWindow, method, new=lambda self: None)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.old_style = self.app.styleSheet()
        self.app.setStyleSheet(APP_STYLE)
        self.main = MainWindow()
        self.main.show()
        self.center = self.main.findChild(QFrame, "CenterConsole")
        self.scroll = self.center.findChild(QScrollArea, "CenterControlsScroll")

    def tearDown(self) -> None:
        self.main.close()
        self.app.setStyleSheet(self.old_style)

    def test_scroll_surface_keeps_console_background_after_resize(self) -> None:
        for height in (1100, 720, 900, 1100):
            with self.subTest(height=height):
                self.main.resize(1550, height)
                self.app.processEvents()
                self.scroll.verticalScrollBar().setValue(self.scroll.verticalScrollBar().maximum())
                self.app.processEvents()
                self.assertEqual(self.center.y(), self.main.left.y())
                self.assertEqual(self.center.height(), self.main.left.height())
                image = self.center.grab().toImage()
                # The rounded frame and the viewport share one surface even
                # when extra space opens below the scrolling controls.
                frame_color = image.pixelColor(8, self.center.height() // 2)
                viewport_color = image.pixelColor(self.scroll.x(), self.scroll.y())
                self.assertEqual(viewport_color, frame_color)
                if height == 1100:
                    bottom_color = image.pixelColor(self.scroll.x() + 5, self.scroll.geometry().bottom() - 5)
                    self.assertEqual(bottom_color, frame_color)

    def test_karaoke_background_stays_with_children_while_scrolling(self) -> None:
        remote = self.main.karaoke_remote
        remote.setProperty("playing", True)
        remote.setProperty("flashOn", True)
        self.main._refresh_karaoke_highlight()
        for height in (1100, 720, 900, 1100):
            with self.subTest(height=height):
                self.main.resize(1550, height)
                self.app.processEvents()
                self.scroll.verticalScrollBar().setValue(self.scroll.verticalScrollBar().maximum())
                self.app.processEvents()
                image = remote.grab().toImage()
                self.assertEqual(image.pixelColor(5, remote.height() // 2).name(), "#ffcf33")
                for child in (self.main.karaoke_remote_title, self.main.karaoke_lab_button,
                              self.main.karaoke_playlist):
                    self.assertTrue(remote.rect().contains(child.geometry()))


if __name__ == "__main__":
    unittest.main()
