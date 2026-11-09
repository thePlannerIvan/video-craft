#!/usr/bin/env python3
"""Tests for the model-agnostic Style Extraction & Evolution system (`style_vault.py`, `extract_style.py`, `resolve_vault.py`)."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "helpers"))

import extract_style  # noqa: E402
import resolve_vault  # noqa: E402
import style_vault  # noqa: E402


def _make_temp_vault(tmp: Path) -> Path:
    (tmp / "styles").mkdir(parents=True, exist_ok=True)
    (tmp / "frames").mkdir(parents=True, exist_ok=True)
    (tmp / "global").mkdir(parents=True, exist_ok=True)
    (tmp / "frames" / "landscape-left-host.json").write_text('{"preset_id":"landscape-left-host"}\n', encoding="utf-8")
    (tmp / "frames" / "vertical-zine-head.json").write_text('{"preset_id":"vertical-zine-head"}\n', encoding="utf-8")
    (tmp / "frames" / "vertical-band-table.json").write_text('{"preset_id":"vertical-band-table"}\n', encoding="utf-8")
    (tmp / "global" / "author-spec.md").write_text("# 全局判准\n\n## G01 主体在场\n- 做法：有主体\n- 证据：片A\n- 执行：judgment:看主体\n", encoding="utf-8")
    (tmp / "global" / "voice-profile.md").write_text("# 口播规范\n\n- 一句一意\n", encoding="utf-8")
    (tmp / "manifest.json").write_text(json.dumps({"schema_version": "2.0.0", "styles": ["line-art"]}, ensure_ascii=False), encoding="utf-8")

    sdir = tmp / "styles" / "line-art"
    sdir.mkdir(parents=True, exist_ok=True)
    (sdir / "patterns").mkdir(exist_ok=True)
    (sdir / "style.json").write_text(
        json.dumps({
            "style_id": "line-art",
            "name": "线稿图解",
            "production_mode": "keyframe-svg",
            "default_frame_preset": "landscape-left-host",
            "params": {
                "stroke_ease": {"value": "power2.out", "source": "measured"},
            },
            "patterns": [],
        }, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    for st in ("idea", "page", "craft"):
        (sdir / f"{st}.md").write_text(style_vault.render_stage("line-art", st, []), encoding="utf-8")
    (sdir / "candidates.json").write_text("[]\n", encoding="utf-8")
    return tmp


class ResolveVaultTests(unittest.TestCase):
    def test_fallback_mode_when_env_is_none(self):
        old = os.environ.get("PLANNERS_VIDEO_VAULT")
        try:
            os.environ["PLANNERS_VIDEO_VAULT"] = "none"
            info = resolve_vault.resolve_vault("lifestyle-cult")
            self.assertFalse(info["available"])
            self.assertEqual(info["mode"], "open-source-fallback")
            self.assertEqual(info["production_mode"], "footage-montage")
            self.assertEqual(info["craft_type"], "montage")
        finally:
            if old is None:
                os.environ.pop("PLANNERS_VIDEO_VAULT", None)
            else:
                os.environ["PLANNERS_VIDEO_VAULT"] = old

    def test_resolves_default_frame_preset_including_multi_preset_slash(self):
        with tempfile.TemporaryDirectory() as td:
            vault = _make_temp_vault(Path(td))
            sdir = vault / "styles" / "lifestyle-cult"
            sdir.mkdir(parents=True, exist_ok=True)
            (sdir / "style.json").write_text(
                json.dumps({
                    "style_id": "lifestyle-cult",
                    "production_mode": "footage-montage",
                    "default_frame_preset": "vertical-zine-head / vertical-band-table",
                }),
                encoding="utf-8",
            )
            old = os.environ.get("PLANNERS_VIDEO_VAULT")
            try:
                os.environ["PLANNERS_VIDEO_VAULT"] = str(vault)
                info = resolve_vault.resolve_vault("lifestyle-cult")
                self.assertTrue(info["available"])
                self.assertEqual(info["frame_preset"], "vertical-zine-head")
                self.assertTrue(info["frame_preset_path"].endswith("vertical-zine-head.json"))
                self.assertEqual(len(info["frame_preset_paths"]), 2)
            finally:
                if old is None:
                    os.environ.pop("PLANNERS_VIDEO_VAULT", None)
                else:
                    os.environ["PLANNERS_VIDEO_VAULT"] = old


class ExtractionProtocolTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.vault = _make_temp_vault(Path(self._td.name))

    def tearDown(self):
        self._td.cleanup()

    def test_numbers_and_quotes_in_prose_are_rejected(self):
        bad_proposal = {
            "style_id": "line-art",
            "source_project": "测试片A",
            "rules": [
                {
                    "stage": "craft",
                    "relation": "新增",
                    "title": "线条用 2px 随词生长",
                    "fields": {
                        "做法": "用 #D84A32 色和「弹跳」缓动绘出线条",
                        "执行": "judgment:看线条",
                    },
                    "evidence": [{"project": "测试片A", "where": "beat-01", "type": "feedback-negative"}],
                }
            ],
        }
        res = extract_style.evaluate_proposal(bad_proposal, self.vault)
        self.assertFalse(res["ok"])
        joined = "\n".join(res["problems"])
        self.assertIn("含数字或色值", joined)
        self.assertIn("含引号", joined)

    def test_feedback_negative_admitted_immediately_while_tendency_waits_for_second_project(self):
        # 1st project: 1 feedback-negative + 1 feedback-tendency
        prop1 = {
            "style_id": "line-art",
            "source_project": "项目一",
            "summary": "第一次提取",
            "rules": [
                {
                    "stage": "craft",
                    "relation": "新增",
                    "title": "线条对齐关键词逐步绘出",
                    "fields": {
                        "做法": "路径对齐口播关键词起止时间逐步绘出，不整张画面同时淡入。",
                        "执行": "judgment:逐屏检查路径是否随词绘出",
                        "参数": "stroke_ease",
                    },
                    "evidence": [{"project": "项目一", "where": "beat-01", "type": "feedback-negative"}],
                },
                {
                    "stage": "idea",
                    "relation": "新增",
                    "title": "开场直接刺破常见直觉误区",
                    "fields": {
                        "做法": "开篇直接点破日常直觉误区，不铺垫背景定义。",
                        "执行": "judgment:看开场前两句是否刺破误区",
                    },
                    "evidence": [{"project": "项目一", "where": "beat-01", "type": "feedback-tendency"}],
                },
            ],
        }
        applied1 = extract_style.apply_proposal(prop1, self.vault)
        self.assertTrue(applied1["ok"], applied1)
        craft_entries = style_vault.stage_entries(self.vault / "styles" / "line-art", "craft")
        idea_entries = style_vault.stage_entries(self.vault / "styles" / "line-art", "idea")
        self.assertEqual(len(craft_entries), 1)
        self.assertEqual(craft_entries[0]["fields"]["依据"], "反馈否定")
        self.assertEqual(len(idea_entries), 0)
        self.assertEqual(applied1["candidates_count"], 1)

        # 2nd independent project hits the same idea tendency -> auto-promoted to active idea.md!
        prop2 = {
            "style_id": "line-art",
            "source_project": "项目二",
            "summary": "第二次独立项目复现",
            "rules": [
                {
                    "stage": "idea",
                    "relation": "新增",
                    "title": "开场直接刺破常见直觉误区",
                    "fields": {
                        "做法": "开篇直接点破日常直觉误区，不铺垫背景定义。",
                        "执行": "judgment:看开场前两句是否刺破误区",
                    },
                    "evidence": [{"project": "项目二", "where": "beat-01", "type": "approved-observation"}],
                },
            ],
        }
        applied2 = extract_style.apply_proposal(prop2, self.vault)
        self.assertTrue(applied2["ok"], applied2)
        idea_entries_after = style_vault.stage_entries(self.vault / "styles" / "line-art", "idea")
        self.assertEqual(len(idea_entries_after), 1)
        self.assertEqual(idea_entries_after[0]["fields"]["依据"], "复现")
        self.assertIn("项目一", idea_entries_after[0]["fields"]["证据"])
        self.assertIn("项目二", idea_entries_after[0]["fields"]["证据"])
        self.assertEqual(applied2["candidates_count"], 0)

    def test_cap_enforces_replacement_when_stage_has_five_entries(self):
        rules = [
            {
                "stage": "craft",
                "relation": "新增",
                "title": f"动效规则标题{label}",
                "fields": {
                    "做法": f"可观察的运动行为描述{label}",
                    "执行": "judgment:看运动行为",
                },
                "evidence": [{"project": "项目甲", "where": "ch01", "type": "feedback-negative"}],
            }
            for label in ("甲", "乙", "丙", "丁", "戊")
        ]
        res5 = extract_style.apply_proposal({"style_id": "line-art", "source_project": "项目甲", "rules": rules}, self.vault)
        self.assertTrue(res5["ok"], res5)

        # 6th rule with relation="新增" must fail
        sixth_add = {
            "style_id": "line-art",
            "source_project": "项目乙",
            "rules": [{
                "stage": "craft",
                "relation": "新增",
                "title": "第六条规则",
                "fields": {"做法": "试图超出五条硬上限", "执行": "judgment:看上限"},
                "evidence": [{"project": "项目乙", "where": "ch01", "type": "feedback-negative"}],
            }],
        }
        check6 = extract_style.evaluate_proposal(sixth_add, self.vault)
        self.assertFalse(check6["ok"])
        self.assertTrue(any("超过 5 条上限" in p for p in check6["problems"]))

        # Using relation="替代" targeting C01 succeeds!
        sixth_replace = {
            "style_id": "line-art",
            "source_project": "项目乙",
            "rules": [{
                "stage": "craft",
                "relation": "替代",
                "target_id": "C01",
                "title": "替代第一条的新规则",
                "fields": {"做法": "通过替换保持五条硬上限不膨胀", "执行": "judgment:看替换结果"},
                "evidence": [{"project": "项目乙", "where": "ch01", "type": "feedback-negative"}],
            }],
        }
        apply_rep = extract_style.apply_proposal(sixth_replace, self.vault)
        self.assertTrue(apply_rep["ok"], apply_rep)
        entries = style_vault.stage_entries(self.vault / "styles" / "line-art", "craft")
        self.assertEqual(len(entries), 5)
        self.assertEqual(entries[0]["title"], "替代第一条的新规则")

    def test_real_vault_passes_lint_if_mounted(self):
        real_vault = resolve_vault.find_vault_root()
        if real_vault is not None:
            problems = style_vault.lint_vault(real_vault)
            self.assertEqual(problems, [], f"真实风格库未通过 lint：{problems}")


if __name__ == "__main__":
    unittest.main()
