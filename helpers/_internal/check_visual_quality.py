#!/usr/bin/env python3
"""Unified build-time visual quality gate (Q1-Q6 + demo-footage specialized checks).

Routes checks by tier declared in `<project>/visual-plan.json`:
  - `demo-footage`: exempt from >=32px text size and >6-8s static checks;
    strictly checks source exists outside composition/assets/, valid in/out bounds,
    non-black sampled frames, and no intrusion into personSlot / captionSafe.
  - `talk-only`: exempt from Q1 font size & Q2 static-duration warnings/errors.
  - `logic-diagram` / `theory-board` (or default composition): checks:
      Q1  Minimum font size >= 32px at 1080p (captions exempt)
      Q2  Max continuous static duration (error > 8.0s, warn > 6.0s)
      Q3  Bounding-box intrusion into unified personSlot or captionSafe
      Q4  Horizontal/vertical SVG <line>/<path> with filter missing filterUnits="userSpaceOnUse"
      Q5  Unregistered local/custom font-family references
      Q6  Multi-chapter root elements lacking exit/hide transition

Exit codes: 0 = pass, 1 = error findings, 2 = missing project/usage error.
"""
from __future__ import annotations

import argparse
import ast
import json
import operator
import re
import subprocess
import sys
from pathlib import Path

INTERNAL = Path(__file__).resolve().parent
if str(INTERNAL) not in sys.path:
    sys.path.insert(0, str(INTERNAL))

from _geometry import box_intersects, resolve_project_frame  # noqa: E402

SKIP_DIRS = {"node_modules", ".hyperframes", "_render", "renders", ".git", ".cache"}
TEXT_SUFFIXES = {".html", ".htm", ".css", ".svg"}
CODE_SUFFIXES = {".html", ".htm", ".js", ".mjs"}

SYSTEM_AND_GENERIC_FONTS = {
    "sans-serif", "serif", "monospace", "cursive", "fantasy", "system-ui",
    "-apple-system", "blinkmacsystemfont", "pingfang sc", "pingfangsc-regular",
    "pingfangsc-medium", "pingfangsc-semibold", "hiragino sans gb",
    "microsoft yahei", "noto sans sc", "noto serif sc", "noto sans",
    "helvetica", "helvetica neue", "arial", "inter", "sf pro",
    "sf pro display", "sf pro text", "sf mono", "jetbrains mono",
    "menlo", "monaco", "consolas", "georgia", "times new roman",
    "inherit", "initial", "unset", "currentcolor",
}


def _strip_comments(text: str, suffix: str) -> str:
    if suffix in {".css", ".js", ".mjs"}:
        text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    if suffix in {".js", ".mjs"}:
        text = re.sub(r"(?m)//.*$", "", text)
    if suffix in {".html", ".htm", ".svg"}:
        text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    return text


def _collect_files(comp_dir: Path) -> list[Path]:
    if not comp_dir.is_dir():
        return []
    out: list[Path] = []
    for p in sorted(comp_dir.rglob("*")):
        if not p.is_file():
            continue
        if any(part in SKIP_DIRS for part in p.relative_to(comp_dir).parts):
            continue
        if p.name.endswith((".min.js", ".min.css")):
            continue
        if p.suffix.lower() in (TEXT_SUFFIXES | CODE_SUFFIXES):
            out.append(p)
    return out


def _ffprobe_duration(path: Path) -> float | None:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        return None
    try:
        return float((proc.stdout or "").strip())
    except ValueError:
        return None


def _frame_mean_luma(path: Path, at_sec: float) -> float | None:
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{max(0.0, at_sec):.3f}", "-i", str(path),
         "-frames:v", "1", "-vf", "scale=160:90,format=gray", "-f", "rawvideo", "-"],
        capture_output=True,
    )
    if proc.returncode != 0 or not proc.stdout:
        return None
    return sum(proc.stdout) / len(proc.stdout)


def _check_demo_segments(project: Path, plan: dict, geo: dict, errors: list[dict]) -> None:
    comp_assets = (project / "composition" / "assets").resolve()
    person = geo["person"]
    caption = geo["caption"]
    for idx, seg in enumerate(plan.get("segments") or []):
        if not isinstance(seg, dict) or seg.get("tier") != "demo-footage":
            continue
        sid = str(seg.get("id") or f"demo-{idx + 1}")
        demo = seg.get("demo")
        if not isinstance(demo, dict) or not demo.get("source"):
            errors.append({"rule": "DEMO_SOURCE", "id": sid, "detail": f"{sid}: 缺少 demo.source"})
            continue
        raw = Path(str(demo["source"])).expanduser()
        src = (raw if raw.is_absolute() else (project / raw)).resolve()
        if src == comp_assets or src.is_relative_to(comp_assets):
            errors.append({"rule": "DEMO_IN_ASSETS", "id": sid, "detail": f"{sid}: 原录屏不得放入 composition/assets/: {demo['source']}"})
            continue
        if not src.is_file():
            errors.append({"rule": "DEMO_MISSING", "id": sid, "detail": f"{sid}: 找不到实机录屏文件 {src}"})
            continue

        in_s = float(demo.get("inSec", 0.0))
        out_s = float(demo.get("outSec", 0.0))
        src_dur = _ffprobe_duration(src)
        if src_dur is None:
            errors.append({"rule": "DEMO_UNREADABLE", "id": sid, "detail": f"{sid}: 无法读取实机录屏时长 {src}"})
            continue
        if in_s < 0 or out_s <= in_s or out_s > src_dur + 0.05:
            errors.append({
                "rule": "DEMO_RANGE",
                "id": sid,
                "detail": f"{sid}: demo 入出点越界 [{in_s:.2f}, {out_s:.2f}]s（源文件仅 {src_dur:.2f}s）",
            })
            continue

        mid = (in_s + out_s) / 2.0
        luma = _frame_mean_luma(src, mid)
        if luma is not None and luma < 6.0:
            errors.append({
                "rule": "DEMO_BLACK_FRAME",
                "id": sid,
                "detail": f"{sid}: 实机录屏片段在 {mid:.2f}s 处接近全黑 (luma={luma:.1f})",
            })

        box = demo.get("box") if isinstance(demo.get("box"), dict) else geo["stage"]
        if person["w"] > 0 and box_intersects(box, person):
            errors.append({
                "rule": "DEMO_SAFEZONE",
                "id": sid,
                "detail": f"{sid}: 实机录屏显示区域 {box} 侵入人物区 {person}",
            })
        if caption["h"] > 0 and box_intersects(box, caption):
            errors.append({
                "rule": "DEMO_SAFEZONE",
                "id": sid,
                "detail": f"{sid}: 实机录屏显示区域 {box} 侵入字幕安全区 {caption}",
            })


_VOID_HTML_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}
_DATA_ROLE_RE = re.compile(r'\bdata-role\s*=\s*(?:"([^"]*)"|\'([^\']*)\')', re.I)


