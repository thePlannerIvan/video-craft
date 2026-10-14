#!/usr/bin/env python3
"""卡点对齐：把一个词/短句定位到**输出时间轴**的秒数。

## 为什么有它

动效卡点、强调时点、字幕断句都要回答同一个问题：「这句话在第几秒」。手工按 cue 内字数
比例估算过三次（本轮实测：27.62 / 179.27 / 181.42），既慢又不可复查；而且第一次还找错了
数据源 —— `edit/caption_words.json` 的 `out_start/out_end` 是**段内按比例插值**的假时间戳
（我 0.65–0.73、最 0.73–0.81、近 0.83–0.93，均匀得像刻度尺），真实词级时间戳在
`edit/transcripts/<source>.json` 的 `words[]`（`type: "word"`）里。

## 判定顺序（并明确标注用了哪一种）

1. **exact** —— 在真实词级时间戳里连续命中该短语，取第一个字的 `out_start`。可复查。
2. **estimated** —— 词级里找不到（ASR 漏字/改写），退回 cue 内按有效字位比例估算，
   输出会**显式标注 `estimated`**，不要把它当精确值用。

时间戳是**源视频时间**，输出时间由 EDL 的段映射换算（`source_start → output_start`，段内等长）。

## 用法

    python3 helpers/align.py <project> --text "给你一个答案"
    python3 helpers/align.py <project> --text "不一样" --all        # 列出全部命中
    python3 helpers/align.py <project> --text "卧槽" --after 25 --before 30
    python3 helpers/align.py <project> --text "心流" --json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

PUNCT = re.compile(r"[\s，。、；：？！“”‘’（）()《》〈〉·—…,.!?;:'\"\[\]]+")


def norm(s: str) -> str:
    return PUNCT.sub("", s or "")


def load_segments(project: Path) -> list[dict]:
    """源时间 → 输出时间 的段映射。优先 caption_words.json 的 segments，退回 edl.json。"""
    cw = project / "edit" / "caption_words.json"
    if cw.is_file():
        segs = (json.loads(cw.read_text(encoding="utf-8")) or {}).get("segments") or []
        out = [s for s in segs if s.get("source_start") is not None and s.get("output_start") is not None]
        if out:
            return out
    edl = project / "edit" / "edl.json"
    if edl.is_file():
        doc = json.loads(edl.read_text(encoding="utf-8"))
        ranges = doc.get("ranges") or doc.get("segments") or []
        out, acc = [], 0.0
        for r in ranges:
            a, b = float(r.get("source_start", r.get("start", 0))), float(r.get("source_end", r.get("end", 0)))
            out.append({"source_start": a, "source_end": b, "output_start": acc, "output_end": acc + (b - a)})
            acc += b - a
        return out
    return []


def source_to_output(segs: list[dict], t: float) -> float | None:
    for s in segs:
        if s["source_start"] - 1e-3 <= t <= s["source_end"] + 1e-3:
            return s["output_start"] + (t - s["source_start"])
    return None


def load_words(project: Path, segs: list[dict]) -> list[dict]:
    """真实词级时间戳 → 输出时间，按输出时间排序。"""
    tdir = project / "edit" / "transcripts"
    if not tdir.is_dir():
        return []
    words: list[dict] = []
    for f in sorted(tdir.glob("*.json")):
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        for w in doc.get("words") or []:
            if w.get("type") != "word":
                continue
            a, b = source_to_output(segs, float(w["start"])), source_to_output(segs, float(w["end"]))
            if a is None or b is None:
                continue          # 落在被剪掉的区间里，输出时间轴上不存在
            words.append({"text": w.get("text") or "", "out_start": a, "out_end": b, "src": f.name})
    words.sort(key=lambda x: x["out_start"])
    return words


def load_cues(project: Path) -> list[dict]:
    f = project / "edit" / "captions.json"
    if not f.is_file():
        return []
    doc = json.loads(f.read_text(encoding="utf-8"))
    rows = doc if isinstance(doc, list) else (doc.get("captions") or doc.get("cues") or [])
    out = []
    for c in rows:
        line = c.get("line") or c.get("text") or ""
        if not line:
            continue
        out.append({"start": float(c["start"]), "end": float(c["end"]), "line": line})
    return out


def find_exact(words: list[dict], phrase: str) -> list[dict]:
    """在词序列里找连续命中。返回 [{start, end, matched}]。"""
    target = norm(phrase)
    if not target or not words:
        return []
    toks = [norm(w["text"]) for w in words]
    hits = []
    n = len(target)
    for i in range(len(toks)):
        joined, j = "", i
        while j < len(toks) and len(joined) < n:
            joined += toks[j]
            j += 1
        if joined == target:
            hits.append({"start": words[i]["out_start"], "end": words[j - 1]["out_end"],
                         "matched": "".join(w["text"] for w in words[i:j]), "src": words[i]["src"]})
        elif joined.startswith(target):
            # 末尾字被合并（例如 ASR 把两个词并成一个）：仍算命中
            hits.append({"start": words[i]["out_start"], "end": words[i]["out_end"],
                         "matched": "".join(w["text"] for w in words[i:j]), "src": words[i]["src"]})
    # 去重：同一段多次命中只留最早
    seen, uniq = set(), []
    for h in hits:
        key = round(h["start"], 2)
        if key not in seen:
            seen.add(key)
            uniq.append(h)
    return uniq


def find_estimated(cues: list[dict], phrase: str) -> list[dict]:
    target = norm(phrase)
    hits = []
    for c in cues:
        speak = norm(c["line"])
        i = speak.find(target)
        if i < 0:
            continue
        span = c["end"] - c["start"]
        t = c["start"] + span * (i / max(1, len(speak)))
        hits.append({"start": t, "end": t + span * (len(target) / max(1, len(speak))),
                     "matched": phrase, "cue": c["line"], "cue_span": [c["start"], c["end"]]})
    return hits


def main() -> int:
    ap = argparse.ArgumentParser(description="把词/短句定位到输出时间轴")
    ap.add_argument("project")
    ap.add_argument("--text", required=True, help="要定位的词或短句")
    ap.add_argument("--all", action="store_true", help="列出全部命中，不只第一个")
    ap.add_argument("--after", type=float, help="只看这个秒数之后的命中")
    ap.add_argument("--before", type=float, help="只看这个秒数之前的命中")
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    args = ap.parse_args()

    project = Path(args.project).resolve()
    segs = load_segments(project)
    words = load_words(project, segs)
    method, hits = "exact", find_exact(words, args.text)
    if not hits:
        method, hits = "estimated", find_estimated(load_cues(project), args.text)

    if args.after is not None:
        hits = [h for h in hits if h["start"] >= args.after]
    if args.before is not None:
        hits = [h for h in hits if h["start"] <= args.before]

    if args.json:
        print(json.dumps({"text": args.text, "method": method, "hits": hits}, ensure_ascii=False, indent=2))
        return 0 if hits else 1

    if not words:
        print("⚠ 没有真实词级时间戳（edit/transcripts/*.json 缺失）—— 只能退回估算")
    if not hits:
        print(f"✗ 「{args.text}」在 {method} 路径下没有命中")
        return 1
    tag = "精确（真实词级时间戳）" if method == "exact" else "**估算**（cue 内按字位比例，不可当精确值）"
    print(f"「{args.text}」 → {len(hits)} 处命中，方法：{tag}")
    for h in (hits if args.all else hits[:1]):
        print(f"  {h['start']:.3f}s – {h['end']:.3f}s   命中文本：{h['matched']}")
        if method == "estimated":
            print(f"     （cue {h['cue_span'][0]:.3f}–{h['cue_span'][1]:.3f}「{h['cue']}」）")
    if method == "exact" and len(hits) > 1 and not args.all:
        print(f"  · 另有 {len(hits) - 1} 处命中，用 --all 看全部；用 --after/--before 收敛")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
