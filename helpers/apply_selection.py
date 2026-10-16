#!/usr/bin/env python3
"""Apply the author's word/gap selections to the EDL.

**Only edits the EDL — it does not render.** The delivery master is produced at the
"确认后输出底片" step, after the cuts are confirmed; rendering here used to happen and
no longer does (the docstring said "and re-render" long after the code stopped).

Reads selections.json (written by the word picker via POST /api/save):
  {"words": [{"src","start","end"}...],
   "pauses": [{"src","start","end","target"}...],
   "restore": [{"src","start","end"}...],
   "fixes": [{"src","start","end","text"}...]}

Rules:
- Word selections delete exactly [word.start, word.end] — cut edges land on
  word boundaries, never mid-word.
- Selections are merged only when genuinely adjacent (<= 0.02s apart); a bigger
  tolerance silently re-joined deletions of short duplicated tokens.
- Sub-ranges left with no complete word are dropped (pure-silence slivers that
  would otherwise add cut points and fades).
- A word selection is IGNORED if the word's start is not inside any current
  EDL range (e.g. a token that was already cut, or page-render padding noise).
- Pause selections keep `target` seconds of that gap (delete the excess silence).
- Restore selections un-delete a span: it is added back as a kept range and
  merged with its neighbours.
- Merged per source (overlapping/nearby < 0.12s). Each EDL range is cut
  against the intervals; surviving sub-ranges become the new EDL. Original
  EDL is backed up to edl.previous.json — the same rolling one-step-back file
  every other EDL edit writes. Three overlapping backup names (previous /
  preselection / ad-hoc pre*) meant "which file is one step back?" had three
  answers, and clean_edit_dir already classified two of them as sediment.
"""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _words import load_words, words_inside  # noqa: E402

if any(a in ("-h", "--help") for a in sys.argv[1:]):
    print(__doc__)
    print("Usage: apply_selection.py <edit_dir>")
    sys.exit(0)

EDIT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd().resolve()
# Only genuinely adjacent intervals may be joined. At 0.12s this tolerance
# re-absorbed deletions of short tokens (a 0.04s duplicated "想" left a 0.10s
# hole that got merged back), silently undoing the user's review decision.
MERGE_TOL = 0.02
MIN_SUBSEG = 0.25

edl_path = EDIT / "edl.json"
sel_path = EDIT / "selections.json"
if not sel_path.exists():
    sys.exit("no selections.json — save a selection from the word picker first")

selections = json.loads(sel_path.read_text(encoding="utf-8"))
edl = json.loads(edl_path.read_text(encoding="utf-8"))
ranges = edl["ranges"]

# word selections must anchor to a word actually inside a current range
valid_words = []
for rec in selections.get("words", []):
    s, e = rec["start"], rec["end"]
    inside = any(r["source"] == rec["src"] and r["start"] <= s <= r["end"]
                 for r in ranges)
    if inside and e - s > 0.01:
        valid_words.append(rec)
    elif not inside:
        print(f"  ignore word {rec['src'][-4:]} {s:.2f}-{e:.2f} (not in current cut)")

by_src = {}
for rec in valid_words:
    by_src.setdefault(rec["src"], []).append((rec["start"], rec["end"]))
# pauses: keep `target` seconds of each selected gap, delete the excess silence
for rec in selections.get("pauses", []):
    gs, ge, t = rec["start"], rec["end"], float(rec.get("target", 0))
    if ge - gs > t:
        by_src.setdefault(rec["src"], []).append((round(gs + t, 3), ge))


def align_gap_edges(src, ivs):
    """Gap (silence) edges measured with silencedetect can fall a few ms inside
    a word's quiet tail/onset (Scribe drift), clipping real speech. Walk the
    chain of contiguous words around an edge and extend the interval to the
    chain's word boundary. Tokens longer than 0.5s are swallowed-tail artifacts
    (Scribe pads trailing silence into the word) — never extend through those.
    """
    words = [w for w in json.loads(
        (EDIT / "transcripts" / f"{src}.json").read_text(encoding="utf-8"))["words"]
        if w["type"] == "word" and w.get("end") is not None]
    if not words:
        return ivs
    out = []
    for a, b in ivs:
        # a: extend forward through the chain starting at the word containing a
        w0 = next((w for w in words if w["start"] < a < w["end"]), None)
        if w0 is not None and (w0["end"] - w0["start"]) <= 0.5:
            cur = w0
            for w in words:
                if w["start"] > cur["end"]:
                    break
                if w["start"] <= cur["end"] + 0.05 and (w["end"] - w["start"]) <= 0.5:
                    cur = w if w["end"] > cur["end"] else cur
            a = cur["end"]
        # b: extend backward through the chain ending at the word containing b
        w0 = next((w for w in words if w["start"] < b < w["end"]), None)
        if w0 is not None and (w0["end"] - w0["start"]) <= 0.5:
            cur = w0
            for w in reversed(words):
                if w["end"] < cur["start"]:
                    break
                if w["end"] >= cur["start"] - 0.05 and (w["end"] - w["start"]) <= 0.5:
                    cur = w if w["start"] < cur["start"] else cur
            b = cur["start"]
        if b > a:
            out.append((a, b))
    return out


