#!/usr/bin/env python3
"""Delivery verification — run on the RENDERED file, never on a preview.

Checks, in the order a failure would hurt:

  1. the rendered file exists and carries a video + audio stream;
  2. its duration matches the timeline the subtitles were built on — a subtitle
     file timed for a different timeline is the failure this exists for
     (building cues on the EDL's nominal total ran a delivered SRT ~1s early
     while every caption check still passed);
  3. no pure-silence interval is longer than the agreed pause budget
     (a cut or a leftover blank the viewer actually hears);
  4. the first / middle / last frames are written out for human inspection —
     a green schema is not a picture;
  5. when a delivery directory is given, every copied artefact is byte-identical
     to its working copy (two valid-looking SRTs in one project is a real trap).

Usage:
  <venv>/python helpers/verify_delivery.py <edit_dir> \
      [--video edit/final.mp4] [--deliver-dir 成品] [--max-pause 1.0] [--json]

Exit code 1 when a HARD check fails.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path


def probe(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "format=duration,size:stream=index,codec_type,codec_name,width,height,"
         "r_frame_rate,channels",
         "-of", "json", str(path)], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def srt_cues(path: Path) -> list[tuple[float, float]]:
    def sec(h: str, m: str, s: str, ms: str) -> float:
        return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000

    text = path.read_text(encoding="utf-8", errors="replace")
    cues = []
    for groups in re.findall(
            r"(\d\d):(\d\d):(\d\d),(\d\d\d) --> (\d\d):(\d\d):(\d\d),(\d\d\d)", text):
        cues.append((sec(*groups[:4]), sec(*groups[4:])))
    return cues


def silence_spans(path: Path, max_pause: float) -> list[tuple[float, float, float]]:
    out = subprocess.run(
        ["ffmpeg", "-v", "info", "-i", str(path), "-af",
         f"silencedetect=noise=-50dB:d={max_pause}", "-f", "null", "-"],
        capture_output=True, text=True).stderr
    spans, start = [], None
    for line in out.splitlines():
        m = re.search(r"silence_start: ([\d.]+)", line)
        if m:
            start = float(m.group(1))
        m = re.search(r"silence_end: ([\d.]+) \| silence_duration: ([\d.]+)", line)
        if m and start is not None:
            spans.append((start, float(m.group(1)), float(m.group(2))))
            start = None
    return spans


def measured_total(edit_dir: Path) -> tuple[float | None, str | None]:
    path = edit_dir / "segment_durations.json"
    if not path.exists():
        return None, None
    try:
        blob = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None, None
    for tag, entry in blob.items():
        if isinstance(entry, dict) and isinstance(entry.get("durations"), list):
            return round(sum(float(x) for x in entry["durations"]), 3), tag
    return None, None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("edit_dir", type=Path)
    ap.add_argument("--video", type=Path, default=None)
    ap.add_argument("--deliver-dir", type=Path, default=None)
    ap.add_argument("--max-pause", type=float, default=1.0)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    edit_dir = args.edit_dir.resolve()
    video = (args.video or (edit_dir / "final.mp4")).resolve()
    hard: list[str] = []
    warn: list[str] = []
    report: dict = {"video": str(video)}

    if not video.exists():
        print(f"  ✗ 没有可校验的成片：{video}")
        return 1

    info = probe(video)
    duration = float(info["format"]["duration"])
    streams = {s["codec_type"]: s for s in info["streams"]}
    report["duration_s"] = round(duration, 3)
    report["size_bytes"] = int(info["format"]["size"])
    print(f"成片 {video.name}：{duration:.3f}s，{info['format']['size']} bytes")
    if "video" in streams:
        v = streams["video"]
        print(f"  视频 {v['codec_name']} {v['width']}x{v['height']} {v['r_frame_rate']}")
    else:
        hard.append("成片没有视频流")
    if "audio" in streams:
        print(f"  音频 {streams['audio']['codec_name']} {streams['audio']['channels']}ch")
    else:
        hard.append("成片没有音频流")

    measured, tag = measured_total(edit_dir)
    if measured is not None:
        report["measured_total_s"] = measured
        if abs(duration - measured) > 0.5:
            hard.append(f"成片 {duration:.3f}s 与渲染记录的实测合计 {measured:.3f}s 相差 "
                        f"{duration - measured:+.3f}s——成片可能被截断或替换过")
        else:
            print(f"  时长与渲染记录（{tag}）一致（{measured:.3f}s）")

    srt = edit_dir / "subtitles.srt"
    if srt.exists():
        cues = srt_cues(srt)
        report["cues"] = len(cues)
        if cues:
            tail = cues[-1][1]
            report["srt_tail_s"] = round(tail, 3)
            print(f"  字幕 {len(cues)} 条，末条 {tail:.3f}s")
            if tail > duration + 0.05:
                hard.append(f"字幕末条 {tail:.3f}s 超出成片时长 {duration:.3f}s")
            if measured is not None and abs(tail - measured) > 1.0:
                hard.append(f"字幕末条 {tail:.3f}s 与成片实测 {measured:.3f}s 相差 "
                            f"{tail - measured:+.3f}s——字幕与成片不同步")
            gaps = [p for p in zip(cues, cues[1:]) if p[0][1] > p[1][0] + 0.001]
            if gaps:
                warn.append(f"{len(gaps)} 处字幕时间重叠")
    else:
        warn.append("没有 subtitles.srt（如果本次要独立交付字幕，这是个缺口）")

    spans = silence_spans(video, args.max_pause)
    report["long_silences"] = [round(s, 2) for s, _, _ in spans]
    print(f"  纯静音 ≥{args.max_pause}s：{len(spans)} 段")
    for s, e, g in spans:
        hard.append(f"成片 {s:.2f}-{e:.2f}s 有 {g:.2f}s 纯静音，超过 {args.max_pause}s 预算")

    frames_dir = edit_dir / "verify" / "final_frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    stamps = {"first": 0.5, "middle": duration / 2, "last": max(0.0, duration - 1.0)}
    for name, t in stamps.items():
        png = frames_dir / f"{name}_{t:.1f}s.png"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", str(video),
                        "-frames:v", "1", "-vf", "scale=540:-2", str(png)], check=True)
    print(f"  首/中/尾帧已导出 → {frames_dir.relative_to(edit_dir)} （需要人看一眼）")

    if args.deliver_dir:
        out = args.deliver_dir.resolve()
        report["deliver_dir"] = str(out)
        # A delivery copy is often renamed (e.g. 新职场体系.srt for playlist
        # auto-loading), so match by name first and by content hash otherwise —
        # "there may be multiple valid-looking SRTs" is a real trap.
        import hashlib

        SMALL = 64 * 1024 * 1024      # hash small artefacts whole
        CHUNK = 4 * 1024 * 1024

        def digest(path: Path) -> tuple[str, bool]:
            """(hash, is_full). Hashing 750MB twice over cloud storage is slow,
            so big media files get a head/middle/tail sample instead — the label
            says which one was used."""
            size = path.stat().st_size
            h = hashlib.sha256()
            if size <= SMALL:
                with path.open("rb") as fh:
                    for block in iter(lambda: fh.read(1 << 20), b""):
                        h.update(block)
                return h.hexdigest(), True
            with path.open("rb") as fh:
                for offset in (0, max(0, size // 2 - CHUNK // 2), max(0, size - CHUNK)):
                    fh.seek(offset)
                    h.update(fh.read(CHUNK))
            h.update(str(size).encode())
            return h.hexdigest(), False

        candidates = [edit_dir / n for n in ("final.mp4", "preview.mp4", "subtitles.srt",
                                             "master.srt") if (edit_dir / n).exists()]
        by_hash = {digest(c)[0]: c for c in candidates}
        for dst in sorted(p for p in out.glob("*") if p.is_file()):
            src = edit_dir / dst.name
            if not src.exists():
                src = by_hash.get(digest(dst)[0])
            if src is None:
                warn.append(f"交付目录里的 {dst.name} 在工作区找不到对应文件")
                continue
            src_hash, src_full = digest(src)
            dst_hash, _ = digest(dst)
            same = src.stat().st_size == dst.stat().st_size and src_hash == dst_hash
            label = src.name if src.name != dst.name else dst.name
            how = "逐字节一致" if src_full else "采样一致（大文件）"
            print(f"  {dst.name} ↔ {label}: {how if same else '❌ 与工作区不一致'}")
            if not same:
                hard.append(f"{dst.name} 交付副本与工作区 {label} 不一致（可能是旧版本）")

    report["hard"] = hard
    report["warn"] = warn
    report["ok"] = not hard
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for msg in hard:
            print(f"  ✗ {msg}")
        for msg in warn:
            print(f"  · {msg}")
        print("RESULT:", "OK" if not hard else f"FAIL（{len(hard)} 项）")
    return 0 if not hard else 1


if __name__ == "__main__":
    raise SystemExit(main())
