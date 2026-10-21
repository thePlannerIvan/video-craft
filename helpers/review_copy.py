#!/usr/bin/env python3
"""Make a time-preserving review copy of a film.

The review host hands the whole file to the page (the DSH asset bridge transfers
bytes; it does not stream), so pointing a review surface at a 263MB master is a bad
handoff. The skill's answer is a 审阅副本: same duration, and **native resolution
first** (the reviewer is judging pixels — downscaling to 720p to save bytes trades
away the thing being reviewed), but a higher CRF and a light audio bitrate.

Only when native pixels still cannot fit the budget does the copy step down the
resolution. On a 368s 720x1280 talking-head master (2026-10-21, XHS v1) one pass
of "higher CRF, same pixels" still produced 52MB against a 4MB live-stage budget;
a 0.75 / 0.5 / 0.35 ladder is what makes such a file reachable instead of leaving
the page to carry 70MB of base64. The record says whether it stepped down, so the
review page can say "picture is a 0.5x proxy" instead of pretending nothing changed.

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
# Native pixels are tried first; these are the only fallbacks, in order. 0.75 keeps
# a 4K-ish master readable in a side-by-side review, 0.35 is the floor where text
# on a 1080p screen track is still legible at review scale. The ladder stops at the
# first step that fits; if none fits, the smallest result is returned and the
# record says `underBudget: false` rather than silently leaving the master in place.
DOWNSCALE_STEPS = (0.75, 0.5, 0.35)
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


def media_size(path: Path) -> tuple[int, int] | None:
    """(width, height) of the first video stream, or None when unreadable."""
    try:
        _duration, width, height = _probe_media(path)
    except (RuntimeError, OSError, ValueError):
        return None
    return (width, height) if width and height else None


def has_audio(path: Path) -> bool:
    """True when the file has at least one audio stream."""
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=index", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True)
    return proc.returncode == 0 and bool(proc.stdout.strip())


def is_fresh_copy(path: Path, expect_duration: float, tolerance: float = 0.5) -> bool:
    """True when `path` is a decodable copy of a source of `expect_duration`."""
    duration = media_duration(path)
    if duration is None or duration <= 0:
        return False
    return abs(duration - expect_duration) <= tolerance


def needs_copy(src: Path, max_mb: float = DEFAULT_MAX_MB) -> bool:
    """True when the file is bigger than the review budget."""
    return src.stat().st_size > max_mb * 1_000_000


def scaled_size(width: int, height: int, scale: float) -> tuple[int, int]:
    """Even dimensions, never below 2px: yuv420p rejects odd width/height."""
    def even(value: float) -> int:
        return max(2, int(round(value)) // 2 * 2)
    return even(width * scale), even(height * scale)


def _encode(cmd: list[str], out: Path) -> None:
    """Run ffmpeg with retries; never leave a partial file behind."""
    tail: list[str] = []
    for attempt in range(1, PROXY_ATTEMPTS + 1):
        proc = subprocess.run(cmd, capture_output=True)
        if proc.returncode == 0:
            return
        tail = proc.stderr.decode("utf-8", "replace").strip().splitlines()[-3:]
        out.unlink(missing_ok=True)   # a partial encode must never survive
        if attempt == PROXY_ATTEMPTS:
            raise SystemExit("✗ 审阅副本编码失败（重试 %d 次）：" % PROXY_ATTEMPTS
                             + " / ".join(tail))
        delay = PROXY_RETRY_DELAY_S * attempt
        print(f"  · 审阅副本编码失败（{tail[-1][:80] if tail else 'unknown'}），"
              f"{delay:.1f}s 后重试（{attempt}/{PROXY_ATTEMPTS - 1}）")
        time.sleep(delay)


def _video_cmd(src: Path, tmp: Path, *, crf: int, audio_kbps: int,
               gop: int | None, size: tuple[int, int] | None,
               keep_audio: bool) -> list[str]:
    # `gop` exists for copies that will be CUT with `-c copy`
    # (review_slices.py needs a keyframe at each step boundary). It is not
    # free: on the 1236x916 screen track, forcing one keyframe per second
    # took the same CRF 29 encode from 2.6 MB to 10.0 MB. Pass gop=None
    # when nothing slices the copy (the live stage's asset map does not).
    keyframes = (["-g", str(gop), "-keyint_min", str(gop), "-sc_threshold", "0"]
                 if gop else [])
    scale = ["-vf", f"scale={size[0]}:{size[1]}"] if size else []
    audio = (["-c:a", "aac", "-b:a", f"{audio_kbps}k"] if keep_audio else ["-an"])
    return ["ffmpeg", "-v", "error", "-y", "-i", str(src),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
            *keyframes, *scale, "-pix_fmt", "yuv420p",
            *audio, "-movflags", "+faststart", str(tmp)]


def _audio_cmd(src: Path, tmp: Path) -> list[str]:
    # Audio sidecar: downmix and drop the bitrate. Nothing here is judged at
    # the pixel, so there is no reason to carry a stereo narration master.
    return ["ffmpeg", "-v", "error", "-y", "-i", str(src),
            "-vn", "-ac", "1", "-c:a", "aac", "-b:a", f"{AUDIO_ONLY_KBPS}k",
            "-movflags", "+faststart", str(tmp)]


def _validate(tmp: Path, *, duration: float, expect_size: tuple[int, int] | None,
              source_size: tuple[int, int] | None) -> tuple[int, int]:
    """Prove the temp file is the same duration, and at the resolution we asked for."""
    out_duration, out_w, out_h = _probe_media(tmp)
    if abs(out_duration - duration) > 0.1:
        raise SystemExit(f"✗ 审阅副本时长变了 {duration:.3f}s → {out_duration:.3f}s；"
                         "审阅副本必须保留时间")
    if source_size is not None:
        if expect_size is None:
            raise SystemExit("✗ 内部错误：视频副本缺少期望分辨率")
        if (out_w, out_h) != expect_size:
            raise SystemExit(f"✗ 审阅副本分辨率 {expect_size[0]}×{expect_size[1]} "
                             f"→ {out_w}×{out_h}，与这一步声明的不一致")
    return out_w, out_h


def make(src: Path, out: Path | None = None, *, crf: int = DEFAULT_CRF,
         audio_kbps: int = DEFAULT_AUDIO_KBPS, gop: int | None = DEFAULT_GOP,
         max_mb: float = DEFAULT_MAX_MB, force: bool = False,
         allow_downscale: bool = True, keep_audio: bool = True) -> dict:
    """Encode a review copy. Returns a small decision record.

    Handles both a film (video + audio) and an audio-only sidecar — the live
    stage's asset map holds narration tracks too, and those are the cheapest
    bytes to reclaim (a 193 kbps stereo narration becomes ~48 kbps mono with no
    audible cost, where the picture must keep its pixels).

    Three promises, each asserted rather than assumed:

    * never rewrites the source;
    * video keeps the source's duration, and keeps native pixels **as long as
      native pixels fit the budget** — otherwise it steps down
      `DOWNSCALE_STEPS` and says so (`scaled`, `scale`, `sourceWidth`);
    * **the result is actually under `max_mb` when that is reachable**. A
      "review copy" that is still over budget is worse than none: `build_review`
      would point the page at it and report success while the page still
      transfers the whole thing. If even the floor cannot fit, the smallest copy
      is returned with `underBudget: false` and the caller decides.

    `keep_audio=False` strips the audio track. The live stage uses it for media
    that the composition itself mutes: on the 2026-10-21 XHS master the person
    track carried a second copy of the narration (191 kbps), which alone was
    5.9MB — more than the whole 4MB budget. Dropping a track nothing plays is
    not a quality trade.
    """
    src = Path(src).resolve()
    if not src.is_file():
        raise SystemExit(f"✗ 找不到源片：{src}")

    size_mb = src.stat().st_size / 1_000_000
    if not force and not needs_copy(src, max_mb):
        return {"ok": True, "action": "skip", "reason": "already small",
                "path": str(src), "bytes": src.stat().st_size,
                "size_mb": round(size_mb, 1),
                "scaled": False, "scale": 1.0, "underBudget": True}

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
    budget = max_mb * 1_000_000
    source_size = (width, height) if has_video else None
    steps: list[float | None] = [None]
    if has_video and allow_downscale:
        steps += [s for s in DOWNSCALE_STEPS if 0 < s < 1]

    candidates: list[dict] = []
    for scale in steps:
        tmp = out.with_name(out.stem + (f".s{scale}" if scale else "") + ".part" + out.suffix)
        expect_size = scaled_size(width, height, scale) if scale else source_size
        cmd = (_video_cmd(src, tmp, crf=crf, audio_kbps=audio_kbps, gop=gop,
                          size=expect_size if scale else None,
                          keep_audio=keep_audio)
               if has_video else _audio_cmd(src, tmp))
        _encode(cmd, tmp)
        try:
            real_w, real_h = _validate(tmp, duration=duration, expect_size=expect_size,
                                       source_size=source_size)
        except SystemExit:
            tmp.unlink(missing_ok=True)
            raise
        bytes_ = tmp.stat().st_size
        candidates.append({"tmp": tmp, "scale": scale or 1.0, "scaled": scale is not None,
                           "bytes": bytes_, "width": real_w, "height": real_h})
        if bytes_ <= budget:
            break

    # Prefer the first step that fits; otherwise the smallest candidate.
    fitting = [c for c in candidates if c["bytes"] <= budget]
    best = fitting[0] if fitting else min(candidates, key=lambda c: c["bytes"])
    for candidate in candidates:
        if candidate is not best:
            candidate["tmp"].unlink(missing_ok=True)

    out_bytes = best["bytes"]
    under_budget = out_bytes <= budget
    if not under_budget and not allow_downscale:
        best["tmp"].unlink(missing_ok=True)
        raise SystemExit(
            f"✗ 原生像素压不进 {max_mb:.1f}MB 预算（{out_bytes / 1e6:.1f}MB），"
            "且已禁止降分辨率（--no-downscale）。"
            "换一份更小的源、提高 --crf，或允许降分辨率。")
    if not under_budget and out_bytes >= src.stat().st_size:
        best["tmp"].unlink(missing_ok=True)
        # Handing this over as a "审阅副本" would read as the problem being solved.
        # A copy that shrank but is still over budget is a different case: it did
        # help, so it is reported (`underBudget: false`) and the caller decides.
        raise SystemExit(
            f"✗ 审阅副本没有变小：{size_mb:.1f}MB → {out_bytes / 1e6:.1f}MB"
            f"（上限 {max_mb:.0f}MB）。这份副本解决不了问题："
            f"提高 --crf、下调 --audio-kbps，或改用 --slices 只交付当前窗口。")

    os.replace(best["tmp"], out)   # atomic: the final path never holds a partial file
    record = {"ok": True, "action": "made", "path": str(out),
              "bytes": out_bytes,
              "size_mb": round(out_bytes / 1_000_000, 1),
              "source_mb": round(size_mb, 1), "duration_s": round(duration, 3),
              "underBudget": under_budget,
              "kind": "video" if has_video else "audio",
              "width": best["width"] or None, "height": best["height"] or None,
              "sourceWidth": width or None, "sourceHeight": height or None,
              "scale": best["scale"], "scaled": bool(best["scaled"]),
              "audio": (bool(keep_audio) if has_video else True),
              "audioDropped": bool(has_video and not keep_audio),
              "crf": crf if has_video else None,
              "gop": (gop or None) if has_video else None}
    if best["scaled"]:
        record["note"] = (f"原生 {width}×{height} 压不进 {max_mb:.1f}MB 预算，"
                          f"按 {best['scale']:g}× 降到 {best['width']}×{best['height']}")
        if not under_budget:
            record["note"] += (f"；⚠ 已经降到最低仍超 {max_mb:.1f}MB 预算，"
                               "页面仍会整份搬")
    elif not under_budget:
        record["note"] = (f"已经降到最低 {best['scale']:g}× 仍超 {max_mb:.1f}MB 预算；"
                          "页面仍会整份搬")
    return record


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
    ap.add_argument("--no-downscale", action="store_true",
                    help="不允许降分辨率：原生像素压不进预算就返回失败，而不是降低画面")
    ap.add_argument("--no-audio", action="store_true",
                    help="去掉视频里的音轨（composition 自己 muted 的素材用；成片副本不要用）")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    record = make(args.src, args.out, crf=args.crf, audio_kbps=args.audio_kbps,
                  gop=args.gop, max_mb=args.max_mb, force=args.force,
                  allow_downscale=not args.no_downscale,
                  keep_audio=not args.no_audio)
    if args.json:
        print(json.dumps(record, ensure_ascii=False))
    elif record["action"] == "skip":
        print(f"无需副本：{Path(record['path']).name} 只有 {record['size_mb']}MB"
              f"（上限 {args.max_mb}MB）")
    else:
        shape = (f"{record['width']}x{record['height']}" if record.get("width")
                 else "纯音频")
        if record.get("scaled"):
            shape += f"（0.75/0.5/0.35 阶梯降到 {record['scale']:g}×）"
        if record.get("audioDropped"):
            shape += "（去音轨）"
        warn = "" if record.get("underBudget", True) else "  ⚠ 仍超上限，页面仍会整份搬"
        print(f"审阅副本 {record['source_mb']}MB → {record['size_mb']}MB  "
              f"{shape}  {record['duration_s']}s  "
              f"→ {Path(record['path']).name}{warn}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
