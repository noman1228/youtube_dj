from __future__ import annotations

from PySide6.QtCore import QEvent, QMargins, QTimer, Qt
from PySide6.QtWidgets import QScrollArea, QWidget


class SymmetricScrollArea(QScrollArea):
    """Keep content centered when a native vertical scrollbar takes up space."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._gutter_ready = True
        self.verticalScrollBar().rangeChanged.connect(self._sync_gutters)

    def _sync_gutters(self, *_args) -> None:
        bar = self.verticalScrollBar()
        policy = self.verticalScrollBarPolicy()
        needed = policy == Qt.ScrollBarPolicy.ScrollBarAlwaysOn or (
            policy == Qt.ScrollBarPolicy.ScrollBarAsNeeded and bar.maximum() > bar.minimum()
        )
        extent = bar.sizeHint().width() if needed else 0
        margins = (QMargins(0, 0, extent, 0) if self.layoutDirection() == Qt.LayoutDirection.RightToLeft
                   else QMargins(extent, 0, 0, 0))
        if self.viewportMargins() != margins:
            self.setViewportMargins(margins)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_gutters()

    def event(self, event) -> bool:
        result = super().event(event)
        if getattr(self, "_gutter_ready", False) and event.type() in (
            QEvent.Type.StyleChange, QEvent.Type.LayoutDirectionChange,
        ):
            QTimer.singleShot(0, self._sync_gutters)
        return result
