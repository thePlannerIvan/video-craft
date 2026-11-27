#!/usr/bin/env python3
"""两层规范护栏（Style Card v3 + 全局 G01–G05 / V01–V05）必须真的会红。"""
from __future__ import annotations

import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "helpers"))
sys.path.insert(0, str(ROOT / "helpers" / "_internal"))

import spec_lint  # noqa: E402

SKILL_ROOT = ROOT


def author_entry(n: int, *, prefix: str = "G", fields: dict[str, str] | None = None) -> str:
    base = {"做法": "做法描述", "执行": "judgment:交付时看某处"}
    if fields:
        base.update(fields)
    lines = [f"### {prefix}{n:02d} 标题{n}"]
    for name in ("做法", "执行"):
        if base.get(name) is not None:
            lines.append(f"- {name}：{base[name]}")
    return "\n".join(lines) + "\n"


def minimal_author(*, g_count: int = 1, v_count: int = 1) -> str:
    parts = ["# 全局视觉与口播底线\n"]
    if g_count > 0:
        parts.append("## 全局视觉底线（G01–G05）\n")
        parts.extend(author_entry(i, prefix="G") for i in range(1, g_count + 1))
    if v_count > 0:
        parts.append("## 全局口播底线（V01–V05）\n")
        parts.extend(author_entry(i, prefix="V") for i in range(1, v_count + 1))
    return "\n".join(parts) + "\n"


def style_card(slug: str = "line-art", *, guardrails: int = 1, extra_lines: int = 0) -> str:
    lines = [
        f"## {slug} · 风格示例",
        "",
        "### 风格领词（Style Leading Words）",
        "- **Precision Linework**：极简线稿秩序。",
        "- **Monochrome Calibration**：黑白灰刻度层次。",
        "- **Causal Motion**：同轴联动推进。",
        "",
        "### 镜头与声画语法",
        "- 线条沿流程轴生长。",
        "",
        "### 高频防线",
    ]
    for i in range(1, guardrails + 1):
        lines.append(f"- **防线 {i}**：可核查动作描述。")
    for i in range(extra_lines):
        lines.append(f"- 补充说明行 {i + 1}")
    return "\n".join(lines) + "\n"


def make_specs(tmp: Path, author: str, styles: str) -> Path:
    (tmp / "author-spec.md").write_text(author, encoding="utf-8")
    (tmp / "style-spec.md").write_text(styles, encoding="utf-8")
    return tmp


def minimal_styles() -> str:
    return "## 风格清单\n\n| slug | 风格 |\n|---|---|\n| `line-art` | 线稿 |\n\n" + style_card("line-art")


