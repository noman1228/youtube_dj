"""Playback configuration and offline readiness checks."""
from __future__ import annotations

import os
import ctypes
import ctypes.util
import re
import shutil
import subprocess
import sysconfig
from pathlib import Path


def configure_playback(*, software_video: bool = False) -> None:
    # Run before importing Qt Multimedia, including in helper processes.
    os.environ["QT_MEDIA_BACKEND"] = "ffmpeg"
    if software_video:
        os.environ["QT_FFMPEG_DECODING_HW_DEVICE_TYPES"] = ","
        os.environ["QT_DISABLE_HW_TEXTURES_CONVERSION"] = "1"


def javascript_runtimes() -> dict[str, dict[str, str]]:
    runtimes = {}
    for name in ("deno", "node"):
        if name == "deno":
            # Resolve the package's executable directly, avoiding the Python
            # module launcher (which spawns another process on Windows).
            try:
                from deno import find_deno_bin
                binary = Path(os.fsdecode(find_deno_bin()))
                if binary.is_file():
                    runtimes[name] = {"path": str(binary)}
                    continue
            except (ImportError, OSError, RuntimeError):
                pass
        executable = name + (".exe" if os.name == "nt" else "")
        bundled = Path(sysconfig.get_path("scripts")) / executable
        path = str(bundled) if bundled.is_file() else shutil.which(name)
        if path:
            runtimes[name] = {"path": path}
    return runtimes


def readiness_issues() -> list[str]:
    """Check advertised capabilities; requires a Qt app, never plays media."""
    from PySide6.QtMultimedia import QMediaDevices, QMediaFormat

    issues = []
    media_format = QMediaFormat()
    mode = QMediaFormat.ConversionMode.Decode
    # Initialize Qt's backend as well as checking its actual decoder library.
    if not media_format.supportedFileFormats(mode):
        issues.append("Qt's media backend could not load. Run run.py --repair and check README.md for platform libraries.")
    try:
        missing = missing_decoders()
    except (OSError, AttributeError) as exc:
        missing = []
        issues.append(f"Unable to inspect FFmpeg decoders: {exc}. Run run.py --repair; see README.md for platform libraries.")
    if missing:
        issues.append(
            "Qt's FFmpeg backend is missing decoders: " + ", ".join(missing)
            + ". Run run.py --repair to reinstall the packaged playback libraries. "
            "On Linux, check the Qt platform dependencies linked in README.md."
        )
    if QMediaDevices.defaultAudioOutput().isNull():
        issues.append("No audio output device is available. Connect or enable an audio device and restart.")
    for name, config in javascript_runtimes().items():
        try:
            result = subprocess.run(
                [config["path"], "--version"], capture_output=True, text=True,
                timeout=10, check=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            match = re.search(r"(?:deno |v)(\d+)\.(\d+)\.(\d+)", result.stdout)
            minimum = (2, 3, 0) if name == "deno" else (22, 0, 0)
            if match and tuple(map(int, match.groups())) >= minimum:
                break
        except (OSError, subprocess.SubprocessError):
            continue
    else:
        issues.append("YouTube requires working Deno 2.3+ or Node.js 22+. Run run.py --repair to install Deno.")
    try:
        import requests
        import yt_dlp
        import yt_dlp_ejs
        import ytmusicapi
    except ImportError as exc:
        issues.append(f"Missing application dependency: {exc}. Run run.py --repair.")
    return issues


def missing_decoders() -> list[str]:
    # QMediaFormat's decoder list is approximated from encoders in Qt 6.11;
    # use FFmpeg's stable lookup API without opening or playing any media.
    import PySide6

    root = Path(PySide6.__file__).resolve().parent
    candidates = [*root.glob("avcodec-*.dll"), *root.glob("Qt/lib/libavcodec*.dylib"),
                  *root.glob("Qt/lib/libavcodec.so.*")]
    library = str(sorted(candidates)[0]) if candidates else ctypes.util.find_library("avcodec")
    if not library:
        raise OSError("FFmpeg shared library libavcodec was not found")
    codec = ctypes.CDLL(library)
    codec.avcodec_find_decoder_by_name.argtypes = [ctypes.c_char_p]
    codec.avcodec_find_decoder_by_name.restype = ctypes.c_void_p
    names = {
        "H264": ("h264",), "HEVC/H265": ("hevc",), "VP9": ("vp9", "libvpx-vp9"),
        "AV1": ("libdav1d", "libaom-av1", "av1"), "AAC": ("aac",),
        "MP3": ("mp3", "mp3float"), "Opus": ("opus", "libopus"),
        "Vorbis": ("vorbis", "libvorbis"), "FLAC": ("flac",), "PCM": ("pcm_s16le",),
    }
    return [label for label, decoders in names.items()
            if not any(codec.avcodec_find_decoder_by_name(name.encode("ascii")) for name in decoders)]
