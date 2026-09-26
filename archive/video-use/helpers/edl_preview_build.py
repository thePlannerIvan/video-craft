#!/usr/bin/env python3
"""Build edl_preview.html in <edit_dir> — browser timeline preview of the
edited cut, the editing-software equivalent of scrubbing the timeline.

Usage: edl_preview_build.py <edit_dir>
       edl_preview_serve.py <edit_dir> [port]   # then open the page

Reads edl.json (+ sources) and, when present, subtitles.srt (the article-first
delivery file) or the legacy master.srt / subtitles_sentences.srt
(output-timeline subtitles). Plays the cut directly from the SOURCE clips —
no render needed — by mapping the output timeline to segment + source offset:

  output time T → segment i (offset_i <= T < offset_i+1)
                 → source clip at start_i + (T - offset_i)

Features:
  - timeline ruler with per-source segment blocks, ticks, playhead
  - click / drag on the ruler to scrub (same feel as a NLE timeline)
  - play / pause, prev / next cut, 0.5x-2x speed, space / arrow keys
  - live beat / quote / reason readout for the current segment
  - optional caption overlay synced to the output timeline
  - click a caption cue to jump to it

This page iterates CONTENT and RHYTHM decisions. It cannot show ffmpeg-side
grade / overlay / burned subtitles — for the final look still render a
--preview (render.py --preview) once before the final render.
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

# serve root: the common ancestor of edit_dir and all source files, so the
# preview page can reach the raw footage over http (paths stay URL-safe,
# no ".."). Page lives at relpath(EDIT, ROOT) + "/edl_preview.html".
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

# URL-safe absolute paths under the serve root: "/1785493077348.mp4"
if USE_RENDERED:
    src_map_web = {PREVIEW_KEY: "/" + PREVIEW_VIDEO.relative_to(ROOT).as_posix()}
else:
    src_map_web = {k: "/" + v.relative_to(ROOT).as_posix() for k, v in SRC_MAP.items()}

# optional output-timeline captions (master.srt, or srt_export's sentence SRT)
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
for cand in ("subtitles.srt", "subtitles2.srt", "Newsubtitles.srt",
             "master.srt", "subtitles_sentences.srt"):
    if (EDIT / cand).exists():
        cues = parse_srt(EDIT / cand)
        break

# ---- word-review data (merged from word_picker: click-to-delete words,
#      drag multi-select, double-click text fixes, silence gaps) ----
MIN_GAP = 0.15
LONG_GAP = 0.5
NOISE_DB = -25


def real_silences(src_path, seg_start, seg_end):
    dur = seg_end - seg_start
    cmd = ["ffmpeg", "-ss", str(seg_start), "-t", str(dur), "-i", str(src_path),
           "-af", f"silencedetect=noise={NOISE_DB}dB:d=0.15", "-f", "null", "-"]
    out = subprocess.run(cmd, capture_output=True, text=True).stderr
    starts = [float(m) for m in re.findall(r"silence_start: ([\d.]+)", out)]
    ends = [float(m) for m in re.findall(r"silence_end: ([\d.]+)", out)]
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
        # mlx-whisper fallback output mixes in "spacing" entries that carry no
        # start/end keys — they'd KeyError every downstream loop.
        trans[k] = [w for w in json.load(open(tf, encoding="utf-8"))["words"]
                    if w.get("type", "word") != "spacing"]

gidx = 0
for i, r in enumerate(edl["ranges"]):
    src = r["source"]
    s, e = r["start"], r["end"]
    src_words = trans.get(src, [])
    # only words whose audible part is really inside the segment (>=80%),
    # filters orphan tokens that merely touch the padded edges
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
    # pauses between kept words (from word timing — instant, no ffmpeg)
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

# what was CUT: source words not covered by any segment (same 80% rule)
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

# map each deleted chunk to the segment index it follows (by SOURCE time, so it
# works whether the page plays the source clips or a rendered final.mp4)
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
<title>EDL 时间线预览</title>
<style>
  * { box-sizing: border-box; }
  body { font-family: -apple-system, "PingFang SC", "Noto Sans SC", sans-serif;
         background: #0d0d12; color: #e8e8ee; margin: 0; padding: 0 0 60px;
         min-width: 1280px; }
  #bar { position: sticky; top: 0; z-index: 20; background: #13131a;
         border-bottom: 1px solid #26262e; padding: 10px 20px;
         display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
  #bar b { font-size: 15px; }
  #stats { font-size: 13px; color: #9a9aa6; font-variant-numeric: tabular-nums; }
  button { padding: 5px 14px; border: 1px solid #3a3a46; border-radius: 6px;
           background: #1c1c26; color: #e8e8ee; cursor: pointer; font-size: 14px; }
  button:hover { background: #262633; }
  button.on { background: #1d4ed8; border-color: #1d4ed8; color: #fff; }
  select { background: #1c1c26; color: #e8e8ee; border: 1px solid #3a3a46;
           border-radius: 6px; font-size: 13px; padding: 4px 6px; }
  #wrap { max-width: 1560px; margin: 0 auto; padding: 14px 20px;
          display: grid; grid-template-columns: 1fr 440px; gap: 20px; }
  #left { min-width: 0; }
  #side { border-left: 1px solid #26262e; padding-left: 18px; }
  .side-head { display: flex; justify-content: space-between; align-items: baseline; }
  .side-head b { font-size: 16px; }
  #wstats { font-size: 13px; color: #b8b8c4; }
  .side-actions { display: flex; gap: 8px; flex-wrap: wrap; margin: 12px 0; }
  #w-hint { font-size: 12px; color: #7c7c88; margin: 6px 0 12px; line-height: 1.7; }
  #w-root { overflow-y: auto; max-height: 66vh; padding-right: 6px; }
  #w-root::-webkit-scrollbar { width: 8px; }
  #w-root::-webkit-scrollbar-thumb { background: #2c2c38; border-radius: 4px; }
  .wseg { margin: 14px 0; padding: 12px 14px; background: #16161d;
          border: 1px solid #24242d; border-radius: 10px; }
  .wseg.active { border-color: #f59e0b66; }
  .wseg-head { font-size: 13px; color: #a8a8b4; margin-bottom: 8px; }
  .wseg-head b { color: #d8d8e2; }
  .w { display: inline-block; padding: 1px 1px; border-radius: 3px;
       cursor: pointer; font-size: 16px; line-height: 1.85; user-select: none; }
  .w:hover { background: #1c2440; }
  .w.del { background: #e5484d; color: #fff; text-decoration: line-through; }
  .w.cut { color: #e5484d; text-decoration: line-through; opacity: .75; }
  .w.cut:hover { background: #2a1518; color: #d8d8e2; opacity: 1; }
  .w.cut.restored { color: #3ddc76; text-decoration: none; opacity: 1; background: #132a1a; }
  .cutdiv { margin: 6px 0 12px; padding: 6px 10px; border-left: 3px solid #5c2a2e;
            background: #131318; border-radius: 6px; font-size: 14px; line-height: 1.9; }
  .cutlabel { font-size: 11px; color: #a05056; margin-right: 8px; vertical-align: middle; }
  body.hidecut .cutdiv { display: none; }
  .w.drag { background: #1d4ed8; color: #fff; }
  .w.drag-undo { background: #3ddc76; color: #0d0d12; }
  .w.playing { background: #f59e0b; color: #111; border-radius: 4px;
               padding: 0 4px; font-weight: 700;
               box-shadow: 0 0 0 2px rgba(245,158,11,.55); }
  .w.fixed { border-bottom: 2px dashed #38bdf8; }
  .gap { display: inline-block; cursor: pointer; font-size: 9px;
         color: #70707c; padding: 0 2px; vertical-align: middle;
         border-radius: 3px; user-select: none; }
  .gap:hover { color: #e8e8ee; background: #24242d; }
  .gap.del { background: #e5484d; color: #fff; }
  .gap.long { color: #f59e0b; font-size: 10px; font-weight: 600;
              background: #241a0e; padding: 1px 4px; }
  .gap.long:hover { background: #3a2a12; color: #fbbf24; }
  .gap.long.del { background: #e5484d; color: #fff; }
  input.edit-in { background: #1c1c26; color: #fff; border: 1px solid #38bdf8;
                  font-size: 15px; border-radius: 3px; padding: 1px 4px; width: 7em; }
  .delrow { font-size: 12px; color: #8a8a96; line-height: 1.6; padding: 2px 0;
            border-bottom: 1px dashed #24242d; }
  .delrow:last-child { border-bottom: none; }
  .deltime { color: #8a8a96; font-variant-numeric: tabular-nums; }
  .deltext { color: #a0a0aa; }
  .tick span { position: absolute; bottom: 7px; left: 3px; font-size: 11px;
               color: #8a8a96; font-variant-numeric: tabular-nums; }
  #stage { position: relative; background: #000; border: 1px solid #26262e;
           border-radius: 10px; overflow: hidden; }
  #stage video { width: 100%; display: block; max-height: 640px; }
  #capbar { position: absolute; left: 0; right: 0; bottom: 0; padding: 10px 16px;
            background: rgba(0,0,0,.72); color: #fff; font-size: 19px;
            text-align: center; min-height: 46px; display: flex;
            align-items: center; justify-content: center; }
  #capbar.empty { display: none; }
  #info { display: grid; grid-template-columns: 1fr 1fr; gap: 8px 24px;
          margin: 14px 0; font-size: 14px; color: #b8b8c4; }
  #info .lbl { color: #6f6f7c; font-size: 12px; letter-spacing: .06em; }
  #info .beat { color: #f59e0b; font-weight: 600; }
  #ruler { position: relative; height: 72px; background: #13131a;
           border: 1px solid #26262e; border-radius: 8px; overflow: hidden;
           cursor: crosshair; user-select: none; touch-action: none; }
  #blocks { position: absolute; inset: 12px 0 18px 0; }
  .seg-block { position: absolute; top: 0; bottom: 0; border-right: 1px solid #0d0d12;
               display: flex; align-items: center; padding: 0 6px; overflow: hidden;
               white-space: nowrap; font-size: 11px; color: #fff; text-shadow: 0 1px 2px #000; }
  .seg-block .d { opacity: .75; margin-left: 5px; font-variant-numeric: tabular-nums; }
  .seg-block.active { outline: 2px solid #fbbf24; outline-offset: -2px; z-index: 2; }
  #ticks { position: absolute; left: 0; right: 0; bottom: 0; height: 16px; }
  .tick { position: absolute; bottom: 0; height: 7px; width: 1px; background: #3a3a46; }
  .tick span { position: absolute; bottom: 7px; left: 3px; font-size: 10px;
               color: #6f6f7c; font-variant-numeric: tabular-nums; }
  #playhead { position: absolute; top: 0; bottom: 0; width: 2px; background: #fbbf24;
              z-index: 3; pointer-events: none; }
  #playhead .hd { position: absolute; top: -2px; left: -5px; border: 5px solid transparent;
                  border-top: 7px solid #fbbf24; }
  #ptime { position: absolute; top: -22px; left: -30px; width: 60px; text-align: center;
           font-size: 11px; color: #fbbf24; background: #1c1c26; border-radius: 4px;
           font-variant-numeric: tabular-nums; pointer-events: none; }
  #cues { margin-top: 14px; max-height: 220px; overflow-y: auto; }
  .cue { display: flex; gap: 10px; padding: 5px 8px; border-bottom: 1px solid #1e1e28;
         font-size: 14px; cursor: pointer; border-radius: 5px; }
  .cue:hover { background: #1a1a24; }
  .cue .ct { color: #6f6f7c; font-variant-numeric: tabular-nums; flex-shrink: 0; }
  #hint { font-size: 12px; color: #6f6f7c; margin: 8px 2px 0; }
</style>
</head>
<body>
<div id="bar">
  <b>EDL 时间线预览</b>
  <button id="btn-play">▶ 播放</button>
  <button id="btn-prev">⏮ 上一刀</button>
  <button id="btn-next">⏭ 下一刀</button>
  <select id="speed">
    <option value="0.25">0.25x</option>
    <option value="0.5">0.5x</option>
    <option value="0.75">0.75x</option>
    <option value="1" selected>1x</option>
    <option value="1.5">1.5x</option>
    <option value="2">2x</option>
    <option value="3">3x</option>
  </select>
  <button id="btn-cut" class="on">剪后预览</button>
  <button id="btn-caps">字幕</button>
  <span id="stats">0:00 / __TOTAL__ · __NSEG__ 段 · 1x</span>
</div>
<div id="wrap">
  <div id="left">
    <div id="stage">
      <video id="main" playsinline></video>
      <div id="capbar"></div>
    </div>
    <div id="info">
      <div><div class="lbl">Beat</div><div id="i-beat" class="beat"></div></div>
      <div><div class="lbl">片段</div><div id="i-seg"></div></div>
      <div style="grid-column:1"><div class="lbl">这段话</div><div id="i-quote"></div></div>
      <div><div class="lbl">为什么这么剪</div><div id="i-reason"></div></div>
    </div>
    <div id="ruler">
      <div id="blocks"></div>
      <div id="ticks"></div>
      <div id="playhead"><div class="hd"></div><div id="ptime">0:00</div></div>
    </div>
    <div id="cues" hidden></div>
    <div id="hint">拖动时间轴 = 预览（像剪辑软件）· 空格播放/暂停 · ←/→ ±1 秒 · 点字幕跳转 · 右侧逐字审阅 · 「剪后预览」开启时播放会跳过已选删除的词/停顿</div>
  </div>
  <div id="side">
    <div class="side-head">
      <b>逐字审阅</b>
      <span id="wstats">0 处选中 · 约减 0.0s</span>
    </div>
    <div class="side-actions">
      <button id="w-save">保存选择</button>
      <button id="w-clear">清空</button>
      <button id="w-clearfix">清空修正</button>
      <button id="w-toggledel">已剪内容 (<span id="w-delcount"></span>)</button>
      <label style="font-size:12px;color:#9a9aa6;display:inline-flex;align-items:center;gap:4px;">
        停顿时长
        <input id="w-pausedur" type="number" min="0" step="0.1" value="0.5"
               style="width:56px;background:#1c1c26;color:#e8e8ee;border:1px solid #3a3a46;border-radius:6px;padding:3px 6px;"> s
      </label>
    </div>
    <div id="w-delpanel" hidden></div>
    <div id="w-hint"><b>单击</b>词：跳转播放（不会删除）；<b>拖动</b>：标记删除，
      从已选词拖起则取消删除（绿色预览）；<b>双击</b>：改字（蓝色虚线=已修正）；
      橙色=长气口 ≥0.5s；黄框=正在播放的词。</div>
    <div id="w-root"></div>
  </div>
</div>
<div id="vpool" hidden></div>
<script>
const SEGS = __SEGS__;
const SRC = __SRC__;
const CUES = __CUES__;
const TOTAL = __TOTAL__;
const PAL = ["#3b82f6", "#10b981", "#f59e0b", "#a855f7", "#ef4444", "#14b8a6"];
const srcColor = {};
Object.keys(SRC).forEach((k, i) => (srcColor[k] = PAL[i % PAL.length]));
const BEAT_COLORS = { HOOK: "#f59e0b", PROBLEM: "#ef4444", SOLUTION: "#22c55e",
                      BENEFIT: "#3b82f6", EXAMPLE: "#a855f7", CTA: "#fbbf24" };
const beatColor = b => {
  const k = Object.keys(BEAT_COLORS).find(x => (b || "").toUpperCase().includes(x));
  return k ? BEAT_COLORS[k] : "#9a9aa6";
};

/* ---- video pool: one element per source file, PRELOAD ONLY (never
       played) — warms the browser cache so segment switches don't
       stutter. Playback happens on the visible #main element. ---- */
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
let cur = -1;            // active segment index
let playing = false;
let playhead = 0;
let raf = null;
let scrubbing = false;
let lastCur = -1;        // for word-panel active segment sync
let lastPlayingG = -1;   // for word-panel moving highlight
let lastPlayEl = null;      // cached .playing element (no per-frame DOM scan)
const sel = new Set();   // "w:G" | "g:S:I"
const restoreSet = new Set();  // deleted-word key "src|ws|we" -> restore on save
const cutWords = [];   // {el, key} — 已剪词的扁平列表（DOM 顺序）
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
/* ---- cut preview: skip selected words/gaps while playing ----
   Time axes: SEGS intervals (o0/o1) and deleted intervals live on the
   OUTPUT timeline; the <video> element plays on the SOURCE timeline.
   Never compare the two directly (that bug made cut preview skip nothing). */
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
  // if only a tiny silence tail remains after the cut, skip it too
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
// Caption bar is OFF by default: the rendered video usually carries burned
// subtitles, and showing the bar on top would double them. Toggle via 字幕.
if (!document.getElementById("btn-caps").classList.contains("on")) {
  capbar.classList.add("empty");
}
if (CUES.length) {
  CUES.forEach((c, i) => {
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
  /* word-review sync: playing word + active segment card */
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

/* ---- playback engine: the visible #main element is the only thing that
       plays; the playhead derives from main.currentTime so the clock stays
       aligned with what the user actually sees ---- */
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
      // only reload when the source actually changes — reassigning the same
      // URL reloads the media element and stutters at every cut boundary
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
  // pre-warm the following segment's source in the hidden pool
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
      // advance on the OUTPUT timeline; skip deleted intervals, then map back
      // scale by the effective playback rate so word highlights, captions and
      // the ruler keep up at 2x/3x — otherwise they lag at 1x wall-clock
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
        // Seek ONLY when a deleted interval was actually jumped. The video
        // clock otherwise tracks the playhead on its own; drift-based seeks
        // re-seek constantly and each seek resets the decode pipeline,
        // starving frame presentation (measured 80% frame drop).
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
  if (e.target.tagName === "SELECT") return;
  if (e.code === "Space") { e.preventDefault(); playing ? pause() : play(); }
  else if (e.code === "ArrowLeft") { pause(); seekTo(playhead - 1); }
  else if (e.code === "ArrowRight") { pause(); seekTo(playhead + 1); }
  else if (e.code === "Home") { pause(); seekTo(0); }
  else if (e.code === "End") { pause(); seekTo(TOTAL); }
});

/* ---- init ---- */
document.getElementById("main").addEventListener("click", () => (playing ? pause() : play()));
seekTo(0);

/* ================= 逐字审阅 (merged from word_picker) ================= */
const DELETED = __DELETED__;
const fixes = new Map();        // unsaved text fixes: wordKey -> text
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
// deleted chunks cut between segments: use the precomputed after_seg (source-time based)
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
  head.innerHTML = '<b style="color:' + beatColor(seg.beat) + '">' + (seg.beat || seg.label) +
                   "</b> · " + fmt(seg.o0) + " - " + fmt(seg.o1) + " · " + seg.label;
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
      span.title = "输出 " + fmt(it.o0) + " · 源 " + it.ws.toFixed(2) + "-" + it.we.toFixed(2) + "s";
      bindWord(span, it.g);
      flow.appendChild(span);
    } else {
      const it = seg.gaps[en.ni];
      const gap = document.createElement("span");
      gap.className = "gap" + (it.long ? " long" : "");
      gap.textContent = "·" + (it.ge - it.gs).toFixed(1) + "s·";
      gap.title = "停顿 " + (it.ge - it.gs).toFixed(2) + "s" + (it.long ? "（长气口）" : "");
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
  // 已剪掉的内容（行内标注，点击跳到剪口听衔接）
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
        s.title = "拖动恢复一行 / 单击恢复这一个字 · 源 " + w.ws.toFixed(2) + "-" + w.we.toFixed(2) + "s";
        s.addEventListener("mousedown", (e) => e.preventDefault());
        div.appendChild(s);
      });
    });
    box.appendChild(div);
  }
  wroot.appendChild(box);
});
buildCutWords();

/* deleted-content panel */
document.getElementById("w-delcount").textContent = DELETED.length;
const toggledel = document.getElementById("w-toggledel");
toggledel.onclick = () => {
  // 隐藏/显示行内"已剪掉"标注，呈现干净逐字稿
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

/* drag select/deselect + click-to-play + dblclick edit.
   Click    = jump to the word and PLAY (never deletes).
   Drag     = select a range for deletion; if the drag STARTS on an already
              selected word it DESELECTS the range instead (undo).
   Dblclick = fix the word text. */
let anchor = null, downKey = null, dragKeys = new Set();
let downPos = null;      // pointer position at mousedown
let dragMode = "add";    // "add" | "remove", decided by anchor's state

// 已剪词的拖动恢复
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
      // robust range even when the drag never crossed a word boundary
      dragKeys = dragKeys.size ? dragKeys : rangeKeys(anchor, g === null ? anchor : g);
      if (dragKeys.size) applyDrag();
    } else if (g === downKey) {
      // click: jump to the word and play — never touches the selection
      const rec = byG.get(g);
      if (rec) { seekTo(rec.item.o0, true, false); play(); }
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
  // Route the save to THIS project's edit dir: one preview server may serve
  // several projects from a shared root, and selections must land in the dir
  // of the page being reviewed, not the server's startup dir.
  const pageDir = location.pathname.split("/").slice(0, -1).join("/") || "/";
  const r = await fetch("/api/save", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ words, pauses, restore: restores, fixes: fixArr, dir: pageDir }),
  });
  const ok = r.ok && (await r.json()).ok;
  const btn = document.getElementById("w-save");
  btn.textContent = ok ? "✓ 已保存，可以告诉我「剪」" : "✗ 保存失败";
  if (ok) setTimeout(() => (btn.textContent = "保存选择"), 6000);
};

wstats();
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
print(f"serve root: {ROOT} → http://localhost:8737/{PAGE_REL.as_posix()} "
      f"(run helpers/edl_preview_serve.py {EDIT})")
