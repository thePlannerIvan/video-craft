#!/usr/bin/env python3
"""Scripted EDL edits with a text assertion — the safe way to cut words.

Why this exists: the first version of scripted cutting addressed words by
*filtered index*, while the transcript JSON (and caption_corrections.json) key
on the *raw* index. The two spaces differ by the number of spacing tokens, so a
correct-looking index silently deleted 18 wrong words. Index arithmetic is not
a contract anyone can check; text is.

Every deletion therefore states what it expects to remove:

    helpers/edl_edit.py <edit_dir> \\
        --delete "455.88,459.76=人处理能力的能力会变大因为AI有协助你|真实口误，双引擎复核" \\
        --delete "281.88,282.16=那|口吃重复" \\
        --restore "459.95,463.96=那么之前我们需要很多的层级是因为人的" \\
        --merge-at 104.5 \\
        --max-pause 1.0

The helper finds the words inside each interval, compares the normalized text
with the assertion, and refuses to write anything when they differ. It also
runs the EDL health check before and after, and rolls back if an edit would
introduce a NEW hard problem (a cut inside a word, a pause over budget, ...).

Backups: a single rolling `edl.previous.json` (one step back) — deliberately not
a timestamped trail, which turns into sediment.

Exit codes: 0 = applied, 1 = refused (assertion mismatch or new hard problem).
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _words import load_words, normalize, text_of, words_inside  # noqa: E402
import check_edl  # noqa: E402

PRE_PAD = 0.05        # head padding added when a span is restored
POST_PAD = 0.08       # tail padding added when a span is restored
MERGE_GAP = 0.02      # only genuinely abutting ranges are joined
MIN_RANGE = 0.30      # a range shorter than this holds no useful speech


def parse_spec(spec: str) -> tuple[float, float, str, str]:
    if "=" not in spec:
        raise SystemExit(f"--delete/--restore 需要「起点,终点=期望文本」格式，收到：{spec!r}")
    window, rest = spec.split("=", 1)
    text, _, reason = rest.partition("|")
    try:
        start_s, end_s = window.split(",")
        start, end = float(start_s), float(end_s)
    except ValueError:
        raise SystemExit(f"时间区间无法解析：{window!r}（应为 起点,终点）")
    if end <= start:
        raise SystemExit(f"时间区间 end <= start：{window!r}")
    return start, end, text.strip(), reason.strip()


def resolve_span(edit_dir: Path, source: str, start: float, end: float,
                 expected: str, what: str) -> tuple[float, float, str]:
    """Words inside [start, end]; the normalized text must match `expected`."""
    words = load_words(edit_dir, source)
    inside = words_inside(words, start, end)
    if not inside:
        raise SystemExit(f"{what} 断言失败：{start:.2f}-{end:.2f} 内没有完整词，"
                         f"期望「{expected}」。请核对时间区间来自 transcript 的真实词时间。")
    found = text_of(inside)
    if normalize(found) != normalize(expected):
        raise SystemExit(
            f"{what} 断言失败：{start:.2f}-{end:.2f}\n"
            f"  期望「{expected}」\n  实际「{found}」\n"
            "  拒绝写入。常见原因：用了过滤后的词序号（应改用时间区间+文本）、"
            "区间跨越了别的词、或词表已变化。")
    return inside[0]["start"], inside[-1]["end"], found


def split_out(ranges: list[dict], cut_start: float, cut_end: float) -> list[dict]:
    out: list[dict] = []
    for r in ranges:
        a, b = float(r["start"]), float(r["end"])
        if cut_end <= a or cut_start >= b:
            out.append(r)
            continue
        if cut_start - a > 0.05:
            out.append({**r, "start": round(a, 3), "end": round(cut_start, 3)})
        if b - cut_end > 0.05:
            out.append({**r, "start": round(cut_end, 3), "end": round(b, 3)})
    return out


def merge_neighbours(ranges: list[dict], span: tuple[float, float]) -> list[dict]:
    """Join the (start, end) span with abutting neighbours only."""
    idx = next((i for i, r in enumerate(ranges)
                if abs(float(r["start"]) - span[0]) < 1e-6
                and abs(float(r["end"]) - span[1]) < 1e-6), None)
    if idx is None:
        return ranges
    if idx > 0 and ranges[idx]["start"] - ranges[idx - 1]["end"] <= MERGE_GAP:
        ranges[idx - 1]["end"] = max(ranges[idx - 1]["end"], ranges[idx]["end"])
        ranges.pop(idx)
        idx -= 1
    if idx + 1 < len(ranges) and ranges[idx + 1]["start"] - ranges[idx]["end"] <= MERGE_GAP:
        ranges[idx]["end"] = max(ranges[idx]["end"], ranges[idx + 1]["end"])
        ranges.pop(idx + 1)
    return ranges


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("edit_dir", type=Path)
    ap.add_argument("--source", help="source key in edl.json (default: the only one)")
    ap.add_argument("--delete", action="append", default=[], metavar="START,END=TEXT[|REASON]")
    ap.add_argument("--restore", action="append", default=[], metavar="START,END=TEXT[|REASON]")
    ap.add_argument("--merge-at", action="append", default=[], type=float)
    ap.add_argument("--max-pause", type=float, default=check_edl.DEFAULT_MAX_PAUSE)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    edit_dir = args.edit_dir.resolve()
    edl_path = edit_dir / "edl.json"
    if not edl_path.exists():
        raise SystemExit(f"no edl.json in {edit_dir}")
    original = json.loads(edl_path.read_text(encoding="utf-8"))
    edl = json.loads(json.dumps(original))
    edl["sources"] = original["sources"]
    source = args.source or next(iter(original["sources"]))

    before = check_edl.check(edit_dir, args.max_pause)
    log: list[str] = []

    for spec in args.delete:
        start, end, expected, reason = parse_spec(spec)
        span_start, span_end, found = resolve_span(edit_dir, source, start, end,
                                                   expected, "删除")
        edl["ranges"] = split_out(edl["ranges"], span_start, span_end)
        log.append(f"删除 {span_start:.2f}-{span_end:.2f} 「{found}」"
                   + (f"（{reason}）" if reason else ""))

    for spec in args.restore:
        start, end, expected, reason = parse_spec(spec)
        spanned = resolve_span(edit_dir, source, start, end, expected, "恢复")
        rs = round(spanned[0] - PRE_PAD, 3)
        re_ = round(spanned[1] + POST_PAD, 3)
        edl["ranges"].append({
            "source": source, "start": rs, "end": re_,
            "beat": "RESTORED",
            "quote": spanned[2][:24],
            "reason": reason or "用户在审阅中恢复此段",
        })
        edl["ranges"].sort(key=lambda r: r["start"])
        edl["ranges"] = merge_neighbours(edl["ranges"], (rs, re_))
        log.append(f"恢复 {rs:.2f}-{re_:.2f} 「{spanned[2]}」")

    for t in args.merge_at:
        idx = next((i for i in range(len(edl["ranges"]) - 1)
                    if float(edl["ranges"][i]["end"]) <= t <= float(edl["ranges"][i + 1]["start"])),
                   None)
        if idx is None:
            raise SystemExit(f"--merge-at {t}: 找不到跨该时刻的相邻两段")
        a, b = edl["ranges"][idx], edl["ranges"][idx + 1]
        log.append(f"合并 {a['start']:.2f}-{a['end']:.2f} + {b['start']:.2f}-{b['end']:.2f}")
        a["end"] = b["end"]
        edl["ranges"].pop(idx + 1)

    if not log:
        raise SystemExit("没有任何编辑动作（--delete / --restore / --merge-at 都为空）")

    # --- structural cleanup that every edit must not have to think about ------
    words = load_words(edit_dir, source)
    kept_ranges = []
    for r in edl["ranges"]:
        a, b = float(r["start"]), float(r["end"])
        if b - a < MIN_RANGE or not words_inside(words, a, b):
            log.append(f"丢弃无完整词的碎片段 {a:.2f}-{b:.2f}（{b - a:.2f}s）")
            continue
        kept_ranges.append(r)
    edl["ranges"] = kept_ranges

    # pull boundary pauses inside the budget, in whole milliseconds
    for _ in range(4):
        fixed = False
        for i in range(len(edl["ranges"]) - 1):
            x, y = edl["ranges"][i], edl["ranges"][i + 1]
            kx = words_inside(words, float(x["start"]), float(x["end"]))
            ky = words_inside(words, float(y["start"]), float(y["end"]))
            if not kx or not ky:
                continue
            pause = (float(x["end"]) - kx[-1]["end"]) + (ky[0]["start"] - float(y["start"]))
            if pause <= args.max_pause:
                continue
            excess = pause - args.max_pause
            take_x = min(excess / 2, float(x["end"]) - kx[-1]["end"])
            take_y = min(excess - take_x, ky[0]["start"] - float(y["start"]))
            x["end"] = round(float(x["end"]) - take_x, 3)
            y["start"] = round(float(y["start"]) + take_y, 3)
            log.append(f"边界停顿 {pause:.3f}s → {pause - take_x - take_y:.3f}s（第 {i} 段）")
            fixed = True
        if not fixed:
            break

    if not edl["ranges"]:
        raise SystemExit("编辑后不剩任何片段——拒绝写入")

    edl["total_duration_s"] = round(sum(float(r["end"]) - float(r["start"])
                                       for r in edl["ranges"]), 3)

    if args.dry_run:
        for line in log:
            print(f"  · {line}")
        print(f"[dry-run] 未写入；预计 {len(edl['ranges'])} 段 / {edl['total_duration_s']:.3f}s")
        return 0

    shutil.copy2(edl_path, edit_dir / "edl.previous.json")
    edl_path.write_text(json.dumps(edl, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    after = check_edl.check(edit_dir, args.max_pause)
    new_hard = [m for m in after["hard"] if m not in before["hard"]]
    for line in log:
        print(f"  · {line}")
    print(f"EDL：{len(edl['ranges'])} 段 / {edl['total_duration_s']:.3f}s"
          f"（备份 edl.previous.json）")
    if new_hard:
        shutil.copy2(edit_dir / "edl.previous.json", edl_path)
        print("已回滚——本次编辑引入了新的硬问题：")
        for m in new_hard:
            print(f"  ✗ {m}")
        return 1
    for m in after["warn"]:
        print(f"  · {m}")
    print("体检 OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