def _role_spans(raw: str, roles: tuple[str, ...] = ("background", "caption", "person")) -> list[tuple[int, int]]:
    """Return [(start, end), ...] for elements (and their descendants) matching `data-role`."""
    want = {r.lower() for r in roles}
    spans: list[tuple[int, int]] = []
    stack: list[tuple[str, int | None]] = []
    for m in re.finditer(r"<(/?)([a-zA-Z][\w:-]*)\b([^>]*)>", raw):
        closing, tag, attrs = m.group(1), m.group(2).lower(), m.group(3)
        if not closing:
            rm = _DATA_ROLE_RE.search(attrs)
            role = (rm.group(1) if rm and rm.group(1) is not None else (rm.group(2) if rm else "")).strip().lower()
            start_pos = m.start() if role in want else None
            self_close = attrs.rstrip().endswith("/") or tag in _VOID_HTML_TAGS
            if self_close:
                if start_pos is not None:
                    spans.append((start_pos, m.end()))
            else:
                stack.append((tag, start_pos))
        else:
            for idx in range(len(stack) - 1, -1, -1):
                if stack[idx][0] == tag:
                    for _, s_pos in stack[idx:]:
                        if s_pos is not None:
                            spans.append((s_pos, m.end()))
                    del stack[idx:]
                    break
    for _, s_pos in stack:
        if s_pos is not None:
            spans.append((s_pos, len(raw)))
    return spans


def _in_spans(pos: int, spans: list[tuple[int, int]]) -> bool:
    return any(s0 <= pos < s1 for s0, s1 in spans)


def _is_exempt_text_context(ctx: str) -> bool:
    low = ctx.lower()
    return any(
        tok in low
        for tok in (
            "caption",
            "subtitle",
            'data-role="caption"',
            "data-role='caption'",
            'data-role="background"',
            "data-role='background'",
            'data-role="person"',
            "data-role='person'",
            'data-tier="talk-only"',
            'data-tier="demo-footage"',
        )
    )


def _check_min_font_size(files: list[Path], geo: dict, errors: list[dict]) -> None:
    scale = 1080.0 / float(geo["height"] or 1080)
    css_rule_re = re.compile(r"([^{};@]+)\{([^{}]*)\}", re.S)
    font_size_re = re.compile(r"\bfont-size\s*:\s*([\d.]+)\s*px\b", re.I)
    style_blocks_re = re.compile(r"<style\b[^>]*>(.*?)</style>", re.S | re.I)

    for path in files:
        suf = path.suffix.lower()
        if suf not in TEXT_SUFFIXES:
            continue
        raw = _strip_comments(path.read_text(encoding="utf-8", errors="ignore"), suf)

        css_chunks: list[str] = []
        if suf == ".css":
            css_chunks.append(raw)
        elif suf in {".html", ".htm", ".svg"}:
            css_chunks.extend(m.group(1) for m in style_blocks_re.finditer(raw))

        for chunk in css_chunks:
            for m in css_rule_re.finditer(chunk):
                sel = m.group(1).strip()
                body = m.group(2)
                if sel.lower() in (":root", "html") or _is_exempt_text_context(sel):
                    continue
                for fm in font_size_re.finditer(body):
                    eff = float(fm.group(1)) * scale
                    if eff < 32.0:
                        errors.append({
                            "rule": "Q1_FONT_SIZE",
                            "file": str(path),
                            "detail": f"{path.name} `{sel}` 字号 {eff:.1f}px < 32px（1080p 手机端可读底线）",
                        })

        if suf in {".html", ".htm", ".svg"}:
            exempt_spans = _role_spans(raw)
            for tag_m in re.finditer(r"<([a-zA-Z][\w:-]*)\b([^>]*)>", raw):
                tag, attrs = tag_m.group(1), tag_m.group(2)
                if _in_spans(tag_m.start(), exempt_spans) or _is_exempt_text_context(tag + " " + attrs):
                    continue
                style_m = re.search(r'\bstyle\s*=\s*(?:"([^"]*)"|\'([^\']*)\')', attrs, re.I)
                if style_m:
                    st = style_m.group(1) if style_m.group(1) is not None else style_m.group(2)
                    for fm in font_size_re.finditer(st):
                        eff = float(fm.group(1)) * scale
                        if eff < 32.0:
                            errors.append({
                                "rule": "Q1_FONT_SIZE",
                                "file": str(path),
                                "detail": f"{path.name} <{tag}> 内联字号 {eff:.1f}px < 32px",
                            })
                svg_fs = re.search(r'(?<!-)\bfont-size\s*=\s*(?:"([\d.]+)(?:px)?"|\'([\d.]+)(?:px)?\')', attrs, re.I)
                if svg_fs:
                    val = float(svg_fs.group(1) or svg_fs.group(2)) * scale
                    if val < 32.0:
                        errors.append({
                            "rule": "Q1_FONT_SIZE",
                            "file": str(path),
                            "detail": f"{path.name} <{tag} font-size={val:.1f}> < 32px",
                        })


def _extract_anchor_cues(files: list[Path]) -> dict[int, float]:
    cues: dict[int, float] = {}
    anchor_re = re.compile(r'"cues"\s*:\s*(\[\[.*?\]\])', re.S)
    for path in files:
        if path.suffix.lower() not in CODE_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for m in anchor_re.finditer(text):
            try:
                arr = json.loads(m.group(1))
            except json.JSONDecodeError:
                continue
            for item in arr:
                if isinstance(item, list) and len(item) >= 2 and isinstance(item[0], int) and isinstance(item[1], (int, float)):
                    cues[int(item[0])] = float(item[1])
    return cues


def _extract_change_times(files: list[Path]) -> list[float]:
    times: set[float] = set()
    cues = _extract_anchor_cues(files)
    call_re = re.compile(r"\.(?:to|fromTo|from|set|add)\s*\(")
    cue_call_re = re.compile(r"\bC\(\s*(\d+)\s*\)(?:\s*([+-])\s*(\d+(?:\.\d+)?))?")
    for path in files:
        suf = path.suffix.lower()
        if suf not in CODE_SUFFIXES:
            continue
        text = _strip_comments(path.read_text(encoding="utf-8", errors="ignore"), suf)
        for m in re.finditer(r'\bdata-(?:start|at)\s*=\s*["\']([\d.]+)["\']', text):
            times.add(float(m.group(1)))
        if cues:
            for cm in cue_call_re.finditer(text):
                idx = int(cm.group(1))
                if idx in cues:
                    t = cues[idx]
                    if cm.group(2) and cm.group(3):
                        delta = float(cm.group(3))
                        t = t + delta if cm.group(2) == "+" else t - delta
                    times.add(max(0.0, t))
        for m in call_re.finditer(text):
            depth = 1
            i = m.end()
            while i < len(text) and depth > 0:
                if text[i] == "(":
                    depth += 1
                elif text[i] == ")":
                    depth -= 1
                i += 1
            if depth == 0:
                call_args = text[m.end():i - 1]
                pos_m = re.search(r",\s*(\d+(?:\.\d+)?)\s*$", call_args.strip())
                if pos_m:
                    t = float(pos_m.group(1))
                    times.add(t)
                    dur_m = re.search(r"\bduration\s*:\s*(\d+(?:\.\d+)?)", call_args)
                    if dur_m:
                        times.add(t + min(float(dur_m.group(1)), 2.5))
    return sorted(times)


