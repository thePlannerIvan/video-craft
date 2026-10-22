#!/usr/bin/env python3
"""两层规范护栏必须真的会红。

证明两件事：
1. 仓库里真实的 author / style 两份规范通过；
2. 五类机械缺陷各自会让 lint 失败——否则上限只是装饰。
外加一条语义护栏：规范里不出现作者原话引文（防止模型按字面理解偏差）。
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "helpers"))

import spec_lint  # noqa: E402

SKILL_ROOT = ROOT


def author_entry(n: int, *, fields: dict[str, str] | None = None) -> str:
    base = {"做法": "做法描述", "证据": "项目A ch01", "执行": "judgment:交付时看某处"}
    if fields:
        base.update(fields)
    lines = [f"## G{n:02d} 标题{n}"]
    for name in ("做法", "证据", "执行"):
        if base.get(name) is not None:
            lines.append(f"- {name}：{base[name]}")
    return "\n".join(lines) + "\n"


def style_entry(n: int) -> str:
    return (
        f"### S{n:02d} 风格标题{n}\n"
        "- 做法：做法描述\n"
        "- 证据：项目A ch01\n"
        "- 执行：judgment:交付时看某处\n"
    )


def make_specs(tmp: Path, author: str, styles: str) -> Path:
    (tmp / "author-spec.md").write_text(author, encoding="utf-8")
    (tmp / "style-spec.md").write_text(styles, encoding="utf-8")
    return tmp


def minimal_styles() -> str:
    return "## 风格清单\n\n| slug | 风格 |\n|---|---|\n| `line-art` | 线稿 |\n\n## line-art · 线稿\n\n" + style_entry(1)


class RealSpecs(unittest.TestCase):
    def test_repository_specs_pass(self):
        problems = spec_lint.lint()
        self.assertEqual(problems, [], f"仓库内规范未通过：{problems}")

    def test_cli_exit_zero(self):
        self.assertEqual(spec_lint.main(["--json"]), 0)

    def test_check_pointers_resolve(self):
        text = (ROOT / "references" / "author-spec.md").read_text(encoding="utf-8")
        self.assertIn("check:helpers/align.py", text)
        self.assertTrue((SKILL_ROOT / "helpers" / "align.py").exists())

    def test_no_verbatim_author_quotes(self):
        """规则里不引原话：防止模型按字面理解偏差。"""
        for name in spec_lint.SPEC_FILES:
            text = (ROOT / "references" / name).read_text(encoding="utf-8")
            for mark in ("「", "」", "“", "”"):
                self.assertNotIn(mark, text, f"{name} 含引文标记 {mark}")


class MechanicalDefects(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_author_cap_is_enforced(self):
        author = "".join(author_entry(i) for i in range(1, spec_lint.MAX_AUTHOR_ENTRIES + 2))
        spec_dir = make_specs(self.tmp, author, minimal_styles())
        self.assertTrue(any("条上限" in p for p in spec_lint.lint(spec_dir, SKILL_ROOT)))

    def test_missing_required_field_is_reported(self):
        author = author_entry(1, fields={"执行": None})  # type: ignore[arg-type]
        spec_dir = make_specs(self.tmp, author, minimal_styles())
        self.assertTrue(any("缺字段：执行" in p for p in spec_lint.lint(spec_dir, SKILL_ROOT)))

    def test_dangling_check_pointer_is_reported(self):
        author = author_entry(1, fields={"执行": "check:helpers/does-not-exist.py"})
        spec_dir = make_specs(self.tmp, author, minimal_styles())
        self.assertTrue(any("不存在" in p for p in spec_lint.lint(spec_dir, SKILL_ROOT)))

    def test_unknown_style_slug_is_reported(self):
        styles = "## made-up-style · 编的\n\n" + style_entry(1)
        spec_dir = make_specs(self.tmp, author_entry(1), styles)
        self.assertTrue(any("未知风格节" in p for p in spec_lint.lint(spec_dir, SKILL_ROOT)))

    def test_duplicate_entry_id_is_reported(self):
        author = author_entry(1) + author_entry(1)
        spec_dir = make_specs(self.tmp, author, minimal_styles())
        self.assertTrue(any("重复条目编号" in p for p in spec_lint.lint(spec_dir, SKILL_ROOT)))

    def test_missing_file_exits_two(self):
        make_specs(self.tmp, author_entry(1), minimal_styles())
        (self.tmp / "style-spec.md").unlink()
        self.assertEqual(spec_lint.main(["--json", "--spec-dir", str(self.tmp)]), 2)


if __name__ == "__main__":
    unittest.main()
