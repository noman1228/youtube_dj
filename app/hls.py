from __future__ import annotations

import re
import secrets
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urljoin


@dataclass(frozen=True)
class HlsVideoSource:
    url: str
    playlist: bytes
    height: int


class HlsPlaylistServer:
    """Serve only the current small playlist on loopback, never media or files."""

    def __init__(self) -> None:
        self._current: tuple[str, bytes] = ("", b"")
        self._closed = False
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                path, playlist = owner._current
                if not path or self.path != path:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/vnd.apple.mpegurl")
                self.send_header("Content-Length", str(len(playlist)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                try:
                    self.wfile.write(playlist)
                except (BrokenPipeError, ConnectionResetError):
                    pass  # The player changed tracks while reading the playlist.

            def log_message(self, *_args: object) -> None:
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(
            target=lambda: self._server.serve_forever(poll_interval=0.1), daemon=True
        )
        self._thread.start()

    def publish(self, source: HlsVideoSource) -> str:
        path = f"/{secrets.token_urlsafe(18)}.m3u8"
        self._current = (path, source.playlist)
        return f"http://127.0.0.1:{self._server.server_port}{path}"

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._current = ("", b"")
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=1)


def _attributes(line: str) -> dict[str, str]:
    return {
        key: value.strip('"')
        for key, value in re.findall(r'([A-Z0-9-]+)=("[^"]*"|[^,]*)', line)
    }


def _absolute_uris(line: str, base_url: str) -> str:
    return re.sub(
        r'URI="([^"]+)"',
        lambda match: f'URI="{urljoin(base_url, match.group(1))}"',
        line,
    )


def select_hls_video(text: str, url: str, max_height: int = 720) -> HlsVideoSource:
    """Keep one video rendition and its audio, avoiding probes of every quality."""
    lines = [line.strip() for line in text.lstrip("\ufeff").splitlines() if line.strip()]
    if not lines or lines[0] != "#EXTM3U":
        raise RuntimeError("The video server returned an invalid HLS playlist.")
    media = [
        (_attributes(line), line) for line in lines if line.startswith("#EXT-X-MEDIA:")
    ]
    variants = []
    pending = None
    for line in lines:
        if line.startswith("#EXT-X-STREAM-INF:"):
            pending = (_attributes(line), line)
        elif not line.startswith("#") and pending:
            attributes, tag = pending
            pending = None
            resolution = attributes.get("RESOLUTION", "").lower().split("x")
            if len(resolution) != 2 or not all(value.isdigit() for value in resolution):
                continue
            audio = [
                (fields, entry) for fields, entry in media
                if fields.get("TYPE") == "AUDIO"
                and fields.get("GROUP-ID") == attributes.get("AUDIO")
                and fields.get("URI")
            ]
            if not audio:
                continue
            # Prefer the default language, then keep only that rendition.
            audio.sort(key=lambda item: item[0].get("DEFAULT") == "YES", reverse=True)
            height = int(resolution[1])
            if height > 0:
                variants.append((height, attributes, tag, line, audio[0][1]))
    if not variants:
        raise RuntimeError("No compatible HLS video/audio rendition was found.")

    preferred = [variant for variant in variants if variant[0] <= max_height]
    if not preferred:
        smallest = min(variant[0] for variant in variants)
        preferred = [variant for variant in variants if variant[0] == smallest]
    selected = max(preferred, key=lambda variant: (
        variant[0],
        "avc1" in variant[1].get("CODECS", ""),
        int(variant[1].get("BANDWIDTH", "0")),
    ))
    height, attributes, tag, video_url, audio_tag = selected
    result = ["#EXTM3U"]
    result.extend(
        _absolute_uris(line, url) for line in lines
        if line.startswith(("#EXT-X-VERSION:", "#EXT-X-INDEPENDENT-SEGMENTS", "#EXT-X-SESSION-KEY:"))
    )
    result.append(_absolute_uris(audio_tag, url))
    # Preserve any subtitle group referenced by the retained video variant.
    result.extend(
        _absolute_uris(entry, url) for fields, entry in media
        if fields.get("TYPE") == "SUBTITLES"
        and fields.get("GROUP-ID") == attributes.get("SUBTITLES")
    )
    result.extend((tag, urljoin(url, video_url)))
    return HlsVideoSource(url, ("\n".join(result) + "\n").encode("utf-8"), height)
