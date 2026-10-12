#!/usr/bin/env python3
"""EDL health check — the pre-render gate and the edit-side evaluator.

Severity is graded, because only some defects can corrupt a delivery:

  HARD (refuse to render / refuse to deliver)
    - a cut edge lands in MEASURED SPEECH (there is audio energy at the cut)
    - a boundary pause, or a silence inside a range, exceeds --max-pause
    - a range with end <= start
    - a source file is missing
    - the EDL no longer agrees with the render that exists
      (segment_durations.json) — the字幕 desync that shipped a 1s-early SRT

  WARN (report, do not block)
    - a cut edge inside an ASR word frame that is MEASURED SILENCE — the frame is
      loose, the cut is fine (SeedASR onsets run 0.15-0.25s early; treating its
      frame as truth rejects correct cuts)
    - a range that contains no complete word (leftover silence sliver)
    - a range missing beat/quote labels (preview readability only)

Why cut edges are judged on the audio and not on the transcript: see
`_silence.py`. Both engines we use misplace word boundaries, in opposite
directions, so a transcript frame is neither necessary nor sufficient for "this
cut clips speech".

Usage:
  <venv>/python helpers/check_edl.py <edit_dir> [--max-pause 1.0] [--json] [--quiet]

Exit code 1 when any HARD problem is found, so a script or an agent can gate on
it directly. `--json` prints the machine-readable form for an evaluator.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _words import load_words, text_of, words_inside  # noqa: E402
from _edl import render_record  # noqa: E402
from _silence import measure as measure_silence  # noqa: E402

DEFAULT_MAX_PAUSE = 1.0
TIMELINE_TOLERANCE = 0.15      # seconds; EDL nominal vs measured render total
CUE_SYNC_TOLERANCE = 0.05      # seconds; cue stamp vs the caption contract


def _srt_tail(path: Path) -> float | None:
    """End timestamp (seconds) of the last cue in an SRT, or None."""
    text = path.read_text(encoding="utf-8", errors="replace")
    stamps = re.findall(r"-->\s*(\d\d):(\d\d):(\d\d),(\d\d\d)", text)
    if not stamps:
        return None
    h, m, s, ms = (int(x) for x in stamps[-1])
    return h * 3600 + m * 60 + s + ms / 1000


def _srt_cues(path: Path) -> list[tuple[float, float]]:
    """(start, end) seconds of every cue in an SRT, in file order."""
    text = path.read_text(encoding="utf-8", errors="replace")
    out = []
    for m in re.finditer(r"(\d\d):(\d\d):(\d\d),(\d\d\d)\s*-->\s*"
                         r"(\d\d):(\d\d):(\d\d),(\d\d\d)", text):
        g = [int(x) for x in m.groups()]
        out.append((g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000,
                    g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000))
    return out


def _cue_contract_mismatches(edit_dir: Path, srt_file: Path) -> list[str]:
    """Does the SRT still reproduce the caption contract it was built from?

    This is the right sync test. The previous one compared the SRT's last cue end
    against the film's total duration, which fails a perfectly synchronised SRT
    whenever the film keeps a tail after the last word (this project's TRAIL_PAD
    is 0.55s, so a 251.41s cue list in a 251.87s film was reported as "不同步").
    """
    contract = edit_dir / "captions.json"
    if not contract.exists():
        return []
    try:
        payload = json.loads(contract.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    cues = payload.get("cues") if isinstance(payload, dict) else payload
    if not isinstance(cues, list) or not cues:
        return []
    srt = _srt_cues(srt_file)
    if len(srt) != len(cues):
        return [f"subtitles.srt 有 {len(srt)} 条、captions.json 有 {len(cues)} 条"
                "——字幕与契约不同版本，重建后再交付"]
    bad: list[str] = []
    for idx in sorted({0, len(cues) // 2, len(cues) - 1}):
        want = (float(cues[idx]["start"]), float(cues[idx]["end"]))
        got = srt[idx]
        if abs(want[0] - got[0]) > CUE_SYNC_TOLERANCE or abs(want[1] - got[1]) > CUE_SYNC_TOLERANCE:
            bad.append(f"subtitles.srt 第 {idx + 1} 条 {got[0]:.3f}-{got[1]:.3f}s 与 "
                       f"captions.json 的 {want[0]:.3f}-{want[1]:.3f}s 不一致"
                       "——字幕过期，重建后再交付")
    return bad


def load_edl(edit_dir: Path) -> dict:
    path = edit_dir / "edl.json"
    if not path.exists():
        raise SystemExit(f"no edl.json in {edit_dir}")
    return json.loads(path.read_text(encoding="utf-8"))


def check(edit_dir: Path, max_pause: float = DEFAULT_MAX_PAUSE) -> dict:
    edit_dir = Path(edit_dir).resolve()
    edl = load_edl(edit_dir)
    ranges = edl["ranges"]
    sources = edl.get("sources", {})

    hard: list[str] = []
    warn: list[str] = []
    words_by_source: dict[str, list[dict]] = {}

    def words_for(source: str) -> list[dict]:
        if source not in words_by_source:
            words_by_source[source] = load_words(edit_dir, source)
        return words_by_source[source]

    silence_by_source: dict[str, object | None] = {}
    silence_errors: list[str] = []

    def silence_for(source: str):
        """Measured silence map for a source, or None when it cannot be measured."""
        if source not in silence_by_source:
            path_str = sources.get(source)
            try:
                silence_by_source[source] = (measure_silence(resolve(path_str))
                                             if path_str else None)
            except Exception as exc:                      # noqa: BLE001 - report, never pass
                silence_by_source[source] = None
                silence_errors.append(f"source '{source}'：{exc}")
        return silence_by_source[source]

    def resolve(path_str: str) -> Path:
        p = Path(path_str)
        return p if p.is_absolute() else (edit_dir / p).resolve()

    for name, path_str in sources.items():
        if not resolve(path_str).exists():
            hard.append(f"source '{name}' 不存在: {resolve(path_str)}")

    kept: list[list[dict]] = []
    for i, r in enumerate(ranges):
        start, end = float(r["start"]), float(r["end"])
        if end <= start:
            hard.append(f"range {i}: end <= start ({start:.3f}-{end:.3f})")
            kept.append([])
            continue
        words = words_for(r["source"])
        inside = words_inside(words, start, end)
        kept.append(inside)
        if not inside:
            warn.append(f"range {i}: 没有完整词（{start:.3f}-{end:.3f}，{end - start:.2f}s）")
        smap = silence_for(r["source"])
        for edge, label in ((start, "start"), (end, "end")):
            hit = next((w for w in words if w["start"] < edge < w["end"]), None)
            if smap is None:
                # Measurement unavailable: say so and fall back to the word frame,
                # which is the weaker test. Never silently pass.
                if hit is not None:
                    hard.append(f"range {i} {label} {edge:.3f} 切在词内 「{hit['text']}」"
                                f"({hit['start']:.2f}-{hit['end']:.2f})"
                                f"（无法测量静音，退回词框判据）")
                continue
            db = smap.db_at(edge)
            if smap.is_silent(edge):
                if hit is not None:
                    warn.append(
                        f"range {i} {label} {edge:.3f} 落在 ASR 词框「{hit['text']}」内，"
                        f"但实测是静音（{db:.1f}dB ≤ 阈值 {smap.threshold_db:.1f}dB）"
                        f"——词框偏松，剪点本身没问题")
                continue
            near = smap.nearest_run(edge)
            where = (f"，最近静音段 {near[0]:.3f}-{near[1]:.3f}（距 {near[2]:.3f}s）"
                     if near else "，全文没有可用静音段")
            inword = f"，且落在 ASR 词框「{hit['text']}」内" if hit is not None else ""
            hard.append(f"range {i} {label} {edge:.3f} 实测有语音"
                        f"（{db:.1f}dB > 阈值 {smap.threshold_db:.1f}dB）{inword}{where}"
                        f"——剪点会切到声音")
        if "beat" not in r or "quote" not in r:
            warn.append(f"range {i}: 缺少 beat/quote 标签（仅影响预览页可读性）")

    for i, r in enumerate(ranges):
        if not kept[i]:
            continue
        for a, b in zip(kept[i], kept[i][1:]):
            gap = b["start"] - a["end"]
            if gap > max_pause:
                hard.append(f"range {i}: 段内静音 {gap:.3f}s 超过 {max_pause}s"
                            f"（「{text_of([a])}」→「{text_of([b])}」）")

    pauses: list[tuple[int, float]] = []
    for i in range(len(ranges) - 1):
        if not kept[i] or not kept[i + 1]:
            continue
        # Both pads are clamped at 0: a word that the range only partly covers
        # still counts as kept (>=80% visible), which can make the raw
        # difference negative and hide a real pause.
        tail = max(0.0, float(ranges[i]["end"]) - kept[i][-1]["end"])
        head = max(0.0, kept[i + 1][0]["start"] - float(ranges[i + 1]["start"]))
        pause = tail + head
        pauses.append((i, pause))
        if pause > max_pause:
            hard.append(f"range {i}/{i + 1}: 边界停顿 {pause:.3f}s 超过 {max_pause}s"
                        f"（下一段首词 「{kept[i + 1][0]['text']}」）")

    nominal_total = round(sum(float(r["end"]) - float(r["start"]) for r in ranges), 3)
    measured = None
    render_stale = None
    # The record that belongs to THIS EDL, chosen by its sha256 — not by
    # iteration order over the keys the project accumulated (`poc`, `draft`,
    # `final`). Reading `poc` here printed "成片 12.000s" for an 84s film.
    tag, entry, how = render_record(edit_dir)
    if entry is None:
        ptag, pentry, _phow = render_record(edit_dir, allow_projected=True)
        if pentry is not None:
            warn.append(f"segment_durations.json[{ptag}] 只是解析预演（projected），"
                        "不是渲染证据——可用于审阅，交付前必须真实渲染")
    if how == "unparsable":
        warn.append("segment_durations.json 无法解析")
    elif how == "none" and (edit_dir / "segment_durations.json").exists():
        warn.append("segment_durations.json 是旧格式（没有 durations/edl_sha256 结构），"
                    "字幕不能据此对齐时间轴——重新渲染一次即可升级")
    if entry is not None:
        durations = entry["durations"]
        measured = round(sum(float(x) for x in durations), 3)
        if len(durations) != len(ranges):
            render_stale = (f"segment_durations.json[{tag}] 有 {len(durations)} 段，"
                            f"EDL 有 {len(ranges)} 段")
        elif how == "mismatch":
            render_stale = (f"segment_durations.json[{tag}] 记录的是另一次 EDL 的渲染"
                            "（哈希不符）")
        if render_stale:
            warn.append(f"{render_stale}——EDL 在渲染之后又改过；交付前必须重新渲染")
        elif how == "no-digest":
            warn.append(f"segment_durations.json[{tag}] 没有 edl_sha256，只能按最新一条读；"
                        "重新渲染一次即可升级")
        elif abs(measured - nominal_total) > TIMELINE_TOLERANCE:
            warn.append(
                f"EDL 标称总长 {nominal_total:.3f}s 与成片实测 {measured:.3f}s 相差 "
                f"{measured - nominal_total:+.3f}s（每段最多一帧的编码取整）。"
                "字幕按实测段时长生成即不受影响；想消除这处差异就按实测回写 EDL")

    # Delivery-polluting: an SRT timed on a timeline the video does not have.
    srt_file = edit_dir / "subtitles.srt"
    if srt_file.exists():
        # The word contract records which timeline the cues were built on
        # (captions.json is only the generated cue list).
        source = None
        for name in ("caption_words.json", "captions.json"):
            path = edit_dir / name
            if not path.exists():
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict) and payload.get("timeline_source"):
                source = payload["timeline_source"]
                break
        tail = _srt_tail(srt_file)
        if source == "nominal" and measured is not None:
            hard.append("subtitles.srt 是按 EDL 标称时间轴生成的，但成片已经存在"
                        "——重新跑 --prepare / --lock / --build，让字幕用实测段时长")
        else:
            hard.extend(_cue_contract_mismatches(edit_dir, srt_file))
            # A film legitimately keeps a tail after the last word, so "last cue
            # end == film length" is NOT the test. Cues that run PAST the picture
            # are the real defect.
            if tail is not None and measured is not None and tail > measured + TIMELINE_TOLERANCE:
                hard.append(f"subtitles.srt 末条 {tail:.3f}s 超出成片 {measured:.3f}s "
                            f"{tail - measured:+.3f}s——字幕比成片长，交付前重建")

    measured_sources = [k for k, v in silence_by_source.items() if v is not None]
    if silence_errors:
        warn.append("静音测量不可用，剪点退回词框判据：" + "；".join(silence_errors))

    result = {
        "edit_dir": str(edit_dir),
        "ranges": len(ranges),
        "silence_gate": ("measured" if measured_sources else "unavailable"),
        "silence_thresholds_db": {k: v.threshold_db
                                  for k, v in silence_by_source.items() if v is not None},
        "max_pause": max_pause,
        "nominal_total_s": nominal_total,
        "measured_total_s": measured,
        "hard": hard,
        "warn": warn,
        "max_boundary_pause_s": round(max((p for _, p in pauses), default=0.0), 3),
        "ok": not hard,
    }
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("edit_dir", type=Path)
    ap.add_argument("--max-pause", type=float, default=DEFAULT_MAX_PAUSE)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    result = check(args.edit_dir, args.max_pause)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ok"] else 1
    if not args.quiet:
        print(f"EDL 体检：{result['ranges']} 段，标称 {result['nominal_total_s']:.3f}s"
              + (f"，成片 {result['measured_total_s']:.3f}s" if result["measured_total_s"] else "")
              + f"，最大边界停顿 {result['max_boundary_pause_s']:.3f}s（上限 {args.max_pause}s）")
        for msg in result["hard"]:
            print(f"  ✗ {msg}")
        for msg in result["warn"]:
            print(f"  · {msg}")
        print("RESULT:", "OK" if result["ok"] else f"FAIL（{len(result['hard'])} 项硬失败）")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
