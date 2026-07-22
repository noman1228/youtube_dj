from __future__ import annotations

import traceback
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, QUrl, Signal, Slot
from PySide6.QtMultimedia import QAudioOutput, QMediaMetaData, QMediaPlayer, QVideoSink

from .models import Track


class ResolveSignals(QObject):
    resolved = Signal(int, object, str, int, str)
    failed = Signal(int, str)


class ResolveTask(QRunnable):
    def __init__(self, generation: int, track: Track, video: bool = False) -> None:
        super().__init__()
        self.generation = generation
        self.track = track
        self.video = video
        self.signals = ResolveSignals()

    @Slot()
    def run(self) -> None:
        try:
            if self.track.source == "Local file" or self.track.webpage_url.startswith("file:"):
                self._emit_resolved(
                    self.generation,
                    self.track,
                    self.track.webpage_url,
                    int(self.track.duration_seconds or 0),
                    "LOCAL FILE",
                )
                return

            import yt_dlp

            options: Any = {
                "quiet": True,
                "no_warnings": True,
                "skip_download": True,
                "noplaylist": True,
                "format": (
                    "best[height<=720][vcodec!=none][acodec!=none]/"
                    "best[vcodec!=none][acodec!=none]/best"
                    if self.video
                    else "bestaudio/best"
                ),
                "socket_timeout": 20,
            }
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(self.track.webpage_url, download=False)
            if not info:
                raise RuntimeError("No playable stream information was returned.")
            stream_url = info.get("url") or _best_stream_url(
                info.get("formats") or [], require_video=self.video
            )
            if not stream_url:
                raise RuntimeError("No playable audio stream was found.")
            duration = int(info.get("duration") or self.track.duration_seconds or 0)
            stream_info = _stream_description(dict(info), stream_url)
            self._emit_resolved(self.generation, self.track, stream_url, duration, stream_info)
        except Exception as exc:  # pragma: no cover - network/tooling dependent
            details = "".join(traceback.format_exception_only(type(exc), exc)).strip()
            try:
                self.signals.failed.emit(self.generation, details)
            except RuntimeError:
                pass  # The owning window was closed while resolution was in flight.

    def _emit_resolved(self, *args: object) -> None:
        try:
            self.signals.resolved.emit(*args)
        except RuntimeError:
            pass  # The owning window was closed while resolution was in flight.


def _best_stream_url(formats: list[dict[str, Any]], require_video: bool = False) -> str:
    if require_video:
        combined = [
            fmt
            for fmt in formats
            if fmt.get("url")
            and fmt.get("acodec") not in {None, "none"}
            and fmt.get("vcodec") not in {None, "none"}
        ]
        combined.sort(
            key=lambda fmt: (fmt.get("height") or 0, fmt.get("tbr") or 0), reverse=True
        )
        if combined:
            return str(combined[0]["url"])
        return ""
    audio_only = [
        fmt for fmt in formats
        if fmt.get("url") and fmt.get("acodec") not in {None, "none"} and fmt.get("vcodec") == "none"
    ]
    candidates = audio_only or [fmt for fmt in formats if fmt.get("url") and fmt.get("acodec") != "none"]
    if not candidates:
        return ""
    candidates.sort(key=lambda fmt: (fmt.get("abr") or 0, fmt.get("tbr") or 0), reverse=True)
    return str(candidates[0]["url"])


def _stream_description(info: dict[str, Any], stream_url: str) -> str:
    selected = info
    for candidate in info.get("formats") or []:
        if candidate.get("url") == stream_url:
            selected = candidate
            break
    bitrate = selected.get("abr") or selected.get("tbr") or info.get("abr") or info.get("tbr")
    codec = selected.get("acodec") or info.get("acodec")
    container = selected.get("ext") or info.get("ext")
    parts: list[str] = []
    try:
        if bitrate and isinstance(bitrate, (int, float, str)):
            parts.append(f"{round(float(bitrate))} KBPS")
    except (TypeError, ValueError):
        pass
    format_parts = [
        str(value).upper()
        for value in (codec, container)
        if value and str(value).lower() not in {"none", "unknown"}
    ]
    if format_parts:
        parts.append("/".join(format_parts))
    return " · ".join(parts) or "AUDIO STREAM"


def _metadata_name(value: object) -> str:
    if value is None:
        return ""
    name = getattr(value, "name", None)
    text = str(name or value)
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    return "" if text.lower() in {"", "unspecified", "unknown"} else text.upper()


def _safe_metadata_value(metadata: QMediaMetaData, key: QMediaMetaData.Key) -> object | None:
    try:
        return metadata.value(key)
    except (RuntimeError, TypeError, ValueError):
        return None


