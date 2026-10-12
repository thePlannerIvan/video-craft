#!/usr/bin/env python3
"""Encode a HyperFrames PNG sequence into an alpha-preserving MOV overlay.

Why this exists (learned the hard way in the 2026-08 种草大赏 session, and
re-measured 2026-09-22): writing WebM/MKV/ivf silently drops transparency —
the round trip returns opaque pixels (yuv420p) even though libvpx *advertises*
yuva420p and the container records alpha_mode=1. The advertised format is not
evidence; only the extracted plane is. PNG-in-MOV keeps rgba and is ~1/5 the
size of ProRes 4444 — the default for overlay layers composited onto footage.

Alpha is verified before reporting success, and the verdict is the PLANE:
  1. the alpha plane spans both transparent and opaque pixels
     (alphaextract → span ≥ 16), so the encode didn't flatten everything
     onto an opaque background. Span rather than absolute levels, because
     alphaextract output can come back range-converted.
  2. pix_fmt is only printed as a note — it under-reports real alpha
     (HEVC+alpha reports yuv420p) so it must never be the gate.

For an arbitrary file (not one of ours), `helpers/check_alpha.py <file>` runs
the same plane test and exits non-zero when transparency is missing.

Usage:
    python3 scripts/encode_transparent.py <png_dir> -o out.mov
    python3 scripts/encode_transparent.py <png_dir> -o out.mov --codec prores --fps 30
    python3 scripts/encode_transparent.py <png_dir> -o layer.webm --codec webm

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
    # Browser-compositable alpha. MOV/ProRes alpha is fine for ffmpeg and invisible
    # to every browser (Chrome cannot composite it at all), which is why an overlay
    # could only ever be reviewed as a baked render. VP9-in-WebM with yuva420p is the
    # one alpha carrier the review page can stack over a video itself.
    # -auto-alt-ref 0 is required: VP9 alpha in WebM is not written otherwise.
    # -cpu-used 5 / -deadline good: default VP9 speed spends minutes on a 1080x1920
    # overlay that exists only to be looked at. A review preview does not need
    # slow-search quality; the MOV remains the delivery artefact.
    "webm": ["-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-auto-alt-ref", "0",
             "-b:v", "0", "-crf", "24", "-row-mt", "1",
             "-cpu-used", "5", "-deadline", "good"],
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
    # pix_fmt is ADVISORY, never a verdict: it under-reports real alpha (HEVC+alpha
    # reports yuv420p) and it cannot prove loss (a VP9 encode advertises yuva420p in
    # the stream header and still round-trips opaque). The plane decides.
    if not any(c in pix for c in ("a", "yuva")):
        print(f"  note: pix_fmt reports {pix} — checking the alpha plane anyway, "
              f"because pix_fmt does not reliably describe transparency")
    a_min, a_max = _alpha_range(path)
    # Span, not absolute levels: alphaextract output can come back range-converted, so
    # a fixed threshold (the old a_min < 64 and a_max > 192) can false-fail a good file.
    if a_max - a_min < 16:
        sys.exit(f"FAIL: alpha plane spans only [{a_min},{a_max}] — overlay is opaque or blank")
    print(f"  alpha OK: pix_fmt {pix}, plane range [{a_min},{a_max}], span {a_max - a_min}")
    return pix, a_min, a_max


def _alpha_range(path: Path) -> tuple[float, float]:
    """Alpha plane range, or exit.

    VP9-in-WebM keeps alpha in a separate block that ffmpeg's *default* decoder does
    not surface: `alphaextract` then fails with "Requested planes not available" on a
    file that does carry alpha, and ffprobe still reports `pix_fmt=yuv420p`. Naming
    the decoder makes the plane appear, so a failed extract retries that way instead
    of condemning a good overlay.
    """
    def extract(extra: list[str]) -> bytes:
        return subprocess.run(
            ["ffmpeg", "-v", "error", *extra, "-i", str(path),
             "-vf", "alphaextract,format=gray",
             "-f", "rawvideo", "-pix_fmt", "gray", "-"],
            capture_output=True).stdout

    out = extract([])
    if not out:
        out = extract(["-c:v", "libvpx-vp9"])
        if out:
            print("  note: alpha needed the explicit libvpx-vp9 decoder to surface "
                  "(VP9 stores it out-of-band; the default decoder hides the plane)")
    if not out:
        sys.exit(f"FAIL: could not extract alpha from {path.name}")
    return min(out), max(out)


def encode_sequence(png_dir: Path, out: Path, *, codec: str = "png",
                    fps: int = 30, quiet: bool = False) -> dict:
    """PNG 序列 → 带 alpha 的载体。返回 {pix_fmt, size_mb, duration_s, frames}。

    抽成函数是为了让一次渲染能出多种载体：capture 一次、编码几次，两条载体就不可能
    各走各的。CLI 与 render_layer.py 走同一条路径。
    """
    png_dir = Path(png_dir).resolve()
    frames = sorted(png_dir.glob("*.png"))
    if not frames:
        raise SystemExit(f"✗ 没有 PNG 帧：{png_dir}")
    if codec not in CODECS:
        raise SystemExit(f"✗ 不支持的编码 {codec}；可选 {sorted(CODECS)}")
    out = Path(out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        # copy to a canonical img_%05d.png naming: the concat demuxer drops
        # frames from image inputs on ffmpeg 8.1.2 (30 pngs -> 4 frames),
        # image2 with a zero-padded pattern is the reliable path
        seq = Path(tmp) / "seq"
        seq.mkdir()
        for i, f in enumerate(frames):
            shutil.copy2(f, seq / f"img_{i:05d}.png")
        # Encode into LOCAL disk, then move the finished file in. Writing a long
        # encode straight into a cloud-synced workspace dies partway with
        # "Error writing trailer: Operation timed out" and leaves a 0-byte file
        # (observed on the 5-layer 图拉斯 set: two of five came back empty).
        staging = Path(tmp) / out.name
        run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps),
             "-i", str(seq / "img_%05d.png")] + CODECS[codec] + [str(staging)])
        out.unlink(missing_ok=True)
        shutil.move(str(staging), str(out))

    pix, _, _ = verify_alpha(out)
    info = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration,size",
         "-of", "default=noprint_wrappers=1", str(out)],
        capture_output=True, text=True).stdout
    d = dict(line.split("=", 1) for line in info.splitlines() if "=" in line)
    size_mb = int(d.get("size", 0)) / 1e6
    dur = float(d.get("duration", 0))
    if not quiet:
        print(f"→ {out}  ({codec}, {pix}, {fps}fps, {_fmt_seconds(dur)}, "
              f"{size_mb:.1f} MB, {len(frames)} frames")
    return {"pix_fmt": pix, "size_mb": size_mb, "duration_s": dur,
            "frames": len(frames)}


def main() -> None:
    ap = argparse.ArgumentParser(description="PNG sequence → alpha MOV overlay")
    ap.add_argument("png_dir", type=Path)
    ap.add_argument("-o", "--output", type=Path, required=True)
    ap.add_argument("--codec", choices=sorted(CODECS), default="png",
                    help="png = PNG-in-MOV (default, ~1/5 ProRes size); "
                         "prores = ProRes 4444; webm = VP9 + alpha, the only carrier "
                         "a browser can composite (use it for review previews)")
    ap.add_argument("--fps", type=int, default=30)
    args = ap.parse_args()

    encode_sequence(args.png_dir, args.output, codec=args.codec,
                    fps=args.fps)


if __name__ == "__main__":
    main()