class RealSpecs(unittest.TestCase):
    def test_repository_specs_pass(self):
        problems = spec_lint.lint()
        self.assertEqual(problems, [], f"仓库内规范未通过：{problems}")

    def test_cli_exit_zero(self):
        self.assertEqual(spec_lint.main(["--json"]), 0)

    def test_author_spec_has_exact_five_g_and_five_v_rules(self):
        """author-spec.md 对齐 v3 五条视觉底线 G01-G05 与五条口播底线 V01-V05。"""
        text = (ROOT / "references" / "author-spec.md").read_text(encoding="utf-8")
        lines = text.splitlines()
        self.assertLessEqual(len(lines), spec_lint.MAX_AUTHOR_LINES)

        g_entries = spec_lint._iter_entries(lines, spec_lint.AUTHOR_G_RE)
        v_entries = spec_lint._iter_entries(lines, spec_lint.AUTHOR_V_RE)
        self.assertEqual([e[0] for e in g_entries], ["G01", "G02", "G03", "G04", "G05"])
        self.assertEqual([e[0] for e in v_entries], ["V01", "V02", "V03", "V04", "V05"])

        self.assertIn("G03 动效与切镜绑定词级锚点", text)
        self.assertNotIn("check:helpers/align.py", text)
        # G05 不再硬编码暗场骨白/红框假设
        self.assertNotIn("骨白", text)
        # V01 不再锁死固定秒数
        self.assertNotIn("15 秒", text)
        self.assertNotIn("60 秒", text)

    def test_style_spec_covers_all_six_v3_styles_and_leading_words(self):
        text = (ROOT / "references" / "style-spec.md").read_text(encoding="utf-8")
        for slug in ("line-art", "business-report", "collage", "concept-film", "lifestyle-cult", "studio-motion-ui"):
            self.assertIn(f"## {slug} ", text, f"style-spec.md 缺少风格节：{slug}")
        self.assertIn("风格领词（Style Leading Words）", text)
        self.assertIn("Single High-Contrast Accent", text)
        self.assertIsNone(re.search(r"(?<!Style\s)Leading\s+Words", text, re.IGNORECASE))
        self.assertIsNone(re.search(r"1920[x×]1080", text))

    def test_no_verbatim_author_quotes(self):
        """规则里不引原话：防止模型按字面理解偏差。"""
        for name in spec_lint.SPEC_FILES:
            text = (ROOT / "references" / name).read_text(encoding="utf-8")
            for mark in ("「", "」", "“", "”"):
                self.assertNotIn(mark, text, f"{name} 含引文标记 {mark}")

    def test_author_spec_retires_production_mode_wording(self):
        for name in spec_lint.SPEC_FILES:
            text = (ROOT / "references" / name).read_text(encoding="utf-8")
            for retired in ("生产模式", "keyframe-svg", "footage-montage", "pure-talking", "craft.md", "page.md"):
                self.assertNotIn(retired, text, f"{name} 不应再绑定退役词 {retired}")


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
            "风格（Style）",
            "风格卡（Style Card）",
            "风格领词（Style Leading Words）",
            "视觉锚点（Visual Anchor）",
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

    def test_author_g_and_v_caps_are_enforced(self):
        spec_dir = make_specs(self.tmp, minimal_author(g_count=6, v_count=1), minimal_styles())
        self.assertTrue(any("视觉底线" in p and "上限" in p for p in spec_lint.lint(spec_dir, SKILL_ROOT)))

        spec_dir = make_specs(self.tmp, minimal_author(g_count=1, v_count=6), minimal_styles())
        self.assertTrue(any("口播底线" in p and "上限" in p for p in spec_lint.lint(spec_dir, SKILL_ROOT)))

    def test_author_line_cap_is_enforced(self):
        bloated = minimal_author() + ("\n" * (spec_lint.MAX_AUTHOR_LINES + 5))
        spec_dir = make_specs(self.tmp, bloated, minimal_styles())
        self.assertTrue(any("行上限" in p for p in spec_lint.lint(spec_dir, SKILL_ROOT)))

    def test_missing_required_field_is_reported(self):
        author = "# 全局\n\n### G01 标题\n- 做法：做法描述\n\n" + author_entry(1, prefix="V")
        spec_dir = make_specs(self.tmp, author, minimal_styles())
        self.assertTrue(any("缺字段：执行" in p for p in spec_lint.lint(spec_dir, SKILL_ROOT)))

    def test_dangling_check_pointer_is_reported(self):
        author = "# 全局\n\n" + author_entry(1, prefix="G", fields={"执行": "check:helpers/does-not-exist.py"}) + author_entry(1, prefix="V")
        spec_dir = make_specs(self.tmp, author, minimal_styles())
        self.assertTrue(any("不存在" in p for p in spec_lint.lint(spec_dir, SKILL_ROOT)))

    def test_unknown_style_slug_is_reported(self):
        styles = "## made-up-style · 编的\n\n" + style_card("made-up-style").split("\n", 1)[1]
        spec_dir = make_specs(self.tmp, minimal_author(), styles)
        self.assertTrue(any("未知风格节" in p for p in spec_lint.lint(spec_dir, SKILL_ROOT)))

    def test_missing_style_subsection_and_caps_are_reported(self):
        # Missing 高频防线
        bad_card = "## line-art · 线稿\n\n### 风格领词（Style Leading Words）\n- **A**：a\n- **B**：b\n- **C**：c\n\n### 镜头与声画语法\n- x\n"
        spec_dir = make_specs(self.tmp, minimal_author(), bad_card)
        self.assertTrue(any("高频防线" in p for p in spec_lint.lint(spec_dir, SKILL_ROOT)))

        # Guardrail cap > 4
        too_many_guards = style_card("line-art", guardrails=5)
        spec_dir = make_specs(self.tmp, minimal_author(), too_many_guards)
        self.assertTrue(any("防线" in p and "上限" in p for p in spec_lint.lint(spec_dir, SKILL_ROOT)))

        # Style card line cap > 45
        too_long = style_card("line-art", guardrails=2, extra_lines=40)
        spec_dir = make_specs(self.tmp, minimal_author(), too_long)
        self.assertTrue(any("行" in p and "上限" in p for p in spec_lint.lint(spec_dir, SKILL_ROOT)))

    def test_bare_leading_words_and_1920x1080_are_reported(self):
        bad_author = minimal_author() + "\n请使用 Leading Words。\n"
        spec_dir = make_specs(self.tmp, bad_author, minimal_styles())
        self.assertTrue(any("Leading Words" in p for p in spec_lint.lint(spec_dir, SKILL_ROOT)))

        bad_style = minimal_styles() + "\n默认按 1920x1080 布局。\n"
        spec_dir = make_specs(self.tmp, minimal_author(), bad_style)
        self.assertTrue(any("1920" in p for p in spec_lint.lint(spec_dir, SKILL_ROOT)))

    def test_duplicate_entry_id_is_reported(self):
        author = "# 全局\n\n" + author_entry(1, prefix="G") + author_entry(1, prefix="G") + author_entry(1, prefix="V")
        spec_dir = make_specs(self.tmp, author, minimal_styles())
        self.assertTrue(any("重复条目编号" in p for p in spec_lint.lint(spec_dir, SKILL_ROOT)))

    def test_missing_file_exits_two(self):
        make_specs(self.tmp, minimal_author(), minimal_styles())
        (self.tmp / "style-spec.md").unlink()
        self.assertEqual(spec_lint.main(["--json", "--spec-dir", str(self.tmp)]), 2)

    def test_single_route_wording_is_reported(self):
        author = minimal_author()
        spec_dir = make_specs(self.tmp, author, minimal_styles())
        banned = "路线不作为规范维度：" + "只有 " + "recompose 一" + "条。"
        (spec_dir / "preferences.md").write_text(banned + "\n", encoding="utf-8")
        problems = spec_lint.lint(spec_dir, SKILL_ROOT)
        self.assertTrue(
            any("单路线措辞" in p and "preferences.md" in p for p in problems),
            f"禁句没有被报出来：{problems}",
        )

    def test_two_route_wording_is_accepted(self):
        author = "> 底座剪口播叠加能力组合，与画框正交。\n\n" + minimal_author()
        spec_dir = make_specs(self.tmp, author, minimal_styles())
        self.assertEqual(spec_lint.lint(spec_dir, SKILL_ROOT), [])


if __name__ == "__main__":
    unittest.main()
