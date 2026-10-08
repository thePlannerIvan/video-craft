#!/usr/bin/env python3
"""Derive deterministic per-screen animation choreography (`timeline/choreography.json`).

Bridges static SVG screens (`[data-step]`, `data-anim`, `data-cue`, `data-camera`,
optional `data-rel-start`) with the measured timeline (`timeline/timeline.json`
and optional `caption_words.json` / `sentences.json`).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from import_svg_page import resolve_pages
from snapshot_input import resolve_snapshot, invalidation


def _clean_text(s: str) -> str:
    return re.sub(r"[\s，。！？、；：“”‘’（）()《》…—\-·,.!?:;\"']", "", s or "")


def _infer_anim(el: ET.Element) -> str:
    explicit = el.attrib.get("data-anim")
    if explicit:
        return explicit
    xml_str = ET.tostring(el, encoding="unicode")
    if "slot-left" in xml_str or "slot-core" in xml_str:
        return "slot-push"
    if 'pathLength="1"' in xml_str or "anim-stroke" in xml_str:
        return "draw-stroke"
    if "anim-fill" in xml_str or "anim-wall" in xml_str or "anim-bar-h" in xml_str or "anim-bar-v" in xml_str:
        return "meter-halt"
    if "wipe-bar" in xml_str or "anim-typewriter" in xml_str:
        return "cursor-wipe"
    if "polaroid-unit" in xml_str or "anim-tape" in xml_str:
        return "polaroid-slap"
    if "anim-stamp" in xml_str:
        return "stamp-in"
    if "anim-count" in xml_str:
        return "number-ticker"
    text_content = "".join(el.itertext())
    if re.search(r"\d+(?:\.\d+)?%|\d{3,}", text_content):
        return "number-ticker"
    return "stagger-cards"


def parse_svg_steps(svg_path: Path) -> list[dict]:
    """Extract all `[data-step]` groups and their pre-wired attributes from an SVG file."""
    if not svg_path or not svg_path.is_file():
        return []
    try:
        root = ET.fromstring(svg_path.read_text(encoding="utf-8"))
    except ET.ParseError:
        return []

    speaker_w = 0
    try:
        speaker_w = int(root.attrib.get("data-speaker-width") or 0)
    except ValueError:
        speaker_w = 0

    steps = []
    for el in root.iter():
        step_raw = el.attrib.get("data-step")
        if step_raw is None:
            continue
        try:
            step_num = int(step_raw)
        except ValueError:
            continue
        rel_raw = el.attrib.get("data-rel-start")
        rel_val = float(rel_raw) if rel_raw not in (None, "") else None
        steps.append({
            "step": step_num,
            "id": el.attrib.get("id") or f"step-{step_num}",
            "anim": _infer_anim(el),
            "camera": "none" if speaker_w > 0 else (el.attrib.get("data-camera") or ""),
            "cue": el.attrib.get("data-cue") or "",
            "relStartSec": rel_val,
            "speakerWidth": speaker_w,
        })
    steps.sort(key=lambda x: x["step"])
    return steps


def _load_measured_words(project: Path) -> list[dict]:
    for cand in (
        project / "caption_words.json",
        project / "edit" / "caption_words.json",
        project / "edit2" / "caption_words.json",
        project.parent / "edit" / "caption_words.json",
        project.parent / "edit2" / "caption_words.json",
    ):
        if cand.is_file():
            try:
                data = json.loads(cand.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    return data
                if isinstance(data, dict) and isinstance(data.get("words"), list):
                    return data["words"]
            except ValueError:
                pass
    return []


def match_cue_offset_sec(cue: str, caption: str, duration_s: float, idx: int, total: int,
                         words: list[dict] | None = None, screen_start_s: float = 0.0) -> tuple[float, int]:
    """Compute `(relative_start_sec, sub_delay_ms)` for a step within a screen of `duration_s`."""
    if total <= 1 or idx == 0:
        return 0.05, 220

    cue_clean = _clean_text(cue)
    if words and cue_clean:
        anchor = cue_clean[:5]
        if len(anchor) >= 2:
            window_words = [
                w for w in words
                if float(w.get("out_start", w.get("start", -1))) >= screen_start_s - 0.3
                and float(w.get("out_start", w.get("start", 1e9))) <= screen_start_s + duration_s + 0.3
            ]
            acc = ""
            char_to_time = []
            for w in window_words:
                w_txt = _clean_text(w.get("text", w.get("word", "")))
                w_start = float(w.get("out_start", w.get("start", screen_start_s)))
                for _ in w_txt:
                    char_to_time.append(max(0.0, w_start - screen_start_s))
                acc += w_txt
            pos = acc.find(anchor)
            if pos >= 0 and pos < len(char_to_time):
                rel_s = round(min(max(0.05, char_to_time[pos]), max(0.2, duration_s - 0.6)), 2)
                sub_ms = 280 if ("，" in cue or "……" in cue) else 160
                return rel_s, sub_ms

    cap_clean = _clean_text(caption)
    if cue_clean and cap_clean:
        anchor = cue_clean[:5]
        pos = cap_clean.find(anchor)
        if pos >= 0 and len(cap_clean) > 0:
            ratio = pos / len(cap_clean)
            rel_s = round(min(max(0.1, ratio * duration_s * 0.88), max(0.2, duration_s - 0.6)), 2)
            sub_ms = 280 if ("，" in cue or "……" in cue) else 160
            return rel_s, sub_ms

    slot_span = (duration_s * 0.78) / max(1, total)
    rel_s = round(0.05 + idx * slot_span, 2)
    sub_ms = 240 if ("，" in cue or "……" in cue) else 150
    return rel_s, sub_ms


def build_choreography(project: Path, pages_dir: Path | None = None) -> dict:
    """Build or update `<project>/timeline/choreography.json`."""
    project = project.resolve()
    tl_path = project / "timeline" / "timeline.json"
    if not tl_path.is_file():
        raise FileNotFoundError(f"missing timeline: {tl_path}")
    timeline = json.loads(tl_path.read_text(encoding="utf-8"))

    snapshot = resolve_snapshot(project, pages_dir)
    pages_dir, _ = resolve_pages(project, pages_dir)
    if pages_dir is None and (project / 'svg').is_dir():
        pages_dir = project / 'svg'

    measured_words = _load_measured_words(project)

    choreo_path = project / "timeline" / "choreography.json"
    existing_screens = {}
    existing = {}
    if choreo_path.is_file():
        try:
            existing = json.loads(choreo_path.read_text(encoding="utf-8"))
            existing_screens = existing.get("screens", {})
        except ValueError:
            existing_screens = {}

    screens_out = {}
    changes = invalidation(existing.get('snapshot', {}), snapshot) if snapshot else None
    fps = float(timeline.get("fps", 30))
    for ch in timeline.get("chapters", []):
        for st in ch.get("steps", []):
            sid = st["id"]
            if "durationMs" in st:
                dur_s = round(float(st["durationMs"]) / 1000.0, 3)
            elif "durationInFrames" in st:
                dur_s = round(float(st["durationInFrames"]) / fps, 3)
            else:
                dur_s = 4.0
            start_s = round(float(st.get("startMs", 0)) / 1000.0, 3)
            page_key = st.get("sourcePageKey") or Path(st.get("svg", sid)).stem
            if snapshot and page_key not in snapshot.pages:
                raise ValueError(f'Timeline screen {sid} has no matching snapshot page {page_key}')
            svg_file = (pages_dir / f"{page_key}.svg") if pages_dir else None
            raw_steps = parse_svg_steps(svg_file) if svg_file else []

            prev_screen = existing_screens.get(sid, {})
            if (snapshot and page_key not in changes['static_screens'] and prev_screen
                    and prev_screen.get('sourcePageKey') == page_key
                    and prev_screen.get('startSec') == start_s and prev_screen.get('durationSec') == dur_s
                    and prev_screen.get('chapterId') == ch['id']):
                screens_out[sid] = prev_screen
                continue
            prev_steps = {int(k): v for k, v in (prev_screen.get("steps") or {}).items()}

            has_speaker = any(item.get("speakerWidth", 0) > 0 for item in raw_steps)
            default_cam = "none" if has_speaker else ("focus-step" if len(raw_steps) >= 3 else "none")
            step_map = {}
            for idx, item in enumerate(raw_steps):
                snum = item["step"]
                if item["relStartSec"] is not None:
                    rel_s = round(float(item["relStartSec"]), 2)
                    sub_ms = 240 if ("，" in item["cue"] or "……" in item["cue"]) else 160
                else:
                    rel_s, sub_ms = match_cue_offset_sec(
                        item["cue"], st.get("caption", ""), dur_s, idx, len(raw_steps),
                        words=measured_words, screen_start_s=start_s
                    )
                over = prev_steps.get(snum, {})
                if snapshot and over.get('id') != item['id']:
                    over = {}
                resolved_rel = over.get("relStartSec", rel_s)
                step_map[str(snum)] = {
                    "step": snum,
                    "id": item["id"],
                    "anim": over.get("anim") or item["anim"],
                    "camera": "none" if has_speaker else (over.get("camera") or item["camera"] or default_cam),
                    "relStartSec": resolved_rel,
                    "startSec": round(start_s + float(resolved_rel), 3),
                    "subDelayMs": over.get("subDelayMs", sub_ms),
                    "cue": over.get("cue") or item["cue"],
                }

            screens_out[sid] = {
                "stepId": sid,
                "chapterId": ch["id"],
                "sourcePageKey": page_key,
                "startSec": start_s,
                "durationSec": dur_s,
                "cameraMode": "none" if has_speaker else prev_screen.get("cameraMode", default_cam),
                "focusMode": prev_screen.get("focusMode", "spotlight"),
                "steps": step_map,
            }

    doc = {
        "version": "4.0.0",
        "contract_version": "video-craft-choreography/1.0.0",
        "screens": screens_out,
    }
    if snapshot:
        doc['snapshot'] = snapshot.binding()
        doc['invalidation'] = changes
    choreo_path.parent.mkdir(parents=True, exist_ok=True)
    choreo_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return doc


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Generate timeline/choreography.json from SVG steps + timeline.json")
    ap.add_argument("project", type=Path, help="Video project directory")
    ap.add_argument("--pages", type=Path, default=None, help="Optional SVG directory override")
    args = ap.parse_args(argv)
    doc = build_choreography(args.project, args.pages)
    print(f"choreography -> {args.project / 'timeline' / 'choreography.json'} ({len(doc['screens'])} screens)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
