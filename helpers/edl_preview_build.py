#!/usr/bin/env python3
"""Build edl_preview.html in <edit_dir> — browser timeline & transcript NLE
workbench for reviewing and refining the edited cut.

Usage: edl_preview_build.py <edit_dir>
       edl_review_surface.py <edit_dir>         # 写 surface + 起审阅宿主（公共缝）

Reads edl.json (+ sources) and, when present, subtitles.srt (the article-first
delivery file) (output-timeline subtitles). Plays the cut directly from the
SOURCE clips — no render needed — by mapping the output timeline to segment +
source offset:

  output time T → segment i (offset_i <= T < offset_i+1)
                 → source clip at start_i + (T - offset_i)
"""
import json
import re
import subprocess
import sys
from pathlib import Path

if any(a in ("-h", "--help") for a in sys.argv[1:]):
    print(__doc__)
    print("Usage: edl_preview_build.py <edit_dir>")
    sys.exit(0)

EDIT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd().resolve()

edl = json.load(open(EDIT / "edl.json", encoding="utf-8"))
SRC_MAP = {k: (EDIT / v).resolve() if not Path(v).is_absolute() else Path(v).resolve()
           for k, v in edl["sources"].items()}
total = round(sum((r["end"] - r["start"]) / r.get("speed", 1.0) for r in edl["ranges"]), 2)

PREVIEW_VIDEO = next(
    (EDIT / n for n in ("final.mp4", "preview.mp4", "screen_final.mp4", "final_master.mp4")
     if (EDIT / n).exists()),
    None,
)
USE_RENDERED = PREVIEW_VIDEO is not None
PREVIEW_KEY = "__PREVIEW__"

ROOT = Path(__file__).resolve()
try:
    ROOT = Path(__import__("os").path.commonpath([EDIT, *SRC_MAP.values()]))
except ValueError:
    ROOT = EDIT
PAGE_REL = EDIT.relative_to(ROOT) / "edl_preview.html"

segments = []
offset = 0.0
for r in edl["ranges"]:
    s, e = r["start"], r["end"]
    speed = r.get("speed", 1.0)
    out0, out1 = offset, offset + (e - s) / speed
    if USE_RENDERED:
        p_start, p_end, p_speed = round(out0, 3), round(out1, 3), 1
    else:
        p_start, p_end, p_speed = round(s, 3), round(e, 3), speed
    segments.append({
        "src": PREVIEW_KEY if USE_RENDERED else r["source"],
        "orig_src": r["source"],
        "label": PREVIEW_VIDEO.name if USE_RENDERED else SRC_MAP[r["source"]].name,
        "start": p_start, "end": p_end,
        "o0": round(out0, 3), "o1": round(out1, 3),
        "speed": p_speed,
        "beat": r.get("beat", ""), "quote": r.get("quote", ""),
        "reason": r.get("reason", ""),
    })
    offset = out1

if USE_RENDERED:
    src_map_web = {PREVIEW_KEY: "/" + PREVIEW_VIDEO.relative_to(ROOT).as_posix()}
else:
    src_map_web = {k: "/" + v.relative_to(ROOT).as_posix() for k, v in SRC_MAP.items()}


def parse_srt(path: Path) -> list[dict]:
    txt = path.read_text(encoding="utf-8", errors="replace")
    cues, cur = [], None
    for line in txt.splitlines():
        m = re.match(r"(\d+):(\d+):(\d+)[,.](\d+) --> (\d+):(\d+):(\d+)[,.](\d+)", line)
        if m:
            def to_sec(a, b, c, d):
                return int(a) * 3600 + int(b) * 60 + int(c) + int(d) / 1000
            s0, s1 = to_sec(*m.groups()[:4]), to_sec(*m.groups()[4:])
            cur = {"s": round(s0, 3), "e": round(s1, 3), "t": ""}
            cues.append(cur)
        elif cur is not None and line.strip() and not line.strip().isdigit():
            cur["t"] += line.strip()
        elif cur is not None and not line.strip():
            cur = None
    return cues


cues = []
for cand in ("subtitles.srt",):
    if (EDIT / cand).exists():
        cues = parse_srt(EDIT / cand)
        break

MIN_GAP = 0.15
LONG_GAP = 0.5
NOISE_DB = -25


def real_silences(src_path, seg_start, seg_end):
    dur = seg_end - seg_start
    cmd = ["ffmpeg", "-ss", str(seg_start), "-t", str(dur), "-i", str(src_path),
           "-af", f"silencedetect=noise={NOISE_DB}dB:d=0.15", "-f", "null", "-bitexact", "-"]
    out = subprocess.run(cmd, capture_output=True, text=True).stderr
    starts = [float(m) for m in re.findall(r"silence_start: (-?[\d.]+)", out)]
    ends = [float(m) for m in re.findall(r"silence_end: (-?[\d.]+)", out)]
    if len(ends) < len(starts):
        ends.append(seg_end - seg_start)
    pairs = []
    for a, b in zip(starts, ends):
        s0, s1 = max(seg_start, a + seg_start), min(seg_end, b + seg_start)
        if s1 - s0 >= MIN_GAP:
            pairs.append((s0, s1))
    return pairs


fixes = {}
sel_file = EDIT / "selections.json"
if sel_file.exists():
    for fx in json.loads(sel_file.read_text(encoding="utf-8")).get("fixes", []):
        fixes[f"{fx['src']}|{fx['start']}|{fx['end']}"] = fx["text"]

trans = {}
for k in SRC_MAP:
    tf = EDIT / "transcripts" / f"{k}.json"
    if tf.exists():
        trans[k] = [w for w in json.load(open(tf, encoding="utf-8"))["words"]
                    if w.get("type", "word") != "spacing"]

gidx = 0
for i, r in enumerate(edl["ranges"]):
    src = r["source"]
    s, e = r["start"], r["end"]
    speed = r.get("speed", 1.0)
    src_words = trans.get(src, [])
    words = [w for w in src_words
             if w["end"] > s and w["start"] < e
             and (min(w["end"], e) - max(w["start"], s)) >= 0.8 * (w["end"] - w["start"])]
    items = []
    for w in words:
        key = f"{src}|{w['start']}|{w['end']}"
        items.append({
            "t": fixes.get(key, w["text"]), "f": key in fixes,
            "ws": round(w["start"], 3), "we": round(w["end"], 3), "g": gidx,
            "o0": round(max(0.0, (w["start"] - s) / speed) + segments[i]["o0"], 3),
            "o1": round((min(e, w["end"]) - s) / speed + segments[i]["o0"], 3),
        })
        gidx += 1
    gaps = []
    for a, b in zip(items, items[1:]):
        g = b["ws"] - a["we"]
        if g >= 0.25:
            gaps.append({
                "gs": round(a["we"], 3), "ge": round(b["ws"], 3),
                "o0": round((a["o1"] + b["o0"]) / 2, 3), "long": g > 1.0,
            })
    segments[i]["items"] = items
    segments[i]["gaps"] = gaps


def covered_fraction(w, s, e):
    return max(0.0, min(w["end"], e) - max(w["start"], s))


