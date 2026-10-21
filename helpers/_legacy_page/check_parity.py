#!/usr/bin/env python3
"""审阅面 / 合成面 一致性检查 —— 三条断言，全部确定性、可进自检。

## 为什么有它

`timeline/choreography.json` 是一份 spec，却有**三条实现路径**：composition 的 GSAP 补丁、
审阅页活舞台的 runtime、以及引擎原语本身。三方没有任何守卫，于是同一类事故反复发生
（见 GOTCHAS #6/#8/#9，与 `references/review-ui.md`）：

- spec 里写的 `kind`，某一条路径**没有实现** → 预览会演、渲染不演（或反过来），两边都不报错；
- spec 里的 `selector` 在目标页面里**命中不到元素** → 那一步静默跳过（标注移出 `data-step`
  分组后就发生过：制图轨道还在跑，只是"落标注"永远不发生）。

这两件都不会让 `hyperframes check` 失败，也不会让页面报错 —— 只能靠断言拦。

## 用法

    python3 helpers/check_parity.py <project>

退出码非 0 = 不一致。可放进项目交付前的自检链。

## 边界（刻意保守）

selector 解析不做完整 CSS 匹配：只校验 `#id` 是否存在于目标 SVG，以及无 `#id` 时选择器里
的标签/属性标记是否在 SVG 文本中出现。够抓住"元素被移走/改名"这类真实事故，不做样式匹配。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# spec 里用到的每个 effects kind，必须在两条实现路径里都有分支
KIND_IMPLS = {
    "draft-reveal": ["draft-reveal"],
    "camera-push": ["camera-push"],
    "mirrored-3d-split-tilt": ["mirrored-3d-split-tilt"],
    "stretch-retract": ["stretch-retract"],
    "translate-out": ["translate-out"],
}


def fail(msg: str, hits: list[str]) -> None:
    hits.append(msg)


def main(project: Path) -> int:
    problems: list[str] = []
    notes: list[str] = []

    choreo_path = project / "timeline" / "choreography.json"
    if not choreo_path.is_file():
        print(f"✗ 找不到 {choreo_path}")
        return 2
    choreo = json.loads(choreo_path.read_text(encoding="utf-8"))
    screens = choreo.get("screens") or {}

    svg_dir = project / "visual_screens" / "_internal" / "02_svg_source"
    comp_path = project / "composition" / "index.html"
    page_path = project / "review" / "index.html"
    comp = comp_path.read_text(encoding="utf-8") if comp_path.is_file() else ""
    page = page_path.read_text(encoding="utf-8") if page_path.is_file() else ""
    if not comp:
        notes.append("composition/index.html 不存在，跳过路径 1 的检查")
    if not page:
        notes.append("review/index.html 不存在，跳过路径 2 的检查")

    kinds = set()
    checks = 0

    for screen_id, screen in screens.items():
        svg_file = svg_dir / f"{screen_id}.svg"
        if svg_file.is_file():
            svg = svg_file.read_text(encoding="utf-8")
        else:
            # 复用别页的屏（例如钩子复用 beat-03）：按 sourcePageKey 找
            key = screen.get("sourcePageKey") or screen_id
            alt = svg_dir / f"{key}.svg"
            svg = alt.read_text(encoding="utf-8") if alt.is_file() else ""
            if not svg:
                fail(f"{screen_id}: 找不到源 SVG（{screen_id}.svg / {key}.svg）", problems)
                continue

        # ── 断言 A：spec 里每个 kind 在两条实现路径里都有分支 ───────────────
        for fx in screen.get("effects") or []:
            kind = fx.get("kind")
            kinds.add(kind)
            checks += 1
            if kind not in KIND_IMPLS:
                fail(f"{screen_id}: effects kind `{kind}` 未登记（新效果要在 KIND_IMPLS 里登记）", problems)
            if comp and f"'{kind}'" not in comp and f'"{kind}"' not in comp:
                fail(f"{screen_id}: effects kind `{kind}` 在 composition 里没有实现分支", problems)
            if page and f'"{kind}"' not in page:
                fail(f"{screen_id}: effects kind `{kind}` 在审阅页 runtime 里没有实现分支", problems)

        # ── 断言 B1：typewriter 的 selector 必须命中 ────────────────────────
        for tw in screen.get("typewriter") or []:
            checks += 1
            sel = tw.get("selector", "")
            if not selector_hits(svg, sel):
                fail(f"{screen_id}: typewriter selector `{sel}` 在该页 SVG 里命中不到元素（会静默不打字）", problems)

        # ── 断言 B2：effects[].tracks[] 的 selector / 标注 selector 必须命中 ─
        for fx in screen.get("effects") or []:
            for tr in fx.get("tracks") or []:
                for ph in tr.get("phases") or []:
                    checks += 1
                    sel = ph.get("selector", "")
                    if sel and not selector_hits(svg, sel):
                        fail(f"{screen_id}: 制图轨道 selector `{sel}` 在该页 SVG 里命中不到元素（该相位会静默跳过）", problems)
                lbl = tr.get("labelSelector")
                if lbl:
                    checks += 1
                    if not selector_hits(svg, lbl):
                        fail(f"{screen_id}: 标注 selector `{lbl}` 在该页 SVG 里命中不到（标注会永远不出现）", problems)

        # ── 断言 C：强调目标的 id 必须在 SVG 里 ─────────────────────────────
        for item in screen.get("emphasis") or []:
            sid = item.get("stepId", "")
            checks += 1
            if sid and f'id="{sid}"' not in svg:
                fail(f"{screen_id}: emphasis 目标 `{sid}` 在该页 SVG 里不存在", problems)
            act = item.get("action") or {}
            for key in ("selector", "lineSelector", "tipSelector"):
                sel = act.get(key)
                if sel:
                    checks += 1
                    if not selector_hits(svg, sel):
                        fail(f"{screen_id}: 强调动作 {key}=`{sel}` 在该页 SVG 里命中不到", problems)

    print(f"审阅面一致性：{checks} 项检查，{len(problems)} 个问题")
    for n in notes:
        print(f"  · {n}")
    for p in problems:
        print(f"  ✗ {p}")
    if not problems:
        print("  ✓ 三方一致（spec ↔ composition ↔ 审阅页 runtime）")
    return 1 if problems else 0


def selector_hits(svg: str, sel: str) -> bool:
    """保守命中判定：`#id` 必须在；否则看选择器里的标签/属性标记是否出现。

    两个必须处理的坑：
    1. 先剥掉属性选择器（`[stroke='#FFFFFF']`），否则里面的颜色值会被当成 `#id`；
    2. `:not([attr])` 是**取反**语义（定位点相位就用 `circle:not([stroke])`），
       按正向判会永远失配 —— 必须真的去数"有没有该标签且不带该属性的元素"。
    """
    if not sel:
        return False
    neg = re.search(r"^([a-z]+):not\(\[([A-Za-z-]+)\]\)", sel.strip())
    if neg:
        tag, attr = neg.group(1), neg.group(2)
        return any(f"{attr}=" not in m.group(0)
                   for m in re.finditer(rf"<{tag}\b[^>]*>", svg))
    bare = re.sub(r"\[[^\]]*\]", "", sel)
    ids = re.findall(r"#([A-Za-z0-9_-]+)", bare)
    if ids:
        return all(f'id="{i}"' in svg for i in ids)
    m = re.search(r"\[([A-Za-z-]+)", sel)
    if m:
        return m.group(1) in svg
    m = re.search(r"^([a-z]+)", sel.strip())
    if m:
        return f"<{m.group(1)}" in svg
    return True


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(Path(sys.argv[1]).resolve()))
