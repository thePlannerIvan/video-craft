#!/usr/bin/env python3
"""Build an EDL from a keep list, snapping every cut edge to measured silence.

This is the missing verb the 2026-10 session had to re-implement in a project:
transcripts give you "keep 812.4–831.0", but cutting at those word frames clips
speech (SeedASR onsets early, Scribe tokens merge). The only ground truth is the
measured envelope in `_silence.py`.

Input (JSON, paths relative to the keep file):

    {"sources": {"SRC": "source.mp4"},
     "fps": 30,
     "keeps": [{"source": "SRC", "start": 812.4, "end": 831.0, "note": "hook"}]}

Output: <edit-dir>/edl.json (+ optional cut_text.md when --transcripts is given).

    edl_from_keep.py keeps.json --edit-dir edit/ [--snap-tol 0.35] [--no-snap]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _silence  # noqa: E402


def snap(t: float, smap: "_silence.SilenceMap", tol: float) -> tuple[float, bool]:
    """Move a cut edge onto the nearest measured silence boundary."""
    best = None
    for s0, s1 in smap.runs:
        for boundary in (s0, s1):
            d = abs(boundary - t)
            if best is None or d < best[1]:
                best = (boundary, d)
    if best is None or best[1] > tol:
        return t, False
    return round(best[0], 3), True


def main() -> int:
    ap = argparse.ArgumentParser(description="keep list → silence-snapped EDL")
    ap.add_argument("keeps", type=Path)
    ap.add_argument("--edit-dir", type=Path, required=True)
    ap.add_argument("--snap-tol", type=float, default=0.35)
    ap.add_argument("--no-snap", action="store_true")
    ap.add_argument("--transcripts", type=Path, help="optional transcripts dir for cut_text.md")
    a = ap.parse_args()

    src = json.loads(a.keeps.read_text(encoding="utf-8"))
    sources = src.get("sources") or {}
    keeps = src.get("keeps") or []
    if not sources or not keeps:
        sys.exit("keeps.json 需要非空的 sources 与 keeps")

    edit_dir: Path = a.edit_dir
    edit_dir.mkdir(parents=True, exist_ok=True)
    smaps: dict[str, "_silence.SilenceMap"] = {}
    if not a.no_snap:
        for name, rel in sources.items():
            path = (a.keeps.parent / rel).resolve()
            try:
                smaps[name] = _silence.measure(path)
            except RuntimeError as exc:
                sys.exit(f"静音测量失败（{name}）：{exc}")

    ranges, warnings = [], []
    for i, k in enumerate(keeps):
        name = k["source"]
        start, end = float(k["start"]), float(k["end"])
        if end <= start:
            sys.exit(f"keep #{i} end <= start")
        ok_s = ok_e = True
        if name in smaps:
            start, ok_s = snap(start, smaps[name], a.snap_tol)
            end, ok_e = snap(end, smaps[name], a.snap_tol)
        if not (ok_s and ok_e):
            warnings.append(f"#{i} 未找到 {a.snap_tol}s 内的静音边界，保留原值 "
                            f"{k['start']}–{k['end']}")
        item = {"source": name, "start": start, "end": end}
        for key in ("beat", "quote", "reason"):
            if k.get(key):
                item[key] = k[key]
        ranges.append(item)

    edl = {"sources": {k: str((a.keeps.parent / v).resolve()) for k, v in sources.items()},
           "ranges": ranges}
    if src.get("fps"):
        edl["fps"] = src["fps"]
    if src.get("canvas"):
        edl["canvas"] = src["canvas"]
    (edit_dir / "edl.json").write_text(json.dumps(edl, ensure_ascii=False, indent=2) + "\n",
                                       encoding="utf-8")

    if a.transcripts and a.transcripts.is_dir():
        words = []
        for t in sorted(a.transcripts.glob("*.json")):
            blob = json.loads(t.read_text(encoding="utf-8"))
            words += [w for w in blob.get("words", []) if w.get("type") == "word"]
        lines, offset = [], 0.0
        for i, r in enumerate(ranges):
            dur = r["end"] - r["start"]
            kept = [w["text"] for w in words
                    if r["start"] - 0.02 <= w.get("start", -1) <= r["end"] + 0.02]
            lines.append(f"## {i+1:02d}  [{offset:.2f}-{offset+dur:.2f}]  "
                         f"({dur:.2f}s)\n> {''.join(kept).strip()}\n")
            offset += dur
        (edit_dir / "cut_text.md").write_text("\n".join(lines), encoding="utf-8")

    total = sum(r["end"] - r["start"] for r in ranges)
    print(f"{len(ranges)} ranges, {total:.2f}s → {edit_dir/'edl.json'}")
    for w in warnings:
        print(f"  ! {w}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
