"""Detect screen-recorded / UI footage that needs stillimage-style encoding.

Screen captures (terminals, IDEs, review pages) are full of fine text that
generic x264 rate control blurs away. Camera footage (faces, rooms) is
naturally smooth. Laplacian variance of sampled frames separates the two by
an order of magnitude, so classification uses spatial detail alone — motion
is NOT a reliable signal (screen recordings often show fullscreen video).

Threshold 600 was calibrated on real footage: screen recordings 1000-3900,
talking-head / phone camera 200-330 (960px-wide grayscale frames).
"""

from __future__ import annotations

import struct
import subprocess
from pathlib import Path

_SAMPLE_COUNT = 6
_SAMPLE_WIDTH = 960
_LAPLACIAN_THRESHOLD = 600.0

_CACHE: dict[str, bool] = {}


def is_screen_content(video: Path) -> bool:
    """True if the video is dominated by high-detail static UI/text content."""
    key = str(video)
    if key in _CACHE:
        return _CACHE[key]
    result = _detect(video)
    _CACHE[key] = result
    return result


def _source_duration(video: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(video)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def _lapvar_of_frame(video: Path, t: float) -> float:
    """Laplacian variance of one frame, downscaled to _SAMPLE_WIDTH."""
    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(video),
         "-frames:v", "1", "-vf", f"scale={_SAMPLE_WIDTH}:-2,format=gray",
         "-f", "rawvideo", "-"],
        capture_output=True, check=True,
    )
    raw = out.stdout
    w = _SAMPLE_WIDTH
    h = len(raw) // w
    fr = struct.unpack(f"{len(raw)}B", raw)
    # Stride 2 keeps this fast in pure Python; threshold has a huge margin
    s = 0.0
    c = 0
    for y in range(1, h, 2):
        row, prow, nrow = y * w, (y - 1) * w, min(y + 1, h - 1) * w
        for x in range(1, w - 1, 2):
            lap = (
                4 * fr[row + x] - fr[row + x - 1] - fr[row + x + 1]
                - fr[prow + x] - fr[nrow + x]
            )
            s += lap * lap
            c += 1
    return s / c


def _detect(video: Path) -> bool:
    try:
        duration = _source_duration(video)
        laps = [
            _lapvar_of_frame(video, duration * (i + 0.5) / _SAMPLE_COUNT)
            for i in range(_SAMPLE_COUNT)
        ]
        return max(laps) > _LAPLACIAN_THRESHOLD
    except (subprocess.CalledProcessError, ValueError, ZeroDivisionError):
        return False
