from __future__ import annotations

# IDEs often run the currently open file instead of the project's entry point.
# Redirect that case to the full application before package-relative imports run.
if __name__ == "__main__" and not __package__:
    import sys
    from pathlib import Path

    project_root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(project_root))
    from main import main

    raise SystemExit(main())

from PySide6.QtCore import QByteArray, QThreadPool, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QKeyEvent, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QLabel,
    QMessageBox,
    QPushButton,
    QWidget,
)

from .ui_loader import load_ui

from .models import Track
from .search_service import SearchTask
from .similar_search import SimilarSearchTask


class ResultCard(QFrame):
    addRequested = Signal(str, object)

    def __init__(
        self,
        track: Track,
        parent: QWidget | None = None,
        targets: list[tuple[str, str, str]] | None = None,
        compact: bool = False,
    ) -> None:
        super().__init__(parent)
        self.track = track
        ui = load_ui(self, "result_card_compact.ui" if compact else "result_card.ui")
        ui.title.setText(track.title)
        ui.title.setToolTip(track.title)
        if compact:
            ui.title.ensurePolished()
            ui.title.setMaximumHeight(2 * ui.title.fontMetrics().lineSpacing())
        meta = " • ".join(part for part in [track.source, track.uploader, track.duration_text] if part)
        ui.meta_label.setText(meta)
        ui.meta_label.setToolTip(meta if compact else "")
        ui.description.setText(track.description or "No description supplied.")
        ui.description.setToolTip(track.description)
        ui.description.setVisible(not compact)
        targets = targets or [
            ("left", "ADD LEFT", "PrimaryButton"),
            ("right", "ADD RIGHT", "HotButton"),
        ]
        target_buttons = [ui.add_left, ui.add_right]
        for button in target_buttons[len(targets):]:
            button.hide()
        for index, (target, label, object_name) in enumerate(targets):
            if index < len(target_buttons):
                add = target_buttons[index]
            else:
                add = QPushButton(self)
                add.setMinimumWidth(ui.add_left.minimumWidth())
                add.setMaximumWidth(ui.add_left.maximumWidth())
                ui.buttons.insertWidget(ui.buttons.indexOf(ui.details), add)
            add.setText(label)
            add.setObjectName(object_name)
            add.clicked.connect(
                lambda _checked=False, target=target: self.addRequested.emit(target, self.track)
            )
        ui.details.clicked.connect(self._show_details)

    def _show_details(self) -> None:
        QMessageBox.information(
            self,
            self.track.title,
            f"Source: {self.track.source}\n"
            f"Artist/channel: {self.track.uploader or 'Unknown'}\n"
            f"Duration: {self.track.duration_text or 'Unknown'}\n\n"
            f"{self.track.description or 'No description supplied.'}",
        )


