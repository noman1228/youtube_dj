"""Silent, disposable decoder process. Only a compact waveform leaves this process."""
from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path


def lower_priority() -> None:
    try:
        if os.name == "nt":
            import ctypes
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.GetCurrentProcess.restype = ctypes.c_void_p
            kernel.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
            kernel.SetPriorityClass(kernel.GetCurrentProcess(), 0x00004000)  # Below normal
        else:
            os.nice(10)
    except (OSError, AttributeError):
        pass


def main() -> int:
    lower_priority()
    # Import Qt after lowering priority, including its decoder threads.
    from PySide6.QtCore import QCoreApplication, QTimer, QUrl
    from PySide6.QtMultimedia import QAudioDecoder, QAudioFormat

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from app.waveform_analysis import BIN_COUNT, valid_waveform

    source, cache_path = map(Path, sys.argv[1:3])
    try:
        if cache_path.stat().st_size < 32_768:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if valid_waveform(cached):
                print(json.dumps(cached), flush=True)
                return 0
    except (OSError, ValueError, UnicodeError):
        pass

    app = QCoreApplication([])
    decoder = QAudioDecoder()
    audio_format = QAudioFormat()
    audio_format.setSampleRate(8000)
    audio_format.setChannelCount(1)
    audio_format.setSampleFormat(QAudioFormat.SampleFormat.Float)
    decoder.setAudioFormat(audio_format)
    # 50 ms RMS windows, bounded to 24 hours; never retain the full PCM audio.
    levels: list[float] = []
    square_sum = 0.0
    count = 0
    frames = 0

    def read_buffer() -> None:
        nonlocal square_sum, count, frames
        buffer = decoder.read()
        if not buffer.isValid():
            return
        fmt = buffer.format()
        if (fmt.sampleFormat() != QAudioFormat.SampleFormat.Float
                or fmt.sampleRate() != 8000 or fmt.channelCount() != 1):
            app.exit(1)
            return
        for value in memoryview(buffer.constData()).cast("f"):
            square_sum += float(value) ** 2
            count += 1
            frames += 1
            if count == 400:
                levels.append(min(1.0, math.sqrt(square_sum / count) * 2.4))
                square_sum, count = 0.0, 0
        if frames > 8000 * 24 * 60 * 60:
            app.exit(1)

    def finish() -> None:
        if count:
            levels.append(min(1.0, math.sqrt(square_sum / count) * 2.4))
        if not frames:
            app.exit(1)
            return
        bins = []
        for index in range(BIN_COUNT):
            start = index * len(levels) // BIN_COUNT
            end = max(start + 1, (index + 1) * len(levels) // BIN_COUNT)
            bins.append(round(max(levels[start:end]), 5))
        result = {"duration_ms": max(1, round(frames / 8)), "levels": bins}
        if not valid_waveform(result):
            app.exit(1)
            return
        serialized = json.dumps(result)
        temporary = cache_path.with_suffix(f".{os.getpid()}.tmp")
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(serialized, encoding="utf-8")
            temporary.replace(cache_path)
            # Keep the disk cache bounded; pruning runs only in this helper.
            entries = sorted(cache_path.parent.glob("*.json"), key=lambda item: item.stat().st_mtime)
            for old in entries[:-1000]:
                old.unlink(missing_ok=True)
        except OSError:
            pass  # Read-only/full cache must not prevent a usable waveform.
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
        print(serialized, flush=True)
        app.quit()

    decoder.bufferReady.connect(read_buffer)
    decoder.finished.connect(finish)
    decoder.error.connect(lambda _error: app.exit(1))
    decoder.setSource(QUrl.fromLocalFile(str(source.resolve())))
    QTimer.singleShot(0, decoder.start)
    QTimer.singleShot(300_000, lambda: app.exit(1))
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
