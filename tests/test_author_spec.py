#!/usr/bin/env python3
"""两层规范护栏必须真的会红。

证明两件事：
1. 仓库里真实的 author / style 两份规范通过；
2. 六类机械缺陷各自会让 lint 失败——否则上限只是装饰。
外加一条语义护栏：规范里不出现作者原话引文（防止模型按字面理解偏差）。
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "helpers"))
sys.path.insert(0, str(ROOT / "helpers" / "_internal"))

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

    def test_g03_has_no_pointer_to_deleted_align(self):
        """G03 的执行点已改为 judgment；align.py 本轮删除，指针不许再指回来。"""
        text = (ROOT / "references" / "author-spec.md").read_text(encoding="utf-8")
        self.assertIn("## G03 动效绑定词级锚点", text)
        self.assertNotIn("check:helpers/align.py", text)
        # check: 指针整体可解析由 test_repository_specs_pass 覆盖。
        self.assertIn("judgment:", text)

    def test_no_verbatim_author_quotes(self):
        """规则里不引原话：防止模型按字面理解偏差。"""
        for name in spec_lint.SPEC_FILES:
            text = (ROOT / "references" / name).read_text(encoding="utf-8")
            for mark in ("「", "」", "“", "”"):
                self.assertNotIn(mark, text, f"{name} 含引文标记 {mark}")

    def test_v3_aesthetic_benchmarks_present(self):
        """author-spec.md 纳入 v3 三条全局审美基准且不突破行数/条目上限。"""
        text = (ROOT / "references" / "author-spec.md").read_text(encoding="utf-8")
        lines = text.splitlines()
        self.assertLessEqual(len(lines), spec_lint.MAX_AUTHOR_LINES)
        entries = spec_lint._iter_entries(lines, spec_lint.AUTHOR_ENTRY_RE)
        self.assertLessEqual(len(entries), spec_lint.MAX_AUTHOR_ENTRIES)
        # 1. 无静态参考时采用随口播持续演化的单一空间思维模型，禁止 PPT 文字框拼接
        self.assertIn("思维模型", text)
        self.assertIn("文字框", text)
        # 2. 图片、海报与卡片组件采用极细骨白边框，禁止红色高亮框
        self.assertIn("骨白", text)
        self.assertIn("红", text)
        # 3. 顶部辅助角区仅留极简几何装饰，禁止段落编号与内部排产标签
        self.assertIn("几何装饰", text)
        self.assertIn("编号", text)

    def test_author_spec_retires_production_mode_wording(self):
        text = (ROOT / "references" / "author-spec.md").read_text(encoding="utf-8")
        for retired in ("生产模式", "keyframe-svg", "footage-montage", "pure-talking"):
            self.assertNotIn(retired, text, f"author-spec.md 不应再绑定退役词 {retired}")


class DomainModelV3(unittest.TestCase):
    def test_glossary_defines_six_canonical_terms_and_retires_production_mode(self):
        glossary = (ROOT / "GLOSSARY.md").read_text(encoding="utf-8")
        self.assertIn("## Language", glossary)
        self.assertIn("## Retired Terms", glossary)
        language_part, retired_part = glossary.split("## Retired Terms", 1)
        for term in (
            "能力组合",
            "人声润色",
            "画面声景",
            "思维模型动效",
            "轻量样镜定调",
            "执行分镜",
        ):
            self.assertIn(f"**{term}", language_part, f"GLOSSARY.md Language 缺少规范术语：{term}")
        self.assertNotIn("**生产模式", language_part)
        self.assertIn("生产模式", retired_part)
        active_defs = "\n".join(
            ln for ln in language_part.splitlines() if not ln.strip().startswith("_Avoid_:")
        )
        self.assertNotIn("无声纯画面", active_defs)
        self.assertNotIn("画面成片必须 0 音轨", active_defs)

    def test_adr_0005_exists_and_updates_0002_0004_status(self):
        adr_dir = ROOT / "docs" / "adr"
        adr5 = adr_dir / "0005-composable-capabilities-segment-splicing-and-visual-soundscape.md"
        self.assertTrue(adr5.is_file(), "缺少 ADR-0005")
        adr5_text = adr5.read_text(encoding="utf-8")
        self.assertIn("**Status**: accepted", adr5_text)
        for keyword in ("能力组合", "按段分流", "人声润色", "画面声景", "ADR-0002", "ADR-0004"):
            self.assertIn(keyword, adr5_text)

        adr2_text = (adr_dir / "0002-four-tier-visual-grammar-and-builtin-quality-gate.md").read_text(encoding="utf-8")
        adr4_text = (adr_dir / "0004-split-delivery-default-and-chat-approval-gate.md").read_text(encoding="utf-8")
        self.assertIn("partially superseded by ADR-0005", adr2_text)
        self.assertIn("partially superseded by ADR-0005", adr4_text)


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

    def test_single_route_wording_is_reported(self):
        """单路线口径已作废：片型有 graphic / montage 两条，禁句要让 lint 红。"""
        author = "> 片型有两条：graphic / montage\n\n" + author_entry(1)
        spec_dir = make_specs(self.tmp, author, minimal_styles())
        # 禁句按片段拼出来：仓库里不该出现这句的完整字面量，但它必须能被 lint 抓到。
        banned = "路线不作为规范维度：" + "只有 " + "recompose 一" + "条。"
        (spec_dir / "preferences.md").write_text(banned + "\n", encoding="utf-8")
        problems = spec_lint.lint(spec_dir, SKILL_ROOT)
        self.assertTrue(
            any("单路线措辞" in p and "preferences.md" in p for p in problems),
            f"禁句没有被报出来：{problems}",
        )

    def test_two_route_wording_is_accepted(self):
        """正常表述（两条片型 + 版式正交）不误报。"""
        author = "> 片型有两条：graphic 造画面 / montage 选画面；版式与片型正交。\n\n" + author_entry(1)
        spec_dir = make_specs(self.tmp, author, minimal_styles())
        self.assertEqual(spec_lint.lint(spec_dir, SKILL_ROOT), [])


if __name__ == "__main__":
    unittest.main()
