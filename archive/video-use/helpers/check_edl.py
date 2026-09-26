#!/usr/bin/env python3
"""EDL health check — the pre-render gate and the edit-side evaluator.

Severity is graded, because only some defects can corrupt a delivery:

  HARD (refuse to render / refuse to deliver)
    - a cut edge lands inside a word
    - a boundary pause, or a silence inside a range, exceeds --max-pause
    - a range with end <= start
    - a source file is missing
    - the EDL no longer agrees with the render that exists
      (segment_durations.json) — the字幕 desync that shipped a 1s-early SRT

  WARN (report, do not block)
    - a range that contains no complete word (leftover silence sliver)
    - a range missing beat/quote labels (preview readability only)

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
from _edl import edl_digest  # noqa: E402

DEFAULT_MAX_PAUSE = 1.0
TIMELINE_TOLERANCE = 0.15      # seconds; EDL nominal vs measured render total


def _srt_tail(path: Path) -> float | None:
    """End timestamp (seconds) of the last cue in an SRT, or None."""
    text = path.read_text(encoding="utf-8", errors="replace")
    stamps = re.findall(r"-->\s*(\d\d):(\d\d):(\d\d),(\d\d\d)", text)
    if not stamps:
        return None
    h, m, s, ms = (int(x) for x in stamps[-1])
    return h * 3600 + m * 60 + s + ms / 1000


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
        for edge, label in ((start, "start"), (end, "end")):
            hit = next((w for w in words if w["start"] < edge < w["end"]), None)
            if hit is not None:
                hard.append(f"range {i} {label} {edge:.3f} 切在词内 「{hit['text']}」"
                            f"({hit['start']:.2f}-{hit['end']:.2f})")
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
    dur_file = edit_dir / "segment_durations.json"
    if dur_file.exists():
        try:
            blob = json.loads(dur_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            blob = {}
            warn.append("segment_durations.json 无法解析")
        entries = [(tag, v) for tag, v in blob.items()
                   if isinstance(v, dict) and isinstance(v.get("durations"), list)]
        if blob and not entries:
            warn.append("segment_durations.json 是旧格式（没有 durations/edl_sha256 结构），"
                        "字幕不能据此对齐时间轴——重新渲染一次即可升级")
        if entries:
            tag, entry = entries[0]
            durations = entry["durations"]
            measured = round(sum(float(x) for x in durations), 3)
            if len(durations) != len(ranges):
                render_stale = (f"segment_durations.json[{tag}] 有 {len(durations)} 段，"
                                f"EDL 有 {len(ranges)} 段")
            elif entry.get("edl_sha256") and entry["edl_sha256"] != edl_digest(edit_dir / "edl.json"):
                render_stale = "segment_durations.json 记录的是另一次 EDL 的渲染（哈希不符）"
            if render_stale:
                warn.append(f"{render_stale}——EDL 在渲染之后又改过；交付前必须重新渲染")
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
        elif tail is not None and measured is not None and abs(tail - measured) > TIMELINE_TOLERANCE:
            hard.append(f"subtitles.srt 末条 {tail:.3f}s 与成片 {measured:.3f}s 相差 "
                        f"{tail - measured:+.3f}s——字幕与成片不同步，重建字幕后再交付")

    result = {
        "edit_dir": str(edit_dir),
        "ranges": len(ranges),
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
