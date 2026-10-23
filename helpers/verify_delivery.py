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
  4. the picture has no accumulated hole: total pure-black time stays inside the
     `--max-black` budget — the one failure class where every other gate is green
     and the viewer still sees a broken film (see `black_spans`);
  5. the first / middle / last frames are written out for human inspection —
     a green schema is not a picture;
  6. when a delivery directory is given, every copied artefact is byte-identical
     to its working copy (two valid-looking SRTs in one project is a real trap);
  7. a film that was cut AGAIN after rendering must declare its cuts in
     `edit/cut-map.json`; the delivered SRT must then be reproducible from the
     pre-cut SRT plus those cuts, cue by cue (`_cutmap.verify_srt_pair`).
     Matching the master timeline is not the same as matching the delivered
     film: on the 2026-10-22 XHS series the post-cut SRT drifted up to 3.2s
     while every old check stayed green. No cut-map + film ≠ render record =
     refusal, not a guess.

Usage:
  <venv>/python helpers/verify_delivery.py <edit_dir> \
      [--video edit/final.mp4] [--deliver-dir 成品] [--max-pause 1.0] \
      [--max-black 2.0] [--json]

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
    """统一实现见 `helpers/_probe.py`（合并地图 M4）；保留旧返回形状。"""
    from _probe import probe_media
    media = probe_media(path)
    return {
        "format": {"duration": media["duration"], "size": media["size"]},
        "streams": media["streams"],
    }


def srt_cues(path: Path) -> list[tuple[float, float]]:
    """统一实现见 `helpers/_timecode.py`（合并地图 M1/M2）；畸形块保持跳过语义。"""
    from _timecode import parse_srt_file_loose
    return [(cue["startMs"] / 1000, cue["endMs"] / 1000)
            for cue in parse_srt_file_loose(path)]


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


def black_spans(path: Path, min_dur: float = 0.12,
                pix_th: float = 0.02) -> list[tuple[float, float, float]]:
    """成片里成段的纯黑画面：`(start, end, duration)`。

    ## 为什么这道门必须存在

    这是唯一一类「所有 schema 都绿、观众一眼就看出来坏了」的缺陷。实测踩到：
    合成生成器给每个「步」单独发一个 `<video>` clip，长度正好等于该步时长，
    而各步并不首尾相接——实测 37 处步间空隙、合计 12.51s（占成片 4.0%）里画面区
    什么都没有，渲染出来就是切换过程中的黑帧。当时**字幕门、静音门、时长门全部通过**，
    是作者肉眼看片发现的。

    ## 判据是「总时长预算」而不是「有黑帧即失败」

    深色设计的片子（例如蓝图底图本身就是近黑）天然含近黑帧，逐帧判黑会做成恒真告警。
    所以：报出全部黑段，由 `--max-black` 给一个**累计秒数预算**超了才失败——
    零散一两段（内容本身的瞬时黑场、源素材当时就是黑的）不触发，成片的空洞会触发。
    """
    out = subprocess.run(
        ["ffmpeg", "-v", "info", "-i", str(path), "-vf",
         f"blackdetect=d={min_dur}:pix_th={pix_th}", "-an", "-f", "null", "-bitexact", "-"],
        capture_output=True, text=True).stderr
    spans: list[tuple[float, float, float]] = []
    for m in re.finditer(
            r"black_start:(-?[\d.]+) black_end:(-?[\d.]+) black_duration:([\d.]+)", out):
        spans.append((float(m.group(1)), float(m.group(2)), float(m.group(3))))
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
                            hard: list, warn: list, report: dict,
                            source_audio: Path | None = None) -> None:
    """交付规格门禁：与源音轨的声道/采样率一致、成品之间等长、共用同一音轨。

    为什么要有：本轮把 24 段音轨处理成了单声道（源是立体声）✗，而**没有任何检查发现** ——
    声道布局这种东西在最终交付上是听得出、看不出的。
    """
    src = source_audio or next(iter(sorted((project / "input").glob("audio*.*"))), None)
    src_ch = src_rate = None
    if src and src.is_file():
        a = next((x for x in probe(src)["streams"] if x["codec_type"] == "audio"), None)
        if a:
            src_ch, src_rate = a.get("channels"), int(float(a.get("sample_rate") or 0))
        report["source_audio"] = {"file": src.name, "channels": src_ch, "sample_rate": src_rate}

    specs: dict = {}
    for v in sorted(deliver_dir.rglob("*.mp4")):
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


