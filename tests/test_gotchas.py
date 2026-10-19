#!/usr/bin/env python3
"""A gotcha without an enforcement point is a no-op.

2026-10 audit: 74 entries, 46 with no check/test/env pointer. The four that this
project's own session re-stepped (#41/#52/#69/#70) all had text but no execution
point. This test freezes the list: every entry names where it is enforced, the
pointer resolves, and the total cannot grow while entries still lack mechanisms.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
GOTCHAS = ROOT / "GOTCHAS.md"
HISTORY = ROOT / "references" / "maintenance-history.md"
MAX_GOTCHAS = 40  # 2026-10-19: 74 → 51 (retire upgraded) → 40 (merge same-root)
PREFIXES = ("test", "check", "env", "judgment")


def entries():
    text = GOTCHAS.read_text(encoding="utf-8")
    pat = re.compile(r"(?m)^##+\s+(\d+)\.\s+([^\n]*)\n")
    ms = list(pat.finditer(text))
    out = []
    for i, m in enumerate(ms):
        end = ms[i + 1].start() if i + 1 < len(ms) else len(text)
        out.append((int(m.group(1)), text[m.start():end]))
    return out


class GotchaEnforcement(unittest.TestCase):
    def test_every_entry_has_an_enforcement_pointer(self):
        missing = [n for n, body in entries() if "- **enforcement**：" not in body]
        self.assertEqual(missing, [], f"缺 enforcement 的条目：{missing}")

    def test_enforcement_pointer_resolves(self):
        broken = []
        for n, body in entries():
            m = re.search(r"- \*\*enforcement\*\*：(\S+)", body)
            self.assertIsNotNone(m, f"#{n} enforcement 格式不对")
            value = m.group(1)
            prefix, _, target = value.partition(":")
            self.assertIn(prefix, PREFIXES, f"#{n} 未知前缀 {prefix}")
            path = ROOT / target.split("#")[0]
            if not path.exists():
                broken.append((n, target))
        self.assertEqual(broken, [], f"enforcement 指向不存在的文件：{broken}")

    def test_entry_numbers_unique(self):
        nums = [n for n, _ in entries()]
        self.assertEqual(len(nums), len(set(nums)))

    def test_retired_numbers_are_indexed(self):
        hist = HISTORY.read_text(encoding="utf-8")
        kept = {n for n, _ in entries()}
        # Anything that used to exist and is no longer in the body must appear in
        # the migration index (this catches silent deletion).
        self.assertIn("GOTCHAS 迁移索引（2026-10-19）", hist)
        for n in range(1, 75):
            if n not in kept:
                self.assertIn(f"#{n} ", hist, f"#{n} 既不在正文也不在迁移索引")

    def test_cap_is_frozen(self):
        self.assertLessEqual(len(entries()), MAX_GOTCHAS,
                             f"GOTCHAS 超过上限 {MAX_GOTCHAS}：先合并或移到迁移索引，再加新的")


if __name__ == "__main__":
    unittest.main()