intervals = {}
for src, ivs in by_src.items():
    if any(rec["start"] != rec["end"] for rec in selections.get("words", [])
           if rec["src"] == src):
        # gap edges only come from silence selections; word selections are
        # already on word boundaries — but merged runs may still contain both,
        # so align the whole set (word edges are already aligned, no-op)
        ivs = align_gap_edges(src, ivs)
    ivs.sort()
    merged = []
    cur = list(ivs[0])
    for a, b in ivs[1:]:
        if a <= cur[1] + MERGE_TOL:
            cur[1] = max(cur[1], b)
        else:
            merged.append(tuple(cur))
            cur = [a, b]
    merged.append(tuple(cur))
    intervals[src] = merged

deleted_s = sum(e - s for ivs in intervals.values() for s, e in ivs)

new_ranges = []
for r in ranges:
    s, e = r["start"], r["end"]
    cuts = [(a, b) for a, b in intervals.get(r["source"], []) if b > s and a < e]
    if not cuts:
        new_ranges.append(r)
        continue
    cursor = s
    for a, b in cuts:
        if a > cursor + 0.05:
            sub = dict(r, start=cursor, end=min(a, e))
            if sub["end"] - sub["start"] >= MIN_SUBSEG:
                sub["reason"] = (sub.get("reason", "") + " | 用户选择修剪").strip(" |")
                new_ranges.append(sub)
        cursor = max(cursor, b)
        if cursor >= e:
            break
    if cursor < e - 0.05:
        sub = dict(r, start=cursor, end=e)
        if sub["end"] - sub["start"] >= MIN_SUBSEG:
            sub["reason"] = (sub.get("reason", "") + " | 用户选择修剪").strip(" |")
            new_ranges.append(sub)

old_dur = sum(r["end"] - r["start"] for r in ranges)

# restore: un-delete selected spans — add them back as kept ranges, then merge
restore_spans = selections.get("restore", [])
if restore_spans:
    for rec in restore_spans:
        new_ranges.append({"source": rec["src"],
                           "start": round(rec["start"] - 0.05, 2),
                           "end": round(rec["end"] + 0.05, 2),
                           "reason": "用户恢复"})
    new_ranges.sort(key=lambda r: (r["source"], r["start"]))
    merged_ranges = []
    for r in new_ranges:
        if merged_ranges and r["source"] == merged_ranges[-1]["source"] \
                and r["start"] <= merged_ranges[-1]["end"] + 0.12:
            merged_ranges[-1]["end"] = max(merged_ranges[-1]["end"], r["end"])
        else:
            merged_ranges.append(dict(r))
    new_ranges = merged_ranges

# Drop sub-ranges that contain no complete word: cutting between two adjacent
# deleted words leaves pure-silence slivers (0.36-0.84s in practice) that add
# cut points and 10ms fades without carrying speech.
fragments = []
kept_ranges = []
_words_cache: dict[str, list[dict]] = {}
for r in new_ranges:
    src = r["source"]
    if src not in _words_cache:
        _words_cache[src] = load_words(EDIT, src)
    if words_inside(_words_cache[src], float(r["start"]), float(r["end"])):
        kept_ranges.append(r)
    else:
        fragments.append(r)
if fragments:
    new_ranges = kept_ranges
    for r in fragments:
        print(f"  丢弃无完整词的碎片段 {r['start']:.2f}-{r['end']:.2f} "
              f"({float(r['end']) - float(r['start']):.2f}s)")

new_dur = sum(r["end"] - r["start"] for r in new_ranges)
print(f"selection: {len(valid_words)} words, {len(selections.get('pauses', []))} pauses, "
      f"{len(restore_spans)} restores → {sum(len(v) for v in intervals.values())} merged intervals, {deleted_s:.1f}s requested")
print(f"EDL: {len(ranges)} → {len(new_ranges)} ranges, "
      f"{old_dur/60:.1f} → {new_dur/60:.1f} min (removed {old_dur-new_dur:.1f}s)")

shutil.copy(edl_path, EDIT / "edl.previous.json")
edl["ranges"] = new_ranges
edl["total_duration_s"] = round(new_dur, 2)
edl_path.write_text(json.dumps(edl, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"wrote {edl_path.name} (backup: edl.previous.json)")