def _check_static_duration(files: list[Path], plan: dict | None, comp_dir: Path,
                           max_static_s: float, errors: list[dict], warnings: list[dict]) -> None:
    windows: list[tuple[str, float, float]] = []
    if plan and isinstance(plan.get("segments"), list):
        for idx, seg in enumerate(plan["segments"]):
            if not isinstance(seg, dict):
                continue
            tier = seg.get("tier") or "logic-diagram"
            if tier in ("talk-only", "demo-footage"):
                continue
            st0 = float(seg.get("startMs", 0)) / 1000.0
            st1 = float(seg.get("endMs", 0)) / 1000.0
            windows.append((str(seg.get("id") or f"seg-{idx + 1}"), st0, st1))
    else:
        idx_html = comp_dir / "index.html"
        if idx_html.is_file():
            m = re.search(r'\bdata-duration\s*=\s*["\']([\d.]+)["\']', idx_html.read_text(encoding="utf-8", errors="ignore"))
            if m:
                windows.append(("composition", 0.0, float(m.group(1))))

    if not windows:
        return
    changes = _extract_change_times(files)
    for wid, w0, w1 in windows:
        if w1 - w0 <= 6.0:
            continue
        pts = [w0, *(t for t in changes if w0 < t < w1), w1]
        max_gap = max(b - a for a, b in zip(pts, pts[1:]))
        if max_gap > max_static_s:
            errors.append({
                "rule": "Q2_STATIC_DURATION",
                "id": wid,
                "detail": f"{wid}: 存在连续 {max_gap:.1f}s（>{max_static_s:.1f}s）无视觉状态变化",
            })
        elif max_gap > 6.0:
            warnings.append({
                "rule": "Q2_STATIC_WARN",
                "id": wid,
                "detail": f"{wid}: 存在 {max_gap:.1f}s 连续静止区间（建议 6–8s 内给予微推进）",
            })


def _num_attr(attrs: str, name: str) -> float | None:
    m = re.search(rf'\b{re.escape(name)}\s*=\s*(?:"(-?[\d.]+)"|\'(-?[\d.]+)\')', attrs, re.I)
    if not m:
        return None
    try:
        return float(m.group(1) if m.group(1) is not None else m.group(2))
    except ValueError:
        return None


def _style_id_offsets(raw: str) -> dict[str, tuple[int, int]]:
    """Extract `#id { left: ..px; top: ..px }` pixel offsets from <style> blocks."""
    id_offsets: dict[str, tuple[int, int]] = {}
    for sm in re.finditer(r"<style\b[^>]*>(.*?)</style>", raw, re.S | re.I):
        for rm in re.finditer(r"#([A-Za-z_][\w-]*)\s*\{([^}]*)\}", sm.group(1)):
            lm = re.search(r"\bleft\s*:\s*(-?[\d.]+)px", rm.group(2))
            tm = re.search(r"\btop\s*:\s*(-?[\d.]+)px", rm.group(2))
            if lm or tm:
                id_offsets[rm.group(1)] = (
                    int(round(float(lm.group(1)))) if lm else 0,
                    int(round(float(tm.group(1)))) if tm else 0,
                )
    return id_offsets


def _attrs_offset(attrs: str, id_offsets: dict[str, tuple[int, int]]) -> tuple[int, int]:
    """Resolve explicit CSS `left/top` and SVG `transform="translate(x, y)"` on one tag."""
    ox, oy = 0, 0
    idm = re.search(r'\bid\s*=\s*["\']([^"\']+)["\']', attrs)
    if idm and idm.group(1) in id_offsets:
        ox, oy = id_offsets[idm.group(1)]
    st_m = re.search(r'\bstyle\s*=\s*(?:"([^"]*)"|\'([^\']*)\')', attrs, re.I)
    if st_m:
        st = st_m.group(1) if st_m.group(1) is not None else st_m.group(2)
        lm = re.search(r"\bleft\s*:\s*(-?[\d.]+)px", st)
        tm = re.search(r"\btop\s*:\s*(-?[\d.]+)px", st)
        if lm:
            ox = int(round(float(lm.group(1))))
        if tm:
            oy = int(round(float(tm.group(1))))
    tr_m = re.search(
        r'\btransform\s*=\s*(?:"[^"]*translate\(\s*(-?[\d.]+)(?:px)?\s*(?:,\s*(-?[\d.]+)(?:px)?)?\s*\)[^"]*"'
        r'|\'[^\']*translate\(\s*(-?[\d.]+)(?:px)?\s*(?:,\s*(-?[\d.]+)(?:px)?)?\s*\)[^\']*\')',
        attrs,
        re.I,
    )
    if tr_m:
        tx = tr_m.group(1) if tr_m.group(1) is not None else tr_m.group(3)
        ty = tr_m.group(2) if tr_m.group(2) is not None else tr_m.group(4)
        if tx is not None:
            ox += int(round(float(tx)))
        if ty is not None:
            oy += int(round(float(ty)))
    return ox, oy


def _ancestor_offset_spans(raw: str) -> list[tuple[int, int, int, int]]:
    """Return [(start, end, dx, dy), ...] for ALL positioned ancestor containers (<div|section|g|svg|...>)."""
    id_offsets = _style_id_offsets(raw)
    spans: list[tuple[int, int, int, int]] = []
    stack: list[tuple[str, int, int, int]] = []
    container_tags = {"div", "section", "main", "article", "aside", "g", "svg"}
    for m in re.finditer(r"<(/?)([a-zA-Z][\w:-]*)\b([^>]*)>", raw, re.S):
        closing, tag, attrs = m.group(1), m.group(2).lower(), m.group(3)
        if not closing:
            if tag in container_tags and not (attrs.rstrip().endswith("/") or tag in _VOID_HTML_TAGS):
                dx, dy = _attrs_offset(attrs, id_offsets)
                stack.append((tag, m.start(), dx, dy))
        else:
            for idx in range(len(stack) - 1, -1, -1):
                if stack[idx][0] == tag:
                    for _t, s_pos, dx, dy in stack[idx:]:
                        if dx or dy:
                            spans.append((s_pos, m.end(), dx, dy))
                    del stack[idx:]
                    break
    for _t, s_pos, dx, dy in stack:
        if dx or dy:
            spans.append((s_pos, len(raw), dx, dy))
    return spans


