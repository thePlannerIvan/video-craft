#!/usr/bin/env python3
"""A transparent video can be opaque, and both ffprobe and the encoder will say otherwise.

Why this exists
---------------
"Does this file really carry transparency?" cannot be answered from metadata.
Measured on this machine (2026-09-22, ffmpeg 8.1.2, one transparent PNG source):

| written as              | ffprobe pix_fmt   | decode a frame back | truth        |
|-------------------------|-------------------|---------------------|--------------|
| ProRes 4444 .mov        | yuva444p12le      | RGBA, alpha 0       | has alpha    |
| HEVC+alpha .mov (VT)    | yuv420p (!)       | RGBA, alpha 0       | has alpha    |
| QuickTime RLE .mov      | argb              | RGBA, alpha 0       | has alpha    |
| H.264 .mp4              | yuv420p           | RGB, alpha 255      | no alpha     |
| VP9 .webm               | yuv420p           | RGB, alpha 255      | no alpha     |

`pix_fmt` is wrong in BOTH directions: it under-reports HEVC+alpha, and it is
useless for proving loss. A VP9 encode even advertises `yuva420p` in the output
stream header and records `alpha_mode=1` in the container while the round trip
still returns opaque pixels — so "the encoder says it supports alpha" is not
evidence either. The only trustworthy verdict is to extract the alpha plane and
look at its values.

The verdict is the SPAN of that plane, not absolute levels: `alphaextract` output
can come back range-converted, so an absolute threshold (e.g. "max > 192") can
false-fail a good file. A real alpha channel has both transparent and opaque
pixels somewhere → `max − min` is large.

What sampling cannot prove (2026-09-25)
---------------------------------------
A 565 s 花字 layer that is transparent almost everywhere was reported FAIL at
`--samples 5` and OK at `--samples 9`: every sampled frame happened to land in a
transparent gap. Two things follow, and both are implemented here.

1. Density follows duration. The default is now ~one sample per 15 s, floor 8,
   ceiling 40 — five uniform samples of a long layer is not a measurement.
2. "Every sampled plane is constant" only means the encode dropped alpha when
   that constant plane is OPAQUE. A constant plane at 0 is transparency being
   preserved faithfully; it just proves nothing about contrast. That case is
   reported as INCONCLUSIVE, not as a lost alpha channel.

Being honest about the limit matters because it cannot be engineered away: no
finite sample can prove the absence of a visible frame. What can be proven is
that the plane exists and is not opaque.

Usage
-----
    check_alpha.py <video> [--samples N] [--json]
    check_alpha.py overlay.mov

Exit code 0 = transparency is actually present, 1 = it is not (no alpha channel
at all, or an opaque plane), 2 = INCONCLUSIVE (the samples cannot tell). Run this
on every alpha layer BEFORE handing it to whoever composites it: a dropped alpha
channel is a silent failure — exit code 0 from the encoder, a playable file, and
a black box over the footage.
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path

# A plane spanning less than this is a constant plane, i.e. no usable transparency.
MIN_SPAN = 16
# ...but a CONSTANT plane only proves lost alpha when it is opaque. A constant
# plane at 0 has transparency; it simply has no contrast to measure.
OPAQUE_FLOOR = 250
# Sampling density: ~one probe per 15 s of runtime, never fewer than 8 (a short
# overlay gets a dense sweep for free) and never more than 40 (each probe is a
# seek plus one decoded frame).
SECONDS_PER_SAMPLE = 15.0
MIN_SAMPLES = 8
MAX_SAMPLES = 40

EXIT = {"OK": 0, "FAIL": 1, "INCONCLUSIVE": 2}


def probe(path: Path) -> tuple[dict, float]:
    info = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                           "-show_entries", "stream=codec_name,pix_fmt,width,height,avg_frame_rate",
                           "-show_entries", "format=duration", "-of", "json", str(path)],
                          capture_output=True, text=True).stdout
    try:
        d = json.loads(info)
        st = d["streams"][0]
        dur = float(d["format"]["duration"])
    except (json.JSONDecodeError, KeyError, IndexError, ValueError):
        st, dur = {}, 0.0
    return st, dur


def alpha_plane(path: Path, t: float) -> tuple[int, int, float] | tuple[None, str]:
    """Extract the alpha plane at time t.

    Returns (min, max, dark_fraction) or (None, reason).
    """
    r = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(path),
         "-frames:v", "1", "-vf", "alphaextract,format=gray",
         "-f", "rawvideo", "-pix_fmt", "gray", "-bitexact", "-"],
        capture_output=True,
    )
    if r.returncode != 0:
        # `alphaextract` fails outright on a frame with no alpha plane
        # ("Requested planes not available"), e.g. an H.264/VP9 encode that
        # dropped it — that is the loud case, not the quiet one.
        return None, "no alpha channel"
    if not r.stdout:
        return None, "no frame at this timestamp"
    data = r.stdout
    lo, hi = min(data), max(data)
    mid = lo + (hi - lo) // 2
    dark = sum(1 for b in data if b <= mid) / len(data)
    return lo, hi, dark


def sample_count(requested: int | None, dur: float) -> int:
    """How many frames to probe: explicit `--samples` wins, else scale with length."""
    if requested:
        return max(1, requested)
    if dur <= 0.05:
        return 1
    return max(MIN_SAMPLES, min(MAX_SAMPLES, int(math.ceil(dur / SECONDS_PER_SAMPLE))))


def main() -> None:
    ap = argparse.ArgumentParser(description="Verify that a video really carries an alpha channel")
    ap.add_argument("video", type=Path)
    ap.add_argument("--samples", type=int, default=None,
                    help=f"how many frames to sample (default: one per {SECONDS_PER_SAMPLE:g}s, "
                         f"min {MIN_SAMPLES}, max {MAX_SAMPLES})")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    path: Path = args.video
    if not path.exists():
        sys.exit(f"FAIL: {path} does not exist")

    info, dur = probe(path)
    n = sample_count(args.samples, dur)
    # Sample strictly inside the file: the last frame of a short clip is easy to miss
    # and would be misreported as "no alpha plane".
    times = [max(0.0, (dur * (i + 0.5) / n) - 0.02) for i in range(n)] if dur > 0.05 else [0.0]

    rows = []
    for t in times:
        res = alpha_plane(path, t)
        if len(res) == 2 and res[0] is None:
            rows.append({"t": round(t, 3), "state": res[1], "span": None})
        else:
            lo, hi, dark = res
            rows.append({"t": round(t, 3), "state": "plane", "min": lo, "max": hi,
                         "span": hi - lo, "dark_fraction": round(dark, 4)})

    planes = [r for r in rows if r["state"] == "plane"]
    opaque_planes = [r for r in planes if r["min"] >= OPAQUE_FLOOR]
    if any(r["span"] >= MIN_SPAN for r in planes):
        verdict = "OK"
        reason = "transparency present"
    elif all(r["state"] == "no alpha channel" for r in rows):
        verdict = "FAIL"
        reason = "no alpha channel in the file at all"
    elif not planes:
        verdict = "FAIL"
        reason = "could not read any frame"
    elif opaque_planes:
        verdict = "FAIL"
        reason = (f"alpha plane is constant and opaque (span < {MIN_SPAN}, min >= {OPAQUE_FLOOR}) "
                  "— the encode dropped transparency")
    else:
        verdict = "INCONCLUSIVE"
        reason = (f"all {len(planes)} sampled planes are constant but NOT opaque — these samples "
                  "cannot demonstrate transparency (no visible frame was hit) and cannot prove it "
                  "was lost either. The alpha plane exists; re-run with more samples, or measure a "
                  "timestamp where the layer is actually on screen")

    payload = {
        "file": str(path), "verdict": verdict, "reason": reason,
        "samples": n,
        "codec": info.get("codec_name"), "pix_fmt": info.get("pix_fmt"),
        "size": [info.get("width"), info.get("height")], "duration": round(dur, 3),
        "frames": rows,
        "note": "pix_fmt is advisory only; the verdict comes from the extracted alpha plane span",
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        sys.exit(EXIT[verdict])

    print(f"透明通道体检：{path.name}  {info.get('width')}x{info.get('height')}  "
          f"{info.get('codec_name')}  pix_fmt={info.get('pix_fmt')}  {dur:.2f}s  "
          f"（采样 {n} 帧）")
    for r in rows:
        if r["state"] == "plane":
            print(f"  t={r['t']:<8} alpha 平面 [{r['min']:>3},{r['max']:>3}]  "
                  f"跨度 {r['span']:>3}  低调像素 {r['dark_fraction'] * 100:5.1f}%")
        else:
            print(f"  t={r['t']:<8} {r['state']}")
    print(f"  → {reason}")
    print("  注：pix_fmt 只是参考值——HEVC+alpha 会报 yuv420p，而 VP9 会报 alpha 却实际丢失")
    print("  注：全采样都恒定且不透明才是「丢了透明」；恒定但透明只是这几次没抽到可见帧")
    print(f"RESULT: {verdict}")
    sys.exit(EXIT[verdict])


if __name__ == "__main__":
    main()
