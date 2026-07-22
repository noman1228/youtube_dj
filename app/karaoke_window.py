from __future__ import annotations

from PySide6.QtCore import QByteArray, QObject, QRect, QThreadPool, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QBrush, QCloseEvent, QColor, QKeyEvent, QMouseEvent, QPainter
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtMultimedia import QVideoFrame, QVideoSink
from PySide6.QtWidgets import (
    QDialog,
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .media import QtMediaDeckEngine
from .models import Track
from .search_dialog import ResultCard
from .search_service import SearchTask


class VideoDisplayWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._frame_image = None
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)

    def set_image(self, image) -> None:
        self._frame_image = image if not image.isNull() else None
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#000000"))
        if self._frame_image is None:
            return
        size = self._frame_image.size()
        size.scale(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
        target = QRect(
            (self.width() - size.width()) // 2,
            (self.height() - size.height()) // 2,
            size.width(),
            size.height(),
        )
        painter.drawImage(target, self._frame_image)


class ProjectorVideoWidget(VideoDisplayWidget):
    fullscreenRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._artist = ""
        self._show_artist = True

    def set_artist(self, artist: str, visible: bool) -> None:
        self._artist = artist.strip()
        self._show_artist = visible
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if not self._show_artist or not self._artist:
            return
        painter = QPainter(self)
        overlay_height = max(70, self.height() // 7)
        overlay = QRect(0, self.height() - overlay_height, self.width(), overlay_height)
        painter.fillRect(overlay, QColor(0, 0, 0, 180))
        font = painter.font()
        font.setBold(True)
        font.setPointSize(max(18, min(34, self.height() // 22)))
        painter.setFont(font)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(
            overlay.adjusted(30, 8, -30, -8),
            Qt.AlignmentFlag.AlignCenter,
            self._artist,
        )

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        self.fullscreenRequested.emit()
        event.accept()


class MirroredVideoRouter(QObject):
    def __init__(self, displays: list[VideoDisplayWidget], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.displays = displays
        self.sink = QVideoSink(self)
        self.sink.videoFrameChanged.connect(self._frame_changed)

    @Slot(QVideoFrame)
    def _frame_changed(self, frame: QVideoFrame) -> None:
        image = frame.toImage()
        for display in self.displays:
            display.set_image(image)


class ProjectorWindow(QMainWindow):
    closed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle("EncoreMix Karaoke Video - Move to projector, then press F11")
        self.resize(960, 540)
        self.video = ProjectorVideoWidget()
        self.video.setStyleSheet("background:#000;")
        self.setCentralWidget(self.video)
        self.statusBar().showMessage("Move this window to the projector. F11/double-click: fullscreen · Esc: exit fullscreen")
        self.video.fullscreenRequested.connect(self.toggle_fullscreen)

    def toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
            self.statusBar().show()
        else:
            self.statusBar().hide()
            self.showFullScreen()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_F11:
            self.toggle_fullscreen()
            event.accept()
        elif event.key() == Qt.Key.Key_Escape and self.isFullScreen():
            self.toggle_fullscreen()
            event.accept()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.closed.emit()
        super().closeEvent(event)


class KaraokeWindow(QDialog):
    queueChanged = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("EncoreMix - KARAOKE DECK")
        self.resize(1400, 850)
        self.setMinimumSize(1000, 650)

        self.tracks: list[Track] = []
        self.current_index = -1
        self._seeking = False
        self._search_generation = 0
        self._result_count = 0
        self._active_tasks: dict[int, SearchTask] = {}
        self._pool = QThreadPool.globalInstance()
        self._network = QNetworkAccessManager(self)
        self._reply_targets: dict[QNetworkReply, QLabel] = {}
        self._network.finished.connect(self._thumbnail_finished)

        self.engine = QtMediaDeckEngine(self, video=True)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        title = QLabel("KARAOKE DECK")
        title.setObjectName("AppTitle")
        root.addWidget(title)

        if parent is not None and hasattr(parent, "left") and hasattr(parent, "crossfader"):
            root.addWidget(self._build_main_remote(parent))

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_search_panel())
        splitter.addWidget(self._build_deck_panel())
        splitter.setSizes([570, 800])
        root.addWidget(splitter, 1)

        self.projector = ProjectorWindow(self)
        self.video_router = MirroredVideoRouter([self.video, self.projector.video], self)
        self.engine.set_video_sink(self.video_router.sink)
        self.engine.stateChanged.connect(self._set_state)
        self.engine.positionChanged.connect(self._position_changed)
        self.engine.ended.connect(self._ended)
        self.engine.error.connect(lambda message: QMessageBox.warning(self, "Karaoke deck", message))

    def _build_main_remote(self, main_window: QWidget) -> QWidget:
        panel = QFrame()
        panel.setObjectName("DeckFrame")
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(10)

        title = QLabel("MAIN MIX REMOTE")
        title.setStyleSheet("font-weight:800;letter-spacing:1px;")
        layout.addWidget(title)

        side_label = QLabel("SIDE")
        side_label.setObjectName("Subtle")
        self.main_side = QComboBox()
        self.main_side.addItems(["LEFT", "RIGHT"])
        layout.addWidget(side_label)
        layout.addWidget(self.main_side)

        self.main_play_button = QPushButton("PLAY / PAUSE")
        layout.addWidget(self.main_play_button)

        volume_label = QLabel("VOLUME")
        volume_label.setObjectName("Subtle")
        self.main_volume = QSlider(Qt.Orientation.Horizontal)
        self.main_volume.setRange(0, 100)
        self.main_volume.setMaximumWidth(170)
        layout.addWidget(volume_label)
        layout.addWidget(self.main_volume, 1)

        fade_label = QLabel("FADE")
        fade_label.setObjectName("Subtle")
        self.main_crossfader = QSlider(Qt.Orientation.Horizontal)
        self.main_crossfader.setObjectName("Crossfader")
        self.main_crossfader.setRange(main_window.crossfader.minimum(), main_window.crossfader.maximum())
        self.main_crossfader.setValue(main_window.crossfader.value())
        self.main_crossfader.setMaximumWidth(230)
        layout.addWidget(QLabel("L"))
        layout.addWidget(fade_label)
        layout.addWidget(self.main_crossfader, 1)
        layout.addWidget(QLabel("R"))

        fade_time_label = QLabel("TIME")
        fade_time_label.setObjectName("Subtle")
        self.main_fade_seconds = QSpinBox()
        self.main_fade_seconds.setRange(2, 10)
        self.main_fade_seconds.setValue(main_window.fade_seconds.value())
        self.main_fade_seconds.setSuffix(" s")
        layout.addWidget(fade_time_label)
        layout.addWidget(self.main_fade_seconds)

        self.main_side.currentIndexChanged.connect(
            lambda _index: self._sync_selected_main_volume(main_window)
        )
        self.main_play_button.clicked.connect(lambda: self._toggle_main_deck(main_window))
        self.main_volume.valueChanged.connect(lambda value: self._set_main_volume(main_window, value))
        self.main_crossfader.valueChanged.connect(main_window.crossfader.setValue)
        main_window.crossfader.valueChanged.connect(self.main_crossfader.setValue)
        self.main_fade_seconds.valueChanged.connect(main_window.fade_seconds.setValue)
        main_window.fade_seconds.valueChanged.connect(self.main_fade_seconds.setValue)
        main_window.left.gain.valueChanged.connect(
            lambda value: self._main_gain_changed(main_window, "left", value)
        )
        main_window.right.gain.valueChanged.connect(
            lambda value: self._main_gain_changed(main_window, "right", value)
        )
        self._sync_selected_main_volume(main_window)
        return panel

    def _selected_main_deck(self, main_window: QWidget):
        return main_window.left if self.main_side.currentIndex() == 0 else main_window.right

    def _toggle_main_deck(self, main_window: QWidget) -> None:
        self._selected_main_deck(main_window).play()

    def _set_main_volume(self, main_window: QWidget, value: int) -> None:
        self._selected_main_deck(main_window).gain.setValue(value)

    def _sync_selected_main_volume(self, main_window: QWidget) -> None:
        value = self._selected_main_deck(main_window).gain.value()
        self.main_volume.blockSignals(True)
        self.main_volume.setValue(value)
        self.main_volume.blockSignals(False)

    def _main_gain_changed(self, main_window: QWidget, side: str, value: int) -> None:
        selected_side = "left" if self.main_side.currentIndex() == 0 else "right"
        if side == selected_side and self.main_volume.value() != value:
            self.main_volume.setValue(value)

    def _build_search_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("CenterConsole")
        layout = QVBoxLayout(panel)

        heading = QLabel("KARAOKE SEARCH")
        heading.setStyleSheet("font-size:14pt;font-weight:800;")
        layout.addWidget(heading)

        search_row = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Artist and song title")
        self.search_button = QPushButton("SEARCH")
        self.search_button.setObjectName("HotButton")
        search_row.addWidget(self.search_edit, 1)
        search_row.addWidget(self.search_button)
        layout.addLayout(search_row)

        self.search_status = QLabel('Every query automatically includes "karaoke" and searches YouTube only.')
        self.search_status.setObjectName("Subtle")
        self.search_status.setWordWrap(True)
        layout.addWidget(self.search_status)

        self.results_widget = QWidget()
        self.results_layout = QVBoxLayout(self.results_widget)
        self.results_layout.setContentsMargins(0, 0, 0, 0)
        self.results_layout.setSpacing(10)
        self.results_layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.results_widget)
        layout.addWidget(scroll, 1)

        self.search_button.clicked.connect(self.search)
        self.search_edit.returnPressed.connect(self.search)
        return panel

    def _build_deck_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("CenterConsole")
        layout = QVBoxLayout(panel)

        header = QHBoxLayout()
        deck_title = QLabel("DECK KARAOKE")
        deck_title.setObjectName("DeckBadge")
        self.state_label = QLabel("EMPTY")
        self.state_label.setObjectName("Subtle")
        header.addWidget(deck_title)
        header.addStretch(1)
        header.addWidget(self.state_label)
        layout.addLayout(header)

        self.video = VideoDisplayWidget()
        self.video.setMinimumHeight(330)
        layout.addWidget(self.video, 3)

        self.now_playing = QLabel("Nothing loaded")
        self.now_playing.setObjectName("TrackTitle")
        self.now_playing.setWordWrap(True)
        layout.addWidget(self.now_playing)

        time_row = QHBoxLayout()
        self.elapsed = QLabel("00:00")
        self.remaining = QLabel("-00:00")
        self.elapsed.setObjectName("TimeLabel")
        self.remaining.setObjectName("TimeLabel")
        time_row.addWidget(self.elapsed)
        time_row.addStretch(1)
        time_row.addWidget(self.remaining)
        layout.addLayout(time_row)

        self.progress = QSlider(Qt.Orientation.Horizontal)
        self.progress.setRange(0, 1000)
        layout.addWidget(self.progress)

        controls = QHBoxLayout()
        self.play_button = QPushButton("PLAY / PAUSE")
        self.play_button.setObjectName("HotButton")
        self.stop_button = QPushButton("STOP")
        self.next_button = QPushButton("NEXT")
        self.projector_button = QPushButton("PROJECTOR WINDOW")
        self.projector_button.setObjectName("PrimaryButton")
        volume_label = QLabel("VOLUME")
        volume_label.setObjectName("Subtle")
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(100)
        self.volume.setMaximumWidth(150)
        for widget in (
            self.play_button,
            self.stop_button,
            self.next_button,
            self.projector_button,
            volume_label,
            self.volume,
        ):
            controls.addWidget(widget)
        layout.addLayout(controls)

        queue_header = QHBoxLayout()
        queue_header.addWidget(QLabel("KARAOKE QUEUE"))
        self.show_artist = QCheckBox("SHOW SINGER ON PROJECTOR")
        self.show_artist.setChecked(True)
        queue_header.addWidget(self.show_artist)
        queue_header.addStretch(1)
        self.reenable_button = QPushButton("RE-ENABLE")
        self.remove_button = QPushButton("REMOVE")
        queue_header.addWidget(self.reenable_button)
        queue_header.addWidget(self.remove_button)
        layout.addLayout(queue_header)

        self.playlist = QListWidget()
        layout.addWidget(self.playlist, 2)

        self.play_button.clicked.connect(self.play)
        self.stop_button.clicked.connect(self.engine.stop)
        self.next_button.clicked.connect(lambda: self._advance(autoplay=True))
        self.projector_button.clicked.connect(self.open_projector)
        self.volume.valueChanged.connect(self.engine.set_gain)
        self.progress.sliderPressed.connect(lambda: setattr(self, "_seeking", True))
        self.progress.sliderReleased.connect(self._seek_released)
        self.playlist.itemDoubleClicked.connect(self._double_clicked)
        self.reenable_button.clicked.connect(self._reenable_selected)
        self.remove_button.clicked.connect(self._remove_selected)
        self.show_artist.toggled.connect(self._update_projector_artist)
        return panel

    def search(self) -> None:
        query = self.search_edit.text().strip()
        if not query:
            return
        self._search_generation += 1
        generation = self._search_generation
        effective_query = f"{query} karaoke"
        self._clear_results()
        self._result_count = 0
        self.search_status.setText(f'Searching YouTube for "{effective_query}"...')
        task = SearchTask(effective_query, "YouTube", limit=12, request_id=generation)
        self._active_tasks[generation] = task
        task.signals.result.connect(self._append_result, Qt.ConnectionType.QueuedConnection)
        task.signals.finished.connect(self._search_finished, Qt.ConnectionType.QueuedConnection)
        task.signals.failed.connect(self._search_failed, Qt.ConnectionType.QueuedConnection)
        self._pool.start(task)

    @Slot(int, object)
    def _append_result(self, generation: int, track: Track) -> None:
        if generation != self._search_generation:
            return
        self._result_count += 1
        card = ResultCard(
            track,
            targets=[("karaoke", "ADD KARAOKE", "HotButton")],
        )
        card.addRequested.connect(self._add_result)
        self.results_layout.insertWidget(self.results_layout.count() - 1, card)
        self.search_status.setText(f"Searching... {self._result_count} result(s) available now.")
        if track.thumbnail_url:
            reply = self._network.get(QNetworkRequest(QUrl(track.thumbnail_url)))
            self._reply_targets[reply] = card.thumbnail

    @Slot(int, str)
    def _search_finished(self, generation: int, _provider: str) -> None:
        self._active_tasks.pop(generation, None)
        if generation == self._search_generation:
            self.search_status.setText(f"{self._result_count} karaoke result(s).")

    @Slot(int, str, str)
    def _search_failed(self, generation: int, _provider: str, message: str) -> None:
        self._active_tasks.pop(generation, None)
        if generation != self._search_generation:
            return
        self.search_status.setText("Karaoke search failed.")
        QMessageBox.warning(self, "Karaoke search", message)

    def _add_result(self, _target: str, track: Track) -> None:
        artist, accepted = QInputDialog.getText(
            self,
            "Karaoke Artist",
            f"Who will sing this track?\n\n{track.title}",
        )
        if not accepted:
            return
        karaoke_track = Track.from_dict(track.to_dict())
        karaoke_track.played = False
        karaoke_track.karaoke_artist = artist.strip() or "Unassigned"
        self.tracks.append(karaoke_track)
        self.playlist.addItem(self._make_item(len(self.tracks) - 1, karaoke_track))
        if self.current_index < 0:
            self._load_index(0)
        else:
            self.queueChanged.emit()

    def _load_index(self, index: int, autoplay: bool = False) -> None:
        if not (0 <= index < len(self.tracks)) or self.tracks[index].played:
            return
        self.current_index = index
        self.playlist.setCurrentRow(index)
        track = self.tracks[index]
        self.now_playing.setText(f"{track.karaoke_artist} — {track.title}")
        self._update_projector_artist()
        self.engine.load(track, autoplay=autoplay)
        self._refresh_items()
        self.queueChanged.emit()

    def play_index(self, index: int) -> None:
        """Load and play an exact queue entry, including a previously played one."""
        if not (0 <= index < len(self.tracks)):
            return
        self.tracks[index].played = False
        self._load_index(index, autoplay=True)

    def play(self) -> None:
        if self.current_index < 0 or self.tracks[self.current_index].played:
            next_index = self._first_unplayed_index()
            if next_index is not None:
                self._load_index(next_index, autoplay=True)
        else:
            self.engine.toggle_play_pause()

    def _advance(self, autoplay: bool = False) -> bool:
        if not self.tracks:
            return False
        start = self.current_index if self.current_index >= 0 else -1
        for offset in range(1, len(self.tracks) + 1):
            index = (start + offset) % len(self.tracks)
            if not self.tracks[index].played:
                self._load_index(index, autoplay=autoplay)
                return True
        return False

    def _ended(self) -> None:
        if 0 <= self.current_index < len(self.tracks):
            self.tracks[self.current_index].played = True
            self._refresh_items()
        if not self._advance(autoplay=False):
            self.current_index = -1
            self.now_playing.setText("Nothing loaded")
            self._update_projector_artist()
            self.queueChanged.emit()

    def _double_clicked(self, item: QListWidgetItem) -> None:
        index = self.playlist.row(item)
        self.play_index(index)

    def _reenable_selected(self) -> None:
        index = self.playlist.currentRow()
        if 0 <= index < len(self.tracks) and self.tracks[index].played:
            self.tracks[index].played = False
            self._refresh_items()
            self.queueChanged.emit()

    def _remove_selected(self) -> None:
        index = self.playlist.currentRow()
        if not (0 <= index < len(self.tracks)):
            return
        was_current = index == self.current_index
        self.tracks.pop(index)
        self.playlist.takeItem(index)
        if was_current:
            self.engine.stop()
            self.current_index = -1
            next_index = self._first_unplayed_index()
            if next_index is not None:
                self._load_index(next_index)
            else:
                self.now_playing.setText("Nothing loaded")
                self.state_label.setText("EMPTY")
                self._update_projector_artist()
        elif index < self.current_index:
            self.current_index -= 1
        self._refresh_items()
        self.queueChanged.emit()

    def _make_item(self, index: int, track: Track) -> QListWidgetItem:
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, track)
        self._refresh_item(item, index, track)
        return item

    def _refresh_items(self) -> None:
        for index, track in enumerate(self.tracks):
            self._refresh_item(self.playlist.item(index), index, track)

    def _refresh_item(self, item: QListWidgetItem, index: int, track: Track) -> None:
        prefix = "PLAYED" if track.played else ("▶" if index == self.current_index else f"{index + 1:02d}")
        artist = track.karaoke_artist or "Unassigned"
        item.setText(f"{prefix} · {artist} — {track.title}")
        font = item.font()
        font.setStrikeOut(track.played)
        item.setFont(font)
        item.setForeground(QBrush(QColor("#66758c")) if track.played else QBrush())

    def _first_unplayed_index(self) -> int | None:
        return next((index for index, track in enumerate(self.tracks) if not track.played), None)

    def _set_state(self, state: str) -> None:
        self.state_label.setText(state)
        self.state_label.setToolTip(state)

    def open_projector(self) -> None:
        self._update_projector_artist()
        self.projector.showNormal()
        self.projector.show()
        self.projector.raise_()
        self.projector.activateWindow()

    def _update_projector_artist(self, _checked: bool | None = None) -> None:
        artist = ""
        if 0 <= self.current_index < len(self.tracks):
            artist = self.tracks[self.current_index].karaoke_artist
        label = f"SINGER: {artist}" if artist else ""
        self.projector.video.set_artist(label, self.show_artist.isChecked())

    def _position_changed(self, current_ms: int, total_ms: int) -> None:
        self.elapsed.setText(_format_ms(current_ms))
        self.remaining.setText(f"-{_format_ms(max(0, total_ms - current_ms))}")
        if total_ms > 0 and not self._seeking:
            self.progress.setValue(round(current_ms / total_ms * 1000))

    def _seek_released(self) -> None:
        self._seeking = False
        self.engine.seek_fraction(self.progress.value() / 1000.0)

    def _clear_results(self) -> None:
        for reply in tuple(self._reply_targets):
            reply.abort()
        self._reply_targets.clear()
        while self.results_layout.count() > 1:
            item = self.results_layout.takeAt(0)
            if item:
                widget = item.widget()
                if widget:
                    widget.deleteLater()

    def _thumbnail_finished(self, reply: QNetworkReply) -> None:
        target = self._reply_targets.pop(reply, None)
        if target and reply.error() == QNetworkReply.NetworkError.NoError:
            pixmap_data: QByteArray = reply.readAll()
            from PySide6.QtGui import QPixmap

            pixmap = QPixmap()
            if pixmap.loadFromData(pixmap_data):
                target.setPixmap(
                    pixmap.scaled(
                        target.size(),
                        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
        reply.deleteLater()

    def closeEvent(self, event: QCloseEvent) -> None:
        self.projector.close()
        self.engine.stop()
        super().closeEvent(event)


def _format_ms(milliseconds: int) -> str:
    seconds = max(0, milliseconds // 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"
