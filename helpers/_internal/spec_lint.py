#!/usr/bin/env python3
"""Style Card v3 与全局底线规范的结构护栏。

规范分两层、两个文件：
- author-spec.md：跨风格都成立的全局视觉底线（G01–G05）与口播底线（V01–V05）
- style-spec.md：六套风格的开源单卡基准（风格领词（Style Leading Words）、镜头与声画语法、高频防线 0–4 条）

检查项：
1. 全局底线：G01–G05 ≤ 5 条、V01–V05 ≤ 5 条，author-spec ≤ 90 行
2. 全局字段与指针：每条须含 做法 / 执行；`check:` 路径必须存在，`judgment:` 不能为空
3. 编号唯一：G / V 条目编号不重复且属于 G01..G05 / V01..V05
4. 六套风格节校验：slug 必须属于六套标准风格，每套 ≤ 45 行，必含 风格领词（Style Leading Words）（3–5 条）、镜头与声画语法（≥1 条）、高频防线（0–4 条）
5. 卫生禁令：author-spec / style-spec / preferences 不得出现单路线口径、裸写 Leading Words 或硬编码 1920x1080 版式规则

用法：
    python3 helpers/_internal/spec_lint.py [--json] [--spec-dir <目录>]

退出码：0 无问题 · 1 有问题 · 2 文件缺失
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SPEC_DIR = SKILL_ROOT / "references"

AUTHOR_SPEC = "author-spec.md"
STYLE_SPEC = "style-spec.md"
SPEC_FILES = (AUTHOR_SPEC, STYLE_SPEC)

MAX_AUTHOR_G_ENTRIES = 5
MAX_AUTHOR_V_ENTRIES = 5
MAX_AUTHOR_LINES = 90
MAX_STYLE_LINES = 45
MIN_LEADING_WORDS = 3
MAX_LEADING_WORDS = 5
MAX_STYLE_GUARDRAILS = 4
MAX_ENTRY_BODY_LINES = 9

STYLE_SLUGS = (
    "line-art",
    "business-report",
    "collage",
    "concept-film",
    "lifestyle-cult",
    "studio-motion-ui",
)

ROUTE_TEXT_FILES = (AUTHOR_SPEC, STYLE_SPEC, "preferences.md")
SINGLE_ROUTE_RES = (
    re.compile(r"路线只有\s*(?:一[条个]|recompose)"),
    re.compile(r"只有\s*recompose\s*一[条个]"),
    re.compile(r"只有\s*一[条个]\s*路线"),
)
BARE_LEADING_WORDS_RE = re.compile(r"(?<!Style\s)Leading\s+Words", re.IGNORECASE)
HARDCODED_1080P_RE = re.compile(r"1920\s*[x×]\s*1080")

AUTHOR_G_RE = re.compile(r"^#{2,3}\s+(G\d{2})\s+(.+?)\s*$")
AUTHOR_V_RE = re.compile(r"^#{2,3}\s+(V\d{2})\s+(.+?)\s*$")
AUTHOR_ANY_RE = re.compile(r"^#{2,3}\s+([GV]\d{2})\s+(.+?)\s*$")
SECTION_RE = re.compile(r"^##\s+([a-z][a-z0-9-]+)\s*(?:·\s*(.+?))?\s*$")
SUBSECTION_RE = re.compile(r"^###\s+(.+?)\s*$")
FIELD_RE = re.compile(r"^-\s*(做法|证据|执行)\s*[：:]\s*(.+?)\s*$")
CHECK_PREFIXES = ("check:", "judgment:")

VALID_G_IDS = {f"G{i:02d}" for i in range(1, 6)}
VALID_V_IDS = {f"V{i:02d}" for i in range(1, 6)}


def _split_enforcement(value: str) -> list[str]:
    return [p.strip() for p in re.split(r"[；;]", value) if p.strip()]


def _check_enforcement(value: str, skill_root: Path) -> list[str]:
    problems: list[str] = []
    parts = _split_enforcement(value)
    if not parts:
        return ["执行点为空"]
    for part in parts:
        prefix = next((p for p in CHECK_PREFIXES if part.startswith(p)), None)
        if prefix is None:
            problems.append(f"执行点缺少 check:/judgment: 前缀：{part!r}")
            continue
        target = part[len(prefix):].strip()
        if not target:
            problems.append(f"执行点没有内容：{prefix}")
            continue
        if prefix == "check:":
            path = skill_root / target.split()[0]
            if not path.exists():
                problems.append(f"check: 指向的路径不存在：{target}")
    return problems


def _iter_entries(lines: list[str], entry_re: re.Pattern[str]) -> list[tuple[str, str, list[str]]]:
    marks = [(i, m) for i, line in enumerate(lines) if (m := entry_re.match(line))]
    out: list[tuple[str, str, list[str]]] = []
    for idx, (i, m) in enumerate(marks):
        end = marks[idx + 1][0] if idx + 1 < len(marks) else len(lines)
        block = lines[i + 1:end]
        for j, line in enumerate(block):
            if line.startswith("## ") and not line.startswith("### "):
                block = block[:j]
                break
        out.append((m.group(1), m.group(2), block))
    return out


def _entry_problems(entry_id: str, body: list[str], skill_root: Path) -> list[str]:
    fields: dict[str, str] = {}
    for line in body:
        m = FIELD_RE.match(line.strip())
        if m:
            fields[m.group(1)] = m.group(2)
    problems = [f"{entry_id} 缺字段：{name}" for name in ("做法", "执行") if name not in fields]
    if "执行" in fields:
        problems += [f"{entry_id} {p}" for p in _check_enforcement(fields["执行"], skill_root)]
    body_lines = [ln for ln in body if ln.strip()]
    if len(body_lines) > MAX_ENTRY_BODY_LINES:
        problems.append(f"{entry_id} 正文 {len(body_lines)} 行，超过 {MAX_ENTRY_BODY_LINES} 行上限")
    return problems


def _lint_style_section(slug: str, section_lines: list[str]) -> list[str]:
    problems: list[str] = []
    trimmed = list(section_lines)
    while trimmed and not trimmed[-1].strip():
        trimmed.pop()
    if len(trimmed) > MAX_STYLE_LINES:
        problems.append(f"{STYLE_SPEC} 风格 {slug} 共 {len(trimmed)} 行，超过 {MAX_STYLE_LINES} 行上限")

    subs: list[tuple[str, list[str]]] = []
    current_title: str | None = None
    current_body: list[str] = []
    for line in trimmed[1:]:
        m = SUBSECTION_RE.match(line)
        if m:
            if current_title is not None:
                subs.append((current_title, current_body))
            current_title = m.group(1).strip()
            current_body = []
        elif current_title is not None:
            current_body.append(line)
    if current_title is not None:
        subs.append((current_title, current_body))

    def find_sub(predicate) -> list[str] | None:
        for title, body in subs:
            if predicate(title):
                return body
        return None

    leading_body = find_sub(lambda t: "Style Leading Words" in t)
    grammar_body = find_sub(lambda t: t == "镜头与声画语法")
    guard_body = find_sub(lambda t: t == "高频防线")

    if leading_body is None:
        problems.append(f"{STYLE_SPEC} 风格 {slug} 缺少「风格领词（Style Leading Words）」小节")
    else:
        bullets = [ln for ln in leading_body if ln.strip().startswith("- ")]
        if len(bullets) < MIN_LEADING_WORDS or len(bullets) > MAX_LEADING_WORDS:
            problems.append(
                f"{STYLE_SPEC} 风格 {slug} 的风格领词（Style Leading Words）有 {len(bullets)} 条，"
                f"须在 {MIN_LEADING_WORDS}–{MAX_LEADING_WORDS} 条之间"
            )

    if grammar_body is None:
        problems.append(f"{STYLE_SPEC} 风格 {slug} 缺少「镜头与声画语法」小节")
    else:
        bullets = [ln for ln in grammar_body if ln.strip().startswith("- ")]
        if not bullets:
            problems.append(f"{STYLE_SPEC} 风格 {slug} 的「镜头与声画语法」没有任何条目")

    if guard_body is None:
        problems.append(f"{STYLE_SPEC} 风格 {slug} 缺少「高频防线」小节")
    else:
        bullets = [ln for ln in guard_body if ln.strip().startswith("- ")]
        if len(bullets) > MAX_STYLE_GUARDRAILS:
            problems.append(
                f"{STYLE_SPEC} 风格 {slug} 的高频防线有 {len(bullets)} 条，超过 {MAX_STYLE_GUARDRAILS} 条上限"
            )

    return problems


def _wording_hygiene_problems(spec_dir: Path) -> list[str]:
    """挡掉单路线措辞、裸写 Leading Words 与硬编码 1920x1080 版式规则。"""
    problems: list[str] = []
    for name in ROUTE_TEXT_FILES:
        path = spec_dir / name
        if not path.exists():
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if any(pattern.search(line) for pattern in SINGLE_ROUTE_RES):
                problems.append(
                    f"{name}:{lineno} 出现单路线措辞（路线只有一条）；"
                    "应写成正交能力组合 + 画框（frame）"
                )
            if BARE_LEADING_WORDS_RE.search(line):
                problems.append(
                    f"{name}:{lineno} 出现裸写 Leading Words；请写全称 风格领词（Style Leading Words）"
                )
            if HARDCODED_1080P_RE.search(line):
                problems.append(
                    f"{name}:{lineno} 出现硬编码 1920x1080 版式规则；画幅与版式应与 frame 正交解耦"
                )
    return problems


def lint(spec_dir: Path | str | None = None, skill_root: Path | str | None = None) -> list[str]:
    spec_dir = Path(spec_dir) if spec_dir else DEFAULT_SPEC_DIR
    skill_root = Path(skill_root) if skill_root else SKILL_ROOT
    problems: list[str] = []
    for name in SPEC_FILES:
        if not (spec_dir / name).exists():
            problems.append(f"缺少文件：{spec_dir / name}")
    if problems:
        return problems

    text = {name: (spec_dir / name).read_text(encoding="utf-8").splitlines() for name in SPEC_FILES}

    if len(text[AUTHOR_SPEC]) > MAX_AUTHOR_LINES:
        problems.append(f"{AUTHOR_SPEC} 共 {len(text[AUTHOR_SPEC])} 行，超过 {MAX_AUTHOR_LINES} 行上限")

    ids: set[str] = set()
    g_entries = _iter_entries(text[AUTHOR_SPEC], AUTHOR_G_RE)
    v_entries = _iter_entries(text[AUTHOR_SPEC], AUTHOR_V_RE)
    if not g_entries:
        problems.append(f"{AUTHOR_SPEC} 缺少视觉底线条目（G01–G05）")
    if len(g_entries) > MAX_AUTHOR_G_ENTRIES:
        problems.append(f"{AUTHOR_SPEC} 视觉底线有 {len(g_entries)} 条，超过 {MAX_AUTHOR_G_ENTRIES} 条上限")
    if not v_entries:
        problems.append(f"{AUTHOR_SPEC} 缺少口播底线条目（V01–V05）")
    if len(v_entries) > MAX_AUTHOR_V_ENTRIES:
        problems.append(f"{AUTHOR_SPEC} 口播底线有 {len(v_entries)} 条，超过 {MAX_AUTHOR_V_ENTRIES} 条上限")

    for entry_id, _title, body in _iter_entries(text[AUTHOR_SPEC], AUTHOR_ANY_RE):
        if entry_id in ids:
            problems.append(f"重复条目编号：{entry_id}")
        ids.add(entry_id)
        if entry_id.startswith("G") and entry_id not in VALID_G_IDS:
            problems.append(f"视觉底线编号越界：{entry_id}（允许 G01–G05）")
        if entry_id.startswith("V") and entry_id not in VALID_V_IDS:
            problems.append(f"口播底线编号越界：{entry_id}（允许 V01–V05）")
        problems += _entry_problems(entry_id, body, skill_root)

    style_lines = text[STYLE_SPEC]
    sections: list[tuple[int, str]] = []
    for i, line in enumerate(style_lines):
        m = SECTION_RE.match(line)
        if m and not line.startswith("### "):
            sections.append((i, m.group(1)))

    seen_slugs: set[str] = set()
    for idx, (start, slug) in enumerate(sections):
        end = sections[idx + 1][0] if idx + 1 < len(sections) else len(style_lines)
        for j in range(start + 1, end):
            if style_lines[j].startswith("## ") and not SECTION_RE.match(style_lines[j]):
                end = j
                break
        if slug not in STYLE_SLUGS:
            problems.append(f"{STYLE_SPEC} 未知风格节：{slug!r}（已知：{', '.join(STYLE_SLUGS)}）")
            continue
        if slug in seen_slugs:
            problems.append(f"{STYLE_SPEC} 重复风格节：{slug}")
            continue
        seen_slugs.add(slug)
        problems += _lint_style_section(slug, style_lines[start:end])

    if not sections:
        problems.append(f"{STYLE_SPEC} 未定义任何风格节")

    problems += _wording_hygiene_problems(spec_dir)
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="检查 Style Card v3 与全局底线规范（author-spec / style-spec）")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出")
    parser.add_argument("--spec-dir", default=None, help="规范文件所在目录（默认 references/）")
    parser.add_argument("--skill-root", default=None, help="解析 check: 路径的根（默认 Skill 根）")
    args = parser.parse_args(argv)

    spec_dir = Path(args.spec_dir) if args.spec_dir else DEFAULT_SPEC_DIR
    if not spec_dir.exists():
        print(f"spec 目录不存在：{spec_dir}", file=sys.stderr)
        return 2

    problems = lint(spec_dir=spec_dir, skill_root=args.skill_root or SKILL_ROOT)
    missing = any(p.startswith("缺少文件") for p in problems)

    if args.json:
        print(json.dumps({"ok": not problems, "problems": problems}, ensure_ascii=False, indent=2))
    elif problems:
        print("spec 检查未通过：")
        for p in problems:
            print(f"  - {p}")
    else:
        print("spec 检查通过")
    if missing:
        return 2
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
