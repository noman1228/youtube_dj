from __future__ import annotations

import json
import math
import time
from pathlib import Path

from PySide6.QtCore import (QEvent, QObject, QParallelAnimationGroup, QPropertyAnimation,
                            QSignalBlocker, QTime, QTimer, QVariantAnimation, Qt)
from PySide6.QtGui import QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QListWidgetItem, QMainWindow, QMessageBox

from .ui_loader import load_ui

from .beat import (
    BeatInfo,
    bar_fade_seconds,
    delay_to_next_beat_ms,
    matched_playback_rate,
    normalized_target_bpm,
    phase_error_cycles,
)
from .appearance_dialog import AppearanceDialog, AppearanceShortcut
from .deck_widget import DeckWidget
from .karaoke_window import KaraokeWindow
from .logo_pulse import LogoPulseController
from .models import Track
from .projector_preview import ProjectorPreview
from .search_dialog import SearchDialog
from .similar_search import youtube_id
from .song_suggestions import SongSuggestions
from .symmetric_scroll_area import SymmetricScrollArea


class MainWindow(QMainWindow):
    _CROSSFADER_MAX = 1000
    _AUTOMIX_MIN_PLAYED_MS = 5_000

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("EncoreMix - MAIN")
        self.resize(1550, 900)
        self.setMinimumSize(1180, 720)
        self._fullscreen_was_maximized = False
        self._appearance_dialog: AppearanceDialog | None = None
        self._appearance_shortcut = AppearanceShortcut(self)
        self._appearance_shortcut.activated.connect(self._open_appearance)

        self._fullscreen_shortcut = QShortcut(QKeySequence("F11"), self)
        self._fullscreen_shortcut.setAutoRepeat(False)
        self._fullscreen_shortcut.activated.connect(self._toggle_fullscreen)
        self._exit_fullscreen_shortcut = QShortcut(QKeySequence("Escape"), self)
        self._exit_fullscreen_shortcut.setEnabled(False)
        self._exit_fullscreen_shortcut.activated.connect(self._exit_fullscreen)

        self._search_dialog: SearchDialog | None = None
        self._karaoke_window: KaraokeWindow | None = None
        self._logo_pulse: LogoPulseController | None = None
        self._manual_crossfade = False
        self._transition_active = False
        self._pending_transition: tuple[str, str] | None = None
        self._transition_from = self._CROSSFADER_MAX // 2
        self._transition_to = self._CROSSFADER_MAX // 2
        self._transition_started = 0.0
        self._transition_hold_started: float | None = None
        self._transition_hold_source_ms = 0
        self._transition_duration = 8.0
        self._transition_beat_matched = False
        self._transition_total_beats = 0
        self._transition_source_side: str | None = None
        self._transition_target_side: str | None = None
        self._transition_source_start_ms = 0.0
        self._transition_beat_interval_ms = 0.0
        self._transition_last_reported_beat = -1
        self._transition_target_grid_bpm = 0.0
        self._transition_target_base_rate = 1.0
        self._beat_analysis_target: str | None = None
        self._beat_analysis_started = 0.0
        self._beat_analysis_requested = 0.0
        self._beat_launch_in_progress = False
        self._beat_phase_settling = False
        self._last_triggered_side: str | None = None
        self._karaoke_width_animation: QParallelAnimationGroup | None = None
        self._karaoke_normal_left_width = 0
        self._karaoke_normal_right_width = 0
        self._karaoke_normal_suggestions_height = 0
        self._karaoke_normal_preview_height = 112
        self._suggestion_height_animation: QPropertyAnimation | None = None

        ui = load_ui(self, "main_window.ui", {
            "DeckWidget": lambda parent, name: DeckWidget(name, parent),
            "ProjectorPreview": lambda parent, _name: ProjectorPreview(parent),
            "SongSuggestions": lambda parent, _name: SongSuggestions(self._suggestion_context, parent),
            "SymmetricScrollArea": lambda parent, _name: SymmetricScrollArea(parent),
        })
        self.center = ui.center
        self._suggestion_visible_height = self.song_suggestions.sizeHint().height()
        ui.controls_scroll.viewport().setObjectName("CenterControlsViewport")
        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(1000)
        self._clock_timer.timeout.connect(self._update_clock)
        self._update_clock()
        self._clock_timer.start()
        self.fullscreen_button.clicked.connect(self._toggle_fullscreen)
        ui.cut_left.clicked.connect(lambda: self.crossfader.setValue(0))
        ui.center_button.clicked.connect(lambda: self.crossfader.setValue(self._CROSSFADER_MAX // 2))
        ui.cut_right.clicked.connect(lambda: self.crossfader.setValue(self._CROSSFADER_MAX))
        self.song_suggestions.addRequested.connect(self._add_suggestion)
        self.song_suggestions.resultsChanged.connect(self._sync_suggestions_layout)
        for deck in (self.left, self.right):
            deck.installEventFilter(self)
        self._sync_deck_header_layout()

        self.left.searchRequested.connect(self.open_search)
        self.right.searchRequested.connect(self.open_search)
        self.left.deckEnded.connect(self._deck_ended)
        self.right.deckEnded.connect(self._deck_ended)
        self.left.playbackStarted.connect(self._deck_started)
        self.right.playbackStarted.connect(self._deck_started)
        self.left.playlistChanged.connect(self._save_playlists)
        self.right.playlistChanged.connect(self._save_playlists)
        self.left.play_on_double_click.toggled.connect(self._save_playlists)
        self.right.play_on_double_click.toggled.connect(self._save_playlists)
        self.left.moveTrackRequested.connect(self._move_track)
        self.right.moveTrackRequested.connect(self._move_track)
        self.crossfader.valueChanged.connect(self._apply_crossfader)
        self.crossfader.sliderPressed.connect(self._manual_fade_started)
        self.crossfader.sliderReleased.connect(self._manual_fade_finished)
        self.karaoke_lab_button.clicked.connect(self.open_karaoke)
        self.karaoke_play_button.clicked.connect(self._toggle_karaoke)
        self.karaoke_projector_button.toggled.connect(self._toggle_karaoke_projector)
        self.karaoke_volume.valueChanged.connect(self._set_karaoke_volume)
        self.karaoke_playlist.itemDoubleClicked.connect(self._play_karaoke_queue_item)
        self.beat_match.toggled.connect(self._sync_fade_mode_controls)

        for button in (
            self.left.play_button, self.left.stop_button, self.left.next_button,
            self.right.play_button, self.right.stop_button, self.right.next_button,
            self.karaoke_play_button,
        ):
            button.setAutoDefault(False)
            button.setDefault(False)
            button.installEventFilter(self)

        self._automation_timer = QTimer(self)
        self._automation_timer.setInterval(200)
        self._automation_timer.timeout.connect(self._automation_tick)
        self._automation_timer.start()

        self._fade_timer = QTimer(self)
        self._fade_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._fade_timer.setInterval(20)
        self._fade_timer.timeout.connect(self._fade_tick)

        self._beat_launch_timer = QTimer(self)
        self._beat_launch_timer.setSingleShot(True)
        self._beat_launch_timer.timeout.connect(self._launch_pending_transition)

        self._beat_settle_timer = QTimer(self)
        self._beat_settle_timer.setSingleShot(True)
        self._beat_settle_timer.timeout.connect(self._settle_beat_transition)

        self._beat_mix_start_timer = QTimer(self)
        self._beat_mix_start_timer.setSingleShot(True)
        self._beat_mix_start_timer.timeout.connect(self._start_aligned_transition)

        self._karaoke_blink_timer = QTimer(self)
        self._karaoke_blink_timer.setInterval(600)
        self._karaoke_blink_timer.timeout.connect(self._blink_karaoke_remote)

        self._apply_crossfader(self._CROSSFADER_MAX // 2)
        self._sync_fade_mode_controls()
        QTimer.singleShot(0, self._load_playlists)

    def _update_clock(self) -> None:
        self.clock_display.setText(QTime.currentTime().toString("h:mm:ss AP"))

    def _sync_suggestions_layout(self, has_results: bool) -> None:
        target = self.song_suggestions.sizeHint().height() if has_results else self.song_suggestions.sizeHint().height()
        if self.karaoke_remote.property("playing"):
            self._karaoke_normal_suggestions_height = target
            return
        if self._suggestion_height_animation is not None:
            self._suggestion_height_animation.stop()
        current = self._suggestion_visible_height
        self.song_suggestions.setMaximumHeight(current)
        animation = QPropertyAnimation(self.song_suggestions, b"maximumHeight", self)
        animation.setDuration(300)
        animation.setStartValue(current)
        animation.setEndValue(target)
        def finish_suggestions_animation() -> None:
            self.song_suggestions.setMaximumHeight(target)
            self._suggestion_visible_height = target

        animation.finished.connect(finish_suggestions_animation)
        self._suggestion_height_animation = animation
        animation.start()

    def _open_appearance(self) -> None:
        if self._appearance_dialog is None:
            self._appearance_dialog = AppearanceDialog(self)
        self._appearance_dialog.show()
        self._appearance_dialog.raise_()
        self._appearance_dialog.activateWindow()

    def _toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self._exit_fullscreen()
        else:
            self._fullscreen_was_maximized = self.isMaximized()
            self.showFullScreen()

    def _exit_fullscreen(self) -> None:
        if self.isFullScreen():
            if self._fullscreen_was_maximized:
                self.showMaximized()
            else:
                self.showNormal()

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange and hasattr(self, "fullscreen_button"):
            fullscreen = self.isFullScreen()
            self.fullscreen_button.setChecked(fullscreen)
            self.fullscreen_button.setText("EXIT FULL SCREEN" if fullscreen else "FULL SCREEN")
            self._exit_fullscreen_shortcut.setEnabled(fullscreen)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched in (self.left, self.right) and event.type() in (
            QEvent.Type.Resize, QEvent.Type.ContentsRectChange, QEvent.Type.LayoutRequest,
        ):
            self._sync_deck_header_layout()
        # Playback controls must not activate on Return or numeric-keypad Enter.
        if event.type() in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                event.accept()
                return True
        return super().eventFilter(watched, event)

    def _sync_deck_header_layout(self) -> None:
        # The LEFT/RIGHT labels have different widths. A shared breakpoint keeps
        # the action rows and playlists aligned even at the one-pixel boundary.
        decks = (self.left, self.right)
        two_rows = any(
            deck.contentsRect().width() - deck.layout().contentsMargins().left()
            - deck.layout().contentsMargins().right() < deck.playlist_header.sizeHint().width()
            for deck in decks
        )
        for deck in decks:
            deck.playlist_header.set_two_rows(two_rows)

    def open_search(self, preferred_side: str | None) -> None:
        if self._search_dialog is None:
            self._search_dialog = SearchDialog(self)
            self._search_dialog.trackAdded.connect(self._add_search_track)
            self._search_dialog.similarRequested.connect(self._search_similar)
        if preferred_side:
            self._search_dialog.status.setText(f"Search results can be added to {preferred_side.upper()} or the opposite deck.")
        self._search_dialog.show()
        self._search_dialog.raise_()
        self._search_dialog.activateWindow()
        self._search_dialog.focus_search()

    def _suggestion_context(self) -> tuple[Track | None, str, bool, set[str]]:
        decks = (self.left, self.right)
        audible = [deck for deck in decks if deck.engine.has_playback_progress()
                   and deck.engine._gain * deck.engine._crossfade_factor > 0]
        deck = max(audible, key=lambda item: item.engine._gain * item.engine._crossfade_factor,
                   default=None)
        engines = [item.engine for item in decks]
        if self._karaoke_window is not None:
            engines.append(self._karaoke_window.engine)
        busy = bool(self._transition_active or self._pending_transition or self._manual_crossfade)
        for engine in engines:
            analysis = engine._waveform_analysis
            busy = busy or engine.is_preparing() or engine._pool.activeThreadCount() > 0
            busy = busy or bool(engine._prefetch_task)
            busy = busy or bool(analysis and (analysis._active or analysis._pending))
        for dialog in (self._search_dialog, self._karaoke_window):
            if dialog is not None:
                busy = busy or bool(dialog._active_tasks) or dialog._pool.activeThreadCount() > 0
        if self._karaoke_window and self._karaoke_window.engine.is_playing():
            busy = True
        excluded = {youtube_id(track) for item in decks for track in item.tracks}
        return (deck.engine.track if deck else None, deck.side if deck else "", busy, excluded)

    def _add_suggestion(self, side: str, track: Track) -> None:
        deck = self.left if side == "left" else self.right
        if any(youtube_id(item) == youtube_id(track) for item in deck.tracks):
            return
        deck.add_track(Track.from_dict(track.to_dict()), load_if_empty=False)
        self.status.setText(f"ADDED TO {side.upper()}:\n{track.title}")

    def _search_similar(self, side: str) -> None:
        deck = self.left if side == "left" else self.right
        track = deck.engine.track
        if track is None or not youtube_id(track):
            self._search_dialog.status.setText(f"Load a YouTube or YouTube Music track in {side.upper()} first.")
            return
        excluded = {youtube_id(item) for item in deck.tracks}
        # Don't immediately suggest the same result on the next click.
        excluded.update(self._search_dialog._seen_results)
        self._search_dialog.search_similar(track, side, excluded)

    def open_karaoke(self) -> None:
        karaoke = self._get_karaoke_window()
        karaoke.show()
        karaoke.raise_()
        karaoke.activateWindow()

    def _get_karaoke_window(self) -> KaraokeWindow:
        if self._karaoke_window is None:
            self._karaoke_window = KaraokeWindow(self)
            self.projector_preview.set_source(self._karaoke_window.projector.video)
            self._karaoke_window.volume.setValue(self.karaoke_volume.value())
            self._karaoke_window.volume.valueChanged.connect(self._sync_karaoke_volume)
            self._karaoke_window.queueChanged.connect(self._sync_karaoke_playlist)
            self._karaoke_window.projectorVisibilityChanged.connect(
                self._sync_karaoke_projector_button
            )
            self._karaoke_window.engine.stateChanged.connect(self._sync_karaoke_playback)
            self._logo_pulse = LogoPulseController(
                (self.left.engine, self.right.engine), self._karaoke_window.projector.video, self
            )
            self._sync_karaoke_playlist()
        return self._karaoke_window

    def _sync_karaoke_playback(self, _state: str = "") -> None:
        playing = bool(self._karaoke_window and self._karaoke_window.engine.is_playing())
        if playing == self.karaoke_remote.property("playing"):
            return
        self._animate_karaoke_layout(playing)
        self.karaoke_remote.setProperty("playing", playing)
        self.karaoke_remote.setProperty("flashOn", playing)
        self.karaoke_remote_title.setText("KARAOKE PLAYING" if playing else "KARAOKE REMOTE")
        if playing:
            self._karaoke_blink_timer.start()
        else:
            self._karaoke_blink_timer.stop()
        self._refresh_karaoke_highlight()

    def _animate_karaoke_layout(self, playing: bool) -> None:
        if self._karaoke_width_animation is not None:
            self._karaoke_width_animation.stop()
        for deck in (self.left, self.right):
            deck.set_karaoke_compact(playing)
        current_deck_width = self.left.width()
        current_right_width = self.right.width()
        current_center_width = self.center.width()
        shrink = int((QApplication.instance().property("appearance") or {}).get(
            "karaoke_deck_shrink", 35
        )) / 100
        target_left_width = round(current_deck_width * (1 - shrink)) if playing else self._karaoke_normal_left_width
        target_right_width = round(current_right_width * (1 - shrink)) if playing else self._karaoke_normal_right_width
        target_center_width = (current_center_width + current_deck_width - target_left_width
                               + current_right_width - target_right_width)
        if not playing:
            target_center_width = self._karaoke_normal_center_width
        else:
            self._karaoke_normal_left_width = current_deck_width
            self._karaoke_normal_right_width = current_right_width
            self._karaoke_normal_center_width = current_center_width
        group = QParallelAnimationGroup(self)
        start_widths = (current_deck_width, current_right_width, current_center_width)
        target_widths = (target_left_width, target_right_width, target_center_width)
        widths = QVariantAnimation(group)
        widths.setDuration(450)
        widths.setStartValue(0.0)
        widths.setEndValue(1.0)

        def update_widths(progress: object) -> None:
            fraction = float(progress)
            values = tuple(round(start + (target - start) * fraction)
                           for start, target in zip(start_widths, target_widths))
            self.left.setFixedWidth(values[0])
            self.right.setFixedWidth(values[1])
            self.center.setFixedWidth(values[2])
            for widget in (self.left, self.right, self.center, self.karaoke_remote):
                layout = widget.layout()
                if layout is not None:
                    layout.activate()
                widget.updateGeometry()

        widths.valueChanged.connect(update_widths)
        group.addAnimation(widths)
        preview_height = self.projector_preview.height()
        if playing:
            self._karaoke_normal_preview_height = preview_height
            self._karaoke_normal_suggestions_height = self._suggestion_visible_height
            playlist_height = self.karaoke_playlist.height()
            target_preview_height = preview_height + max(0, playlist_height - self.karaoke_playlist.minimumHeight())
            target_preview_height += self._karaoke_normal_suggestions_height
            suggestions_target = 0
        else:
            target_preview_height = self._karaoke_normal_preview_height
            suggestions_target = self._karaoke_normal_suggestions_height
        suggestions = QPropertyAnimation(self.song_suggestions, b"maximumHeight", group)
        suggestions.setDuration(450)
        suggestions.setStartValue(self.song_suggestions.height())
        suggestions.setEndValue(suggestions_target)
        group.addAnimation(suggestions)
        for property_name in (b"minimumHeight", b"maximumHeight"):
            preview = QPropertyAnimation(self.projector_preview, property_name, group)
            preview.setDuration(450)
            preview.setStartValue(self.projector_preview.height())
            preview.setEndValue(target_preview_height)
            group.addAnimation(preview)

        def release_widths() -> None:
            if playing:
                self.left.setFixedWidth(target_left_width)
                self.right.setFixedWidth(target_right_width)
                self.center.setFixedWidth(target_center_width)
            else:
                self.left.setFixedWidth(target_left_width)
                self.right.setFixedWidth(target_right_width)
                self.center.setFixedWidth(target_center_width)
                self._suggestion_visible_height = suggestions_target
                for deck in (self.left, self.right):
                    deck.set_karaoke_compact(False)

        group.finished.connect(release_widths)
        self._karaoke_width_animation = group
        group.start()

    def _blink_karaoke_remote(self) -> None:
        self._sync_karaoke_playback()
        if not self.karaoke_remote.property("playing"):
            return
        self.karaoke_remote.setProperty("flashOn", not self.karaoke_remote.property("flashOn"))
        self._refresh_karaoke_highlight()

    def _refresh_karaoke_highlight(self) -> None:
        for widget in (self.karaoke_remote, self.karaoke_remote_title):
            widget.style().unpolish(widget)
            widget.style().polish(widget)
            widget.update()
        layout = self.karaoke_remote.layout()
        if layout is not None:
            layout.invalidate()
            layout.activate()
        self.karaoke_remote.updateGeometry()

    def _sync_karaoke_playlist(self) -> None:
        karaoke = self._karaoke_window
        if karaoke is None:
            self.karaoke_playlist.clear()
            return
        self.karaoke_playlist.clear()
        for row in range(karaoke.playlist.count()):
            source_item = karaoke.playlist.item(row)
            if source_item is not None:
                item = source_item.clone()
                font = item.font()
                font.setPointSize(9)
                item.setFont(font)
                item.setToolTip(source_item.text())
                self.karaoke_playlist.addItem(item)
        if 0 <= karaoke.current_index < self.karaoke_playlist.count():
            self.karaoke_playlist.setCurrentRow(karaoke.current_index)

    def _play_karaoke_queue_item(self, item: QListWidgetItem) -> None:
        index = self.karaoke_playlist.row(item)
        self._get_karaoke_window().play_index(index)

    def _toggle_karaoke(self) -> None:
        self._get_karaoke_window().play()

    def _toggle_karaoke_projector(self, visible: bool) -> None:
        if visible:
            self._get_karaoke_window().open_projector()
        elif self._karaoke_window is not None:
            self._karaoke_window.hide_projector()

    def _sync_karaoke_projector_button(self, visible: bool) -> None:
        self.karaoke_projector_button.blockSignals(True)
        self.karaoke_projector_button.setChecked(visible)
        self.karaoke_projector_button.setText(
            "CLOSE PROJECTOR" if visible else "SHOW PROJECTOR"
        )
        self.karaoke_projector_button.blockSignals(False)

    def _set_karaoke_volume(self, value: int) -> None:
        if self._karaoke_window is not None:
            self._karaoke_window.volume.setValue(value)

    def _sync_karaoke_volume(self, value: int) -> None:
        if self.karaoke_volume.value() != value:
            self.karaoke_volume.blockSignals(True)
            self.karaoke_volume.setValue(value)
            self.karaoke_volume.blockSignals(False)

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

    def _sync_fade_mode_controls(self, _checked: bool | None = None) -> None:
        beat_mode = self.beat_match.isChecked()
        self.fade_bars_label.setVisible(beat_mode)
        self.fade_bars.setVisible(beat_mode)
        self.fade_label.setVisible(not beat_mode)
        self.fade_seconds.setVisible(not beat_mode)

    def _automation_tick(self) -> None:
        if not self.auto_mix.isChecked():
            if self._pending_transition:
                self._cancel_transition("AUTOMIX DISARMED")
            return
        if self._beat_analysis_target is not None:
            self._beat_analysis_tick()
            return
        if self._transition_active or self._pending_transition or self._manual_crossfade:
            return
        value = self.crossfader.value()
        candidates = []
        if self.left.engine.is_playing() and value <= self._CROSSFADER_MAX * 0.55:
            candidates.append(("left", self.left.current_remaining_ms()))
        if self.right.engine.is_playing() and value >= self._CROSSFADER_MAX * 0.45:
            candidates.append(("right", self.right.current_remaining_ms()))
        for side, remaining in candidates:
            if remaining is None:
                continue
            trigger_ms = 10_000
            if self.beat_match.isChecked():
                source = self.left if side == "left" else self.right
                info = source.engine.beat_info()
                effective_bpm = (
                    info.bpm * source.engine.playback_rate() if info is not None else 120.0
                )
                beat_fade = bar_fade_seconds(self.fade_bars.value(), effective_bpm)
                trigger_ms = max(trigger_ms, round((beat_fade + 7.0) * 1000))
            source = self.left if side == "left" else self.right
            position_ms, duration_ms = source.engine.current_times()
            long_enough = duration_ms >= trigger_ms + self._AUTOMIX_MIN_PLAYED_MS
            if (
                long_enough
                and position_ms >= self._AUTOMIX_MIN_PLAYED_MS
                and 0 < remaining <= trigger_ms
                and self._last_triggered_side != side
            ):
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
        if self.beat_match.isChecked() and not target.engine.is_playing():
            self._beat_analysis_target = to_side
            self._beat_analysis_started = 0.0
            self._beat_analysis_requested = time.monotonic()
            target.engine.set_playback_rate(1.0)
            target.engine.set_analysis_muted(True)
            self.status.setText(f"ANALYZING {to_side.upper()} BEATS...")
            target.play()
            return
        self.status.setText(f"PREPARING {to_side.upper()} DECK…")
        if target.engine.is_playing():
            self._begin_transition(from_side, to_side)
        else:
            target.play()

    def _deck_started(self, side: str) -> None:
        if self._beat_launch_in_progress:
            return
        if (
            self._beat_phase_settling
            and self._pending_transition
            and self._pending_transition[1] == side
        ):
            return
        if self._beat_analysis_target == side:
            if self._beat_analysis_started <= 0:
                self._beat_analysis_started = time.monotonic()
            return
        if self._pending_transition and self._pending_transition[1] == side:
            from_side, to_side = self._pending_transition
            self._begin_transition(from_side, to_side)

    def _beat_analysis_tick(self) -> None:
        if not self._pending_transition:
            return
        from_side, to_side = self._pending_transition
        source = self.left if from_side == "left" else self.right
        target = self.left if to_side == "left" else self.right
        if self._beat_analysis_started <= 0:
            if target.engine.is_preparing():
                self._beat_analysis_requested = time.monotonic()
                return
            if time.monotonic() - self._beat_analysis_requested >= 12.0:
                self._cancel_transition("INCOMING DECK COULD NOT START")
            return
        source_info = source.engine.beat_info()
        target_info = target.engine.beat_info()
        elapsed = time.monotonic() - self._beat_analysis_started
        if elapsed >= 0.5 and not target.engine.is_playing():
            self._cancel_transition("INCOMING BEAT ANALYSIS STOPPED")
            return
        confident = self._usable_beat_info(source_info) and self._usable_beat_info(target_info)
        if not confident and elapsed < 5.0:
            return

        self._beat_analysis_target = None
        self._beat_analysis_started = 0.0
        self._beat_analysis_requested = 0.0
        target.engine.pause()
        if confident and source_info is not None and target_info is not None:
            source_rate = source.engine.playback_rate()
            effective_bpm = source_info.bpm * source_rate
            target_grid_bpm = normalized_target_bpm(
                effective_bpm, target_info.bpm
            )
            target_rate = matched_playback_rate(
                source_info.bpm,
                source_rate,
                target_info.bpm,
            )
            target.engine.set_playback_rate(target_rate)
            target.engine.seek_ms(target_info.phase_ms)
            source_position, _duration = source.engine.current_times()
            delay_ms = delay_to_next_beat_ms(
                source_position,
                source_info.phase_ms,
                source_info.bpm,
                source_rate,
            )
            self._transition_total_beats = self.fade_bars.value() * 4
            self._transition_duration = bar_fade_seconds(
                self.fade_bars.value(), effective_bpm
            )
            self._transition_target_grid_bpm = target_grid_bpm
            self._transition_target_base_rate = target_rate
            self._transition_beat_matched = True
            self.status.setText(
                f"TEMPO LOCK {effective_bpm:.1f} BPM\n"
                f"INCOMING {target_info.bpm:.1f} x {target_rate:.3f}"
            )
            self._beat_launch_timer.start(delay_ms)
            return

        target.engine.set_playback_rate(1.0)
        target.engine.seek_ms(0)
        self._transition_duration = float(self.fade_seconds.value())
        self._transition_beat_matched = False
        self._transition_total_beats = 0
        self._transition_target_grid_bpm = 0.0
        self._transition_target_base_rate = 1.0
        self.status.setText("BEAT NOT FOUND - TIMED MIX")
        self._beat_launch_timer.start(0)

    @staticmethod
    def _usable_beat_info(info: BeatInfo | None) -> bool:
        return bool(info and 70.0 <= info.bpm <= 180.0 and info.confidence >= 0.45)

    def _launch_pending_transition(self) -> None:
        if not self._pending_transition:
            return
        from_side, to_side = self._pending_transition
        target = self.left if to_side == "left" else self.right
        self._beat_phase_settling = True
        self._beat_launch_in_progress = True
        try:
            target.engine.play()
        finally:
            self._beat_launch_in_progress = False
        if self._transition_beat_matched:
            self.status.setText("TEMPO LOCKED - SETTLING PHASE")
            self._beat_settle_timer.start(180)
            return
        self._beat_mix_start_timer.start(0)

    def _settle_beat_transition(self) -> None:
        if not self._pending_transition:
            return
        from_side, to_side = self._pending_transition
        source = self.left if from_side == "left" else self.right
        target = self.left if to_side == "left" else self.right
        if not self._incoming_deck_ready(to_side):
            self._beat_settle_timer.start(50)
            return
        source_info = source.engine.beat_info()
        target_info = target.engine.beat_info()
        if source_info is None or target_info is None or self._transition_target_grid_bpm <= 0:
            self._transition_beat_matched = False
            self._transition_total_beats = 0
            target.engine.set_playback_rate(1.0)
            target.engine.seek_ms(0)
            self.status.setText("PHASE LOCK LOST - TIMED MIX")
            self._transition_duration = float(self.fade_seconds.value())
            self._beat_mix_start_timer.start(50)
            return

        source_position, _source_duration = source.engine.current_times()
        target_position, _target_duration = target.engine.current_times()
        source_interval = 60_000.0 / source_info.bpm
        target_interval = 60_000.0 / self._transition_target_grid_bpm
        source_fraction = (
            (source_position - source_info.phase_ms) / source_interval
        ) % 1.0
        target_phase = target_info.phase_ms % target_interval
        target_cycle = round((target_position - target_phase) / target_interval)
        aligned_target_position = (
            target_phase + target_cycle * target_interval + source_fraction * target_interval
        )
        while aligned_target_position < 0:
            aligned_target_position += target_interval
        target.engine.seek_ms(round(aligned_target_position))

        delay_ms = delay_to_next_beat_ms(
            source_position,
            source_info.phase_ms,
            source_info.bpm,
            source.engine.playback_rate(),
        )
        self.status.setText(f"PHASE LOCKED - START IN {delay_ms} ms")
        self._beat_mix_start_timer.start(delay_ms)

    def _start_aligned_transition(self) -> None:
        if not self._pending_transition:
            return
        from_side, to_side = self._pending_transition
        target = self.left if to_side == "left" else self.right
        if not self._incoming_deck_ready(to_side):
            self._beat_mix_start_timer.start(50)
            return
        self._beat_phase_settling = False
        target.engine.set_analysis_muted(False)
        self._begin_transition(
            from_side,
            to_side,
            duration=self._transition_duration,
            beat_matched=self._transition_beat_matched,
        )

    def _incoming_deck_ready(self, side: str) -> bool:
        target = self.left if side == "left" else self.right
        return target.engine.is_playing() and target.engine.has_playback_progress()

    def _begin_transition(
        self,
        from_side: str,
        to_side: str,
        duration: float | None = None,
        beat_matched: bool = False,
    ) -> None:
        self._pending_transition = None
        self._transition_active = True
        self._transition_duration = max(
            0.5, duration if duration is not None else float(self.fade_seconds.value())
        )
        self._transition_beat_matched = beat_matched
        self._transition_source_side = from_side
        self._transition_target_side = to_side
        self._transition_last_reported_beat = -1
        if beat_matched:
            source = self.left if from_side == "left" else self.right
            source_info = source.engine.beat_info()
            position_ms, _duration_ms = source.engine.current_times()
            if source_info is not None and source_info.bpm > 0:
                interval_ms = 60_000.0 / source_info.bpm
                grid_number = round((position_ms - source_info.phase_ms) / interval_ms)
                self._transition_source_start_ms = (
                    source_info.phase_ms + grid_number * interval_ms
                )
                self._transition_beat_interval_ms = interval_ms
            else:
                self._transition_source_start_ms = float(position_ms)
                self._transition_beat_interval_ms = 0.0
        else:
            self._transition_total_beats = 0
            self._transition_source_start_ms = 0.0
            self._transition_beat_interval_ms = 0.0
            self._transition_target_grid_bpm = 0.0
            self._transition_target_base_rate = 1.0
        self._transition_from = self.crossfader.value()
        self._transition_to = self._CROSSFADER_MAX if to_side == "right" else 0
        self._transition_started = time.monotonic()
        self._transition_hold_started = None
        self._transition_hold_source_ms = 0
        label = "BEAT MIX" if beat_matched else "AUTOMIX"
        self.status.setText(f"{label} {from_side.upper()} → {to_side.upper()}")
        self._fade_timer.start()

    def _fade_tick(self) -> None:
        if not self._transition_active:
            return
        now = time.monotonic()
        if self._transition_target_side is not None:
            source = self.left if self._transition_source_side == "left" else self.right
            source_position, _duration_ms = source.engine.current_times()
            if not self._incoming_deck_ready(self._transition_target_side):
                if self._transition_hold_started is None:
                    self._transition_hold_started = now
                    self._transition_hold_source_ms = source_position
                self.status.setText("MIX HELD - WAITING FOR INCOMING AUDIO")
                return
            if self._transition_hold_started is not None:
                # Resume at the existing gains; neither elapsed wall time nor
                # outgoing beats during buffering may jump the fade forward.
                self._transition_started += now - self._transition_hold_started
                self._transition_source_start_ms += max(
                    0, source_position - self._transition_hold_source_ms
                )
                self._transition_hold_started = None
                self._transition_last_reported_beat = -1
                label = "BEAT MIX" if self._transition_beat_matched else "AUTOMIX"
                self.status.setText(
                    f"{label} {self._transition_source_side.upper()} → "
                    f"{self._transition_target_side.upper()}"
                )
        duration = self._transition_duration
        wall_progress = min(1.0, (now - self._transition_started) / duration)
        progress = wall_progress
        eased = progress * progress * (3.0 - 2.0 * progress)
        if (
            self._transition_beat_matched
            and self._transition_source_side is not None
            and self._transition_total_beats > 0
            and self._transition_beat_interval_ms > 0
        ):
            source = (
                self.left if self._transition_source_side == "left" else self.right
            )
            position_ms, _duration_ms = source.engine.current_times()
            beat_position = max(
                0.0,
                (position_ms - self._transition_source_start_ms)
                / self._transition_beat_interval_ms,
            )
            if not source.engine.is_playing():
                beat_position = max(
                    beat_position, wall_progress * self._transition_total_beats
                )
            beat_position = min(float(self._transition_total_beats), beat_position)
            completed_beats = min(
                self._transition_total_beats, int(math.floor(beat_position))
            )
            beat_phase = beat_position - completed_beats
            eased_phase = beat_phase * beat_phase * (3.0 - 2.0 * beat_phase)
            eased = min(
                1.0,
                (completed_beats + eased_phase) / self._transition_total_beats,
            )
            progress = beat_position / self._transition_total_beats
            reported_beat = min(self._transition_total_beats, completed_beats + 1)
            if reported_beat != self._transition_last_reported_beat:
                self._transition_last_reported_beat = reported_beat
                phase_error = self._measure_phase_error()
                self.status.setText(
                    f"BEAT MIX {self._transition_source_side.upper()} -> "
                    f"{self._transition_target_side.upper()}\n"
                    f"BEAT {reported_beat}/{self._transition_total_beats} · "
                    f"PHASE {phase_error:+.2f}"
                )
        value = round(self._transition_from + (self._transition_to - self._transition_from) * eased)
        self.crossfader.setValue(value)
        if progress >= 1.0:
            self._fade_timer.stop()
            # setValue() emits nothing when rounding reached the endpoint on an
            # earlier tick, so explicitly enforce full gain on the new deck.
            self._apply_crossfader(self._transition_to)
            self._transition_active = False
            if self._transition_target_side is not None:
                target = self.left if self._transition_target_side == "left" else self.right
                target.engine.set_playback_rate(1.0)
            if self._transition_beat_matched and self._transition_target_side is not None:
                self.status.setText("BEAT MIX COMPLETE - ORIGINAL TEMPO")
            else:
                self.status.setText("AUTOMIX COMPLETE")

    def _measure_phase_error(self) -> float:
        if (
            self._transition_source_side is None
            or self._transition_target_side is None
            or self._transition_target_grid_bpm <= 0
        ):
            return 0.0
        source = self.left if self._transition_source_side == "left" else self.right
        target = self.left if self._transition_target_side == "left" else self.right
        source_info = source.engine.beat_info()
        target_info = target.engine.beat_info()
        if source_info is None or target_info is None:
            return 0.0
        source_position, _source_duration = source.engine.current_times()
        target_position, _target_duration = target.engine.current_times()
        error = phase_error_cycles(
            source_position,
            source_info.phase_ms,
            source_info.bpm,
            target_position,
            target_info.phase_ms,
            self._transition_target_grid_bpm,
        )
        return error

    def _deck_ended(self, side: str) -> None:
        if self._last_triggered_side == side:
            self._last_triggered_side = None
        if self._pending_transition and self._pending_transition[0] == side:
            self._cancel_transition("SOURCE ENDED DURING PREPARATION")
        deck = self.left if side == "left" else self.right
        if deck.has_tracks():
            self.status.setText(f"{side.upper()} ADVANCED TO NEXT TRACK")
        else:
            self.status.setText(f"{side.upper()} PLAYLIST COMPLETE")

    def _cancel_transition(self, reason: str) -> None:
        self._fade_timer.stop()
        self._beat_launch_timer.stop()
        self._beat_settle_timer.stop()
        self._beat_mix_start_timer.stop()
        analysis_side = self._beat_analysis_target
        pending = self._pending_transition
        if analysis_side is not None:
            analysis_deck = self.left if analysis_side == "left" else self.right
            analysis_deck.engine.pause()
            analysis_deck.engine.seek_ms(0)
            analysis_deck.engine.set_analysis_muted(False)
        elif pending is not None:
            target_side = pending[1]
            target = self.left if target_side == "left" else self.right
            target.engine.set_analysis_muted(False)
            if self._transition_beat_matched:
                target.engine.pause()
                target.engine.seek_ms(0)
                target.engine.set_playback_rate(1.0)
        self._beat_analysis_target = None
        self._beat_analysis_started = 0.0
        self._beat_analysis_requested = 0.0
        self._beat_phase_settling = False
        self._transition_active = False
        self._transition_hold_started = None
        self._transition_hold_source_ms = 0
        self._transition_beat_matched = False
        self._transition_source_side = None
        self._transition_target_side = None
        self._transition_total_beats = 0
        self._transition_target_grid_bpm = 0.0
        self._transition_target_base_rate = 1.0
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
            "play_on_double_click": {
                "left": self.left.play_on_double_click.isChecked(),
                "right": self.right.play_on_double_click.isChecked(),
            },
            # Keep the persisted value in the original 0-100 format.
            "crossfader": round(self.crossfader.value() / self._CROSSFADER_MAX * 100),
            "auto_mix": self.auto_mix.isChecked(),
            "beat_match": self.beat_match.isChecked(),
            "fade_bars": self.fade_bars.value(),
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
            double_click = data.get("play_on_double_click", {})
            if not isinstance(double_click, dict):
                double_click = {}
            # Restore both settings without writing a partially restored session.
            with QSignalBlocker(self.left.play_on_double_click), QSignalBlocker(self.right.play_on_double_click):
                self.left.play_on_double_click.setChecked(double_click.get("left") is True)
                self.right.play_on_double_click.setChecked(double_click.get("right") is True)
            self.left.set_tracks([Track.from_dict(item) for item in data.get("left", [])])
            self.right.set_tracks([Track.from_dict(item) for item in data.get("right", [])])
            saved_crossfader = max(0, min(100, int(data.get("crossfader", 50))))
            self.crossfader.setValue(round(saved_crossfader / 100 * self._CROSSFADER_MAX))
            self.auto_mix.setChecked(bool(data.get("auto_mix", True)))
            self.beat_match.setChecked(bool(data.get("beat_match", True)))
            self.fade_bars.setValue(int(data.get("fade_bars", 4)))
            self.fade_seconds.setValue(int(data.get("fade_seconds", 8)))
        except (TypeError, ValueError) as exc:
            QMessageBox.warning(self, "Playlist restore", f"The saved playlist file could not be restored: {exc}")

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._karaoke_window is not None:
            projector = self._karaoke_window.projector
            if projector.isVisible() and not projector.close():
                event.ignore()
                return
            self._karaoke_window.engine.stop()
            self._karaoke_window.close()
        self.song_suggestions.shutdown()
        self._karaoke_blink_timer.stop()
        if self._logo_pulse is not None:
            self._logo_pulse.stop()
        self._save_playlists()
        self.left.engine.stop()
        self.right.engine.stop()
        super().closeEvent(event)