deleted = []
for src, src_words in trans.items():
    cov = sorted((r["start"], r["end"]) for r in edl["ranges"] if r["source"] == src)
    mc = []
    if cov:
        cur = list(cov[0])
        for a, b in cov[1:]:
            if a <= cur[1]:
                cur[1] = max(cur[1], b)
            else:
                mc.append(tuple(cur))
                cur = [a, b]
        mc.append(tuple(cur))
    chunks, cur_chunk = [], []
    for w in src_words:
        visible = max((covered_fraction(w, s, e) for s, e in mc), default=0.0)
        if visible >= 0.8 * (w["end"] - w["start"]):
            if cur_chunk:
                chunks.append(cur_chunk)
                cur_chunk = []
            continue
        if cur_chunk and w["start"] - cur_chunk[-1]["end"] > 0.5:
            chunks.append(cur_chunk)
            cur_chunk = []
        cur_chunk.append(w)
    if cur_chunk:
        chunks.append(cur_chunk)
    for ch in chunks:
        deleted.append({
            "src": src,
            "start": round(ch[0]["start"], 2),
            "end": round(ch[-1]["end"], 2),
            "text": "".join(w["text"] for w in ch)[:70],
            "words": [{"ws": round(w["start"], 3), "we": round(w["end"], 3),
                       "t": w["text"]} for w in ch],
        })
for ci, ch in enumerate(deleted):
    ch["ci"] = ci

for ch in deleted:
    after = -1
    for i, r in enumerate(edl["ranges"]):
        if r["source"] == ch["src"] and r["end"] <= ch["start"]:
            after = i
    ch["after_seg"] = after

