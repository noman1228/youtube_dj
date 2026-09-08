from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QHBoxLayout, QSizePolicy, QWidget


class PlaylistHeader(QWidget):
    """Keep playlist controls aligned, wrapping only when a deck is narrow."""

    def __init__(self, label, option, buttons, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._heading = QWidget(self)
        heading = QHBoxLayout(self._heading)
        heading.setContentsMargins(0, 0, 0, 0)
        heading.addWidget(label)
        heading.addWidget(option)
        self._actions = QWidget(self)
        actions = QHBoxLayout(self._actions)
        actions.setContentsMargins(0, 0, 0, 0)
        for button in buttons:
            actions.addWidget(button)
        policy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    def sizeHint(self) -> QSize:
        heading, actions = self._heading.sizeHint(), self._actions.sizeHint()
        return QSize(heading.width() + actions.width() + 12, max(heading.height(), actions.height()))

    def minimumSizeHint(self) -> QSize:
        return QSize(max(self._heading.minimumSizeHint().width(), self._actions.minimumSizeHint().width()), 0)

    def heightForWidth(self, width: int) -> int:
        if width >= self.sizeHint().width():
            return self.sizeHint().height()
        return self._heading.sizeHint().height() + self._actions.sizeHint().height() + 6

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        heading, actions = self._heading.sizeHint(), self._actions.sizeHint()
        if self.width() >= self.sizeHint().width():
            height = max(heading.height(), actions.height())
            self._heading.setGeometry(0, (height - heading.height()) // 2, heading.width(), heading.height())
            self._actions.setGeometry(self.width() - actions.width(), (height - actions.height()) // 2,
                                      actions.width(), actions.height())
        else:
            self._heading.setGeometry(0, 0, self.width(), heading.height())
            self._actions.setGeometry(self.width() - actions.width(), heading.height() + 6,
                                      actions.width(), actions.height())
