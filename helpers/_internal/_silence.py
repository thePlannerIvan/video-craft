#!/usr/bin/env python3
"""Measured speech/silence, taken from the audio itself.

Why this exists
---------------
Every word-level transcript we use misplaces its boundaries, in different
directions:

  * 豆包 SeedASR onsets run **0.15-0.25s early** and its word ends run into the
    following silence, so its inter-word gaps read ~0.3s shorter than reality
    (「包」 at 67.87 where the audio's silence ends at 68.04);
  * ElevenLabs Scribe's gaps happen to match the audio closely, but its token
    spans are unreliable in the documented way (it merges 「。muji，」 into one
    2.9s token) and its onsets drift late.

A cut edge checked against either transcript's word frame is therefore wrong in
both directions: a correct cut judged as "inside a word", and a cut that really
does clip speech judged clean. The audio is the only ground truth for "is there
speech at this instant", so the edit-side gate measures a 10ms RMS envelope and
checks cut edges against *that*.

This module is the single implementation of that measurement. It is deliberately
dependency-free (stdlib + ffmpeg) so the gate can run anywhere the rest of
`helpers/` runs.
"""
from __future__ import annotations

import array
import math
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

# Frame length. 10ms is short enough to sit inside a real inter-word gap and long
# enough that a single frame is not dominated by one sample.
HOP_S = 0.010
SAMPLE_RATE = 16_000
# The threshold is adaptive: the 5th percentile of frame level is the room floor,
# and speech must clear it by this much. Clamped, because a very quiet recording
# would otherwise put the threshold below its own noise and call everything silent.
NOISE_PERCENTILE = 0.05
NOISE_MARGIN_DB = 10.0
THRESHOLD_MIN_DB = -52.0
THRESHOLD_MAX_DB = -35.0
# Silence runs closer than this are one run; runs shorter than this are ignored
# when *placing* a boundary, but still count for the "is this instant silent" test.
MERGE_GAP_S = 0.12
MIN_RUN_S = 0.12
# A cut edge may sit this close to a measured silence run and still count as inside
# it — the envelope is quantised to 10ms frames, so a boundary cannot land exactly
# on a run's edge.
EDGE_TOLERANCE_S = 0.02


@dataclass
class SilenceMap:
    """Per-frame RMS level of a media file, plus the silence runs it implies."""

    path: Path
    threshold_db: float
    floor_db: float
    hop_s: float
    levels_db: list[float] = field(repr=False)
    runs: list[tuple[float, float]]

    def db_at(self, t: float) -> float:
        """Frame level at time `t` (seconds), clamped to the measured range."""
        if not self.levels_db:
            return -99.0
        i = int(round(t / self.hop_s))
        i = max(0, min(len(self.levels_db) - 1, i))
        return self.levels_db[i]

    def run_at(self, t: float, min_run_s: float = 0.0) -> tuple[float, float] | None:
        """The silence run containing `t`, if any."""
        for s0, s1 in self.runs:
            if s1 - s0 < min_run_s:
                continue
            if s0 - EDGE_TOLERANCE_S <= t <= s1 + EDGE_TOLERANCE_S:
                return (s0, s1)
        return None

    def is_silent(self, t: float, min_run_s: float = 0.03) -> bool:
        """True when `t` sits in a measured silence run of at least `min_run_s`.

        The default is deliberately shorter than MIN_RUN_S: a cut placed in a real
        but brief inter-word dip is legitimate, and rejecting it would push editors
        back onto the transcript frames this module exists to distrust.
        """
        return self.run_at(t, min_run_s) is not None

    def nearest_run(self, t: float) -> tuple[float, float, float] | None:
        """(start, end, distance) of the closest silence run, for error messages."""
        best = None
        for s0, s1 in self.runs:
            d = 0.0 if s0 <= t <= s1 else min(abs(t - s0), abs(t - s1))
            if best is None or d < best[2]:
                best = (s0, s1, d)
        return best


_CACHE: dict[tuple[str, int, int], SilenceMap] = {}


def measure(media_path: Path | str, *, hop_s: float = HOP_S,
            threshold_db: float | None = None) -> SilenceMap:
    """Measure a media file's silence runs. Cached per (path, size, mtime).

    Raises RuntimeError with an actionable message when ffmpeg is missing or the
    file cannot be decoded — callers that can degrade (the EDL gate) should catch
    it and say the measured check was skipped, never silently pass.
    """
    path = Path(media_path)
    if not path.exists():
        raise RuntimeError(f"找不到媒体文件：{path}")
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("PATH 上没有 ffmpeg，无法测量静音")
    stat = path.stat()
    key = (str(path.resolve()), stat.st_size, int(stat.st_mtime))
    if threshold_db is None and key in _CACHE:
        return _CACHE[key]

    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "1",
         "-ar", str(SAMPLE_RATE), "-f", "s16le", "-"],
        capture_output=True)
    if proc.returncode != 0 or not proc.stdout:
        detail = proc.stderr.decode("utf-8", "replace").strip().splitlines()[-1:] or [""]
        raise RuntimeError(f"ffmpeg 读不出音频：{path.name}（{detail[0][:120]}）")

    pcm = array.array("h")
    pcm.frombytes(proc.stdout[: len(proc.stdout) // 2 * 2])
    hop = max(1, int(round(hop_s * SAMPLE_RATE)))
    levels: list[float] = []
    for i in range(0, len(pcm) - hop, hop):
        seg = pcm[i:i + hop]
        rms = math.sqrt(sum(x * x for x in seg) / len(seg))
        levels.append(20 * math.log10(rms / 32768) if rms > 0 else -99.0)
    if not levels:
        raise RuntimeError(f"音频为空：{path.name}")

    if threshold_db is None:
        floor = sorted(levels)[int(len(levels) * NOISE_PERCENTILE)]
        threshold_db = max(min(floor + NOISE_MARGIN_DB, THRESHOLD_MAX_DB),
                           THRESHOLD_MIN_DB)
    else:
        floor = sorted(levels)[int(len(levels) * NOISE_PERCENTILE)]

    runs: list[list[float]] = []
    i = 0
    while i < len(levels):
        if levels[i] < threshold_db:
            j = i
            while j < len(levels) and levels[j] < threshold_db:
                j += 1
            runs.append([i * hop_s, j * hop_s])
            i = j
        else:
            i += 1
    merged: list[list[float]] = []
    for r in runs:
        if merged and r[0] - merged[-1][1] < MERGE_GAP_S:
            merged[-1][1] = r[1]
        else:
            merged.append(r)

    smap = SilenceMap(
        path=path,
        threshold_db=round(threshold_db, 2),
        floor_db=round(floor, 2),
        hop_s=hop_s,
        levels_db=levels,
        runs=[(round(a, 3), round(b, 3)) for a, b in merged if b - a >= MIN_RUN_S],
    )
    if threshold_db is None:
        _CACHE[key] = smap
    return smap