def post_cut_problems(edit_dir: Path, duration: float, hard: list, warn: list,
                      report: dict) -> tuple[dict | None, Path | None]:
    """二次剪成片的声明与字幕核验；返回 `(cut_map, film_srt)`。

    没有 `edit/cut-map.json` 时返回 `(None, None)`，由调用方按「成片必须是渲染
    记录那一版」处理。有声明时：成片时长必须与剪点推算一致，交付字幕必须能被
    「剪前 SRT + 剪点」逐条复算出来——**对得上母版不代表对得上交付成片**。
    """
    from _cutmap import (DURATION_TOLERANCE_S, describe, expected_film_duration_s,
                         load, paths, validate, verify_srt_pair)

    payload, problems = load(edit_dir)
    if payload is None:
        hard.extend(problems)
        return None, None
    problems += validate(payload, edit_dir.parent)
    if problems:
        hard.extend(problems)
        return payload, None

    resolved = paths(payload, edit_dir.parent)
    film_srt = resolved["srt_film"]
    expected = expected_film_duration_s(payload)
    report["cut_map"] = {
        "path": str(edit_dir / "cut-map.json"),
        "summary": describe(payload),
        "cuts": len(payload.get("cuts") or []),
        "expected_film_s": expected,
        "srt_source": str(resolved["srt_source"]),
        "srt_film": str(film_srt),
    }
    print(f"  二次剪声明：{describe(payload)}")
    if expected is not None and abs(duration - expected) > DURATION_TOLERANCE_S:
        hard.append(f"成片 {duration:.3f}s 与 cut-map 推算的 {expected:.3f}s 相差 "
                    f"{duration - expected:+.3f}s——剪点表与实际成片不是同一版")
    hard.extend(verify_srt_pair(resolved["srt_source"], film_srt, payload,
                                film_duration_s=duration))
    cues = srt_cues(film_srt)
    if cues:
        report["cues"] = len(cues)
        report["srt_tail_s"] = round(cues[-1][1], 3)
        print(f"  交付字幕 {len(cues)} 条（cut-map 声明），末条 {cues[-1][1]:.3f}s")
        if cues[-1][1] > duration + 0.05:
            hard.append(f"交付字幕末条 {cues[-1][1]:.3f}s 超出成片时长 {duration:.3f}s")
        gaps = [p for p in zip(cues, cues[1:]) if p[0][1] > p[1][0] + 0.001]
        if gaps:
            warn.append(f"{len(gaps)} 处字幕时间重叠")
    return payload, film_srt


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("edit_dir", type=Path)
    ap.add_argument("--video", type=Path, default=None)
    ap.add_argument("--deliver-dir", type=Path, default=None)
    ap.add_argument("--media", type=Path, help="本次选用的外部剪好音频；与 srt-import 来源记录比对")
    ap.add_argument("--srt", type=Path, help="本次选用的字幕；默认 edit/subtitles.srt 或外部来源字幕")
    ap.add_argument("--max-pause", type=float, default=1.0)
    ap.add_argument("--max-black", type=float, default=2.0,
                    help="成片里累计纯黑画面的秒数预算（超过即失败）。深色设计天然含近黑帧，"
                         "所以给的是总量预算而不是「有黑帧即失败」；这一步抓的是成段的画面空洞。")
    ap.add_argument("--no-audio", action="store_true",
                    help="这是无声画面轨（画面成片）：不要求音轨；声音在成片或人物轨上")
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
    elif args.no_audio:
        print("  声明为无声画面轨：不要求音轨（声音在成片或人物轨上）")
    else:
        hard.append("成片没有音频流")

    cut_map, film_srt = post_cut_problems(edit_dir, duration, hard, warn, report)
    extra_sources: dict[str, Path] = {}
    if cut_map is not None:
        extra_sources[video.name] = video
    if film_srt is not None:
        extra_sources[film_srt.name] = film_srt

    from _paths import timeline_file, timeline_span_ms
    timeline = timeline_file(edit_dir)
    timeline_doc = json.loads(timeline.read_text(encoding='utf-8')) if timeline else {}
    external = timeline_doc.get('source') == 'srt-import' or timeline_doc.get('timeSource') == 'srt-import'
    external_srt = None
    current_measured = None
    if external:
        from import_srt_timeline import source_problems
        hard.extend(source_problems(edit_dir.parent, timeline_doc, media=args.media, srt=args.srt))
        report['timeSource'] = 'srt-import'
        source_srt = timeline_doc.get('sourceSrt')
        external_srt = Path(source_srt) if source_srt else None
        if external_srt and external_srt.is_file():
            extra_sources[external_srt.name] = external_srt
        extra_sources[video.name] = video
    elif (edit_dir / 'edl.json').is_file():
        from _edl import duration_record
        try:
            edl_path = edit_dir / 'edl.json'
            count = len(json.loads(edl_path.read_text(encoding='utf-8')).get('ranges') or [])
            durations, source, _tag, problem = duration_record(edit_dir, count, edl_path, time_source='measured')
            if problem or source != 'measured' or not durations:
                hard.append(f'正式交付缺当前 EDL 的实测证据：{problem or source}')
            else:
                current_measured = (round(sum(durations), 3), _tag, 'digest')
            if timeline_doc.get('timeSource') == 'projected':
                hard.append('当前画面时间轴仍是 projected；先显式升级实测字幕并重建 timeline')
        except (ValueError, OSError) as exc:
            hard.append(f'正式交付缺当前 EDL 的实测证据：{exc}')
    if args.deliver_dir:
        media_record = (timeline_doc.get('sourceEvidence') or {}).get('media') or {}
        selected_audio = args.media or (Path(media_record['path']) if external and media_record.get('path') else None)
        check_deliverable_specs(edit_dir.parent, args.deliver_dir.resolve(), hard, warn, report, selected_audio)
    timeline_end = timeline_span_ms(timeline) if timeline is not None else None
    if timeline_end:
        expected = timeline_end / 1000
        report["timeline_end_s"] = round(expected, 3)
        if cut_map is not None:
            print(f"  画面时间轴（母版）末段 {expected:.3f}s；成片按 cut-map 是 {duration:.3f}s")
        elif abs(duration - expected) > 0.5:
            hard.append(f"成片 {duration:.3f}s 与画面时间轴末段 {expected:.3f}s "
                        f"相差 {duration - expected:+.3f}s——画面与时间轴不是同一版"
                        "（成片被二次剪过？提供 edit/cut-map.json 声明剪点，"
                        "或把剪点写回 EDL 重渲）")
        else:
            print(f"  时长与画面时间轴一致（{expected:.3f}s）")

    measured, tag, how = (None, None, 'srt-import') if external else (current_measured or measured_total(edit_dir))
    if measured is not None:
        report["measured_total_s"] = measured
        report["measured_tag"] = tag
        if how == "mismatch":
            hard.append(f"segment_durations.json[{tag}] 记录的是另一次 EDL 的渲染"
                        "（哈希不符）——按当前 EDL 重新渲染，再交付")
        elif abs(duration - measured) > 0.5:
            if cut_map is not None:
                print(f"  成片 {duration:.3f}s 比渲染记录[{tag}] {measured:.3f}s 短："
                      f"按 cut-map 二次剪（{report.get('cut_map', {}).get('summary', '')}）")
            else:
                hard.append(f"成片 {duration:.3f}s 与渲染记录[{tag}]的实测合计 {measured:.3f}s "
                            f"相差 {duration - measured:+.3f}s——成片被剪过但没有声明："
                            "把剪点写回 EDL 重渲，或提供 edit/cut-map.json"
                            "（schema 见 references/delivery.md）")
        else:
            print(f"  时长与渲染记录（{tag}）一致（{measured:.3f}s）")

    srt = args.srt or (external_srt if external else edit_dir / "subtitles.srt")
    srt = srt or edit_dir / "subtitles.srt"
    if external and (edit_dir / 'subtitles.srt').is_file() and external_srt:
        from state_fingerprint import sha256
        if sha256(edit_dir / 'subtitles.srt') != sha256(external_srt):
            hard.append('edit/subtitles.srt 与外部时间轴登记字幕不是同一版；采用当前字幕后重新导入')
    if cut_map is not None:
        # 交付字幕已由 post_cut_problems 按 cut-map 逐条核过；母版 SRT 不参与这里的比较
        if srt.exists():
            warn.append(f"{srt.name} 是剪前字幕（母版时间轴），交付用的是 cut-map 声明的"
                        f"{film_srt.name if film_srt else '剪后字幕'}")
    elif srt.exists():
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

    blacks = black_spans(video)
    total_black = sum(g for _, _, g in blacks)
    report["black_spans"] = [[round(s, 2), round(e, 2), round(g, 2)] for s, e, g in blacks]
    report["black_total_s"] = round(total_black, 2)
    print(f"  纯黑画面 ≥0.12s：{len(blacks)} 段，合计 {total_black:.2f}s"
          f"（预算 {args.max_black}s）")
    if total_black > args.max_black:
        worst = sorted(blacks, key=lambda x: -x[2])[:5]
        detail = "；".join(f"{s:.2f}-{e:.2f}s({g:.2f}s)" for s, e, g in worst)
        hard.append(
            f"成片累计纯黑画面 {total_black:.2f}s，超过 {args.max_black}s 预算"
            f"（{len(blacks)} 段，最长的几段：{detail}）——"
            "排查合成里是否给每一步单独发了媒体 clip 而各步不首尾相接（空隙处无画面）")

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
        if external:
            candidates = [video] + ([external_srt] if external_srt and external_srt.is_file() else [])
        by_hash = {digest(c)[0]: c for c in candidates}
        # 二次剪成片的工作区副本不在 edit/ 里：成片与剪后字幕由 cut-map 声明，
        # 交付目录按名字或内容哈希对回它们，而不是误报「找不到对应文件」。
        for path in extra_sources.values():
            by_hash.setdefault(digest(path)[0], path)
        for dst in sorted(p for p in out.rglob("*") if p.is_file()):
            src = edit_dir / dst.name
            if not src.exists():
                src = None
            if src is None:
                src = extra_sources.get(dst.name)
            if src is None:
                src = by_hash.get(digest(dst)[0])
            if src is None:
                message = f"交付目录里的 {dst.name} 在工作区找不到当前对应文件（可能是旧版本）"
                (hard if external and dst.suffix.lower() in ('.mp4', '.srt') else warn).append(message)
                continue
            if external and src not in candidates:
                hard.append(f'{dst.name} 不是当前外部 SRT 项目的核验交付源')
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
