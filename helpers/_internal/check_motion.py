#!/usr/bin/env python3
"""A rendered composition that was supposed to move can be perfectly static.

Why this exists
---------------
A HyperFrames composition whose timeline never registers still renders: the
producer screenshots the page, the encode succeeds, the exit code is 0, and the
file is a still image with a video wrapper. The 2026-09-21 run shipped five
"animations" this way — a `ReferenceError` in the composition script (the
timeline was registered *after* the code that used `tl`) meant the paused
timeline never existed, and nothing in the pipeline noticed. The tell is cheap:
sample the file at several times and compare pixels. A clip that claims to
animate but does not change is a HARD failure.

Usage
-----
    check_motion.py <video> [--samples 5] [--min-change 1.0] [--expect-still]
    check_motion.py <video> --json

`--min-change` is the mean absolute per-pixel difference (0-255 scale) between
consecutive samples that counts as motion. Talking heads and screen recordings
sit well above 1.0; text-on-dark motion graphics usually sit around 1-5. A still
frame is ~0.0. Pass `--expect-still` for screens that are meant to hold (a
static page you deliberately hold for 20 s) — then motion is the warning.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", str(path)], capture_output=True, text=True).stdout.strip()
    return float(out)


def gray_frame(path: Path, t: float, w: int = 160, h: int = 90) -> bytes:
    return subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(path),
                           "-frames:v", "1", "-vf", f"scale={w}:{h},format=gray",
                           "-f", "rawvideo", "-bitexact", "-"], capture_output=True).stdout


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--samples", type=int, default=5)
    ap.add_argument("--min-change", type=float, default=1.0)
    ap.add_argument("--expect-still", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    p = Path(a.video)
    if not p.exists():
        print(f"not found: {p}", file=sys.stderr)
        return 2
    dur = duration(p)
    n = max(2, a.samples)
    times = [dur * (i + 1) / (n + 1) for i in range(n)]
    frames = [gray_frame(p, t) for t in times]
    frames = [f for f in frames if f]
    diffs = []
    for x, y in zip(frames, frames[1:]):
        if len(x) != len(y) or not x:
            continue
        diffs.append(round(sum(abs(i - j) for i, j in zip(x, y)) / len(x), 3))

    peak = max(diffs) if diffs else 0.0
    moving = peak >= a.min_change
    hard, warn = [], []
    if a.expect_still:
        if moving:
            warn.append(f"声明为静帧，但帧间差异 {peak} ≥ {a.min_change}（可能是动画没关）")
    else:
        if not moving:
            hard.append(f"声明为动画，帧间差异峰值仅 {peak}（阈值 {a.min_change}）——"
                        "很可能是合成的时间轴没注册，渲出来是静止帧")
    size_mb = p.stat().st_size / 1e6
    report = {"file": str(p), "duration": round(dur, 3), "samples": [round(t, 2) for t in times],
              "diffs": diffs, "peak": peak, "min_change": a.min_change,
              "expect": "still" if a.expect_still else "moving",
              "size_mb": round(size_mb, 2), "hard": hard, "warn": warn}
    if a.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"动效体检：{p.name}  {dur:.2f}s  {size_mb:.1f}MB  {len(diffs)} 次采样")
        print(f"  帧间差异 {diffs}  峰值 {peak}  （阈值 {a.min_change}）")
        for m in warn:
            print(f"  · {m}")
        for m in hard:
            print(f"  ✗ {m}")
        print("RESULT:", "OK" if not hard else "FAIL")
    return 0 if not hard else 1


if __name__ == "__main__":
    raise SystemExit(main())
