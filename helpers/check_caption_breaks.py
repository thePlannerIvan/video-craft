#!/usr/bin/env python3
"""Catch the "pack text into 20-character boxes" failure in a caption line plan.

Why this exists
---------------
On 2026-09-21 a line plan was produced by greedily packing clauses up to a
20-character ceiling and cutting wherever the ceiling hit. Every cue was under
the limit, `srt_export.py --check` was green, and the result still read as
garbage: `Adidas 有 7,618` / `条`, `分` / `析`, `总共` / `有 21 页`. The spec was
never "fit 20 characters" — it is *one cue per natural clause, punctuation
breaks are mandatory, and the ceiling only forces a second break inside a clause
that is itself too long.* Nothing in the pipeline could tell the two apart, so
this gate looks for the signature of packing.

Checks
------
  hard  cue ends with a digit and no punctuation         → a number lost its unit
  warn  cue ends with a Latin letter and no punctuation  → may be a cut token
  hard  next cue starts with a measure word             → split a number from its unit
  hard  cue content length > 20                          → over the ceiling
  warn  cue ends without punctuation and the sentence    → cut mid-sentence
        continues in the next cue
  warn  cue content length < 5                           → orphan cue

Usage
-----
    check_caption_breaks.py <edit_dir|semantic_lines.txt|subtitles.srt> [--json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

MEASURE = "条个页字张份次名位层句块组天年月日点分秒人场家款支台"
TERMINAL = "。！？…"
PUNCT = "，。、；：？！"


def content_len(s: str) -> int:
    return len(re.sub(r"[\s，。、；：？！]", "", s))


def load_cues(target: Path) -> list[str]:
    if target.is_dir():
        for name in ("semantic_lines.txt", "subtitles.srt"):
            f = target / name
            if f.exists():
                target = f
                break
        else:
            raise SystemExit(f"no semantic_lines.txt / subtitles.srt in {target}")
    text = target.read_text(encoding="utf-8")
    if target.suffix == ".srt":
        cues = []
        for block in text.strip().split("\n\n"):
            lines = [l for l in block.split("\n") if l.strip()]
            if len(lines) >= 3:
                cues.append(" ".join(lines[2:]).strip())
        return cues
    return [l.strip() for l in text.split("\n") if l.strip()]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    cues = load_cues(Path(a.path))
    hard, warn = [], []
    for i, c in enumerate(cues):
        n = content_len(c)
        nxt = cues[i + 1] if i + 1 < len(cues) else ""
        if n > 20:
            hard.append(f"#{i + 1} 超 20 字（{n}）：{c}")
        bare = c.rstrip()
        if bare and bare[-1] not in PUNCT and re.search(r"[0-9]$", bare):
            hard.append(f"#{i + 1} 结尾是数字且没有标点，量词被切掉了：{c}")
        elif bare and bare[-1] not in PUNCT and re.search(r"[A-Za-z]$", bare):
            warn.append(f"#{i + 1} 结尾是拉丁字母且没有标点，确认这个单词是完整的：{c}")
        if nxt and c.rstrip() and c.rstrip()[-1] in "0123456789" and nxt[0] in MEASURE:
            hard.append(f"#{i + 1}→#{i + 2} 把数字和量词切开：{c} | {nxt}")
        if n < 5 and len(cues) > 1:
            warn.append(f"#{i + 1} 只有 {n} 字，像是孤块：{c}")
        if nxt and c and c[-1] not in PUNCT and c[-1] not in TERMINAL:
            warn.append(f"#{i + 1} 结尾没有标点，下一句还接着：{c} | {nxt}")

    if a.json:
        print(json.dumps({"cues": len(cues), "hard": hard, "warn": warn}, ensure_ascii=False, indent=2))
    else:
        print(f"字幕断句体检：{len(cues)} 条")
        for m in warn:
            print(f"  · {m}")
        for m in hard:
            print(f"  ✗ {m}")
        print("RESULT:", "OK" if not hard else f"FAIL（{len(hard)} 项硬失败）")
    return 0 if not hard else 1


if __name__ == "__main__":
    raise SystemExit(main())
