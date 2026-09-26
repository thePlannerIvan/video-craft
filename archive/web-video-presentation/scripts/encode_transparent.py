#!/usr/bin/env python3
"""Encode a HyperFrames PNG sequence into an alpha-preserving MOV overlay.

Why this exists (learned the hard way in the 2026-08 种草大赏 session):
homebrew ffmpeg's libvpx is built WITHOUT alpha support, so WebM/MKV/ivf
renders silently drop transparency (yuv420p). PNG-in-MOV keeps rgba and is
~1/5 the size of ProRes 4444 — the default for overlay layers that get
composited onto phone-shot footage.

Alpha is verified twice before reporting success:
  1. ffprobe pix_fmt contains an alpha channel (rgba / yuva44*)
  2. the alpha plane spans both transparent and opaque pixels
     (alphaextract → min < 64 and max > 192), so the encode didn't
     flatten everything onto an opaque background

Usage:
    python3 scripts/encode_transparent.py <png_dir> -o out.mov
    python3 scripts/encode_transparent.py <png_dir> -o out.mov --codec prores --fps 30

Companion render (Phase 5, RENDERING.md):
    npx hyperframes render --no-low-memory-mode --format png-sequence -o <png_dir>
--no-low-memory-mode is REQUIRED: the low-memory screenshot-capture path
loses alpha even when the composition needs it.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

CODECS = {
    "png": ["-c:v", "png", "-pix_fmt", "rgba"],                      # default: small, lossless alpha
    "prores": ["-c:v", "prores_videotoolbox", "-profile:v", "4444"],  # 4444 alpha, ~5x larger
}


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _fmt_seconds(s: float) -> str:
    return f"{int(s // 60)}m{s % 60:04.1f}s"


def verify_alpha(path: Path) -> tuple[str, float, float]:
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=pix_fmt,width,height", "-of", "default=noprint_wrappers=1",
         str(path)],
        capture_output=True, text=True).stdout
    info = dict(line.split("=", 1) for line in probe.splitlines() if "=" in line)
    pix = info.get("pix_fmt", "")
    if not any(c in pix for c in ("a", "yuva")):
        sys.exit(f"FAIL: {path.name} pix_fmt {pix} has NO alpha channel — encode dropped transparency")
    a_min, a_max = _alpha_range(path)
    if not (a_min < 64 and a_max > 192):
        sys.exit(f"FAIL: alpha plane spans only [{a_min},{a_max}] — overlay is opaque or blank")
    print(f"  alpha OK: pix_fmt {pix}, plane range [{a_min},{a_max}]")
    return pix, a_min, a_max


def _alpha_range(path: Path) -> tuple[float, float]:
    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-vf", "alphaextract,format=gray",
         "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        capture_output=True).stdout
    if not out:
        sys.exit(f"FAIL: could not extract alpha from {path.name}")
    return min(out), max(out)


def main() -> None:
    ap = argparse.ArgumentParser(description="PNG sequence → alpha MOV overlay")
    ap.add_argument("png_dir", type=Path)
    ap.add_argument("-o", "--output", type=Path, required=True)
    ap.add_argument("--codec", choices=sorted(CODECS), default="png",
                    help="png = PNG-in-MOV (default, ~1/5 ProRes size); prores = ProRes 4444")
    ap.add_argument("--fps", type=int, default=30)
    args = ap.parse_args()

    png_dir = args.png_dir.resolve()
    frames = sorted(png_dir.glob("*.png"))
    if not frames:
        sys.exit(f"no *.png frames in {png_dir}")
    out = args.output.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        # copy to a canonical img_%05d.png naming: the concat demuxer drops
        # frames from image inputs on ffmpeg 8.1.2 (30 pngs -> 4 frames),
        # image2 with a zero-padded pattern is the reliable path
        seq = Path(tmp) / "seq"
        seq.mkdir()
        for i, f in enumerate(frames):
            shutil.copy2(f, seq / f"img_{i:05d}.png")
        run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(args.fps),
             "-i", str(seq / "img_%05d.png")] + CODECS[args.codec] + [str(out)])

    pix, _, _ = verify_alpha(out)
    info = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration,size",
         "-of", "default=noprint_wrappers=1", str(out)],
        capture_output=True, text=True).stdout
    d = dict(line.split("=", 1) for line in info.splitlines() if "=" in line)
    size_mb = int(d.get("size", 0)) / 1e6
    dur = float(d.get("duration", 0))
    print(f"→ {out}  ({args.codec}, {pix}, {args.fps}fps, {_fmt_seconds(dur)}, "
          f"{size_mb:.1f} MB, {len(frames)} frames)")


if __name__ == "__main__":
    main()
