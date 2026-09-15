"""Small, idle-only song-radio lookups; never prepare or download media."""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from functools import partial

from PySide6.QtCore import QObject, QRunnable, QSize, QThread, QThreadPool, QTimer, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QListWidgetItem, QMenu

from .ui_loader import load_ui

from .models import Track
from .similar_search import SimilarSearchTask, youtube_id


_idle_pool: QThreadPool | None = None


def suggestion_pool() -> QThreadPool:
    global _idle_pool
    if _idle_pool is None:
        _idle_pool = QThreadPool()
        _idle_pool.setMaxThreadCount(1)
        _idle_pool.setThreadPriority(QThread.Priority.IdlePriority)
    return _idle_pool


class SuggestionSignals(QObject):
    done = Signal(int, object)


class SuggestionTask(QRunnable):
    def __init__(self, request: int, track: Track, excluded: set[str]) -> None:
        super().__init__()
        self.request = request
        self.track = Track.from_dict(track.to_dict())
        self.excluded = set(excluded)
        self.cancelled = threading.Event()
        self.signals = SuggestionSignals()

    def run(self) -> None:
        results = []
        try:
            if not self.cancelled.is_set():
                import requests
                from ytmusicapi import YTMusic

                with requests.Session() as session:
                    # One bounded metadata lookup; no thumbnails, extraction,
                    # media preparation, or automatic retries.
                    session.request = partial(session.request, timeout=5)
                    client = YTMusic(requests_session=session)
                    if not self.cancelled.is_set():
                        results = SimilarSearchTask(
                            self.track, "suggestions", self.request, self.excluded, limit=5, radio_limit=0,
                        ).find_tracks(client=client)
        except Exception:
            pass  # Optional discoveries must never interrupt the show.
        try:
            self.signals.done.emit(self.request, [] if self.cancelled.is_set() else results)
        except RuntimeError:
            pass  # The window was destroyed while the request was finishing.


class SongSuggestions(QFrame):
    addRequested = Signal(str, object)
    resultsChanged = Signal(bool)
    _SETTLE_SECONDS = 15

    def __init__(self, context, parent=None) -> None:
        super().__init__(parent)
        # context returns (audible track, deck name, busy, queued video IDs).
        self._context = context
        self._pool = suggestion_pool()
        self._request = 0
        self._seed = ""
        self._settled_at = time.monotonic()
        self._task: SuggestionTask | None = None
        self._attempted = False
        self._closed = False
        self._cache: OrderedDict[str, list[Track]] = OrderedDict()
        self.setObjectName("SongSuggestions")
        load_ui(self, "song_suggestions.ui")
        self.list.setFont(QFont(self.font().family(), 8))
        self.list.ensurePolished()
        self.list.setFixedHeight(5 * (self.list.fontMetrics().height() + 2) + 2 * self.list.frameWidth())
        self.list.itemClicked.connect(self._menu_for_item)
        self.list.hide()
        self._timer = QTimer(self)
        self._timer.setInterval(2000)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def _tick(self) -> None:
        if self._closed:
            return
        track, side, busy, excluded = self._context()
        seed = youtube_id(track) if track else ""
        now = time.monotonic()
        if seed != self._seed:
            self._request += 1
            if self._task:
                self._task.cancelled.set()
            self._seed = seed
            self._settled_at = now
            self._attempted = False
            self.list.clear()
            self.list.hide()
            self.status.show()
            self.status.setToolTip(track.title if track else "")
            self.status.setText(f"Related to deck {side.upper()}" if seed else "Play a YouTube music track")
        if not seed:
            return
        if busy:
            self._settled_at = now
            return
        if self._attempted or self._task or now - self._settled_at < self._SETTLE_SECONDS:
            return
        if seed in self._cache:
            self._show_tracks(self._cache[seed], excluded)
            self._cache.move_to_end(seed)
            self._attempted = True
            return
        task = SuggestionTask(self._request, track, excluded)
        task.signals.done.connect(self._finished)
        # Never queue behind another recommendation or build up stale jobs.
        if self._pool.tryStart(task):
            self._task = task
            self._attempted = True

    def _finished(self, request: int, tracks: list[Track]) -> None:
        if self._task and self._task.request == request:
            self._task = None
        if self._closed or request != self._request:
            return
        current, side, _busy, excluded = self._context()
        if not current or youtube_id(current) != self._seed:
            return
        self._cache[self._seed] = tracks
        while len(self._cache) > 24:
            self._cache.popitem(last=False)
        self._show_tracks(tracks, excluded)

    def _show_tracks(self, tracks: list[Track], excluded: set[str]) -> None:
        self.list.clear()
        for track in tracks:
            if youtube_id(track) in excluded:
                continue
            item = QListWidgetItem(track.title)
            # Windows 11's native delegate otherwise reserves tall touch rows,
            # forcing this compact five-song panel to scroll or clip the console.
            item.setSizeHint(QSize(0, self.list.fontMetrics().height() + 2))
            item.setData(Qt.ItemDataRole.UserRole, track)
            item.setToolTip(f"{track.title}\n{track.uploader}\nClick to add to a deck")
            self.list.addItem(item)
            if self.list.count() == 5:
                break
        self.status.setText("Click to add to a deck" if self.list.count() else "No new suggestions")
        if self.list.count():
            self.list.setFixedHeight(
                sum(self.list.sizeHintForRow(row) for row in range(self.list.count()))
                + 2 * self.list.frameWidth()
            )
        self.list.setVisible(self.list.count() > 0)
        self.status.setVisible(self.list.count() == 0)
        self.resultsChanged.emit(bool(self.list.count()))

    def _menu_for_item(self, item: QListWidgetItem) -> None:
        track = item.data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        for side in ("left", "right"):
            action = menu.addAction(f"Add to {side.title()} Deck")
            action.triggered.connect(lambda _checked=False, side=side: self.addRequested.emit(side, track))
        menu.aboutToHide.connect(menu.deleteLater)
        menu.popup(self.list.viewport().mapToGlobal(self.list.visualItemRect(item).bottomLeft()))

    def shutdown(self) -> None:
        self._closed = True
        self._timer.stop()
        if self._task:
            self._task.cancelled.set()
