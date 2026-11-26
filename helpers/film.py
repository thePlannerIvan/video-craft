#!/usr/bin/env python3
"""`画面` —— 统一执行分镜（`storyboard.json`）、轻量 Look-Dev 门禁与实机代理工具（兼旧项目兼容）。

统一执行分镜（`storyboard.json`，`version: "storyboard/3"`）
----------------------------------------------------------
- `talk-only`              只看人留白
- `footage` / `video`      实拍/商业视频切片（媒体直切 `ffmpeg-cut`）
- `motion` / `model`       思维模型动效（随口播演化的单一空间模型，`remotion`）
- `card-deck` / `xhs`      3D 卡片组/海报展卷（`remotion`）
- `screen-demo`            实机演示录屏（审阅挂 `proxy`，交付直切高清原录屏）

旧 `visual-plan.json` 与 `pages/` 逐元素拆解仅作历史项目只读兼容。

用法
----
    python3 helpers/film.py init    <project>              # 初始化分拍表
    python3 helpers/film.py verify  <project> [--json]     # 校验 storyboard.json（或旧 visual-plan.json / pages/）
    python3 helpers/film.py summary <project> [--out PATH] # 从 storyboard.json 派生人读分镜概览
    python3 helpers/film.py lookdev <project> [--verify|--approve] # 轻量 Look-Dev 定调门禁
    python3 helpers/film.py proxy   <project> [--json]     # 为实机演示段生成审阅用低码率代理片
    python3 helpers/film.py outline / pages ...            # 旧静态参考页兼容子命令

退出码：0 = 通过；1 = 有缺口（逐条列出）；2 = 前置缺失。
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

_HELPERS_DIR = str(Path(__file__).resolve().parent)
if _HELPERS_DIR not in sys.path:
    sys.path.insert(0, _HELPERS_DIR)

from montage import (  # noqa: E402
    MIN_REUSE_GAP,
    Fail as MontageFail,
    ReuseLedger,
    inventory_files,
    require_inventory,
    same_material,
)

PAGES_REL = "pages"
MAP_NAME = "map.json"
PLAN_NAME = "visual-plan.json"
STORYBOARD_NAME = "storyboard.json"
STORYBOARD_VERSION = "storyboard/3"
VISUAL_TIERS = ("talk-only", "logic-diagram", "theory-board", "demo-footage")
FOOTAGE_KINDS = ("footage", "video")
MOTION_KINDS = ("motion", "model", "card-deck", "xhs")
DEMO_KINDS = ("screen-demo", "demo-footage")
SHOT_KINDS = ("talk-only", *FOOTAGE_KINDS, *MOTION_KINDS, *DEMO_KINDS)
ENGINES = ("ffmpeg-cut", "remotion", "hyperframes")
SOUND_BEDS = ("auto", "on", "off", "mute", "duck")
IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp")
STATIC_REF_SUFFIXES = (".svg", ".png", ".jpg", ".jpeg", ".webp", ".md", ".html")
LOOKDEV_REL = "lookdev"
LOOKDEV_MANIFEST = "lookdev-manifest.json"
LOOKDEV_SAMPLE = "sample-model.json"
LOOKDEV_BRIEF = "lookdev-brief.md"
DEMO_PROXY_REL = "review/demo_proxies"
SVG_NS = "{http://www.w3.org/2000/svg}"

# 原页里这些内容是"版面记号"，不是内容 —— 默认判为删，并写清理由
CHROME_PATTERNS = (
    ("页码", re.compile(r"^\d{1,2}\s*/\s*\d{1,2}$")),
    ("页脚署名", re.compile(r"IVAN|阿祖|@")),
    ("眉标/章节标", re.compile(r"^[0-9A-Z ·/—_\-]{6,}$")),
)
# 拼贴风 (collage) 与线稿风 (line-art) 的结构化档案编号/节点角标（如 [REF-01]、FIG.02、STEP 01）
# 是画面叙事锚点，不应被眉标正则误删
STRUCTURAL_BADGE_RE = re.compile(
    r"^\[?(?:REF|FIG|STEP|NODE|AXIS|ARCHIVE|DOC|EVIDENCE)[-_.\s0-9A-Z]*\]?$",
    re.IGNORECASE,
)
KEEP_MIN_FONT = 30.0        # 字号 ≥ 30 视为关键概念，默认保留
SPLIT_IF_LONG = 24         # 中文长句默认"拆"


def _text_of(node: ET.Element) -> str:
    return (node.text or "").strip()


def _font_size(node: ET.Element) -> float:
    raw = node.get("font-size") or "0"
    try:
        return float(re.sub(r"[^0-9.]", "", raw) or 0)
    except ValueError:
        return 0.0


def _classify(node: ET.Element) -> tuple[str, dict]:
    """返回（类别，几何/排版信息）。"""
    tag = node.tag.replace(SVG_NS, "")
    if tag == "text":
        return "字", {"text": _text_of(node),
                      "font": _font_size(node),
                      "weight": node.get("font-weight") or "",
                      "fill": node.get("fill") or "",
                      "keep": (node.get("data-keep") or "").lower() in ("1", "true", "yes")}
    if tag == "rect":
        w = float(node.get("width") or 0)
        h = float(node.get("height") or 0)
        full = w >= 1800 and h >= 1000
        return ("底" if full else "框"), {"w": w, "h": h,
                                        "fill": node.get("fill") or "",
                                        "stroke": node.get("stroke") or ""}
    if tag == "line":
        # 线的坐标在 x1/y1/x2/y2，不在 x/y 上；不取出来就全落在 (0,0)，
        # 拆解表里分不清哪根线对应哪句口播。
        return "线", {"stroke": node.get("stroke") or "",
                      "x1": float(node.get("x1") or 0), "y1": float(node.get("y1") or 0),
                      "x2": float(node.get("x2") or 0), "y2": float(node.get("y2") or 0)}
    if tag == "circle":
        return "点", {"r": float(node.get("r") or 0), "fill": node.get("fill") or "",
                      "cx": float(node.get("cx") or 0), "cy": float(node.get("cy") or 0)}
    if tag == "image":
        return "图", {}
    return "其他", {}


def _disposition(kind: str, info: dict, keep_chrome: bool = False) -> tuple[str, str]:
    """默认处置 + 理由。人/模型可以改，但必须留下处置这一列。"""
    if kind == "底":
        return "保留", "整页底色，是这一页的纸/暗场"
    if kind == "字":
        text = info.get("text") or ""
        if info.get("keep") or STRUCTURAL_BADGE_RE.match(text):
            return "保留", "结构化档案/节点角标，承载证据编号或轴向标记"
        if not keep_chrome:
            for label, pattern in CHROME_PATTERNS:
                if pattern.search(text):
                    return "删", f"{label}：视频里由进度/署名位承担，留着只会和画面抢位置"
        if info.get("font", 0) >= KEEP_MIN_FONT:
            return "保留", "关键概念字，是这一屏的主张"
        if len(text) >= SPLIT_IF_LONG:
            return "拆", "长句：口播已经在讲，上屏只留其中的关键词"
        return "保留", "短标签，支撑结构"
    if kind in ("框", "线", "点"):
        return "保留", "结构元素，承载这一屏的模型关系"
    if kind == "图":
        return "拆", "原图需要单独确认授权与裁切，默认先不搬"
    return "拆", "无法归类，先不搬"


def extract_elements(svg_path: Path, keep_chrome: bool = False) -> list[dict]:
    tree = ET.parse(svg_path)
    root = tree.getroot()
    out: list[dict] = []
    for node in root.iter():
        kind, info = _classify(node)
        if kind == "其他":
            continue
        text = info.get("text", "")
        if kind == "字" and not text:
            continue
        if kind == "线":
            x = float(node.get("x1") or 0)
            y = float(node.get("y1") or 0)
        elif kind == "点":
            x = float(node.get("cx") or 0)
            y = float(node.get("cy") or 0)
        else:
            x = float(node.get("x") or 0)
            y = float(node.get("y") or 0)
        action, reason = _disposition(kind, info, keep_chrome=keep_chrome)
        out.append({
            "kind": kind, "x": x, "y": y, "info": info,
            "text": text, "action": action, "reason": reason,
        })
    # 阅读顺序：先上后下、先左后右
    out.sort(key=lambda e: (round(e["y"] / 8), e["x"]))
    return out


def _page_key_from(svg_path: Path) -> str:
    return svg_path.stem


def cmd_outline(project: Path, page_key: str, source: Path | None, overwrite: bool = False,
                keep_chrome: bool = False) -> int:
    pages_dir = project / PAGES_REL
    pages_dir.mkdir(parents=True, exist_ok=True)
    target = pages_dir / f"{page_key}.md"
    if target.exists() and not overwrite:
        print(f"○ {target} 已存在（要重写加 --overwrite）")
        return 0
    if source is None:
        print(json.dumps({"ok": False, "error": "缺 --source：原页 SVG 的绝对路径"},
                         ensure_ascii=False, indent=1))
        return 2
    if not source.is_file():
        print(json.dumps({"ok": False, "error": f"原页不存在：{source}"}, ensure_ascii=False, indent=1))
        return 2

    try:
        elements = extract_elements(source, keep_chrome=keep_chrome)
    except ET.ParseError as error:
        print(json.dumps({"ok": False, "error": f"原页不是合法 SVG：{error}"}, ensure_ascii=False, indent=1))
        return 2
    if not elements:
        print(json.dumps({"ok": False, "error": "原页里没抽到元素"}, ensure_ascii=False, indent=1))
        return 2

    try:
        rel = source.resolve().relative_to(project.resolve()).as_posix()
    except ValueError:
        rel = str(source)

    lines: list[str] = []
    lines.append(f"# {page_key} · 原页拆解\n")
    lines.append(f"来源：`{rel}`\n")
    lines.append("> 这份表是**动手前的作业**。每个元素都要有处置（保留 / 删 / 拆）和")
    lines.append("> 它对应的口播（写那半句的关键词即可）。`film.py verify` 会逐条检查。\n")
    lines.append("## 元素清单（按阅读顺序）\n")
    lines.append("| # | 类别 | 位置 | 原页内容 | 处置 | 理由 | 对应口播 |")
    lines.append("|---|---|---|---|---|---|---|")
    for i, el in enumerate(elements, 1):
        info = el["info"]
        where = f"({el['x']:.0f},{el['y']:.0f})"
        if el["kind"] == "框":
            where += f" {info.get('w', 0):.0f}×{info.get('h', 0):.0f}"
        if el["kind"] == "线":
            where = (f"({info.get('x1', 0):.0f},{info.get('y1', 0):.0f})→"
                     f"({info.get('x2', 0):.0f},{info.get('y2', 0):.0f})")
        if el["kind"] == "点":
            where = f"({info.get('cx', 0):.0f},{info.get('cy', 0):.0f}) r{info.get('r', 0):.0f}"
        if el["kind"] == "字":
            where += f" {info.get('font', 0):.0f}px"
        content = el["text"][:28].replace("|", "\\|")
        if el["kind"] != "字":
            content = info.get("fill") or info.get("stroke") or ""
        lines.append(f"| {i} | {el['kind']} | {where} | {content or '—'} | "
                     f"{el['action']} | {el['reason']} |  |")
    lines.append("\n## 这一页要讲的一句话\n")
    lines.append("（一句话。写不出来说明还没读懂原页 —— 回去再读。）\n")
    lines.append("\n## 删掉的东西与理由\n")
    lines.append("（把上面判为「删」「拆」的逐条写明：为什么视频里不需要它。）\n")
    target.write_text("\n".join(lines), encoding="utf-8")
    print(f"✓ 拆解骨架已写：{target}（{len(elements)} 个元素，处置已按启发式预填，口播列待填）")
    return 0


def load_map(project: Path) -> dict:
    path = project / PAGES_REL / MAP_NAME
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def write_map(project: Path, pairs: list[str]) -> int:
    pages_dir = project / PAGES_REL
    pages_dir.mkdir(parents=True, exist_ok=True)
    mapping = load_map(project)
    for pair in pairs:
        if "=" not in pair:
            print(json.dumps({"ok": False, "error": f"映射要写成 beatId=pageKey：{pair}"},
                             ensure_ascii=False, indent=1))
            return 2
        beat, page = pair.split("=", 1)
        mapping[beat.strip()] = page.strip()
    (pages_dir / MAP_NAME).write_text(json.dumps(mapping, ensure_ascii=False, indent=2) + "\n",
                                      encoding="utf-8")
    print(f"✓ 映射已写：{pages_dir / MAP_NAME}（{len(mapping)} 条）")
    return 0


def _beats_of(project: Path) -> list[dict]:
    for rel in ("recompose/lines.json", "edit/lines.json"):
        path = project / rel
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            return data.get("beats") or []
    return []


def _table_rows(md: str) -> list[list[str]]:
    rows = []
    for line in md.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 7 or cells[0] in ("#", "---") or set(cells[0]) <= {"-"}:
            continue
        rows.append(cells)
    return rows


def _seed_segments(project: Path) -> list[dict]:
    """Derive initial visual-plan segments from timeline.json or recompose/lines.json."""
    tl_path = project / "timeline" / "timeline.json"
    if tl_path.is_file():
        try:
            tl = json.loads(tl_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            tl = {}
        chapters = tl.get("chapters") or []
        if chapters:
            segs = []
            cursor = 0
            for idx, ch in enumerate(chapters, 1):
                steps = ch.get("steps") or []
                if steps:
                    st0 = min(int(s.get("startMs", cursor)) for s in steps)
                    st1 = max(int(s.get("startMs", st0)) + int(s.get("durationMs", 3000)) for s in steps)
                else:
                    st0 = int(ch.get("startMs", cursor))
                    dur = int(ch.get("durationMs", 4000))
                    st1 = int(ch.get("endMs", st0 + dur))
                st1 = max(st0 + 1000, st1)
                cursor = st1
                cid = str(ch.get("id") or f"seg-{idx:02d}")
                title = str(ch.get("title") or cid).strip()
                segs.append({
                    "id": f"seg-{idx:02d}",
                    "beatId": cid,
                    "tier": "logic-diagram",
                    "startMs": st0,
                    "endMs": st1,
                    "hero": title,
                    "anchors": [title[:12]],
                })
            if segs:
                return segs
    beats = _beats_of(project)
    if beats:
        segs = []
        cursor = 0
        for idx, b in enumerate(beats, 1):
            bid = str(b.get("id") or f"beat-{idx:02d}")
            title = str(b.get("title") or bid).strip()
            st0 = int(b.get("startMs", cursor))
            st1 = max(st0 + 1000, int(b.get("endMs", st0 + int(b.get("durationMs", 4000)))))
            cursor = st1
            segs.append({
                "id": f"seg-{idx:02d}",
                "beatId": bid,
                "tier": "logic-diagram",
                "startMs": st0,
                "endMs": st1,
                "hero": title,
                "anchors": [title[:12]],
            })
        return segs
    return [{
        "id": "seg-01",
        "beatId": "seg-01",
        "tier": "logic-diagram",
        "startMs": 0,
        "endMs": 5000,
        "hero": "主视觉对象",
        "anchors": ["核心关键词"],
    }]


def _parse_project_yaml_hints(project: Path) -> tuple[str | None, list[str]]:
    """Extract optional `frame` preset and `capabilities` list from `project.yaml` without PyYAML."""
    pyaml = project / "project.yaml"
    if not pyaml.is_file():
        return None, []
    try:
        lines = pyaml.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return None, []
    frame_preset: str | None = None
    caps: list[str] = []
    in_caps = False
    for raw in lines:
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if in_caps:
            if stripped.startswith("- "):
                val = stripped[2:].strip().strip("\"'")
                if val:
                    caps.append(val)
                continue
            if raw.startswith((" ", "\t")):
                continue
            in_caps = False
        m_frame = re.match(r"^(?:frame|framePreset|frame_preset)\s*:\s*(.+)$", stripped)
        if m_frame:
            val = m_frame.group(1).strip().strip("\"'")
            if val and val.lower() not in ("null", "none", "~"):
                frame_preset = val
            continue
        m_caps = re.match(r"^capabilities\s*:\s*(.*)$", stripped)
        if m_caps:
            rest = m_caps.group(1).strip()
            if rest.startswith("[") and rest.endswith("]"):
                for item in rest[1:-1].split(","):
                    v = item.strip().strip("\"'")
                    if v:
                        caps.append(v)
            elif not rest:
                in_caps = True
    return frame_preset, caps


def _resolve_storyboard_frame(project: Path, explicit_preset: str | None = None) -> tuple[dict, str, list[str]]:
    sys.path.insert(0, str(Path(__file__).resolve().parent / "_internal"))
    from _geometry import resolve_project_frame

    geo = resolve_project_frame(project)
    canvas = {"width": int(geo["width"]), "height": int(geo["height"]), "fps": int(geo["fps"])}
    yaml_preset, caps = _parse_project_yaml_hints(project)
    preset = explicit_preset or yaml_preset
    if not preset:
        for rel in ("frame.json", "material/frame/tokens.json", "recompose.json"):
            p = project / rel
            if p.is_file():
                try:
                    d = json.loads(p.read_text(encoding="utf-8"))
                    if isinstance(d, dict) and isinstance(d.get("framePreset"), str) and d["framePreset"].strip():
                        preset = d["framePreset"].strip()
                        break
                except (OSError, json.JSONDecodeError):
                    pass
    if not preset:
        preset = "vertical-zine-head" if canvas["height"] > canvas["width"] else "landscape-16x9"
    return canvas, preset, caps


def _timeline_step_lookup(project: Path) -> dict[str, tuple[int, int]]:
    out: dict[str, tuple[int, int]] = {}
    for rel in ("timeline/timeline.json", "edit/timeline/timeline.json"):
        tp = project / rel
        if not tp.is_file():
            continue
        try:
            tl = json.loads(tp.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for ch in tl.get("chapters") or []:
            for st in ch.get("steps") or []:
                sid = str(st.get("id") or "")
                if not sid:
                    continue
                st0 = int(st.get("startMs", 0))
                st1 = int(st.get("endMs", st0 + int(st.get("durationMs", 4000))))
                out[sid] = (st0, max(st0 + 200, st1))
        break
    return out


def _map_grouping_kind(item: dict, default_kind: str) -> str:
    raw_kind = item.get("kind")
    if isinstance(raw_kind, str) and raw_kind in SHOT_KINDS:
        return raw_kind
    tier = item.get("tier")
    if tier == "talk-only":
        return "talk-only"
    if tier == "demo-footage":
        return "screen-demo"
    if tier in ("logic-diagram", "theory-board"):
        return "motion"
    return default_kind


def _seed_storyboard_shots(project: Path, capabilities: list[str]) -> list[dict]:
    default_kind = "motion" if "motion" in capabilities else "talk-only"
    tl_steps = _timeline_step_lookup(project)
    for rel in ("timeline/grouping.json", "edit/timeline/grouping.json"):
        gp = project / rel
        if not gp.is_file():
            continue
        try:
            gdoc = json.loads(gp.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            gdoc = {}
        chapters = gdoc.get("chapters") or []
        if chapters:
            shots: list[dict] = []
            cursor = 0
            idx = 0
            for ch in chapters:
                ch_id = str(ch.get("id") or "")
                ch_title = str(ch.get("title") or ch_id).strip()
                steps = ch.get("steps") or []
                items = steps if steps else [ch]
                for st in items:
                    idx += 1
                    sid = str(st.get("id") or f"S{idx:02d}").strip()
                    if st.get("startMs") is not None:
                        st0 = int(st["startMs"])
                        st1 = int(st.get("endMs", st0 + int(st.get("durationMs", 4000))))
                    elif sid in tl_steps:
                        st0, st1 = tl_steps[sid]
                    else:
                        st0 = cursor
                        st1 = st0 + int(st.get("durationMs", 4000))
                    st1 = max(st0 + 200, st1)
                    cursor = st1
                    kind = _map_grouping_kind(st, default_kind)
                    engine = st.get("engine") if st.get("engine") in ENGINES else _resolve_shot_engine({"kind": kind}, project=project)
                    shot: dict = {
                        "id": sid,
                        "kind": kind,
                        "engine": engine,
                        "startSec": round(st0 / 1000.0, 3),
                        "endSec": round(st1 / 1000.0, 3),
                    }
                    if ch_title:
                        shot["chapter"] = ch_title
                    title = str(st.get("title") or "").strip()
                    if title:
                        shot["title"] = title
                    shots.append(shot)
            if shots:
                return shots

    shots = []
    for seg in _seed_segments(project):
        kind = _map_grouping_kind(seg, default_kind)
        shot = {
            "id": str(seg.get("id") or "S01"),
            "kind": kind,
            "engine": _resolve_shot_engine({"kind": kind}, project=project),
            "startSec": round(float(seg.get("startMs", 0)) / 1000.0, 3),
            "endSec": round(float(seg.get("endMs", 5000)) / 1000.0, 3),
        }
        if seg.get("hero"):
            shot["title"] = str(seg["hero"])
        shots.append(shot)
    return shots


def cmd_init(
    project: Path,
    overwrite: bool = False,
    as_json: bool = False,
    legacy_visual_plan: bool = False,
    frame_preset: str | None = None,
) -> int:
    if legacy_visual_plan:
        target = project / PLAN_NAME
        if target.exists() and not overwrite:
            if as_json:
                print(json.dumps({"ok": True, "path": str(target), "created": False}, ensure_ascii=False, indent=1))
            else:
                print(f"○ {target} 已存在（重写加 --overwrite）")
            return 0
        doc = {
            "version": 2,
            "reference": {
                "styleNote": "可选：静态参考图仅提取配色、比例与造型",
                "keyframeSvgs": [],
            },
            "segments": _seed_segments(project),
        }
        target.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if as_json:
            print(json.dumps({"ok": True, "path": str(target), "created": True, "segments": len(doc["segments"])},
                             ensure_ascii=False, indent=1))
        else:
            print(f"✓ 视觉分拍表已初始化：{target}（{len(doc['segments'])} 段，无需 pages/ 原页拆解）")
        return 0

    existing = _find_storyboard(project)
    target = existing or (project / STORYBOARD_NAME)
    if existing is not None and not overwrite:
        if as_json:
            print(json.dumps({"ok": True, "path": str(target), "created": False, "mode": STORYBOARD_VERSION},
                             ensure_ascii=False, indent=1))
        else:
            print(f"○ {target} 已存在（重写加 --overwrite）")
        return 0

    canvas, preset, caps = _resolve_storyboard_frame(project, explicit_preset=frame_preset)
    shots = _seed_storyboard_shots(project, caps)
    doc: dict = {
        "version": STORYBOARD_VERSION,
        "canvas": canvas,
        "framePreset": preset,
        "shots": shots,
    }
    if caps:
        doc["capabilities"] = caps
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if as_json:
        print(json.dumps({
            "ok": True,
            "mode": STORYBOARD_VERSION,
            "path": str(target),
            "created": True,
            "framePreset": preset,
            "shots": len(shots),
        }, ensure_ascii=False, indent=1))
    else:
        print(f"✓ 统一执行分镜已初始化：{target}（{len(shots)} 镜，framePreset={preset}）")
    return 0


def _resolve_plan_source(project: Path, raw: str) -> Path:
    p = Path(raw).expanduser()
    return (p if p.is_absolute() else (project / p)).resolve()


def _is_inside_composition_assets(src: Path, project: Path) -> bool:
    comp_assets = (project / "composition" / "assets").resolve()
    return src == comp_assets or src.is_relative_to(comp_assets)


def _generate_demo_proxy(
    project: Path,
    seg_id: str,
    src: Path,
    in_sec: float,
    out_sec: float,
    max_width: int,
    crf: int,
) -> tuple[str | None, str | None]:
    proxy_dir = project / DEMO_PROXY_REL
    safe_id = re.sub(r"[^A-Za-z0-9._-]+", "_", seg_id)
    if _is_inside_composition_assets(src, project):
        return None, f"{seg_id} 原录屏禁止放入 composition/assets/: {src}"
    if not src.is_file():
        return None, f"{seg_id} 找不到原录屏：{src}"
    if in_sec < 0 or out_sec <= in_sec:
        return None, f"{seg_id} 入出点非法：inSec={in_sec}, outSec={out_sec}"
    proxy_dir.mkdir(parents=True, exist_ok=True)
    out_file = proxy_dir / f"{safe_id}.mp4"
    dur = out_sec - in_sec
    with tempfile.NamedTemporaryFile(dir="/tmp", prefix="vc_proxy_", suffix=".mp4", delete=False) as tf:
        tmp_out = Path(tf.name)
    cmd = [
        "ffmpeg", "-y", "-v", "error",
        "-ss", f"{in_sec:.3f}", "-t", f"{dur:.3f}", "-i", str(src),
        "-vf", f"scale='min({int(max_width)},iw)':-2",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", str(int(crf)),
        "-pix_fmt", "yuv420p", "-an", "-movflags", "+faststart",
        str(tmp_out),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0 or not tmp_out.is_file() or tmp_out.stat().st_size == 0:
            return None, f"{seg_id} 生成代理片失败：{proc.stderr[-300:]}"
        shutil.move(str(tmp_out), str(out_file))
    finally:
        if tmp_out.exists():
            tmp_out.unlink(missing_ok=True)
    rel_proxy = os.path.relpath(out_file.resolve(), project.resolve()).replace(os.sep, "/")
    return rel_proxy, None


def cmd_proxy(project: Path, max_width: int = 960, crf: int = 28, as_json: bool = False) -> int:
    sb_path = _find_storyboard(project)
    if sb_path is not None:
        try:
            doc = json.loads(sb_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(json.dumps({"ok": False, "error": f"{STORYBOARD_NAME} 解析失败：{exc}"}, ensure_ascii=False, indent=1))
            return 2
        generated = []
        for idx, shot in enumerate(doc.get("shots") or []):
            if not isinstance(shot, dict) or shot.get("kind") not in DEMO_KINDS:
                continue
            seg_id = str(shot.get("id") or f"demo-{idx + 1:02d}")
            demo = shot.get("demo")
            if isinstance(demo, dict):
                raw_src = demo.get("source")
                raw_in, raw_out = demo.get("inSec", 0.0), demo.get("outSec", 0.0)
            else:
                raw_src = shot.get("clip") or shot.get("source") or shot.get("material")
                raw_in = shot.get("clipIn") if shot.get("clipIn") is not None else shot.get("inSec", 0.0)
                raw_out = shot.get("clipOut") if shot.get("clipOut") is not None else shot.get("outSec", 0.0)
            if not raw_src:
                print(json.dumps({"ok": False, "error": f"{seg_id} 缺少 demo.source"}, ensure_ascii=False, indent=1))
                return 1
            src = _resolve_storyboard_asset(project, sb_path.parent, str(raw_src))
            rel_proxy, err = _generate_demo_proxy(
                project, seg_id, src, float(raw_in or 0.0), float(raw_out or 0.0), max_width, crf
            )
            if err:
                print(json.dumps({"ok": False, "error": err}, ensure_ascii=False, indent=1))
                return 1
            if not isinstance(demo, dict):
                demo = {"source": str(raw_src), "inSec": float(raw_in or 0.0), "outSec": float(raw_out or 0.0)}
                shot["demo"] = demo
            demo["proxy"] = rel_proxy
            generated.append({"id": seg_id, "source": str(src), "proxy": rel_proxy})

        sb_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        result = {"ok": True, "mode": STORYBOARD_VERSION, "count": len(generated), "proxies": generated}
        if as_json:
            print(json.dumps(result, ensure_ascii=False, indent=1))
        else:
            print(f"✓ 已生成 {len(generated)} 个实机演示轻量代理片 → {project / DEMO_PROXY_REL}")
        return 0

    plan_path = project / PLAN_NAME
    if not plan_path.is_file():
        print(json.dumps({"ok": False, "error": f"缺 {STORYBOARD_NAME} / {PLAN_NAME}；先跑 film.py init"}, ensure_ascii=False, indent=1))
        return 2
    try:
        doc = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": f"{PLAN_NAME} 解析失败：{exc}"}, ensure_ascii=False, indent=1))
        return 2

    proxy_dir = project / DEMO_PROXY_REL
    generated = []
    for idx, seg in enumerate(doc.get("segments") or []):
        if seg.get("tier") != "demo-footage":
            continue
        seg_id = str(seg.get("id") or f"demo-{idx + 1:02d}")
        demo = seg.get("demo")
        if not isinstance(demo, dict) or not demo.get("source"):
            print(json.dumps({"ok": False, "error": f"{seg_id} 缺少 demo.source"}, ensure_ascii=False, indent=1))
            return 1
        src = _resolve_plan_source(project, str(demo["source"]))
        rel_proxy, err = _generate_demo_proxy(
            project, seg_id, src, float(demo.get("inSec", 0.0)), float(demo.get("outSec", 0.0)), max_width, crf
        )
        if err:
            print(json.dumps({"ok": False, "error": err}, ensure_ascii=False, indent=1))
            return 1
        demo["proxy"] = rel_proxy
        generated.append({"id": seg_id, "source": str(src), "proxy": rel_proxy})

    plan_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result = {"ok": True, "count": len(generated), "proxies": generated}
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=1))
    else:
        print(f"✓ 已生成 {len(generated)} 个实机演示轻量代理片 → {proxy_dir}")
    return 0


def _verify_visual_plan(project: Path, plan_path: Path, as_json: bool) -> int:
    problems: list[str] = []
    notes: list[str] = []
    try:
        doc = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "mode": "v2-visual-plan", "problems": [f"{PLAN_NAME} 无效：{exc}"]},
                         ensure_ascii=False, indent=1))
        return 1
    if not isinstance(doc, dict):
        problems.append(f"{PLAN_NAME} 顶层必须是 JSON 对象")
        segments = []
    else:
        segments = doc.get("segments")
        if not isinstance(segments, list) or not segments:
            problems.append(f"{PLAN_NAME} 必须包含非空 segments 数组")
            segments = []

    tier_counts: dict[str, int] = {t: 0 for t in VISUAL_TIERS}
    prev_end = 0.0
    for idx, seg in enumerate(segments):
        if not isinstance(seg, dict):
            problems.append(f"segments[{idx}] 必须是对象")
            continue
        sid = str(seg.get("id") or f"segments[{idx}]")
        tier = seg.get("tier")
        if tier not in VISUAL_TIERS:
            problems.append(f"{sid}: 非法视觉档位 {tier!r}（仅允许 {VISUAL_TIERS}）")
            continue
        tier_counts[tier] += 1
        try:
            st0 = float(seg["startMs"])
            st1 = float(seg["endMs"])
        except (KeyError, TypeError, ValueError):
            problems.append(f"{sid}: 缺少合法的 startMs / endMs")
            continue
        if st0 < 0 or st1 <= st0:
            problems.append(f"{sid}: 时间区间非法 ({st0}..{st1})")
        if st0 < prev_end - 1e-6:
            problems.append(f"{sid}: 与上一段重叠 (startMs={st0} < prevEndMs={prev_end})")
        prev_end = max(prev_end, st1)

        if tier == "logic-diagram":
            hero = seg.get("hero")
            anchors = seg.get("anchors")
            if not isinstance(hero, str) or not hero.strip():
                problems.append(f"{sid} (logic-diagram): 缺少 hero 主视觉主角描述")
            if not isinstance(anchors, list) or not (1 <= len(anchors) <= 6) or not all(
                isinstance(a, str) and a.strip() for a in anchors
            ):
                problems.append(f"{sid} (logic-diagram): anchors 必须为 1–6 个简洁核心大字锚点")
        elif tier == "theory-board":
            hero = seg.get("hero")
            anchors = seg.get("anchors")
            if not isinstance(hero, str) or not hero.strip():
                problems.append(f"{sid} (theory-board): 缺少 hero 框架名称")
            if not isinstance(anchors, list) or not anchors or not all(
                isinstance(a, str) and a.strip() for a in anchors
            ):
                problems.append(f"{sid} (theory-board): 缺少非空 anchors 条目列表")
            focus_mode = seg.get("focusMode")
            if focus_mode is not None and focus_mode not in ("spotlight", "active-highlight"):
                problems.append(f"{sid} (theory-board): focusMode 必须为 spotlight/active-highlight（当前讲解项高亮、其余压暗）")
            elif focus_mode is None:
                notes.append(f"{sid} (theory-board): 需确保当前口播条目高亮放大、其余非焦点条目降暗退后")
        elif tier == "demo-footage":
            demo = seg.get("demo")
            if not isinstance(demo, dict):
                problems.append(f"{sid} (demo-footage): 缺少 demo 配置对象")
                continue
            raw_src = demo.get("source")
            if not isinstance(raw_src, str) or not raw_src.strip():
                problems.append(f"{sid} (demo-footage): 缺少 demo.source 原录屏路径")
                continue
            src = _resolve_plan_source(project, raw_src)
            if _is_inside_composition_assets(src, project):
                problems.append(f"{sid} (demo-footage): 原录屏禁止放入 composition/assets/（请用代理或由 deliver 交付直拼）：{raw_src}")
            elif not src.is_file():
                problems.append(f"{sid} (demo-footage): 找不到原录屏文件：{src}")
            try:
                in_sec = float(demo["inSec"])
                out_sec = float(demo["outSec"])
            except (KeyError, TypeError, ValueError):
                problems.append(f"{sid} (demo-footage): 缺少合法的 inSec / outSec")
                continue
            if in_sec < 0 or out_sec <= in_sec:
                problems.append(f"{sid} (demo-footage): demo 入出点非法 ({in_sec}..{out_sec})")
            try:
                speed = float(demo.get("speed", 1.0))
                if speed <= 0:
                    problems.append(f"{sid} (demo-footage): speed 必须大于 0")
            except (TypeError, ValueError):
                problems.append(f"{sid} (demo-footage): speed 必须为正数")

    result = {
        "ok": not problems,
        "mode": "v2-visual-plan",
        "segments": len(segments),
        "tiers": tier_counts,
        "problems": problems,
        "notes": notes,
        "next": ("视觉分拍表校验通过 → 编写或渲染 composition/（demo-footage 预览走 proxy、交付直拼原片）"
                 if not problems else "按 problems 修复 visual-plan.json 后重验"),
    }
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=1))
    else:
        if result["ok"]:
            print(f"✓ 视觉分拍表校验通过（{len(segments)} 段：{tier_counts}）")
        else:
            print(f"✗ 视觉分拍表未通过（{len(problems)} 处）：")
            for item in problems:
                print(f"  - {item}")
    return 0 if result["ok"] else 1


def _find_storyboard(project: Path) -> Path | None:
    for cand in (project / STORYBOARD_NAME, project / "edit" / STORYBOARD_NAME):
        if cand.is_file():
            return cand
    return None


def _project_root(project: Path) -> Path:
    return project.parent if project.name == "edit" else project


def _resolve_storyboard_asset(project: Path, sb_dir: Path, raw: str) -> Path:
    """Resolve clip/image paths relative to project, storyboard dir, or standard media folders."""
    p = Path(str(raw)).expanduser()
    if p.is_absolute():
        return p.resolve()
    root = _project_root(project)
    roots = (
        root,
        sb_dir,
        root / "material",
        root / "material" / "clips",
        root / "materials",
        root / "materials" / "clips",
        root / "素材",
        root / "素材" / "clips",
        root / "assets",
        root / "composition" / "assets",
    )
    for base in roots:
        cand = (base / p).resolve()
        if cand.exists():
            return cand
    return (root / p).resolve()


def _has_remotion_dir(project: Path | None) -> bool:
    if project is None:
        return False
    root = _project_root(project)
    return any((root / "remotion" / "src" / name).is_file() for name in ("Root.tsx", "Root.ts", "Root.jsx", "Root.js"))


def _resolve_shot_engine(shot: dict, project: Path | None = None) -> str:
    raw = shot.get("engine")
    if raw is not None:
        return str(raw)
    if shot.get("kind") in MOTION_KINDS:
        if project is not None and not _has_remotion_dir(project) and (_project_root(project) / "composition" / "index.html").is_file():
            return "hyperframes"
        return "remotion"
    return "ffmpeg-cut"


def _capability_bucket(kind: str) -> str:
    if kind in FOOTAGE_KINDS:
        return "footage"
    if kind in MOTION_KINDS:
        return "motion"
    if kind in DEMO_KINDS:
        return "screen-demo"
    return "talk-only"


def _extract_shot_images(shot: dict, project: Path, sb_dir: Path) -> list[Path]:
    """Collect deduplicated static image/cover/page paths referenced by a single shot."""
    raws: list[str] = []
    for key in ("image", "cover"):
        val = shot.get(key)
        if isinstance(val, str) and val.strip():
            raws.append(val.strip())
    for key in ("covers", "pages"):
        seq = shot.get(key)
        if isinstance(seq, list):
            for entry in seq:
                if isinstance(entry, str) and entry.strip():
                    raws.append(entry.strip())
    items = shot.get("items")
    if isinstance(items, list):
        for entry in items:
            if isinstance(entry, str) and entry.strip():
                raws.append(entry.strip())
            elif isinstance(entry, dict):
                for key in ("file", "path", "src", "image"):
                    val = entry.get(key)
                    if isinstance(val, str) and val.strip():
                        raws.append(val.strip())
                        break
    seen: set[str] = set()
    resolved: list[Path] = []
    for raw in raws:
        p = _resolve_storyboard_asset(project, sb_dir, raw)
        key = str(p)
        if key not in seen:
            seen.add(key)
            resolved.append(p)
    return resolved


def _check_inventory_if_present(
    mat: Path, project: Path, sb_dir: Path, cache: dict, sid: str
) -> str | None:
    """Validate `material-inventory.json` via `montage.py` when an inventory file governs `mat`."""
    root = _project_root(project)
    edit_ctx = root / "edit"
    inv_list = inventory_files(mat, edit_ctx)
    if inv_list:
        try:
            require_inventory(mat, edit_ctx, cache, sid)
        except MontageFail as exc:
            return f"{sid}: {exc}"
        return None

    extra_invs = [
        p
        for p in (sb_dir / "material-inventory.json", root / "material" / "material-inventory.json")
        if p.is_file()
    ]
    if not extra_invs:
        return None

    for inv in extra_invs:
        doc = cache.get(inv)
        if doc is None:
            try:
                doc = json.loads(inv.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                return f"{sid}: 素材清单读不出来：{inv}（{exc}）"
            cache[inv] = doc
        for line, row in enumerate((doc.get("rows") if isinstance(doc, dict) else []) or [], 1):
            if isinstance(row, dict) and same_material(row, inv.parent, mat):
                if not str(row.get("summary") or "").strip():
                    return f"{sid}: 素材清单行没填 summary（{inv.name} 第 {line} 行，{mat.name}）"
                if row.get("usable") is False:
                    return f"{sid}: 素材在清单里标了 usable=false（{inv.name} 第 {line} 行，{mat.name}）"
                return None
    return f"{sid}: 素材没有登记进素材清单：{mat}"


def _format_reuse_reason(sid: str, reason: str, seq_to_id: dict[int, str]) -> str:
    annotated = re.sub(
        r"第 (\d+) 镜",
        lambda m: f"第 {m.group(1)} 镜 ({seq_to_id.get(int(m.group(1)), m.group(1))})",
        reason,
    )
    return f"{sid}: {annotated}"


def _verify_storyboard_footage(
    shot: dict,
    sid: str,
    idx: int,
    project: Path,
    sb_dir: Path,
    ledger: ReuseLedger,
    inv_cache: dict,
    seq_to_id: dict[int, str],
    problems: list[str],
) -> Path | None:
    kind = shot["kind"]
    raw_clip = shot.get("clip") or shot.get("material") or shot.get("source")
    if not isinstance(raw_clip, str) or not raw_clip.strip():
        problems.append(f"{sid} ({kind}): 缺少 clip 素材路径")
        return None
    mat = _resolve_storyboard_asset(project, sb_dir, raw_clip.strip())
    if not mat.is_file():
        problems.append(f"{sid} ({kind}): 找不到素材文件：{mat}")
    else:
        inv_err = _check_inventory_if_present(mat, project, sb_dir, inv_cache, sid)
        if inv_err:
            problems.append(inv_err)
    media_kind = "photo" if (mat.suffix.lower() in IMAGE_SUFFIXES or shot.get("mediaKind") == "photo") else "clip"
    clip_in = 0.0
    if media_kind == "clip":
        raw_in = shot.get("clipIn") if shot.get("clipIn") is not None else shot.get("in")
        if raw_in is None:
            raw_in = shot.get("inSec")
        try:
            clip_in = float(raw_in)
        except (TypeError, ValueError):
            problems.append(f"{sid} ({kind}): 缺少合法的 clipIn 素材入点")
            clip_in = -1.0
        if clip_in < 0:
            problems.append(f"{sid} ({kind}): clipIn={clip_in} 不能为负")
        raw_out = shot.get("clipOut") if shot.get("clipOut") is not None else shot.get("out")
        if raw_out is None:
            raw_out = shot.get("outSec")
        if raw_out is not None:
            try:
                clip_out = float(raw_out)
                if clip_out <= clip_in:
                    problems.append(f"{sid} ({kind}): clipOut={clip_out} 必须大于 clipIn={clip_in}")
            except (TypeError, ValueError):
                problems.append(f"{sid} ({kind}): clipOut 必须为数字")
    if clip_in >= 0:
        reason = ledger.note(mat, media_kind, clip_in, idx)
        if reason:
            problems.append(_format_reuse_reason(sid, reason, seq_to_id))
    return mat if media_kind == "photo" else None


def _verify_storyboard_screen_demo(
    shot: dict, sid: str, project: Path, sb_dir: Path, problems: list[str]
) -> None:
    demo = shot.get("demo")
    if isinstance(demo, dict):
        raw_src = demo.get("source")
        raw_in, raw_out = demo.get("inSec"), demo.get("outSec")
        speed_val = demo.get("speed", 1.0)
    else:
        raw_src = shot.get("clip") or shot.get("source") or shot.get("material")
        raw_in = shot.get("clipIn") if shot.get("clipIn") is not None else shot.get("inSec")
        raw_out = shot.get("clipOut") if shot.get("clipOut") is not None else shot.get("outSec")
        speed_val = shot.get("speed", 1.0)
    if not isinstance(raw_src, str) or not raw_src.strip():
        problems.append(f"{sid} (screen-demo): 缺少原录屏路径")
    else:
        src = _resolve_storyboard_asset(project, sb_dir, raw_src.strip())
        if _is_inside_composition_assets(src, project):
            problems.append(f"{sid} (screen-demo): 原录屏禁止放入 composition/assets/：{raw_src}")
        elif not src.is_file():
            problems.append(f"{sid} (screen-demo): 找不到原录屏文件：{src}")
    try:
        in_sec, out_sec = float(raw_in), float(raw_out)
        if in_sec < 0 or out_sec <= in_sec:
            problems.append(f"{sid} (screen-demo): 入出点非法 ({in_sec}..{out_sec})")
    except (TypeError, ValueError):
        problems.append(f"{sid} (screen-demo): 缺少合法的 inSec / outSec")
    try:
        if float(speed_val) <= 0:
            problems.append(f"{sid} (screen-demo): speed 必须大于 0")
    except (TypeError, ValueError):
        problems.append(f"{sid} (screen-demo): speed 必须为正数")


def _verify_storyboard(project: Path, sb_path: Path, as_json: bool) -> int:
    problems: list[str] = []
    notes: list[str] = []
    sb_dir = sb_path.parent
    try:
        doc = json.loads(sb_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(
            json.dumps(
                {"ok": False, "mode": STORYBOARD_VERSION, "problems": [f"{STORYBOARD_NAME} 无效：{exc}"]},
                ensure_ascii=False,
                indent=1,
            )
        )
        return 1

    if not isinstance(doc, dict):
        problems.append(f"{STORYBOARD_NAME} 顶层必须是 JSON 对象")
        doc = {}
    else:
        if doc.get("version") != STORYBOARD_VERSION:
            problems.append(f"{STORYBOARD_NAME} version 必须为 {STORYBOARD_VERSION!r}，当前为 {doc.get('version')!r}")
        canvas = doc.get("canvas")
        if canvas is not None:
            if not isinstance(canvas, dict) or any(
                not isinstance(canvas.get(k), (int, float)) or float(canvas.get(k)) <= 0
                for k in ("width", "height", "fps")
            ):
                problems.append(f"{STORYBOARD_NAME} canvas 必须包含正数 width / height / fps")
        preset = doc.get("framePreset")
        if preset is not None and (not isinstance(preset, str) or not preset.strip()):
            problems.append(f"{STORYBOARD_NAME} framePreset 必须为非空字符串")

    shots = doc.get("shots") if isinstance(doc, dict) else None
    if not isinstance(shots, list) or not shots:
        problems.append(f"{STORYBOARD_NAME} 必须包含非空 shots 数组")
        shots = []

    try:
        min_gap = MIN_REUSE_GAP if doc.get("minReuseGap") is None else float(doc.get("minReuseGap"))
    except (TypeError, ValueError):
        min_gap = MIN_REUSE_GAP
        problems.append(f"{STORYBOARD_NAME} minReuseGap 必须为数字")

    ledger = ReuseLedger(min_gap)
    inv_cache: dict = {}
    kind_counts: dict[str, int] = {k: 0 for k in SHOT_KINDS}
    engine_counts: dict[str, int] = {e: 0 for e in ENGINES}
    seen_ids: set[str] = set()
    seq_to_id: dict[int, str] = {}
    prev_end = 0.0

    for idx, shot in enumerate(shots, 1):
        if not isinstance(shot, dict):
            problems.append(f"shots[{idx - 1}] 必须是对象")
            continue
        raw_id = shot.get("id")
        if not isinstance(raw_id, str) or not raw_id.strip():
            sid = f"shots[{idx - 1}]"
            problems.append(f"{sid}: 缺少非空字符串 id")
        else:
            sid = raw_id.strip()
            if sid in seen_ids:
                problems.append(f"{sid}: 镜号 id 重复")
            seen_ids.add(sid)
        seq_to_id[idx] = sid

        kind = shot.get("kind")
        if kind not in SHOT_KINDS:
            problems.append(f"{sid}: 非法镜头类型 kind={kind!r}（仅允许 {SHOT_KINDS}）")
            continue
        kind_counts[kind] += 1

        engine_raw = shot.get("engine")
        if engine_raw is not None:
            if engine_raw not in ENGINES:
                problems.append(f"{sid}: 非法渲染引擎 engine={engine_raw!r}（仅允许 {ENGINES}）")
                engine = _resolve_shot_engine(dict(shot, engine=None), project=project)
            else:
                engine = str(engine_raw)
                if kind in MOTION_KINDS and engine == "ffmpeg-cut":
                    problems.append(f"{sid} ({kind}): 动效/模型/卡片镜头不得走 ffmpeg-cut")
        else:
            engine = _resolve_shot_engine(shot, project=project)
        if engine in engine_counts:
            engine_counts[engine] += 1

        try:
            st0 = float(shot["startSec"])
            st1 = float(shot["endSec"])
        except (KeyError, TypeError, ValueError):
            problems.append(f"{sid}: 缺少合法的 startSec / endSec")
            continue
        if st0 < 0 or st1 <= st0:
            problems.append(f"{sid}: 时间区间非法 ({st0}..{st1})")
        if st0 < prev_end - 1e-6:
            problems.append(f"{sid}: 与上一段重叠或倒序 (startSec={st0} < prevEndSec={prev_end})")
        prev_end = max(prev_end, st1)

        sound_bed = shot.get("soundBed")
        if sound_bed is not None:
            if isinstance(sound_bed, str) and sound_bed not in SOUND_BEDS:
                problems.append(f"{sid}: 非法 soundBed={sound_bed!r}（仅允许 {SOUND_BEDS}）")
            elif not isinstance(sound_bed, (bool, str, dict)):
                problems.append(f"{sid}: soundBed 类型非法")

        sound_cues = shot.get("soundCues")
        if sound_cues is not None:
            if not isinstance(sound_cues, list) or not all(isinstance(c, str) and c.strip() for c in sound_cues):
                problems.append(f"{sid}: soundCues 必须为非空字符串数组")

        noted_photo: Path | None = None
        if kind in FOOTAGE_KINDS:
            noted_photo = _verify_storyboard_footage(
                shot, sid, idx, project, sb_dir, ledger, inv_cache, seq_to_id, problems
            )
        elif kind in DEMO_KINDS:
            _verify_storyboard_screen_demo(shot, sid, project, sb_dir, problems)

        for img_path in _extract_shot_images(shot, project, sb_dir):
            if noted_photo is not None and img_path == noted_photo:
                continue
            reason = ledger.note(img_path, "photo", 0.0, idx)
            if reason:
                problems.append(_format_reuse_reason(sid, reason, seq_to_id))
            if img_path.is_file():
                inv_err = _check_inventory_if_present(img_path, project, sb_dir, inv_cache, sid)
                if inv_err:
                    problems.append(inv_err)

    result = {
        "ok": not problems,
        "mode": STORYBOARD_VERSION,
        "path": str(sb_path),
        "shots": len(shots),
        "kinds": {k: v for k, v in kind_counts.items() if v > 0},
        "engines": engine_counts,
        "framePreset": doc.get("framePreset") if isinstance(doc, dict) else None,
        "problems": problems,
        "notes": notes,
        "next": (
            "执行分镜校验通过 → 可按需生成概览（film.py summary）或过 Look-Dev 门禁（film.py lookdev）"
            if not problems
            else "按 problems 修复 storyboard.json 后重验"
        ),
    }
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=1))
    else:
        if result["ok"]:
            print(f"✓ 统一分镜校验通过（{len(shots)} 镜，engines={engine_counts}）")
        else:
            print(f"✗ 统一分镜未通过（{len(problems)} 处）：")
            for item in problems:
                print(f"  - {item}")
    return 0 if result["ok"] else 1


def _compute_storyboard_stats(doc: dict, project: Path | None = None) -> dict:
    shots = doc.get("shots") or []
    buckets = {b: {"count": 0, "sec": 0.0, "pct": 0.0} for b in ("footage", "motion", "screen-demo", "talk-only")}
    engines = {e: {"count": 0, "sec": 0.0, "pct": 0.0} for e in ENGINES}
    total_sec = 0.0
    for s in shots:
        if not isinstance(s, dict):
            continue
        dur = max(0.0, float(s.get("endSec", 0.0)) - float(s.get("startSec", 0.0)))
        total_sec += dur
        b = _capability_bucket(str(s.get("kind") or "talk-only"))
        buckets[b]["count"] += 1
        buckets[b]["sec"] += dur
        eng = _resolve_shot_engine(s, project=project)
        if eng in engines:
            engines[eng]["count"] += 1
            engines[eng]["sec"] += dur
    denom = total_sec if total_sec > 0 else 1.0
    for item in (*buckets.values(), *engines.values()):
        item["sec"] = round(item["sec"], 3)
        item["pct"] = round(item["sec"] * 100.0 / denom, 1)
    return {"totalSec": round(total_sec, 3), "shotCount": len(shots), "buckets": buckets, "engines": engines}


def _describe_shot_target(shot: dict) -> str:
    kind = shot.get("kind")
    if kind in FOOTAGE_KINDS:
        clip = Path(str(shot.get("clip") or shot.get("material") or shot.get("source") or "-")).name
        c_in = shot.get("clipIn") if shot.get("clipIn") is not None else shot.get("in")
        c_out = shot.get("clipOut") if shot.get("clipOut") is not None else shot.get("out")
        span = f" [`{float(c_in):.2f}–{float(c_out):.2f}s`]" if c_in is not None and c_out is not None else (
            f" [`in={float(c_in):.2f}s`]" if c_in is not None else ""
        )
        return f"`{clip}`{span}"
    if kind in DEMO_KINDS:
        demo = shot.get("demo") if isinstance(shot.get("demo"), dict) else {}
        src = Path(str(demo.get("source") or shot.get("clip") or shot.get("source") or "-")).name
        return f"实机录屏 `{src}`"
    parts = [str(shot[k]) for k in ("modelId", "style", "title") if shot.get(k)]
    return " · ".join(parts) if parts else str(kind)


def cmd_summary(project: Path, out: Path | None, as_json: bool) -> int:
    sb_path = _find_storyboard(project)
    if sb_path is None:
        msg = f"找不到 {STORYBOARD_NAME}（已检查项目根与 edit/）"
        print(json.dumps({"ok": False, "error": msg}, ensure_ascii=False, indent=1))
        return 2
    try:
        doc = json.loads(sb_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": f"{STORYBOARD_NAME} 解析失败：{exc}"}, ensure_ascii=False, indent=1))
        return 2

    stats = _compute_storyboard_stats(doc, project=project)
    canvas = doc.get("canvas") or {}
    canvas_str = (
        f"{canvas.get('width', '?')}×{canvas.get('height', '?')} @ {canvas.get('fps', '?')}fps"
        if isinstance(canvas, dict)
        else "未指定"
    )
    title = doc.get("project") or project.name
    lines = [
        f"# 分镜执行概览：{title}",
        "",
        f"- **真源**：`{sb_path.relative_to(project).as_posix() if sb_path.is_relative_to(project) else sb_path}`（`{doc.get('version', STORYBOARD_VERSION)}`）",
        f"- **画框与规格**：`framePreset={doc.get('framePreset') or '未指定'}` · `{canvas_str}`",
    ]
    if doc.get("referenceStyle"):
        lines.append(f"- **风格参考**：{doc['referenceStyle']}")
    lines += [
        f"- **总时长与镜头数**：`{stats['totalSec']:.2f}s` · `{stats['shotCount']}` 镜",
        "",
        "## 能力配比与引擎分布",
        "",
        "| 维度 | 镜数 | 时长 | 占比 |",
        "|---|---|---|---|",
    ]
    labels = {
        "footage": "剪视频（footage / video）",
        "motion": "做动效（motion / model / card-deck）",
        "screen-demo": "实机录屏（screen-demo）",
        "talk-only": "只看人留白（talk-only）",
    }
    for key in ("footage", "motion", "screen-demo", "talk-only"):
        b = stats["buckets"][key]
        lines.append(f"| {labels[key]} | {b['count']} | `{b['sec']:.2f}s` | `{b['pct']:.1f}%` |")
    for eng in ENGINES:
        e = stats["engines"][eng]
        lines.append(f"| 引擎 `{eng}` | {e['count']} | `{e['sec']:.2f}s` | `{e['pct']:.1f}%` |")

    lines += [
        "",
        "## 逐镜分镜表",
        "",
        "| 镜号 | 章节 | 时间区间 | 时长 | 类型 | 引擎 | 内容 / 素材 | 声景 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for s in doc.get("shots") or []:
        if not isinstance(s, dict):
            continue
        st0 = float(s.get("startSec", 0.0))
        st1 = float(s.get("endSec", 0.0))
        dur = max(0.0, st1 - st0)
        eng = _resolve_shot_engine(s, project=project)
        sound_bits: list[str] = []
        if s.get("soundBed") is not None:
            sound_bits.append(f"bed:{s['soundBed']}")
        if s.get("soundCues"):
            sound_bits.append("cues:" + ",".join(str(c) for c in s["soundCues"]))
        lines.append(
            f"| `{s.get('id', '-')}` | {s.get('chapter') or '—'} | "
            f"`{st0:.2f}–{st1:.2f}s` | `{dur:.2f}s` | `{s.get('kind', '-')}` | "
            f"`{eng}` | {_describe_shot_target(s)} | {'；'.join(sound_bits) or '—'} |"
        )

    if out is not None:
        out_path = out.expanduser()
        if not out_path.is_absolute():
            out_path = (project / out_path).resolve()
    elif project.name == "edit":
        out_path = project / "storyboard-overview.md"
    else:
        out_path = project / "edit" / "storyboard-overview.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    payload = {
        "ok": True,
        "out": str(out_path),
        "shots": stats["shotCount"],
        "totalSec": stats["totalSec"],
        "mix": stats["buckets"],
        "engines": stats["engines"],
    }
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=1))
    else:
        print(f"✓ 分镜概览已派生：{out_path}（{stats['shotCount']} 镜，{stats['totalSec']:.2f}s）")
    return 0


def _has_static_pages_reference(project: Path, sb_doc: dict | None) -> tuple[bool, str]:
    for rel in ("pages", "deliverable/pages"):
        pdir = project / rel
        if pdir.is_dir():
            files = [
                f for f in pdir.rglob("*")
                if f.is_file() and f.suffix.lower() in STATIC_REF_SUFFIXES and not f.name.startswith(".")
            ]
            if files:
                return True, f"存在静态参考页目录 {rel}/（{len(files)} 个文件）"
    if isinstance(sb_doc, dict):
        if sb_doc.get("staticReference") is True or sb_doc.get("reuseMatureStyle") is True:
            return True, "storyboard.json 已声明静态参考或沿用成熟风格"
        ref = sb_doc.get("reference")
        if isinstance(ref, dict) and (ref.get("keyframeSvgs") or ref.get("pages")):
            return True, "storyboard.json reference 已提供静态参考页"
    return False, ""


def _motion_shots_in(sb_doc: dict | None, project: Path) -> tuple[bool, list[dict]]:
    if isinstance(sb_doc, dict):
        shots = [s for s in (sb_doc.get("shots") or []) if isinstance(s, dict)]
        motion_shots = [
            s for s in shots if s.get("kind") in MOTION_KINDS or _resolve_shot_engine(s, project) in ("remotion", "hyperframes")
        ]
        caps = sb_doc.get("capabilities") or []
        if motion_shots or "motion" in caps:
            return True, motion_shots
        return False, []
    plan_path = project / PLAN_NAME
    if plan_path.is_file():
        try:
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            segs = [s for s in (plan.get("segments") or []) if isinstance(s, dict)]
            active = [s for s in segs if s.get("tier") in ("logic-diagram", "theory-board")]
            return bool(active), active
        except (OSError, json.JSONDecodeError):
            pass
    return False, []


def _pick_sample_shot(motion_shots: list[dict], sample_shot_id: str | None) -> dict | None:
    if sample_shot_id:
        for s in motion_shots:
            if s.get("id") == sample_shot_id:
                return s
        return None
    for s in motion_shots:
        if s.get("kind") in ("model", "motion"):
            return s
    return motion_shots[0] if motion_shots else None


def cmd_lookdev(
    project: Path,
    verify: bool = False,
    approve: bool = False,
    out_dir: Path | None = None,
    sample_shot_id: str | None = None,
    as_json: bool = False,
) -> int:
    sb_path = _find_storyboard(project)
    sb_doc: dict | None = None
    if sb_path is not None:
        try:
            sb_doc = json.loads(sb_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(json.dumps({"ok": False, "error": f"{STORYBOARD_NAME} 解析失败：{exc}"}, ensure_ascii=False, indent=1))
            return 2

    motion_active, motion_shots = _motion_shots_in(sb_doc, project)
    if not motion_active:
        payload = {
            "ok": True,
            "required": False,
            "exempt": True,
            "reason": "no-motion-active",
            "detail": "工程未启用 motion/model/card-deck（纯剪视频/口播/录屏），自动豁免 Look-Dev 定调",
        }
        print(json.dumps(payload, ensure_ascii=False, indent=1) if as_json else f"○ {payload['detail']}")
        return 0

    has_static_ref, ref_reason = _has_static_pages_reference(project, sb_doc)
    if has_static_ref:
        payload = {
            "ok": True,
            "required": False,
            "exempt": True,
            "reason": "static-reference-present",
            "detail": f"自动豁免 Look-Dev 定调：{ref_reason}",
        }
        print(json.dumps(payload, ensure_ascii=False, indent=1) if as_json else f"○ {payload['detail']}")
        return 0

    if sb_doc is None:
        payload = {"ok": False, "required": True, "exempt": False, "problems": [f"缺少 {STORYBOARD_NAME}，无法生成或校验 Look-Dev 定调包"]}
        print(json.dumps(payload, ensure_ascii=False, indent=1) if as_json else f"✗ {payload['problems'][0]}")
        return 1

    ld_dir = out_dir.expanduser().resolve() if out_dir is not None else (project / LOOKDEV_REL)
    manifest_path = ld_dir / LOOKDEV_MANIFEST
    sample_path = ld_dir / LOOKDEV_SAMPLE
    brief_path = ld_dir / LOOKDEV_BRIEF

    if verify and not approve:
        problems: list[str] = []
        manifest: dict = {}
        sample: dict = {}
        if not manifest_path.is_file():
            problems.append(f"缺少 Look-Dev 配比意图清单：{manifest_path}（先运行 film.py lookdev <project>）")
        else:
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                problems.append(f"{LOOKDEV_MANIFEST} 解析失败：{exc}")
        if not sample_path.is_file():
            problems.append(f"缺少单样镜契约：{sample_path}（先运行 film.py lookdev <project>）")
        else:
            try:
                sample = json.loads(sample_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                problems.append(f"{LOOKDEV_SAMPLE} 解析失败：{exc}")

        if manifest:
            if not isinstance(manifest.get("capabilityMix"), dict):
                problems.append(f"{LOOKDEV_MANIFEST}: 缺少 capabilityMix 配比统计")
            if not isinstance(manifest.get("intent"), str) or not manifest["intent"].strip():
                problems.append(f"{LOOKDEV_MANIFEST}: 缺少 intent 视觉定调意图")
            sm = manifest.get("sampleModel")
            valid_ids = {str(s.get("id")) for s in motion_shots if s.get("id")}
            if not isinstance(sm, dict) or not sm.get("shotId"):
                problems.append(f"{LOOKDEV_MANIFEST}: 缺少 sampleModel 单样镜定义")
            elif valid_ids and sm.get("shotId") not in valid_ids:
                problems.append(f"{LOOKDEV_MANIFEST}: sampleModel.shotId={sm.get('shotId')!r} 不在当前分镜动效镜头内")
            elif sample and sample.get("shotId") != sm.get("shotId"):
                problems.append(f"{LOOKDEV_SAMPLE}: shotId 与 {LOOKDEV_MANIFEST} 不一致")
            if manifest.get("approved") is not True:
                problems.append("Look-Dev 尚未拍板确认（approved != true）；审阅后运行 film.py lookdev <project> --approve")
        if sample and sample.get("status") == "rejected":
            problems.append(f"{LOOKDEV_SAMPLE}: status='rejected'，需重新调整样镜后拍板")

        result = {
            "ok": not problems,
            "required": True,
            "exempt": False,
            "approved": not problems,
            "manifest": str(manifest_path),
            "sample": str(sample_path),
            "problems": problems,
        }
        if as_json:
            print(json.dumps(result, ensure_ascii=False, indent=1))
        else:
            if result["ok"]:
                print(f"✓ Look-Dev 门禁已通过（样镜 {sample.get('shotId')} 已拍板）")
            else:
                print(f"✗ Look-Dev 门禁未通过（{len(problems)} 处）：")
                for item in problems:
                    print(f"  - {item}")
        return 0 if result["ok"] else 1

    # Generate (or approve) Look-Dev packet
    sample_shot = _pick_sample_shot(motion_shots, sample_shot_id)
    if sample_shot is None:
        msg = f"未找到可用的动效样镜（sample_shot={sample_shot_id!r}）"
        print(json.dumps({"ok": False, "error": msg}, ensure_ascii=False, indent=1))
        return 2

    stats = _compute_storyboard_stats(sb_doc, project=project)
    existing_approved = False
    if manifest_path.is_file() and not approve:
        try:
            existing_approved = json.loads(manifest_path.read_text(encoding="utf-8")).get("approved") is True
        except (OSError, json.JSONDecodeError):
            existing_approved = False

    is_approved = True if approve else existing_approved
    st0 = float(sample_shot.get("startSec", 0.0))
    st1 = float(sample_shot.get("endSec", 0.0))
    sample_id = str(sample_shot.get("id") or "M1")
    intent = (
        f"随口播推进演化的单一空间思维模型（Mental-Model Motion）；"
        f"参考调性：{sb_doc.get('referenceStyle') or '极简几何暗场'}；"
        f"优先打磨样镜 {sample_id}（{sample_shot.get('title') or sample_shot.get('kind')}）定调，再全片展开。"
    )
    sample_contract = {
        "version": "lookdev-sample/1",
        "shotId": sample_id,
        "kind": sample_shot.get("kind"),
        "modelId": sample_shot.get("modelId"),
        "title": sample_shot.get("title") or sample_id,
        "chapter": sample_shot.get("chapter"),
        "canvas": sb_doc.get("canvas"),
        "framePreset": sb_doc.get("framePreset"),
        "rhythm": {
            "startSec": st0,
            "endSec": st1,
            "durationSec": round(max(0.0, st1 - st0), 3),
            "soundCues": sample_shot.get("soundCues") or [],
        },
        "visualSpec": {
            "approach": "mental-model-motion",
            "borderRule": "thin-bone-white",
            "noChapterBadge": True,
        },
        "status": "approved" if is_approved else "pending",
    }
    manifest_doc = {
        "version": "lookdev/1",
        "project": sb_doc.get("project") or project.name,
        "framePreset": sb_doc.get("framePreset"),
        "canvas": sb_doc.get("canvas"),
        "capabilityMix": stats["buckets"],
        "intent": intent,
        "sampleModel": {
            "shotId": sample_id,
            "kind": sample_shot.get("kind"),
            "modelId": sample_shot.get("modelId"),
            "title": sample_shot.get("title") or sample_id,
            "startSec": st0,
            "endSec": st1,
            "contractPath": LOOKDEV_SAMPLE,
        },
        "approved": is_approved,
    }
    if is_approved:
        manifest_doc["approvedAt"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    brief_lines = [
        f"# 轻量 Look-Dev 定调单：{manifest_doc['project']}",
        "",
        f"- **状态**：{'已拍板（approved）' if is_approved else '待创作者拍板（pending）'}",
        f"- **画框预设**：`{manifest_doc['framePreset'] or '未指定'}`",
        f"- **核心意图**：{intent}",
        "",
        "## 能力配比清单",
        "",
        f"- 剪视频（footage）：`{stats['buckets']['footage']['pct']:.1f}%`（{stats['buckets']['footage']['count']} 镜）",
        f"- 做动效（motion）：`{stats['buckets']['motion']['pct']:.1f}%`（{stats['buckets']['motion']['count']} 镜）",
        f"- 实机录屏（screen-demo）：`{stats['buckets']['screen-demo']['pct']:.1f}%`（{stats['buckets']['screen-demo']['count']} 镜）",
        f"- 只看人留白（talk-only）：`{stats['buckets']['talk-only']['pct']:.1f}%`（{stats['buckets']['talk-only']['count']} 镜）",
        "",
        "## 代表性样镜（1 个）",
        "",
        f"- **镜号**：`{sample_id}`（`{sample_shot.get('kind')}`）",
        f"- **标题**：{sample_contract['title']}",
        f"- **口播节奏区间**：`{st0:.2f}–{st1:.2f}s`（`{sample_contract['rhythm']['durationSec']:.2f}s`）",
        f"- **契约文件**：`{LOOKDEV_SAMPLE}`",
    ]

    ld_dir.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    sample_path.write_text(json.dumps(sample_contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    brief_path.write_text("\n".join(brief_lines) + "\n", encoding="utf-8")

    payload = {
        "ok": True,
        "required": True,
        "exempt": False,
        "approved": is_approved,
        "manifest": str(manifest_path),
        "sample": str(sample_path),
        "brief": str(brief_path),
        "sampleShotId": sample_id,
    }
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=1))
    else:
        state = "已拍板" if is_approved else "已生成待拍板（审阅后运行 --approve）"
        print(f"✓ Look-Dev 定调包{state}：{ld_dir}（样镜 {sample_id}）")
    return 0


def cmd_verify(project: Path, as_json: bool) -> int:
    sb_path = _find_storyboard(project)
    if sb_path is not None:
        return _verify_storyboard(project, sb_path, as_json)

    plan_path = project / PLAN_NAME
    if plan_path.is_file():
        return _verify_visual_plan(project, plan_path, as_json)

    problems: list[str] = []
    pages_dir = project / PAGES_REL
    if not pages_dir.is_dir():
        msg = f"没有 {PLAN_NAME} 或 {PAGES_REL}/：先跑 film.py init {project}"
        print(json.dumps({"ok": False, "error": msg}, ensure_ascii=False, indent=1))
        return 1

    beats = _beats_of(project)
    mapping = load_map(project)
    if beats and not mapping:
        problems.append(f"{PAGES_REL}/{MAP_NAME} 缺失：每个 beat 都要指明对应哪一页原页")
    for beat in beats:
        bid = beat.get("id")
        if bid and bid not in mapping:
            problems.append(f"beat {bid} 没有对应原页（补 {PAGES_REL}/{MAP_NAME}: \"{bid}\": \"<pageKey>\"）")

    checked_pages = set()
    for page_key in sorted(set(mapping.values())):
        md_path = pages_dir / f"{page_key}.md"
        if not md_path.is_file():
            problems.append(f"缺拆解表：{md_path}（跑 film.py outline --page {page_key} --source <svg>）")
            continue
        md = md_path.read_text(encoding="utf-8")
        rows = _table_rows(md)
        if not rows:
            problems.append(f"{page_key}.md 没有元素表 —— 拆解没做，不允许进 composition")
            continue
        checked_pages.add(page_key)
        unfilled = []
        for cells in rows:
            action, cue = cells[4], cells[6]
            if action not in ("保留", "删", "拆"):
                unfilled.append(f"元素 {cells[0]} 的处置不合法：{action!r}")
            if not cue:
                unfilled.append(f"元素 {cells[0]} 没填「对应口播」")
        if unfilled:
            problems.append(f"{page_key}.md 还有 {len(unfilled)} 处没填：" + "；".join(unfilled[:3]))
        if not re.search(r"##\s*这一页要讲的一句话\s*\n+\s*[^\n（(]", md):
            problems.append(f"{page_key}.md 的「这一页要讲的一句话」还空着")

    composition = project / "composition"
    if not composition.is_dir():
        problems.append("没有 composition/ —— 拆解做完了，但画面还没建")

    result = {
        "ok": not problems,
        "beats": len(beats),
        "mapped": len(mapping),
        "pages_checked": sorted(checked_pages),
        "problems": problems,
        "next": ("拆解齐了 → 写 composition（每屏一个视觉重点、按拆解的阅读顺序出元素）"
                 if not problems else "按 problems 逐条补，补完再跑一次"),
    }
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=1))
    else:
        if result["ok"]:
            print(f"✓ 原页拆解齐备：{result['mapped']} 个 beat 对应 {len(result['pages_checked'])} 页原页，"
                  f"元素处置与口播都已登记")
        else:
            print(f"✗ 拆解还没做完（{len(problems)} 处）：")
            for item in problems:
                print(f"  - {item}")
    return 0 if result["ok"] else 1


def cmd_pages(project: Path) -> int:
    beats = _beats_of(project)
    mapping = load_map(project)
    if not beats:
        print(json.dumps({"ok": False, "error": "没有 recompose/lines.json 的 beats；先跑 recompose_plan.py"},
                         ensure_ascii=False, indent=1))
        return 2
    rows = []
    for beat in beats:
        bid = beat.get("id")
        page = mapping.get(bid)
        exists = bool(page) and (project / PAGES_REL / f"{page}.md").is_file()
        rows.append({"beat": bid, "title": beat.get("title"), "page": page,
                     "has_outline": exists})
    print(json.dumps({"ok": True, "rows": rows,
                      "missing": [r["beat"] for r in rows if not r["has_outline"]]},
                     ensure_ascii=False, indent=1))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init", help="初始化统一执行分镜 storyboard.json（或 --legacy-visual-plan）")
    p_init.add_argument("project", type=Path)
    p_init.add_argument("--overwrite", action="store_true")
    p_init.add_argument("--legacy-visual-plan", action="store_true", help="兼容旧工程：改为初始化 visual-plan.json")
    p_init.add_argument("--frame-preset", default=None, help="显式指定画框预设名（默认由画框真源推断）")
    p_init.add_argument("--json", action="store_true")

    p_proxy = sub.add_parser("proxy", help="为 storyboard.json / visual-plan.json 中实机演示段生成审阅轻代理")
    p_proxy.add_argument("project", type=Path)
    p_proxy.add_argument("--max-width", type=int, default=960)
    p_proxy.add_argument("--crf", type=int, default=28)
    p_proxy.add_argument("--json", action="store_true")

    p_outline = sub.add_parser("outline", help="（兼容旧工程）从原页 SVG 抽元素，写 pages/<page>.md 骨架")
    p_outline.add_argument("project", type=Path)
    p_outline.add_argument("--page", required=True, help="页 key（如 page_04）")
    p_outline.add_argument("--source", type=Path, help="原页 SVG 的绝对路径")
    p_outline.add_argument("--overwrite", action="store_true")
    p_outline.add_argument("--keep-chrome", action="store_true",
                           help="保留眉标/角标（如 collage/line-art 的档案编号）")

    p_pages = sub.add_parser("pages", help="（兼容旧工程）beat ↔ 原页 映射；写映射")
    p_pages.add_argument("project", type=Path)
    p_pages.add_argument("--map", default="", help="beatId=pageKey[,beatId=pageKey...]")

    p_verify = sub.add_parser("verify", help="闸门：校验 storyboard.json（或旧版 visual-plan.json / pages/）")
    p_verify.add_argument("project", type=Path)
    p_verify.add_argument("--json", action="store_true")

    p_summary = sub.add_parser("summary", help="从 storyboard.json 确定性派生人读 Markdown 概览")
    p_summary.add_argument("project", type=Path)
    p_summary.add_argument("--out", type=Path, default=None, help="输出 Markdown 路径（默认 edit/storyboard-overview.md）")
    p_summary.add_argument("--json", action="store_true")

    p_lookdev = sub.add_parser("lookdev", help="轻量 Look-Dev 定调门禁（生成配比意图清单与单样镜契约，--verify 校验拍板）")
    p_lookdev.add_argument("project", type=Path)
    p_lookdev.add_argument("--verify", action="store_true", help="校验 Look-Dev 是否已完备并拍板（豁免场景自动放行）")
    p_lookdev.add_argument("--approve", action="store_true", help="生成/更新并标记 Look-Dev 已拍板确认")
    p_lookdev.add_argument("--out-dir", type=Path, default=None, help="Look-Dev 输出目录（默认 <project>/lookdev）")
    p_lookdev.add_argument("--sample-shot", default=None, help="指定作为代表样镜的镜号 id")
    p_lookdev.add_argument("--json", action="store_true")

    p_import_svg = sub.add_parser("import-svg", help="将静态 SVG 参考页导入为 Remotion 运镜场景")
    p_import_svg.add_argument("project", type=Path)
    p_import_svg.add_argument("--source", type=Path, required=True, action="append", help="SVG 文件或目录（可多次传）")
    p_import_svg.add_argument("--seconds-per-slide", type=float, default=4.0)
    p_import_svg.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    project = args.project.expanduser().resolve()
    if args.cmd == "import-svg":
        sys.path.insert(0, str(Path(__file__).resolve().parent / "_internal"))
        from remotion_svg_scene import import_svg_pages_to_remotion  # noqa: E402
        res = import_svg_pages_to_remotion(
            project,
            [p.expanduser().resolve() for p in args.source],
            seconds_per_slide=args.seconds_per_slide,
        )
        if args.json:
            print(json.dumps(res, ensure_ascii=False, indent=2))
        else:
            print(f"✓ 已包装 {len(res['slides'])} 页静态 SVG 为 Remotion 场景 → {res['sceneFile']}")
        return 0
    if args.cmd == "init":
        return cmd_init(
            project,
            args.overwrite,
            args.json,
            legacy_visual_plan=args.legacy_visual_plan,
            frame_preset=args.frame_preset,
        )
    if args.cmd == "proxy":
        return cmd_proxy(project, args.max_width, args.crf, args.json)
    if args.cmd == "outline":
        return cmd_outline(project, args.page, args.source, args.overwrite, args.keep_chrome)
    if args.cmd == "pages":
        if args.map:
            return write_map(project, args.map.split(","))
        return cmd_pages(project)
    if args.cmd == "summary":
        return cmd_summary(project, args.out, args.json)
    if args.cmd == "lookdev":
        return cmd_lookdev(
            project,
            verify=args.verify,
            approve=args.approve,
            out_dir=args.out_dir,
            sample_shot_id=args.sample_shot,
            as_json=args.json,
        )
    return cmd_verify(project, args.json)


if __name__ == "__main__":
    raise SystemExit(main())