def _cumulative_offset_at(pos: int, spans: list[tuple[int, int, int, int]]) -> tuple[int, int]:
    """Sum offsets of all enclosing ancestor containers at byte offset `pos` (strictly enclosing)."""
    tx, ty = 0, 0
    for s0, s1, dx, dy in spans:
        if s0 < pos < s1:
            tx += dx
            ty += dy
    return tx, ty


def _svg_offsets(raw: str) -> list[tuple[int, int, int, int]]:
    """Backward-compatible wrapper returning positioned <svg> spans."""
    id_offsets = _style_id_offsets(raw)
    ranges: list[tuple[int, int, int, int]] = []
    for sm in re.finditer(r"<svg\b([^>]*)>(.*?)</svg>", raw, re.S | re.I):
        ox, oy = _attrs_offset(sm.group(1), id_offsets)
        if ox or oy:
            ranges.append((sm.start(), sm.end(), ox, oy))
    return ranges


def _check_safe_zones(files: list[Path], geo: dict, errors: list[dict]) -> None:
    cw, ch = int(geo["width"]), int(geo["height"])
    person = geo["person"]
    caption = geo["caption"]
    stage_w = int((geo.get("stage") or {}).get("w") or cw)
    dark_fills = {"#000", "#000000", "#050505", "#050607", "#090b10", "#0b0d12", "#11131a", "black"}

    for path in files:
        if path.suffix.lower() not in {".html", ".htm", ".svg"}:
            continue
        raw = _strip_comments(path.read_text(encoding="utf-8", errors="ignore"), path.suffix.lower())
        exempt_spans = _role_spans(raw)
        ancestor_spans = _ancestor_offset_spans(raw)
        for m in re.finditer(r"<(rect|circle|image|text|div|section|g)\b([^>]*)>", raw, re.I):
            tag = m.group(1).lower()
            attrs = m.group(2)
            low_attrs = attrs.lower()
            if _in_spans(m.start(), exempt_spans) or any(
                k in low_attrs
                for k in (
                    'data-role="caption"',
                    "data-role='caption'",
                    'data-role="person"',
                    "data-role='person'",
                    'data-role="background"',
                    "data-role='background'",
                    "caption",
                    "subtitle",
                    "person-slot",
                    'id="root"',
                )
            ):
                continue
            ox, oy = _cumulative_offset_at(m.start(), ancestor_spans)
            box: dict[str, int] | None = None
            if tag in ("rect", "image"):
                x = _num_attr(attrs, "x")
                y = _num_attr(attrs, "y")
                w = _num_attr(attrs, "width")
                h = _num_attr(attrs, "height")
                if None not in (x, y, w, h) and w > 0 and h > 0:
                    fill_m = re.search(r'\bfill\s*=\s*["\']([^"\']+)["\']', attrs, re.I)
                    fill_val = fill_m.group(1).strip().lower() if fill_m else ""
                    if w >= cw * 0.95 and h >= ch * 0.95:
                        continue
                    if tag == "rect" and fill_val in dark_fills and w >= stage_w * 0.95 and h >= ch * 0.95:
                        continue
                    box = {"x": int(round(x)) + ox, "y": int(round(y)) + oy, "w": int(round(w)), "h": int(round(h))}
            elif tag == "circle":
                cx = _num_attr(attrs, "cx")
                cy = _num_attr(attrs, "cy")
                r = _num_attr(attrs, "r")
                if None not in (cx, cy, r) and r > 0:
                    box = {"x": int(round(cx - r)) + ox, "y": int(round(cy - r)) + oy,
                           "w": int(round(2 * r)), "h": int(round(2 * r))}
            elif tag == "text":
                x = _num_attr(attrs, "x")
                y = _num_attr(attrs, "y")
                if x is not None and y is not None:
                    fs = _num_attr(attrs, "font-size") or 40.0
                    box = {"x": max(0, int(round(x - 4)) + ox), "y": max(0, int(round(y - fs)) + oy),
                           "w": 20, "h": max(8, int(round(fs)))}
            else:
                st_m = re.search(r'\bstyle\s*=\s*(?:"([^"]*)"|\'([^\']*)\')', attrs, re.I)
                if st_m:
                    st = st_m.group(1) if st_m.group(1) is not None else st_m.group(2)
                    lm = re.search(r"\bleft\s*:\s*(-?[\d.]+)px", st)
                    tm = re.search(r"\btop\s*:\s*(-?[\d.]+)px", st)
                    wm = re.search(r"\bwidth\s*:\s*([\d.]+)px", st)
                    hm = re.search(r"\bheight\s*:\s*([\d.]+)px", st)
                    if lm and tm and wm and hm:
                        w, h = float(wm.group(1)), float(hm.group(1))
                        if w >= cw * 0.95 and h >= ch * 0.95:
                            continue
                        box = {"x": int(round(float(lm.group(1)))) + ox, "y": int(round(float(tm.group(1)))) + oy,
                               "w": int(round(w)), "h": int(round(h))}
            if box is None:
                continue
            ident_m = re.search(r'\bid\s*=\s*["\']([^"\']+)["\']', attrs)
            ident = f"<{tag}" + (f"#{ident_m.group(1)}" if ident_m else "") + ">"
            if person["w"] > 0 and box_intersects(box, person):
                errors.append({"rule": "Q3_SAFEZONE", "file": str(path),
                               "detail": f"{path.name} {ident} ({box}) 侵入人物区 personSlot {person}"})
            if caption["h"] > 0 and box_intersects(box, caption):
                errors.append({"rule": "Q3_SAFEZONE", "file": str(path),
                               "detail": f"{path.name} {ident} ({box}) 侵入字幕区 captionSafe {caption}"})


_SAFE_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}
_SAFE_UNARY_OPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def _eval_num_expr(expr: str, env: dict[str, float]) -> float | None:
    expr = expr.strip()
    if not expr:
        return None
    norm = expr.replace("canvas.width", "__CW__").replace("canvas.height", "__CH__")
    try:
        tree = ast.parse(norm, mode="eval")
    except SyntaxError:
        return None

    def _eval(node: ast.AST) -> float | None:
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return float(node.value)
        if isinstance(node, ast.Name):
            return env.get(node.id)
        if isinstance(node, ast.UnaryOp) and type(node.op) in _SAFE_UNARY_OPS:
            val = _eval(node.operand)
            return _SAFE_UNARY_OPS[type(node.op)](val) if val is not None else None
        if isinstance(node, ast.BinOp) and type(node.op) in _SAFE_BIN_OPS:
            left, right = _eval(node.left), _eval(node.right)
            if left is None or right is None:
                return None
            if isinstance(node.op, ast.Div) and abs(right) < 1e-12:
                return None
            return float(_SAFE_BIN_OPS[type(node.op)](left, right))
        return None

    return _eval(tree)


