"""Random discoveries from a song's YouTube Music radio."""
from __future__ import annotations

import math
import random
import re
from urllib.parse import parse_qs, urlparse

from PySide6.QtCore import QRunnable, Slot

from .models import Track
from .search_service import SearchSignals, _parse_duration, _safe_int


def youtube_id(track: Track) -> str:
    if track.video_id:
        return track.video_id
    url = urlparse(track.webpage_url)
    if url.hostname in {"youtu.be", "www.youtu.be"}:
        return url.path.strip("/").split("/")[0]
    if url.hostname in {"youtube.com", "www.youtube.com", "music.youtube.com"}:
        return parse_qs(url.query).get("v", [""])[0]
    return ""


def view_count(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value) if value > 0 else None
    match = re.fullmatch(r"([\d,.]+)\s*([KMB]?)\s*(?:views|plays)?", str(value or "").strip(), re.I)
    if not match:
        return None
    try:
        return float(match[1].replace(",", "")) * {"": 1, "K": 1e3, "M": 1e6, "B": 1e9}[match[2].upper()]
    except ValueError:
        return None


def similarity_weight(seed: dict, candidate: dict, rank: int) -> float:
    # Radio ordering supplies musical similarity; missing fields stay unknown.
    weight = 1 / (1 + rank / 10)
    year, other_year = _safe_int(seed.get("year")), _safe_int(candidate.get("year"))
    if year and other_year:
        weight /= 1 + abs(year - other_year) / 5
    views, other_views = view_count(seed.get("views")), view_count(candidate.get("views"))
    if views and other_views:
        weight /= 1 + abs(math.log10(views) - math.log10(other_views))
    return weight


class SimilarSearchTask(QRunnable):
    def __init__(self, track: Track, provider: str, request_id: int, excluded: set[str]) -> None:
        super().__init__()
        self.track = Track.from_dict(track.to_dict())
        self.provider = provider
        self.request_id = request_id
        self.excluded = set(excluded)
        self.signals = SearchSignals()

    @Slot()
    def run(self) -> None:
        try:
            for result in self.find_tracks():
                self.signals.result.emit(self.request_id, result)
            self.signals.finished.emit(self.request_id, self.provider)
        except Exception as exc:
            self.signals.failed.emit(self.request_id, self.provider, str(exc))

    def find_tracks(self) -> list[Track]:
        from ytmusicapi import YTMusic

        seed_id = youtube_id(self.track)
        if not seed_id:
            raise ValueError("Load a YouTube or YouTube Music track in this deck first. Local files do not have a song-radio ID.")
        radio = YTMusic().get_watch_playlist(videoId=seed_id, radio=True, limit=40)
        entries = radio.get("tracks") or []
        seed = next((entry for entry in entries if entry.get("videoId") == seed_id), {})
        seen = self.excluded | {seed_id}
        candidates, weights = [], []
        for rank, entry in enumerate(entries):
            video_id = entry.get("videoId")
            if not video_id or video_id in seen or not entry.get("title") or entry.get("isAvailable") is False:
                continue
            seen.add(video_id)
            candidates.append(entry)
            weights.append(similarity_weight(seed, entry, rank))
        if not candidates:
            raise ValueError("No new related songs were returned for this track. Try another seed track.")
        results = []
        for _ in range(min(10, len(candidates))):
            index = random.choices(range(len(candidates)), weights=weights, k=1)[0]
            chosen = candidates.pop(index)
            weights.pop(index)
            results.append(self._to_track(chosen))
        return results

    def _to_track(self, chosen: dict) -> Track:
        artists = ", ".join(artist["name"] for artist in chosen.get("artists", []) if artist.get("name"))
        details = [f"Related to {self.track.title}"]
        if chosen.get("year"):
            details.append(f"Released {chosen['year']}")
        if chosen.get("views"):
            details.append(f"Popularity: {chosen['views']}")
        thumbnails = chosen.get("thumbnail") or []
        return Track(
            title=chosen["title"], video_id=chosen["videoId"],
            webpage_url=f"https://www.youtube.com/watch?v={chosen['videoId']}",
            source="YouTube Music", uploader=artists, description=" • ".join(details),
            thumbnail_url=thumbnails[-1].get("url", "") if thumbnails else "",
            duration_seconds=_parse_duration(chosen.get("length")),
        )
