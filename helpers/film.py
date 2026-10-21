#!/usr/bin/env python3
"""`画面` —— 一个深模块：**先读懂原页，再写 composition**。

它替换掉的是一整条历史路线
--------------------------
旧 Skill 里有两条动画路线（保真页面 page / 重排 recompose，另有一段"能力包组合"），
入口判断给的是三个名字 + 十几组能力，没有一句"你的输入是这个就走这条命令"。结果是
实现方**跳过了所有路线，自己手写一套 composition**，把原页"重画"成抽象几何 ——
2026-10-21 的三条片上，用户的原话是"太简单、缺画面、不如我 PPT 清楚"。

所以这里只留一个方向，而且把**原页拆解**做成硬闸门：

    outline  —— 从原页（PPT 导出的 SVG）抽出元素清单，写成 `pages/<page>.md` 骨架
    verify   —— 拆解表必须填满（每个元素的处置 + 对应哪句口播），然后 composition 才准进门
    pages    —— 看 beat ↔ 原页的映射，缺哪一页

接口只有这三个动词。原页是唯一事实来源；拆解表是动手前必须交的作业。

为什么"拆解"不能省
------------------
用户说的不是"画风不喜欢"，是"你没理解我在讲什么"。原页里每个框、每个数字、每根线
都已经携带信息；**只有先把它们逐条登记、并指认它对应哪一句口播，动画才知道该讲什么**。
跳过这一步，能画出来的就只有抽象几何。

用法
----
    python3 helpers/film.py outline <project> --page page_04 --source <svg路径>
    python3 helpers/film.py pages  <project> --map <beatId>=<pageKey>[,<beatId>=<pageKey>...]
    python3 helpers/film.py verify <project> [--json]

退出码：0 = 通过；1 = 有缺口（会逐条列出该补什么）；2 = 前置缺失。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

PAGES_REL = "pages"
MAP_NAME = "map.json"
SVG_NS = "{http://www.w3.org/2000/svg}"

# 原页里这些内容是"版面记号"，不是内容 —— 默认判为删，并写清理由
CHROME_PATTERNS = (
    ("页码", re.compile(r"^\d{1,2}\s*/\s*\d{1,2}$")),
    ("页脚署名", re.compile(r"IVAN|阿祖|@")),
    ("眉标/章节标", re.compile(r"^[0-9A-Z ·/—_\-]{6,}$")),
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
                      "fill": node.get("fill") or ""}
    if tag == "rect":
        w = float(node.get("width") or 0)
        h = float(node.get("height") or 0)
        full = w >= 1800 and h >= 1000
        return ("底" if full else "框"), {"w": w, "h": h,
                                        "fill": node.get("fill") or "",
                                        "stroke": node.get("stroke") or ""}
    if tag == "line":
        return "线", {"stroke": node.get("stroke") or ""}
    if tag == "circle":
        return "点", {"r": float(node.get("r") or 0), "fill": node.get("fill") or ""}
    if tag == "image":
        return "图", {}
    return "其他", {}


def _disposition(kind: str, info: dict) -> tuple[str, str]:
    """默认处置 + 理由。人/模型可以改，但必须留下处置这一列。"""
    if kind == "底":
        return "保留", "整页底色，是这一页的纸/暗场"
    if kind == "字":
        text = info.get("text") or ""
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


def extract_elements(svg_path: Path) -> list[dict]:
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
        x = float(node.get("x") or 0)
        y = float(node.get("y") or 0)
        if kind in ("框", "底", "图"):
            x = float(node.get("x") or 0)
            y = float(node.get("y") or 0)
        action, reason = _disposition(kind, info)
        out.append({
            "kind": kind, "x": x, "y": y, "info": info,
            "text": text, "action": action, "reason": reason,
        })
    # 阅读顺序：先上后下、先左后右
    out.sort(key=lambda e: (round(e["y"] / 8), e["x"]))
    return out


def _page_key_from(svg_path: Path) -> str:
    return svg_path.stem


def cmd_outline(project: Path, page_key: str, source: Path | None, overwrite: bool = False) -> int:
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
        elements = extract_elements(source)
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


def cmd_verify(project: Path, as_json: bool) -> int:
    problems: list[str] = []
    pages_dir = project / PAGES_REL
    if not pages_dir.is_dir():
        print(json.dumps({"ok": False, "error": f"没有 {PAGES_REL}/：先跑 film.py outline 拆原页"},
                         ensure_ascii=False, indent=1))
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

    p_outline = sub.add_parser("outline", help="从原页 SVG 抽元素，写 pages/<page>.md 骨架")
    p_outline.add_argument("project", type=Path)
    p_outline.add_argument("--page", required=True, help="页 key（如 page_04）")
    p_outline.add_argument("--source", type=Path, help="原页 SVG 的绝对路径")
    p_outline.add_argument("--overwrite", action="store_true")

    p_pages = sub.add_parser("pages", help="beat ↔ 原页 映射；写映射")
    p_pages.add_argument("project", type=Path)
    p_pages.add_argument("--map", default="", help="beatId=pageKey[,beatId=pageKey...]")

    p_verify = sub.add_parser("verify", help="闸门：拆解填满了吗")
    p_verify.add_argument("project", type=Path)
    p_verify.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    project = args.project.expanduser().resolve()
    if args.cmd == "outline":
        return cmd_outline(project, args.page, args.source, args.overwrite)
    if args.cmd == "pages":
        if args.map:
            return write_map(project, args.map.split(","))
        return cmd_pages(project)
    return cmd_verify(project, args.json)


if __name__ == "__main__":
    raise SystemExit(main())
