#!/usr/bin/env python3
"""Static guardrail for the review-page template.

Why static, and what it is worth
--------------------------------
Several defects shipped together in `visual/assets/review-page-template.html` and the
author found every one of them by hand, over three rounds, while two browser tests
sat dead in `tests/` (one was not a unittest and referenced three deleted buttons,
the other was opt-in and skipped for want of playwright). Every one of those is
a **fixed syntactic shape**, so each gets a deterministic check rather than a rule
for a reviewer to remember.

What this buys: the recorded defects cannot come back silently. What it does **not**
buy: any proof that the page works. A new *kind* of stage defect still needs a human
to hit it. Do not read a green run here as "the review page is verified" —
`architecture.md` records that boundary where the next reader will look for it.

Checks
------
  S1  舞台选择函数不得把调用方传进来的参数改写掉
  S2  标记里每个可交互的 `id` 都必须在脚本里被引用（挂载点与元素一一对应）
  S3  标记里恰好一块舞台可见，且必须是最不挑数据的那块（SVG 舞台）
  S4  每次 `review.readText(...)` 都必须带 `{ optional: true }`
  S5  字幕不得在匹配不到当前句时退回"整屏字幕"
  S6  点一屏的分支里，seek 了成片播放器就必须把它播起来
  S7  标记里不得出现声明了却没人定义的自定义元素（空壳）
  S8  舞台提升必须在初始化 IIFE 之外也被调用一次
  S9  调整项的归属键只能有一个出处（写读键域不得分叉）

Usage
-----
    check_review_template.py                      # 查发布中的模板
    check_review_template.py --template PATH      # 查别处的一份
    check_review_template.py --json
    check_review_template.py --prove              # 把历史缺陷逐条打回去，证明每条检查真的会响

Exit: 0 clean · 1 findings · 2 the template was not found.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

DEFAULT_TEMPLATE = Path(__file__).resolve().parents[1] / "visual/assets/review-page-template.html"

STAGE_WRAPS = ["svg-stage-wrap", "live-stage-wrap", "composite-player-wrap",
               "verbatim-iframe-wrap"]
# 永远有内容可画的那块：其余三块都取决于项目有没有对应数据
ALWAYS_STAGEABLE = "svg-stage-wrap"

# 宿主框架提供的元素（这些不需要本文件 define）
FRAMEWORK_ELEMENTS: set[str] = {"hyperframes-player"}  # build_review inlines the installed official implementation



def _strip_comments(text: str) -> str:
    """去掉 JS 注释再找调用 —— 注释里出现同名文字不该被当成一次调用。

    这条是踩出来的：S8 的说明里写了 `promoteStage()`，判据就把注释当调用，
    于是「把缺陷打回去」的自证反而通过不了。
    """
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"(?m)^\s*//.*$", "", text)
    return text

def _balanced_body(html: str, open_brace: int) -> str:
    """Return the text between the brace at `open_brace` and its match."""
    depth = 0
    for i in range(open_brace, len(html)):
        ch = html[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return html[open_brace + 1:i]
    return html[open_brace + 1:]


def s1_stage_function_keeps_its_argument(html: str) -> list[str]:
    out = []
    for m in re.finditer(r"function\s+setStageViewMode\s*\(\s*(\w+)\s*\)\s*\{", html):
        param = m.group(1)
        body = _balanced_body(html, m.end() - 1)
        for hit in re.finditer(rf'(?m)^\s*{re.escape(param)}\s*=\s*(".*?"|\'.*?\')\s*;', body):
            line = body[:hit.start()].count("\n") + 1
            out.append(f"setStageViewMode() 第 {line} 行把参数 {param} 改写成了字面量 "
                       f"{hit.group(1)} —— 调用方传进来的舞台选择被丢掉了")
    return out


def s2_buttons_are_wired(html: str) -> list[str]:
    """每个按钮要么被 id 引用，要么挂在一个被委托监听的 data-* 钩子上。

    只认 id 会把工具栏那三个按钮（`data-stage-tool` + 一个委托监听）误判成死的 ——
    而对正确代码报红的检查，训练出来的是忽略它。
    """
    out = []
    for m in re.finditer(r"<button[^>]*>", html):
        tag = m.group(0)
        idm = re.search(r'\bid="([^"]+)"', tag)
        if not idm:
            continue
        el = idm.group(1)
        if html.count(f'"{el}"') > 1:
            continue
        rest = html.replace(tag, "", 1)
        hooks = re.findall(r'\b(data-[a-z0-9-]+)=', tag)
        if any(re.search(rf'\b{re.escape(hook)}\b', rest) for hook in hooks):
            continue
        out.append(f"<button id=\"{el}\"> 既没有在脚本里按 id 引用，也没有挂在被监听的 "
                   f"data-* 钩子上 —— 点了不会有事发生")
    return out


def s3_default_stage_is_stageable(html: str) -> list[str]:
    visible = [s for s in STAGE_WRAPS
               if re.search(rf'id="{re.escape(s)}"(?![^>]*\bhidden\b)', html)]
    out = []
    if len(visible) != 1:
        out.append(f"标记里可见的舞台有 {len(visible)} 块（{'、'.join(visible) or '无'}）"
                   f"；必须恰好一块，否则页面开在哪个舞台上取决于标记顺序")
    elif visible[0] != ALWAYS_STAGEABLE:
        out.append(f"标记默认可见的舞台是 {visible[0]}，而最不挑数据的是 {ALWAYS_STAGEABLE}："
                   f"项目没有对应数据时页面会停在空占位上")
    return out


# 页面离开这两个就读不出自己是谁、也没有时间轴。它们不像可选文件 —— 404 是真的致命，
# 所以明确列出来，而不是把规则放宽到抓不住东西。
REQUIRED_READS = {"REVIEW_SURFACE_REL", "TIMELINE_REL"}


def s4_reads_are_optional(html: str) -> list[str]:
    out = []
    for m in re.finditer(r"review\.readText\(([^;]{0,200}?)\)", html):
        args = m.group(1)
        if "optional" in args:
            continue
        target = args.split(",")[0].strip()
        if target in REQUIRED_READS:
            continue
        out.append(f"review.readText({target[:60]}…) 没带 {{ optional: true }} —— "
                   f"文件还不存在时会在状态栏刷一条 404。它若不真的是必需文件，就补 optional；"
                   f"若真是必需的，加进 REQUIRED_READS 并写清理由")
    return out


def s5_subtitle_no_whole_step_fallback(html: str) -> list[str]:
    out = []
    if re.search(r"if\s*\(\s*!\s*matchedText\s*&&\s*\w+\s*\)", html):
        out.append("字幕更新器里有「匹配不到就退回 st.caption」的分支 —— "
                   "st.caption 是整屏所有句子的拼接，塞进圆角药丸会把它撑成一个椭圆盖住舞台")
    if "captions.length" not in html:
        out.append("字幕更新器里看不到 captions.length 判断 —— 有字幕契约时的匹配路径不见了")
    return out


def s6_step_click_plays(html: str) -> list[str]:
    """点一屏必须真的看起来。

    只查分屏点击处理函数那一段：切舞台（L2450）与拖进度条（L2596）里 seek 而不播
    是**对的** —— 那两处不该自己开始播放。把整份文件里所有 `compVid.currentTime =`
    都算成缺陷，就成了对正确代码报红的门。
    """
    m = re.search(r'el\.addEventListener\(\s*"click"\s*,\s*async\s*\(\)\s*=>\s*\{', html)
    if not m:
        return ["找不到分屏点击处理函数（el.addEventListener(\"click\", async () => {…}）—— "
                "判据的前提没了，检查会永远通过"]
    body = _balanced_body(html, m.end() - 1)
    if "compVid.currentTime" in body and "compVid.play()" not in body:
        return ["分屏点击处理函数 seek 了成片播放器却没有 compVid.play() —— "
                "点一屏得到的是一张静止帧（舞台还停在静态 SVG 页上）"]
    return []


def s7_no_undeclared_custom_elements(html: str) -> list[str]:
    tags = set(re.findall(r"<([a-z][a-z0-9]*-[a-z0-9-]+)[\s>/]", html))
    defined = set(re.findall(r"customElements\.define\(\s*[\"']([^\"']+)[\"']", html))
    out = []
    for tag in sorted(tags - defined - FRAMEWORK_ELEMENTS):
        out.append(f"<{tag}> 出现在标记里，但这份文件没有 customElements.define(\"{tag}\") —— "
                   f"空壳元素比没声明更坏：它让人以为已经有了")
    return out



def s8_stage_promotion_survives_init_failure(html: str) -> list[str]:
    """舞台提升必须在初始化 IIFE **之外**也被调用一次。

    它原先是那个 async IIFE 的最后一句：前面任何 await 抛错，提升就永远不执行，页面
    停在标记给的静态 SVG 舞台上 —— 而且看门狗也不响（`attach()` 根本没被调用），
    于是一个「初始化失败」伪装成「这个项目没有能播的东西」。舞台显示什么只取决于
    数据，不该取决于初始化跑没跑完。
    """
    out = []
    code = _strip_comments(html)
    if not re.search(r"function\s+promoteStage\s*\(", code):
        return ["找不到 promoteStage() —— 提升逻辑又回到初始化 IIFE 的末尾了"]
    m = re.search(r"\(async\s*\(\)\s*=>\s*\{", code)
    if not m:
        return ["找不到初始化 IIFE —— 判据的前提没了，检查会永远通过"]
    body_start = m.end() - 1
    body = _balanced_body(code, body_start)
    span = (body_start, body_start + len(body) + 2)
    # 只认**语句级**调用：`function promoteStage() {` 里也含 `promoteStage()`，
    # 把它算成一次调用，判据就永远不会失败（又一次「永远不会失败的判据」）。
    calls = [mm.start() for mm in re.finditer(r"(?m)^\s*promoteStage\(\)\s*;", code)]
    if not calls:
        return ["promoteStage() 定义了却从没被调用"]
    if not [i for i in calls if not (span[0] <= i < span[1])]:
        out.append("promoteStage() 只在初始化 IIFE 内部被调用 —— 前面任何 await 抛错，"
                   "提升就永远不执行，页面停在静态舞台，看门狗也不会响")
    return out

def s9_adjustment_key_has_one_source(html: str) -> list[str]:
    """调整项的归属键只能有一个出处。

    2026-10-16 修的真实缺陷：写入侧用过**两个不同的兜底键** —— 改字 `state.step || "global"`、
    框选批注 `state.step || "overall"` —— 而提交记录那三行读取侧一律用裸 `state.step`。
    没选中步时（`if (state.step)` 式守卫证明它可为空），写入落进**没有任何读者**的键：
    作者在画布上改的字被静默丢弃，而「保存反馈」看起来是成功的。
    当时唯一断言该字段的用例只断言"键存在"，且被 env 门跳过，所以没人发现。

    判据：① 唯一的键函数存在；② 三张调整表不得再用裸 `state.step` 索引；
          ③ 不得再就地写 `state.step || "…"` 形式的兜底键。
    """
    code = _strip_comments(html)
    out: list[str] = []
    if not re.search(r"(?:const|let|var|function)\s+adjustKey\b", code):
        out.append("找不到唯一的调整项归属键函数 `adjustKey` —— 键域迟早再分叉")
    for name in ("svgEdits", "choreoOverrides", "annotations"):
        for m in re.finditer(rf"state\.{name}\[\s*state\.step\s*\]", code):
            line = code[:m.start()].count("\n") + 1
            out.append(f"state.{name}[state.step] 用裸键直接索引（第 {line} 行附近）—— "
                       f"必须走 adjustKey()，否则没选中步时写入键与读取键不是同一个")
    # 兜底键只允许出现在 adjustKey 的定义那一行（那就是唯一出处本身）。
    m_def = re.search(r"(?:const|let|var|function)\s+adjustKey\b[^\n]*", code)
    def_span = (m_def.start(), m_def.end()) if m_def else None
    for m in re.finditer(r'state\.step\s*\|\|\s*"([^"]+)"', code):
        if def_span and def_span[0] <= m.start() < def_span[1]:
            continue          # 唯一出处的定义行，合法
        # 行号按去注释后的文本算，只作定位用
        line = code[:m.start()].count("\n") + 1
        out.append(f'第 {line} 行附近（去注释后行号）又出现 `state.step || "{m.group(1)}"` '
                   f"这种就地兜底键 —— 归属键只能由 adjustKey() 定义")
    return out


CHECKS = [
    ("S1", "舞台选择函数保住参数", s1_stage_function_keeps_its_argument),
    ("S2", "可交互 id 都挂了事件", s2_buttons_are_wired),
    ("S3", "默认舞台是最不挑数据的那块", s3_default_stage_is_stageable),
    ("S4", "readText 都是 optional", s4_reads_are_optional),
    ("S5", "字幕不退回整屏", s5_subtitle_no_whole_step_fallback),
    ("S6", "点一屏即播", s6_step_click_plays),
    ("S7", "没有空壳自定义元素", s7_no_undeclared_custom_elements),
    ("S8", "舞台提升不依赖初始化成败", s8_stage_promotion_survives_init_failure),
    ("S9", "调整项归属键只有一个出处", s9_adjustment_key_has_one_source),
]

# 把历史缺陷原样打回去，证明每条检查真的会响（对着 GOTCHA #30「一个永远不会失败的判据」）。
# 目标状态是**修好之后**的模板：自证要证明的是"从干净基线也能被抓住"，
# 而不是"这份目前还脏着的文件恰好被抓住"。
def _proof_s1(h):
    return h.replace("function setStageViewMode(mode) {",
                     "function setStageViewMode(mode) {\n      mode = \"composite\";", 1)


def _proof_s2(h):
    return re.sub(r'(<button[^>]*\bid=")btn-back-to-stage(")',
                  r"\1btn-a-button-nobody-wires\2", h, count=1)


def _proof_s3(h):
    # 让两块舞台同时可见：默认舞台就不确定了
    return re.sub(r'(id="(?:svg-stage-wrap|composite-player-wrap)")\s+hidden', r"\1", h)


def _proof_s4(h):
    # 拿掉一个非必需读取的 optional
    return h.replace("review.readText(DRAFT_REL, { optional: true })",
                     "review.readText(DRAFT_REL)", 1)


def _proof_s5(h):
    return h.replace("function updateStageSubtitle(st, curTimeSec) {",
                     "function updateStageSubtitle(st, curTimeSec) {\n"
                     "      let matchedText = \"\";\n"
                     "      if (!matchedText && st) { matchedText = st.caption || \"\"; }", 1)


def _proof_s6(h):
    # 把分屏点击处理函数里的 play() 拿掉：seek 还在，播放没了
    m = re.search(r'el\.addEventListener\(\s*"click"\s*,\s*async\s*\(\)\s*=>\s*\{', h)
    if not m:
        return h
    body = _balanced_body(h, m.end() - 1)
    if "compVid.play()" not in body:
        return h
    stripped = body.replace("compVid.play()", "/*play removed*/")
    return h[:m.end() - 1] + "{" + stripped + "}" + h[m.end() - 1 + len(body) + 2:]


def _proof_s7(h):
    return h.replace("</body>", "<undefined-preview></undefined-preview>\n</body>", 1)


def _proof_s8(h):
    # 把 IIFE 之外那次提升调用删掉，让提升只剩 IIFE 内部那一次
    i = h.find("\n    promoteStage();\n")
    if i < 0:
        return h
    return h[:i] + "\n" + h[i + len("\n    promoteStage();\n"):]


def _proof_s9(h):
    # 把写入侧换成另一个兜底键、读取侧换回裸键 —— 正是 2026-10-16 那个缺陷的形状
    return h.replace('const sid = adjustKey();', 'const sid = state.step || "overall";', 1)


PROOFS = {"S1": _proof_s1, "S2": _proof_s2, "S3": _proof_s3, "S4": _proof_s4,
          "S5": _proof_s5, "S6": _proof_s6, "S7": _proof_s7, "S8": _proof_s8, "S9": _proof_s9}


def check_template(path: Path) -> dict:
    html = path.read_text(encoding="utf-8")
    results = []
    for code, title, fn in CHECKS:
        findings = fn(html)
        results.append({"code": code, "title": title, "ok": not findings, "findings": findings})
    return {"template": str(path), "checks": results,
            "failed": sum(1 for r in results if not r["ok"])}


def prove() -> int:
    """每条检查都必须能在被打回缺陷的副本上响起来。"""
    html = DEFAULT_TEMPLATE.read_text(encoding="utf-8")
    by_code = {code: fn for code, _t, fn in CHECKS}
    print(f"反空洞自证：把 {len(PROOFS)} 个历史缺陷逐个打回去，看对应检查是否响")
    vacuous = []
    for code, mutate in PROOFS.items():
        mutated = mutate(html)
        if mutated == html:
            vacuous.append((code, "缺陷没打回去（锚点对不上），这条自证是空的"))
            continue
        fired = bool(by_code[code](mutated))
        print(f"  {'✓' if fired else '✗'} {code} {'响' if fired else '没响'}")
        if not fired:
            vacuous.append((code, "把缺陷打回去之后检查仍然通过 —— 这条检查抓不住它"))
    if vacuous:
        print("\n✗ 有检查是空洞的：")
        for code, why in vacuous:
            print(f"   {code}: {why}")
        return 1
    print(f"\n✓ {len(PROOFS)} 条检查都能被对应的缺陷触发（没有一条是永远不会失败的判据）")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--template", default=str(DEFAULT_TEMPLATE))
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--prove", action="store_true")
    args = ap.parse_args()

    if args.prove:
        return prove()

    path = Path(args.template)
    if not path.is_file():
        print(f"✗ no template at {path}", file=sys.stderr)
        return 2

    report = check_template(path)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"审阅页模板静态检查：{path}")
        for r in report["checks"]:
            if r["ok"]:
                print(f"  ✓ {r['code']} {r['title']}")
            else:
                print(f"  ✗ {r['code']} {r['title']}")
                for f in r["findings"]:
                    print(f"      · {f}")
        print(f"\n{report['failed']} 项不通过")
    return 1 if report["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
