from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QApplication, QPushButton, QWidget

from app.models import Track
from app.search_dialog import ResultCard


class SearchResultLayoutTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_constructing_results_never_shows_temporary_windows(self) -> None:
        class WindowWatcher(QObject):
            def __init__(self):
                super().__init__()
                self.shown_windows = []

            def eventFilter(self, obj, event):
                if event.type() == QEvent.Type.Show and isinstance(obj, QWidget) and obj.isWindow():
                    self.shown_windows.append(type(obj).__name__)
                return False

        watcher = WindowWatcher()
        self.app.installEventFilter(watcher)
        cards = []
        try:
            for compact in (False, True):
                for index in range(16):
                    cards.append(ResultCard(Track(
                        title=f"Result {index}", webpage_url=f"https://example.test/{index}",
                        description="A search result description",
                    ), compact=compact))
            self.app.processEvents()
            self.assertEqual(watcher.shown_windows, [])
        finally:
            self.app.removeEventFilter(watcher)
            for card in cards:
                card.close()
                card.deleteLater()

    def test_short_and_long_results_use_identical_columns(self) -> None:
        cards = [
            ResultCard(Track(title="Short title", webpage_url="https://example.test/1")),
            ResultCard(
                Track(
                    title="A very long title " * 20,
                    webpage_url="https://example.test/2",
                    description="A very long returned-media description " * 100,
                )
            ),
        ]
        try:
            for card in cards:
                card.resize(860, 155)
                card.show()
            self.app.processEvents()

            button_positions = []
            for card in cards:
                text_panel = card.findChild(QWidget, "ResultTextPanel")
                add_left = next(
                    button
                    for button in card.findChildren(QPushButton)
                    if button.text() == "ADD LEFT"
                )
                self.assertEqual(card.height(), 155)
                self.assertEqual(text_panel.width(), 360)
                button_positions.append(add_left.x())
            self.assertEqual(button_positions[0], button_positions[1])
        finally:
            for card in cards:
                card.close()


if __name__ == "__main__":
    unittest.main()
