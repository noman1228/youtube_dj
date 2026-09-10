from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from app.search_service import SearchTask
from app.youtube_runtime import configure_youtube_processes


class SearchRuntimeTest(unittest.TestCase):
    def test_windows_helpers_suppress_consoles_and_preserve_flags(self):
        from yt_dlp.utils import Popen

        original = Mock()
        # Set an explicit False marker; Mock otherwise manufactures an attribute.
        original._encoremix_hidden = False
        with patch("app.youtube_runtime.sys.platform", "win32"), patch("app.youtube_runtime.subprocess.CREATE_NO_WINDOW", 0x08000000, create=True), patch.object(Popen, "__init__", original):
            configure_youtube_processes()
            wrapped = Popen.__init__
            configure_youtube_processes()
            self.assertIs(Popen.__init__, wrapped)
            process = object()
            wrapped(process, ["deno", "--version"], creationflags=0x200, stdout=123)
            original.assert_called_once_with(process, ["deno", "--version"], creationflags=0x08000200, stdout=123)

    def test_other_platforms_leave_subprocesses_unchanged(self):
        from yt_dlp.utils import Popen

        original = Popen.__init__
        with patch("app.youtube_runtime.sys.platform", "linux"):
            configure_youtube_processes()
        self.assertIs(Popen.__init__, original)

    def test_search_passes_direct_runtime_path_without_downloading(self):
        runtimes = {"deno": {"path": "packaged/deno.exe"}}
        with patch("app.search_service.javascript_runtimes", return_value=runtimes), patch("yt_dlp.YoutubeDL") as downloader:
            downloader.return_value.__enter__.return_value.extract_info.return_value = {"entries": []}
            self.assertEqual(SearchTask("test song", "YouTube")._search_youtube(), [])
            options = downloader.call_args.args[0]
            self.assertEqual(options["js_runtimes"], runtimes)
            self.assertTrue(options["extract_flat"])
            self.assertTrue(options["skip_download"])
            downloader.return_value.__enter__.return_value.extract_info.assert_called_once_with(
                "ytsearch12:test song", download=False,
            )


if __name__ == "__main__":
    unittest.main()
