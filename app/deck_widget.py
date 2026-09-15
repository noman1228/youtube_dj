from __future__ import annotations

from PySide6.QtCore import QByteArray, QEvent, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QBrush, QColor, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import QFileDialog, QFrame, QListWidgetItem, QMessageBox, QWidget

from .ui_loader import load_ui

from .media import QtMediaDeckEngine
from .models import Track
from .playlist_header import PlaylistHeader
from .vu_meter import VuMeter
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
        self._sample_active = False
        self._sample_was_playing = False
        self._sample_position_ms = 0
        self._sample_pending_fraction: float | None = None
        self._sample_hold_timer = QTimer(self)
        self._sample_hold_timer.setSingleShot(True)
        self._sample_hold_timer.setInterval(180)
        self._sample_hold_timer.timeout.connect(self._activate_sample)
        self._sample_gain = 100
        self._sample_crossfade_factor = 1.0
        self._network = QNetworkAccessManager(self)
        self._network.finished.connect(self._art_finished)
        self._art_reply: QNetworkReply | None = None

        self.setObjectName("LeftDeck" if side == "left" else "RightDeck")
        self.engine = QtMediaDeckEngine(self, capture_waveform=True)

        ui = load_ui(self, "deck.ui", {
            "VuMeter": lambda parent, _name: VuMeter(side, parent),
            "WaveformWidget": lambda parent, _name: WaveformWidget(side, parent),
            "PlaylistHeader": lambda parent, _name: PlaylistHeader(parent=parent),
        })
        self.setObjectName("LeftDeck" if side == "left" else "RightDeck")
        ui.badge.setText(f"DECK {side.upper()}")
        self.search_button.setObjectName("PrimaryButton" if side == "left" else "HotButton")
        self.vu_meter.setAccessibleName(f"Deck {side} source VU meter")
        self.vu_meter.setToolTip(f"Deck {side.upper()} source level (RMS dBFS), before gain and crossfader")
        self.playlist_header.label.setText(f"{side.upper()} SET PLAYLIST")
        for name in ("play_on_double_click", "remove_button", "reenable_button", "move_button"):
            setattr(self, name, getattr(self.playlist_header, name))
        self.move_button.setText("MOVE RIGHT" if side == "left" else "MOVE LEFT")
        for widget in (self, self.search_button):
            widget.style().unpolish(widget)
            widget.style().polish(widget)
        self.playlist.model().rowsMoved.connect(self._sync_order_from_widget)
        self.playlist.setProperty("deck_side", side)
        self.playlist.installEventFilter(self)
        self.playlist.viewport().installEventFilter(self)

        self.engine.stateChanged.connect(self._state_changed)
        self.engine.positionChanged.connect(self._position_changed)
        self.engine.waveformSample.connect(self.waveform.add_sample)
        self.engine.waveformReady.connect(self._waveform_ready)
        self.engine.waveformSample.connect(self._update_bpm)
        self.engine.audioLevelChanged.connect(self._update_vu)
        self.engine.loaded.connect(self._loaded)
        self.engine.ended.connect(self._ended)
        self.engine.error.connect(self._show_error)
        self.engine.playbackStarted.connect(lambda: self.playbackStarted.emit(self.side))
        self.playlistChanged.connect(self._prefetch_next)
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
        self.waveform.samplePressed.connect(self._sample_press_started)
        self.waveform.sampleReleased.connect(self._sample_release_finished)

    def set_karaoke_compact(self, enabled: bool) -> None:
        """Keep the deck controls inside a temporarily narrow karaoke deck."""
        for widget in (
            self.vu_meter, self.bpm_label, self.state_label,
            self.search_button, self.local_button,
            self.play_on_double_click, self.move_button, self.reenable_button,
        ):
            widget.setVisible(not enabled)
        self.playlist_header.set_two_rows(not enabled)

    def _sample_press_started(self, fraction: float) -> None:
        self._sample_pending_fraction = fraction
        self._sample_hold_timer.start()

    def _activate_sample(self) -> None:
        fraction = self._sample_pending_fraction
        if fraction is None:
            return
        self._sample_pending_fraction = None
        self._sample_pressed(fraction)

    def _sample_pressed(self, fraction: float) -> None:
        if self._sample_active:
            return
        self._sample_active = True
        self._sample_was_playing = self.engine.is_playing()
        self._sample_position_ms = self.engine.current_times()[0]
        self._sample_gain = self.engine._gain
        self._sample_crossfade_factor = self.engine._crossfade_factor
        self.engine.seek_fraction(fraction)
        self.engine.set_crossfade_factor(1.0)
        self.engine.play()

    def _sample_release_finished(self) -> None:
        self._sample_hold_timer.stop()
        self._sample_pending_fraction = None
        self._sample_released()

    def _sample_released(self) -> None:
        if not self._sample_active:
            return
        self._sample_active = False
        self.engine.seek_ms(self._sample_position_ms)
        self.engine.set_gain(self._sample_gain)
        self.engine.set_crossfade_factor(self._sample_crossfade_factor)
        if not self._sample_was_playing:
            self.engine.pause()

    def eventFilter(self, watched, event) -> bool:
        if watched in (self.playlist, self.playlist.viewport()):
            if event.type() == QEvent.Type.KeyPress and event.key() in (
                Qt.Key.Key_Delete, Qt.Key.Key_Backspace,
            ):
                self.remove_selected()
                event.accept()
                return True
            if (event.type() == QEvent.Type.MouseButtonDblClick
                    and event.button() == Qt.MouseButton.RightButton):
                self.remove_selected()
                event.accept()
                return True
        if watched in (self.playlist, self.playlist.viewport()) and event.type() in (
            QEvent.Type.DragEnter, QEvent.Type.DragMove, QEvent.Type.Drop,
        ):
            source = event.source()
            source_side = source.property("deck_side") if source is not None else None
            if source_side in ("left", "right") and source_side != self.side:
                if event.type() == QEvent.Type.Drop:
                    row = source.currentRow()
                    if row >= 0:
                        self.moveTrackRequested.emit(source_side, row)
                    event.acceptProposedAction()
                else:
                    event.acceptProposedAction()
                return True
        return super().eventFilter(watched, event)

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
        else:
            self.engine.prefetch(None)

    def load_index(self, index: int, autoplay: bool = False) -> None:
        if not (0 <= index < len(self.tracks)) or self.tracks[index].played:
            return
        self.current_index = index
        self.playlist.setCurrentRow(index)
        track = self.tracks[index]
        self.waveform.reset(int(track.duration_seconds or 0) * 1000)
        self.vu_meter.reset()
        self.bpm_label.setText("BPM --")
        self._set_track_labels(track)
        self._load_art(track.thumbnail_url)
        self.engine.load(track, autoplay=autoplay)
        self._prefetch_next()
        self._refresh_numbering()

    def _prefetch_next(self) -> None:
        """Prepare the next queue entry without changing this deck's player."""
        if not (0 <= self.current_index < len(self.tracks)) or self.engine.track is not self.tracks[self.current_index]:
            self.engine.prefetch(None)
            return
        for offset in range(1, len(self.tracks)):
            track = self.tracks[(self.current_index + offset) % len(self.tracks)]
            if not track.played:
                self.engine.prefetch(track)
                return
        self.engine.prefetch(None)

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

    def current_remaining_ms(self) -> int | None:
        if not self.engine.has_reliable_duration():
            return None
        current, total = self.engine.current_times()
        return max(0, total - current) if total else None

    def has_tracks(self) -> bool:
        return any(not track.played for track in self.tracks)

    def _double_clicked(self, item: QListWidgetItem) -> None:
        row = self.playlist.row(item)
        if 0 <= row < len(self.tracks) and not self.tracks[row].played:
            self.load_index(row, autoplay=self.play_on_double_click.isChecked())

    def _ended(self) -> None:
        if 0 <= self.current_index < len(self.tracks):
            self.tracks[self.current_index].played = True
            self._refresh_numbering()
            self.playlistChanged.emit()
        self.deckEnded.emit(self.side)
        self.advance_to_next(autoplay=False)

    def _loaded(self, track: Track) -> None:
        self._set_track_labels(track)

    def _set_track_labels(self, track: Track) -> None:
        title = " ".join(track.title.split()) or "Untitled"
        artist = " ".join((track.uploader or "Unknown artist").split())
        self.title_label.setText(title)
        self.meta_label.setText(artist)

    def _state_changed(self, state: str) -> None:
        self.state_label.setText(state)
        self.state_label.setToolTip(state)
        if not self.engine.is_playing():
            self.vu_meter.reset()

    def _update_vu(self, level: float) -> None:
        if self.engine.is_playing():
            self.vu_meter.set_level(level)
        else:
            self.vu_meter.reset()

    def _waveform_ready(self, data: object) -> None:
        if (0 <= self.current_index < len(self.tracks)
                and self.engine.track is self.tracks[self.current_index]):
            self.waveform.set_overview(data)

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
