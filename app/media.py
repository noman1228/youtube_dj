from __future__ import annotations

import math
import tempfile
import threading
import time
import traceback
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from PySide6.QtCore import QObject, QRunnable, QThread, QThreadPool, QTimer, QUrl, Signal, Slot
from PySide6.QtMultimedia import (
    QAudioBuffer,
    QAudioBufferOutput,
    QAudioFormat,
    QAudioOutput,
    QMediaMetaData,
    QMediaPlayer,
    QVideoSink,
)

from .beat import BeatInfo, BeatTracker
from .hls import HlsPlaylistServer, HlsVideoSource, select_hls_video
from .models import Track
from .media_cache import prepare_media


@dataclass
class PreparedMedia:
    # Keep the directory alive for as long as any deck uses this source.
    directory: tempfile.TemporaryDirectory
    path: Path
    duration: int
    description: str
    height: int = 0
    size: int = 0


_prepared_cache: OrderedDict[tuple[str, bool, int | None], PreparedMedia] = OrderedDict()
_cache_lock = threading.Lock()
_prepare_pool: QThreadPool | None = None


def _media_pool() -> QThreadPool:
    global _prepare_pool
    if _prepare_pool is None:
        # Queue speculative work behind requested loads; avoid three extractors
        # and downloaders competing with the audio/video decoders at once.
        _prepare_pool = QThreadPool()
        _prepare_pool.setMaxThreadCount(1)
        _prepare_pool.setThreadPriority(QThread.Priority.LowPriority)
    return _prepare_pool


class ResolveSignals(QObject):
    resolved = Signal(int, object, object, int, str)
    failed = Signal(int, str)
    preparing = Signal(int)


