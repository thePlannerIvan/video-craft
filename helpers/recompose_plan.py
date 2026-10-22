#!/usr/bin/env python3
"""Recompose build mode: line-level visual budget + project config.

This is an **internal build mode**, not a user-facing route. The human workflow is
unchanged: approve the board in PPT Hell, record, then review the film. The only
difference is that the approved board is a reference the agent may re-compose.

Artifacts:
  recompose.json            mode marker + draft/composition/person/caption facts
  recompose/lines.json      one row per caption line: state + proposal + note

States:
  auto   follow `proposal` (what the agent suggests)
  off    no graphic; captions + person carry the line
  still  one stable diagram
  light  1-2 parts move with the words
  full   multi-part choreography

The density panel in the existing review page reads this data through
review_data.json; submissions are applied by review_inbox.py.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _probe import probe_video  # noqa: E402

CONFIG_REL = "recompose.json"
LINES_REL = "recompose/lines.json"
STATES = ("auto", "off", "still", "light", "full")
RESOLVED = ("off", "still", "light", "full")
DEFAULT_PROPOSAL = "still"


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_json(path: Path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path: Path, doc) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def enabled(project: Path) -> bool:
    cfg = read_json(Path(project) / CONFIG_REL, {}) or {}
    return str(cfg.get("mode") or "").strip() == "recompose"


def config(project: Path) -> dict:
    return read_json(Path(project) / CONFIG_REL, {}) or {}


def parse_srt(text: str) -> list[dict]:
    """统一实现见 `helpers/_timecode.py`（合并地图 M1）；输出形状保持不变。"""
    from _timecode import flatten as _flatten, parse_srt_text as _parse_srt_text
    return [{
        "id": f"l{cue['index']:03d}",
        "startMs": cue["startMs"],
        "endMs": cue["endMs"],
        "text": _flatten(cue, " "),
    } for cue in _parse_srt_text(text)]


def load_cues(project: Path) -> tuple[list[dict], str]:
    edit = Path(project) / "edit"
    srt = edit / "subtitles.srt"
    if srt.is_file():
        return parse_srt(srt.read_text(encoding="utf-8")), "edit/subtitles.srt"
    cap = edit / "captions.json"
    if cap.is_file():
        raw = read_json(cap, []) or []
        cues = []
        for i, c in enumerate(raw if isinstance(raw, list) else []):
            cues.append({
                "id": f"l{i + 1:03d}",
                "startMs": int(c.get("startMs") or 0),
                "endMs": int(c.get("endMs") or 0),
                "text": str(c.get("text") or ""),
            })
        return cues, "edit/captions.json"
    return [], ""


def chapters_of(timeline: dict) -> list[dict]:
    out = []
    for chapter in timeline.get("chapters") or []:
        steps = chapter.get("steps") or []
        if not steps:
            continue
        out.append({
            "id": str(chapter.get("id") or ""),
            "title": str(chapter.get("title") or ""),
            "startMs": float(steps[0].get("startMs") or 0),
            "endMs": float(steps[-1].get("endMs") or 0),
        })
    return out


def build_lines(project: Path) -> tuple[list[dict], dict]:
    timeline = read_json(Path(project) / "timeline/timeline.json", {}) or {}
    chapters = chapters_of(timeline)
    cues, source = load_cues(project)
    if not chapters:
        raise ValueError("timeline/timeline.json 里没有 chapters")
    if not cues:
        raise ValueError("没有字幕行可做密度：先锁 edit/subtitles.srt 或 edit/captions.json")
    lines = []
    for cue in cues:
        mid = (cue["startMs"] + cue["endMs"]) / 2
        beat = next((c for c in chapters if c["startMs"] <= mid < c["endMs"]), None)
        if beat is None:
            beat = min(chapters, key=lambda c: abs(c["startMs"] - cue["startMs"]))
        lines.append({
            "id": cue["id"],
            "beatId": beat["id"],
            "startMs": cue["startMs"],
            "endMs": cue["endMs"],
            "text": cue["text"],
            "state": "auto",
            "proposal": DEFAULT_PROPOSAL,
            "note": "",
        })
    return lines, {"source": source, "chapters": chapters}


def init_project(project: Path, args) -> dict:
    project = Path(project).resolve()
    cfg_path = project / CONFIG_REL
    lines_path = project / LINES_REL
    if cfg_path.exists() and not args.force:
        raise SystemExit(f"{cfg_path} 已存在；加 --force 重写（不会自动覆盖已审的密度）")
    if lines_path.exists() and not args.force:
        raise SystemExit(f"{lines_path} 已存在；加 --force 重写")
    lines, meta = build_lines(project)
    cfg = {
        "version": 1,
        "mode": "recompose",
        "createdAt": now(),
        "draft": args.draft,
        "composition": args.composition,
        "personSlot": parse_box(args.person_slot, "--person-slot"),
        "captionSafe": parse_box(args.caption_safe, "--caption-safe"),
        "canvas": parse_canvas(args.canvas, args.fps),
        "board": args.board or None,
        "note": "board 是 PPT Hell 批准过的视觉参考；final film 允许重排。",
    }
    write_json(cfg_path, cfg)
    write_json(lines_path, {
        "version": 1,
        "source": meta["source"],
        "updatedAt": now(),
        "beats": meta["chapters"],
        "lines": lines,
    })
    return {"ok": True, "config": str(cfg_path), "lines": str(lines_path),
            "lineCount": len(lines), "beatCount": len(meta["chapters"])}


def parse_box(value: str, field: str) -> dict:
    parts = [p.strip() for p in str(value).split(",")]
    if len(parts) != 4:
        raise SystemExit(f"{field} 需要 x,y,w,h，收到：{value!r}")
    try:
        x, y, w, h = (int(p) for p in parts)
    except ValueError:
        raise SystemExit(f"{field} 必须是整数：{value!r}")
    return {"x": x, "y": y, "w": w, "h": h}


def parse_canvas(value: str, fps) -> dict:
    m = re.split(r"[xX]", str(value))
    if len(m) != 2 or not all(x.isdigit() for x in m):
        raise SystemExit(f"--canvas 需要 WxH，收到：{value!r}")
    return {"w": int(m[0]), "h": int(m[1]), "fps": int(fps)}


def validate_record(record: dict, lines_doc: dict) -> tuple[list[dict], str | None]:
    if str(record.get("phase") or "") != "density":
        return [], "phase 必须是 density"
    raw = record.get("lines")
    if not isinstance(raw, list) or not raw:
        return [], "density.lines 必须是非空数组"
    known = {str(one.get("id")): one for one in (lines_doc.get("lines") or [])}
    seen, clean = set(), []
    for one in raw:
        if not isinstance(one, dict):
            return [], "lines 里有一项不是对象"
        lid = str(one.get("id") or "")
        if lid not in known:
            return [], f"未知 line id：{lid!r}"
        if lid in seen:
            return [], f"line 重复：{lid}"
        seen.add(lid)
        state = one.get("state")
        if state not in STATES:
            return [], f"{lid}: state={state!r} 不在 {'/'.join(STATES)}"
        clean.append({"id": lid, "state": state, "note": str(one.get("note") or "")})
    return clean, None


def apply_record(project: Path, record: dict) -> dict:
    project = Path(project).resolve()
    path = project / LINES_REL
    doc = read_json(path, {}) or {}
    clean, error = validate_record(record, doc)
    if error:
        raise ValueError(error)
    by_id = {str(one.get("id")): one for one in doc.get("lines") or []}
    changed = []
    for one in clean:
        row = by_id[one["id"]]
        before = (row.get("state"), row.get("note") or "")
        after = (one["state"], one["note"])
        if before != after:
            changed.append({"id": one["id"], "before": before[0], "after": after[0]})
        row["state"] = one["state"]
        row["note"] = one["note"]
    doc["updatedAt"] = now()
    write_json(path, doc)
    return {"changed": changed, "lines": str(path)}


def check_project(project: Path, require_draft: bool = False) -> dict:
    project = Path(project).resolve()
    problems, warnings = [], []
    cfg = read_json(project / CONFIG_REL)
    doc = read_json(project / LINES_REL)
    if not cfg:
        problems.append(f"缺 {CONFIG_REL}（这不是 recompose 模式）")
    elif str(cfg.get("mode") or "") != "recompose":
        problems.append(f"{CONFIG_REL} 的 mode 不是 recompose")
    if not doc:
        problems.append(f"缺 {LINES_REL}（先跑 recompose_plan.py init）")
    if problems:
        return {"ok": False, "problems": problems, "warnings": warnings}
    lines = doc.get("lines") or []
    if not lines:
        problems.append(f"{LINES_REL} 没有 lines")
    seen = set()
    last = -1
    for line in lines:
        lid = str(line.get("id") or "")
        if not lid or lid in seen:
            problems.append(f"line id 为空或重复：{lid!r}")
        seen.add(lid)
        if line.get("state") not in STATES:
            problems.append(f"{lid}: state={line.get('state')!r} 非法")
        if line.get("proposal") not in RESOLVED:
            problems.append(f"{lid}: proposal={line.get('proposal')!r} 非法")
        if int(line.get("startMs") or 0) < last:
            problems.append(f"{lid}: startMs 倒退")
        last = int(line.get("startMs") or 0)
    canvas = cfg.get("canvas") or {}
    cw, ch = int(canvas.get("w") or 0), int(canvas.get("h") or 0)
    for key in ("personSlot", "captionSafe"):
        box = cfg.get(key) or {}
        if not all(isinstance(box.get(k), int) for k in ("x", "y", "w", "h")):
            problems.append(f"{key} 需要 x/y/w/h 整数")
        elif cw and ch and (box["x"] + box["w"] > cw or box["y"] + box["h"] > ch):
            problems.append(f"{key} 超出画幅 {cw}×{ch}")
    comp = project / str(cfg.get("composition") or "")
    if not (comp / "index.html").is_file():
        warnings.append(f"composition 里没有 index.html：{comp}（构建前补上）")
    draft = project / str(cfg.get("draft") or "")
    if not draft.is_file():
        msg = f"draft 不存在：{draft}"
        (problems if require_draft else warnings).append(msg)
    elif probe_video(draft).get("duration") is None:
        problems.append(f"draft 不是可读视频：{draft}")
    return {"ok": not problems, "problems": problems, "warnings": warnings,
            "lineCount": len(lines), "beatCount": len(doc.get("beats") or [])}


def print_lines(project: Path) -> dict:
    doc = read_json(Path(project) / LINES_REL, {}) or {}
    rows = [{
        "id": one.get("id"), "beat": one.get("beatId"),
        "start": round(int(one.get("startMs") or 0) / 1000, 2),
        "end": round(int(one.get("endMs") or 0) / 1000, 2),
        "state": one.get("state"), "proposal": one.get("proposal"),
        "text": one.get("text"),
    } for one in doc.get("lines") or []]
    return {"ok": True, "lines": rows}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Recompose build mode: line-level visual budget")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init")
    p_init.add_argument("project")
    p_init.add_argument("--draft", default="recompose/draft.mp4")
    p_init.add_argument("--composition", default="composition")
    p_init.add_argument("--person-slot", default="0,0,620,1080")
    p_init.add_argument("--caption-safe", default="0,885,1920,195")
    p_init.add_argument("--canvas", default="1920x1080")
    p_init.add_argument("--fps", default="30")
    p_init.add_argument("--board", default="")
    p_init.add_argument("--force", action="store_true")
    p_init.add_argument("--json", action="store_true")

    p_check = sub.add_parser("check")
    p_check.add_argument("project")
    p_check.add_argument("--require-draft", action="store_true")
    p_check.add_argument("--json", action="store_true")

    p_lines = sub.add_parser("lines")
    p_lines.add_argument("project")
    p_lines.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    project = Path(args.project).expanduser().resolve()
    if args.cmd == "init":
        result = init_project(project, args)
    elif args.cmd == "check":
        result = check_project(project, require_draft=args.require_draft)
    else:
        result = print_lines(project)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=1))
    elif args.cmd == "lines":
        print("ID      BEAT      RANGE          STATE  TEXT")
        for row in result["lines"]:
            print(f"{row['id']:<7} {row['beat']:<9} {row['start']:>6.1f}-{row['end']:<6.1f} {row['state']:<6} {row['text']}")
    else:
        print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0 if result.get("ok", True) else 2


if __name__ == "__main__":
    raise SystemExit(main())
