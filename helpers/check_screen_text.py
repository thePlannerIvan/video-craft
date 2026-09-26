#!/usr/bin/env python3
"""On-screen text is read by the audience — process words must never reach it.

Why this exists
---------------
Two rounds of review on 2026-09-21 were spent deleting text that described *how
the film was made* rather than what the viewer is looking at: a caption reading
`10× 加速 · 中段停一下`, a label `同一句标题：…` that was a note to self, and a
top-left line that repeated the author's own conclusion. Each one shipped inside
a designed screen and had to be re-rendered. The rule is simple and cheap to
check: the picture carries content, never production method.

This gate collects every string that will actually be drawn on screen, prints
them as one list for a human pass, and fails on the words that are a defect in
**any** style. It checks what got rendered against what upstream declared; it
does **not** own the declaration.

Usage
-----
    check_screen_text.py <project_or_edit_dir> [--plan visual-plan.json]
                         [--caption TEXT ...] [--ban WORD ...] [--allow WORD ...]
    check_screen_text.py <project_or_edit_dir> --json

Rendered sources
----------------
  * `<dir>/visual/**/*.html`                 — composition text nodes
  * `<dir>/*.html`                           — the same, at project root
  * `<dir>/_internal/02_svg_source/**/*.svg` — 做画面 gives the video route its
    pictures here. Before this directory was scanned, a project whose pictures
    all came from there got a green light while nothing was checked.
  * `--caption`                              — PIL 花字 passed on the command line

Declaration (`--plan`, read-only)
---------------------------------
The upstream content contract owns the declaration of on-screen text and 花字:
`screens[].sample.captions[]` (the 花字 layer); `must_show[]` entries marked
「文字：」; and **every** `exact_labels[]` entry — the contract defines that field
as "必须原样出现的标题、指标、数字、术语", so it is literal whole and needs no
marker. Declared strings meet the same rules as rendered ones. There is no second
declaration channel on this side.

Blocking vs reporting
---------------------
A gate blocks only what is a defect in **any** style. Engineering jargon, tool
names, placeholders and the artifact-form `beat` are; `样张 / 预览 / 草稿 / 审阅 /
缺口` are not — they are ordinary vocabulary in printing, software, writing,
editorial and business subjects, and no pattern separates the senses. Those five
are reported in their own section and never affect the exit status. The same goes
for the declared-versus-rendered diff: text can be produced at runtime, so the
difference is information for the human pass, never a failure.

Process material
----------------
Review surfaces are process material, not screens, and are skipped — every skip
is printed and also listed under `--json` so the exclusion stays auditable. They
are recognised by **structure, never by upstream names** (upstream is being
renamed and merged; a hardcoded directory or artifact name would silently stop
matching): a `.process-material` marker file in the directory or an ancestor, a
page that declares itself with `data-process-material`, or a page that hands
feedback back to a server (`/api/feedback`, `/api/save`) — a rendered screen
never does that.

Exit code 1 only when a blocking word appears. "待补拍/需新做" style placeholders
belong in review material, not in a rendered screen, so they are blocking too.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path


def _pattern(word: str) -> str:
    """ASCII 词按词界匹配，中文词按字面。

    Substring matching let `EDL` fire inside `MEDLEY` and `HF` inside `HFR`;
    a boundary keeps the ban on the word and off ordinary prose.
    """
    if word.isascii():
        return rf"(?<![A-Za-z0-9]){re.escape(word)}(?![A-Za-z0-9])"
    return re.escape(word)


# 画面只放内容，不放「制作过程的话」——这张表是本闸门自己的判定依据。
# 上游把某个产物改叫什么，与本表无关：一条规则说的是「这句话在讲怎么做的」，
# 不是「上游管它叫这个名字」。所以它既不会被改名悄悄关掉，也不替上游背书。
BLOCKING_RULES: list[tuple[str, str, str]] = [
    # (报告用的词, 匹配式, 为什么算工程话)
    ("加速", _pattern("加速"), "剪辑手法"),
    ("倍速", _pattern("倍速"), "剪辑手法"),
    ("静帧", _pattern("静帧"), "剪辑手法"),
    ("停顿", _pattern("停顿"), "剪辑手法"),
    ("裁切", _pattern("裁切"), "剪辑手法"),
    ("帧率", _pattern("帧率"), "规格参数"),
    ("时间码", _pattern("时间码"), "工程记号"),
    ("转写", _pattern("转写"), "工作流"),
    ("待补拍", _pattern("待补拍"), "占位符"),
    ("需新做", _pattern("需新做"), "占位符"),
    ("HyperFrames", _pattern("HyperFrames"), "工具名"),
    ("EDL", _pattern("EDL"), "工具缩写"),
    ("SRT", _pattern("SRT"), "工具缩写"),
    ("HF", _pattern("HF"), "工具缩写"),
    ("TODO", _pattern("TODO"), "占位符"),
    # `beat` 单独一个词是普通英文（音乐、节奏、beat the odds），禁它会误伤；
    # 该禁的是上游那份编号（`beat-01` / `BEAT 3`），所以只禁编号形态。
    ("beat-NN", r"(?<![A-Za-z0-9])beat[-_ ]?\d", "Beat 编号"),
]

# 只报不拦：这五个词在别的题材里是正当代词 —— 印刷样张、软件预览、写作草稿、
# 编辑审阅、市场缺口。没有任何匹配式能把这两种意思分开，所以它们进报告、不进
# 判定：闸门只拦「在任何风格里都是缺陷」的东西。要安静，用 `--allow`。
ADVISORY_RULES: list[tuple[str, str, str]] = [
    ("样张", _pattern("样张"), "工作流"),
    ("预览", _pattern("预览"), "工作流"),
    ("草稿", _pattern("草稿"), "工作流"),
    ("审阅", _pattern("审阅"), "工作流"),
    ("缺口", _pattern("缺口"), "占位符"),
]

TAG = re.compile(r"<[^>]+>")
# script/style are code; `<head>` (meta, `<title>`) is document identity. The
# `<title>` 「满屏真实评论 · 样张」 was reported as on-screen 「样张」 on 2026-09-25.
SKIP = re.compile(r"<(script|style)\b.*?</\1>", re.S | re.I)
HEAD = re.compile(r"<head\b.*?</head>", re.S | re.I)
# SVG `<title>`/`<desc>` are hover text and accessibility notes, not pixels.
SVG_META = re.compile(r"<(title|desc)\b.*?</\1>", re.S | re.I)

# 过程材料的结构标记：任一条命中即跳过。认出的是「这一页会做什么」，不是名字。
PROCESS_MARKER = ".process-material"
SELF_MARK = re.compile(r"<!--\s*process-material\s*-->|data-process-material", re.I)
# 审阅页会把作者反馈交给宿主，画面不会 —— 这是本 skill 自己已经在用的判据。
# 三种形状都算审阅页，旧的那两种留着认历史产物：
#   · `{{REVIEW_BRIDGE}}` —— 现在的审阅页：留一个注入点，由 planners-review-core 的宿主
#     在 serve 时换成桥（`visual_review_feedback.py` 的守卫也认它）
#   · `/__review/` —— 桥连上之后的说话路径
#   · `/api/feedback`、`/api/save` —— 直存时代自己 POST 的副本（服务已退役）
FEEDBACK_ENDPOINTS = ("{{REVIEW_BRIDGE}}", "/__review/", "/api/feedback", "/api/save")

# 做画面那一步把画面写成这里的 SVG；视频路线的画面只能从这里来。
SVG_SOURCE_DIR = ("_internal", "02_svg_source")

# `must_show` 里用这个前缀标出「这一条是要原样上屏的字」；没标的只是在说画面要
# 表达什么。`exact_labels` 不用这个前缀 —— 它整条就是字。
TEXT_MARKS = ("文字：", "文字:")


def _text_nodes(raw: str) -> list[str]:
    """Text nodes between tags, code and document identity already stripped."""
    out = []
    for chunk in TAG.split(raw):
        t = html.unescape(chunk).strip()
        t = re.sub(r"\s+", " ", t)
        if t and not t.startswith(("{", "}", "//")):
            out.append(t)
    return out


def html_text_nodes(raw: str) -> list[str]:
    return _text_nodes(SKIP.sub(" ", HEAD.sub(" ", raw)))


def svg_text_nodes(raw: str) -> list[str]:
    """SVG 里真正会画出来的字。"""
    return _text_nodes(SKIP.sub(" ", SVG_META.sub(" ", raw)))


def process_material(path: Path, root: Path, body: str) -> str | None:
    """Why `path` is process material rather than a rendered screen."""
    d = path.parent
    while True:
        if (d / PROCESS_MARKER).exists():
            return f"过程材料标记（{PROCESS_MARKER}）"
        if d == root or d.parent == d:
            break
        d = d.parent
    if SELF_MARK.search(body):
        return "页面自述为过程材料"
    for endpoint in FEEDBACK_ENDPOINTS:
        if endpoint in body:
            return f"审阅页（会把反馈回传 {endpoint}）"
    return None


def plan_declarations(plan: Path) -> list[tuple[str, str]]:
    """The upstream declaration, read-only: `(来源, 字)` pairs.

    `screens[].sample.captions[]` is the 花字 layer; `must_show[]` carries literal
    text only when marked 「文字：」 (unmarked entries describe what the picture
    must express); `exact_labels[]` is literal whole — every entry is a title,
    metric, number or term that must appear verbatim.
    """
    data = json.loads(plan.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("screens"), list):
        raise ValueError("不是 visual-plan 契约（缺 screens[]）")
    out: list[tuple[str, str]] = []
    for i, screen in enumerate(data["screens"]):
        if not isinstance(screen, dict):
            continue
        sid = str(screen.get("screen_id") or screen.get("beat_id") or f"#{i + 1}")
        sample = screen.get("sample") if isinstance(screen.get("sample"), dict) else {}
        captions = sample.get("captions") if isinstance(sample.get("captions"), list) else []
        for t in captions:
            out.append((f"{plan.name}:{sid}/花字", str(t).strip()))
        for item in screen.get("must_show") or []:
            text = str(item)
            for mark in TEXT_MARKS:
                if text.startswith(mark):
                    out.append((f"{plan.name}:{sid}/must_show", text[len(mark):].strip()))
                    break
        for item in screen.get("exact_labels") or []:
            text = str(item).strip()
            for mark in TEXT_MARKS:      # 旧写法多带一个标记时去掉，它本身不是字
                if text.startswith(mark):
                    text = text[len(mark):].strip()
                    break
            out.append((f"{plan.name}:{sid}/exact_labels", text))
    return [(s, t) for s, t in out if t]


def _same_text(a: str, b: str) -> bool:
    """A declared string may be split across text nodes/tspans, so containment counts."""
    return bool(a) and bool(b) and (a in b or b in a)


def declaration_diff(rendered: list[tuple[str, str]],
                     declared: list[tuple[str, str]]) -> tuple[list[tuple[str, str]],
                                                              list[tuple[str, str]]]:
    """(声明了但画面上找不到, 画面上有但声明里没有) —— 只报不拦。"""
    missing = [(s, t) for s, t in declared
               if not any(_same_text(t, r) for _, r in rendered)]
    extra = [(s, t) for s, t in rendered
             if not any(_same_text(t, d) for _, d in declared)]
    return missing, extra


def compile_advisory() -> list[tuple[str, re.Pattern, str]]:
    """只报不拦那一节的匹配式；`--allow` 只管判定，不管报告。"""
    return [(label, re.compile(rx, re.I), why) for label, rx, why in ADVISORY_RULES]


def compile_rules(extra: list[str], allow: list[str]) -> list[tuple[str, re.Pattern, str]]:
    allowed = {w.lower() for w in allow}
    rules = [(label, re.compile(rx, re.I), why) for label, rx, why in BLOCKING_RULES
             if label.lower() not in allowed]
    for word in extra:
        if word.lower() in allowed:
            continue
        rules.append((word, re.compile(_pattern(word), re.I), "调用方加禁（--ban）"))
    return rules


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--plan", type=Path, default=None,
                    help="上游声明：<项目>/deliverable/visual-plan.json（sample.captions[] 是花字层）")
    ap.add_argument("--caption", action="append", default=[])
    ap.add_argument("--ban", action="append", default=[])
    ap.add_argument("--allow", action="append", default=[],
                    help="内容确实会合法出现这个词时放行；每次放行都会打印")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    root = Path(a.path)
    if not root.exists():
        print(f"not found: {root}", file=sys.stderr)
        return 2
    if a.plan and not a.plan.exists():
        print(f"not found: {a.plan}", file=sys.stderr)
        return 2

    rules = compile_rules(a.ban, a.allow)
    advisory = compile_advisory()

    html_files = sorted(list(root.glob("visual/**/*.html")) + list(root.glob("*.html")))
    svg_files = sorted(root.joinpath(*SVG_SOURCE_DIR).glob("**/*.svg"))

    surface: list[tuple[str, str]] = []        # (source, text) — 真的会画出来的字
    skipped: list[tuple[str, str]] = []        # (path, reason)
    for path in html_files + svg_files:
        body = path.read_text(encoding="utf-8", errors="ignore")
        reason = process_material(path, root, body)
        if reason:
            skipped.append((str(path), reason))
            continue
        if path.name == "index.html" and "Hello World" in body:
            skipped.append((str(path), "还是脚手架"))
            continue
        nodes = svg_text_nodes(body) if path.suffix == ".svg" else html_text_nodes(body)
        for t in nodes:
            surface.append((path.name, t))

    declared: list[tuple[str, str]] = []
    if a.plan:
        try:
            declared = plan_declarations(a.plan)
        except Exception as exc:                # noqa: BLE001
            print(f"读不了声明 {a.plan}: {exc}", file=sys.stderr)
            return 2
    captions = [("--caption", t) for t in a.caption]
    rendered = surface + captions
    found = surface + declared + captions

    bad = [(s, t, label, why) for s, t in found
           for label, rx, why in rules if rx.search(t)]
    advisories = [(s, t, label, why) for s, t in found
                  for label, rx, why in advisory if rx.search(t)]
    diff = declaration_diff(rendered, declared) if declared else None

    if a.json:
        print(json.dumps({"surface": {"html": [str(p) for p in html_files],
                                      "svg": [str(p) for p in svg_files]},
                          "strings": [{"source": s, "text": t} for s, t in found],
                          "skipped": [{"file": f, "reason": r} for f, r in skipped],
                          "banned_hits": [{"source": s, "text": t, "word": w, "why": y}
                                          for s, t, w, y in bad],
                          "advisory_hits": [{"source": s, "text": t, "word": w, "why": y}
                                            for s, t, w, y in advisories],
                          "declaration_diff": None if diff is None else {
                              "declared_not_rendered": [{"source": s, "text": t}
                                                        for s, t in diff[0]],
                              "rendered_not_declared": [{"source": s, "text": t}
                                                        for s, t in diff[1]]}},
                         ensure_ascii=False, indent=2))
    else:
        # Printed, not silent: a structural exclusion nobody can see is how a
        # real deliverable gets skipped without anyone noticing.
        for f, r in skipped:
            print(f"  · 跳过 {f}（{r}）")
        for w in a.allow:
            print(f"  · 放行「{w}」（--allow）")
        print(f"扫描面：{len(html_files)} 个 HTML · {len(svg_files)} 个 SVG"
              + (f" · 声明 {a.plan.name}" if a.plan else " · 未给 --plan，只查渲染侧"))
        print(f"上屏文字体检：{len(found)} 条（{len({s for s, _ in found})} 个来源）")
        for s, t in found:
            print(f"  [{s}] {t[:70]}")
        for s, t, w, why in bad:
            print(f"  ✗ [{s}] 出现工程话「{w}」（{why}）：{t[:60]}")
        if advisories:
            print(f"只报不拦（{len(advisories)} 处；这五个词在别的题材里是正当代词，不判对错）：")
            for s, t, w, why in advisories:
                print(f"  · [{s}] 出现「{w}」（{why}）：{t[:60]}")
        if diff is not None:
            missing, extra = diff
            print(f"声明比对（只报不拦）：声明 {len(declared)} 条 · 渲染 {len(rendered)} 条")
            for s, t in missing:
                print(f"  · 声明了但画面上找不到 [{s}] {t[:60]}")
            for s, t in extra:
                print(f"  · 画面上有但声明里没有 [{s}] {t[:60]}")
        print("RESULT:", "OK" if not bad else f"FAIL（{len(bad)} 处工程话）")
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
