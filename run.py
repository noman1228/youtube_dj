"""Create a per-machine environment and launch EncoreMix on desktop platforms."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import struct
import subprocess
import sys
import venv


ROOT = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repair", action="store_true", help="Reinstall required packages and bundled libraries")
    parser.add_argument("--check", action="store_true", help="Check readiness without opening the mixer or playing media")
    parser.add_argument("--software-video", action="store_true", help="Decode video on the CPU to avoid GPU driver issues")
    args = parser.parse_args()
    if sys.version_info < (3, 11) or struct.calcsize("P") != 8:
        print("Install 64-bit Python 3.11 or newer, then run this launcher again.", file=sys.stderr)
        return 1
    environment = ROOT / ".venv"
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    try:
        if not python.is_file():
            venv.EnvBuilder(with_pip=True).create(environment)
        install = [str(python), "-m", "pip", "install"]
        if args.repair:
            install.extend(["--upgrade", "--force-reinstall"])
        subprocess.run([*install, "-r", str(ROOT / "requirements.txt")], cwd=ROOT, check=True)
        subprocess.run([str(python), "-m", "pip", "install", "--upgrade", "yt-dlp[default,deno]"], cwd=ROOT, check=True)
        subprocess.run([str(python), "-m", "pip", "check"], cwd=ROOT, check=True)
        flags = [flag for flag, enabled in (("--check", args.check), ("--software-video", args.software_video)) if enabled]
        return subprocess.call([str(python), str(ROOT / "main.py"), *flags], cwd=ROOT)
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"Setup failed: {exc}\nSee README.md for platform requirements; rerun with --repair.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