def _estimate_text_width(text: str, font_px: float) -> float:
    return sum(font_px * (0.85 if ord(ch) > 127 else 0.50) for ch in text)


def _span_for_align(x: float, width: float, align: str) -> tuple[float, float]:
    a = align.lower()
    if a in ("end", "right"):
        return x - width, x
    if a in ("middle", "center"):
        return x - width / 2.0, x + width / 2.0
    return x, x + width


def _balanced_parens(text: str, open_idx: int) -> tuple[str, int] | None:
    depth = 1
    i = open_idx + 1
    in_quote: str | None = None
    while i < len(text) and depth > 0:
        ch = text[i]
        if in_quote is not None:
            if ch == "\\" and i + 1 < len(text):
                i += 2
                continue
            if ch == in_quote:
                in_quote = None
        else:
            if ch in ('"', "'", "`"):
                in_quote = ch
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
        i += 1
    return (text[open_idx + 1:i - 1], i) if depth == 0 else None


def _split_js_args(args_str: str) -> list[str]:
    out: list[str] = []
    depth = 0
    in_quote: str | None = None
    start = 0
    i = 0
    while i < len(args_str):
        ch = args_str[i]
        if in_quote is not None:
            if ch == "\\" and i + 1 < len(args_str):
                i += 2
                continue
            if ch == in_quote:
                in_quote = None
        else:
            if ch in ('"', "'", "`"):
                in_quote = ch
            elif ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth = max(0, depth - 1)
            elif ch == "," and depth == 0:
                part = args_str[start:i].strip()
                if part:
                    out.append(part)
                start = i + 1
        i += 1
    tail = args_str[start:].strip()
    if tail:
        out.append(tail)
    return out


def _unquote_js_string(expr: str) -> str | None:
    m = re.match(r'^("(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\')$', expr.strip())
    if not m:
        return None
    try:
        return str(ast.literal_eval(m.group(1)))
    except Exception:
        return m.group(1)[1:-1]


def _svg_scales(raw: str) -> list[tuple[int, int, float, float]]:
    """Return [(span_start, span_end, sx, sy), ...] from <svg viewBox width height>."""
    out: list[tuple[int, int, float, float]] = []
    for sm in re.finditer(r"<svg\b([^>]*)>(.*?)</svg>", raw, re.S | re.I):
        attrs = sm.group(1)
        vb_m = re.search(r'\bviewBox\s*=\s*["\']\s*[-.\d]+\s+[-.\d]+\s+([\d.]+)\s+([\d.]+)\s*["\']', attrs, re.I)
        w = _num_attr(attrs, "width")
        h = _num_attr(attrs, "height")
        if vb_m and w and h:
            vb_w, vb_h = float(vb_m.group(1)), float(vb_m.group(2))
            if vb_w > 0 and vb_h > 0:
                out.append((sm.start(), sm.end(), w / vb_w, h / vb_h))
    return out