class ResolveTask(QRunnable):
    def __init__(self, generation: int, track: Track, video: bool = False, max_height: int | None = None) -> None:
        super().__init__()
        self.generation = generation
        self.track = track
        self.video = video
        self.max_height = max_height
        self.signals = ResolveSignals()
        self.cancelled = threading.Event()

    def _check_cancelled(self, _progress: object = None) -> None:
        if self.cancelled.is_set():
            raise RuntimeError("Track preparation cancelled.")

    @Slot()
    def run(self) -> None:
        try:
            self._check_cancelled()
            if self.track.source == "Local file" or self.track.webpage_url.startswith("file:"):
                self._emit_resolved(
                    self.generation,
                    self.track,
                    self.track.webpage_url,
                    int(self.track.duration_seconds or 0),
                    "LOCAL FILE",
                )
                return

            key = (self.track.webpage_url, self.video, self.max_height)
            with _cache_lock:
                cached = _prepared_cache.get(key)
                if cached and cached.path.is_file():
                    _prepared_cache.move_to_end(key)
                else:
                    cached = None
            if cached:
                self._emit_resolved(self.generation, self.track, cached, cached.duration, cached.description)
                return

            import yt_dlp
            from yt_dlp.networking import Request

            options: Any = {
                "quiet": True,
                "no_warnings": False,
                "skip_download": True,
                "noplaylist": True,
                "format": (
                    (lambda context: _video_format_selector(context, self.max_height)) if self.video else "bestaudio/best"
                ),
                "socket_timeout": 20,
                "retries": 3,
                "fragment_retries": 3,
                "extractor_retries": 2,
                "skip_unavailable_fragments": False,
                "concurrent_fragment_downloads": 1,
                "progress_hooks": [self._check_cancelled],
                # yt-dlp enables only Deno by default; support the Node.js
                # installation documented for this app as well.
                "js_runtimes": {"deno": {}, "node": {}},
            }
            directory = tempfile.TemporaryDirectory(prefix="encoremix-", ignore_cleanup_errors=True)
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(self.track.webpage_url, download=False)
                self._check_cancelled()
                if not info:
                    raise RuntimeError("No playable stream information was returned.")
                if info.get("is_live") or info.get("live_status") in {"is_live", "is_upcoming", "post_live"}:
                    raise RuntimeError("Live streams cannot be fully prepared for uninterrupted playback.")
                hls_source = None
                if info and info.get("format_id") == "hls-master":
                    with ydl.urlopen(Request(info["url"], headers=info.get("http_headers") or {})) as response:
                        manifest = response.read(1_048_577)
                    if len(manifest) > 1_048_576:
                        raise RuntimeError("The HLS playlist is too large to open safely.")
                    hls_source = select_hls_video(manifest.decode("utf-8-sig"), info["url"], self.max_height)
                self.signals.preparing.emit(self.generation)
                path = prepare_media(ydl, info, hls_source, Path(directory.name), self.cancelled)
                self._check_cancelled()
            stream_url = info.get("url") or _best_stream_url(
                info.get("formats") or [], require_video=self.video
            )
            if not stream_url:
                raise RuntimeError("No playable audio stream was found.")
            duration = int(info.get("duration") or self.track.duration_seconds or 0)
            stream_info = (
                f"{hls_source.height}P VIDEO + AUDIO" if hls_source
                else _stream_description(dict(info), stream_url)
            )
            prepared = PreparedMedia(
                directory, path, duration, stream_info,
                hls_source.height if hls_source else int(info.get("height") or 0),
                sum(item.stat().st_size for item in Path(directory.name).rglob("*") if item.is_file()),
            )
            with _cache_lock:
                _prepared_cache[key] = prepared
                _prepared_cache.move_to_end(key)
                # Eviction drops cache ownership only; active and next-up decks
                # pin their assets independently until they change sources.
                while len(_prepared_cache) > 6 or (
                    len(_prepared_cache) > 1
                    and sum(asset.size for asset in _prepared_cache.values()) > 2 * 1024**3
                ):
                    _prepared_cache.popitem(last=False)
            self._emit_resolved(self.generation, self.track, prepared, duration, stream_info)
        except Exception as exc:  # pragma: no cover - network/tooling dependent
            if self.cancelled.is_set():
                return
            details = "".join(traceback.format_exception_only(type(exc), exc)).strip()
            try:
                self.signals.failed.emit(self.generation, details)
            except RuntimeError:
                pass  # The owning window was closed while resolution was in flight.

    def _emit_resolved(self, *args: object) -> None:
        if self.cancelled.is_set():
            return
        try:
            self.signals.resolved.emit(*args)
        except RuntimeError:
            pass  # The owning window was closed while resolution was in flight.


def _video_format_selector(context: dict[str, Any], max_height: int | None = None) -> Iterator[dict[str, Any]]:
    # Rank playable combined streams and shared HLS masters together so a
    # low-resolution combined stream cannot hide a higher-quality HLS video.
    formats = [
        fmt for fmt in context.get("formats") or []
        if fmt.get("url") and not fmt.get("has_drm")
    ]
    combined = [
        fmt for fmt in formats
        if fmt.get("vcodec") not in {None, "none"}
        and fmt.get("acodec") not in {None, "none"}
    ]
    # YouTube may expose only separate audio/video renditions. Their shared
    # HLS master links both; a video-only child URL would produce silent video.
    # Resolution will narrow that master to one HD rendition before opening it.
    hls_formats = [
        fmt for fmt in formats
        if fmt.get("protocol") in {"m3u8", "m3u8_native"}
        and fmt.get("manifest_url")
    ]
    audio_masters = {
        fmt["manifest_url"] for fmt in hls_formats
        if fmt.get("vcodec") == "none" and fmt.get("acodec") != "none"
    }
    candidates = combined + [
        fmt for fmt in hls_formats
        if fmt.get("vcodec") not in {None, "none"}
        and fmt["manifest_url"] in audio_masters
    ]
    candidates.sort(key=lambda fmt: (
        fmt.get("height") or 0, fmt.get("fps") or 0, fmt.get("tbr") or 0,
    ), reverse=True)
    if max_height is not None and candidates:
        preferred = [fmt for fmt in candidates if 0 < (fmt.get("height") or 0) <= max_height]
        if not preferred:
            lowest = min(fmt.get("height") or 0 for fmt in candidates)
            preferred = [fmt for fmt in candidates if (fmt.get("height") or 0) == lowest]
        candidates = preferred
    for fmt in candidates:
        if fmt in combined:
            yield fmt
            return
        if (
            fmt.get("vcodec") not in {None, "none"}
            and fmt["manifest_url"] in audio_masters
        ):
            yield {
                "format_id": "hls-master",
                "url": fmt["manifest_url"],
                "ext": "mp4",
                "protocol": "m3u8",
                "acodec": "unknown",
                "vcodec": "unknown",
                "http_headers": fmt.get("http_headers") or {},
            }
            return


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
    if info.get("format_id") == "hls-master":
        return "HLS VIDEO + AUDIO"
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
        if key in (
            QMediaMetaData.Key.AudioCodec,
            QMediaMetaData.Key.VideoCodec,
            QMediaMetaData.Key.FileFormat,
        ):
            # Convert display-only enums inside Qt; value() can raise when
            # PySide has not registered their Python converters.
            return metadata.stringValue(key) or None
        return metadata.value(key)
    except (RuntimeError, TypeError, ValueError):
        return None


