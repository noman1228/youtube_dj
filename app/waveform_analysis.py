from __future__ import annotations

import hashlib
import json
import math
import sys
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QObject, QProcess, QStandardPaths, QTimer, Signal


BIN_COUNT = 512
CACHE_VERSION = 1


def _worker_python() -> str:
    if sys.platform == "win32":
        # Use the same environment without creating a console for each analysis.
        windowless = Path(sys.executable).with_name("pythonw.exe")
        if windowless.is_file():
            return str(windowless)
    return sys.executable


def waveform_key(url: str, path: Path, local: bool) -> str:
    identity = [CACHE_VERSION, url]
    if local:
        stat = path.stat()
        identity.extend([str(path.resolve()), stat.st_size, stat.st_mtime_ns])
    return hashlib.sha256(json.dumps(identity).encode()).hexdigest()


def valid_waveform(data: object) -> bool:
    return (
        isinstance(data, dict)
        and isinstance(data.get("duration_ms"), int)
        and 0 < data["duration_ms"] <= 24 * 60 * 60 * 1000
        and isinstance(data.get("levels"), list)
        and len(data["levels"]) == BIN_COUNT
        and all(isinstance(v, (int, float)) and math.isfinite(v) and 0 <= v <= 1
                for v in data["levels"])
    )


@dataclass
class WaveformJob:
    key: str
    path: Path
    priority: int
    # Pin temporary prepared media until the decoder exits.
    source: object


class WaveformAnalysis(QObject):
    ready = Signal(str, object)

    def __init__(self, parent: QObject | None = None, cache_dir: Path | None = None) -> None:
        super().__init__(parent)
        self._cache_dir = cache_dir or Path(
            QStandardPaths.writableLocation(QStandardPaths.StandardLocation.CacheLocation)
        ) / "waveforms"
        self._wanted: dict[tuple[object, str], str] = {}
        self._pending: dict[str, WaveformJob] = {}
        self._cache: OrderedDict[str, dict] = OrderedDict()
        self._active: WaveformJob | None = None
        self._cancelling = False
        self._closing = False
        self._process = QProcess(self)
        self._process.finished.connect(self._finished)
        self._process.errorOccurred.connect(self._error)
        self._process.readyReadStandardError.connect(self._drain_errors)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._pump)
        self._timeout = QTimer(self)
        self._timeout.setSingleShot(True)
        self._timeout.setInterval(300_000)
        self._timeout.timeout.connect(self._process.kill)

    def request(self, owner: object, slot: str, job: WaveformJob) -> None:
        ticket = (owner, slot)
        if self._closing or self._wanted.get(ticket) == job.key:
            return
        self._wanted[ticket] = job.key
        if self._active is None or self._active.key != job.key or self._cancelling:
            previous = self._pending.get(job.key)
            if previous is None or previous.priority < job.priority:
                self._pending[job.key] = job
        self._prune()
        self._timer.start(0)

    def release(self, owner: object, slot: str | None = None) -> None:
        for ticket in tuple(self._wanted):
            if ticket[0] is owner and (slot is None or ticket[1] == slot):
                del self._wanted[ticket]
        self._prune()

    def _prune(self) -> None:
        wanted = set(self._wanted.values())
        self._pending = {key: job for key, job in self._pending.items() if key in wanted}
        if self._active and self._active.key not in wanted:
            self._cancelling = True
            self._process.kill()

    def _pump(self) -> None:
        if self._closing or self._active is not None:
            return
        while self._pending:
            job = max(self._pending.values(), key=lambda item: item.priority)
            del self._pending[job.key]
            if job.key in self._cache:
                self._cache.move_to_end(job.key)
                self.ready.emit(job.key, self._cache[job.key])
                continue
            self._active = job
            self._process.setProgram(_worker_python())
            self._process.setArguments([
                str(Path(__file__).with_name("waveform_worker.py")),
                str(job.path), str(self._cache_dir / f"{job.key}.json"),
            ])
            self._process.start()
            self._timeout.start()
            return

    def _drain_errors(self) -> None:
        # Decoder diagnostics must not accumulate or interrupt playback with a dialog.
        self._process.readAllStandardError()

    def _error(self, error: QProcess.ProcessError) -> None:
        if error == QProcess.ProcessError.FailedToStart:
            self._finished(-1, QProcess.ExitStatus.CrashExit)

    def _finished(self, code: int, status: QProcess.ExitStatus) -> None:
        self._timeout.stop()
        job, self._active = self._active, None
        self._cancelling = False
        output = bytes(self._process.readAllStandardOutput())
        if job and code == 0 and status == QProcess.ExitStatus.NormalExit:
            try:
                data = json.loads(output)
            except (ValueError, UnicodeError):
                data = None
            if valid_waveform(data):
                self._cache[job.key] = data
                while len(self._cache) > 128:
                    self._cache.popitem(last=False)
                if job.key in self._wanted.values():
                    self.ready.emit(job.key, data)
        if not self._closing:
            self._timer.start(0)

    def shutdown(self) -> None:
        self._closing = True
        self._timer.stop()
        self._timeout.stop()
        self._pending.clear()
        self._wanted.clear()
        if self._process.state() != QProcess.ProcessState.NotRunning:
            self._process.kill()
            self._process.waitForFinished(1000)
        self._active = None


_analysis: WaveformAnalysis | None = None


def waveform_analysis() -> WaveformAnalysis:
    global _analysis
    if _analysis is None:
        app = QCoreApplication.instance()
        _analysis = WaveformAnalysis(app)
        app.aboutToQuit.connect(_analysis.shutdown)
    return _analysis
