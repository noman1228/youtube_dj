from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtWidgets
from PySide6.QtCore import QFile, QIODevice
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import QApplication, QPushButton, QWidget

from app import ui_loader
from app.appearance_dialog import AppearanceDialog
from app.deck_widget import DeckWidget
from app.main_window import MainWindow
from app.models import Track
from app.search_dialog import ResultCard, SearchDialog
from app.theme import DEFAULT_APPEARANCE


class DesignerFormsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.old_appearance = self.app.property("appearance")
        self.app.setProperty("appearance", DEFAULT_APPEARANCE)
        self.addCleanup(self.app.setProperty, "appearance", self.old_appearance)

    def test_every_form_compiles_and_loads_as_a_designer_preview(self):
        compiler = Path(sys.executable).with_name("pyside6-uic.exe" if os.name == "nt" else "pyside6-uic")
        forms = sorted(ui_loader.UI_DIRECTORY.glob("*.ui"))
        self.assertEqual(len(forms), 10)
        for path in forms:
            with self.subTest(form=path.name):
                tree = ET.parse(path)
                names = [node.attrib['name'] for node in tree.iter() if node.tag in ('widget', 'layout', 'spacer')]
                self.assertEqual(len(names), len(set(names)), 'Designer object names must be unique')
                result = subprocess.run([str(compiler), str(path)], capture_output=True, text=True, encoding='utf-8')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stderr, '')
                compile(result.stdout, str(path), 'exec')
                bases = {node.findtext('class'): node.findtext('extends') for node in tree.findall('customwidgets/customwidget')}

                class PreviewLoader(QUiLoader):
                    def createWidget(self, class_name, parent=None, name=''):
                        return super().createWidget(bases.get(class_name, class_name), parent, name)

                source = QFile(str(path))
                self.assertTrue(source.open(QIODevice.OpenModeFlag.ReadOnly))
                loader = PreviewLoader()
                widget = loader.load(source)
                source.close()
                self.assertIsNotNone(widget, loader.errorString())
                widget.deleteLater()

    def test_saved_designer_edits_reach_the_actual_deck_and_keep_actions(self):
        with tempfile.TemporaryDirectory() as directory:
            forms = Path(directory)
            for source in ui_loader.UI_DIRECTORY.glob('*.ui'):
                shutil.copyfile(source, forms / source.name)
            path = forms / 'deck.ui'
            tree = ET.parse(path)
            tree.find(".//widget[@name='play_button']/property[@name='text']/string").text = 'DESIGNER TRANSPORT'
            tree.write(path, encoding='utf-8')
            with patch.object(ui_loader, 'UI_DIRECTORY', forms):
                deck = DeckWidget('right')
            self.addCleanup(deck.deleteLater)
            self.assertEqual(deck.play_button.text(), 'DESIGNER TRANSPORT')
            self.assertEqual(deck.objectName(), 'RightDeck')
            self.assertIn('right', deck.vu_meter.accessibleName())
            self.assertEqual(deck.waveform._side, 'right')
            self.assertEqual(deck.move_button.text(), 'MOVE LEFT')
            with patch.object(deck.engine, 'toggle_play_pause') as toggle:
                deck.tracks = [Track(title='Test', webpage_url='')]
                deck.current_index = 0
                deck.play_button.click()
                toggle.assert_called_once()

    def test_search_similar_and_result_targets_remain_connected(self):
        search = SearchDialog()
        self.addCleanup(search.deleteLater)
        self.assertEqual([search.provider.itemText(i) for i in range(search.provider.count())],
                         ['Both', 'YouTube', 'YouTube Music'])
        self.assertEqual(search.provider.currentText(), 'Both')
        requests = []
        search.similarRequested.connect(requests.append)
        for side in ('LEFT', 'RIGHT'):
            button = next(b for b in search.findChildren(QPushButton) if b.text() == f'SIMILAR TO {side}')
            button.click()
        self.assertEqual(requests, ['left', 'right'])
        track = Track(title='Test song', webpage_url='', description='Details')
        for compact, targets in [(False, None), (True, [('karaoke', 'ADD TO QUEUE', 'HotButton')])]:
            with self.subTest(compact=compact):
                card = ResultCard(track, targets=targets, compact=compact)
                self.addCleanup(card.deleteLater)
                additions = []
                card.addRequested.connect(lambda side, item: additions.append((side, item)))
                for button in card.findChildren(QPushButton):
                    if button.text().startswith('ADD') and not button.isHidden():
                        button.click()
                expected = ['karaoke'] if compact else ['left', 'right']
                self.assertEqual(additions, [(side, track) for side in expected])
                with patch('app.search_dialog.QMessageBox.information') as details:
                    next(b for b in card.findChildren(QPushButton) if b.text() == 'DETAILS').click()
                    details.assert_called_once()

    def test_appearance_actions_and_composed_main_decks(self):
        parent = QWidget()
        self.addCleanup(parent.deleteLater)
        with patch('app.appearance_dialog.apply_appearance') as apply:
            dialog = AppearanceDialog(parent)
            dialog.preferences['left'] = '#123456'
            dialog.findChild(QPushButton, 'reset_button').click()
            self.assertEqual(dialog.preferences, DEFAULT_APPEARANCE)
            apply.assert_called_with(DEFAULT_APPEARANCE, save=True)
            dialog.show()
            dialog.findChild(QtWidgets.QDialogButtonBox, 'buttons').rejected.emit()
            self.assertFalse(dialog.isVisible())
        with patch.object(MainWindow, '_load_playlists'), patch.object(MainWindow, '_save_playlists'):
            main = MainWindow()
            self.addCleanup(main.deleteLater)
            self.assertIsNot(main.left, main.right)
            main.show()
            self.app.processEvents()
            for deck in (main.left, main.right):
                header = deck.playlist_header
                self.assertTrue(header.hasHeightForWidth())
                for button in (deck.move_button, deck.reenable_button, deck.remove_button):
                    position = button.mapTo(header, button.rect().topLeft())
                    self.assertTrue(header.rect().contains(position))
                    self.assertLessEqual(position.y() + button.height(), header.height())
            karaoke = main._get_karaoke_window()
            self.assertEqual([karaoke.main_side.itemText(i) for i in range(karaoke.main_side.count())],
                             ['LEFT', 'RIGHT'])
            for label, value in [('LEFT', 0), ('CENTER', 500), ('RIGHT', 1000)]:
                next(b for b in main.findChildren(QPushButton) if b.text() == label).click()
                self.assertEqual(main.crossfader.value(), value)
            main.close()


if __name__ == '__main__':
    unittest.main()
