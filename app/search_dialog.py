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
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

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
        self.setObjectName("ResultCard")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(175 if compact else 155)

        if compact:
            card_layout = QVBoxLayout(self)
            card_layout.setContentsMargins(12, 12, 12, 12)
            card_layout.setSpacing(10)
            row = QHBoxLayout()
            card_layout.addLayout(row, 1)
        else:
            row = QHBoxLayout(self)
            row.setContentsMargins(12, 12, 12, 12)
        row.setSpacing(10 if compact else 14)

        self.thumbnail = QLabel("NO ART")
        self.thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumbnail.setFixedSize(112 if compact else 160, 63 if compact else 90)
        self.thumbnail.setStyleSheet("background:#080b10;border:1px solid #34445f;border-radius:8px;color:#66758c;")
        row.addWidget(self.thumbnail, 0, Qt.AlignmentFlag.AlignVCenter)

        text_panel = QWidget()
        text_panel.setObjectName("ResultTextPanel")
        if compact:
            text_panel.setMinimumWidth(0)
            text_panel.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        else:
            text_panel.setFixedWidth(360)
        text_panel.setStyleSheet("background: transparent;")
        text_col = QVBoxLayout(text_panel)
        text_col.setContentsMargins(0, 0, 0, 0)
        title = QLabel(track.title)
        title.setObjectName("TrackTitle")
        title.setWordWrap(True)
        title.setMaximumHeight(44)
        title.setToolTip(track.title)
        if compact:
            title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            title.ensurePolished()
            title.setMaximumHeight(2 * title.fontMetrics().lineSpacing())
        text_col.addWidget(title)

        meta = " • ".join(part for part in [track.source, track.uploader, track.duration_text] if part)
        meta_label = QLabel(meta)
        meta_label.setObjectName("Subtle")
        if compact:
            meta_label.setWordWrap(True)
            meta_label.setMaximumHeight(36)
            meta_label.setToolTip(meta)
        text_col.addWidget(meta_label)

        # setVisible(True) below must never show a temporary top-level window.
        description = QLabel(track.description or "No description supplied.", text_panel)
        description.setWordWrap(True)
        description.setMaximumHeight(38)
        description.setToolTip(track.description)
        description.setVisible(not compact)
        text_col.addWidget(description)
        row.addWidget(text_panel, 1 if compact else 0, Qt.AlignmentFlag.AlignVCenter)

        buttons = QHBoxLayout() if compact else QVBoxLayout()
        buttons.setSpacing(7)
        if not compact:
            buttons.addStretch(1)
        targets = targets or [
            ("left", "ADD LEFT", "PrimaryButton"),
            ("right", "ADD RIGHT", "HotButton"),
        ]
        for target, label, object_name in targets:
            add = QPushButton(label)
            add.setObjectName(object_name)
            if compact:
                add.setMinimumWidth(112)
            else:
                add.setFixedWidth(112)
            add.clicked.connect(
                lambda _checked=False, target=target: self.addRequested.emit(target, self.track)
            )
            buttons.addWidget(add)
        details = QPushButton("DETAILS")
        if compact:
            details.setMinimumWidth(112)
        else:
            details.setFixedWidth(112)
        details.clicked.connect(self._show_details)
        buttons.addWidget(details)
        if compact:
            card_layout.addLayout(buttons)
        else:
            buttons.addStretch(1)
            row.addLayout(buttons)
            row.addStretch(1)

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

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)

        header = QLabel("SEARCH THE CRATES")
        header.setObjectName("AppTitle")
        root.addWidget(header)

        controls = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Artist, song, remix, live version…")
        self.provider = QComboBox()
        self.provider.addItems(["Both", "YouTube", "YouTube Music"])
        self.search_button = QPushButton("SEARCH")
        self.search_button.setObjectName("PrimaryButton")
        controls.addWidget(self.search_edit, 1)
        controls.addWidget(self.provider)
        controls.addWidget(self.search_button)
        root.addLayout(controls)

        similar_controls = QHBoxLayout()
        for side, style in (("left", "PrimaryButton"), ("right", "HotButton")):
            button = QPushButton(f"SIMILAR TO {side.upper()}")
            button.setObjectName(style)
            button.setAutoDefault(False)
            button.setToolTip("Find 10 random related songs using this deck's current track. Era and popularity matching depends on available metadata.")
            button.clicked.connect(lambda _checked=False, side=side: self.similarRequested.emit(side))
            similar_controls.addWidget(button)
        root.addLayout(similar_controls)

        self.status = QLabel("Enter a search term. Results can be sent directly to either deck.")
        self.status.setObjectName("Subtle")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.results_widget = QWidget()
        self.results_layout = QVBoxLayout(self.results_widget)
        self.results_layout.setContentsMargins(0, 0, 0, 0)
        self.results_layout.setSpacing(10)
        self.results_layout.addStretch(1)
        self.scroll.setWidget(self.results_widget)
        root.addWidget(self.scroll, 1)

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
