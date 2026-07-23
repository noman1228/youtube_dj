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
from PySide6.QtGui import QPixmap
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


class ResultCard(QFrame):
    addRequested = Signal(str, object)

    def __init__(
        self,
        track: Track,
        parent: QWidget | None = None,
        targets: list[tuple[str, str, str]] | None = None,
    ) -> None:
        super().__init__(parent)
        self.track = track
        self.setObjectName("ResultCard")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(155)

        row = QHBoxLayout(self)
        row.setContentsMargins(12, 12, 12, 12)
        row.setSpacing(14)

        self.thumbnail = QLabel("NO ART")
        self.thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumbnail.setFixedSize(160, 90)
        self.thumbnail.setStyleSheet("background:#080b10;border:1px solid #34445f;border-radius:8px;color:#66758c;")
        row.addWidget(self.thumbnail, 0, Qt.AlignmentFlag.AlignVCenter)

        text_panel = QWidget()
        text_panel.setObjectName("ResultTextPanel")
        text_panel.setFixedWidth(360)
        text_panel.setStyleSheet("background: transparent;")
        text_col = QVBoxLayout(text_panel)
        text_col.setContentsMargins(0, 0, 0, 0)
        title = QLabel(track.title)
        title.setObjectName("TrackTitle")
        title.setWordWrap(True)
        title.setMaximumHeight(44)
        title.setToolTip(track.title)
        text_col.addWidget(title)

        meta = " • ".join(part for part in [track.source, track.uploader, track.duration_text] if part)
        meta_label = QLabel(meta)
        meta_label.setObjectName("Subtle")
        text_col.addWidget(meta_label)

        description = QLabel(track.description or "No description supplied.")
        description.setWordWrap(True)
        description.setMaximumHeight(38)
        description.setToolTip(track.description)
        text_col.addWidget(description)
        row.addWidget(text_panel, 0, Qt.AlignmentFlag.AlignVCenter)

        buttons = QVBoxLayout()
        buttons.setSpacing(7)
        buttons.addStretch(1)
        targets = targets or [
            ("left", "ADD LEFT", "PrimaryButton"),
            ("right", "ADD RIGHT", "HotButton"),
        ]
        for target, label, object_name in targets:
            add = QPushButton(label)
            add.setObjectName(object_name)
            add.setFixedWidth(112)
            add.clicked.connect(
                lambda _checked=False, target=target: self.addRequested.emit(target, self.track)
            )
            buttons.addWidget(add)
        details = QPushButton("DETAILS")
        details.setFixedWidth(112)
        details.clicked.connect(self._show_details)
        buttons.addWidget(details)
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
        self._active_tasks: dict[tuple[int, str], SearchTask] = {}

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

        self.status = QLabel("Enter a search term. Results can be sent directly to either deck.")
        self.status.setObjectName("Subtle")
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

    def focus_search(self) -> None:
        self.search_edit.setFocus()
        self.search_edit.selectAll()

    def search(self) -> None:
        query = self.search_edit.text().strip()
        if not query:
            return
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
