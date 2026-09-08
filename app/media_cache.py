from __future__ import annotations

import hashlib
import re
import threading
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from yt_dlp.networking import Request

from .hls import HlsVideoSource


_PLAYLIST_LIMIT = 1_048_576
_CHUNK_SIZE = 262_144
_MAX_DEPTH = 8
_MAX_RESOURCES = 100_000
_URI = re.compile(r'(?<![A-Z0-9-])URI="([^"]*)"')
_ATTRIBUTES = re.compile(r'([A-Z0-9-]+)=("[^"]*"|[^,]*)')
_SUPPORTED_TAGS = {
    "EXTM3U", "EXTINF", "EXT-X-VERSION", "EXT-X-TARGETDURATION",
    "EXT-X-MEDIA-SEQUENCE", "EXT-X-DISCONTINUITY-SEQUENCE", "EXT-X-ENDLIST",
    "EXT-X-PLAYLIST-TYPE", "EXT-X-INDEPENDENT-SEGMENTS", "EXT-X-START",
    "EXT-X-ALLOW-CACHE", "EXT-X-DISCONTINUITY", "EXT-X-PROGRAM-DATE-TIME",
    "EXT-X-BYTERANGE", "EXT-X-MAP", "EXT-X-KEY", "EXT-X-SESSION-KEY",
    "EXT-X-MEDIA", "EXT-X-STREAM-INF", "EXT-X-I-FRAME-STREAM-INF",
}


def _check_cancelled(cancelled: threading.Event) -> None:
    if cancelled.is_set():
        raise RuntimeError("Media preparation was cancelled.")


def prepare_media(
    ydl, info: dict, hls_source: HlsVideoSource | None,
    directory: Path, cancelled: threading.Event,
) -> Path:
    """Finish downloading a finite track before returning any playable source.

    The caller owns the private directory until its player has released the
    returned source. Configure yt-dlp's progress hook to check ``cancelled``
    when constructing the supplied YoutubeDL instance.
    """
    _check_cancelled(cancelled)
    if info.get("is_live") or info.get("live_status") in {"is_live", "is_upcoming", "post_live"}:
        raise RuntimeError("Live media cannot be fully prepared for uninterrupted playback.")
    if info.get("has_drm"):
        raise RuntimeError("Protected media cannot be prepared for playback.")
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    url = str(info.get("url") or "")
    protocol = info.get("protocol") or urlsplit(url).scheme
    if hls_source or protocol in {"m3u8", "m3u8_native"} or urlsplit(url).path.endswith(".m3u8"):
        cache = _HlsCache(ydl, info.get("http_headers") or {}, directory, cancelled)
        return cache.playlist(hls_source.url if hls_source else url,
                              hls_source.playlist if hls_source else None)
    if protocol not in {"http", "https", "http_dash_segments"} or info.get("requested_formats"):
        raise RuntimeError("This media format cannot be fully prepared without an external downloader.")
    if info.get("section_start") or info.get("section_end"):
        raise RuntimeError("Partial media downloads are not supported for prepared playback.")

    selected = dict(info)
    # Do not let stale extraction/download bookkeeping publish an old file or
    # introduce another extraction, a merge, or an external postprocessor.
    for key in ("requested_downloads", "filepath", "_filename", "__write_download_archive",
                "__postprocessors", "__post_extractor", "__files_to_move"):
        selected.pop(key, None)
    options = {
        "outtmpl": {"default": str(directory / "media.%(ext)s")},
        "paths": {}, "skip_download": False, "simulate": False,
        "skip_unavailable_fragments": False, "concurrent_fragment_downloads": 1,
        "external_downloader": "native", "fixup": "never",
        "overwrites": True, "continuedl": False, "nopart": False,
    }
    missing = object()
    previous = {key: ydl.params.get(key, missing) for key in options}
    ydl.params.update(options)
    try:
        ydl.process_info(selected)
        _check_cancelled(cancelled)
        filename = Path(ydl.prepare_filename(selected)).resolve()
        if (not filename.is_relative_to(directory)
                or selected.get("__write_download_archive") is not True
                or not filename.is_file() or filename.stat().st_size == 0
                or any(directory.glob("*.part*"))):
            raise RuntimeError("The media download did not finish; playback has not started.")
        return filename
    finally:
        for key, value in previous.items():
            if value is missing:
                ydl.params.pop(key, None)
            else:
                ydl.params[key] = value


