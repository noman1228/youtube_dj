from __future__ import annotations

import math
import statistics
from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BeatInfo:
    bpm: float
    phase_ms: int
    confidence: float


class BeatTracker:
    """Small real-time onset tracker suitable for transition alignment."""

    def __init__(self) -> None:
        self._samples: deque[tuple[int, float]] = deque(maxlen=120)
        self._onsets: deque[tuple[int, float]] = deque(maxlen=64)
        self._last_time_ms = -1
        self._info: BeatInfo | None = None

    def reset(self) -> None:
        self._samples.clear()
        self._onsets.clear()
        self._last_time_ms = -1
        self._info = None

    def add_level(self, time_ms: int, level: float) -> BeatInfo | None:
        time_ms = max(0, time_ms)
        level = max(0.0, min(1.0, level))
        # Ignore samples replayed after a backwards seek. The estimate already
        # describes this track and remains useful for the active transition.
        if self._last_time_ms >= 0 and time_ms < self._last_time_ms - 100:
            return self._info

        recent = [value for stamp, value in self._samples if time_ms - stamp <= 650]
        baseline = statistics.fmean(recent) if recent else 0.0
        previous = self._samples[-1][1] if self._samples else 0.0
        self._samples.append((time_ms, level))
        self._last_time_ms = max(self._last_time_ms, time_ms)

        last_onset = self._onsets[-1][0] if self._onsets else -10_000
        threshold = max(0.14, baseline * 1.38)
        if level >= threshold and level - previous >= 0.045 and time_ms - last_onset >= 240:
            self._onsets.append((time_ms, max(0.01, level - baseline)))
            self._update_estimate()
        return self._info

    def info(self) -> BeatInfo | None:
        return self._info

    def _update_estimate(self) -> None:
        if len(self._onsets) < 4:
            return
        normalized_intervals: list[float] = []
        onset_list = list(self._onsets)
        for (earlier, _strength), (later, _next_strength) in zip(
            onset_list, onset_list[1:]
        ):
            interval = float(later - earlier)
            if interval <= 0:
                continue
            while interval < 333.0:
                interval *= 2.0
            while interval > 857.0:
                interval /= 2.0
            if 333.0 <= interval <= 857.0:
                normalized_intervals.append(interval)
        if len(normalized_intervals) < 3:
            return

        intervals = normalized_intervals[-16:]
        median_interval = statistics.median(intervals)
        deviations = [abs(value - median_interval) for value in intervals]
        relative_deviation = statistics.median(deviations) / max(1.0, median_interval)
        sample_confidence = min(1.0, len(intervals) / 8.0)
        regularity = max(0.0, 1.0 - relative_deviation * 5.0)
        confidence = sample_confidence * regularity
        bpm = 60_000.0 / median_interval
        phase_ms = round(self._strongest_grid_phase(onset_list, median_interval))
        self._info = BeatInfo(bpm=bpm, phase_ms=phase_ms, confidence=confidence)

    @staticmethod
    def _strongest_grid_phase(
        onsets: list[tuple[int, float]], interval_ms: float
    ) -> float:
        candidates = [time_ms % interval_ms for time_ms, _strength in onsets[-24:]]
        best_phase = candidates[-1]
        best_score = -1.0
        tolerance = interval_ms * 0.22
        for candidate in candidates:
            score = 0.0
            for time_ms, strength in onsets[-24:]:
                raw_distance = abs((time_ms % interval_ms) - candidate)
                distance = min(raw_distance, interval_ms - raw_distance)
                if distance <= tolerance:
                    score += strength * (1.0 - distance / tolerance)
            if score > best_score:
                best_score = score
                best_phase = candidate
        return best_phase


def normalized_target_bpm(source_bpm: float, target_bpm: float) -> float:
    if source_bpm <= 0 or target_bpm <= 0:
        return target_bpm
    candidates = (target_bpm / 2.0, target_bpm, target_bpm * 2.0)
    return min(candidates, key=lambda candidate: abs(math.log(candidate / source_bpm)))


def matched_playback_rate(source_bpm: float, source_rate: float, target_bpm: float) -> float:
    if source_bpm <= 0 or target_bpm <= 0:
        return 1.0
    effective_source_bpm = source_bpm * max(0.5, source_rate)
    grid_bpm = normalized_target_bpm(effective_source_bpm, target_bpm)
    return max(0.5, min(2.0, effective_source_bpm / grid_bpm))


def phase_error_cycles(
    source_position_ms: int,
    source_phase_ms: int,
    source_bpm: float,
    target_position_ms: int,
    target_phase_ms: int,
    target_grid_bpm: float,
) -> float:
    if source_bpm <= 0 or target_grid_bpm <= 0:
        return 0.0
    source_cycles = (source_position_ms - source_phase_ms) / (60_000.0 / source_bpm)
    target_cycles = (target_position_ms - target_phase_ms) / (
        60_000.0 / target_grid_bpm
    )
    return (source_cycles - target_cycles + 0.5) % 1.0 - 0.5


def bar_fade_seconds(bars: int, effective_bpm: float) -> float:
    if effective_bpm <= 0:
        return 0.0
    return max(1, bars) * 4.0 * 60.0 / effective_bpm


def delay_to_next_beat_ms(
    position_ms: int,
    phase_ms: int,
    native_bpm: float,
    playback_rate: float,
) -> int:
    if native_bpm <= 0:
        return 0
    interval_ms = 60_000.0 / native_bpm
    beats_elapsed = math.ceil((position_ms - phase_ms) / interval_ms)
    next_beat = phase_ms + max(0, beats_elapsed) * interval_ms
    media_delay = max(0.0, next_beat - position_ms)
    return round(media_delay / max(0.5, playback_rate))