HTML = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<!-- 审阅桥的注入点：**裸标记独占一行，全页只此一次**（R3）。宿主 serve 时把它原地换成桥本身。 -->
{{REVIEW_BRIDGE}}
<title>粗剪工作台 · EDL 时间线与逐字精修</title>
<style>
  :root {
    --bg-canvas: #090a0f;
    --bg-panel: #11131a;
    --bg-card: #161923;
    --bg-elevated: #1d2130;
    --border-subtle: #232838;
    --border-strong: #32394e;
    --text-primary: #eef0f6;
    --text-secondary: #9da4b8;
    --text-muted: #687086;
    --accent-amber: #f59e0b;
    --accent-blue: #3b82f6;
    --accent-crimson: #e5484d;
    --accent-emerald: #10b981;
  }
  * { box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Noto Sans SC", "Inter", sans-serif;
    background: var(--bg-canvas);
    color: var(--text-primary);
    margin: 0;
    padding: 0 0 48px;
    min-width: 1240px;
  }
  /* ── Top Studio Bar ── */
  #bar {
    position: sticky;
    top: 0;
    z-index: 30;
    background: rgba(17, 19, 26, 0.92);
    backdrop-filter: blur(12px);
    border-bottom: 1px solid var(--border-subtle);
    padding: 10px 24px;
    display: flex;
    gap: 10px;
    align-items: center;
    flex-wrap: wrap;
  }
  .brand-title {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-right: 8px;
  }
  .brand-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--accent-amber);
    box-shadow: 0 0 8px rgba(245, 158, 11, 0.6);
  }
  #bar b { font-size: 14px; font-weight: 600; letter-spacing: 0.02em; }
  .bar-divider { width: 1px; height: 18px; background: var(--border-subtle); margin: 0 4px; }
  #stats {
    font-size: 12px;
    color: var(--text-secondary);
    font-variant-numeric: tabular-nums;
    background: var(--bg-card);
    border: 1px solid var(--border-subtle);
    padding: 4px 10px;
    border-radius: 999px;
  }
  #net {
    margin-left: auto;
    font-size: 12px;
    color: var(--text-secondary);
    background: var(--bg-card);
    border: 1px solid var(--border-subtle);
    padding: 4px 10px;
    border-radius: 999px;
  }
  /* R11：刷新入口无条件存在，写成纯 HTML 链接（空 href ＝重载当前地址） */
  #page-reload {
    font-size: 12px;
    color: var(--text-secondary);
    text-decoration: none;
    background: var(--bg-card);
    border: 1px solid var(--border-strong);
    border-radius: 6px;
    padding: 5px 11px;
    transition: all 0.15s ease;
  }
  #page-reload:hover { color: var(--text-primary); border-color: var(--accent-amber); }

  #staleness {
    margin: 0;
    padding: 10px 24px;
    font-size: 13px;
    line-height: 1.6;
    color: #ffd9a8;
    background: #3b230c;
    border-bottom: 1px solid #6a4520;
  }
  #staleness[hidden] { display: none; }

  button {
    padding: 5px 12px;
    border: 1px solid var(--border-strong);
    border-radius: 6px;
    background: var(--bg-card);
    color: var(--text-primary);
    cursor: pointer;
    font-size: 13px;
    font-weight: 500;
    transition: all 0.15s ease;
  }
  button:hover { background: var(--bg-elevated); border-color: #46506e; }
  button.on {
    background: rgba(59, 130, 246, 0.18);
    border-color: var(--accent-blue);
    color: #93c5fd;
  }
  button.primary-cta {
    background: var(--accent-amber);
    border-color: var(--accent-amber);
    color: #090a0f;
    font-weight: 600;
  }
  button.primary-cta:hover { background: #fbbf24; border-color: #fbbf24; }
  select {
    background: var(--bg-card);
    color: var(--text-primary);
    border: 1px solid var(--border-strong);
    border-radius: 6px;
    font-size: 12px;
    padding: 5px 8px;
  }

  /* ── 2-Column NLE Workbench Layout ── */
  #wrap {
    max-width: 1640px;
    margin: 0 auto;
    padding: 16px 24px;
    display: grid;
    grid-template-columns: minmax(520px, 1fr) 540px;
    gap: 22px;
    align-items: start;
  }
  #left { min-width: 0; display: flex; flex-direction: column; gap: 14px; }

  /* ── Monitor Stage ── */
  #stage {
    position: relative;
    background: #000;
    border: 1px solid var(--border-subtle);
    border-radius: 12px;
    overflow: hidden;
    box-shadow: 0 12px 32px rgba(0, 0, 0, 0.45);
  }
  #stage video { width: 100%; display: block; max-height: 540px; object-fit: contain; background: #040508; }
  #capbar {
    position: absolute;
    left: 24px;
    right: 24px;
    bottom: 16px;
    padding: 8px 16px;
    background: rgba(9, 10, 15, 0.82);
    backdrop-filter: blur(6px);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 8px;
    color: #fff;
    font-size: 17px;
    font-weight: 500;
    text-align: center;
    min-height: 40px;
    display: flex;
    align-items: center;
    justify-content: center;
    pointer-events: none;
  }
  #capbar.empty { display: none; }

  /* ── NLE Timeline Scrubber ── */
  .timeline-card {
    background: var(--bg-panel);
    border: 1px solid var(--border-subtle);
    border-radius: 10px;
    padding: 12px 14px 10px;
  }
  .timeline-head {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 8px;
    font-size: 12px;
    color: var(--text-secondary);
  }
  #ruler {
    position: relative;
    height: 68px;
    background: #0c0e14;
    border: 1px solid var(--border-subtle);
    border-radius: 8px;
    overflow: hidden;
    cursor: ew-resize;
    user-select: none;
    touch-action: none;
  }
  #blocks { position: absolute; inset: 8px 0 20px 0; }
  .seg-block {
    position: absolute;
    top: 0;
    bottom: 0;
    border-right: 1px solid #090a0f;
    border-radius: 4px;
    display: flex;
    align-items: center;
    padding: 0 7px;
    overflow: hidden;
    white-space: nowrap;
    font-size: 11px;
    font-weight: 500;
    color: rgba(255, 255, 255, 0.92);
    transition: filter 0.12s ease;
  }
  .seg-block:hover { filter: brightness(1.12); }
  .seg-block .d { opacity: 0.72; margin-left: 5px; font-variant-numeric: tabular-nums; font-size: 10px; }
  .seg-block.active {
    outline: 2px solid var(--accent-amber);
    outline-offset: -2px;
    z-index: 2;
    box-shadow: inset 0 0 12px rgba(245, 158, 11, 0.25);
  }
  #ticks {
    position: absolute;
    left: 0;
    right: 0;
    bottom: 0;
    height: 18px;
    background: rgba(255, 255, 255, 0.02);
    border-top: 1px solid rgba(255, 255, 255, 0.04);
  }
  .tick { position: absolute; bottom: 0; height: 6px; width: 1px; background: var(--border-strong); }
  .tick span {
    position: absolute;
    bottom: 6px;
    left: 4px;
    font-size: 10px;
    color: var(--text-muted);
    font-variant-numeric: tabular-nums;
  }
  #playhead {
    position: absolute;
    top: 0;
    bottom: 0;
    width: 2px;
    background: var(--accent-amber);
    z-index: 4;
    pointer-events: none;
    box-shadow: 0 0 8px rgba(245, 158, 11, 0.6);
  }
  #playhead .hd {
    position: absolute;
    top: 0;
    left: -5px;
    border: 6px solid transparent;
    border-top: 8px solid var(--accent-amber);
  }
  #ptime {
    position: absolute;
    top: 2px;
    left: 6px;
    padding: 1px 5px;
    font-size: 10px;
    font-weight: 600;
    color: #090a0f;
    background: var(--accent-amber);
    border-radius: 3px;
    font-variant-numeric: tabular-nums;
    pointer-events: none;
    white-space: nowrap;
  }
  #hint { font-size: 11px; color: var(--text-muted); margin-top: 8px; }

  /* ── Segment Metadata Inspector ── */
  #info {
    display: grid;
    grid-template-columns: 150px 1fr;
    gap: 10px 16px;
    padding: 12px 16px;
    background: var(--bg-panel);
    border: 1px solid var(--border-subtle);
    border-radius: 10px;
    font-size: 13px;
    color: var(--text-secondary);
  }
  #info .lbl {
    color: var(--text-muted);
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    margin-bottom: 3px;
  }
  #info .beat { color: var(--accent-amber); font-weight: 600; }

  /* ── Overall Direction Note ── */
  #overall {
    display: flex;
    gap: 10px;
    align-items: center;
    padding: 12px 16px;
    background: var(--bg-panel);
    border: 1px solid var(--border-subtle);
    border-radius: 10px;
  }
  #overall b { font-size: 13px; color: var(--text-primary); white-space: nowrap; }
  #ov-text {
    flex: 1 1 auto;
    min-height: 36px;
    padding: 7px 11px;
    background: var(--bg-card);
    color: var(--text-primary);
    border: 1px solid var(--border-strong);
    border-radius: 6px;
    font: inherit;
    font-size: 13px;
    resize: vertical;
  }
  #ov-text:focus { outline: none; border-color: var(--accent-amber); }
  #ov-state { font-size: 12px; color: var(--text-muted); white-space: nowrap; }

  #cues {
    max-height: 180px;
    overflow-y: auto;
    background: var(--bg-panel);
    border: 1px solid var(--border-subtle);
    border-radius: 10px;
    padding: 6px;
  }
  .cue {
    display: flex;
    gap: 10px;
    padding: 5px 8px;
    border-bottom: 1px solid var(--border-subtle);
    font-size: 13px;
    cursor: pointer;
    border-radius: 5px;
  }
  .cue:hover { background: var(--bg-card); }
  .cue .ct { color: var(--text-muted); font-variant-numeric: tabular-nums; flex-shrink: 0; }

  /* ── Right Column: Transcript & Word Editor ── */
  #side {
    background: var(--bg-panel);
    border: 1px solid var(--border-subtle);
    border-radius: 12px;
    padding: 16px;
    position: sticky;
    top: 62px;
  }
  .side-head {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding-bottom: 10px;
    border-bottom: 1px solid var(--border-subtle);
  }
  .side-head b { font-size: 15px; font-weight: 600; }
  #wstats {
    font-size: 12px;
    color: var(--accent-amber);
    background: rgba(245, 158, 11, 0.12);
    border: 1px solid rgba(245, 158, 11, 0.3);
    padding: 3px 9px;
    border-radius: 999px;
    font-variant-numeric: tabular-nums;
  }
  .side-actions {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
    margin: 12px 0 8px;
    align-items: center;
  }
  #w-hint {
    font-size: 12px;
    color: var(--text-secondary);
    background: var(--bg-card);
    border: 1px solid var(--border-subtle);
    border-radius: 8px;
    padding: 8px 11px;
    margin: 8px 0 12px;
    line-height: 1.65;
  }
  #w-root {
    overflow-y: auto;
    max-height: calc(100vh - 280px);
    padding-right: 4px;
  }
  #w-root::-webkit-scrollbar { width: 6px; }
  #w-root::-webkit-scrollbar-thumb { background: var(--border-strong); border-radius: 3px; }
  .wseg {
    margin: 10px 0;
    padding: 12px 14px;
    background: var(--bg-card);
    border: 1px solid var(--border-subtle);
    border-radius: 10px;
    transition: border-color 0.15s ease;
  }
  .wseg.active {
    border-color: rgba(245, 158, 11, 0.65);
    box-shadow: 0 0 0 1px rgba(245, 158, 11, 0.2);
  }
  .wseg-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    font-size: 12px;
    color: var(--text-secondary);
    margin-bottom: 8px;
    padding-bottom: 6px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.04);
  }
  .wseg-head b { color: var(--text-primary); }
  .wseg-jump {
    padding: 2px 8px;
    font-size: 11px;
    border-radius: 999px;
    background: var(--bg-elevated);
    border: 1px solid var(--border-strong);
    color: var(--text-secondary);
    font-variant-numeric: tabular-nums;
  }
  .wseg-jump:hover { color: var(--accent-amber); border-color: var(--accent-amber); }

  .w {
    display: inline-block;
    padding: 1px 2px;
    margin: 1px 0;
    border-radius: 4px;
    cursor: pointer;
    font-size: 15px;
    line-height: 1.85;
    user-select: none;
    transition: background 0.08s ease, color 0.08s ease;
  }
  .w:hover { background: rgba(59, 130, 246, 0.22); }
  .w.del {
    background: rgba(229, 72, 77, 0.88);
    color: #fff;
    text-decoration: line-through;
  }
  .w.cut {
    color: #f87171;
    text-decoration: line-through;
    opacity: 0.72;
    font-size: 13px;
  }
  .w.cut:hover { background: rgba(229, 72, 77, 0.2); color: var(--text-primary); opacity: 1; }
  .w.cut.restored {
    color: #34d399;
    text-decoration: none;
    opacity: 1;
    background: rgba(16, 185, 129, 0.18);
    border-bottom: 1px solid #10b981;
  }
  .cutdiv {
    margin: 8px 0 4px;
    padding: 6px 10px;
    border-left: 3px solid rgba(229, 72, 77, 0.45);
    background: rgba(9, 10, 15, 0.55);
    border-radius: 0 6px 6px 0;
    font-size: 13px;
    line-height: 1.8;
  }
  body.hidecut .cutdiv { display: none; }
  .w.drag { background: var(--accent-blue); color: #fff; }
  .w.drag-undo { background: var(--accent-emerald); color: #090a0f; }
  .w.playing {
    background: var(--accent-amber);
    color: #090a0f;
    border-radius: 4px;
    padding: 1px 4px;
    font-weight: 700;
    box-shadow: 0 0 0 2px rgba(245, 158, 11, 0.45);
  }
  .w.fixed { border-bottom: 2px dashed #38bdf8; color: #7dd3fc; }
  .gap {
    display: inline-block;
    cursor: pointer;
    font-size: 10px;
    color: var(--text-muted);
    padding: 0 3px;
    margin: 0 1px;
    vertical-align: middle;
    border-radius: 4px;
    user-select: none;
  }
  .gap:hover { color: var(--text-primary); background: var(--bg-elevated); }
  .gap.del { background: var(--accent-crimson); color: #fff; text-decoration: line-through; }
  .gap.long {
    color: var(--accent-amber);
    font-size: 10px;
    font-weight: 600;
    background: rgba(245, 158, 11, 0.12);
    border: 1px solid rgba(245, 158, 11, 0.28);
    padding: 0 4px;
  }
  .gap.long:hover { background: rgba(245, 158, 11, 0.24); }
  .gap.long.del { background: var(--accent-crimson); border-color: var(--accent-crimson); color: #fff; }
  input.edit-in {
    background: var(--bg-elevated);
    color: #fff;
    border: 1px solid #38bdf8;
    font-size: 14px;
    border-radius: 4px;
    padding: 1px 5px;
    width: 7em;
  }
  .delrow {
    font-size: 12px;
    color: var(--text-secondary);
    line-height: 1.6;
    padding: 3px 0;
    border-bottom: 1px dashed var(--border-subtle);
  }
  .delrow:last-child { border-bottom: none; }
  .deltime { color: var(--text-muted); font-variant-numeric: tabular-nums; }
  .deltext { color: var(--text-secondary); }
</style>
</head>
<body>
<div id="bar">
  <div class="brand-title">
    <span class="brand-dot"></span>
    <b>粗剪审阅工作台</b>
  </div>
  <button id="btn-play">▶ 播放</button>
  <button id="btn-prev">⏮ 上一刀</button>
  <button id="btn-next">⏭ 下一刀</button>
  <select id="speed" title="倍速预览">
    <option value="0.25">0.25x</option>
    <option value="0.5">0.5x</option>
    <option value="0.75">0.75x</option>
    <option value="1" selected>1x</option>
    <option value="1.25">1.25x</option>
    <option value="1.5">1.5x</option>
    <option value="2">2x</option>
    <option value="3">3x</option>
  </select>
  <div class="bar-divider"></div>
  <button id="btn-cut" class="on" title="开启后播放自动跳过右侧已标红删除的词与停顿">✂️ 剪后预览</button>
  <button id="btn-caps" title="显示或隐藏画面底部字幕">💬 字幕</button>
  <span id="stats">0:00 / __TOTAL__ · __NSEG__ 段 · 1x</span>
  <span id="net">正在连接审阅宿主…</span>
  <a id="page-reload" href="" title="重新加载当前审阅页">⟳ 刷新</a>
</div>
<div id="staleness" hidden></div>
<div id="wrap">
  <div id="left">
    <div id="stage">
      <video id="main" playsinline></video>
      <div id="capbar"></div>
    </div>
    <div class="timeline-card">
      <div class="timeline-head">
        <span>时间线轨道（拖拽指针预览 · 空格播放/暂停 · ←/→ 微调 1s）</span>
        <span>片段数：__NSEG__</span>
      </div>
      <div id="ruler">
        <div id="blocks"></div>
        <div id="ticks"></div>
        <div id="playhead"><div class="hd"></div><div id="ptime">0:00</div></div>
      </div>
      <div id="hint">点击或拖拽时间轴随时试听剪口衔接 · 开启「剪后预览」可实时跳过右侧标红删掉的词与气口</div>
    </div>
    <div id="info">
      <div><div class="lbl">当前段落 Beat</div><div id="i-beat" class="beat"></div></div>
      <div><div class="lbl">源素材区间</div><div id="i-seg"></div></div>
      <div><div class="lbl">剪辑理由</div><div id="i-reason"></div></div>
      <div><div class="lbl">段落台词摘要</div><div id="i-quote"></div></div>
    </div>
    <div id="overall">
      <b>整体修改备注</b>
      <textarea id="ov-text" placeholder="可填写对整条片子节奏、段落取舍或语气的整体修改要求…"></textarea>
      <button id="ov-send">单独发送备注</button>
      <span id="ov-state">随保存或单独发回对话</span>
    </div>
    <div id="cues" hidden></div>
  </div>
  <div id="side">
    <div class="side-head">
      <b>逐字精修与气口裁剪</b>
      <span id="wstats">0 处选中 · 约减 0.0s</span>
    </div>
    <div class="side-actions">
      <button id="w-save" class="primary-cta">✓ 保存剪接修改</button>
      <button id="w-editmode" title="开启后单击词可直接改错别字；关闭时单击词为跳转播放">✏️ 改字模式：关</button>
      <button id="w-clear">清空选中</button>
      <button id="w-clearfix">还原改字</button>
      <button id="w-toggledel">已剪内容 (<span id="w-delcount"></span>)</button>
      <label style="font-size:12px;color:var(--text-secondary);display:inline-flex;align-items:center;gap:4px;margin-left:auto;">
        保留停顿
        <input id="w-pausedur" type="number" min="0" step="0.1" value="0.5"
               style="width:52px;background:var(--bg-card);color:var(--text-primary);border:1px solid var(--border-strong);border-radius:6px;padding:3px 6px;"> s
      </label>
    </div>
    <div id="w-delpanel" hidden></div>
    <div id="w-hint">
      <b>单击词</b>：定位到此处并播放 ·
      <b>按住拖开</b>：标红删除（从已标红词拖起则取消删除） ·
      <b>双击词</b>（或开「改字模式」）：修正识别错字
    </div>
    <div id="w-root"></div>
  </div>
</div>
<div id="vpool" hidden></div>
<script>
let review = null;   // 桥的句柄。声明在最前、接线放在整页渲染之后。
const SEGS = __SEGS__;
const SRC = __SRC__;
const CUES = __CUES__;
const TOTAL = __TOTAL__;
const PAL = ["#2563eb", "#0d9488", "#d97706", "#4f46e5", "#059669", "#0284c7"];
const srcColor = {};
Object.keys(SRC).forEach((k, i) => (srcColor[k] = PAL[i % PAL.length]));
const BEAT_COLORS = { HOOK: "#f59e0b", PROBLEM: "#f87171", SOLUTION: "#34d399",
                      BENEFIT: "#60a5fa", EXAMPLE: "#a78bfa", CTA: "#fbbf24" };
const beatColor = b => {
  const k = Object.keys(BEAT_COLORS).find(x => (b || "").toUpperCase().includes(x));
  return k ? BEAT_COLORS[k] : "#9da4b8";
};

/* ---- video pool ---- */
const vids = {};
for (const k of Object.keys(SRC)) {
  const v = document.createElement("video");
  v.src = SRC[k]; v.preload = "auto"; v.muted = true; v.playsInline = true;
  document.getElementById("vpool").appendChild(v);
  vids[k] = v;
}
const main = document.getElementById("main");
let curSrc = SRC[SEGS[0].src];
main.src = curSrc;

/* ---- state ---- */
let cur = -1;
let playing = false;
let playhead = 0;
let raf = null;
let scrubbing = false;
let lastCur = -1;
let lastPlayingG = -1;
let lastPlayEl = null;
let editMode = false;    // when true, single-clicking a word opens inline text edit
const sel = new Set();   // "w:G" | "g:S:I"
const restoreSet = new Set();  // deleted-word key "src|ws|we" -> restore on save
const cutWords = [];
let cutAnchor = null, cutDragKeys = new Set(), cutDragMode = "restore", cutDown = null;

const fmt = t => {
  if (!isFinite(t) || t < 0) t = 0;
  const m = Math.floor(t / 60), s = Math.floor(t % 60);
  return m + ":" + String(s).padStart(2, "0");
};
const segAt = t => {
  for (let i = 0; i < SEGS.length; i++)
    if (t >= SEGS[i].o0 && t < SEGS[i].o1) return i;
  return -1;
};

/* ---- cut preview: skip selected words/gaps while playing ---- */
const cutPreview = { on: true };
function deletedIntervalsBySrc() {
  const bySrc = {};
  for (const k of sel) {
    const [ty, p1, p2] = k.split(":");
    if (ty === "w") {
      const rec = byG.get(+p1);
      (bySrc[rec.seg.src] ||= []).push([rec.item.o0, rec.item.o1]);
    } else {
      const seg = SEGS[+p1];
      const it = seg.gaps[+p2];
      (bySrc[seg.src] ||= []).push([it.o0, it.o1]);
    }
  }
  for (const src in bySrc) {
    bySrc[src].sort((a, b) => a[0] - b[0]);
    const merged = [];
    for (const iv of bySrc[src]) {
      if (merged.length && iv[0] <= merged[merged.length - 1][1] + 0.12) {
        merged[merged.length - 1][1] = Math.max(merged[merged.length - 1][1], iv[1]);
      } else {
        merged.push([...iv]);
      }
    }
    bySrc[src] = merged;
  }
  return bySrc;
}
function outToSrc(seg, outT) {
  return Math.min(seg.end, seg.start + (outT - seg.o0) * (seg.speed || 1));
}
function applyCut(seg, outT) {
  if (!cutPreview.on) return outToSrc(seg, outT);
  const ivs = deletedIntervalsBySrc()[seg.src] || [];
  let changed = true;
  while (changed) {
    changed = false;
    for (const [a, b] of ivs) {
      if (outT >= a && outT < b) {
        outT = b;
        changed = true;
      }
    }
  }
  outT = Math.min(seg.o1, outT);
  if (seg.o1 - outT < 0.5) outT = seg.o1;
  return outToSrc(seg, outT);
}

/* ---- ruler ---- */
const blocksEl = document.getElementById("blocks");
SEGS.forEach((s, i) => {
  const el = document.createElement("div");
  el.className = "seg-block";
  el.id = "seg-" + i;
  el.style.left = (s.o0 / TOTAL * 100) + "%";
  el.style.width = ((s.o1 - s.o0) / TOTAL * 100) + "%";
  el.style.background = srcColor[s.src];
  el.innerHTML = (s.beat || s.label) + '<span class="d">' + (s.o1 - s.o0).toFixed(1) + "s</span>";
  blocksEl.appendChild(el);
});
const ticksEl = document.getElementById("ticks");
for (let t = 0; t <= TOTAL; t += 10) {
  const d = document.createElement("div");
  d.className = "tick" + (t % 20 === 0 ? " labeled" : "");
  d.style.left = (t / TOTAL * 100) + "%";
  d.innerHTML = t % 20 === 0 ? "<span>" + fmt(t) + "</span>" : "";
  ticksEl.appendChild(d);
}

/* ---- caption cues ---- */
const cuesEl = document.getElementById("cues");
const capbar = document.getElementById("capbar");
if (!document.getElementById("btn-caps").classList.contains("on")) {
  capbar.classList.add("empty");
}
if (CUES.length) {
  CUES.forEach((c) => {
    const row = document.createElement("div");
    row.className = "cue";
    row.innerHTML = '<span class="ct">' + fmt(c.s) + "</span><span>" + c.t + "</span>";
    row.addEventListener("click", () => seekTo(c.s));
    cuesEl.appendChild(row);
  });
} else {
  capbar.classList.add("empty");
  document.getElementById("btn-caps").style.display = "none";
}

/* ---- render functions ---- */
function renderPlayhead() {
  const ph = document.getElementById("playhead");
  ph.style.left = (playhead / TOTAL * 100) + "%";
  document.getElementById("ptime").textContent = fmt(playhead);
  document.querySelectorAll(".seg-block.active").forEach(el => el.classList.remove("active"));
  if (cur >= 0) document.getElementById("seg-" + cur).classList.add("active");
  document.getElementById("stats").textContent =
    fmt(playhead) + " / " + fmt(TOTAL) + " · " + SEGS.length + " 段 · " +
    document.getElementById("speed").value + "x";
  if (lastPlayEl) { lastPlayEl.classList.remove("playing"); lastPlayEl = null; }
  if (cur >= 0) {
    const hit = SEGS[cur].items.find(it => playhead >= it.o0 && playhead <= it.o1 + 0.05);
    if (hit) {
      const el = document.getElementById("w" + hit.g);
      if (el) {
        el.classList.add("playing");
        lastPlayEl = el;
        if (lastPlayingG !== hit.g) {
          lastPlayingG = hit.g;
          el.scrollIntoView({ block: "nearest" });
        }
      }
    } else {
      lastPlayingG = -1;
    }
  }
  if (lastCur !== cur) {
    document.querySelectorAll(".wseg.active").forEach(el => el.classList.remove("active"));
    if (cur >= 0) {
      const el = document.getElementById("wseg-" + cur);
      if (el) {
        el.classList.add("active");
        if (playing) el.scrollIntoView({ block: "nearest" });
      }
    }
    lastCur = cur;
  }
}
function renderInfo() {
  const s = cur >= 0 ? SEGS[cur] : null;
  const beatEl = document.getElementById("i-beat");
  if (s) {
    beatEl.textContent = s.beat || "—";
    beatEl.style.color = beatColor(s.beat);
  } else {
    beatEl.textContent = "—";
    beatEl.style.color = "";
  }
  document.getElementById("i-seg").textContent = s
    ? s.label + " · 源 " + s.start.toFixed(1) + "-" + s.end.toFixed(1) + "s" : "—";
  document.getElementById("i-quote").textContent = s ? s.quote || "" : "";
  document.getElementById("i-reason").textContent = s ? s.reason || "" : "";
}
function renderCaption() {
  if (!CUES.length || capbar.classList.contains("empty")) return;
  const c = CUES.find(x => playhead >= x.s && playhead < x.e);
  capbar.textContent = c ? c.t : "";
}

/* ---- playback engine ---- */
function seekTo(t, autoplay, useCut = true) {
  t = Math.max(0, Math.min(TOTAL - 0.01, t));
  playhead = t;
  const i = segAt(t);
  if (i >= 0) {
    const s = SEGS[i];
    const rawSt = s.start + (t - s.o0) * (s.speed || 1);
    let st = rawSt;
    if (useCut) st = applyCut(s, t);
    if (st !== rawSt) {
      playhead = Math.min(s.o1, s.o0 + (st - s.start) / (s.speed || 1));
    }
    if (cur !== i) {
      cur = i;
      const u = SRC[s.src];
      if (curSrc !== u) { curSrc = u; main.src = u; }
    }
    main.playbackRate = (s.speed || 1) * parseFloat(document.getElementById("speed").value);
    main.muted = (s.speed || 1) > 1;
    main.currentTime = st;
    if (autoplay) main.play();
  } else {
    cur = -1;
  }
  renderPlayhead(); renderInfo(); renderCaption();
}

function advance() {
  if (cur + 1 >= SEGS.length) { stop(); return; }
  cur++;
  const s = SEGS[cur];
  const u = SRC[s.src];
  if (curSrc !== u) { curSrc = u; main.src = u; }
  main.playbackRate = (s.speed || 1) * parseFloat(document.getElementById("speed").value);
  main.muted = (s.speed || 1) > 1;
  main.currentTime = applyCut(s, s.o0);
  main.play();
  const nxt = SEGS[cur + 1];
  if (nxt) { const pv = vids[nxt.src]; if (pv.readyState < 2) pv.load(); }
  renderInfo();
}

function startLoop() {
  if (raf) return;
  let lastTs = performance.now();
  const loop = () => {
    const now = performance.now();
    const dt = (now - lastTs) / 1000;
    lastTs = now;
    if (playing && cur >= 0) {
      const s = SEGS[cur];
      const rate = (s.speed || 1) * parseFloat(document.getElementById("speed").value);
      let t = playhead + Math.max(0.001, dt) * rate;
      let jumped = false;
      if (cutPreview.on) {
        const ivs = deletedIntervalsBySrc()[s.src] || [];
        let changed = true;
        while (changed) {
          changed = false;
          for (const [a, b] of ivs) {
            if (t >= a && t < b) {
              t = b;
              changed = true;
              jumped = true;
            }
          }
        }
      }
      if (t >= s.o1 - 0.001) {
        advance();
      } else {
        playhead = t;
        if (jumped) main.currentTime = outToSrc(s, t);
        renderPlayhead(); renderCaption();
      }
    }
    raf = requestAnimationFrame(loop);
  };
  raf = requestAnimationFrame(loop);
}
function stopLoop() { if (raf) { cancelAnimationFrame(raf); raf = null; } }

function play() {
  if (cur < 0) seekTo(playhead);
  main.play().catch(() => {});
  playing = true;
  document.getElementById("btn-play").textContent = "⏸ 暂停";
  startLoop();
}
function pause() {
  playing = false;
  main.pause();
  Object.values(vids).forEach(v => v.pause());
  document.getElementById("btn-play").textContent = "▶ 播放";
  stopLoop();
  renderPlayhead();
}
function stop() { pause(); playhead = TOTAL; renderPlayhead(); }

/* ---- controls ---- */
document.getElementById("btn-play").onclick = () => (playing ? pause() : play());
document.getElementById("btn-prev").onclick = () => {
  const cuts = SEGS.map(s => s.o0);
  let t = playhead - 0.2;
  for (let i = cuts.length - 1; i >= 0; i--) if (cuts[i] < t) { t = cuts[i]; break; }
  pause(); seekTo(Math.max(0, t));
};
document.getElementById("btn-next").onclick = () => {
  const cuts = SEGS.map(s => s.o0);
  let t = playhead + 0.2;
  for (let i = 0; i < cuts.length; i++) if (cuts[i] > t) { t = cuts[i]; break; }
  pause(); seekTo(t);
};
document.getElementById("speed").onchange = e => {
  const r = parseFloat(e.target.value);
  Object.values(vids).forEach(v => (v.playbackRate = r));
  if (cur >= 0) {
    main.playbackRate = (SEGS[cur].speed || 1) * r;
    main.muted = (SEGS[cur].speed || 1) > 1;
  }
  renderPlayhead();
};
document.getElementById("btn-cut").onclick = () => {
  cutPreview.on = !cutPreview.on;
  document.getElementById("btn-cut").classList.toggle("on", cutPreview.on);
  if (cur >= 0) seekTo(playhead);
};
document.getElementById("btn-caps").onclick = () => {
  const on = document.getElementById("btn-caps").classList.toggle("on");
  capbar.classList.toggle("empty", !on || !CUES.length);
};

/* ---- scrub ---- */
const ruler = document.getElementById("ruler");
function tFromEvent(e) {
  const r = ruler.getBoundingClientRect();
  return Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)) * TOTAL;
}
ruler.addEventListener("pointerdown", e => {
  scrubbing = true;
  pause();
  seekTo(tFromEvent(e));
  ruler.setPointerCapture(e.pointerId);
});
ruler.addEventListener("pointermove", e => {
  if (scrubbing) seekTo(tFromEvent(e));
});
ruler.addEventListener("pointerup", e => {
  scrubbing = false;
  ruler.releasePointerCapture(e.pointerId);
});

/* ---- keyboard ---- */
document.addEventListener("keydown", e => {
  if (e.target.tagName === "SELECT" || e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;
  if (e.code === "Space") { e.preventDefault(); playing ? pause() : play(); }
  else if (e.code === "ArrowLeft") { pause(); seekTo(playhead - 1); }
  else if (e.code === "ArrowRight") { pause(); seekTo(playhead + 1); }
  else if (e.code === "Home") { pause(); seekTo(0); }
  else if (e.code === "End") { pause(); seekTo(TOTAL); }
});

document.getElementById("main").addEventListener("click", () => (playing ? pause() : play()));
seekTo(0);

/* ================= 逐字审阅与精修 ================= */
const DELETED = __DELETED__;
const fixes = new Map();
const byG = new Map();
SEGS.forEach((seg) => seg.items.forEach((it) => byG.set(it.g, { seg, item: it })));
const wordKey = (seg, it) => seg.src + "|" + it.ws + "|" + it.we;

function wstats() {
  document.getElementById("wstats").textContent =
    sel.size + " 处选中 · 约减 " + wIntervals().toFixed(1) + "s · " +
    fixes.size + " 处修正 · 恢复 " + restoreSet.size + " 字";
}
function wIntervals() {
  const bySrc = {};
  for (const k of sel) {
    const [ty, p1, p2] = k.split(":");
    if (ty === "w") {
      const rec = byG.get(+p1);
      (bySrc[rec.seg.src] ||= []).push([rec.item.ws, rec.item.we]);
    } else {
      const seg = SEGS[+p1];
      const it = seg.gaps[+p2];
      (bySrc[seg.src] ||= []).push([it.gs, it.ge]);
    }
  }
  let total = 0;
  for (const src in bySrc) {
    const iv = bySrc[src].sort((a, b) => a[0] - b[0]);
    let cur = iv[0];
    for (let i = 1; i < iv.length; i++) {
      if (iv[i][0] <= cur[1] + 0.12) cur[1] = Math.max(cur[1], iv[i][1]);
      else { total += cur[1] - cur[0]; cur = iv[i]; }
    }
    total += cur[1] - cur[0];
  }
  return total;
}

const wroot = document.getElementById("w-root");
function bindWord(span, g) {
  span.addEventListener("mousedown", (e) => e.preventDefault());
  span.addEventListener("dblclick", () => startEdit(g));
}

const delAfter = new Map();
DELETED.forEach((d) => {
  if (d.after_seg >= 0) {
    let arr = delAfter.get(d.after_seg);
    if (!arr) { arr = []; delAfter.set(d.after_seg, arr); }
    arr.push(d);
  }
});
SEGS.forEach((seg, si) => {
  const box = document.createElement("div");
  box.className = "wseg";
  box.id = "wseg-" + si;
  const head = document.createElement("div");
  head.className = "wseg-head";
  const titleSpan = document.createElement("span");
  titleSpan.innerHTML = '<b style="color:' + beatColor(seg.beat) + '">' + (seg.beat || seg.label) +
                        "</b> · " + seg.label;
  const jumpBtn = document.createElement("button");
  jumpBtn.className = "wseg-jump";
  jumpBtn.type = "button";
  jumpBtn.textContent = "▶ " + fmt(seg.o0) + " - " + fmt(seg.o1);
  jumpBtn.title = "点击从本段开头试听播放";
  jumpBtn.addEventListener("click", () => { seekTo(seg.o0, true, false); play(); });
  head.appendChild(titleSpan);
  head.appendChild(jumpBtn);
  box.appendChild(head);
  const flow = document.createElement("div");
  const ents = [];
  seg.items.forEach((it, ni) => ents.push({ kind: "w", ni }));
  seg.gaps.forEach((g, gi) => ents.push({ kind: "g", ni: gi, o0: g.o0 }));
  ents.sort((a, b) => (a.kind === "w" ? seg.items[a.ni].o0 : a.o0) -
                      (b.kind === "w" ? seg.items[b.ni].o0 : b.o0));
  for (const en of ents) {
    if (en.kind === "w") {
      const it = seg.items[en.ni];
      const span = document.createElement("span");
      span.className = "w" + (it.f ? " fixed" : "");
      span.id = "w" + it.g; span.dataset.g = it.g;
      span.textContent = it.t;
      span.title = "单击定位播放 · 按住拖开标红删除 · 双击改字 (" + fmt(it.o0) + ")";
      bindWord(span, it.g);
      flow.appendChild(span);
    } else {
      const it = seg.gaps[en.ni];
      const gap = document.createElement("span");
      gap.className = "gap" + (it.long ? " long" : "");
      gap.textContent = "·" + (it.ge - it.gs).toFixed(1) + "s·";
      gap.title = "停顿 " + (it.ge - it.gs).toFixed(2) + "s" + (it.long ? "（长气口，点击标记裁剪）" : "");
      gap.addEventListener("click", () => {
        const k = "g:" + si + ":" + en.ni;
        if (sel.has(k)) { sel.delete(k); gap.classList.remove("del"); }
        else { sel.add(k); gap.classList.add("del"); }
        pause(); seekTo(it.o0);
        wstats();
        if (cutPreview.on && cur >= 0) seekTo(playhead);
      });
      flow.appendChild(gap);
    }
  }
  box.appendChild(flow);
  const dls = delAfter.get(si) || [];
  if (dls.length) {
    const div = document.createElement("div");
    div.className = "cutdiv";
    dls.forEach((d) => {
      d.words.forEach((w) => {
        const wkey = d.src + "|" + w.ws + "|" + w.we;
        const s = document.createElement("span");
        s.className = "w cut" + (restoreSet.has(wkey) ? " restored" : "");
        s.dataset.rk = wkey;
        s.textContent = w.t;
        s.title = "单击或拖动恢复已剪掉的词 · 源 " + w.ws.toFixed(2) + "-" + w.we.toFixed(2) + "s";
        s.addEventListener("mousedown", (e) => e.preventDefault());
        div.appendChild(s);
      });
    });
    box.appendChild(div);
  }
  wroot.appendChild(box);
});
buildCutWords();

/* deleted-content toggle */
document.getElementById("w-delcount").textContent = DELETED.length;
const toggledel = document.getElementById("w-toggledel");
toggledel.onclick = () => {
  document.body.classList.toggle("hidecut");
  toggledel.textContent = (document.body.classList.contains("hidecut") ? "显示" : "隐藏") +
                          "已剪内容 (" + DELETED.length + ")";
};
(function renderDeleted() {
  const list = document.getElementById("w-delpanel");
  const bySrc = {};
  DELETED.forEach((d) => (bySrc[d.src] ||= []).push(d));
  for (const src in bySrc) {
    const head = document.createElement("div");
    head.className = "wseg-head";
    head.innerHTML = "<b>" + src.slice(-6) + "</b> · " + bySrc[src].length + " 段被剪";
    list.appendChild(head);
    bySrc[src].forEach((d) => {
      const row = document.createElement("div");
      row.className = "delrow";
      row.innerHTML = '<span class="deltime">' + d.start.toFixed(1) + "-" +
                      d.end.toFixed(1) + "s</span> " +
                      '<span class="deltext">' + d.text + "</span>";
      list.appendChild(row);
    });
  }
})();

/* Edit-mode toggle button */
const editModeBtn = document.getElementById("w-editmode");
editModeBtn.onclick = () => {
  editMode = !editMode;
  editModeBtn.classList.toggle("on", editMode);
  editModeBtn.textContent = editMode ? "✏️ 改字模式：开" : "✏️ 改字模式：关";
};

/* Word interaction:
   - Single click (default): jump to the word and play (never deletes).
   - Hold and drag (>= 6px): select/deselect range for deletion.
   - Double click (or single click when editMode is ON): inline text edit. */
let anchor = null, downKey = null, dragKeys = new Set();
let downPos = null;
let dragMode = "add";

function buildCutWords() {
  cutWords.length = 0;
  document.querySelectorAll(".w.cut").forEach((el) => cutWords.push({ el, key: el.dataset.rk }));
}
function cutRange(a, b) {
  const lo = Math.min(a, b), hi = Math.max(a, b), out = new Set();
  for (let i = lo; i <= hi; i++) out.add(i);
  return out;
}
function paintCutDrag() {
  cutWords.forEach((c, i) => c.el.classList.toggle("drag", cutDragKeys.has(i)));
}
function applyCutDrag() {
  cutDragKeys.forEach((idx) => {
    const c = cutWords[idx];
    if (!c) return;
    if (cutDragMode === "restore") restoreSet.add(c.key); else restoreSet.delete(c.key);
    c.el.classList.toggle("restored", restoreSet.has(c.key));
  });
}

function rangeKeys(a, b) {
  const lo = Math.min(a, b), hi = Math.max(a, b), out = new Set();
  for (let g = lo; g <= hi; g++) out.add(g);
  return out;
}
function clearDrag() {
  dragKeys.forEach((g) => {
    const el = document.getElementById("w" + g);
    if (el) el.classList.remove("drag", "drag-undo");
  });
  dragKeys = new Set();
  anchor = null;
  downKey = null;
  downPos = null;
}
function applyDrag() {
  dragKeys.forEach((gg) => {
    const el = document.getElementById("w" + gg);
    if (dragMode === "add") { sel.add("w:" + gg); if (el) el.classList.add("del"); }
    else { sel.delete("w:" + gg); if (el) el.classList.remove("del"); }
  });
  wstats();
  if (cutPreview.on && cur >= 0) seekTo(playhead);
}
function paintDrag() {
  document.querySelectorAll(".w.drag, .w.drag-undo").forEach(el =>
    el.classList.remove("drag", "drag-undo"));
  dragKeys.forEach((g) => {
    const el = document.getElementById("w" + g);
    if (el) el.classList.add(dragMode === "add" ? "drag" : "drag-undo");
  });
}
document.addEventListener("mousedown", (e) => {
  const cut = e.target.closest(".w.cut");
  if (cut) {
    cutAnchor = cutWords.findIndex((c) => c.el === cut);
    cutDown = [e.clientX, e.clientY];
    cutDragMode = restoreSet.has(cut.dataset.rk) ? "unrestore" : "restore";
    cutDragKeys = new Set([cutAnchor]);
    paintCutDrag();
    e.preventDefault();
    return;
  }
  const w = e.target.closest(".w");
  if (!w) return;
  anchor = +w.dataset.g;
  downKey = +w.dataset.g;
  downPos = [e.clientX, e.clientY];
  dragMode = sel.has("w:" + anchor) ? "remove" : "add";
  e.preventDefault();
});
document.addEventListener("mouseover", (e) => {
  if (cutAnchor !== null) {
    const cut = e.target.closest(".w.cut");
    if (cut && cutDown && Math.hypot(e.clientX - cutDown[0], e.clientY - cutDown[1]) >= 6) {
      const idx = cutWords.findIndex((c) => c.el === cut);
      if (idx >= 0) { cutDragKeys = cutRange(cutAnchor, idx); paintCutDrag(); }
    }
    return;
  }
  const w = e.target.closest(".w");
  if (anchor === null || !w) return;
  if (downPos && Math.hypot(e.clientX - downPos[0], e.clientY - downPos[1]) < 6) return;
  dragKeys = rangeKeys(anchor, +w.dataset.g);
  paintDrag();
});
document.addEventListener("mouseup", (e) => {
  if (cutAnchor !== null) {
    const moved = cutDown && Math.hypot(e.clientX - cutDown[0], e.clientY - cutDown[1]) >= 6;
    if (moved) {
      applyCutDrag();
    } else {
      const c = cutWords[cutAnchor];
      if (c) {
        if (restoreSet.has(c.key)) restoreSet.delete(c.key); else restoreSet.add(c.key);
        c.el.classList.toggle("restored", restoreSet.has(c.key));
      }
    }
    cutAnchor = null; cutDragKeys = new Set(); cutDown = null;
    wstats();
    return;
  }
  if (anchor === null) return;
  try {
    const w = e.target.closest(".w");
    const g = w ? +w.dataset.g : null;
    const moved = downPos && Math.hypot(e.clientX - downPos[0], e.clientY - downPos[1]) >= 6;
    if (moved) {
      dragKeys = dragKeys.size ? dragKeys : rangeKeys(anchor, g === null ? anchor : g);
      if (dragKeys.size) applyDrag();
    } else if (g === downKey) {
      if (editMode) {
        startEdit(g);
      } else {
        const rec = byG.get(g);
        if (rec) { seekTo(rec.item.o0, true, false); play(); }
      }
    }
  } finally {
    clearDrag();
  }
});
document.addEventListener("mouseleave", () => { clearDrag(); cutAnchor = null; cutDragKeys = new Set(); cutDown = null; });
window.addEventListener("blur", clearDrag);

function startEdit(g) {
  const el = document.getElementById("w" + g);
  if (!el) return;
  pause();
  const rec = byG.get(g);
  if (!rec) return;
  const key = wordKey(rec.seg, rec.item);
  const input = document.createElement("input");
  input.className = "edit-in";
  input.value = fixes.has(key) ? fixes.get(key) : rec.item.t;
  el.replaceWith(input);
  input.focus(); input.select();
  let done = false;
  const commit = (save) => {
    if (done) return; done = true;
    const span = document.createElement("span");
    span.className = "w" + (sel.has("w:" + g) ? " del" : "");
    span.id = "w" + g; span.dataset.g = g;
    span.textContent = input.value.trim() || rec.item.t;
    span.classList.toggle("fixed", save || rec.item.f);
    input.replaceWith(span);
    if (save && input.value.trim() && input.value.trim() !== rec.item.t) {
      fixes.set(key, input.value.trim());
      span.classList.add("fixed");
    } else if (!rec.item.f) {
      fixes.delete(key);
    }
    bindWord(span, g);
    wstats();
  };
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") commit(true);
    else if (e.key === "Escape") commit(false);
  });
  input.addEventListener("blur", () => commit(true));
}

/* bar buttons */
document.getElementById("w-clear").onclick = () => {
  document.querySelectorAll(".del").forEach((el) => el.classList.remove("del"));
  sel.clear();
  wstats();
};
document.getElementById("w-clearfix").onclick = () => {
  fixes.clear();
  document.querySelectorAll(".w.fixed").forEach((el) => {
    const rec = byG.get(+el.dataset.g);
    if (rec && !rec.item.f) el.classList.remove("fixed");
    el.textContent = rec ? rec.item.t : el.textContent;
  });
  wstats();
};
document.getElementById("w-save").onclick = async () => {
  const words = [], pauses = [];
  for (const k of sel) {
    const [ty, p1, p2] = k.split(":");
    if (ty === "w") {
      const rec = byG.get(+p1);
      words.push({ src: rec.seg.orig_src || rec.seg.src, start: rec.item.ws, end: rec.item.we });
    } else {
      const seg = SEGS[+p1];
      const it = seg.gaps[+p2];
      pauses.push({ src: seg.orig_src || seg.src, start: it.gs, end: it.ge,
                    target: parseFloat(document.getElementById("w-pausedur").value) || 0 });
    }
  }
  const restores = [];
  restoreSet.forEach((wkey) => {
    const parts = wkey.split("|");
    restores.push({ src: parts[0], start: +parts[1], end: +parts[2] });
  });
  const fixArr = [...fixes].map(([k, text]) => {
    const [src, s, e] = k.split("|");
    return { src, start: +s, end: +e, text };
  });
  const pageDir = location.pathname.split("/").slice(0, -1).join("/") || "/";
  const payload = { words, pauses, restore: restores, fixes: fixArr, dir: pageDir };
  const btn = document.getElementById("w-save");
  if (!review) { btn.textContent = "✗ 尚未连接审阅宿主"; return; }
  let ok = false;
  try {
    await review.write(payload);
    ok = true;
  } catch (error) {
    btn.textContent = "✗ 保存失败：" + error.message;
    setTimeout(() => (btn.textContent = "✓ 保存剪接修改"), 8000);
    return;
  }
  if (ok) {
    const extraNote = document.getElementById("ov-text").value.trim();
    const wakeMsg = "剪接选择已保存（整份覆盖 selections.json）——跑 helpers/apply_selection.py 应用剪点，再重出这一页。"
      + (extraNote ? (" 附整体备注：" + extraNote) : "");
    try {
      await review.wake({ unit: "剪接", text: wakeMsg });
      if (extraNote) {
        document.getElementById("ov-text").value = "";
        document.getElementById("ov-state").textContent = "已随保存一并发送";
      }
      btn.textContent = "✓ 已保存并通知模型";
    } catch (error) {
      btn.textContent = "✓ 已保存（回对话说一声「剪」）";
    }
    setTimeout(() => (btn.textContent = "✓ 保存剪接修改"), 8000);
  } else {
    btn.textContent = "✗ 保存失败";
  }
};

wstats();

/* ─────────────────────────────────────────────────────────────────────────
   审阅桥：接在同步渲染之后，前面不许有任何顶层 await。
   ───────────────────────────────────────────────────────────────────────── */
function setNet(text) { document.getElementById("net").textContent = text; }

function noteStale() {
  const box = document.getElementById("staleness");
  box.textContent = "edl.json 已更新：当前时间轴为旧版快照，请点击右上角「⟳ 刷新」加载最新粗剪。";
  box.hidden = false;
}

document.getElementById("ov-send").onclick = async () => {
  const text = document.getElementById("ov-text").value.trim();
  const state = document.getElementById("ov-state");
  if (!text) { state.textContent = "请先填写整体修改备注"; return; }
  if (!review) { state.textContent = "尚未连接审阅宿主"; return; }
  try {
    await review.wake({ unit: "整段", text: "整段剪辑有一条整体意见：" + text });
    document.getElementById("ov-text").value = "";
    state.textContent = "已发回对话";
    setTimeout(() => (state.textContent = "随保存或单独发回对话"), 6000);
  } catch (error) {
    state.textContent = "发送失败（" + error.message + "）";
  }
};

(async () => {
  if (!window.ReviewBridge) {
    setNet("未加载审阅桥");
    return;
  }
  try {
    review = await ReviewBridge.connect();
  } catch (error) {
    setNet("未连接审阅宿主（" + error.message + "）");
    return;
  }
  setNet("已连接审阅宿主（" + review.transport + "）");
  review.on("changed", noteStale);
})();
</script>
</body>
</html>
"""

data = {
    "__SEGS__": json.dumps(segments, ensure_ascii=False),
    "__SRC__": json.dumps(src_map_web, ensure_ascii=False),
    "__CUES__": json.dumps(cues, ensure_ascii=False),
    "__DELETED__": json.dumps(deleted, ensure_ascii=False),
    "__TOTAL__": repr(total),
    "__NSEG__": str(len(segments)),
}
html = HTML
for k, v in data.items():
    html = html.replace(k, v)

out = EDIT / "edl_preview.html"
out.write_text(html, encoding="utf-8")
print(f"edl_preview.html written ({out.stat().st_size/1024:.0f} KB, {len(segments)} segments, "
      f"{total}s, {len(cues)} caption cues, {gidx} words, {len(deleted)} deleted chunks, "
      f"sources: {sorted(set(s['src'] for s in segments))})")
print(f"serve root: {ROOT}（审阅宿主会 serve 它）→ {PAGE_REL.as_posix()} "
      f"(run helpers/edl_review_surface.py {EDIT})")
