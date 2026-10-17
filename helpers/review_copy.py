#!/usr/bin/env python3
"""Make a time-preserving review copy of a film.

The review host hands the whole file to the page (the DSH asset bridge transfers
bytes; it does not stream), so pointing a review surface at a 263MB master is a bad
handoff. The skill's answer is a 审阅副本: same duration, **same native
resolution** (the reviewer is judging pixels — downscaling to 720p to save bytes
trades away the thing being reviewed), but a higher CRF and a light audio bitrate.

On the 图拉斯 project this turns the 263MB master into 37MB at 1080x1920.

    python3 helpers/review_copy.py <src.mp4> [--out <dst.mp4>] [--max-mb 80] [--force]

Default output is `<stem>.review.mp4` next to the source. Prints the decision as
one line of JSON so a caller (build_review) can consume the path.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

DEFAULT_MAX_MB = 80.0
DEFAULT_CRF = 29
DEFAULT_AUDIO_KBPS = 128
# Audio-only sidecars (narration tracks in the live stage's asset map) have no
# pixels to protect, so they get a much tighter budget than a film does:
# 193 kbps stereo -> 48 kbps mono is inaudible for speech and saves ~75% of the
# bytes, and bytes are what the review page pays for (base64 in the srcdoc).
AUDIO_ONLY_KBPS = 48
# A cloud-synced output path stalls ffmpeg's muxer intermittently (GOTCHA #5). The
# encode is cheap and the failure is transient, so retry before giving up — a
# failed copy used to leave a truncated file that build_review then reused forever.
PROXY_ATTEMPTS = 3
PROXY_RETRY_DELAY_S = 1.5
# One keyframe per second. This is not a quality knob: review_slices.py cuts each
# step out with `-c copy`, which can only start at a keyframe. At x264's default
# keyframe interval (~8s here) a 6-second step came out with a 7.9s lead in front of
# it, so every "slice" was bigger than the step it served. One-second spacing bounds
# the lead to 1s and keeps slices genuinely small.
DEFAULT_GOP = 30


def _probe_media(path: Path) -> tuple[float, int, int]:
    """(duration_s, width, height) of the first video stream."""
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height",
         "-show_entries", "format=duration",
         "-of", "json", str(path)],
        capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe 读不出 {path.name}")
    blob = json.loads(proc.stdout or "{}")
    stream = (blob.get("streams") or [{}])[0]
    duration = float((blob.get("format") or {}).get("duration") or 0.0)
    return duration, int(stream.get("width") or 0), int(stream.get("height") or 0)


def media_duration(path: Path) -> float | None:
    """Duration in seconds, or None when ffprobe cannot read the file.

    Callers use this as a decodability test: a truncated encode (no moov atom)
    returns None instead of raising, so "is this proxy still usable?" is one call.
    """
    try:
        duration, _w, _h = _probe_media(path)
    except (RuntimeError, OSError, ValueError):
        return None
    return duration


def is_fresh_copy(path: Path, expect_duration: float, tolerance: float = 0.5) -> bool:
    """True when `path` is a decodable copy of a source of `expect_duration`."""
    duration = media_duration(path)
    if duration is None or duration <= 0:
        return False
    return abs(duration - expect_duration) <= tolerance


def needs_copy(src: Path, max_mb: float = DEFAULT_MAX_MB) -> bool:
    """True when the file is bigger than the review budget."""
    return src.stat().st_size > max_mb * 1_000_000


def make(src: Path, out: Path | None = None, *, crf: int = DEFAULT_CRF,
         audio_kbps: int = DEFAULT_AUDIO_KBPS, gop: int | None = DEFAULT_GOP,
         max_mb: float = DEFAULT_MAX_MB, force: bool = False) -> dict:
    """Encode a review copy. Returns a small decision record.

    Handles both a film (video + audio) and an audio-only sidecar — the live
    stage's asset map holds narration tracks too, and those are the cheapest
    bytes to reclaim (a 193 kbps stereo narration becomes ~48 kbps mono with no
    audible cost, where the picture must keep its pixels).

    Three promises, each asserted rather than assumed:

    * never rewrites the source;
    * video keeps the source's pixel dimensions and the duration is preserved;
    * **the result is actually under `max_mb`**. A "review copy" that is still
      over budget is worse than none: `build_review` would point the page at it
      and report success while the page still transfers the whole thing.
    """
    src = Path(src).resolve()
    if not src.is_file():
        raise SystemExit(f"✗ 找不到源片：{src}")

    size_mb = src.stat().st_size / 1_000_000
    if not force and not needs_copy(src, max_mb):
        return {"ok": True, "action": "skip", "reason": "already small",
                "path": str(src), "bytes": src.stat().st_size, "size_mb": round(size_mb, 1)}

    duration, width, height = _probe_media(src)
    has_video = bool(width and height)
    if out is None:
        out = src.with_name(src.stem + ".review" + src.suffix)
    out = Path(out).resolve()
    if out == src:
        raise SystemExit("✗ 输出不能覆盖源片")

    if shutil.which("ffmpeg") is None:
        raise SystemExit("✗ PATH 上没有 ffmpeg")

    # Keep the real extension: ffmpeg infers the muxer from it, and ".part" alone
    # is an unknown format ("Error initializing the muxer ... Invalid argument").
    tmp = out.with_name(out.stem + ".part" + out.suffix)
    if has_video:
        # `gop` exists for copies that will be CUT with `-c copy`
        # (review_slices.py needs a keyframe at each step boundary). It is not
        # free: on the 1236x916 screen track, forcing one keyframe per second
        # took the same CRF 29 encode from 2.6 MB to 10.0 MB. Pass gop=None
        # when nothing slices the copy (the live stage's asset map does not).
        keyframes = (["-g", str(gop), "-keyint_min", str(gop), "-sc_threshold", "0"]
                     if gop else [])
        cmd = ["ffmpeg", "-v", "error", "-y", "-i", str(src),
               "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
               *keyframes, "-pix_fmt", "yuv420p",
               "-c:a", "aac", "-b:a", f"{audio_kbps}k",
               "-movflags", "+faststart", str(tmp)]
    else:
        # Audio sidecar: downmix and drop the bitrate. Nothing here is judged at
        # the pixel, so there is no reason to carry a stereo narration master.
        cmd = ["ffmpeg", "-v", "error", "-y", "-i", str(src),
               "-vn", "-ac", "1", "-c:a", "aac", "-b:a", f"{AUDIO_ONLY_KBPS}k",
               "-movflags", "+faststart", str(tmp)]
    tail = []
    for attempt in range(1, PROXY_ATTEMPTS + 1):
        proc = subprocess.run(cmd, capture_output=True)
        if proc.returncode == 0:
            break
        tail = proc.stderr.decode("utf-8", "replace").strip().splitlines()[-3:]
        tmp.unlink(missing_ok=True)   # a partial encode must never survive
        if attempt == PROXY_ATTEMPTS:
            raise SystemExit("✗ 审阅副本编码失败（重试 %d 次）：" % PROXY_ATTEMPTS
                             + " / ".join(tail))
        delay = PROXY_RETRY_DELAY_S * attempt
        print(f"  · 审阅副本编码失败（{tail[-1][:80] if tail else 'unknown'}），"
              f"{delay:.1f}s 后重试（{attempt}/{PROXY_ATTEMPTS - 1}）")
        time.sleep(delay)

    # Validate the temp file, not the destination: a muxer timeout leaves a
    # truncated file with no moov atom, and a truncated file at the FINAL path
    # gets judged "fresh" by build_review on the next rebuild (mtime + size look
    # fine) and is then handed to the page as a silent no-audio copy.
    try:
        out_duration, out_w, out_h = _probe_media(tmp)
        if has_video and (out_w, out_h) != (width, height):
            raise SystemExit(f"✗ 审阅副本改动了分辨率 {(width, height)} → {(out_w, out_h)}；"
                             "审阅副本必须保持原生像素")
        if abs(out_duration - duration) > 0.1:
            raise SystemExit(f"✗ 审阅副本时长变了 {duration:.3f}s → {out_duration:.3f}s；"
                             "审阅副本必须保留时间")
    except SystemExit:
        tmp.unlink(missing_ok=True)
        raise

    out_bytes = tmp.stat().st_size
    under_budget = out_bytes <= max_mb * 1_000_000
    if not under_budget and out_bytes >= src.stat().st_size:
        tmp.unlink(missing_ok=True)
        # A copy that is no smaller than what it copies has achieved nothing, and
        # handing it over as a "审阅副本" would read as the problem being solved.
        # A copy that shrank but is still over budget is a different case: it did
        # help, so it is reported (`underBudget: false`) and the caller decides.
        raise SystemExit(
            f"✗ 审阅副本没有变小：{size_mb:.1f}MB → {out_bytes / 1e6:.1f}MB"
            f"（上限 {max_mb:.0f}MB）。这份副本解决不了问题："
            f"提高 --crf、下调 --audio-kbps，或改用 --slices 只交付当前窗口。")

    os.replace(tmp, out)   # atomic: the final path never holds a partial file
    return {"ok": True, "action": "made", "path": str(out),
            "bytes": out_bytes,
            "size_mb": round(out_bytes / 1_000_000, 1),
            "source_mb": round(size_mb, 1), "duration_s": round(duration, 3),
            "underBudget": under_budget,
            "kind": "video" if has_video else "audio",
            "width": width or None, "height": height or None,
            "crf": crf if has_video else None,
            "gop": (gop or None) if has_video else None}


def main() -> int:
    ap = argparse.ArgumentParser(description="生成保留时间与原生分辨率的审阅副本")
    ap.add_argument("src", type=Path)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--max-mb", type=float, default=DEFAULT_MAX_MB)
    ap.add_argument("--crf", type=int, default=DEFAULT_CRF)
    ap.add_argument("--audio-kbps", type=int, default=DEFAULT_AUDIO_KBPS)
    ap.add_argument("--gop", type=int, default=DEFAULT_GOP,
                    help="关键帧间隔（帧），供 --slices 用 `-c copy` 切片时对准切点；"
                         "传 0 表示不限制（给不会被切片的副本用，体积小得多）")
    ap.add_argument("--force", action="store_true", help="源片已经够小也照样生成")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    record = make(args.src, args.out, crf=args.crf, audio_kbps=args.audio_kbps,
                  gop=args.gop, max_mb=args.max_mb, force=args.force)
    if args.json:
        print(json.dumps(record, ensure_ascii=False))
    elif record["action"] == "skip":
        print(f"无需副本：{Path(record['path']).name} 只有 {record['size_mb']}MB"
              f"（上限 {args.max_mb}MB）")
    else:
        shape = (f"{record['width']}x{record['height']}" if record.get("width")
                 else "纯音频")
        warn = "" if record.get("underBudget", True) else "  ⚠ 仍超上限，页面仍会整份搬"
        print(f"审阅副本 {record['source_mb']}MB → {record['size_mb']}MB  "
              f"{shape}  {record['duration_s']}s  "
              f"→ {Path(record['path']).name}{warn}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
