#!/usr/bin/env python3
"""Static hygiene & link-integrity guardrails for video-craft.

Fails if:
1. Any non-test .py/.md/.html/.json file cites `helpers/<name>.py` for a module that
   moved into `helpers/_internal/`.
2. Any tracked/shipped doc or test still cites retired files (`upstream-diff.md` or
   `references/implementation-brief.md`) that were pruned in v2.1.
3. Any markdown relative link inside `SKILL.md` / `GLOSSARY.md` / `README.md` /
   `references/*.md` points to a missing local file.
4. Any `.DS_Store` or empty working `edit/` directory sneaks back into the Skill tree.
"""
from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RETIRED_DOCS = ("upstream-diff.md", "implementation-brief.md")
COMPAT_MARKERS = ("兼容", "历史", "只读", "legacy", "存量", "retired", "退役")
RETIRED_TERM_CHECKS = (
    ("recompose.json", "已退役配置文件名"),
    ("production_mode", "已退役互斥模式字段"),
    ("composition/public/step-durations.json", "已退役旧引擎时长默认输出路径"),
)


def _doc_targets(root: Path, *, include_gotchas: bool = True, include_evals: bool = False) -> list[Path]:
    docs = [
        root / "SKILL.md",
        root / "README.md",
        root / "GLOSSARY.md",
        root / "install.md",
    ]
    if include_gotchas:
        docs.append(root / "GOTCHAS.md")
    if include_evals:
        docs.append(root / "evals" / "evals.json")
    docs.extend(sorted((root / "references").glob("*.md")))
    return docs


def find_cross_doc_broken_quotes(root: Path = ROOT) -> list[str]:
    """Return errors where `[doc.md](...)「heading」` does not match a heading in target."""
    heading_re = re.compile(r"^#{1,6}\s+(.+?)\s*$")
    link_quote_re = re.compile(r"\[[^\]]+\]\(([^)#\s]+\.md)(?:#[^)]*)?\)\s*「([^」]+)」")
    broken = []
    for p in _doc_targets(root, include_gotchas=True, include_evals=False):
        if not p.is_file():
            continue
        txt = p.read_text(encoding="utf-8")
        for idx, line in enumerate(txt.splitlines(), 1):
            for m in link_quote_re.finditer(line):
                href, quote = m.group(1), m.group(2)
                target = (p.parent / href).resolve()
                if not target.is_file():
                    broken.append(f"{p.relative_to(root)}:{idx}: missing target {href}")
                    continue
                headings = [
                    hm.group(1)
                    for ln in target.read_text(encoding="utf-8").splitlines()
                    if (hm := heading_re.match(ln))
                ]
                if not any(quote in h for h in headings):
                    broken.append(
                        f"{p.relative_to(root)}:{idx}: {href} 缺少章节「{quote}」"
                    )
    return broken


def find_bare_delivery_md(root: Path = ROOT) -> list[str]:
    """Return hits for bare `delivery.md` (should be `review-and-delivery.md`)."""
    bare_re = re.compile(r"(?<![A-Za-z0-9_-])delivery\.md\b")
    hits = []
    for p in _doc_targets(root, include_gotchas=True, include_evals=True):
        if not p.is_file():
            continue
        for idx, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if bare_re.search(line):
                hits.append(f"{p.relative_to(root)}:{idx}: {line.strip()}")
    return hits


def find_monorepo_path_leaks(root: Path = ROOT) -> list[str]:
    """Return hits for maintainer monorepo paths in shipped docs."""
    leak = "02-skills-library/03-design-delivery/video-craft"
    hits = []
    for p in _doc_targets(root, include_gotchas=True, include_evals=False):
        if not p.is_file():
            continue
        for idx, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if leak in line:
                hits.append(f"{p.relative_to(root)}:{idx}: {line.strip()}")
    return hits


def find_retired_eval_routes(root: Path = ROOT) -> list[str]:
    """Return errors where `evals/evals.json` uses a retired route."""
    retired_routes = {"recompose", "montage"}
    evals_file = root / "evals" / "evals.json"
    if not evals_file.is_file():
        return []
    cases = json.loads(evals_file.read_text(encoding="utf-8"))
    return [
        f"evals[{idx}] ({c.get('id')}): retired route={c.get('route')!r}"
        for idx, c in enumerate(cases)
        if isinstance(c, dict) and c.get("route") in retired_routes
    ]


def find_false_scribe_ark_fallback(root: Path = ROOT) -> list[str]:
    """Return hits claiming `Scribe -> Ark` auto-fallback."""
    bad_re = re.compile(r"Scribe\s*(?:→|->)\s*Ark", re.IGNORECASE)
    hits = []
    for p in _doc_targets(root, include_gotchas=True, include_evals=False):
        if not p.is_file():
            continue
        for idx, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if bad_re.search(line):
                hits.append(f"{p.relative_to(root)}:{idx}: {line.strip()}")
    return hits


def find_retired_terms_as_active_defaults(root: Path = ROOT) -> list[str]:
    """Return hits where active docs or evals present retired paths/fields as active defaults."""
    hits = []
    docs = [
        root / "SKILL.md",
        root / "README.md",
        root / "install.md",
        root / "evals" / "evals.json",
        *[
            p for p in sorted((root / "references").glob("*.md"))
            if p.name != "gotchas-index.md"
        ],
    ]
    for p in docs:
        if not p.is_file():
            continue
        for idx, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            low = line.lower()
            if any(m in line or m in low for m in COMPAT_MARKERS):
                continue
            for token, desc in RETIRED_TERM_CHECKS:
                if token in line:
                    hits.append(f"{p.relative_to(root)}:{idx}: {desc} `{token}` -> {line.strip()}")
    return hits


