from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import QApplication, QColorDialog, QDialog, QWidget

from .ui_loader import load_ui

from .theme import DEFAULT_APPEARANCE, THEMES, apply_appearance, load_appearance


class AppearanceShortcut(QObject):
    activated = Signal()

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        QApplication.instance().installEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (event.type() in (QEvent.Type.ShortcutOverride, QEvent.Type.KeyPress)
                and isinstance(watched, QWidget) and watched.window() is self.parent()
                and not event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.MetaModifier)
                and (event.key() == Qt.Key.Key_Question
                     or (event.key() == Qt.Key.Key_Slash and event.modifiers() & Qt.KeyboardModifier.ShiftModifier))):
            event.accept()
            if event.type() == QEvent.Type.KeyPress and not event.isAutoRepeat():
                self.activated.emit()
            return True
        return super().eventFilter(watched, event)


class AppearanceDialog(QDialog):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle("Appearance — EncoreMix")
        self.setMinimumWidth(420)
        self.preferences = dict(QApplication.instance().property("appearance") or load_appearance())
        ui = load_ui(self, "appearance_dialog.ui")
        self.theme_combo.clear()
        self.theme_combo.addItems(THEMES)
        self.theme_combo.setCurrentText(self.preferences["theme"])
        self.karaoke_deck_shrink.setValue(int(self.preferences.get("karaoke_deck_shrink", 35)))
        self.color_buttons = {"left": ui.left_color_button, "right": ui.right_color_button}
        for side, button in self.color_buttons.items():
            button.clicked.connect(lambda _checked=False, side=side: self._choose_color(side))
        ui.reset_button.clicked.connect(self._reset)
        ui.buttons.rejected.connect(self.close)
        self.theme_combo.currentTextChanged.connect(self._theme_changed)
        self.karaoke_deck_shrink.valueChanged.connect(self._shrink_changed)
        self._refresh_colors()

    def _refresh_colors(self) -> None:
        for side, button in self.color_buttons.items():
            color = self.preferences[side]
            swatch = QPixmap(20, 20)
            swatch.fill(QColor(color))
            button.setIcon(QIcon(swatch))
            button.setText(f"{color.upper()}  ·  Choose…")

    def _theme_changed(self, theme: str) -> None:
        self.preferences["theme"] = theme
        apply_appearance(self.preferences, save=True)

    def _shrink_changed(self, value: int) -> None:
        self.preferences["karaoke_deck_shrink"] = value
        apply_appearance(self.preferences, save=True)

    def _choose_color(self, side: str) -> None:
        color = QColorDialog.getColor(QColor(self.preferences[side]), self, f"Choose {side} color")
        if color.isValid():
            self.preferences[side] = color.name()
            self._refresh_colors()
            apply_appearance(self.preferences, save=True)

    def _reset(self) -> None:
        self.preferences = dict(DEFAULT_APPEARANCE)
        self.theme_combo.setCurrentText(self.preferences["theme"])
        self.karaoke_deck_shrink.setValue(self.preferences["karaoke_deck_shrink"])
        self._refresh_colors()
        apply_appearance(self.preferences, save=True)
