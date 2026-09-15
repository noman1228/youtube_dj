from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QSizePolicy, QWidget

from .ui_loader import load_ui


class PlaylistHeader(QWidget):
    """Keep playlist controls aligned, wrapping only when a deck is narrow."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._two_rows: bool | None = None
        ui = load_ui(self, "playlist_header.ui")
        self._heading = ui.heading
        self._actions = ui.actions
        self.label = ui.label
        policy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    def sizeHint(self) -> QSize:
        heading, actions = self._heading.sizeHint(), self._actions.sizeHint()
        return QSize(heading.width() + actions.width() + 12, max(heading.height(), actions.height()))

    def minimumSizeHint(self) -> QSize:
        return QSize(max(self._heading.minimumSizeHint().width(), self._actions.minimumSizeHint().width()), 0)

    def heightForWidth(self, width: int) -> int:
        if not self._wraps(width):
            return self.sizeHint().height()
        return self._heading.sizeHint().height() + self._actions.sizeHint().height() + 6

    def set_two_rows(self, enabled: bool) -> None:
        """Let the main mixer make both deck headers wrap together."""
        if self._two_rows != enabled:
            self._two_rows = enabled
            self.updateGeometry()
            self._arrange()

    def _wraps(self, width: int) -> bool:
        return self._two_rows if self._two_rows is not None else width < self.sizeHint().width()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._arrange()

    def _arrange(self) -> None:
        heading, actions = self._heading.sizeHint(), self._actions.sizeHint()
        if not self._wraps(self.width()):
            height = max(heading.height(), actions.height())
            self._heading.setGeometry(0, (height - heading.height()) // 2, heading.width(), heading.height())
            self._actions.setGeometry(self.width() - actions.width(), (height - actions.height()) // 2,
                                      actions.width(), actions.height())
        else:
            self._heading.setGeometry(0, 0, self.width(), heading.height())
            self._actions.setGeometry(self.width() - actions.width(), heading.height() + 6,
                                      actions.width(), actions.height())