class SkillRepoHygieneTests(unittest.TestCase):
    def test_no_stale_internal_helper_references(self):
        pub = {p.name for p in (ROOT / "helpers").glob("*.py")}
        internal = {p.name for p in (ROOT / "helpers" / "_internal").glob("*.py")}
        pat = re.compile(r"(?<!_internal/)helpers/([A-Za-z0-9_]+\.py)\b")
        hits = []
        for p in sorted(ROOT.rglob("*")):
            if not p.is_file() or any(x in p.parts for x in ("__pycache__", "node_modules", ".git", "tests")):
                continue
            if p.suffix.lower() not in (".py", ".md", ".html", ".json"):
                continue
            if "docs" in p.parts and "specs" in p.parts:
                continue
            txt = p.read_text(encoding="utf-8", errors="ignore")
            for idx, line in enumerate(txt.splitlines(), 1):
                for m in pat.finditer(line):
                    name = m.group(1)
                    if name not in pub and name in internal:
                        hits.append(f"{p.relative_to(ROOT)}:{idx}: helpers/{name}")
        self.assertEqual(hits, [], f"发现过期内部脚本路径引用：\n" + "\n".join(hits))

    def test_no_retired_clutter_files_or_dangling_links(self):
        for retired in ("upstream-diff.md", "references/implementation-brief.md"):
            self.assertFalse((ROOT / retired).exists(), f"已清理历史文档不应再存在: {retired}")
        self.assertFalse((ROOT / "edit").exists(), "Skill 目录内不应残留空工作目录 edit/")
        ds_stores = [str(p.relative_to(ROOT)) for p in ROOT.rglob(".DS_Store") if ".git" not in p.parts]
        self.assertEqual(ds_stores, [], f"Skill 目录内存在 .DS_Store: {ds_stores}")

        dangling = []
        for p in sorted([ROOT / "SKILL.md", ROOT / "GLOSSARY.md", ROOT / "README.md", *sorted((ROOT / "references").glob("*.md"))]):
            if not p.is_file():
                continue
            txt = p.read_text(encoding="utf-8")
            for retired in RETIRED_DOCS:
                if retired in txt:
                    dangling.append(f"{p.relative_to(ROOT)} still mentions {retired}")
            for m in re.finditer(r"\[[^\]]+\]\(([^)#\s]+)(?:#[^)]*)?\)", txt):
                href = m.group(1)
                if href.startswith(("http://", "https://", "mailto:", "file://")):
                    continue
                target = (p.parent / href).resolve()
                if not target.exists():
                    dangling.append(f"{p.relative_to(ROOT)} broken link -> {href}")
        self.assertEqual(dangling, [], "\n".join(dangling))

    def test_cross_doc_section_quotes_resolve(self):
        """跨文档 `[doc.md](...)「小节标题」` 引用必须在目标文档标题中真实存在。"""
        broken = find_cross_doc_broken_quotes(ROOT)
        self.assertEqual(broken, [], "\n".join(broken))

    def test_no_bare_delivery_md_in_shipped_docs(self):
        """现行分发文档与评估用例不得引用已更名/不存在的裸 `delivery.md`（应为 `review-and-delivery.md`）。"""
        hits = find_bare_delivery_md(ROOT)
        self.assertEqual(hits, [], "\n".join(hits))

    def test_no_local_monorepo_path_leak(self):
        """主入口、分发说明与参考手册不得泄露维护者本机父级单仓路径。"""
        hits = find_monorepo_path_leaks(ROOT)
        self.assertEqual(hits, [], "\n".join(hits))

    def test_evals_no_retired_routes(self):
        """evals/evals.json 不得再使用已退役的 route 枚举（recompose / montage）。"""
        hits = find_retired_eval_routes(ROOT)
        self.assertEqual(hits, [], "\n".join(hits))

    def test_no_false_scribe_ark_mlx_autofallback(self):
        """文档不得声称 `transcribe.py --backend auto` 会自动回退到 Ark（仅限显式传参）。"""
        hits = find_false_scribe_ark_fallback(ROOT)
        self.assertEqual(hits, [], "\n".join(hits))

    def test_no_retired_terms_as_active_defaults(self):
        """现行参考文档、SKILL.md 与 evals.json 不得把已退役路径/字段写成默认主路径（显式标注历史只读兼容的除外）。"""
        hits = find_retired_terms_as_active_defaults(ROOT)
        self.assertEqual(hits, [], "\n".join(hits))

    def test_negative_fixtures_catch_all_hygiene_violations(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "references").mkdir()
            (root / "evals").mkdir()
            (root / "references" / "target.md").write_text("# Target\n\n## Real Section\n", encoding="utf-8")
            (root / "SKILL.md").write_text(
                "见 [target](references/target.md)「Missing Section」\n"
                "参考 delivery.md\n"
                "路径 02-skills-library/03-design-delivery/video-craft\n"
                "默认写入 recompose.json\n",
                encoding="utf-8",
            )
            (root / "README.md").write_text("自动回退 Scribe → Ark → mlx\n", encoding="utf-8")
            (root / "evals" / "evals.json").write_text(
                json.dumps([{"id": "bad", "route": "recompose", "prompt": "使用 production_mode"}]),
                encoding="utf-8",
            )

            self.assertEqual(len(find_cross_doc_broken_quotes(root)), 1)
            self.assertEqual(len(find_bare_delivery_md(root)), 1)
            self.assertEqual(len(find_monorepo_path_leaks(root)), 1)
            self.assertEqual(len(find_retired_eval_routes(root)), 1)
            self.assertEqual(len(find_false_scribe_ark_fallback(root)), 1)
            retired_hits = find_retired_terms_as_active_defaults(root)
            self.assertEqual(len(retired_hits), 2, retired_hits)


if __name__ == "__main__":
    unittest.main()