def _audio_buffer_level(buffer: QAudioBuffer, *, scale: float = 2.4) -> float | None:
    """Return scaled RMS without retaining the decoder's buffer."""
    if not buffer.isValid() or buffer.sampleCount() <= 0:
        return None
    raw = memoryview(buffer.constData())
    sample_format = buffer.format().sampleFormat()
    try:
        if sample_format == QAudioFormat.SampleFormat.UInt8:
            values = raw.cast("B")
            normalize = lambda value: (float(value) - 128.0) / 128.0
        elif sample_format == QAudioFormat.SampleFormat.Int16:
            values = raw.cast("h")
            normalize = lambda value: float(value) / 32768.0
        elif sample_format == QAudioFormat.SampleFormat.Int32:
            values = raw.cast("i")
            normalize = lambda value: float(value) / 2147483648.0
        elif sample_format == QAudioFormat.SampleFormat.Float:
            values = raw.cast("f")
            normalize = float
        else:
            return None
    except (TypeError, ValueError):
        return None
    # Level metering does not need every decoded sample.  Keep this callback
    # cheap because Qt delivers it on the GUI thread for both decks.
    # Sample complete frames so the stride cannot skip one stereo channel.
    channels = max(1, buffer.format().channelCount())
    frames = len(values) // channels
    frame_budget = max(1, 512 // channels)
    step = max(1, (frames + frame_budget - 1) // frame_budget)
    square_sum = 0.0
    sample_count = 0
    for frame in range(0, frames, step):
        for channel in range(channels):
            value = normalize(values[frame * channels + channel])
            if math.isfinite(value):
                square_sum += value * value
            sample_count += 1
    if not sample_count:
        return None
    return max(0.0, min(1.0, math.sqrt(square_sum / sample_count) * scale))


def _effective_duration_ms(player_duration_ms: int, resolved_duration_ms: int) -> int:
    """Prefer full metadata over a transient streaming-segment duration."""
    player_duration_ms = max(0, int(player_duration_ms))
    resolved_duration_ms = max(0, int(resolved_duration_ms))
    if not resolved_duration_ms:
        return player_duration_ms
    # yt-dlp describes the complete VOD. Qt may initially expose only one
    # transport segment, or occasionally a manifest window. Accept only its
    # small sub-second precision improvement when the two values agree.
    if abs(player_duration_ms - resolved_duration_ms) <= 2_000:
        return max(player_duration_ms, resolved_duration_ms)
    return resolved_duration_ms


class QtMediaDeckEngine(QObject):
    _MAX_STREAM_RETRIES = 3
    _AUDIO_ANALYSIS_INTERVAL_MS = 50
    _STREAM_STALL_TIMEOUT_MS = 20_000
    _END_TOLERANCE_MS = 2_000

    positionChanged = Signal(int, int)
    stateChanged = Signal(str)
    loaded = Signal(object)
    playbackStarted = Signal()
    ended = Signal()
    error = Signal(str)
    waveformSample = Signal(int, float)
    audioLevelChanged = Signal(float)

    def __init__(
        self,
        parent: QObject | None = None,
        video: bool = False,
        capture_waveform: bool = False,
    ) -> None:
        super().__init__(parent)
        self._pool = _media_pool()
        self._resolve_tasks: dict[int, ResolveTask] = {}
        self._prefetch_task: ResolveTask | None = None
        self._prefetch_generation = 0
        self._prefetched_media: PreparedMedia | None = None
        self._prefetch_url = ""
        self._prepared_media: PreparedMedia | None = None
        self._source_is_local = False
        self._playback_confirmed = False
        self._last_progress_at = 0.0
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
        self._analysis_muted = False
        self._resolved_duration_ms = 0
        self._last_position_ms = 0
        self._playlist_server: HlsPlaylistServer | None = None
        self._video_height = 0
        self._video_max_height: int | None = None
        self._hls_source: HlsVideoSource | None = None
        self._last_audio_analysis_ms = -self._AUDIO_ANALYSIS_INTERVAL_MS
        self._beat_tracker = BeatTracker()

        self._player = QMediaPlayer(self)
        self._audio_output = QAudioOutput(self)
        self._player.setAudioOutput(self._audio_output)
        self._audio_buffer_output: QAudioBufferOutput | None = None
        if capture_waveform:
            self._audio_buffer_output = QAudioBufferOutput(self)
            self._audio_buffer_output.audioBufferReceived.connect(self._audio_buffer_received)
            self._player.setAudioBufferOutput(self._audio_buffer_output)
            # Pitch compensation arrived in Qt 6.10; requirements still allow
            # Qt 6.8/6.9, where beat matching must remain startup-safe.
            try:
                availability = self._player.pitchCompensationAvailability()
                unavailable = QMediaPlayer.PitchCompensationAvailability.Unavailable
                if availability != unavailable:
                    self._player.setPitchCompensation(True)
            except (AttributeError, RuntimeError):
                pass
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
        self._stall_timer = QTimer(self)
        self._stall_timer.setSingleShot(True)
        self._stall_timer.setInterval(self._STREAM_STALL_TIMEOUT_MS)
        self._stall_timer.timeout.connect(self._stream_timed_out)
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
        # Let next-up preparation finish and populate the shared cache. The
        # requested load is queued ahead of other speculative work.
        prefetch = self._prefetch_task
        self._prefetch_task = None
        self.stop()
        if prefetch and prefetch.track.webpage_url == track.webpage_url:
            # This work now belongs to the requested load. Updating the next
            # queue item must not cancel a nearly completed incoming track.
            self._resolve_tasks[prefetch.generation] = prefetch
        else:
            self._prefetch_task = prefetch
        self._video_max_height = None
        self._video_height = 0
        self._hls_source = None
        self._player.setPlaybackRate(1.0)
        self._beat_tracker.reset()
        self._retry_attempt = 0
        self._retry_pending = False
        self._retry_position_ms = 0
        self._failure_reported = False
        self._resolved_duration_ms = max(0, int(track.duration_seconds or 0) * 1000)
        self._last_position_ms = 0
        self._last_audio_analysis_ms = -self._AUDIO_ANALYSIS_INTERVAL_MS
        self._play_requested = autoplay
        self._user_stopped = False
        self._source_is_local = False
        self._begin_resolve(track, autoplay)

    def is_preparing(self) -> bool:
        return self._resolving or self._retry_pending

    def has_playback_progress(self) -> bool:
        return (
            self._playback_confirmed and self.is_playing()
            and time.monotonic() - self._last_progress_at < 1.5
        )

    def prefetch(self, track: Track | None) -> None:
        if track and self._prefetch_url == track.webpage_url and (
            self._prefetch_task or self._prefetched_media
        ):
            return
        if self._prefetch_task:
            self._prefetch_task.cancelled.set()
            self._prefetch_task = None
        self._prefetched_media = None
        self._prefetch_url = ""
        if not track or track.source == "Local file" or track.webpage_url.startswith("file:"):
            return
        if self._track and self._track.webpage_url == track.webpage_url:
            return
        self._prefetch_generation -= 1
        self._prefetch_url = track.webpage_url
        task = ResolveTask(self._prefetch_generation, track, video=self._video)
        self._prefetch_task = task
        task.signals.resolved.connect(self._prefetched)
        task.signals.failed.connect(self._prefetch_failed)
        self._pool.start(task, -1)

    @Slot(int, object, object, int, str)
    def _prefetched(self, generation: int, _track: Track, source: object, _duration: int, _info: str) -> None:
        self._resolve_tasks.pop(generation, None)
        if self._prefetch_task and generation == self._prefetch_task.generation:
            self._prefetched_media = source if isinstance(source, PreparedMedia) else None
            self._prefetch_task = None

    @Slot(int, str)
    def _prefetch_failed(self, generation: int, _message: str) -> None:
        self._resolve_tasks.pop(generation, None)
        if self._prefetch_task and generation == self._prefetch_task.generation:
            # Speculative preparation must never stop the current song or
            # display a modal error. An explicit load can retry later.
            self._prefetch_task = None

    def _begin_resolve(self, track: Track, autoplay: bool) -> None:
        self._stall_timer.stop()
        self._generation += 1
        self._track = track
        self._ready = False
        self._resolving = True
        self._autoplay_after_resolve = autoplay
        self._stream_info = "VIDEO STREAM" if self._video else "AUDIO STREAM"
        self.stateChanged.emit("PREPARING")
        task = ResolveTask(self._generation, track, video=self._video, max_height=self._video_max_height)
        self._resolve_tasks[self._generation] = task
        task.signals.resolved.connect(self._resolved)
        task.signals.failed.connect(self._resolve_failed)
        task.signals.preparing.connect(self._preparing)
        self._pool.start(task, 1)

    @Slot(int)
    def _preparing(self, generation: int) -> None:
        if generation == self._generation and self._resolving:
            self.stateChanged.emit("PREPARING FULL TRACK")

    @Slot(int, object, object, int, str)
    def _resolved(
        self, generation: int, track: Track, stream_url: str | HlsVideoSource | PreparedMedia,
        duration: int, stream_info: str
    ) -> None:
        self._resolve_tasks.pop(generation, None)
        if generation != self._generation:
            return
        if duration:
            track.duration_seconds = duration
            self._resolved_duration_ms = duration * 1000
        self._stream_info = stream_info
        self._resolving = False
        self._ready = True
        self._retry_pending = False
        self._video_height = 0
        previous_media = self._prepared_media
        self._prepared_media = stream_url if isinstance(stream_url, PreparedMedia) else None
        if isinstance(stream_url, PreparedMedia):
            self._video_height = stream_url.height
            stream_url = stream_url.path.as_uri()
        self._hls_source = stream_url if isinstance(stream_url, HlsVideoSource) else None
        if isinstance(stream_url, HlsVideoSource):
            self._video_height = stream_url.height
            if self._playlist_server is None:
                self._playlist_server = HlsPlaylistServer()
                self.destroyed.connect(self._playlist_server.close)
            stream_url = self._playlist_server.publish(stream_url)
        self._source_is_local = QUrl(stream_url).isLocalFile()
        self._player.setSource(QUrl(stream_url))
        # Release the previous asset only after the backend has changed source.
        del previous_media
        # Some backends report failure synchronously from setSource(). Do not
        # overwrite a reconnect/error state with LOADED or start another play.
        if self._retry_pending or self._failure_reported:
            return
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
        if any(reason in message.lower() for reason in (
            "requested format is not available",
            "no video formats found",
            "no playable audio stream was found",
            "no compatible hls video/audio rendition was found",
            "live streams cannot",
            "incomplete",
            "not supported",
        )):
            self._report_failure(f"Could not load this track. {message}", "LOAD ERROR")
            return
        self._schedule_stream_retry(f"Could not resolve a fresh stream: {message}")

    def play(self) -> None:
        self._play_requested = True
        self._user_stopped = False
        if self._failure_reported:
            self._failure_reported = False
            self._retry_attempt = 0
            self._retry_position_ms = 0
            self._last_position_ms = 0
        if self._resolving:
            self._autoplay_after_resolve = True
            return
        if self._retry_pending:
            return
        if not self._ready:
            if self._track:
                self._begin_resolve(self._track, autoplay=True)
            return
        self._arm_stall_timer()
        self._player.play()

    def pause(self) -> None:
        self._play_requested = False
        self._autoplay_after_resolve = False
        self._stall_timer.stop()
        self._playback_confirmed = False
        self._player.pause()

    def stop(self) -> None:
        self._play_requested = False
        self._autoplay_after_resolve = False
        self._user_stopped = True
        self._retry_pending = False
        self._retry_timer.stop()
        self._stall_timer.stop()
        self._retry_position_ms = 0
        self._last_position_ms = 0
        self._playback_confirmed = False
        self._last_progress_at = 0.0
        for task in self._resolve_tasks.values():
            task.cancelled.set()
        self._resolve_tasks.clear()
        if self._prefetch_task:
            self._prefetch_task.cancelled.set()
            self._prefetch_task = None
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
            _position, duration = self.current_times()
            if duration > 0:
                self.seek_ms(round(duration * fraction))

    def set_gain(self, gain: int) -> None:
        self._gain = max(0, min(100, gain))
        self._apply_volume()

    def set_crossfade_factor(self, factor: float) -> None:
        self._crossfade_factor = max(0.0, min(1.0, factor))
        self._apply_volume()

    def set_analysis_muted(self, muted: bool) -> None:
        self._analysis_muted = muted
        self._apply_volume()

    def set_playback_rate(self, rate: float) -> None:
        rate = max(0.5, min(2.0, rate))
        if abs(self._player.playbackRate() - rate) > 0.0001:
            self._player.setPlaybackRate(rate)

    def playback_rate(self) -> float:
        return self._player.playbackRate()

    def beat_info(self) -> BeatInfo | None:
        return self._beat_tracker.info()

    def output_volume(self) -> float:
        """Effective deck gain, including crossfade and silent analysis."""
        return self._audio_output.volume()

    def seek_ms(self, position_ms: int) -> None:
        if self._ready:
            _position, duration = self.current_times()
            target = max(0, int(position_ms))
            if duration > 0:
                target = min(target, duration)
            self._last_position_ms = target
            self._playback_confirmed = False
            self._last_progress_at = 0.0
            self._arm_stall_timer()
            self._player.setPosition(target)

    def _apply_volume(self) -> None:
        # QAudioOutput accepts continuous volume, avoiding integer steps.
        volume = self._gain / 100.0 * self._crossfade_factor
        if self._analysis_muted:
            volume = 0.0
        self._audio_output.setVolume(max(0.0, min(1.0, volume)))

    def current_times(self) -> tuple[int, int]:
        duration = _effective_duration_ms(
            self._player.duration(), self._resolved_duration_ms
        )
        return max(0, self._player.position()), duration

    def has_reliable_duration(self) -> bool:
        if self._resolved_duration_ms > 0:
            return True
        track = self._track
        is_local = self._source_is_local or bool(
            track
            and (track.source == "Local file" or track.webpage_url.startswith("file:"))
        )
        return is_local and self._player.duration() > 0

    @Slot(int)
    def _position_changed(self, position: int) -> None:
        if (
            position > 0
            and not self._resolving
            and not self._retry_pending
            and not self._user_stopped
            and not self._failure_reported
        ):
            if position != self._last_position_ms:
                self._confirm_playback_progress()
                self._arm_stall_timer()
            # Keep the last useful position if Qt resets to zero before it
            # reports EndOfMedia or an error on a truncated remote stream.
            self._last_position_ms = position
        self.positionChanged.emit(*self.current_times())

    def _confirm_playback_progress(self) -> None:
        if not self._play_requested or self._user_stopped or self._resolving or self._retry_pending:
            return
        if not self.is_playing():
            return
        self._last_progress_at = time.monotonic()
        if not self._playback_confirmed:
            self._playback_confirmed = True
            self.playbackStarted.emit()

    @Slot(int)
    def _duration_changed(self, _duration: int) -> None:
        self.positionChanged.emit(*self.current_times())

    @Slot(QAudioBuffer)
    def _audio_buffer_received(self, buffer: QAudioBuffer) -> None:
        if buffer.isValid() and buffer.sampleCount() > 0:
            self._confirm_playback_progress()
        start_time = buffer.startTime()
        time_ms = round(start_time / 1000) if start_time >= 0 else self._player.position()
        if (
            time_ms >= self._last_audio_analysis_ms
            and time_ms - self._last_audio_analysis_ms < self._AUDIO_ANALYSIS_INTERVAL_MS
        ):
            return
        self._last_audio_analysis_ms = time_ms
        rms = _audio_buffer_level(buffer, scale=1.0)
        if rms is None:
            self.audioLevelChanged.emit(0.0)
            return
        # This player's source level is independent of gain and crossfader.
        self.audioLevelChanged.emit(rms)
        level = min(1.0, rms * 2.4)
        self._beat_tracker.add_level(time_ms, level)
        self.waveformSample.emit(time_ms, level)

    @Slot(QMediaPlayer.PlaybackState)
    def _playback_state_changed(self, state: QMediaPlayer.PlaybackState) -> None:
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self._apply_volume()
            self._showing_stream_info = False
            self.stateChanged.emit("PLAYING")
            self._status_timer.start()
        elif state == QMediaPlayer.PlaybackState.PausedState:
            self._playback_confirmed = False
            self._status_timer.stop()
            self.stateChanged.emit("PAUSED")
        elif self._track:
            self._playback_confirmed = False
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
            if self._video and not self._video_height:
                resolution = _safe_metadata_value(metadata, QMediaMetaData.Key.Resolution)
                if resolution is not None and hasattr(resolution, "height"):
                    self._video_height = resolution.height()
            bitrate = _safe_metadata_value(metadata, QMediaMetaData.Key.AudioBitRate)
            codec = _safe_metadata_value(metadata, QMediaMetaData.Key.AudioCodec)
            container = _safe_metadata_value(metadata, QMediaMetaData.Key.FileFormat)
            parts: list[str] = []
            if self._video_height:
                parts.append(f"{self._video_height}P")
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
            if (
                self._retry_pending
                or self._resolving
                or self._user_stopped
                or self._failure_reported
            ):
                return
            position = max(self._player.position(), self._last_position_ms)
            if (
                (self._is_remote_track() or self._prepared_media is not None)
                and self._resolved_duration_ms > 0
                and position + self._END_TOLERANCE_MS < self._resolved_duration_ms
            ):
                self._schedule_stream_retry(
                    f"The stream ended at {position / 1000:.1f}s of "
                    f"{self._resolved_duration_ms / 1000:.1f}s."
                )
                return
            self._stall_timer.stop()
            self._play_requested = False
            self._user_stopped = True
            self.ended.emit()

    def _is_remote_track(self) -> bool:
        return bool(
            self._track
            and not self._source_is_local
            and self._track.source != "Local file"
            and not self._track.webpage_url.startswith("file:")
        )

    def _arm_stall_timer(self) -> None:
        if (
            self._is_remote_track()
            and self._ready
            and self._play_requested
            and not self._user_stopped
            and not self._retry_pending
            and not self._resolving
            and not self._failure_reported
        ):
            self._stall_timer.start(self._STREAM_STALL_TIMEOUT_MS)

    @Slot()
    def _stream_timed_out(self) -> None:
        if self._play_requested and self._ready and self._is_remote_track():
            position = self._player.position()
            if position > self._last_position_ms or self.has_playback_progress():
                self._last_position_ms = max(position, self._last_position_ms)
                self._arm_stall_timer()
                return
            self._schedule_stream_retry(
                "The stream made no playback progress for "
                f"{self._stall_timer.interval() // 1000} seconds."
            )

    @Slot(QMediaPlayer.Error, str)
    def _player_error(self, error: QMediaPlayer.Error, message: str) -> None:
        if error == QMediaPlayer.Error.NoError:
            return
        self._schedule_stream_retry(message or error.name)

    def _schedule_stream_retry(self, reason: str) -> None:
        if (
            self._user_stopped
            or self._retry_pending
            or self._resolving
            or self._failure_reported
        ):
            return
        self._ready = False
        self._stall_timer.stop()
        track = self._track
        is_local = self._source_is_local or bool(
            track
            and (track.source == "Local file" or track.webpage_url.startswith("file:"))
        )
        if is_local:
            self._report_failure(f"The prepared or local media could not continue playing. {reason}")
            return
        if not track or self._retry_attempt >= self._MAX_STREAM_RETRIES:
            self._report_failure(
                "Playback stopped safely after the stream connection failed. "
                f"{reason}"
            )
            return

        self._retry_attempt += 1
        if self._video and self._video_height > 0:
            self._video_max_height = max(1, self._video_height - 1)
        self._retry_pending = True
        self._retry_position_ms = max(
            self._retry_position_ms, self._player.position(), self._last_position_ms
        )
        self._status_timer.stop()
        self._player.stop()
        self._player.setSource(QUrl())
        self.stateChanged.emit(
            f"RECONNECTING {self._retry_attempt}/{self._MAX_STREAM_RETRIES}"
        )
        # A short exponential delay prevents Qt/FFmpeg from hammering a socket
        # that Windows has just reset while keeping recovery quick for the DJ.
        self._retry_timer.start(500 * (2 ** (self._retry_attempt - 1)))

    def _report_failure(self, message: str, state: str = "PLAYBACK ERROR") -> None:
        if self._user_stopped or self._failure_reported:
            return
        self._failure_reported = True
        self._ready = False
        self._retry_pending = False
        self._play_requested = False
        self._autoplay_after_resolve = False
        self._retry_timer.stop()
        self._stall_timer.stop()
        self._status_timer.stop()
        self._player.stop()
        self.stateChanged.emit(state)
        self.error.emit(message)

    @Slot()
    def _retry_stream(self) -> None:
        if not self._retry_pending or not self._track:
            return
        if self._video_max_height is not None and self._hls_source and self._hls_source.master_playlist:
            source = select_hls_video(
                self._hls_source.master_playlist.decode("utf-8"),
                self._hls_source.url, self._video_max_height,
            )
            if source.height < self._video_height:
                # Reuse the already resolved master for a quick quality change.
                self._autoplay_after_resolve = self._play_requested
                self._resolved(self._generation, self._track, source,
                               self._resolved_duration_ms // 1000, f"{source.height}P VIDEO + AUDIO")
                return
        self._begin_resolve(self._track, autoplay=self._play_requested)

    @Slot(QMediaPlayer.MediaStatus)
    def _resume_after_reconnect(self, status: QMediaPlayer.MediaStatus) -> None:
        if (
            self._retry_pending
            or self._resolving
            or not self._ready
            or self._user_stopped
            or self._failure_reported
        ):
            return
        if status not in {
            QMediaPlayer.MediaStatus.LoadedMedia,
            QMediaPlayer.MediaStatus.BufferedMedia,
        }:
            return
        if self._retry_position_ms > 0:
            position = self._retry_position_ms
            self._retry_position_ms = 0
            self._player.setPosition(position)