class _HlsCache:
    def __init__(self, ydl, headers: dict, directory: Path, cancelled: threading.Event) -> None:
        self.ydl = ydl
        # Each cached object is complete, including objects reused by byte ranges.
        self.headers = {key: value for key, value in headers.items() if key.lower() != "range"}
        self.directory = directory
        self.cancelled = cancelled
        self.completed: dict[tuple[str, bool], Path] = {}
        self.active: set[str] = set()

    def _path(self, url: str, playlist: bool) -> Path:
        suffix = Path(urlsplit(url).path).suffix
        if not re.fullmatch(r"\.[A-Za-z0-9]{1,8}", suffix):
            suffix = ".bin"
        return self.directory / (hashlib.sha256(url.encode()).hexdigest() + (".m3u8" if playlist else suffix))

    def _url(self, value: str, base: str) -> str:
        if not value or "{$" in value:
            raise RuntimeError("HLS contains an empty or unsupported variable URI.")
        url = urljoin(base, value)
        if urlsplit(url).scheme not in {"http", "https"}:
            raise RuntimeError("HLS contains an unsupported resource URI.")
        return url

    def _fetch(self, url: str, destination: Path, playlist: bool) -> str:
        partial = destination.with_name(destination.name + ".part")
        for attempt in range(3):
            _check_cancelled(self.cancelled)
            try:
                with self.ydl.urlopen(Request(url, headers=self.headers)) as response:
                    if getattr(response, "status", 200) == 206:
                        raise RuntimeError("The HLS server returned an incomplete resource.")
                    length = (getattr(response, "headers", {}) or {}).get("Content-Length")
                    expected = int(length) if length is not None else None
                    if playlist and expected is not None and expected > _PLAYLIST_LIMIT:
                        raise RuntimeError("The HLS playlist is too large to prepare safely.")
                    size = 0
                    with partial.open("wb") as output:
                        while True:
                            _check_cancelled(self.cancelled)
                            chunk = response.read(min(_CHUNK_SIZE, _PLAYLIST_LIMIT + 1 - size)
                                                  if playlist else _CHUNK_SIZE)
                            if not chunk:
                                break
                            size += len(chunk)
                            if playlist and size > _PLAYLIST_LIMIT:
                                raise RuntimeError("The HLS playlist is too large to prepare safely.")
                            output.write(chunk)
                    if size == 0 or (expected is not None and size != expected):
                        raise RuntimeError("An HLS resource was empty or incomplete.")
                    final_url = getattr(response, "url", None) or url
                _check_cancelled(self.cancelled)
                partial.replace(destination)
                return final_url
            except Exception:
                partial.unlink(missing_ok=True)
                _check_cancelled(self.cancelled)
                if attempt == 2:
                    raise
                self.cancelled.wait(0.1 * (attempt + 1))
        raise RuntimeError("The HLS resource could not be prepared.")  # pragma: no cover

    def resource(self, url: str) -> Path:
        _check_cancelled(self.cancelled)
        key = (url, False)
        if key not in self.completed:
            if len(self.completed) >= _MAX_RESOURCES:
                raise RuntimeError("The HLS track contains too many resources.")
            path = self._path(url, False)
            self._fetch(url, path, False)
            self.completed[key] = path
        return self.completed[key]

    def playlist(self, url: str, supplied: bytes | None = None, depth: int = 0) -> Path:
        _check_cancelled(self.cancelled)
        url = self._url(url, url)
        if url in self.active or depth > _MAX_DEPTH:
            raise RuntimeError("The HLS playlists contain a cycle or too many nested playlists.")
        if (url, True) in self.completed:
            return self.completed[(url, True)]
        if len(self.completed) >= _MAX_RESOURCES:
            raise RuntimeError("The HLS track contains too many resources.")
        path = self._path(url, True)
        raw = path.with_suffix(".manifest")
        base = url
        if supplied is None:
            base = self._fetch(url, raw, True)
            supplied = raw.read_bytes()
            raw.unlink()
        if len(supplied) > _PLAYLIST_LIMIT:
            raise RuntimeError("The HLS playlist is too large to prepare safely.")
        lines = [line.strip() for line in supplied.decode("utf-8-sig").splitlines() if line.strip()]
        if not lines or lines[0] != "#EXTM3U":
            raise RuntimeError("The HLS server returned an invalid playlist.")
        master = any(line.startswith("#EXT-X-STREAM-INF:") for line in lines)
        if not master and "#EXT-X-ENDLIST" not in lines:
            raise RuntimeError("Live or incomplete HLS media cannot be prepared for uninterrupted playback.")
        # Validate the entire manifest before fetching any media from it.
        for line in lines:
            if not line.startswith("#"):
                self._url(line, base)
                continue
            tag = line[1:].split(":", 1)[0]
            if tag.startswith("EXT") and tag not in _SUPPORTED_TAGS:
                raise RuntimeError(f"Unsupported HLS feature: {tag}.")
            fields = {key: value.strip('"') for key, value in _ATTRIBUTES.findall(line)}
            if "URI" in fields and not _URI.search(line):
                raise RuntimeError("HLS contains an unsupported URI attribute.")
            if any(key.endswith("URI") and key != "URI" for key in fields):
                raise RuntimeError("HLS contains an unsupported external URI attribute.")
            if tag in {"EXT-X-KEY", "EXT-X-SESSION-KEY"}:
                if (fields.get("METHOD") not in {"NONE", "AES-128"}
                        or fields.get("KEYFORMAT", "identity") != "identity"
                        or (fields.get("METHOD") == "AES-128" and "URI" not in fields)):
                    raise RuntimeError("This HLS encryption method cannot be prepared for playback.")
        self.active.add(url)
        try:
            rewritten = []
            media_count = 0
            pending_variant = False
            for line in lines:
                _check_cancelled(self.cancelled)
                if not line.startswith("#"):
                    target = self._url(line, base)
                    if master:
                        if not pending_variant:
                            raise RuntimeError("The HLS master contains an invalid variant URI.")
                        local = self.playlist(target, depth=depth + 1)
                        pending_variant = False
                    else:
                        local = self.resource(target)
                    media_count += 1
                    rewritten.append(local.name)
                    continue
                if line.startswith("#EXT-X-STREAM-INF:"):
                    if pending_variant:
                        raise RuntimeError("The HLS master is missing a variant URI.")
                    pending_variant = True
                is_playlist = line.startswith(("#EXT-X-MEDIA:", "#EXT-X-I-FRAME-STREAM-INF:"))

                def replace_uri(match: re.Match) -> str:
                    target = self._url(match.group(1), base)
                    local = self.playlist(target, depth=depth + 1) if is_playlist else self.resource(target)
                    return f'URI="{local.name}"'

                rewritten.append(_URI.sub(replace_uri, line))
            if not media_count or pending_variant:
                raise RuntimeError("The HLS playlist contains no complete playable media.")
            _check_cancelled(self.cancelled)
            temporary = path.with_name(path.name + ".part")
            temporary.write_text("\n".join(rewritten) + "\n", encoding="utf-8")
            temporary.replace(path)
            self.completed[(url, True)] = path
            return path
        finally:
            self.active.remove(url)
