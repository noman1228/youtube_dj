from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication, QColorDialog, QComboBox, QDialog, QDialogButtonBox,
    QFormLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

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
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(18)
        title = QLabel("MAKE IT YOURS")
        title.setObjectName("AppTitle")
        layout.addWidget(title)
        description = QLabel("Choose a theme and deck colors. Changes apply immediately\nand are saved automatically.")
        description.setObjectName("Subtle")
        layout.addWidget(description)
        form = QFormLayout()
        form.setSpacing(14)
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(THEMES)
        self.theme_combo.setCurrentText(self.preferences["theme"])
        form.addRow("Theme", self.theme_combo)
        self.color_buttons: dict[str, QPushButton] = {}
        for side, label in (("left", "Left deck / UI accent"), ("right", "Right deck")):
            button = QPushButton()
            button.clicked.connect(lambda _checked=False, side=side: self._choose_color(side))
            self.color_buttons[side] = button
            form.addRow(label, button)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        reset = buttons.addButton("Reset to defaults", QDialogButtonBox.ButtonRole.ResetRole)
        reset.clicked.connect(self._reset)
        buttons.rejected.connect(self.close)
        layout.addWidget(buttons)
        self.theme_combo.currentTextChanged.connect(self._theme_changed)
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

    def _choose_color(self, side: str) -> None:
        color = QColorDialog.getColor(QColor(self.preferences[side]), self, f"Choose {side} color")
        if color.isValid():
            self.preferences[side] = color.name()
            self._refresh_colors()
            apply_appearance(self.preferences, save=True)

    def _reset(self) -> None:
        self.preferences = dict(DEFAULT_APPEARANCE)
        self.theme_combo.setCurrentText(self.preferences["theme"])
        self._refresh_colors()
        apply_appearance(self.preferences, save=True)
