from __future__ import annotations

import copy
import io
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import urlopen

import yt_dlp

from app.media import ResolveTask, _video_format_selector
from app.hls import HlsPlaylistServer, HlsVideoSource, select_hls_video
from app.models import Track


class MediaFormatTest(unittest.TestCase):
    def setUp(self) -> None:
        self.master = "https://example.invalid/master.m3u8"
        # Match the separate HLS renditions returned for AQOt75axc0Y,
        # including an audio rendition whose codec is not specified.
        self.audio = {
            "format_id": "234", "url": "https://example.invalid/audio.m3u8",
            "ext": "mp4", "protocol": "m3u8_native",
            "vcodec": "none", "acodec": None, "manifest_url": self.master,
        }
        self.video = {
            "format_id": "231", "url": "https://example.invalid/video.m3u8",
            "ext": "mp4", "protocol": "m3u8_native", "height": 720,
            "vcodec": "avc1.4D401F", "acodec": "none", "manifest_url": self.master,
        }

    def _process(self, formats: list[dict], selector=_video_format_selector) -> dict:
        with yt_dlp.YoutubeDL({
            "quiet": True, "logger": Mock(), "format": selector, "check_formats": False,
        }) as ydl:
            return ydl.process_ie_result({
                "id": "fixture", "title": "Format fixture", "extractor": "youtube",
                "duration": 217, "formats": copy.deepcopy(formats),
            }, download=False)

    def test_separate_hls_renditions_select_shared_master(self) -> None:
        result = self._process([self.audio, self.video])
        self.assertEqual(result["url"], self.master)
        self.assertEqual(result["format_id"], "hls-master")
        self.assertNotEqual(result["acodec"], "none")
        self.assertNotEqual(result["vcodec"], "none")
        self.assertEqual(self.video["url"], "https://example.invalid/video.m3u8")

    def test_combined_720p_is_preferred_over_master_and_1080p(self) -> None:
        combined = {
            "format_id": "22", "url": "https://example.invalid/combined.mp4",
            "ext": "mp4", "height": 720, "vcodec": "avc1", "acodec": "mp4a",
        }
        larger = {**combined, "format_id": "37", "height": 1080,
                  "url": "https://example.invalid/larger.mp4"}
        result = self._process([self.audio, self.video, combined, larger])
        self.assertEqual(result["url"], combined["url"])

    def test_combined_above_720p_is_allowed_when_it_is_the_only_combined_stream(self) -> None:
        combined = {**self.video, "format_id": "37", "protocol": "https",
                    "acodec": "mp4a", "height": 1080}
        result = self._process([combined])
        self.assertEqual(result["url"], combined["url"])

    def test_unrelated_or_non_hls_streams_cannot_become_a_master(self) -> None:
        cases = [
            [{**self.audio, "manifest_url": "https://example.invalid/other.m3u8"}, self.video],
            [{**self.audio, "protocol": "https"}, {**self.video, "protocol": "https"}],
            [self.video],
            [self.audio],
            [{**self.audio, "acodec": "none"}, self.video],
            [self.audio, {**self.video, "has_drm": True}],
        ]
        for formats in cases:
            with self.subTest(formats=formats):
                self.assertEqual(list(_video_format_selector({"formats": formats})), [])

    def test_no_compatible_format_still_reports_a_real_extraction_error(self) -> None:
        with self.assertRaisesRegex(yt_dlp.utils.ExtractorError, "Requested format is not available"):
            self._process([self.video])

    def test_audio_selector_keeps_audio_only_stream(self) -> None:
        audio = {**self.audio, "acodec": "mp4a"}
        result = self._process([audio, self.video], "bestaudio/best")
        self.assertEqual(result["url"], audio["url"])

    def test_resolve_task_passes_master_url_and_duration_to_player(self) -> None:
        resolved = Mock()
        failed = Mock()
        task = ResolveTask(7, Track("Karaoke", "https://example.invalid/watch"), video=True)
        task.signals.resolved.connect(resolved)
        task.signals.failed.connect(failed)

        def extract(ydl, url, download=False):
            self.assertFalse(download)
            return ydl.process_ie_result({
                "id": "fixture", "title": "Karaoke", "extractor": "youtube",
                "duration": 217, "formats": copy.deepcopy([self.audio, self.video]),
            }, download=False)

        manifest = (
            '#EXTM3U\n#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",DEFAULT=YES,URI="audio.m3u8"\n'
            '#EXT-X-STREAM-INF:BANDWIDTH=1000000,RESOLUTION=1280x720,AUDIO="audio"\nvideo.m3u8\n'
        )
        with patch.object(yt_dlp.YoutubeDL, "extract_info", extract), patch.object(
            yt_dlp.YoutubeDL, "urlopen", return_value=io.BytesIO(manifest.encode())
        ):
            task.run()

        failed.assert_not_called()
        resolved.assert_called_once()
        generation, track, source, duration, description = resolved.call_args.args
        self.assertEqual((generation, track, duration, description), (7, task.track, 217, "720P VIDEO + AUDIO"))
        self.assertIsInstance(source, HlsVideoSource)
        self.assertEqual(source.url, self.master)
        self.assertEqual(source.playlist.count(b"#EXT-X-STREAM-INF:"), 1)


class HlsSelectionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.url = "https://example.invalid/manifests/master.m3u8?signature=master"
        self.header = (
            '#EXTM3U\n#EXT-X-VERSION:6\n#EXT-X-INDEPENDENT-SEGMENTS\n'
            '#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",NAME="English",DEFAULT=YES,URI="audio.m3u8?signature=audio"\n'
            '#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",NAME="Other",DEFAULT=NO,URI="other.m3u8"\n'
        )

    def _variant(self, height: int, codec: str = "avc1.4D401F", group: str = "audio") -> str:
        return (
            f'#EXT-X-STREAM-INF:BANDWIDTH=1000000,RESOLUTION={height * 16 // 9}x{height},'
            f'CODECS="{codec},mp4a.40.2",AUDIO="{group}"\n{height}-{codec}.m3u8?signature=video\n'
        )

    def test_only_720p_and_default_audio_survive_full_master(self) -> None:
        manifest = self.header + "".join(self._variant(height) for height in (144, 240, 360, 480, 720, 1080))
        source = select_hls_video(manifest, self.url)
        text = source.playlist.decode()
        self.assertEqual(source.height, 720)
        self.assertEqual(text.count("#EXT-X-STREAM-INF:"), 1)
        self.assertEqual(text.count("#EXT-X-MEDIA:"), 1)
        self.assertIn("RESOLUTION=1280x720", text)
        self.assertIn("#EXT-X-INDEPENDENT-SEGMENTS", text)
        self.assertIn("https://example.invalid/manifests/audio.m3u8?signature=audio", text)
        self.assertIn("https://example.invalid/manifests/720-avc1.4D401F.m3u8?signature=video", text)
        self.assertNotIn("1080-", text)
        self.assertNotIn("240-", text)
        self.assertNotIn("other.m3u8", text)

    def test_h264_is_preferred_to_vp9_at_same_resolution(self) -> None:
        source = select_hls_video(self.header + self._variant(720) + self._variant(720, "vp09"), self.url)
        self.assertIn(b"avc1", source.playlist)
        self.assertNotIn(b"vp09", source.playlist)

    def test_best_available_sd_is_used_when_hd_is_absent(self) -> None:
        source = select_hls_video(self.header + self._variant(240) + self._variant(480), self.url)
        self.assertEqual(source.height, 480)

    def test_smallest_above_limit_is_used_when_all_variants_exceed_720p(self) -> None:
        source = select_hls_video(self.header + self._variant(1080) + self._variant(2160), self.url)
        self.assertEqual(source.height, 1080)

    def test_video_without_matching_audio_is_not_selected(self) -> None:
        source = select_hls_video(self.header + self._variant(480) + self._variant(720, group="missing"), self.url)
        self.assertEqual(source.height, 480)
        with self.assertRaisesRegex(RuntimeError, "No compatible HLS"):
            select_hls_video(self.header + self._variant(720, group="missing"), self.url)

    def test_invalid_manifest_is_rejected(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "invalid HLS"):
            select_hls_video("<html>Forbidden</html>", self.url)

    def test_loopback_serves_only_current_playlist_and_closes(self) -> None:
        server = HlsPlaylistServer()
        source = HlsVideoSource(self.url, b"#EXTM3U\n", 720)
        try:
            previous_url = server.publish(source)
            current_url = server.publish(source)
            with urlopen(current_url, timeout=2) as response:
                self.assertEqual(response.read(), source.playlist)
                self.assertEqual(response.headers["Cache-Control"], "no-store")
            with self.assertRaises(HTTPError) as error:
                urlopen(previous_url, timeout=2)
            self.assertEqual(error.exception.code, 404)
            with self.assertRaises(HTTPError) as error:
                urlopen(current_url.rsplit("/", 1)[0] + "/requirements.txt", timeout=2)
            self.assertEqual(error.exception.code, 404)
        finally:
            server.close()
            server.close()
        self.assertFalse(server._thread.is_alive())


if __name__ == "__main__":
    unittest.main()
