#!/usr/bin/env python3
"""Measure the sync offset between two recordings of the same event.

Multi-camera convention (CRITICAL — the sign bit twice produced ~8-20s
misaligned renders):

    offset = face_time - screen_time

i.e. the SAME event is at face-time Tf and screen-time Ts → offset = Tf - Ts.
Pass the printed offset value DIRECTLY to mirror_edl.py --offset
(mirror_edl adds it: face range = base range + offset).

Sanity anchors (also printed):
  - last-speech alignment: last loud audio window in each source
  - optional --anchors: screen-source times to locate in the face source
    (4-5s windows, envelope xcorr over ±35s) → each anchor implies an offset

If any anchor disagrees with the curve by > 0.3s, or the curve is not flat
(> 0.2s spread), the offset is NOT a constant — do not mirror the EDL until
you know why (clock drift between the recorders is a real failure mode).

Usage:
    python helpers/measure_offset.py <screen.mp4> <face.mp4> [--anchors 75 200 300]
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

SR = 16000
FPS = 10
WIN = 20.0
STEP = 20.0
MARGIN = 15.0


def audio_env(path: Path) -> np.ndarray:
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(path),
         "-ac", "1", "-ar", str(SR), "-bitexact", "/tmp/measure_offset.wav"],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    w = wave.open("/tmp/measure_offset.wav")
    a = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(float)
    n = int(len(a) / (SR / FPS))
    return np.abs(a[: n * SR // FPS].reshape(-1, SR // FPS)).mean(axis=1)


def env_around(path: Path, ss: float, dur: float) -> np.ndarray:
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-ss", str(ss), "-t", str(dur), "-i", str(path),
         "-ac", "1", "-ar", str(SR), "-bitexact", "/tmp/measure_offset.wav"],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    w = wave.open("/tmp/measure_offset.wav")
    a = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(float)
    n = len(a) // (SR // FPS)
    return np.abs(a[: n * SR // FPS].reshape(-1, SR // FPS)).mean(axis=1)


def xcorr_lag(x: np.ndarray, y: np.ndarray) -> float:
    """Lag of y relative to x (seconds), via normalized xcorr over ±0.3s."""
    n = min(len(x), len(y))
    x, y = x[:n] - x[:n].mean(), y[:n] - y[:n].mean()
    xn = np.sqrt((x * x).sum()) or 1.0
    yn = np.sqrt((y * y).sum()) or 1.0
    best, bl = -1e18, 0
    for lag in range(-3, 4):
        if lag < 0:
            c = np.dot(x[:lag], y[-lag:])
        elif lag > 0:
            c = np.dot(x[lag:], y[:-lag])
        else:
            c = np.dot(x, y)
        c /= xn * yn
        if c > best:
            best, bl = c, lag
    return bl / FPS if best > 0.3 else float("nan")


def pair_corr(x: np.ndarray, y: np.ndarray) -> float:
    """Normalized correlation of two envelopes at lag ~0 (±0.3s, best)."""
    n = min(len(x), len(y))
    x, y = x[:n] - x[:n].mean(), y[:n] - y[:n].mean()
    xn = np.sqrt((x * x).sum()) or 1.0
    yn = np.sqrt((y * y).sum()) or 1.0
    best = -1e18
    for lag in range(-3, 4):
        if lag < 0:
            c = np.dot(x[:lag], y[-lag:])
        elif lag > 0:
            c = np.dot(x[lag:], y[:-lag])
        else:
            c = np.dot(x, y)
        best = max(best, c / (xn * yn))
    return best


def last_loud(path: Path) -> float | None:
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(path),
         "-ac", "1", "-ar", "8000", "-bitexact", "/tmp/measure_tail.wav"],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    w = wave.open("/tmp/measure_tail.wav")
    a = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(float)
    n = len(a) // 800
    e = np.abs(a[: n * 800].reshape(-1, 800)).max(axis=1)
    loud = np.where(e > 400)[0]
    return loud[-1] * 0.1 if len(loud) else None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("screen", type=Path, help="screen/main-camera recording")
    ap.add_argument("face", type=Path, help="face/alternate-camera recording")
    ap.add_argument("--anchors", type=float, nargs="+", default=[],
                    help="screen-source times (s) to locate in the face source as anchor checks")
    args = ap.parse_args()

    se = audio_env(args.screen)
    fe = audio_env(args.face)

    print("== offset curve (offset = face_time - screen_time) ==")
    offsets: list[float] = []
    corrs: list[float] = []
    t = 0.0
    while t + WIN < min(len(se), len(fe)) / FPS:
        i0, i1 = int(t * FPS), int((t + WIN) * FPS)
        best, bl, bc = -1e18, 0, 0.0
        for lag in range(-int(MARGIN * FPS), int(MARGIN * FPS) + 1):
            j0, j1 = i0 - lag, i1 - lag
            if j0 < 0 or j1 > len(fe):
                continue
            x = se[i0:i1] - se[i0:i1].mean()
            y = fe[j0:j1] - fe[j0:j1].mean()
            xn = np.sqrt((x * x).sum()) or 1.0
            yn = np.sqrt((y * y).sum()) or 1.0
            c = np.dot(x, y) / (xn * yn)
            if c > best:
                best, bl, bc = c, lag, c
        print(f"  t={t:6.1f}  offset={-bl / FPS:+7.2f}s  corr={bc:.2f}")
        if bc > 0.5:
            offsets.append(-bl / FPS)
            corrs.append(bc)
        t += STEP

    if not offsets:
        print("no windows with corr > 0.5 — sources do not align; check the recordings")
        sys.exit(1)

    med = float(np.median(offsets))
    spread = float(np.percentile(offsets, 90) - np.percentile(offsets, 10))
    print(f"\nmedian offset = {med:+.2f}s  (spread {spread:.2f}s over {len(offsets)} windows, "
          f"median corr {float(np.median(corrs)):.2f})")
    if spread > 0.2:
        print("WARNING: offset is NOT constant (clock drift between recorders) — "
              "a single mirror offset will misalign parts of the cut")

    # Anchor 0: last speech in both recordings must be the same event
    s_last = last_loud(args.screen)
    f_last = last_loud(args.face)
    if s_last is not None and f_last is not None:
        anchor = f_last - s_last
        print(f"anchor last-speech: screen {s_last:.1f}s, face {f_last:.1f}s → offset {anchor:+.2f}s")
        if abs(anchor - med) > 0.3:
            print(f"WARNING: last-speech anchor ({anchor:+.2f}s) disagrees with the curve ({med:+.2f}s)")

    # Optional anchors: locate screen-source words in the face source
    for a in args.anchors:
        s = env_around(args.screen, a, 5.0)
        best, best_ss = -1e18, 0.0
        for ss in np.arange(a - 15.0, a + 15.0, 0.5):
            f = env_around(args.face, ss, 5.0)
            c = pair_corr(s, f)
            if c > best:
                best, best_ss = c, ss
        implied = best_ss - a
        if best >= 0.5:
            status = "ok" if abs(implied - med) <= 0.3 else "MISMATCH"
            print(f"anchor screen@{a:.1f}s → face@{best_ss:.1f}s (corr {best:.2f}) → offset {implied:+.2f}s [{status}]")
        else:
            print(f"anchor screen@{a:.1f}s → not found (max corr {best:.2f} in ±15s) — check the recordings")

    print(f"\n→ pass --offset {med:+.2f} to mirror_edl.py")
    print("  (mirror_edl ADDS the offset: face range = base range + offset)")


if __name__ == "__main__":
    main()
