"""Safely update EncoreMix from its canonical GitHub repository."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Sequence


SOURCE_REPOSITORY = "https://github.com/noman1228/youtube_dj.git"
SOURCE_BRANCH = "main"
PROJECT_DIR = Path(__file__).resolve().parent


class UpdateError(RuntimeError):
    """Raised when the update cannot be completed safely."""


def run_git(*args: str, capture: bool = False) -> str:
    command = ["git", *args]
    try:
        result = subprocess.run(
            command,
            cwd=PROJECT_DIR,
            check=True,
            text=True,
            capture_output=capture,
        )
    except FileNotFoundError as exc:
        raise UpdateError("Git was not found. Install Git for Windows and try again.") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip() if capture else ""
        message = f"Git command failed: {' '.join(command)}"
        if detail:
            message = f"{message}\n{detail}"
        raise UpdateError(message) from exc
    return result.stdout.strip() if capture else ""


def ensure_update_is_safe() -> None:
    if shutil.which("git") is None:
        raise UpdateError("Git was not found. Install Git for Windows and try again.")
    if not (PROJECT_DIR / ".git").exists():
        raise UpdateError(
            "This copy is not a Git checkout. Clone the source repository before using "
            "the updater."
        )

    changes = run_git("status", "--porcelain", "--untracked-files=all", capture=True)
    if changes:
        raise UpdateError(
            "Local changes were found, so the updater stopped to avoid overwriting them.\n"
            "Commit, stash, or remove these files first:\n"
            f"{changes}"
        )


def dependency_python() -> Path:
    venv_python = PROJECT_DIR / ".venv" / "Scripts" / "python.exe"
    return venv_python if venv_python.exists() else Path(sys.executable)


def refresh_dependencies() -> None:
    requirements = PROJECT_DIR / "requirements.txt"
    if not requirements.exists():
        return

    python = dependency_python()
    print(f"Refreshing dependencies with {python} ...")
    try:
        subprocess.run(
            [str(python), "-m", "pip", "install", "-r", str(requirements)],
            cwd=PROJECT_DIR,
            check=True,
        )
        subprocess.run(
            [str(python), "-m", "pip", "install", "--upgrade", "yt-dlp[default]"],
            cwd=PROJECT_DIR,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        raise UpdateError(
            "The source was updated, but dependency installation failed.\n"
            "Retry by running run_windows.bat."
        ) from exc


def update(*, check_only: bool, skip_dependencies: bool) -> None:
    ensure_update_is_safe()
    before = run_git("rev-parse", "HEAD", capture=True)

    print(f"Checking {SOURCE_REPOSITORY} ({SOURCE_BRANCH}) ...")
    run_git("fetch", "--quiet", SOURCE_REPOSITORY, SOURCE_BRANCH)
    available = run_git("rev-parse", "FETCH_HEAD", capture=True)

    if before == available:
        print("EncoreMix is already up to date.")
        if not check_only and not skip_dependencies:
            refresh_dependencies()
        return

    common_revision = run_git("merge-base", before, available, capture=True)
    if common_revision == available:
        print("This checkout is ahead of the source repository; no update is needed.")
        return
    if common_revision != before:
        raise UpdateError(
            "The local checkout and source repository have diverged. The updater only "
            "performs safe fast-forward updates; resolve the Git branches manually."
        )

    if check_only:
        commits = run_git(
            "rev-list", "--count", f"{before}..{available}", capture=True
        )
        print(f"An update is available ({commits} new commit(s)).")
        return

    print("Installing update ...")
    run_git("merge", "--ff-only", available)

    short_revision = run_git("rev-parse", "--short", "HEAD", capture=True)
    print(f"Updated EncoreMix to {short_revision}.")
    if not skip_dependencies:
        refresh_dependencies()
    print("Update complete. You can start EncoreMix normally.")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Update EncoreMix from its canonical GitHub repository."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="check whether an update exists without installing it",
    )
    parser.add_argument(
        "--skip-dependencies",
        action="store_true",
        help="do not refresh Python packages after updating",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        update(check_only=args.check, skip_dependencies=args.skip_dependencies)
    except UpdateError as exc:
        print(f"Update failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
