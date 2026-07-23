from __future__ import annotations

from PySide6.QtCore import QByteArray, Qt, QUrl, Signal
from PySide6.QtGui import QBrush, QColor, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDial,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from .media import QtMediaDeckEngine
from .models import Track
from .waveform_widget import WaveformWidget


class DeckWidget(QFrame):
    searchRequested = Signal(str)
    deckEnded = Signal(str)
    playbackStarted = Signal(str)
    playlistChanged = Signal()
    moveTrackRequested = Signal(str, int)

    def __init__(self, side: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.side = side
        self.tracks: list[Track] = []
        self.current_index = -1
        self._seeking = False
        self._network = QNetworkAccessManager(self)
        self._network.finished.connect(self._art_finished)
        self._art_reply: QNetworkReply | None = None

        self.setObjectName("LeftDeck" if side == "left" else "RightDeck")
        self.engine = QtMediaDeckEngine(self, capture_waveform=True)

        root = QVBoxLayout(self)
        root.setContentsMargins(15, 15, 15, 15)
        root.setSpacing(10)

        header = QHBoxLayout()
        badge = QLabel(f"DECK {side.upper()}")
        badge.setObjectName("DeckBadge")
        self.state_label = QLabel("EMPTY")
        self.state_label.setObjectName("Subtle")
        self.state_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.state_label.setMinimumWidth(150)
        self.bpm_label = QLabel("BPM --")
        self.bpm_label.setObjectName("Subtle")
        self.bpm_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(badge)
        header.addStretch(1)
        header.addWidget(self.bpm_label)
        header.addWidget(self.state_label)
        root.addLayout(header)

        hero = QHBoxLayout()
        self.art = QLabel("DROP\nA TRACK")
        self.art.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.art.setFixedSize(145, 145)
        self.art.setStyleSheet("background:#080b10;border:1px solid #34445f;border-radius:12px;color:#66758c;font-weight:800;")
        hero.addWidget(self.art)

        info = QVBoxLayout()
        self.title_label = QLabel("Nothing loaded")
        self.title_label.setObjectName("TrackTitle")
        self.title_label.setWordWrap(True)
        self.meta_label = QLabel("Use search or add a local file")
        self.meta_label.setObjectName("Subtle")
        self.meta_label.setWordWrap(True)
        info.addWidget(self.title_label)
        info.addWidget(self.meta_label)
        info.addStretch(1)

        gain_row = QHBoxLayout()
        gain_text = QLabel("GAIN")
        gain_text.setObjectName("Subtle")
        self.gain = QDial()
        self.gain.setRange(0, 100)
        self.gain.setValue(100)
        self.gain.setFixedSize(56, 56)
        self.gain.setNotchesVisible(True)
        gain_row.addWidget(gain_text)
        gain_row.addWidget(self.gain)
        gain_row.addStretch(1)
        info.addLayout(gain_row)
        hero.addLayout(info, 1)
        root.addLayout(hero)

        time_row = QHBoxLayout()
        self.elapsed = QLabel("00:00")
        self.elapsed.setObjectName("TimeLabel")
        self.remaining = QLabel("-00:00")
        self.remaining.setObjectName("TimeLabel")
        time_row.addWidget(self.elapsed)
        time_row.addStretch(1)
        time_row.addWidget(self.remaining)
        root.addLayout(time_row)

        self.waveform = WaveformWidget(side)
        root.addWidget(self.waveform)

        self.progress = QSlider(Qt.Orientation.Horizontal)
        self.progress.setRange(0, 1000)
        root.addWidget(self.progress)

        transport = QHBoxLayout()
        self.play_button = QPushButton("▶ / ❚❚")
        self.play_button.setObjectName("PlayButton")
        self.stop_button = QPushButton("■")
        self.next_button = QPushButton("NEXT")
        self.search_button = QPushButton("SEARCH")
        self.search_button.setObjectName("PrimaryButton" if side == "left" else "HotButton")
        self.local_button = QPushButton("LOCAL")
        for button in [self.play_button, self.stop_button, self.next_button, self.search_button, self.local_button]:
            transport.addWidget(button)
        root.addLayout(transport)

        playlist_header = QHBoxLayout()
        playlist_label = QLabel(f"{side.upper()} SET PLAYLIST")
        playlist_label.setStyleSheet("font-weight:800;letter-spacing:1px;")
        self.remove_button = QPushButton("REMOVE")
        self.reenable_button = QPushButton("RE-ENABLE")
        self.move_button = QPushButton("MOVE RIGHT" if side == "left" else "MOVE LEFT")
        playlist_header.addWidget(playlist_label)
        playlist_header.addStretch(1)
        playlist_header.addWidget(self.move_button)
        playlist_header.addWidget(self.reenable_button)
        playlist_header.addWidget(self.remove_button)
        root.addLayout(playlist_header)

        self.playlist = QListWidget()
        self.playlist.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.playlist.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.playlist.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.playlist.model().rowsMoved.connect(self._sync_order_from_widget)
        root.addWidget(self.playlist, 1)

        self.engine.stateChanged.connect(self._state_changed)
        self.engine.positionChanged.connect(self._position_changed)
        self.engine.waveformSample.connect(self.waveform.add_sample)
        self.engine.waveformSample.connect(self._update_bpm)
        self.engine.loaded.connect(self._loaded)
        self.engine.ended.connect(self._ended)
        self.engine.error.connect(self._show_error)
        self.engine.playbackStarted.connect(lambda: self.playbackStarted.emit(self.side))
        self.play_button.clicked.connect(self.play)
        self.stop_button.clicked.connect(self.engine.stop)
        self.next_button.clicked.connect(lambda: self.advance_to_next(autoplay=True))
        self.search_button.clicked.connect(lambda: self.searchRequested.emit(self.side))
        self.local_button.clicked.connect(self._add_local_files)
        self.remove_button.clicked.connect(self.remove_selected)
        self.reenable_button.clicked.connect(self.reenable_selected)
        self.move_button.clicked.connect(self._request_move_selected)
        self.playlist.itemDoubleClicked.connect(self._double_clicked)
        self.gain.valueChanged.connect(self.engine.set_gain)
        self.progress.sliderPressed.connect(lambda: setattr(self, "_seeking", True))
        self.progress.sliderReleased.connect(self._seek_released)
        self.waveform.seekRequested.connect(self.engine.seek_fraction)

    def add_track(self, track: Track, load_if_empty: bool = True) -> None:
        self.tracks.append(track)
        self.playlist.addItem(self._make_item(len(self.tracks) - 1, track))
        self.playlistChanged.emit()
        current_is_played = (
            0 <= self.current_index < len(self.tracks) and self.tracks[self.current_index].played
        )
        if load_if_empty and (self.current_index < 0 or current_is_played):
            self.load_index(len(self.tracks) - 1, autoplay=False)

    def set_tracks(self, tracks: list[Track]) -> None:
        self.tracks = tracks
        self.current_index = -1
        self.playlist.clear()
        for index, track in enumerate(tracks):
            self.playlist.addItem(self._make_item(index, track))
        first_unplayed = self._first_unplayed_index()
        if first_unplayed is not None:
            self.load_index(first_unplayed, autoplay=False)

    def load_index(self, index: int, autoplay: bool = False) -> None:
        if not (0 <= index < len(self.tracks)) or self.tracks[index].played:
            return
        self.current_index = index
        self.playlist.setCurrentRow(index)
        track = self.tracks[index]
        self.waveform.reset(int(track.duration_seconds or 0) * 1000)
        self.bpm_label.setText("BPM --")
        self.title_label.setText(track.title)
        self.meta_label.setText(" • ".join(part for part in [track.source, track.uploader, track.duration_text] if part))
        self._load_art(track.thumbnail_url)
        self.engine.load(track, autoplay=autoplay)
        self._refresh_numbering()

    def play(self) -> None:
        if self.current_index < 0 or self.tracks[self.current_index].played:
            next_index = self._first_unplayed_index()
            if next_index is not None:
                self.load_index(next_index, autoplay=True)
        elif self.current_index >= 0:
            self.engine.toggle_play_pause()

    def advance_to_next(self, autoplay: bool = False) -> bool:
        if not self.tracks:
            return False
        start = self.current_index if self.current_index >= 0 else -1
        for offset in range(1, len(self.tracks) + 1):
            next_index = (start + offset) % len(self.tracks)
            if not self.tracks[next_index].played:
                self.load_index(next_index, autoplay=autoplay)
                return True
        return False

    def reenable_selected(self) -> None:
        row = self.playlist.currentRow()
        if not (0 <= row < len(self.tracks)) or not self.tracks[row].played:
            return
        self.tracks[row].played = False
        self._refresh_numbering()
        self.playlistChanged.emit()

    def remove_selected(self) -> None:
        row = self.playlist.currentRow()
        self.take_track(row)

    def take_track(self, row: int) -> Track | None:
        if not (0 <= row < len(self.tracks)):
            return None
        was_current = row == self.current_index
        track = self.tracks.pop(row)
        self.playlist.takeItem(row)
        if not self.tracks:
            self.current_index = -1
            self.engine.stop()
            self.title_label.setText("Nothing loaded")
            self.meta_label.setText("Use search or add a local file")
            self.art.clear()
            self.art.setText("DROP\nA TRACK")
            self.state_label.setText("EMPTY")
            self.waveform.reset()
            self.bpm_label.setText("BPM --")
        elif was_current:
            self.engine.stop()
            self.current_index = -1
            next_index = self._first_unplayed_index()
            if next_index is not None:
                self.load_index(next_index, autoplay=False)
        elif row < self.current_index:
            self.current_index -= 1
        self._refresh_numbering()
        self.playlistChanged.emit()
        return track

    def _request_move_selected(self) -> None:
        row = self.playlist.currentRow()
        if 0 <= row < len(self.tracks):
            self.moveTrackRequested.emit(self.side, row)

    def set_crossfade_factor(self, factor: float) -> None:
        self.engine.set_crossfade_factor(factor)

    def current_remaining_ms(self) -> int:
        current, total = self.engine.current_times()
        return max(0, total - current) if total else 0

    def has_tracks(self) -> bool:
        return any(not track.played for track in self.tracks)

    def _double_clicked(self, item: QListWidgetItem) -> None:
        row = self.playlist.row(item)
        if 0 <= row < len(self.tracks) and not self.tracks[row].played:
            self.load_index(row, autoplay=True)

    def _ended(self) -> None:
        if 0 <= self.current_index < len(self.tracks):
            self.tracks[self.current_index].played = True
            self._refresh_numbering()
            self.playlistChanged.emit()
        self.deckEnded.emit(self.side)
        self.advance_to_next(autoplay=False)

    def _loaded(self, track: Track) -> None:
        self.title_label.setText(track.title)

    def _state_changed(self, state: str) -> None:
        self.state_label.setText(state)
        self.state_label.setToolTip(state)

    def _position_changed(self, current_ms: int, total_ms: int) -> None:
        self.elapsed.setText(_format_ms(current_ms))
        self.remaining.setText(f"-{_format_ms(max(0, total_ms - current_ms))}")
        if total_ms > 0 and not self._seeking:
            self.progress.setValue(round(current_ms / total_ms * 1000))
        self.waveform.set_position(current_ms, total_ms)

    def _update_bpm(self, _time_ms: int, _level: float) -> None:
        info = self.engine.beat_info()
        if info is None or info.confidence < 0.45:
            return
        rate = self.engine.playback_rate()
        self.bpm_label.setText(f"BPM {info.bpm * rate:.0f}")
        self.bpm_label.setToolTip(
            f"Detected {info.bpm:.1f} BPM · playback rate {rate:.3f}x · "
            f"confidence {info.confidence:.0%}"
        )

    def _seek_released(self) -> None:
        self._seeking = False
        self.engine.seek_fraction(self.progress.value() / 1000.0)

    def _add_local_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Add local tracks",
            "",
            "Audio files (*.mp3 *.wav *.flac *.m4a *.aac *.ogg);;All files (*.*)",
        )
        for path in paths:
            title = path.replace("\\", "/").rsplit("/", 1)[-1]
            self.add_track(Track(title=title, webpage_url=QUrl.fromLocalFile(path).toString(), source="Local file"))

    def _show_error(self, message: str) -> None:
        QMessageBox.warning(self, f"Deck {self.side.title()}", message)

    def _load_art(self, url: str) -> None:
        if self._art_reply:
            self._art_reply.abort()
        if not url:
            self.art.clear()
            self.art.setText("NO ART")
            return
        self._art_reply = self._network.get(QNetworkRequest(QUrl(url)))

    def _art_finished(self, reply: QNetworkReply) -> None:
        if reply is self._art_reply and reply.error() == QNetworkReply.NetworkError.NoError:
            data: QByteArray = reply.readAll()
            pixmap = QPixmap()
            if pixmap.loadFromData(data):
                self.art.setPixmap(
                    pixmap.scaled(
                        self.art.size(),
                        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
        reply.deleteLater()
        if reply is self._art_reply:
            self._art_reply = None

    def _sync_order_from_widget(self, *_args: object) -> None:
        ordered = [
            track
            for row in range(self.playlist.count())
            if isinstance((track := self.playlist.item(row).data(Qt.ItemDataRole.UserRole)), Track)
        ]
        if len(ordered) == len(self.tracks):
            current_track = self.engine.track
            self.tracks = ordered
            if current_track in self.tracks:
                self.current_index = self.tracks.index(current_track)
            self._refresh_numbering()
            self.playlistChanged.emit()

    def _make_item(self, index: int, track: Track) -> QListWidgetItem:
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, track)
        self._refresh_item(item, index, track)
        return item

    def _refresh_item(self, item: QListWidgetItem, index: int, track: Track) -> None:
        if track.played:
            prefix = "PLAYED"
        elif index == self.current_index:
            prefix = "▶"
        else:
            prefix = f"{index + 1:02d}"
        item.setText(f"{prefix} · {track.title}")
        font = item.font()
        font.setStrikeOut(track.played)
        item.setFont(font)
        item.setForeground(QBrush(QColor("#66758c")) if track.played else QBrush())
        item.setToolTip("Select and click RE-ENABLE to play again." if track.played else "")

    def _refresh_numbering(self) -> None:
        for index, track in enumerate(self.tracks):
            item = self.playlist.item(index)
            if item:
                self._refresh_item(item, index, track)

    def _first_unplayed_index(self) -> int | None:
        return next((index for index, track in enumerate(self.tracks) if not track.played), None)


def _format_ms(milliseconds: int) -> str:
    seconds = max(0, int(milliseconds / 1000))
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"