def _check_anchor_label_bounds(files: list[Path], geo: dict, errors: list[dict]) -> None:
    """Catch SVG <text> and Canvas fillText/strokeText/drawLeader coordinates outside canvas bounds."""
    cw, ch = float(geo["width"]), float(geo["height"])

    # 1) SVG <text> anchor coordinates + horizontal text extent
    for path in files:
        suf = path.suffix.lower()
        if suf not in {".html", ".htm", ".svg"}:
            continue
        raw = _strip_comments(path.read_text(encoding="utf-8", errors="ignore"), suf)
        exempt_spans = _role_spans(raw)
        ancestor_spans = _ancestor_offset_spans(raw)
        svg_scales = _svg_scales(raw)
        for m in re.finditer(r"<text\b([^>]*)>(.*?)</text>|<text\b([^>]*)/>", raw, re.S | re.I):
            attrs = m.group(1) if m.group(1) is not None else (m.group(3) or "")
            inner = m.group(2) or ""
            if _in_spans(m.start(), exempt_spans) or _is_exempt_text_context(attrs):
                continue
            x = _num_attr(attrs, "x")
            y = _num_attr(attrs, "y")
            if x is None or y is None:
                continue
            ax, ay = _cumulative_offset_at(m.start(), ancestor_spans)
            ox, oy = float(ax), float(ay)
            sx, sy = 1.0, 1.0
            for s0, s1, rx, ry in svg_scales:
                if s0 <= m.start() < s1:
                    sx, sy = rx, ry
                    break
            gx, gy = x * sx + ox, y * sy + oy
            label_text = re.sub(r"<[^>]+>", "", inner).strip()
            if gx < -1.0 or gx > cw + 1.0 or gy < -1.0 or gy > ch + 1.0:
                errors.append({
                    "rule": "Q3_ANCHOR_BOUNDS",
                    "file": str(path),
                    "detail": f"{path.name} <text x={gx:.0f} y={gy:.0f}> 坐标超出画布安全边界 [0..{int(cw)}, 0..{int(ch)}]",
                })
                continue
            if label_text:
                fs = _num_attr(attrs, "font-size")
                if fs is None:
                    stm = re.search(r"\bfont-size\s*:\s*([\d.]+)\s*px", attrs, re.I)
                    fs = float(stm.group(1)) if stm else 36.0
                anchor_m = re.search(r'\btext-anchor\s*[:=]\s*["\']?(start|middle|end)\b', attrs, re.I)
                anchor = anchor_m.group(1).lower() if anchor_m else "start"
                left_x, right_x = _span_for_align(gx, _estimate_text_width(label_text, fs * sx), anchor)
                if left_x < -1.0 or right_x > cw + 1.0:
                    errors.append({
                        "rule": "Q3_ANCHOR_BOUNDS",
                        "file": str(path),
                        "detail": (
                            f"{path.name} <text x={gx:.0f} y={gy:.0f} text-anchor={anchor}> "
                            f"标签 \"{label_text[:16]}\" 水平范围 [{left_x:.0f}..{right_x:.0f}] 越出画布宽 [0..{int(cw)}]"
                        ),
                    })

    # 2) Canvas / JS fillText, strokeText, and drawLeader calls
    for path in files:
        suf = path.suffix.lower()
        if suf not in CODE_SUFFIXES:
            continue
        raw_text = path.read_text(encoding="utf-8", errors="ignore")
        js_blocks: list[str] = []
        if suf in {".js", ".mjs"}:
            js_blocks.append(_strip_comments(raw_text, suf))
        else:
            for sm in re.finditer(r"<script\b([^>]*)>(.*?)</script\s*>", raw_text, re.S | re.I):
                s_attrs = sm.group(1)
                if re.search(r"\bsrc\s*=", s_attrs, re.I):
                    continue
                tm = re.search(r'\btype\s*=\s*["\']([^"\']+)["\']', s_attrs, re.I)
                stype = (tm.group(1).strip().lower() if tm else "")
                if stype and stype not in {"text/javascript", "application/javascript", "module"}:
                    continue
                js_blocks.append(_strip_comments(sm.group(2), ".js"))

        for code in js_blocks:
            env: dict[str, float] = {"__CW__": cw, "__CH__": ch}
            for cm in re.finditer(r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*([^;\n]+);", code):
                val = _eval_num_expr(cm.group(2), env)
                if val is not None:
                    env[cm.group(1)] = val

            def _preceding_canvas_state(pos: int) -> tuple[str, float]:
                ctx_win = code[max(0, pos - 500):pos]
                aligns = re.findall(r"\btextAlign\s*=\s*[\"'](left|right|center|start|end)[\"']", ctx_win)
                fonts = re.findall(r"\bfont\s*=\s*[\"'][^\"']*?(\d+(?:\.\d+)?)\s*px", ctx_win)
                return (aligns[-1].lower() if aligns else "start", float(fonts[-1]) if fonts else 32.0)

            for fm in re.finditer(r"\.\s*(?:fillText|strokeText)\s*\(", code):
                parsed = _balanced_parens(code, fm.end() - 1)
                if not parsed:
                    continue
                args = _split_js_args(parsed[0])
                if len(args) < 3:
                    continue
                x = _eval_num_expr(args[1], env)
                y = _eval_num_expr(args[2], env)
                if x is None or y is None:
                    continue
                align, font_px = _preceding_canvas_state(fm.start())
                if x < -1.0 or x > cw + 1.0 or y < -1.0 or y > ch + 1.0:
                    errors.append({
                        "rule": "Q3_ANCHOR_BOUNDS",
                        "file": str(path),
                        "detail": f"{path.name} fillText(..., {x:.0f}, {y:.0f}) 坐标超出画布 [0..{int(cw)}, 0..{int(ch)}]",
                    })
                    continue
                label = _unquote_js_string(args[0])
                if label:
                    lx0, lx1 = _span_for_align(x, _estimate_text_width(label, font_px), align)
                    if lx0 < -1.0 or lx1 > cw + 1.0:
                        errors.append({
                            "rule": "Q3_ANCHOR_BOUNDS",
                            "file": str(path),
                            "detail": (
                                f"{path.name} fillText(\"{label[:16]}\", {x:.0f}, {y:.0f}) "
                                f"[{lx0:.0f}..{lx1:.0f}] 越出画布宽 [0..{int(cw)}]"
                            ),
                        })

            for dm in re.finditer(r"(?<!function\s)\bdrawLeader\s*\(", code):
                parsed = _balanced_parens(code, dm.end() - 1)
                if not parsed:
                    continue
                args = _split_js_args(parsed[0])
                align, font_px = _preceding_canvas_state(dm.start())
                obj_arg = next((a for a in args if a.startswith("{") and a.endswith("}")), None)
                if obj_arg is not None:
                    x_vals: list[tuple[str, float]] = []
                    y_vals: list[tuple[str, float]] = []
                    for key in ("x", "x1", "x2", "ax", "lx", "tx", "labelX", "targetX"):
                        km = re.search(rf"\b{key}\s*:\s*([^,}}]+)", obj_arg)
                        if km:
                            v = _eval_num_expr(km.group(1), env)
                            if v is not None:
                                x_vals.append((key, v))
                    for key in ("y", "y1", "y2", "ay", "ly", "ty", "labelY", "targetY"):
                        km = re.search(rf"\b{key}\s*:\s*([^,}}]+)", obj_arg)
                        if km:
                            v = _eval_num_expr(km.group(1), env)
                            if v is not None:
                                y_vals.append((key, v))
                    for key, xv in x_vals:
                        if xv < -1.0 or xv > cw + 1.0:
                            errors.append({
                                "rule": "Q3_ANCHOR_BOUNDS",
                                "file": str(path),
                                "detail": f"{path.name} drawLeader({key}={xv:.0f}) X 坐标超出画布 [0..{int(cw)}]",
                            })
                    for key, yv in y_vals:
                        if yv < -1.0 or yv > ch + 1.0:
                            errors.append({
                                "rule": "Q3_ANCHOR_BOUNDS",
                                "file": str(path),
                                "detail": f"{path.name} drawLeader({key}={yv:.0f}) Y 坐标超出画布 [0..{int(ch)}]",
                            })
                    lm = re.search(r'\b(?:label|text)\s*:\s*("(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\')', obj_arg)
                    am = re.search(r'\b(?:align|textAlign)\s*:\s*["\'](left|right|center|start|end)["\']', obj_arg)
                    if lm and x_vals:
                        lbl = _unquote_js_string(lm.group(1)) or ""
                        lbl_align = am.group(1).lower() if am else align
                        anchor_x = next(
                            (v for k, v in x_vals if k in ("lx", "labelX", "tx", "x2")),
                            x_vals[-1][1],
                        )
                        if 0.0 <= anchor_x <= cw and lbl:
                            lx0, lx1 = _span_for_align(anchor_x, _estimate_text_width(lbl, font_px), lbl_align)
                            if lx0 < -1.0 or lx1 > cw + 1.0:
                                errors.append({
                                    "rule": "Q3_ANCHOR_BOUNDS",
                                    "file": str(path),
                                    "detail": f"{path.name} drawLeader 标签 \"{lbl[:16]}\" [{lx0:.0f}..{lx1:.0f}] 越出画布宽 [0..{int(cw)}]",
                                })
                    continue

                # Positional drawLeader(ctx?, x1, y1, x2?, y2?, label?, align?)
                nums: list[float] = []
                labels: list[str] = []
                arg_align = align
                for a in args:
                    s = _unquote_js_string(a)
                    if s is not None:
                        if s.lower() in ("left", "right", "center", "start", "end"):
                            arg_align = s.lower()
                        elif s.strip():
                            labels.append(s)
                    else:
                        v = _eval_num_expr(a, env)
                        if v is not None:
                            nums.append(v)
                pairs = [(nums[i], nums[i + 1]) for i in range(0, len(nums) - 1, 2)]
                oob = False
                for px, py in pairs:
                    if px < -1.0 or px > cw + 1.0 or py < -1.0 or py > ch + 1.0:
                        errors.append({
                            "rule": "Q3_ANCHOR_BOUNDS",
                            "file": str(path),
                            "detail": f"{path.name} drawLeader(..., {px:.0f}, {py:.0f}) 坐标超出画布 [0..{int(cw)}, 0..{int(ch)}]",
                        })
                        oob = True
                if not oob and pairs and labels:
                    lx = pairs[-1][0]
                    lbl = labels[0]
                    lx0, lx1 = _span_for_align(lx, _estimate_text_width(lbl, font_px), arg_align)
                    if lx0 < -1.0 or lx1 > cw + 1.0:
                        errors.append({
                            "rule": "Q3_ANCHOR_BOUNDS",
                            "file": str(path),
                            "detail": f"{path.name} drawLeader 标签 \"{lbl[:16]}\" [{lx0:.0f}..{lx1:.0f}] 越出画布宽 [0..{int(cw)}]",
                        })


def _check_axis_filters(files: list[Path], errors: list[dict]) -> None:
    filters: dict[str, bool] = {}
    for path in files:
        if path.suffix.lower() not in {".html", ".htm", ".svg"}:
            continue
        raw = _strip_comments(path.read_text(encoding="utf-8", errors="ignore"), path.suffix.lower())
        for m in re.finditer(r"<filter\b([^>]*)>", raw, re.I):
            attrs = m.group(1)
            idm = re.search(r'\bid\s*=\s*["\']([^"\']+)["\']', attrs)
            if idm:
                filters[idm.group(1)] = bool(re.search(r'\bfilterUnits\s*=\s*["\']userSpaceOnUse["\']', attrs, re.I))

    for path in files:
        if path.suffix.lower() not in {".html", ".htm", ".svg"}:
            continue
        raw = _strip_comments(path.read_text(encoding="utf-8", errors="ignore"), path.suffix.lower())
        for m in re.finditer(r"<(line|path)\b([^>]*)>", raw, re.I):
            tag, attrs = m.group(1).lower(), m.group(2)
            f_m = re.search(r"\bfilter\s*(?:=|:)\s*(?:[\"'][^\"']*?)?url\(\s*#([^)\s'\"]+)\s*\)", attrs, re.I)
            if not f_m:
                continue
            fid = f_m.group(1)
            if filters.get(fid, False):
                continue
            axis_aligned = False
            if tag == "line":
                x1, y1 = _num_attr(attrs, "x1"), _num_attr(attrs, "y1")
                x2, y2 = _num_attr(attrs, "x2"), _num_attr(attrs, "y2")
                if None not in (x1, y1, x2, y2) and (abs(x1 - x2) < 1e-3 or abs(y1 - y2) < 1e-3):
                    axis_aligned = True
            else:
                dm = re.search(r'\bd\s*=\s*["\']([^"\']+)["\']', attrs)
                if dm:
                    d = dm.group(1).strip()
                    if re.match(r"^M\s*-?[\d.]+\s*[, ]\s*-?[\d.]+\s*[HhVv]\s*-?[\d.]+\s*$", d):
                        axis_aligned = True
                    else:
                        lm = re.match(r"^M\s*(-?[\d.]+)\s*[, ]\s*(-?[\d.]+)\s*[Ll]\s*(-?[\d.]+)\s*[, ]\s*(-?[\d.]+)\s*$", d)
                        if lm:
                            x1, y1, x2, y2 = (float(lm.group(i)) for i in range(1, 5))
                            if abs(x1 - x2) < 1e-3 or abs(y1 - y2) < 1e-3:
                                axis_aligned = True
            if axis_aligned:
                errors.append({
                    "rule": "Q4_AXIS_FILTER",
                    "file": str(path),
                    "detail": f"{path.name} <{tag}> 挂滤镜 url(#{fid}) 缺 filterUnits=\"userSpaceOnUse\"（横竖线零宽/高 bbox 会被裁隐身）",
                })


def _check_fonts(files: list[Path], errors: list[dict]) -> None:
    registered: set[str] = set()
    for path in files:
        suf = path.suffix.lower()
        if suf not in TEXT_SUFFIXES:
            continue
        raw = _strip_comments(path.read_text(encoding="utf-8", errors="ignore"), suf)
        for m in re.finditer(r"@font-face\s*\{([^}]*)\}", raw, re.I | re.S):
            block = m.group(1)
            fm = re.search(r"font-family\s*:\s*([^;]+)", block, re.I)
            if fm:
                fam = fm.group(1).strip().strip("\"'").lower()
                if fam:
                    registered.add(fam)
            for um in re.finditer(r"url\(\s*(['\"]?)([^)'\"]+)\1\s*\)", block, re.I):
                u = um.group(2).strip()
                if u and not u.startswith(("data:", "http://", "https://", "/")):
                    if not (path.parent / u).is_file():
                        errors.append({"rule": "Q5_FONT_MISSING_FILE", "file": str(path),
                                       "detail": f"{path.name} @font-face 引用缺失字体文件：{u}"})

    for path in files:
        suf = path.suffix.lower()
        if suf not in TEXT_SUFFIXES:
            continue
        raw = _strip_comments(path.read_text(encoding="utf-8", errors="ignore"), suf)
        stripped_ff = re.sub(r"@font-face\s*\{[^}]*\}", "", raw, flags=re.I | re.S)
        stacks: list[str] = []
        stacks.extend(m.group(1) for m in re.finditer(r"font-family\s*:\s*([^;}{]+)", stripped_ff, re.I))
        stacks.extend(m.group(1) for m in re.finditer(r'\bfont-family\s*=\s*(?:"([^"]*)"|\'([^\']*)\')', stripped_ff, re.I) if m.group(1) or m.group(2))
        for raw_stack in stacks:
            for item in raw_stack.split(","):
                name = item.strip().strip("\"'")
                if not name or name.startswith("var("):
                    continue
                low = name.lower()
                if low not in SYSTEM_AND_GENERIC_FONTS and low not in registered:
                    errors.append({
                        "rule": "Q5_UNREGISTERED_FONT",
                        "file": str(path),
                        "detail": f"{path.name} 引用未注册外部/本地字体 '{name}'（缺 @font-face 声明，渲染期可能卡死）",
                    })


def _check_cross_chapter_cleanup(files: list[Path], comp_dir: Path, errors: list[dict]) -> None:
    roots: list[tuple[str, str]] = []
    idx_html = comp_dir / "index.html"
    if not idx_html.is_file():
        return
    html_text = _strip_comments(idx_html.read_text(encoding="utf-8", errors="ignore"), ".html")
    for m in re.finditer(r"<([a-zA-Z][\w:-]*)\b([^>]*)>", html_text):
        attrs = m.group(2)
        if re.search(r'\bclass\s*=\s*["\'][^"\']*\bclip\b', attrs) and "data-duration" in attrs:
            continue
        idm = re.search(r'\bid\s*=\s*["\'](ch\d+[^"\']*|chapter-\d+[^"\']*|scene-\d+[^"\']*)["\']', attrs, re.I)
        dcm = re.search(r'\bdata-chapter\s*=\s*["\']([^"\']+)["\']', attrs, re.I)
        if idm:
            roots.append((idm.group(1), idm.group(1)))
        elif dcm:
            roots.append((dcm.group(1), dcm.group(1)))

    if len(roots) < 2:
        return
    code_blob = "\n".join(
        _strip_comments(p.read_text(encoding="utf-8", errors="ignore"), p.suffix.lower())
        for p in files if p.suffix.lower() in (CODE_SUFFIXES | TEXT_SUFFIXES)
    )
    hide_pat = r"(?:opacity\s*:\s*0\b|autoAlpha\s*:\s*0\b|display\s*:\s*['\"]none['\"]|visibility\s*:\s*['\"]hidden['\"]|classList\.add)"
    zero_helper_pat = r"\b(?:lo|go|fade)\s*\([^)]*,\s*0(?:\s*,|\s*\))"

    def _g_children_cleared(cid: str) -> bool:
        start_m = re.search(rf"<g\b[^>]*\bid\s*=\s*[\"']{re.escape(cid)}[\"'][^>]*>", html_text, re.I)
        if not start_m:
            return False
        depth = 1
        pos = start_m.end()
        top_child_ids: list[str] = []
        for tm in re.finditer(r"<(/?)([a-zA-Z][\w:-]*)\b([^>]*)>", html_text[pos:]):
            closing, tag_n, t_attrs = tm.group(1), tm.group(2).lower(), tm.group(3)
            self_close = t_attrs.rstrip().endswith("/")
            if depth == 1 and not closing:
                im = re.search(r'\bid\s*=\s*["\']([^"\']+)["\']', t_attrs)
                if im:
                    top_child_ids.append(im.group(1))
            if not closing and not self_close:
                depth += 1
            elif closing:
                depth -= 1
                if depth == 0:
                    break
        if not top_child_ids:
            return False
        return all(
            re.search(rf"#{re.escape(ch_id)}[^;\n]{{0,160}}(?:{hide_pat}|\b0\b)", code_blob, re.S)
            or re.search(rf"\b(?:lo|go)\s*\([^)]*#{re.escape(ch_id)}[^)]*,\s*0\b", code_blob)
            for ch_id in top_child_ids
        ) and bool(re.search(zero_helper_pat, code_blob))

    for cid, _ in roots[:-1]:
        escaped = re.escape(cid)
        if re.search(rf"(?:#|\.|data-chapter=[\"']){escaped}.{{0,240}}{hide_pat}", code_blob, re.S):
            continue
        if re.search(rf"{escaped}[^;\n]{{0,120}}{hide_pat}", code_blob, re.S):
            continue
        if _g_children_cleared(cid):
            continue
        errors.append({
            "rule": "Q6_CHAPTER_RESIDUAL",
            "id": cid,
            "detail": f"章节根节点 '{cid}' 在切章后未见归零/隐藏退场控制（存在跨章叠影残留风险）",
        })


MOTION_SHOT_KINDS = ("motion", "model", "card-deck", "xhs")
DEMO_SHOT_KINDS = ("screen-demo", "demo-footage")


def _load_plan_or_storyboard(project: Path) -> dict | None:
    """Load `storyboard.json` (preferred) or legacy `visual-plan.json` into normalized segments."""
    for rel in ("storyboard.json", "edit/storyboard.json"):
        sb_path = project / rel
        if not sb_path.is_file():
            continue
        try:
            sb = json.loads(sb_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            sb = None
        if isinstance(sb, dict):
            segs = []
            for idx, shot in enumerate(sb.get("shots") or []):
                if not isinstance(shot, dict):
                    continue
                kind = str(shot.get("kind") or "talk-only")
                if kind in DEMO_SHOT_KINDS:
                    tier = "demo-footage"
                elif kind in MOTION_SHOT_KINDS or shot.get("engine") in ("remotion", "hyperframes"):
                    tier = "logic-diagram"
                else:
                    tier = "talk-only"
                demo = shot.get("demo")
                if tier == "demo-footage" and not isinstance(demo, dict):
                    raw_src = shot.get("clip") or shot.get("source") or shot.get("material")
                    if raw_src:
                        demo = {
                            "source": raw_src,
                            "inSec": shot.get("clipIn") if shot.get("clipIn") is not None else shot.get("inSec", 0.0),
                            "outSec": shot.get("clipOut") if shot.get("clipOut") is not None else shot.get("outSec", 0.0),
                        }
                        if isinstance(shot.get("box"), dict):
                            demo["box"] = shot["box"]
                seg: dict = {
                    "id": str(shot.get("id") or f"shot-{idx + 1}"),
                    "tier": tier,
                    "kind": kind,
                    "startMs": int(round(float(shot.get("startSec", 0.0)) * 1000)),
                    "endMs": int(round(float(shot.get("endSec", 0.0)) * 1000)),
                }
                if isinstance(demo, dict):
                    seg["demo"] = demo
                segs.append(seg)
            return {"version": sb.get("version", "storyboard/3"), "segments": segs}

    plan_path = project / "visual-plan.json"
    if plan_path.is_file():
        try:
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            if isinstance(plan, dict):
                return plan
        except (OSError, json.JSONDecodeError):
            return None
    return None


def run_checks(project: Path, comp_name: str | None = None, max_static_s: float = 8.0) -> dict:
    geo = resolve_project_frame(project)
    plan = _load_plan_or_storyboard(project)
    comp_dir = project / (comp_name or "composition")
    files = _collect_files(comp_dir)

    errors: list[dict] = []
    warnings: list[dict] = []

    if plan:
        _check_demo_segments(project, plan, geo, errors)
    has_motion_tier = (
        not plan
        or any((s.get("tier") or "logic-diagram") not in ("talk-only", "demo-footage")
               for s in (plan.get("segments") or []) if isinstance(s, dict))
    )
    if files:
        if has_motion_tier:
            _check_min_font_size(files, geo, errors)
        _check_static_duration(files, plan, comp_dir, max_static_s, errors, warnings)
        _check_safe_zones(files, geo, errors)
        _check_anchor_label_bounds(files, geo, errors)
        _check_axis_filters(files, errors)
        _check_fonts(files, errors)
        _check_cross_chapter_cleanup(files, comp_dir, errors)

    return {
        "ok": not errors,
        "project": str(project),
        "composition": str(comp_dir),
        "geometry": {"width": geo["width"], "height": geo["height"],
                     "person": geo["person"], "caption": geo["caption"], "stage": geo["stage"]},
        "errors": errors,
        "warnings": warnings,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Unified build-time visual quality gate (Q1-Q6 + demo-footage)")
    ap.add_argument("project", type=Path)
    ap.add_argument("--composition", default=None)
    ap.add_argument("--max-static-s", type=float, default=8.0)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    project = args.project.expanduser().resolve()
    if not project.is_dir():
        print(json.dumps({"ok": False, "error": f"找不到项目目录：{project}"}), file=sys.stderr)
        return 2

    report = run_checks(project, args.composition, max_static_s=args.max_static_s)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        if report["ok"]:
            print(f"✓ 画面质量体检通过（warnings={len(report['warnings'])}）")
        else:
            print(f"✗ 画面质量体检拦截（{len(report['errors'])} 条错误）：")
            for err in report["errors"]:
                print(f"  - [{err['rule']}] {err['detail']}")
        for warn in report["warnings"]:
            print(f"  ! [{warn['rule']}] {warn['detail']}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
