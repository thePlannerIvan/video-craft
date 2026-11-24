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

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RETIRED_DOCS = ("upstream-diff.md", "implementation-brief.md")


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


if __name__ == "__main__":
    unittest.main()
