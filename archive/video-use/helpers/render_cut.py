#!/usr/bin/env python3
"""Render an EDL that carries speed/mute fields into a single MP4.

Each range is extracted separately with 30ms audio fades, sped segments use
setpts (video) and are muted with an anullsrc track, then all segments are
losslessly concatenated.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from screen_detect import is_screen_content  # same directory


def run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check and proc.returncode != 0:
        print(proc.stdout.decode(errors="replace"))
        print(proc.stderr.decode(errors="replace"))
        sys.exit(f"command failed: {' '.join(map(str, cmd[:8]))} …")
    return proc


def resolve(p: str, base: Path) -> Path:
    q = Path(p)
    return q if q.is_absolute() else (base / q).resolve()


def audio_atempo(speed: float) -> list[str]:
    if speed <= 1.0:
        return []
    filters = []
    remaining = speed
    while remaining > 2.0:
        filters.append("atempo=2.0")
        remaining /= 2.0
    filters.append(f"atempo={remaining:.6f}")
    return filters


def extract_segment(
    source: Path,
    start: float,
    raw_dur: float,
    speed: float,
    mute: bool,
    out_path: Path,
    quality: str,
) -> None:
    out_dur = raw_dur / speed
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if quality == "draft":
        preset, crf, tune = "ultrafast", "28", None
    elif quality == "preview":
        preset, crf, tune = "medium", "22", None
    elif is_screen_content(source):
        # Screen recordings (fine text/UI) need stillimage tuning — generic
        # x264 rate control blurs small text even at moderate CRF.
        preset, crf, tune = "fast", "16", "stillimage"
        print(f"  screen content detected: stillimage, CRF 16 → {out_path.name}")
    else:
        preset, crf, tune = "fast", "20", None

    if quality == "draft":
        vf = ["scale=960:540:force_original_aspect_ratio=decrease",
              "pad=960:540:(ow-iw)/2:(oh-ih)/2", "setsar=1"]
    else:
        vf = ["scale=1920:1080:force_original_aspect_ratio=decrease",
              "pad=1920:1080:(ow-iw)/2:(oh-ih)/2", "setsar=1"]
    if speed > 1.0:
        vf.insert(0, f"setpts=PTS/{speed:.6f}")

    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-ss", f"{start:.3f}", "-i", str(source), "-t", f"{raw_dur:.3f}",
    ]

    if mute:
        cmd += [
            "-f", "lavfi", "-t", f"{out_dur:.3f}",
            "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
        ]
    else:
        af_parts = [f"afade=t=in:st=0:d=0.01",
                    f"afade=t=out:st={max(0.0, out_dur - 0.01):.3f}:d=0.01"]
        af_parts += audio_atempo(speed)
        cmd += ["-af", ",".join(af_parts)]

    enc_args = ["-c:v", "libx264", "-preset", preset, "-crf", crf]
    if tune:
        enc_args += ["-tune", tune]

    cmd += [
        "-vf", ",".join(vf),
        "-r", "24",
        *enc_args,
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-t", f"{out_dur:.3f}",
        "-movflags", "+faststart",
        str(out_path),
    ]
    run(cmd)


def concat(segments: list[Path], out_path: Path, edit_dir: Path) -> None:
    list_path = edit_dir / "_concat_list.txt"
    lines = []
    for p in segments:
        escaped = str(p.resolve()).replace("'", "'\\''")
        lines.append(f"file '{escaped}'")
    list_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        run([
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", str(list_path),
            "-c", "copy", "-movflags", "+faststart", str(out_path),
        ])
    finally:
        list_path.unlink(missing_ok=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("edl", type=Path)
    ap.add_argument("-o", "--output", type=Path, required=True)
    ap.add_argument("--quality", choices=["draft", "preview", "final"], default="preview")
    ap.add_argument("--loudnorm", action="store_true", help="one-pass -14 LUFS normalization")
    args = ap.parse_args()

    edl_path = args.edl.resolve()
    edit_dir = edl_path.parent
    edl = json.loads(edl_path.read_text(encoding="utf-8"))
    out_path = args.output.resolve()

    clips_dir = edit_dir / f"clips_{'draft' if args.quality == 'draft' else ('preview' if args.quality == 'preview' else 'graded')}"
    segments: list[Path] = []

    print(f"extracting {len(edl['ranges'])} ranges → {clips_dir.name}/")
    for i, r in enumerate(edl["ranges"]):
        src = resolve(edl["sources"][r["source"]], edit_dir)
        start = float(r["start"])
        end = float(r["end"])
        speed = float(r.get("speed", 1.0))
        mute = bool(r.get("mute", False))
        out = clips_dir / f"seg_{i:02d}_{r['source']}.mp4"
        extract_segment(src, start, end - start, speed, mute, out, args.quality)
        segments.append(out)
        out_dur = (end - start) / speed
        print(f"  [{i:02d}] {r['beat']:<16} {start:8.2f}-{end:8.2f} → {out_dur:6.2f}s"
              f"{'  [speed x' + str(speed) + ']' if speed > 1 else ''}")

    print("concat →", out_path.name)
    raw_path = out_path.with_suffix(".concat.mp4")
    concat(segments, raw_path, edit_dir)
    if args.loudnorm:
        print("loudnorm → -14 LUFS")
        run([
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(raw_path),
            "-c:v", "copy",
            "-af", "loudnorm=I=-14:TP=-1:LRA=11",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-movflags", "+faststart",
            str(out_path),
        ])
        raw_path.unlink(missing_ok=True)
    else:
        raw_path.replace(out_path)
    size_mb = out_path.stat().st_size / (1024 * 1024)
    print(f"done: {out_path} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