class SearchDialog(QDialog):
    trackAdded = Signal(str, object)
    similarRequested = Signal(str)
    _MINIMUM_WIDTH = 760
    _MAXIMUM_WIDTH = 900

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("YouTube / YouTube Music Search")
        self.setMinimumWidth(self._MINIMUM_WIDTH)
        self.setMaximumWidth(self._MAXIMUM_WIDTH)
        self.resize(860, 760)
        self._pool = QThreadPool.globalInstance()
        self._network = QNetworkAccessManager(self)
        self._reply_targets: dict[QNetworkReply, QLabel] = {}
        self._search_generation = 0
        self._pending_providers = 0
        self._result_count = 0
        self._result_limit = 16
        self._seen_results: set[str] = set()
        self._provider_errors: list[str] = []
        self._active_tasks: dict[tuple[int, str], SearchTask | SimilarSearchTask] = {}
        self._similar_side = ""

        ui = load_ui(self, "search_dialog.ui")
        for side in ("left", "right"):
            getattr(ui, f"similar_{side}").clicked.connect(
                lambda _checked=False, side=side: self.similarRequested.emit(side)
            )

        self.search_button.clicked.connect(self.search)
        self.search_edit.returnPressed.connect(self.search)
        self._network.finished.connect(self._thumbnail_finished)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        # The search field already handles Return; avoid a second default-button action.
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            event.accept()
            return
        super().keyPressEvent(event)

    def focus_search(self) -> None:
        self.search_edit.setFocus()
        self.search_edit.selectAll()

    def search(self) -> None:
        query = self.search_edit.text().strip()
        if not query:
            return
        self._similar_side = ""
        self._search_generation += 1
        generation = self._search_generation
        self.status.setText(f"Searching {self.provider.currentText()} for “{query}”…")
        self._clear_results()
        self._result_count = 0
        self._seen_results.clear()
        self._provider_errors.clear()
        providers = (
            ["YouTube", "YouTube Music"]
            if self.provider.currentText() == "Both"
            else [self.provider.currentText()]
        )
        self._pending_providers = len(providers)
        for provider in providers:
            task = SearchTask(query, provider, limit=self._result_limit, request_id=generation)
            self._active_tasks[(generation, provider)] = task
            task.signals.result.connect(self._append_result, Qt.ConnectionType.QueuedConnection)
            task.signals.finished.connect(self._provider_finished, Qt.ConnectionType.QueuedConnection)
            task.signals.failed.connect(self._provider_failed, Qt.ConnectionType.QueuedConnection)
            self._pool.start(task)

    def search_similar(self, track: Track, side: str, excluded: set[str]) -> None:
        self._search_generation += 1
        generation = self._search_generation
        self._similar_side = side
        self._clear_results()
        self._result_count = 0
        self._seen_results.clear()
        self._provider_errors.clear()
        self._pending_providers = 1
        provider = f"Similar to {side.upper()}"
        self.status.setText(f'Finding 10 recommendations related to {side.upper()}: {track.title}…')
        task = SimilarSearchTask(track, provider, generation, excluded)
        self._active_tasks[(generation, provider)] = task
        task.signals.result.connect(self._append_result, Qt.ConnectionType.QueuedConnection)
        task.signals.finished.connect(self._provider_finished, Qt.ConnectionType.QueuedConnection)
        task.signals.failed.connect(self._provider_failed, Qt.ConnectionType.QueuedConnection)
        self._pool.start(task)

    def _clear_results(self) -> None:
        self.scroll.verticalScrollBar().setValue(0)
        for reply in tuple(self._reply_targets):
            reply.abort()
        self._reply_targets.clear()
        while self.results_layout.count() > 1:
            item = self.results_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    @Slot(int, object)
    def _append_result(self, generation: int, track: Track) -> None:
        if generation != self._search_generation or self._result_count >= self._result_limit:
            return
        key = track.video_id or track.webpage_url
        if key in self._seen_results:
            return
        self._seen_results.add(key)
        self._result_count += 1
        card = ResultCard(track)
        card.addRequested.connect(self.trackAdded)
        self.results_layout.insertWidget(self.results_layout.count() - 1, card)
        self.status.setText(f"Searching... {self._result_count} result(s) available now.")
        if track.thumbnail_url:
            request = QNetworkRequest(QUrl(track.thumbnail_url))
            reply = self._network.get(request)
            self._reply_targets[reply] = card.thumbnail

    @Slot(int, str)
    def _provider_finished(self, generation: int, provider: str) -> None:
        self._active_tasks.pop((generation, provider), None)
        if generation != self._search_generation:
            return
        self._pending_providers -= 1
        self._finish_search_if_ready()

    @Slot(int, str, str)
    def _provider_failed(self, generation: int, provider: str, message: str) -> None:
        self._active_tasks.pop((generation, provider), None)
        if generation != self._search_generation:
            return
        self._provider_errors.append(f"{provider}: {message}")
        self._pending_providers -= 1
        self._finish_search_if_ready()

    def _finish_search_if_ready(self) -> None:
        if self._pending_providers > 0:
            return
        if self._result_count:
            if self._similar_side:
                self.status.setText(f"{self._result_count} recommendation(s) for {self._similar_side.upper()}. Click again for more; genre, era and popularity are approximate.")
            else:
                suffix = " Some providers failed." if self._provider_errors else " Pick your poison."
                self.status.setText(f"{self._result_count} result(s).{suffix}")
        else:
            self.status.setText("Search failed." if self._provider_errors else "No results found.")
            if self._provider_errors:
                QMessageBox.critical(self, "Search failed", "\n".join(self._provider_errors))

    def _thumbnail_finished(self, reply: QNetworkReply) -> None:
        target = self._reply_targets.pop(reply, None)
        if target and reply.error() == QNetworkReply.NetworkError.NoError:
            data: QByteArray = reply.readAll()
            pixmap = QPixmap()
            if pixmap.loadFromData(data):
                target.setPixmap(
                    pixmap.scaled(
                        target.size(),
                        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
        reply.deleteLater()
