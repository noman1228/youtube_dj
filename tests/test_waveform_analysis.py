from __future__ import annotations

import math
import os
import struct
import tempfile
import time
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QProcess, QTimer
from PySide6.QtWidgets import QApplication

from app.media import QtMediaDeckEngine
from app.deck_widget import DeckWidget
from app.models import Track
from app.waveform_analysis import WaveformAnalysis, WaveformJob, valid_waveform, waveform_key
from app.waveform_widget import WaveformWidget


class WaveformAnalysisTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.source = self.root / "quiet then loud.wav"
        with wave.open(str(self.source), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(8000)
            output.writeframes(b"".join(
                struct.pack("<h", round((2000 if i < 8000 else 12000) * math.sin(i * math.tau * 440 / 8000)))
                for i in range(16000)
            ))
        self.service = WaveformAnalysis(cache_dir=self.root / "cache")
        self.addCleanup(self.service.shutdown)
        self.key = waveform_key(self.source.as_uri(), self.source, True)

    def wait_until(self, predicate, timeout: float = 15) -> None:
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
            time.sleep(0.005)
        self.assertTrue(predicate(), "Timed out waiting for waveform helper")

    def job(self, key: str | None = None, priority: int = 1) -> WaveformJob:
        return WaveformJob(key or self.key, self.source, priority, self.source)

    def test_silent_decode_keeps_event_loop_running_and_reuses_disk_cache(self) -> None:
        results = []
        ticks = []
        timer = QTimer()
        timer.setInterval(10)
        timer.timeout.connect(lambda: ticks.append(time.monotonic()))
        timer.start()
        self.addCleanup(timer.stop)
        self.service.ready.connect(lambda key, data: results.append((key, data)))
        self.service.request(self, "current", self.job())
        self.wait_until(lambda: bool(results))
        data = results[0][1]
        self.assertTrue(valid_waveform(data))
        self.assertAlmostEqual(data["duration_ms"], 2000, delta=50)
        self.assertGreater(sum(data["levels"][256:]), sum(data["levels"][:256]) * 4)
        self.assertGreater(len(ticks), 2)
        self.assertTrue((self.root / "cache" / f"{self.key}.json").is_file())

        # A new service has no memory cache. A missing source proves the worker
        # returned the persisted waveform without decoding again.
        second = WaveformAnalysis(cache_dir=self.root / "cache")
        self.addCleanup(second.shutdown)
        second.ready.connect(lambda key, cached: results.append((key, cached)))
        self.source.unlink()
        second.request(self, "current", self.job())
        self.wait_until(lambda: len(results) == 2)
        self.assertEqual(results[0], results[1])

    def test_current_priority_deduplication_and_stale_requests(self) -> None:
        other = object()
        self.service.request(self, "next", self.job("next", 0))
        self.service.request(self, "current", self.job("current", 1))
        self.service.request(other, "current", self.job("current", 1))
        self.service.release(self, "next")
        with patch.object(self.service._process, "start"):
            self.service._pump()
        self.assertEqual(self.service._active.key, "current")
        self.assertEqual(self.service._pending, {})
        self.service.release(self)
        self.assertIn("current", self.service._wanted.values())

    def test_local_file_modification_changes_cache_identity(self) -> None:
        self.source.write_bytes(b"changed")
        self.assertNotEqual(self.key, waveform_key(self.source.as_uri(), self.source, True))

    def test_corrupt_cache_is_rebuilt_and_failure_does_not_block_next_job(self) -> None:
        self.service._cache_dir.mkdir()
        (self.service._cache_dir / f"{self.key}.json").write_text('{"levels": [NaN]}')
        results = []
        self.service.ready.connect(lambda key, data: results.append(key))
        self.service.request(self, "bad", WaveformJob("bad", self.root / "missing.wav", 2, None))
        self.service.request(self, "current", self.job())
        self.wait_until(lambda: bool(results))
        self.assertEqual(results, [self.key])

    def test_switching_tracks_ignores_old_waveform_and_uses_next_local_file(self) -> None:
        with patch("app.media.waveform_analysis", return_value=self.service):
            engine = QtMediaDeckEngine(capture_waveform=True)
        self.addCleanup(engine.deleteLater)
        results = []
        engine.waveformReady.connect(results.append)
        first = Track("First", self.source.as_uri(), source="Local file")
        second = Track("Second", "file:///different.wav", source="Local file")
        engine._request_waveform(first, first.webpage_url, "current")
        with patch.object(engine, "_begin_resolve"):
            engine.load(second)
        engine._waveform_ready(self.key, {"duration_ms": 2000, "levels": [0.2] * 512})
        self.assertEqual(results, [])
        engine.prefetch(first)
        self.assertIn(self.key, self.service._wanted.values())

    def test_full_overview_survives_duration_changes_without_affecting_playhead(self) -> None:
        widget = WaveformWidget("left")
        self.addCleanup(widget.deleteLater)
        widget.reset(2000)
        widget.set_position(500, 2000)
        levels = [i / 512 for i in range(512)]
        widget.set_overview({"duration_ms": 2000, "levels": levels})
        widget.add_sample(100, 1.0)
        widget.set_position(600, 2010)
        self.assertEqual(widget._levels, levels)
        self.assertTrue(all(widget._known))
        self.assertEqual(widget._position_ms, 600)
        widget.reset(3000)
        self.assertFalse(any(widget._known))
        self.assertIsNone(widget._overview)

    def test_shutdown_stops_running_helper(self) -> None:
        self.service.request(self, "current", self.job())
        self.service._pump()
        self.service.shutdown()
        self.assertEqual(self.service._process.state(), QProcess.ProcessState.NotRunning)
        self.assertIsNone(self.service._active)

    def test_cancelled_active_track_can_be_requested_again(self) -> None:
        results = []
        self.service.ready.connect(lambda key, data: results.append(key))
        self.service.request(self, "current", self.job())
        self.service._pump()
        self.service.release(self)
        self.service.request(self, "current", self.job())
        self.wait_until(lambda: bool(results))
        self.assertEqual(results, [self.key])

    def test_repeated_local_prefetch_keeps_existing_analysis(self) -> None:
        with patch("app.media.waveform_analysis", return_value=self.service):
            engine = QtMediaDeckEngine(capture_waveform=True)
        self.addCleanup(engine.deleteLater)
        track = Track("Local", self.source.as_uri(), source="Local file")
        engine.prefetch(track)
        self.service._pump()
        with patch.object(self.service._process, "kill") as kill:
            engine.prefetch(track)
            kill.assert_not_called()

    def test_empty_deck_ignores_late_waveform(self) -> None:
        with patch("app.media.waveform_analysis", return_value=self.service):
            deck = DeckWidget("left")
        self.addCleanup(deck.deleteLater)
        deck.engine.waveformReady.emit({"duration_ms": 2000, "levels": [0.5] * 512})
        self.assertFalse(any(deck.waveform._known))
        track = Track("Local", self.source.as_uri(), source="Local file")
        deck.tracks = [track]
        deck.current_index = 0
        deck.engine._track = track
        deck.engine.waveformReady.emit({"duration_ms": 2000, "levels": [0.5] * 512})
        self.assertTrue(all(deck.waveform._known))


if __name__ == "__main__":
    unittest.main()
