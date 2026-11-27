#!/usr/bin/env python3
"""Tests for read-only Style Card v3 Vault resolution and open-source fallback (`resolve_vault.py`)."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "helpers"))
sys.path.insert(0, str(ROOT / "helpers" / "_internal"))

import resolve_vault  # noqa: E402


LEGACY_KEYS = (
    "production_mode",
    "craft_type",
    "craft_rules_path",
    "page_rules_path",
    "params",
    "default_frame_preset",
)


def _make_temp_v3_vault(tmp: Path) -> Path:
    (tmp / "styles").mkdir(parents=True, exist_ok=True)
    (tmp / "frames").mkdir(parents=True, exist_ok=True)
    (tmp / "global").mkdir(parents=True, exist_ok=True)
    (tmp / "frames" / "landscape-left-host.json").write_text(
        '{"preset_id":"landscape-left-host"}\n', encoding="utf-8"
    )
    (tmp / "frames" / "vertical-pip-top-left.json").write_text(
        '{"preset_id":"vertical-pip-top-left"}\n', encoding="utf-8"
    )
    (tmp / "global" / "author-spec.md").write_text(
        "# 全局视觉底线\n\n### G01 单一视觉中心与在场演化\n- 做法：每屏只立一个清晰视觉中心\n- 执行：judgment:看主体\n",
        encoding="utf-8",
    )
    (tmp / "global" / "voice-profile.md").write_text(
        "# 全局口播底线\n\n### V01 开场第一句直入反差体感、锋利判断或可带走资产\n- 做法：不做背景寒暄\n- 执行：judgment:读首句\n",
        encoding="utf-8",
    )
    (tmp / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "3.0.0",
                "styles": ["line-art", "concept-film"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    # line-art without preferred_frame (optional field)
    line_dir = tmp / "styles" / "line-art"
    line_dir.mkdir(parents=True, exist_ok=True)
    (line_dir / "style.md").write_text(
        "# line-art · 线稿工程图\n\n## Style Leading Words\n- **Architectural Precision**：极简线稿秩序\n\n## 镜头与声画语法\n- 沿流程轴自绘。\n\n## 高频防线\n",
        encoding="utf-8",
    )
    (line_dir / "style.json").write_text(
        json.dumps(
            {
                "schema_version": "3.0.0",
                "style_id": "line-art",
                "name": "线稿图解",
                "version": "v1.0",
                "default_capabilities": ["motion"],
                "palette": {"bg_light": "#F7F7F5", "ink_primary": "#111111"},
                "anchors": [],
                "patterns": [],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    # concept-film with preferred_frame, palette, real + missing anchors & patterns
    cf_dir = tmp / "styles" / "concept-film"
    (cf_dir / "anchors").mkdir(parents=True, exist_ok=True)
    (cf_dir / "patterns").mkdir(parents=True, exist_ok=True)
    (cf_dir / "anchors" / "s01-viewfinder-zoom.jpg").write_bytes(b"fake-jpg")
    (cf_dir / "patterns" / "p1-optical-reveal-strip.jpg").write_bytes(b"fake-strip")
    (cf_dir / "patterns" / "p1-optical-reveal.webm").write_bytes(b"fake-webm")
    (cf_dir / "style.md").write_text(
        "# concept-film · 概念暗调短片风\n\n"
        "## Style Leading Words\n"
        "- **Darkroom Precision Blueprint**：暗场精密蓝图\n"
        "- **Single High-Contrast Accent**：九成黑白灰配单一高对比强调色\n\n"
        "## 镜头与声画语法\n"
        "- 推拉与景别服务口播语义。\n\n"
        "## 高频防线\n"
        "- **核心公式独屏居中**：公式独屏呈现。\n",
        encoding="utf-8",
    )
    (cf_dir / "style.json").write_text(
        json.dumps(
            {
                "schema_version": "3.0.0",
                "style_id": "concept-film",
                "name": "概念暗调短片风 (Concept Film)",
                "version": "v2.0",
                "default_capabilities": ["motion"],
                "preferred_frame": "vertical-pip-top-left",
                "palette": {
                    "bg_dark": "#0A0B0E",
                    "ink_primary": "#F4F5F7",
                    "surface_card": "#FFFFFF",
                },
                "anchors": [
                    {"label": "局部精绘拉远露全局", "path": "anchors/s01-viewfinder-zoom.jpg"},
                    {"label": "缺失锚点", "path": "anchors/missing.jpg"},
                ],
                "patterns": [
                    {
                        "id": "p1-optical-reveal",
                        "title": "招式 01 · 光学拉远",
                        "when_to_use": "从局域反转到全局",
                        "rule": "推拉重构视野。",
                        "strip": "patterns/p1-optical-reveal-strip.jpg",
                        "webm": "patterns/p1-optical-reveal.webm",
                    },
                    {
                        "id": "p-missing",
                        "title": "缺失招式",
                        "strip": "patterns/missing-strip.jpg",
                        "webm": "patterns/missing.webm",
                    },
                    {
                        "id": "p-rule-only",
                        "title": "规则级招式",
                        "when_to_use": "纯语义节奏模板",
                        "rule": "按句切镜且保留主焦点。",
                    },
                ],
                "evolved_from_projects": ["AI解决不了未知的未知"],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return tmp


class ResolveVaultTests(unittest.TestCase):
    def test_fallback_mode_when_env_is_none(self):
        old = os.environ.get("PLANNERS_VIDEO_VAULT")
        try:
            os.environ["PLANNERS_VIDEO_VAULT"] = "none"
            info = resolve_vault.resolve_vault("lifestyle-cult")
            self.assertFalse(info["available"])
            self.assertTrue(info["standalone"])
            self.assertEqual(info["mode"], "open-source-fallback")
            self.assertEqual(info["style_id"], "lifestyle-cult")
            self.assertTrue(Path(info["author_spec_path"]).is_file())
            self.assertTrue(Path(info["style_card_path"]).is_file())
            self.assertEqual(info["palette"], {})
            self.assertEqual(info["anchors"], [])
            self.assertEqual(info["patterns"], [])
            self.assertIsNone(info["preferred_frame"])
            for legacy_key in LEGACY_KEYS:
                self.assertNotIn(legacy_key, info)
            self.assertIn("frame_defaults", info)
            self.assertEqual(info["frame_defaults"]["personSlot"], {"x": 0, "y": 0, "w": 620, "h": 1080})
        finally:
            if old is None:
                os.environ.pop("PLANNERS_VIDEO_VAULT", None)
            else:
                os.environ["PLANNERS_VIDEO_VAULT"] = old

    def test_open_source_standalone_without_vault_or_video_manager(self):
        with tempfile.TemporaryDirectory() as isolated_home:
            old_vault = os.environ.get("PLANNERS_VIDEO_VAULT")
            old_home = os.environ.get("HOME")
            try:
                os.environ.pop("PLANNERS_VIDEO_VAULT", None)
                os.environ["HOME"] = isolated_home
                for style in ("line-art", "concept-film", "lifestyle-cult", "studio-motion-ui"):
                    info = resolve_vault.resolve_vault(style)
                    self.assertFalse(info["available"])
                    self.assertTrue(info["standalone"])
                    self.assertEqual(info["style_id"], style)
                    self.assertTrue(Path(info["author_spec_path"]).is_file())
                    self.assertTrue(Path(info["style_card_path"]).is_file())
                    self.assertIn("captionSafe", info["frame_defaults"])
                    for legacy_key in LEGACY_KEYS:
                        self.assertNotIn(legacy_key, info)
            finally:
                if old_vault is None:
                    os.environ.pop("PLANNERS_VIDEO_VAULT", None)
                else:
                    os.environ["PLANNERS_VIDEO_VAULT"] = old_vault
                if old_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = old_home

    def test_resolves_v3_vault_style_card_palette_anchors_patterns_and_preferred_frame(self):
        with tempfile.TemporaryDirectory() as td:
            vault = _make_temp_v3_vault(Path(td))
            old = os.environ.get("PLANNERS_VIDEO_VAULT")
            try:
                os.environ["PLANNERS_VIDEO_VAULT"] = str(vault)
                info = resolve_vault.resolve_vault("concept-film")
                self.assertTrue(info["available"])
                self.assertFalse(info["standalone"])
                self.assertEqual(info["mode"], "private-vault")
                self.assertEqual(info["schema_version"], "3.0.0")
                self.assertEqual(info["style_id"], "concept-film")
                self.assertEqual(info["default_capabilities"], ["motion"])
                self.assertTrue(info["style_card_path"].endswith("styles/concept-film/style.md"))
                self.assertTrue(Path(info["style_card_path"]).is_file())
                self.assertTrue(info["author_spec_path"].endswith("global/author-spec.md"))
                self.assertTrue(info["voice_profile_path"].endswith("global/voice-profile.md"))
                self.assertEqual(
                    info["palette"],
                    {"bg_dark": "#0A0B0E", "ink_primary": "#F4F5F7", "surface_card": "#FFFFFF"},
                )
                # Only existing anchor is returned
                self.assertEqual(len(info["anchors"]), 1)
                self.assertEqual(info["anchors"][0]["label"], "局部精绘拉远露全局")
                self.assertTrue(Path(info["anchors"][0]["path"]).is_file())
                # Existing pattern and rule-only pattern are retained; declared-missing pattern is dropped
                self.assertEqual([p["id"] for p in info["patterns"]], ["p1-optical-reveal", "p-rule-only"])
                self.assertTrue(Path(info["patterns"][0]["strip"]).is_file())
                self.assertTrue(Path(info["patterns"][0]["webm"]).is_file())
                self.assertIsNone(info["patterns"][1]["strip"])
                self.assertIsNone(info["patterns"][1]["webm"])
                self.assertIsNone(info["patterns"][1]["code"])
                cli_rc = resolve_vault.main(["--style", "concept-film", "--vault", str(vault), "--json"])
                self.assertEqual(cli_rc, 0)
                # Optional preferred_frame resolves to frames/<id>.json
                self.assertEqual(info["preferred_frame"], "vertical-pip-top-left")
                self.assertEqual(info["frame_preset"], "vertical-pip-top-left")
                self.assertTrue(info["frame_preset_path"].endswith("vertical-pip-top-left.json"))
                self.assertEqual(len(info["frame_preset_paths"]), 1)
                for legacy_key in LEGACY_KEYS:
                    self.assertNotIn(legacy_key, info)

                # Explicit frame override keeps preferred_frame metadata intact
                overridden = resolve_vault.resolve_vault("concept-film", frame_id="landscape-left-host")
                self.assertEqual(overridden["preferred_frame"], "vertical-pip-top-left")
                self.assertEqual(overridden["frame_preset"], "landscape-left-host")
                self.assertTrue(overridden["frame_preset_path"].endswith("landscape-left-host.json"))
            finally:
                if old is None:
                    os.environ.pop("PLANNERS_VIDEO_VAULT", None)
                else:
                    os.environ["PLANNERS_VIDEO_VAULT"] = old

    def test_optional_preferred_frame_when_omitted(self):
        with tempfile.TemporaryDirectory() as td:
            vault = _make_temp_v3_vault(Path(td))
            old = os.environ.get("PLANNERS_VIDEO_VAULT")
            try:
                os.environ["PLANNERS_VIDEO_VAULT"] = str(vault)
                info = resolve_vault.resolve_vault("line-art")
                self.assertTrue(info["available"])
                self.assertIsNone(info["preferred_frame"])
                self.assertIsNone(info["frame_preset"])
                self.assertIsNone(info["frame_preset_path"])
                self.assertEqual(info["frame_preset_paths"], [])
            finally:
                if old is None:
                    os.environ.pop("PLANNERS_VIDEO_VAULT", None)
                else:
                    os.environ["PLANNERS_VIDEO_VAULT"] = old

    def test_resolve_vault_source_has_no_legacy_fallbacks(self):
        src = (ROOT / "helpers" / "_internal" / "resolve_vault.py").read_text(encoding="utf-8")
        for forbidden in (
            "craft.md",
            "page.md",
            "production_mode",
            "FALLBACK_PRODUCTION_MODES",
            "_craft_type_for",
            "default_frame_preset",
        ):
            self.assertNotIn(forbidden, src, f"resolve_vault.py still contains legacy symbol/ref `{forbidden}`")


if __name__ == "__main__":
    unittest.main()
