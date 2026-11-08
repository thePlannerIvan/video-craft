#!/usr/bin/env python3
"""A gotcha without an enforcement point is a no-op.

2026-10 audit: 74 entries, 46 with no check/test/env pointer. The four that this
project's own session re-stepped (#41/#52/#69/#70) all had text but no execution
point. This test freezes the list: every entry names where it is enforced, the
pointer resolves to something that can actually run, and the total cannot grow
while entries still lack mechanisms.

2026-11-08 (H 包): the pointers themselves were the defect. Seventeen entries
pointed at a document that never mentioned their rule; nine pointed at prose with
`env:`/`check:`; four named the wrong tool; eighteen referenced numbers that had
already left the body. So the checks below are stricter than "the file exists":

* `check:` / `test:` / `env:` may **not** point at a `.md` — a document cannot run.
  A rule that only a human can apply must say `judgment:` and must spell out
  **看什么** (what to look at, and what counts as wrong).
* every `#n` (and `第 n 条`) in the prose must resolve to a live entry or to a
  number recorded in `references/maintenance-history.md`'s migration index.
* the heading level is uniform, so "which of these is an entry" is not a guess.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
GOTCHAS = ROOT / "GOTCHAS.md"
HISTORY = ROOT / "references" / "maintenance-history.md"
PREFIXES = ("test", "check", "env", "judgment")
# 2026-10-19: 74 → 51 (retire upgraded) → 40 (merge same-root)
# 2026-10-21: 40 → 42 — 活舞台静默失败（#74）与渲染闸门（#75）各一条，机制是新检查脚本
# 2026-10-23: 42 → 43 — 成片二次剪的字幕重算（#78），机制是新检查 helpers/_cutmap.py
# 2026-11-04: 43 → 44 — 多 worker 渲染丢内容（#79），机制是 check_render_fidelity.py
# 2026-11-08: 44 → 46 — 蒙太奇两关（#80 素材入点坐标 / #81 空镜的像素检查），
#             机制是 helpers/check_montage.py 与 helpers/montage.py plan
# 2026-11-08: 46 → 48 — #22 拆成三条不同根因（#82 管道吞退出码 / #83 `-t` 归属 /
#             #84 `--no-loudnorm` 撞 base 名）：46 - 1 + 3。上限只跟着净增走，不跟着
#             重排走；本轮没有再新增判准。
MAX_GOTCHAS = 48

ENTRY_RE = re.compile(r"(?m)^(##+)\s+(\d+)\.\s+([^\n]*)\n")
ENFORCE_RE = re.compile(r"(?m)^- \*\*enforcement\*\*：(.+)$")
WHAT_RE = re.compile(r"—\s*看什么：(.+)$")


def entries() -> list[tuple[int, str]]:
    text = GOTCHAS.read_text(encoding="utf-8")
    ms = list(ENTRY_RE.finditer(text))
    out = []
    for i, m in enumerate(ms):
        end = ms[i + 1].start() if i + 1 < len(ms) else len(text)
        out.append((int(m.group(2)), text[m.start():end]))
    return out


def levels() -> list[tuple[int, str]]:
    text = GOTCHAS.read_text(encoding="utf-8")
    return [(int(m.group(2)), m.group(1)) for m in ENTRY_RE.finditer(text)]


def parse(body: str) -> tuple[str, str, str]:
    """(prefix, target, tail) for one entry's enforcement line."""
    m = ENFORCE_RE.search(body)
    assert m is not None
    value = m.group(1).strip()
    prefix, _, rest = value.partition(":")
    target, _, tail = rest.partition(" — ")
    return prefix, target.strip(), tail.strip()


def resolve(target: str) -> Path | None:
    """Resolve `path` or `path:line` against the skill root."""
    path = target.split("#")[0].strip()
    candidate = ROOT / path
    if candidate.exists():
        return candidate
    m = re.match(r"^(.*?):(\d+)$", path)
    if m:
        candidate = ROOT / m.group(1)
        if candidate.exists():
            return candidate
    return None


def indexed_numbers() -> set[int]:
    hist = HISTORY.read_text(encoding="utf-8")
    return {int(n) for n in re.findall(r"#(\d+) ", hist)}


