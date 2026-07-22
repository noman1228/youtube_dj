from __future__ import annotations

import json
import math
import time
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .deck_widget import DeckWidget
from .karaoke_window import KaraokeWindow
from .models import Track
from .search_dialog import SearchDialog


class MainWindow(QMainWindow):
    _CROSSFADER_MAX = 1000

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("EncoreMix - MAIN")
        self.resize(1550, 900)
        self.setMinimumSize(1180, 720)

        self._search_dialog: SearchDialog | None = None
        self._karaoke_window: KaraokeWindow | None = None
        self._manual_crossfade = False
        self._transition_active = False
        self._pending_transition: tuple[str, str] | None = None
        self._transition_from = self._CROSSFADER_MAX // 2
        self._transition_to = self._CROSSFADER_MAX // 2
        self._transition_started = 0.0
        self._last_triggered_side: str | None = None
        self._karaoke_fade_start = 100
        self._karaoke_fade_target = 100
        self._karaoke_fade_started = 0.0
        self._karaoke_fade_updating = False

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(12)

        top = QFrame()
        top.setObjectName("TopBar")
        top_row = QHBoxLayout(top)
        title_col = QVBoxLayout()
        title = QLabel("EncoreMix 2026")
        title.setObjectName("AppTitle")
        subtitle = QLabel("DUAL-DECK STREAM MIXER")
        subtitle.setObjectName("Subtle")
        title_col.addWidget(title)
        title_col.addWidget(subtitle)
        top_row.addLayout(title_col)
        top_row.addStretch(1)
        search = QPushButton("SEARCH MUSIC")
        search.setObjectName("PrimaryButton")
        karaoke = QPushButton("KARAOKE LAB")
        karaoke.setObjectName("HotButton")
        search.clicked.connect(lambda: self.open_search(None))
        karaoke.clicked.connect(self.open_karaoke)
        top_row.addWidget(search)
        top_row.addWidget(karaoke)
        root.addWidget(top)

        decks_row = QHBoxLayout()
        decks_row.setSpacing(12)
        self.left = DeckWidget("left")
        self.right = DeckWidget("right")
        decks_row.addWidget(self.left, 1)

        center = QFrame()
        center.setObjectName("CenterConsole")
        center.setFixedWidth(235)
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(16, 18, 16, 18)
        center_layout.setSpacing(14)
        mix_title = QLabel("MIX BUS")
        mix_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mix_title.setStyleSheet("font-size:15pt;font-weight:900;letter-spacing:2px;")
        center_layout.addWidget(mix_title)

        self.auto_mix = QCheckBox("AUTO MIX")
        self.auto_mix.setChecked(True)
        self.auto_mix.setToolTip("Start the opposite deck when the dominant deck has 10 seconds remaining.")
        center_layout.addWidget(self.auto_mix)

        fade_label = QLabel("FADE SECONDS")
        fade_label.setObjectName("Subtle")
        self.fade_seconds = QSpinBox()
        self.fade_seconds.setRange(2, 10)
        self.fade_seconds.setValue(8)
        center_layout.addWidget(fade_label)
        center_layout.addWidget(self.fade_seconds)

        self.status = QLabel("AUTOMIX ARMED")
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status.setWordWrap(True)
        self.status.setStyleSheet("padding:12px;background:#0c111a;border-radius:10px;font-weight:800;")
        center_layout.addWidget(self.status)

        karaoke_remote = QFrame()
        karaoke_remote.setObjectName("DeckFrame")
        karaoke_remote_layout = QVBoxLayout(karaoke_remote)
        karaoke_remote_layout.setContentsMargins(9, 9, 9, 9)
        karaoke_remote_layout.setSpacing(7)
        karaoke_remote_title = QLabel("KARAOKE REMOTE")
        karaoke_remote_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        karaoke_remote_title.setStyleSheet("font-weight:800;letter-spacing:1px;")
        karaoke_remote_layout.addWidget(karaoke_remote_title)

        self.karaoke_play_button = QPushButton("PLAY / PAUSE")
        self.karaoke_play_button.setObjectName("HotButton")
        karaoke_remote_layout.addWidget(self.karaoke_play_button)

        karaoke_volume_row = QHBoxLayout()
        karaoke_volume_label = QLabel("VOL")
        karaoke_volume_label.setObjectName("Subtle")
        self.karaoke_volume = QSlider(Qt.Orientation.Horizontal)
        self.karaoke_volume.setRange(0, 100)
        self.karaoke_volume.setValue(100)
        karaoke_volume_row.addWidget(karaoke_volume_label)
        karaoke_volume_row.addWidget(self.karaoke_volume, 1)
        karaoke_remote_layout.addLayout(karaoke_volume_row)

        karaoke_fade_row = QHBoxLayout()
        self.karaoke_fade_out_button = QPushButton("FADE OUT")
        self.karaoke_fade_in_button = QPushButton("FADE IN")
        self.karaoke_fade_seconds = QSpinBox()
        self.karaoke_fade_seconds.setRange(1, 10)
        self.karaoke_fade_seconds.setValue(3)
        self.karaoke_fade_seconds.setSuffix(" s")
        self.karaoke_fade_seconds.setToolTip("Karaoke fade duration")
        karaoke_fade_row.addWidget(self.karaoke_fade_out_button)
        karaoke_fade_row.addWidget(self.karaoke_fade_in_button)
        karaoke_fade_row.addWidget(self.karaoke_fade_seconds)
        karaoke_remote_layout.addLayout(karaoke_fade_row)
        center_layout.addWidget(karaoke_remote)
        center_layout.addStretch(1)

        left_marker = QLabel("LEFT")
        right_marker = QLabel("RIGHT")
        marker_row = QHBoxLayout()
        marker_row.addWidget(left_marker)
        marker_row.addStretch(1)
        marker_row.addWidget(right_marker)
        center_layout.addLayout(marker_row)

        self.crossfader = QSlider(Qt.Orientation.Horizontal)
        self.crossfader.setObjectName("Crossfader")
        self.crossfader.setRange(0, self._CROSSFADER_MAX)
        self.crossfader.setValue(self._CROSSFADER_MAX // 2)
        center_layout.addWidget(self.crossfader)

        center_button_row = QHBoxLayout()
        cut_left = QPushButton("<")
        center_button = QPushButton("CENTER")
        cut_right = QPushButton(">")
        for button in (cut_left, center_button, cut_right):
            button.setObjectName("MixerButton")
        cut_left.setToolTip("Cut instantly to the left deck")
        center_button.setToolTip("Center both decks")
        cut_right.setToolTip("Cut instantly to the right deck")
        cut_left.clicked.connect(lambda: self.crossfader.setValue(0))
        center_button.clicked.connect(lambda: self.crossfader.setValue(self._CROSSFADER_MAX // 2))
        cut_right.clicked.connect(lambda: self.crossfader.setValue(self._CROSSFADER_MAX))
        center_button_row.addWidget(cut_left)
        center_button_row.addWidget(center_button)
        center_button_row.addWidget(cut_right)
        center_layout.addLayout(center_button_row)
        decks_row.addWidget(center)
        decks_row.addWidget(self.right, 1)
        root.addLayout(decks_row, 1)

        self.left.searchRequested.connect(self.open_search)
        self.right.searchRequested.connect(self.open_search)
        self.left.deckEnded.connect(self._deck_ended)
        self.right.deckEnded.connect(self._deck_ended)
        self.left.playbackStarted.connect(self._deck_started)
        self.right.playbackStarted.connect(self._deck_started)
        self.left.playlistChanged.connect(self._save_playlists)
        self.right.playlistChanged.connect(self._save_playlists)
        self.left.moveTrackRequested.connect(self._move_track)
        self.right.moveTrackRequested.connect(self._move_track)
        self.crossfader.valueChanged.connect(self._apply_crossfader)
        self.crossfader.sliderPressed.connect(self._manual_fade_started)
        self.crossfader.sliderReleased.connect(self._manual_fade_finished)
        self.karaoke_play_button.clicked.connect(self._toggle_karaoke)
        self.karaoke_volume.valueChanged.connect(self._set_karaoke_volume)
        self.karaoke_fade_out_button.clicked.connect(lambda: self._start_karaoke_fade(0))
        self.karaoke_fade_in_button.clicked.connect(lambda: self._start_karaoke_fade(100))

        self._automation_timer = QTimer(self)
        self._automation_timer.setInterval(200)
        self._automation_timer.timeout.connect(self._automation_tick)
        self._automation_timer.start()

        self._fade_timer = QTimer(self)
        self._fade_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._fade_timer.setInterval(20)
        self._fade_timer.timeout.connect(self._fade_tick)

        self._karaoke_fade_timer = QTimer(self)
        self._karaoke_fade_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._karaoke_fade_timer.setInterval(20)
        self._karaoke_fade_timer.timeout.connect(self._karaoke_fade_tick)

        self._apply_crossfader(self._CROSSFADER_MAX // 2)
        QTimer.singleShot(0, self._load_playlists)

    def open_search(self, preferred_side: str | None) -> None:
        if self._search_dialog is None:
            self._search_dialog = SearchDialog(self)
            self._search_dialog.trackAdded.connect(self._add_search_track)
        if preferred_side:
            self._search_dialog.status.setText(f"Search results can be added to {preferred_side.upper()} or the opposite deck.")
        self._search_dialog.show()
        self._search_dialog.raise_()
        self._search_dialog.activateWindow()
        self._search_dialog.focus_search()

    def open_karaoke(self) -> None:
        karaoke = self._get_karaoke_window()
        karaoke.show()
        karaoke.raise_()
        karaoke.activateWindow()

    def _get_karaoke_window(self) -> KaraokeWindow:
        if self._karaoke_window is None:
            self._karaoke_window = KaraokeWindow(self)
            self._karaoke_window.volume.setValue(self.karaoke_volume.value())
            self._karaoke_window.volume.valueChanged.connect(self._sync_karaoke_volume)
        return self._karaoke_window

    def _toggle_karaoke(self) -> None:
        self._get_karaoke_window().play()

    def _set_karaoke_volume(self, value: int) -> None:
        self._karaoke_fade_timer.stop()
        if self._karaoke_window is not None:
            self._karaoke_window.volume.setValue(value)

    def _sync_karaoke_volume(self, value: int) -> None:
        if not self._karaoke_fade_updating:
            self._karaoke_fade_timer.stop()
        if self.karaoke_volume.value() != value:
            self.karaoke_volume.blockSignals(True)
            self.karaoke_volume.setValue(value)
            self.karaoke_volume.blockSignals(False)

    def _start_karaoke_fade(self, target: int) -> None:
        karaoke = self._get_karaoke_window()
        if target > 0 and not karaoke.engine.is_playing():
            karaoke.play()
        self._karaoke_fade_start = self.karaoke_volume.value()
        self._karaoke_fade_target = target
        self._karaoke_fade_started = time.monotonic()
        self._karaoke_fade_timer.start()

    def _karaoke_fade_tick(self) -> None:
        duration = max(0.25, float(self.karaoke_fade_seconds.value()))
        progress = min(1.0, (time.monotonic() - self._karaoke_fade_started) / duration)
        eased = progress * progress * (3.0 - 2.0 * progress)
        value = round(
            self._karaoke_fade_start
            + (self._karaoke_fade_target - self._karaoke_fade_start) * eased
        )
        # Temporarily block the user-change handler so the animation does not
        # cancel its own timer; the karaoke slider keeps both UIs synchronized.
        self.karaoke_volume.blockSignals(True)
        self.karaoke_volume.setValue(value)
        self.karaoke_volume.blockSignals(False)
        self._karaoke_fade_updating = True
        self._get_karaoke_window().volume.setValue(value)
        self._karaoke_fade_updating = False
        if progress >= 1.0:
            self._karaoke_fade_timer.stop()

    def _add_search_track(self, side: str, track: Track) -> None:
        deck = self.left if side == "left" else self.right
        # Each playlist entry owns its played state, even when the same search
        # result is added to both decks or added more than once.
        deck.add_track(Track.from_dict(track.to_dict()))
        self.status.setText(f"ADDED TO {side.upper()}:\n{track.title}")

    def _move_track(self, from_side: str, row: int) -> None:
        source = self.left if from_side == "left" else self.right
        target = self.right if from_side == "left" else self.left
        track = source.take_track(row)
        if track is None:
            return
        target.add_track(track)
        self.status.setText(
            f"MOVED TO {target.side.upper()}:\n{track.title}"
        )

    def _apply_crossfader(self, value: int) -> None:
        position = value / self._CROSSFADER_MAX
        # Equal-power curve: avoids a deep volume sag at center.
        left_factor = math.cos(position * math.pi / 2)
        right_factor = math.sin(position * math.pi / 2)
        self.left.set_crossfade_factor(left_factor)
        self.right.set_crossfade_factor(right_factor)

    def _manual_fade_started(self) -> None:
        self._manual_crossfade = True
        self._cancel_transition("MANUAL MIX")

    def _manual_fade_finished(self) -> None:
        self._manual_crossfade = False

    def _automation_tick(self) -> None:
        if not self.auto_mix.isChecked() or self._transition_active or self._pending_transition or self._manual_crossfade:
            return
        value = self.crossfader.value()
        candidates = []
        if self.left.engine.is_playing() and value <= self._CROSSFADER_MAX * 0.55:
            candidates.append(("left", self.left.current_remaining_ms()))
        if self.right.engine.is_playing() and value >= self._CROSSFADER_MAX * 0.45:
            candidates.append(("right", self.right.current_remaining_ms()))
        for side, remaining in candidates:
            if 0 < remaining <= 10_000 and self._last_triggered_side != side:
                self._request_automix(side)
                break

    def _request_automix(self, from_side: str) -> None:
        to_side = "right" if from_side == "left" else "left"
        target = self.right if to_side == "right" else self.left
        if not target.has_tracks():
            self.status.setText(f"AUTOMIX NEEDS A TRACK ON {to_side.upper()}")
            return
        self._last_triggered_side = from_side
        self._pending_transition = (from_side, to_side)
        self.status.setText(f"PREPARING {to_side.upper()} DECK…")
        if target.engine.is_playing():
            self._begin_transition(from_side, to_side)
        else:
            target.play()

    def _deck_started(self, side: str) -> None:
        if self._pending_transition and self._pending_transition[1] == side:
            from_side, to_side = self._pending_transition
            self._begin_transition(from_side, to_side)

    def _begin_transition(self, from_side: str, to_side: str) -> None:
        self._pending_transition = None
        self._transition_active = True
        self._transition_from = self.crossfader.value()
        self._transition_to = self._CROSSFADER_MAX if to_side == "right" else 0
        self._transition_started = time.monotonic()
        self.status.setText(f"AUTOMIX {from_side.upper()} → {to_side.upper()}")
        self._fade_timer.start()

    def _fade_tick(self) -> None:
        duration = max(0.5, float(self.fade_seconds.value()))
        progress = min(1.0, (time.monotonic() - self._transition_started) / duration)
        eased = progress * progress * (3.0 - 2.0 * progress)
        value = round(self._transition_from + (self._transition_to - self._transition_from) * eased)
        self.crossfader.setValue(value)
        if progress >= 1.0:
            self._fade_timer.stop()
            # setValue() emits nothing when rounding reached the endpoint on an
            # earlier tick, so explicitly enforce full gain on the new deck.
            self._apply_crossfader(self._transition_to)
            self._transition_active = False
            self.status.setText("AUTOMIX COMPLETE")

    def _deck_ended(self, side: str) -> None:
        if self._last_triggered_side == side:
            self._last_triggered_side = None
        if self._pending_transition and self._pending_transition[0] == side:
            self._pending_transition = None
        deck = self.left if side == "left" else self.right
        if deck.has_tracks():
            self.status.setText(f"{side.upper()} ADVANCED TO NEXT TRACK")
        else:
            self.status.setText(f"{side.upper()} PLAYLIST COMPLETE")

    def _cancel_transition(self, reason: str) -> None:
        self._fade_timer.stop()
        self._transition_active = False
        self._pending_transition = None
        self.status.setText(reason)

    @property
    def _playlist_path(self) -> Path:
        path = Path.home() / ".youtube_dj"
        path.mkdir(parents=True, exist_ok=True)
        return path / "playlists.json"

    def _save_playlists(self) -> None:
        data = {
            "left": [track.to_dict() for track in self.left.tracks],
            "right": [track.to_dict() for track in self.right.tracks],
            # Keep the persisted value in the original 0-100 format.
            "crossfader": round(self.crossfader.value() / self._CROSSFADER_MAX * 100),
            "auto_mix": self.auto_mix.isChecked(),
            "fade_seconds": self.fade_seconds.value(),
        }
        try:
            self._playlist_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError:
            pass

    def _load_playlists(self) -> None:
        try:
            data = json.loads(self._playlist_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        try:
            self.left.set_tracks([Track.from_dict(item) for item in data.get("left", [])])
            self.right.set_tracks([Track.from_dict(item) for item in data.get("right", [])])
            saved_crossfader = max(0, min(100, int(data.get("crossfader", 50))))
            self.crossfader.setValue(round(saved_crossfader / 100 * self._CROSSFADER_MAX))
            self.auto_mix.setChecked(bool(data.get("auto_mix", True)))
            self.fade_seconds.setValue(int(data.get("fade_seconds", 8)))
        except (TypeError, ValueError) as exc:
            QMessageBox.warning(self, "Playlist restore", f"The saved playlist file could not be restored: {exc}")

    def closeEvent(self, event: QCloseEvent) -> None:
        self._save_playlists()
        self.left.engine.stop()
        self.right.engine.stop()
        super().closeEvent(event)
