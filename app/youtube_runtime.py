"""Keep yt-dlp's background helpers from creating Windows consoles."""
from __future__ import annotations

import functools
import subprocess
import sys
import threading


_lock = threading.Lock()


def configure_youtube_processes() -> None:
    if sys.platform != "win32":
        return
    from yt_dlp.utils import Popen

    # yt-dlp passes SW_HIDE, but that still allows a console to be allocated.
    # Update its shared class once so existing imports in runtime discovery,
    # challenge solvers and executable probes all get CREATE_NO_WINDOW.
    # Leave Python's global subprocess implementation untouched.
    with _lock:
        if getattr(Popen.__init__, "_encoremix_hidden", False):
            return
        original = Popen.__init__

        @functools.wraps(original)
        def hidden_init(self, *args, **kwargs):
            kwargs["creationflags"] = kwargs.get("creationflags", 0) | subprocess.CREATE_NO_WINDOW
            original(self, *args, **kwargs)

        hidden_init._encoremix_hidden = True
        Popen.__init__ = hidden_init
