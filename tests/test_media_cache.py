from __future__ import annotations

import io
import re
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import yt_dlp

from app.hls import HlsVideoSource
from app.media_cache import prepare_media


class Response(io.BytesIO):
    def __init__(self, data: bytes, url: str, length: int | None = None) -> None:
        super().__init__(data)
        self.url = url
        self.status = 200
        self.headers = {"Content-Length": str(len(data) if length is None else length)}


class FakeYdl:
    def __init__(self, resources: dict | None = None) -> None:
        self.params = {"skip_download": True, "outtmpl": {"default": "unused"}}
        self.resources = resources or {}
        self.requests = []
        self.selected = None
        self.download_options = None
        self.complete = True
        self.payload = b"fully downloaded media"
        self.partial = False

    def urlopen(self, request):
        self.requests.append(request)
        data = self.resources[request.url]
        if isinstance(data, Exception):
            raise data
        if callable(data):
            return data()
        return Response(data, request.url)

    def prepare_filename(self, info: dict) -> str:
        return self.params["outtmpl"]["default"] % info

    def process_info(self, info: dict) -> None:
        self.selected = dict(info)
        self.download_options = dict(self.params)
        path = Path(self.prepare_filename(info))
        path.write_bytes(self.payload)
        if self.partial:
            path.with_suffix(path.suffix + ".part").write_bytes(b"unfinished")
        if self.complete:
            info["__write_download_archive"] = True


class MediaCacheTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.cancelled = threading.Event()
        self.base = "https://example.invalid/"
        self.info = {"id": "fixture", "title": "Fixture", "url": self.base + "audio.m4a",
                     "ext": "m4a", "protocol": "https"}

    def prepare(self, ydl, info=None, source=None) -> Path:
        return prepare_media(ydl, info or self.info, source, self.directory, self.cancelled)

    def hls(self, playlist: str, resources: dict | None = None, headers=None):
        info = {**self.info, "url": self.base + "audio.m3u8", "protocol": "m3u8_native",
                "http_headers": headers or {}}
        ydl = FakeYdl({info["url"]: playlist.encode(), **(resources or {})})
        return ydl, info

    def test_plain_download_uses_selected_url_and_restores_options(self) -> None:
        ydl = FakeYdl()
        before = dict(ydl.params)
        original = dict(self.info)
        result = self.prepare(ydl)
        self.assertEqual(result.read_bytes(), ydl.payload)
        self.assertEqual(result.parent, self.directory.resolve())
        self.assertEqual(ydl.selected["url"], self.info["url"])
        self.assertFalse(ydl.download_options["skip_download"])
        self.assertFalse(ydl.download_options["skip_unavailable_fragments"])
        self.assertEqual(ydl.download_options["concurrent_fragment_downloads"], 1)
        self.assertEqual(ydl.download_options["external_downloader"], "native")
        self.assertEqual(ydl.download_options["fixup"], "never")
        self.assertEqual(ydl.params, before)
        self.assertEqual(self.info, original)
        self.assertEqual(ydl.requests, [])

    def test_real_yt_dlp_download_bookkeeping_without_network(self) -> None:
        with yt_dlp.YoutubeDL({"quiet": True, "logger": Mock(), "skip_download": True}) as ydl:
            def download(filename, info):
                Path(filename).write_bytes(b"complete fixture")
                return True, True

            with patch.object(ydl, "dl", side_effect=download), patch.object(
                ydl, "extract_info", side_effect=AssertionError("Must not extract again")
            ), patch.object(ydl, "urlopen", side_effect=AssertionError("No network")):
                path = self.prepare(ydl)
            self.assertEqual(path.read_bytes(), b"complete fixture")

    def test_partial_empty_and_failed_downloads_never_become_ready(self) -> None:
        for complete, partial, payload in [(False, False, b"partial"), (True, True, b"partial"),
                                           (True, False, b"")]:
            with self.subTest(complete=complete, partial=partial, payload=payload):
                with tempfile.TemporaryDirectory() as directory:
                    ydl = FakeYdl()
                    ydl.complete, ydl.partial, ydl.payload = complete, partial, payload
                    with self.assertRaisesRegex(RuntimeError, "did not finish"):
                        prepare_media(ydl, self.info, None, Path(directory), self.cancelled)

    def test_stale_success_marker_cannot_hide_failed_download(self) -> None:
        ydl = FakeYdl()
        ydl.complete = False
        with self.assertRaisesRegex(RuntimeError, "did not finish"):
            self.prepare(ydl, {**self.info, "__write_download_archive": True})

    def test_live_and_external_downloader_formats_fail_before_download(self) -> None:
        for update in [{"is_live": True}, {"live_status": "is_upcoming"},
                       {"live_status": "post_live"}, {"has_drm": True},
                       {"protocol": "rtmp"}, {"requested_formats": [self.info]},
                       {"section_end": 5}]:
            with self.subTest(update=update):
                ydl = FakeYdl()
                with self.assertRaises(RuntimeError):
                    self.prepare(ydl, {**self.info, **update})
                self.assertIsNone(ydl.selected)
                self.assertEqual(ydl.requests, [])

    def test_cancelled_download_never_becomes_ready(self) -> None:
        ydl = FakeYdl()
        self.cancelled.set()
        with self.assertRaisesRegex(RuntimeError, "cancelled"):
            self.prepare(ydl)
        self.assertIsNone(ydl.selected)

    def test_cancel_after_plain_download_still_does_not_publish(self) -> None:
        ydl = FakeYdl()
        download = ydl.process_info

        def cancel_after_download(info):
            download(info)
            self.cancelled.set()

        ydl.process_info = cancel_after_download
        with self.assertRaisesRegex(RuntimeError, "cancelled"):
            self.prepare(ydl)

    def test_audio_hls_is_fully_local_with_headers_and_full_byte_range_objects(self) -> None:
        playlist = ('#EXTM3U\n#EXT-X-VERSION:7\n'
                    '#EXT-X-KEY:METHOD=AES-128,URI="key.bin"\n'
                    '#EXT-X-MAP:URI="init.mp4",BYTERANGE="4@0"\n'
                    '#EXTINF:1,\n#EXT-X-BYTERANGE:4@0\nsegments.mp4\n'
                    '#EXTINF:1,\n#EXT-X-BYTERANGE:4\nsegments.mp4\n#EXT-X-ENDLIST\n')
        ydl, info = self.hls(playlist, {self.base + "key.bin": b"1234567890123456",
                                      self.base + "init.mp4": b"init content",
                                      self.base + "segments.mp4": b"12345678"},
                             {"Referer": "https://referrer.invalid/", "Range": "bytes=0-3"})
        path = self.prepare(ydl, info)
        rewritten = path.read_text()
        self.assertNotIn("https://", rewritten)
        self.assertNotIn("segments.mp4", rewritten)
        self.assertIn("#EXT-X-BYTERANGE:4@0", rewritten)
        self.assertEqual(sum(r.url.endswith("segments.mp4") for r in ydl.requests), 1)
        for request in ydl.requests:
            self.assertEqual(request.headers["Referer"], "https://referrer.invalid/")
            self.assertNotIn("Range", request.headers)
        targets = re.findall(r'URI="([^"]+)"', rewritten)
        targets += [line for line in rewritten.splitlines() if not line.startswith("#")]
        self.assertTrue(all((path.parent / name).is_file() for name in targets))

    def test_selected_master_preserves_audio_video_and_subtitles_locally(self) -> None:
        master = ('#EXTM3U\n#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="a",URI="audio.m3u8"\n'
                  '#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="s",URI="subtitles.m3u8"\n'
                  '#EXT-X-STREAM-INF:BANDWIDTH=1000000,AUDIO="a",SUBTITLES="s"\nvideo.m3u8\n')
        source = HlsVideoSource(self.base + "master.m3u8", master.encode(), 720)
        resources = {}
        for kind in ["audio", "video", "subtitles"]:
            resources[self.base + kind + ".m3u8"] = (
                f"#EXTM3U\n#EXTINF:1,\n{kind}.bin\n#EXT-X-ENDLIST\n").encode()
            resources[self.base + kind + ".bin"] = kind.encode()
        ydl = FakeYdl(resources)
        root = self.prepare(ydl, source=source)
        self.assertEqual(len(ydl.requests), 6)
        self.assertNotIn("https://", root.read_text())
        self.assertEqual(len(list(self.directory.glob("*.m3u8"))), 4)
        for path in self.directory.glob("*.m3u8"):
            text = path.read_text()
            targets = re.findall(r'URI="([^"]+)"', text)
            targets += [line for line in text.splitlines() if not line.startswith("#")]
            self.assertTrue(all((self.directory / target).is_file() for target in targets))

    def test_live_and_unsupported_hls_fail_before_fetching_segments(self) -> None:
        for playlist in ["#EXTM3U\n#EXTINF:1,\nsegment.ts\n",
                         "#EXTM3U\n#EXT-X-GAP\n#EXTINF:1,\nsegment.ts\n#EXT-X-ENDLIST\n",
                         '#EXTM3U\n#EXT-X-KEY:METHOD=SAMPLE-AES,URI="key"\n#EXT-X-ENDLIST\n',
                         '#EXTM3U\n#EXT-X-MAP:URI=init.mp4\n#EXT-X-ENDLIST\n',
                         '#EXTM3U\n#EXTINF:1,\nfile:///secret.ts\n#EXT-X-ENDLIST\n']:
            with self.subTest(playlist=playlist):
                ydl, info = self.hls(playlist)
                with self.assertRaises(RuntimeError):
                    self.prepare(ydl, info)
                self.assertEqual(len(ydl.requests), 1)

    def test_failed_fragment_retries_bounded_and_never_publishes_playlist(self) -> None:
        ydl, info = self.hls("#EXTM3U\n#EXTINF:1,\nmissing.ts\n#EXT-X-ENDLIST\n",
                             {self.base + "missing.ts": OSError("Missing fragment")})
        with self.assertRaisesRegex(OSError, "Missing fragment"):
            self.prepare(ydl, info)
        self.assertEqual(sum(r.url.endswith("missing.ts") for r in ydl.requests), 3)
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_truncated_fragment_is_not_treated_as_complete(self) -> None:
        url = self.base + "truncated.ts"
        ydl, info = self.hls("#EXTM3U\n#EXTINF:1,\ntruncated.ts\n#EXT-X-ENDLIST\n",
                             {url: lambda: Response(b"short", url, 100)})
        with self.assertRaisesRegex(RuntimeError, "incomplete"):
            self.prepare(ydl, info)
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_playlist_size_is_bounded(self) -> None:
        ydl, info = self.hls("#EXTM3U\n" + "x" * 1_048_576)
        with self.assertRaisesRegex(RuntimeError, "too large"):
            self.prepare(ydl, info)
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_playlist_cycle_is_rejected(self) -> None:
        ydl, info = self.hls("#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1\naudio.m3u8\n")
        with self.assertRaisesRegex(RuntimeError, "cycle"):
            self.prepare(ydl, info)
        self.assertEqual(len(ydl.requests), 1)

    def test_redirected_playlist_resolves_resources_against_final_url(self) -> None:
        ydl, info = self.hls("")
        final = self.base + "redirected/audio.m3u8"
        ydl.resources[info["url"]] = lambda: Response(
            b"#EXTM3U\n#EXTINF:1,\nsegment.ts\n#EXT-X-ENDLIST\n", final)
        ydl.resources[self.base + "redirected/segment.ts"] = b"media"
        self.assertTrue(self.prepare(ydl, info).is_file())
        self.assertEqual(ydl.requests[-1].url, self.base + "redirected/segment.ts")

    def test_hls_cancel_during_chunk_read_removes_partial_and_stops_retrying(self) -> None:
        event = self.cancelled

        class CancelResponse(Response):
            def read(self, size=-1):
                event.set()
                return super().read(size)

        url = self.base + "segment.ts"
        ydl, info = self.hls("#EXTM3U\n#EXTINF:1,\nsegment.ts\n#EXT-X-ENDLIST\n",
                             {url: lambda: CancelResponse(b"media", url)})
        with self.assertRaisesRegex(RuntimeError, "cancelled"):
            self.prepare(ydl, info)
        self.assertEqual(len(ydl.requests), 2)
        self.assertEqual(list(self.directory.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
