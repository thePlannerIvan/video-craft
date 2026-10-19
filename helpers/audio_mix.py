#!/usr/bin/env python3
"""The one mix output: voice + optional music, ducked, to the delivery loudness.

Owner rationale (v3): four loudness numbers existed (render -14, audio_fix -16.5,
project spikes -15, docs). This helper is the single place a *mix* is decided;
`render.py --no-loudnorm` then muxes it as the only audio source, so the number
cannot be applied twice.

    audio_mix.py voice.wav -o mix.wav
    audio_mix.py voice.wav -o mix.wav --bgm music.wav --bgm-lufs -32
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"ffmpeg 失败：{r.stderr.strip().splitlines()[-1][:200]}")
    return r


def lufs(path: Path) -> float:
    r = run(["ffmpeg", "-hide_banner", "-i", str(path), "-af", "loudnorm=print_format=json",
             "-f", "null", "-"])
    m = re.search(r'\{[^{}]*"input_i"[^{}]*\}', r.stderr, re.S)
    if not m:
        sys.exit(f"量不到响度：{path}")
    return float(json.loads(m.group(0))["input_i"])


def main() -> int:
    ap = argparse.ArgumentParser(description="single mix: voice (+music) → delivery loudness")
    ap.add_argument("voice", type=Path)
    ap.add_argument("-o", "--output", type=Path, required=True)
    ap.add_argument("--bgm", type=Path)
    ap.add_argument("--bgm-lufs", type=float, default=-32.0)
    ap.add_argument("--target-lufs", type=float, default=-14.0)
    ap.add_argument("--tail", type=float, default=0.0, help="seconds of BGM tail after voice")
    a = ap.parse_args()
    if not a.voice.is_file():
        sys.exit(f"找不到人声：{a.voice}")

    dur = float(run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                     "-of", "csv=p=0", str(a.voice)]).stdout.strip())

    if not a.bgm:
        gain = a.target_lufs - lufs(a.voice)
        af = f"volume={gain:.2f}dB,alimiter=limit=0.891:level=false"
        run(["ffmpeg", "-v", "error", "-y", "-i", str(a.voice), "-af", af,
             "-ar", "48000", "-ac", "2", str(a.output)])
        print(f"voice only · {lufs(a.output):.1f} LUFS → {a.output}")
        return 0

    if not a.bgm.is_file():
        sys.exit(f"找不到 BGM：{a.bgm}")
    bed_gain = a.bgm_lufs - lufs(a.bgm)
    total = dur + max(0.0, a.tail)
    fc = (
        f"[0:a]aresample=48000,asplit=2[voice][sc];"
        f"[1:a]aresample=48000,atrim=0:{total:.3f},asetpts=PTS-STARTPTS,"
        f"volume={bed_gain:.2f}dB,afade=t=in:st=0:d=0.8[bed0];"
        f"[bed0][sc]sidechaincompress=threshold=0.1:ratio=2.5:attack=40:release=500[bed];"
        f"[voice][bed]amix=inputs=2:duration=first:dropout_transition=0,"
        f"loudnorm=I={a.target_lufs}:TP=-1.5:LRA=11[out]"
    )
    run(["ffmpeg", "-v", "error", "-y", "-i", str(a.voice), "-i", str(a.bgm),
         "-filter_complex", fc, "-map", "[out]", "-ar", "48000", "-ac", "2", str(a.output)])
    print(f"mix · bed {a.bgm_lufs:.0f} LUFS → {lufs(a.output):.1f} LUFS → {a.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