class GotchaEnforcement(unittest.TestCase):
    def test_every_entry_has_an_enforcement_pointer(self):
        missing = [n for n, body in entries() if not ENFORCE_RE.search(body)]
        self.assertEqual(missing, [], f"缺 enforcement 的条目：{missing}")

    def test_enforcement_line_is_single_and_well_formed(self):
        bad = []
        for n, body in entries():
            found = ENFORCE_RE.findall(body)
            if len(found) != 1:
                bad.append((n, f"{len(found)} 条 enforcement"))
                continue
            prefix, target, _ = parse(body)
            if prefix not in PREFIXES:
                bad.append((n, f"未知前缀 {prefix}"))
            elif not target:
                bad.append((n, "前缀后面没有目标"))
        self.assertEqual(bad, [], f"enforcement 行格式不对：{bad}")

    def test_enforcement_pointer_resolves(self):
        broken = []
        for n, body in entries():
            _, target, _ = parse(body)
            if resolve(target) is None:
                broken.append((n, target))
        self.assertEqual(broken, [], f"enforcement 指向不存在的文件：{broken}")

    def test_mechanical_pointers_are_not_prose(self):
        """check:/test:/env: 指到 .md 上等于没有执行点——文档不能跑。"""
        prose = []
        for n, body in entries():
            prefix, target, _ = parse(body)
            if prefix == "judgment":
                continue
            path = resolve(target)
            if path is None:
                continue
            if path.suffix == ".md":
                prose.append((n, f"{prefix}:{target}"))
        self.assertEqual(
            prose, [],
            "这些条目把机械执行点指到了文档上，请改成脚本/测试，"
            f"或降级为带「看什么」的 judgment：{prose}")

    def test_judgment_says_what_to_look_at(self):
        vague = []
        for n, body in entries():
            prefix, _, tail = parse(body)
            if prefix != "judgment":
                continue
            m = WHAT_RE.search(f"— {tail}")
            if m is None or len(m.group(1).strip()) < 20:
                vague.append((n, tail or "（没有「看什么」）"))
        self.assertEqual(
            vague, [],
            "judgment 必须写出「— 看什么：…」并说清看哪儿、看到什么算错，"
            f"不能只甩一个路径：{vague}")

    def test_entry_numbers_unique(self):
        nums = [n for n, _ in entries()]
        self.assertEqual(len(nums), len(set(nums)))

    def test_every_entry_names_module_and_state(self):
        bad = [n for n, body in entries()
               if "**module**" not in body or "**状态**" not in body]
        self.assertEqual(bad, [], f"缺 module / 状态 的条目：{bad}")

    def test_heading_level_is_uniform(self):
        mixed = [(n, lvl) for n, lvl in levels() if lvl != "##"]
        self.assertEqual(mixed, [], f"这些条目的标题层级不是 `##`：{mixed}")

    def test_retired_numbers_are_indexed(self):
        hist = HISTORY.read_text(encoding="utf-8")
        kept = {n for n, _ in entries()}
        # Anything that used to exist and is no longer in the body must appear in
        # the migration index (this catches silent deletion).
        self.assertIn("GOTCHAS 迁移索引（2026-10-19）", hist)
        highest = max(kept)
        for n in range(1, highest + 1):
            if n not in kept:
                self.assertIn(f"#{n} ", hist, f"#{n} 既不在正文也不在迁移索引")

    def test_inline_references_resolve(self):
        """正文里的 #n / 第 n 条 必须指向现行条目或迁移索引里的编号。"""
        kept = {n for n, _ in entries()}
        indexed = indexed_numbers()
        allowed = kept | indexed
        text = GOTCHAS.read_text(encoding="utf-8")
        dangling = []
        for line in text.splitlines():
            if re.match(r"^#{1,6}\s", line):
                continue                     # 标题行不是引用
            for m in re.finditer(r"#(\d+)(?![\w])", line):
                n = int(m.group(1))
                if n not in allowed:
                    dangling.append((n, line.strip()[:80]))
            for m in re.finditer(r"第\s*(\d+)\s*条", line):
                n = int(m.group(1))
                if n not in allowed:
                    dangling.append((n, line.strip()[:80]))
        self.assertEqual(
            dangling, [],
            "这些编号既不是现行条目、也不在迁移索引里（失联引用）："
            f"{dangling}")

    def test_cap_is_frozen(self):
        self.assertLessEqual(len(entries()), MAX_GOTCHAS,
                             f"GOTCHAS 超过上限 {MAX_GOTCHAS}：先合并或移到迁移索引，再加新的")


if __name__ == "__main__":
    unittest.main()
