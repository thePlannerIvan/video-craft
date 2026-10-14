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
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _edl import render_record  # noqa: E402


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
         f"silencedetect=noise=-50dB:d={max_pause}", "-f", "null", "-bitexact", "-"],
        capture_output=True, text=True).stderr
    spans, start = [], None
    for line in out.splitlines():
        # `-?` 是必须的：文件开头就静音时 ffmpeg 会报负的 silence_start，
        # 正则不收负号就会静默丢掉第一段静音（与 edl_preview_build.py 同源的坑）。
        m = re.search(r"silence_start: (-?[\d.]+)", line)
        if m:
            start = float(m.group(1))
        m = re.search(r"silence_end: (-?[\d.]+) \| silence_duration: ([\d.]+)", line)
        if m and start is not None:
            spans.append((start, float(m.group(1)), float(m.group(2))))
            start = None
    return spans


def measured_total(edit_dir: Path) -> tuple:
    """`(seconds, tag, how)` for the render record belonging to THIS EDL.

    Chosen by the EDL's sha256, never by iteration order: this project had
    accumulated `poc` / `draft` / `draft2` / `mix-base` / `final`, and reading
    the first key made a correct 84.000s film fail as "possibly truncated or
    replaced" against the POC's 12.000s.
    """
    tag, entry, how = render_record(edit_dir)
    if entry is None:
        return None, None, how
    return round(sum(float(x) for x in entry["durations"]), 3), tag, how



def audio_fingerprint(path: Path) -> str:
    """把第 0 条音轨解成 PCM 再哈希 —— 用于断言「多支成片共用同一条音轨」。

    比对编码参数不够：码率/时长相同也可能来自两次不同处理。解到 PCM 再哈希才是同一条轨道。
    """
    import hashlib
    import subprocess
    p = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a:0",
                        "-f", "s16le", "-ac", "2", "-ar", "48000", "-"],
                       capture_output=True)
    return hashlib.sha256(p.stdout).hexdigest() if p.returncode == 0 and p.stdout else ""


def check_deliverable_specs(project: Path, deliver_dir: Path,
                            hard: list, warn: list, report: dict) -> None:
    """交付规格门禁：与源音轨的声道/采样率一致、成品之间等长、共用同一音轨。

    为什么要有：本轮把 24 段音轨处理成了单声道（源是立体声）✗，而**没有任何检查发现** ——
    声道布局这种东西在最终交付上是听得出、看不出的。
    """
    src = next(iter(sorted((project / "input").glob("audio*.*"))), None)
    src_ch = src_rate = None
    if src and src.is_file():
        a = next((x for x in probe(src)["streams"] if x["codec_type"] == "audio"), None)
        if a:
            src_ch, src_rate = a.get("channels"), int(float(a.get("sample_rate") or 0))
        report["source_audio"] = {"file": src.name, "channels": src_ch, "sample_rate": src_rate}

    specs: dict = {}
    for v in sorted(deliver_dir.glob("*.mp4")):
        info = probe(v)
        a = next((x for x in info["streams"] if x["codec_type"] == "audio"), None) or {}
        specs[v.name] = {"duration_s": round(float(info["format"]["duration"]), 3),
                         "channels": a.get("channels"),
                         "sample_rate": int(float(a.get("sample_rate") or 0)),
                         "audio_sha256": audio_fingerprint(v)[:16]}
        if src_ch and a.get("channels") != src_ch:
            hard.append(f"{v.name} 声道数 {a.get('channels')} != 源音轨 {src_ch} ——"
                        f"处理音轨时不要改变声道布局（单声道化过就听不出来但已经是残次）")
        if src_rate and int(float(a.get("sample_rate") or 0)) != src_rate:
            warn.append(f"{v.name} 采样率 {a.get('sample_rate')} != 源 {src_rate}")
    report["deliverables"] = specs

    if len(specs) >= 2:
        ds = [x["duration_s"] for x in specs.values()]
        if max(ds) - min(ds) > 0.05:
            hard.append(f"成品之间时长不一致：{ {k: v['duration_s'] for k, v in specs.items()} }")
        hashes = {x["audio_sha256"] for x in specs.values() if x["audio_sha256"]}
        if len(hashes) > 1:
            hard.append("成品之间音轨不同 —— 多支成片必须共用同一条音轨")


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

    if args.deliver_dir:
        check_deliverable_specs(edit_dir.parent, args.deliver_dir.resolve(), hard, warn, report)

    measured, tag, how = measured_total(edit_dir)
    if measured is not None:
        report["measured_total_s"] = measured
        report["measured_tag"] = tag
        if how == "mismatch":
            hard.append(f"segment_durations.json[{tag}] 记录的是另一次 EDL 的渲染"
                        "（哈希不符）——按当前 EDL 重新渲染，再交付")
        elif abs(duration - measured) > 0.5:
            hard.append(f"成片 {duration:.3f}s 与渲染记录[{tag}]的实测合计 {measured:.3f}s "
                        f"相差 {duration - measured:+.3f}s——成片可能被截断或替换过")
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
                        "-frames:v", "1", "-vf", "scale=540:-2", "-bitexact", str(png)], check=True)
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

        # master.srt is not a candidate: nothing can produce it any more (the
        # --build-subtitles path was removed 2026-09-15). Listing it here implied a
        # delivered SRT might legitimately be the 2-word-chunk legacy file.
        candidates = [edit_dir / n for n in ("final.mp4", "preview.mp4", "subtitles.srt")
                      if (edit_dir / n).exists()]
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
