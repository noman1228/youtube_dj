from __future__ import annotations

import traceback
from typing import Iterable

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from .models import Track


class SearchSignals(QObject):
    result = Signal(int, object)
    finished = Signal(int, str)
    failed = Signal(int, str, str)


class SearchTask(QRunnable):
    def __init__(self, query: str, provider: str, limit: int = 12, request_id: int = 0) -> None:
        super().__init__()
        self.query = query.strip()
        self.provider = provider
        self.limit = limit
        self.request_id = request_id
        self.signals = SearchSignals()

    @Slot()
    def run(self) -> None:
        try:
            if self.provider == "YouTube":
                tracks = self._search_youtube()
            elif self.provider == "YouTube Music":
                tracks = self._search_ytmusic()
            else:
                raise ValueError(f"Unsupported search provider: {self.provider}")
            tracks = self._deduplicate(tracks)[: self.limit]
            for track in tracks:
                self.signals.result.emit(self.request_id, track)
            self.signals.finished.emit(self.request_id, self.provider)
        except Exception as exc:  # pragma: no cover - network/tooling dependent
            details = "".join(traceback.format_exception_only(type(exc), exc)).strip()
            self.signals.failed.emit(self.request_id, self.provider, details)

    def _search_youtube(self) -> list[Track]:
        import yt_dlp

        options = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "noplaylist": True,
            "extract_flat": True,
            "socket_timeout": 15,
        }
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(f"ytsearch{self.limit}:{self.query}", download=False)

        tracks: list[Track] = []
        for entry in (info or {}).get("entries", []):
            if not entry:
                continue
            video_id = str(entry.get("id") or "")
            webpage_url = entry.get("webpage_url") or (
                f"https://www.youtube.com/watch?v={video_id}" if video_id else ""
            )
            if not webpage_url:
                continue
            tracks.append(
                Track(
                    title=entry.get("title") or "Untitled result",
                    webpage_url=webpage_url,
                    source="YouTube",
                    video_id=video_id,
                    description=entry.get("description") or "No description supplied.",
                    thumbnail_url=_thumbnail_url(entry, video_id),
                    uploader=entry.get("channel") or entry.get("uploader") or "",
                    duration_seconds=_safe_int(entry.get("duration")),
                )
            )
        return tracks

    def _search_ytmusic(self) -> list[Track]:
        from ytmusicapi import YTMusic

        client = YTMusic()
        raw_results = client.search(self.query, filter="songs", limit=self.limit)
        tracks: list[Track] = []
        for result in raw_results:
            video_id = result.get("videoId") or ""
            if not video_id:
                continue
            artists = ", ".join(
                artist.get("name", "") for artist in result.get("artists", []) if artist.get("name")
            )
            album = (result.get("album") or {}).get("name", "")
            metadata = " • ".join(part for part in [artists, album, result.get("duration", "")] if part)
            thumbnails = result.get("thumbnails") or []
            thumbnail = thumbnails[-1].get("url", "") if thumbnails else ""
            tracks.append(
                Track(
                    title=result.get("title") or "Untitled result",
                    webpage_url=f"https://www.youtube.com/watch?v={video_id}",
                    source="YouTube Music",
                    video_id=video_id,
                    description=metadata or "YouTube Music search result.",
                    thumbnail_url=thumbnail,
                    uploader=artists,
                    duration_seconds=_safe_int(result.get("duration_seconds")) or _parse_duration(result.get("duration")),
                )
            )
        return tracks

    @staticmethod
    def _deduplicate(tracks: Iterable[Track]) -> list[Track]:
        seen: set[str] = set()
        output: list[Track] = []
        for track in tracks:
            key = track.video_id or track.webpage_url
            if key in seen:
                continue
            seen.add(key)
            output.append(track)
        return output


def _safe_int(value: object) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _thumbnail_url(entry: dict[str, object], video_id: str = "") -> str:
    thumbnail = entry.get("thumbnail")
    if isinstance(thumbnail, str) and thumbnail:
        return thumbnail
    thumbnails = entry.get("thumbnails")
    if isinstance(thumbnails, list):
        for candidate in reversed(thumbnails):
            if isinstance(candidate, dict):
                url = candidate.get("url")
                if isinstance(url, str) and url:
                    return url
    if video_id:
        return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
    return ""


def _parse_duration(value: object) -> int | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parts = [int(part) for part in value.split(":")]
    except ValueError:
        return None
    seconds = 0
    for part in parts:
        seconds = seconds * 60 + part
    return seconds
