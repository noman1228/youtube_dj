from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.runtime import configure_playback, javascript_runtimes, missing_decoders, readiness_issues


class RuntimeTest(unittest.TestCase):
    def test_software_mode_configures_backend_before_qt(self):
        with patch.dict(os.environ, {}, clear=True):
            configure_playback(software_video=True)
            self.assertEqual(os.environ["QT_MEDIA_BACKEND"], "ffmpeg")
            self.assertEqual(os.environ["QT_FFMPEG_DECODING_HW_DEVICE_TYPES"], ",")
            self.assertEqual(os.environ["QT_DISABLE_HW_TEXTURES_CONVERSION"], "1")

    def test_venv_runtime_does_not_need_activation(self):
        with patch("app.runtime.Path.is_file", return_value=True), patch("app.runtime.shutil.which") as which:
            runtimes = javascript_runtimes()
        self.assertIn("deno", runtimes)
        which.assert_not_called()

    def test_deno_uses_real_binary_instead_of_console_launcher(self):
        with patch("deno.find_deno_bin", return_value="packaged/deno.exe"), patch("app.runtime.Path.is_file", return_value=True):
            from pathlib import Path
            self.assertEqual(javascript_runtimes()["deno"]["path"], str(Path("packaged/deno.exe")))

    def test_missing_packaged_deno_falls_back_to_installed_runtime(self):
        with patch("deno.find_deno_bin", side_effect=RuntimeError("not installed")), patch("app.runtime.Path.is_file", return_value=False), patch("app.runtime.shutil.which", side_effect=lambda name: "system/deno" if name == "deno" else None):
            self.assertEqual(javascript_runtimes(), {"deno": {"path": "system/deno"}})

    def check_with(self, *, missing_hevc=False, version="deno 2.9.6", output=True):
        with patch("app.runtime.missing_decoders", return_value=["HEVC/H265"] if missing_hevc else []), patch("PySide6.QtMultimedia.QMediaFormat") as fmt, patch("PySide6.QtMultimedia.QMediaDevices") as devices, patch("app.runtime.javascript_runtimes", return_value={"deno": {"path": "deno"}}), patch("app.runtime.subprocess.run", return_value=SimpleNamespace(stdout=version)):
            fmt.return_value.supportedFileFormats.return_value = ["MP4"]
            devices.defaultAudioOutput.return_value.isNull.return_value = not output
            return readiness_issues()

    def test_complete_runtime_is_ready(self):
        self.assertEqual(self.check_with(), [])

    def test_missing_hevc_is_actionable(self):
        issues = self.check_with(missing_hevc=True)
        self.assertEqual(len(issues), 1)
        self.assertIn("H265", issues[0])
        self.assertIn("--repair", issues[0])

    def test_old_javascript_runtime_is_rejected(self):
        self.assertTrue(any("Deno" in issue for issue in self.check_with(version="deno 1.0.0")))

    def test_missing_audio_output_is_reported(self):
        self.assertTrue(any("audio output" in issue for issue in self.check_with(output=False)))

    def test_decoder_lookup_does_not_require_an_encoder_or_os_hevc_extension(self):
        with patch("app.runtime.Path.glob", return_value=[]), patch("app.runtime.ctypes.util.find_library", return_value="test-avcodec"), patch("app.runtime.ctypes.CDLL") as library:
            library.return_value.avcodec_find_decoder_by_name.side_effect = lambda name: name != b"hevc"
            self.assertEqual(missing_decoders(), ["HEVC/H265"])

    def test_absent_ffmpeg_library_has_a_clear_error(self):
        with patch("app.runtime.Path.glob", return_value=[]), patch("app.runtime.ctypes.util.find_library", return_value=None):
            with self.assertRaisesRegex(OSError, "libavcodec"):
                missing_decoders()


if __name__ == "__main__":
    unittest.main()
