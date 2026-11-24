#!/usr/bin/env python3
"""`画面` —— 四档视觉分拍网关与实机代理工具（兼旧项目 `pages/` 只读兼容）。

四档视觉语法（`visual-plan.json`）
---------------------------------
- `talk-only`     只看人留白档（故事引入、观点铺垫、金句与节奏过渡）
- `logic-diagram` 逻辑演进档（默认主力：集合/因果/定位/对比，每屏 1–2 主图 + 锚点词）
- `theory-board`  理论拆解档（多维模型/清单：支持讲到哪条点亮哪条、其余降暗）
- `demo-footage`  实机演示录屏档（审阅挂 `proxy`，交付直读高清原录屏并做屏幕文字保护）

旧 `pages/` 逐元素拆解仅作历史项目只读兼容，不再作为新建项目的强制门槛；静态参考图只作配色、比例与造型风格参考。

用法
----
    python3 helpers/film.py init   <project>              # 从 timeline/grouping 初始化四档 visual-plan.json
    python3 helpers/film.py verify <project> [--json]     # 校验 visual-plan.json（无之则按旧 pages/ 回退）
    python3 helpers/film.py proxy  <project> [--json]     # 为 demo-footage 段生成审阅用低码率代理片
    python3 helpers/film.py outline / pages ...           # 旧静态参考页兼容子命令

退出码：0 = 通过；1 = 有缺口（逐条列出）；2 = 前置缺失。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

PAGES_REL = "pages"
MAP_NAME = "map.json"
PLAN_NAME = "visual-plan.json"
VISUAL_TIERS = ("talk-only", "logic-diagram", "theory-board", "demo-footage")
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


def cmd_init(project: Path, overwrite: bool = False, as_json: bool = False) -> int:
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


def _resolve_plan_source(project: Path, raw: str) -> Path:
    p = Path(raw).expanduser()
    return (p if p.is_absolute() else (project / p)).resolve()


def _is_inside_composition_assets(src: Path, project: Path) -> bool:
    comp_assets = (project / "composition" / "assets").resolve()
    return src == comp_assets or src.is_relative_to(comp_assets)


def cmd_proxy(project: Path, max_width: int = 960, crf: int = 28, as_json: bool = False) -> int:
    plan_path = project / PLAN_NAME
    if not plan_path.is_file():
        print(json.dumps({"ok": False, "error": f"缺 {PLAN_NAME}；先跑 film.py init"}, ensure_ascii=False, indent=1))
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
        safe_id = re.sub(r"[^A-Za-z0-9._-]+", "_", seg_id)
        demo = seg.get("demo")
        if not isinstance(demo, dict) or not demo.get("source"):
            print(json.dumps({"ok": False, "error": f"{seg_id} 缺少 demo.source"}, ensure_ascii=False, indent=1))
            return 1
        src = _resolve_plan_source(project, str(demo["source"]))
        if _is_inside_composition_assets(src, project):
            print(json.dumps({"ok": False, "error": f"{seg_id} 原录屏禁止放入 composition/assets/: {src}"},
                             ensure_ascii=False, indent=1))
            return 1
        if not src.is_file():
            print(json.dumps({"ok": False, "error": f"{seg_id} 找不到原录屏：{src}"}, ensure_ascii=False, indent=1))
            return 1
        in_sec = float(demo.get("inSec", 0.0))
        out_sec = float(demo.get("outSec", 0.0))
        if in_sec < 0 or out_sec <= in_sec:
            print(json.dumps({"ok": False, "error": f"{seg_id} 入出点非法：inSec={in_sec}, outSec={out_sec}"},
                             ensure_ascii=False, indent=1))
            return 1
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
                print(json.dumps({"ok": False, "error": f"{seg_id} 生成代理片失败：{proc.stderr[-300:]}"},
                                 ensure_ascii=False, indent=1))
                return 1
            shutil.move(str(tmp_out), str(out_file))
        finally:
            if tmp_out.exists():
                tmp_out.unlink(missing_ok=True)
        rel_proxy = os.path.relpath(out_file.resolve(), project.resolve()).replace(os.sep, "/")
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


def cmd_verify(project: Path, as_json: bool) -> int:
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

    p_init = sub.add_parser("init", help="初始化四档视觉语法分拍表 visual-plan.json")
    p_init.add_argument("project", type=Path)
    p_init.add_argument("--overwrite", action="store_true")
    p_init.add_argument("--json", action="store_true")

    p_proxy = sub.add_parser("proxy", help="为 visual-plan.json 中实机演示段生成审阅轻代理")
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

    p_verify = sub.add_parser("verify", help="闸门：校验 visual-plan.json（或旧版 pages/）")
    p_verify.add_argument("project", type=Path)
    p_verify.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    project = args.project.expanduser().resolve()
    if args.cmd == "init":
        return cmd_init(project, args.overwrite, args.json)
    if args.cmd == "proxy":
        return cmd_proxy(project, args.max_width, args.crf, args.json)
    if args.cmd == "outline":
        return cmd_outline(project, args.page, args.source, args.overwrite, args.keep_chrome)
    if args.cmd == "pages":
        if args.map:
            return write_map(project, args.map.split(","))
        return cmd_pages(project)
    return cmd_verify(project, args.json)


if __name__ == "__main__":
    raise SystemExit(main())
