#!/usr/bin/env python3
"""两层规范的结构护栏。

规范分两层、两个文件：
- author-spec.md：跨风格都成立的全局判准（G 条目）
- style-spec.md：某一种风格的动效规则（S 条目，按风格 slug 分节）

路线只有一个（recompose），不作为规范维度。

这条命令只挡机械项，不判断规则对不对——语义冲突仍然要人裁决。

检查项：
1. 条目数：全局 ≤ 8；每种风格 ≤ 5；两个文件合计 ≤ 25
2. 篇幅：author-spec ≤ 110 行
3. 字段齐全：每条必须有 做法 / 证据 / 执行
4. 执行点解析：`check:` 指向的路径必须存在；`judgment:` 必须写具体看什么
5. 编号唯一：G / S 条目编号不重复
6. slug 枚举：风格节名必须是已知 slug（新增是一次架构决定）

用法：
    python3 helpers/spec_lint.py [--json] [--spec-dir <目录>]

退出码：0 无问题 · 1 有问题 · 2 文件缺失
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SPEC_DIR = SKILL_ROOT / "references"

AUTHOR_SPEC = "author-spec.md"
STYLE_SPEC = "style-spec.md"
SPEC_FILES = (AUTHOR_SPEC, STYLE_SPEC)

MAX_AUTHOR_ENTRIES = 8
MAX_AUTHOR_LINES = 110
MAX_PER_STYLE = 5
MAX_TOTAL_ENTRIES = 25
MAX_ENTRY_BODY_LINES = 9

STYLE_SLUGS = ("line-art", "business-report", "collage")

AUTHOR_ENTRY_RE = re.compile(r"^##\s+(G\d{2})\s+(.+?)\s*$")
SECTION_RE = re.compile(r"^##\s+([a-z][a-z0-9-]+)\s*(?:·\s*(.+?))?\s*$")
STYLE_ENTRY_RE = re.compile(r"^###\s+(S\d{2})\s+(.+?)\s*$")
FIELD_RE = re.compile(r"^-\s*(做法|证据|执行)\s*[：:]\s*(.+?)\s*$")
CHECK_PREFIXES = ("check:", "judgment:")


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
    problems = [f"{entry_id} 缺字段：{name}" for name in ("做法", "证据", "执行") if name not in fields]
    if "执行" in fields:
        problems += [f"{entry_id} {p}" for p in _check_enforcement(fields["执行"], skill_root)]
    body_lines = [ln for ln in body if ln.strip()]
    if len(body_lines) > MAX_ENTRY_BODY_LINES:
        problems.append(f"{entry_id} 正文 {len(body_lines)} 行，超过 {MAX_ENTRY_BODY_LINES} 行上限")
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
    author_entries = _iter_entries(text[AUTHOR_SPEC], AUTHOR_ENTRY_RE)
    if len(author_entries) > MAX_AUTHOR_ENTRIES:
        problems.append(f"{AUTHOR_SPEC} 有 {len(author_entries)} 条，超过 {MAX_AUTHOR_ENTRIES} 条上限")
    for entry_id, _title, body in author_entries:
        if entry_id in ids:
            problems.append(f"重复条目编号：{entry_id}")
        ids.add(entry_id)
        problems += _entry_problems(entry_id, body, skill_root)

    style_lines = text[STYLE_SPEC]
    sections = []
    for i, line in enumerate(style_lines):
        m = SECTION_RE.match(line)
        if m and not line.startswith("### "):
            sections.append((i, m.group(1)))
    style_total = 0
    for idx, (start, slug) in enumerate(sections):
        end = sections[idx + 1][0] if idx + 1 < len(sections) else len(style_lines)
        if slug not in STYLE_SLUGS:
            problems.append(f"{STYLE_SPEC} 未知风格节：{slug!r}（已知：{', '.join(STYLE_SLUGS)}）")
            continue
        entries = _iter_entries(style_lines[start:end], STYLE_ENTRY_RE)
        style_total += len(entries)
        if not entries:
            problems.append(f"{STYLE_SPEC} 风格 {slug} 没有任何条目")
        if len(entries) > MAX_PER_STYLE:
            problems.append(f"{STYLE_SPEC} 风格 {slug} 有 {len(entries)} 条，超过 {MAX_PER_STYLE} 条上限")
        for entry_id, _title, body in entries:
            if entry_id in ids:
                problems.append(f"重复条目编号：{entry_id}")
            ids.add(entry_id)
            problems += _entry_problems(entry_id, body, skill_root)

    total = len(author_entries) + style_total
    if total > MAX_TOTAL_ENTRIES:
        problems.append(f"两个文件合计 {total} 条，超过 {MAX_TOTAL_ENTRIES} 条上限")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="检查 author-spec / style-spec 的结构与上限")
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
