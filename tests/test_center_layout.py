from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication, QFrame, QScrollArea, QStyleFactory, QWidget

from app.main_window import MainWindow
from app.models import Track
from app.theme import APP_STYLE, DEFAULT_APPEARANCE, THEMES, apply_appearance


class CenterLayoutTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        # The Windows offscreen backend needs explicit fonts for realistic sizing.
        fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
        for name in ("segoeui.ttf", "segoeuib.ttf", "seguisb.ttf"):
            if (fonts / name).is_file():
                QFontDatabase.addApplicationFont(str(fonts / name))

    def setUp(self) -> None:
        for method in ("_load_playlists", "_save_playlists"):
            patcher = patch.object(MainWindow, method, new=lambda self: None)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.old_style = self.app.styleSheet()
        self.old_appearance = self.app.property("appearance")
        self.app.setProperty("appearance", DEFAULT_APPEARANCE)
        self.app.setStyleSheet(APP_STYLE)
        self.main = MainWindow()
        self.main.show()
        self.center = self.main.findChild(QFrame, "CenterConsole")
        self.scroll = self.center.findChild(QScrollArea, "CenterControlsScroll")

    def tearDown(self) -> None:
        self.main.close()
        self.app.setStyleSheet(self.old_style)
        self.app.setProperty("appearance", self.old_appearance)

    def test_resizing_preserves_equal_decks_and_contains_grouped_controls(self) -> None:
        mix = self.main.findChild(QFrame, "MixControls")
        self.assertTrue(mix.isAncestorOf(self.main.crossfader))
        self.assertTrue(self.main.karaoke_remote.isAncestorOf(self.main.projector_preview))
        for width, height in ((1180, 720), (1550, 900), (1920, 1080), (1180, 720)):
            for beat_mode in (False, True):
                with self.subTest(size=(width, height), beat_mode=beat_mode):
                    self.main.resize(width, height)
                    self.main.beat_match.setChecked(beat_mode)
                    self.app.processEvents()
                    self.assertLessEqual(abs(self.main.left.width() - self.main.right.width()), 1)
                    self.assertLess(self.main.left.geometry().right(), self.center.x())
                    self.assertLess(self.center.geometry().right(), self.main.right.x())
                    self.assertLessEqual(self.scroll.widget().width(), self.scroll.viewport().width())
                    for group in (mix, self.main.karaoke_remote):
                        for child in group.findChildren(QWidget, options=Qt.FindChildOption.FindDirectChildrenOnly):
                            if child.isVisible():
                                self.assertTrue(group.rect().contains(child.geometry()), child.objectName())

    def test_scroll_surface_keeps_console_background_after_resize(self) -> None:
        for height in (1100, 720, 900, 1100):
            with self.subTest(height=height):
                self.main.resize(1550, height)
                self.app.processEvents()
                self.scroll.verticalScrollBar().setValue(self.scroll.verticalScrollBar().maximum())
                self.app.processEvents()
                self.assertEqual(self.center.y(), self.main.left.y())
                self.assertEqual(self.center.height(), self.main.left.height())
                image = self.center.grab().toImage().scaled(self.center.size())
                # Sample the outer gutter: the queue now fills the former
                # blank area at the bottom of the scrolling controls.
                frame_color = image.pixelColor(8, self.center.height() // 2)
                viewport_color = image.pixelColor(self.scroll.x(), self.scroll.y())
                self.assertEqual(viewport_color, frame_color)
                if height == 1100:
                    bottom_color = image.pixelColor(self.scroll.x(), self.scroll.geometry().bottom() - 5)
                    self.assertEqual(bottom_color, frame_color)

    def test_extra_height_expands_karaoke_queue_with_compact_suggestions(self) -> None:
        mix = self.main.findChild(QFrame, "MixControls")
        remote = self.main.karaoke_remote
        measurements = []
        for height in (1100, 1300, 1100):
            self.main.resize(1550, height)
            self.app.processEvents()
            self.assertEqual(mix.x(), remote.x())
            self.assertEqual(mix.width(), remote.width())
            self.assertEqual(self.scroll.verticalScrollBar().maximum(), 0)
            self.assertEqual(self.main.song_suggestions.geometry().bottom(), self.scroll.widget().height() - 3)
            measurements.append((mix.height(), self.main.karaoke_playlist.height()))
        self.assertEqual(measurements[0][0], measurements[1][0])
        self.assertEqual(measurements[1][1] - measurements[0][1], 200)
        self.assertEqual(measurements[0], measurements[2])

    def test_windowed_layout_shows_monitor_controls_and_five_suggestions(self) -> None:
        suggestions = self.main.song_suggestions
        suggestions._show_tracks([Track(f"Song {i}", f"https://youtu.be/{i}") for i in range(5)], set())
        for width, height in ((1180, 720), (1550, 900)):
            self.main.resize(width, height)
            for projector_open in (False, True):
                self.main._sync_karaoke_projector_button(projector_open)
                self.app.processEvents()
                self.assertEqual(self.scroll.verticalScrollBar().maximum(), 0)
                self.assertEqual(suggestions.list.verticalScrollBar().maximum(), 0)
                self.assertTrue(suggestions.list.viewport().rect().contains(
                    suggestions.list.visualItemRect(suggestions.list.item(4))))
                for widget in (self.main.projector_preview, self.main.karaoke_play_button,
                               self.main.karaoke_volume, self.main.karaoke_playlist):
                    self.assertTrue(widget.isVisible())
                self.assertFalse(hasattr(self.main, "karaoke_tabs"))
                self.assertFalse(hasattr(self.main, "karaoke_fade_seconds"))

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
                image = remote.grab().toImage().scaled(remote.size())
                self.assertEqual(image.pixelColor(5, remote.height() // 2).name(), "#ffcf33")
                for child in (self.main.karaoke_remote_title, self.main.projector_preview,
                              self.main.karaoke_playlist):
                    self.assertTrue(remote.rect().contains(child.geometry()))

    def _settle_layout(self) -> None:
        # Scrollbar visibility, viewport margins and height-for-width layouts
        # can each post another layout request during the same resize.
        for _ in range(4):
            self.app.processEvents()

    def _recreate_with_style(self, style: str) -> None:
        self.main.close()
        self.main.deleteLater()
        self.app.setStyle(style)
        self.app.setFont(QFont("Segoe UI", 10))
        apply_appearance(DEFAULT_APPEARANCE)
        self.main = MainWindow()
        # Match main.py: appearance is applied before AND after construction.
        apply_appearance(DEFAULT_APPEARANCE)
        self.main.show()
        self.center = self.main.findChild(QFrame, "CenterConsole")
        self.scroll = self.center.findChild(QScrollArea, "CenterControlsScroll")
        self._settle_layout()

    def _assert_main_symmetry(self) -> None:
        left, right, center = self.main.left, self.main.right, self.center
        self.assertLessEqual(abs(left.width() - right.width()), 1)
        self.assertLessEqual(abs(2 * center.x() + center.width() - self.main.width()), 1)
        self.assertEqual(left.x(), self.main.centralWidget().width() - right.x() - right.width())
        self.assertEqual(center.x() - left.x() - left.width(), right.x() - center.x() - center.width())
        self.assertEqual((left.y(), left.height()), (center.y(), center.height()))
        self.assertEqual((right.y(), right.height()), (center.y(), center.height()))
        for name in ("art", "gain", "waveform", "progress", "play_button", "playlist_header", "playlist"):
            a, b = getattr(left, name), getattr(right, name)
            self.assertEqual(a.mapTo(left, QPoint()).y(), b.mapTo(right, QPoint()).y(), name)
            self.assertEqual(a.height(), b.height(), name)

        viewport = self.scroll.viewport()
        self.assertEqual(viewport.x(), self.scroll.width() - viewport.x() - viewport.width())
        self.assertEqual(self.scroll.widget().width(), viewport.width())
        self.assertEqual(self.scroll.horizontalScrollBar().maximum(), 0)
        self.assertEqual(self.scroll.horizontalScrollBar().value(), 0)
        groups = (self.main.findChild(QFrame, "MixControls"), self.main.karaoke_remote,
                  self.main.song_suggestions)
        for group in groups:
            x = group.mapTo(center, QPoint()).x()
            self.assertEqual(x, center.width() - x - group.width(), group.objectName())
            x_in_view = group.mapTo(viewport, QPoint()).x()
            self.assertGreaterEqual(x_in_view, 0)
            self.assertLessEqual(x_in_view + group.width(), viewport.width())
            self.assertEqual(group.width(), groups[0].width())
        # These full-width controls must share the same left and right inset.
        controls = (self.main.crossfader, self.main.status, self.main.projector_preview,
                    self.main.karaoke_play_button, self.main.karaoke_playlist,
                    self.main.song_suggestions.list)
        insets = []
        for control in controls:
            parent = control.parentWidget()
            self.assertEqual(control.x(), parent.width() - control.x() - control.width())
            insets.append(control.x())
        self.assertEqual(len(set(insets)), 1)

    def _assert_visible_frame_edges(self) -> None:
        # Inspect the composed viewport, not standalone frame grabs: a clipped
        # right border still looks correct when grabbed outside its scroll area.
        image = self.center.grab().toImage().scaled(self.center.size())
        viewport = self.scroll.viewport()
        top = viewport.mapTo(self.center, QPoint()).y()
        bottom = top + viewport.height()
        for group in (self.main.findChild(QFrame, "MixControls"), self.main.karaoke_remote,
                      self.main.song_suggestions):
            origin = group.mapTo(self.center, QPoint())
            for y in range(max(top, origin.y()), min(bottom, origin.y() + group.height())):
                for inset in range(3):
                    left = image.pixelColor(origin.x() + inset, y).getRgb()
                    right = image.pixelColor(origin.x() + group.width() - 1 - inset, y).getRgb()
                    self.assertLessEqual(max(abs(a - b) for a, b in zip(left, right)), 1,
                                         (group.objectName(), inset, y, left, right))

    def test_native_scrollbars_and_theme_changes_preserve_symmetry_after_resizing(self) -> None:
        self.addCleanup(self.app.setStyle, self.app.style().objectName())
        self.addCleanup(self.app.setFont, self.app.font())
        styles = [style for style in QStyleFactory.keys() if style.lower() in ("fusion", "windows11")]
        for style in styles:
            self._recreate_with_style(style)
            self.main.song_suggestions._show_tracks(
                [Track(f"Song {i}", f"https://youtu.be/{i}") for i in range(5)], set())
            # This normal runtime status makes the native scrollbar appear at
            # the minimum height. It previously hid eight pixels of the frame.
            self.main.status.setText("ADDED TO RIGHT:\nA long song title with artist and live performance details")
            for theme in THEMES:
                apply_appearance({**DEFAULT_APPEARANCE, "theme": theme})
                for size in ((1550, 900), (1180, 720), (1181, 721), (1920, 1080), (1180, 720), (1550, 900)):
                    for beat_mode in (False, True):
                        with self.subTest(style=style, theme=theme, size=size, beat_mode=beat_mode):
                            self.main.resize(*size)
                            self.main.beat_match.setChecked(beat_mode)
                            self._settle_layout()
                            self.assertEqual(self.main.size().toTuple(), size)
                            self._assert_main_symmetry()
                            for fraction in (0, 1):
                                bar = self.scroll.verticalScrollBar()
                                bar.setValue(bar.maximum() * fraction)
                                self._settle_layout()
                                self._assert_visible_frame_edges()
                            if size == (1180, 720):
                                self.assertGreater(self.scroll.verticalScrollBar().maximum(), 0)
                            if size == (1550, 900):
                                self.assertEqual(self.scroll.verticalScrollBar().maximum(), 0)

    def test_deck_controls_wrap_together_on_both_sides_of_resize_breakpoint(self) -> None:
        self.addCleanup(self.app.setStyle, self.app.style().objectName())
        self.addCleanup(self.app.setFont, self.app.font())
        for style in QStyleFactory.keys():
            if style.lower() not in ("fusion", "windows11"):
                continue
            self._recreate_with_style(style)
            left, right = self.main.left, self.main.right
            fixed = self.main.width() - left.width() - right.width()
            inset = left.width() - left.playlist_header.width()
            threshold = max(left.playlist_header.sizeHint().width(), right.playlist_header.sizeHint().width())
            boundary = fixed + 2 * (threshold + inset)
            widths = list(range(boundary - 5, boundary + 6))
            modes = set()
            for width in widths + widths[::-1] + [1180, 1920, 1180]:
                with self.subTest(style=style, width=width):
                    self.main.resize(width, 900)
                    self._settle_layout()
                    self.assertEqual(left.playlist.y(), right.playlist.y())
                    self.assertEqual(left.playlist.height(), right.playlist.height())
                    a, b = left.playlist_header, right.playlist_header
                    self.assertEqual(a._actions.y(), b._actions.y())
                    self.assertEqual(a.height(), b.height())
                    modes.add(a._actions.y() == 0)
            self.assertEqual(modes, {False, True})


if __name__ == "__main__":
    unittest.main()