class QtMediaDeckEngine(QObject):
    _MAX_STREAM_RETRIES = 3

    positionChanged = Signal(int, int)
    stateChanged = Signal(str)
    loaded = Signal(object)
    playbackStarted = Signal()
    ended = Signal()
    error = Signal(str)

    def __init__(self, parent: QObject | None = None, video: bool = False) -> None:
        super().__init__(parent)
        self._pool = QThreadPool.globalInstance()
        self._resolve_tasks: dict[int, ResolveTask] = {}
        self._video = video
        self._generation = 0
        self._track: Track | None = None
        self._autoplay_after_resolve = False
        self._ready = False
        self._gain = 100
        self._crossfade_factor = 1.0
        self._stream_info = "VIDEO STREAM" if video else "AUDIO STREAM"
        self._showing_stream_info = False
        self._play_requested = False
        self._retry_attempt = 0
        self._retry_pending = False
        self._retry_position_ms = 0
        self._failure_reported = False
        self._resolving = False
        self._user_stopped = True

        self._player = QMediaPlayer(self)
        self._audio_output = QAudioOutput(self)
        self._player.setAudioOutput(self._audio_output)
        self._player.positionChanged.connect(self._position_changed)
        self._player.durationChanged.connect(self._duration_changed)
        self._player.playbackStateChanged.connect(self._playback_state_changed)
        self._player.mediaStatusChanged.connect(self._media_status_changed)
        self._player.mediaStatusChanged.connect(self._resume_after_reconnect)
        self._player.metaDataChanged.connect(self._metadata_changed)
        self._player.errorOccurred.connect(self._player_error)
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(2500)
        self._status_timer.timeout.connect(self._alternate_playing_status)
        self._retry_timer = QTimer(self)
        self._retry_timer.setSingleShot(True)
        self._retry_timer.timeout.connect(self._retry_stream)
        self._apply_volume()

    @property
    def track(self) -> Track | None:
        return self._track

    @property
    def is_ready(self) -> bool:
        return self._ready

    def is_playing(self) -> bool:
        return self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    def set_video_output(self, output: QObject) -> None:
        self._player.setVideoOutput(output)

    def set_video_sink(self, sink: QVideoSink) -> None:
        self._player.setVideoSink(sink)

    def load(self, track: Track, autoplay: bool = False) -> None:
        self.stop()
        self._retry_attempt = 0
        self._retry_pending = False
        self._retry_position_ms = 0
        self._failure_reported = False
        self._play_requested = autoplay
        self._user_stopped = False
        self._begin_resolve(track, autoplay)

    def _begin_resolve(self, track: Track, autoplay: bool) -> None:
        self._generation += 1
        self._track = track
        self._ready = False
        self._resolving = True
        self._autoplay_after_resolve = autoplay
        self._stream_info = "VIDEO STREAM" if self._video else "AUDIO STREAM"
        self.stateChanged.emit("LOADED")
        task = ResolveTask(self._generation, track, video=self._video)
        self._resolve_tasks[self._generation] = task
        task.signals.resolved.connect(self._resolved)
        task.signals.failed.connect(self._resolve_failed)
        self._pool.start(task)

    @Slot(int, object, str, int, str)
    def _resolved(
        self, generation: int, track: Track, stream_url: str, duration: int, stream_info: str
    ) -> None:
        self._resolve_tasks.pop(generation, None)
        if generation != self._generation:
            return
        if duration and not track.duration_seconds:
            track.duration_seconds = duration
        self._stream_info = stream_info
        self._player.setSource(QUrl(stream_url))
        self._resolving = False
        self._ready = True
        self._retry_pending = False
        self._apply_volume()
        self.stateChanged.emit("LOADED")
        self.loaded.emit(track)
        if self._autoplay_after_resolve:
            self.play()

    @Slot(int, str)
    def _resolve_failed(self, generation: int, message: str) -> None:
        self._resolve_tasks.pop(generation, None)
        if generation != self._generation:
            return
        self._resolving = False
        self._retry_pending = False
        self._ready = False
        self._schedule_stream_retry(f"Could not resolve a fresh stream: {message}")

    def play(self) -> None:
        self._play_requested = True
        self._user_stopped = False
        if not self._ready:
            if self._track:
                self.load(self._track, autoplay=True)
            return
        self._player.play()

    def pause(self) -> None:
        self._play_requested = False
        self._player.pause()

    def stop(self) -> None:
        self._play_requested = False
        self._autoplay_after_resolve = False
        self._user_stopped = True
        self._retry_pending = False
        self._retry_timer.stop()
        if self._resolving:
            # Resolution work cannot be forcibly killed safely, so invalidate
            # its generation and ignore its eventual callback.
            self._generation += 1
            self._resolving = False
        self._player.stop()
        self._status_timer.stop()
        if self._track:
            self.stateChanged.emit("LOADED")

    def toggle_play_pause(self) -> None:
        if self.is_playing():
            self.pause()
        else:
            self.play()

    def seek_fraction(self, fraction: float) -> None:
        if self._ready:
            fraction = max(0.0, min(1.0, fraction))
            self._player.setPosition(round(self._player.duration() * fraction))

    def set_gain(self, gain: int) -> None:
        self._gain = max(0, min(100, gain))
        self._apply_volume()

    def set_crossfade_factor(self, factor: float) -> None:
        self._crossfade_factor = max(0.0, min(1.0, factor))
        self._apply_volume()

    def _apply_volume(self) -> None:
        # QAudioOutput accepts continuous volume, avoiding integer steps.
        volume = self._gain / 100.0 * self._crossfade_factor
        self._audio_output.setVolume(max(0.0, min(1.0, volume)))

    def current_times(self) -> tuple[int, int]:
        return max(0, self._player.position()), max(0, self._player.duration())

    @Slot(int)
    def _position_changed(self, _position: int) -> None:
        self.positionChanged.emit(*self.current_times())

    @Slot(int)
    def _duration_changed(self, _duration: int) -> None:
        self.positionChanged.emit(*self.current_times())

    @Slot(QMediaPlayer.PlaybackState)
    def _playback_state_changed(self, state: QMediaPlayer.PlaybackState) -> None:
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self._apply_volume()
            self._showing_stream_info = False
            self.stateChanged.emit("PLAYING")
            self._status_timer.start()
            self.playbackStarted.emit()
        elif state == QMediaPlayer.PlaybackState.PausedState:
            self._status_timer.stop()
            self.stateChanged.emit("PAUSED")
        elif self._track:
            self._status_timer.stop()
            self.stateChanged.emit("LOADED")

    @Slot()
    def _alternate_playing_status(self) -> None:
        if not self.is_playing():
            self._status_timer.stop()
            return
        self._showing_stream_info = not self._showing_stream_info
        self.stateChanged.emit(self._stream_info if self._showing_stream_info else "PLAYING")

    @Slot()
    def _metadata_changed(self) -> None:
        try:
            metadata = self._player.metaData()
            bitrate = _safe_metadata_value(metadata, QMediaMetaData.Key.AudioBitRate)
            codec = _safe_metadata_value(metadata, QMediaMetaData.Key.AudioCodec)
            container = _safe_metadata_value(metadata, QMediaMetaData.Key.FileFormat)
            parts: list[str] = []
            try:
                if bitrate and isinstance(bitrate, (int, float, str)):
                    parts.append(f"{round(float(bitrate) / 1000)} KBPS")
            except (TypeError, ValueError, RuntimeError):
                pass
            format_parts = [_metadata_name(value) for value in (codec, container)]
            format_parts = [value for value in format_parts if value]
            if format_parts:
                parts.append("/".join(format_parts))
            if parts:
                self._stream_info = " · ".join(parts)
        except Exception:
            # Metadata is display-only. Some PySide/Qt Multimedia builds do
            # not register converters for codec/container enum values; those
            # failures must never interrupt playback or escape a Qt callback.
            return

    @Slot(QMediaPlayer.MediaStatus)
    def _media_status_changed(self, status: QMediaPlayer.MediaStatus) -> None:
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            if self._retry_pending:
                return
            self._play_requested = False
            self._user_stopped = True
            self.ended.emit()

    @Slot(QMediaPlayer.Error, str)
    def _player_error(self, error: QMediaPlayer.Error, message: str) -> None:
        if error == QMediaPlayer.Error.NoError:
            return
        self._ready = False
        self._schedule_stream_retry(message or error.name)

    def _schedule_stream_retry(self, reason: str) -> None:
        if (
            self._user_stopped
            or self._retry_pending
            or self._resolving
            or self._failure_reported
        ):
            return
        track = self._track
        is_local = bool(
            track
            and (track.source == "Local file" or track.webpage_url.startswith("file:"))
        )
        if not track or is_local or self._retry_attempt >= self._MAX_STREAM_RETRIES:
            self._failure_reported = True
            self._retry_pending = False
            self._status_timer.stop()
            self.stateChanged.emit("PLAYBACK ERROR")
            self.error.emit(
                "Playback stopped safely after the stream connection failed. "
                f"{reason}"
            )
            return

        self._retry_attempt += 1
        self._retry_pending = True
        self._retry_position_ms = max(self._retry_position_ms, self._player.position())
        self._status_timer.stop()
        self._player.stop()
        self._player.setSource(QUrl())
        self.stateChanged.emit(
            f"RECONNECTING {self._retry_attempt}/{self._MAX_STREAM_RETRIES}"
        )
        # A short exponential delay prevents Qt/FFmpeg from hammering a socket
        # that Windows has just reset while keeping recovery quick for the DJ.
        self._retry_timer.start(500 * (2 ** (self._retry_attempt - 1)))

    @Slot()
    def _retry_stream(self) -> None:
        if not self._retry_pending or not self._track:
            return
        self._begin_resolve(self._track, autoplay=self._play_requested)

    @Slot(QMediaPlayer.MediaStatus)
    def _resume_after_reconnect(self, status: QMediaPlayer.MediaStatus) -> None:
        if status not in {
            QMediaPlayer.MediaStatus.LoadedMedia,
            QMediaPlayer.MediaStatus.BufferedMedia,
        }:
            return
        if self._retry_position_ms > 0:
            position = self._retry_position_ms
            self._retry_position_ms = 0
            self._player.setPosition(position)
