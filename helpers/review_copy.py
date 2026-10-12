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
import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT_MAX_MB = 80.0
DEFAULT_CRF = 29
DEFAULT_AUDIO_KBPS = 128
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


def needs_copy(src: Path, max_mb: float = DEFAULT_MAX_MB) -> bool:
    """True when the file is bigger than the review budget."""
    return src.stat().st_size > max_mb * 1_000_000


def make(src: Path, out: Path | None = None, *, crf: int = DEFAULT_CRF,
         audio_kbps: int = DEFAULT_AUDIO_KBPS, gop: int = DEFAULT_GOP,
         max_mb: float = DEFAULT_MAX_MB, force: bool = False) -> dict:
    """Encode a review copy. Returns a small decision record.

    Never rewrites the source, and never silently downscales: the copy keeps the
    source's pixel dimensions so the review is of the real picture.
    """
    src = Path(src).resolve()
    if not src.is_file():
        raise SystemExit(f"✗ 找不到源片：{src}")
    out = Path(out).resolve() if out else src.with_suffix("").with_name(
        src.stem + ".review.mp4")

    size_mb = src.stat().st_size / 1_000_000
    if not force and not needs_copy(src, max_mb):
        return {"ok": True, "action": "skip", "reason": "already small",
                "path": str(src), "bytes": src.stat().st_size, "size_mb": round(size_mb, 1)}
    if out == src:
        raise SystemExit("✗ 输出不能覆盖源片")

    if shutil.which("ffmpeg") is None:
        raise SystemExit("✗ PATH 上没有 ffmpeg")

    duration, width, height = _probe_media(src)
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", str(src),
           "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
           "-g", str(gop), "-keyint_min", str(gop), "-sc_threshold", "0",
           "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", f"{audio_kbps}k",
           "-movflags", "+faststart", str(out)]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        tail = proc.stderr.decode("utf-8", "replace").strip().splitlines()[-3:]
        raise SystemExit("✗ 审阅副本编码失败：" + " / ".join(tail))

    out_duration, out_w, out_h = _probe_media(out)
    if (out_w, out_h) != (width, height):
        raise SystemExit(f"✗ 审阅副本改动了分辨率 {(width, height)} → {(out_w, out_h)}；"
                         "审阅副本必须保持原生像素")
    if abs(out_duration - duration) > 0.1:
        raise SystemExit(f"✗ 审阅副本时长变了 {duration:.3f}s → {out_duration:.3f}s；"
                         "审阅副本必须保留时间")

    return {"ok": True, "action": "made", "path": str(out),
            "bytes": out.stat().st_size,
            "size_mb": round(out.stat().st_size / 1_000_000, 1),
            "source_mb": round(size_mb, 1), "duration_s": round(duration, 3),
            "width": width, "height": height, "crf": crf, "gop": gop}


def main() -> int:
    ap = argparse.ArgumentParser(description="生成保留时间与原生分辨率的审阅副本")
    ap.add_argument("src", type=Path)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--max-mb", type=float, default=DEFAULT_MAX_MB)
    ap.add_argument("--crf", type=int, default=DEFAULT_CRF)
    ap.add_argument("--audio-kbps", type=int, default=DEFAULT_AUDIO_KBPS)
    ap.add_argument("--gop", type=int, default=DEFAULT_GOP,
                    help="关键帧间隔（帧）；切片靠它才能切得准")
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
        print(f"审阅副本 {record['source_mb']}MB → {record['size_mb']}MB  "
              f"{record['width']}x{record['height']}  {record['duration_s']}s  "
              f"→ {Path(record['path']).name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
