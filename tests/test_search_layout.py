from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton, QWidget

from app.models import Track
from app.search_dialog import ResultCard


class SearchResultLayoutTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

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
