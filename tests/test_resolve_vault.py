#!/usr/bin/env python3
"""Tests for read-only Style Vault resolution and open-source fallback (`resolve_vault.py`)."""
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


def _make_temp_vault(tmp: Path) -> Path:
    (tmp / "styles").mkdir(parents=True, exist_ok=True)
    (tmp / "frames").mkdir(parents=True, exist_ok=True)
    (tmp / "global").mkdir(parents=True, exist_ok=True)
    (tmp / "frames" / "landscape-left-host.json").write_text('{"preset_id":"landscape-left-host"}\n', encoding="utf-8")
    (tmp / "frames" / "vertical-zine-head.json").write_text('{"preset_id":"vertical-zine-head"}\n', encoding="utf-8")
    (tmp / "frames" / "vertical-band-table.json").write_text('{"preset_id":"vertical-band-table"}\n', encoding="utf-8")
    (tmp / "global" / "author-spec.md").write_text("# 全局判准\n\n## G01 主体在场\n- 做法：有主体\n- 证据：片A\n- 执行：judgment:看主体\n", encoding="utf-8")
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
            "params": {"stroke_ease": {"value": "power2.out", "source": "measured"}},
            "patterns": [],
        }, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (sdir / "craft.md").write_text("# line-art\n", encoding="utf-8")
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
            self.assertEqual(info["production_mode"], "footage-montage")
            self.assertEqual(info["craft_type"], "montage")
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
                for style, expected_mode, expected_type in (
                    ("pure-talking", "pure-talking", "talking"),
                    ("line-art", "keyframe-svg", "graphic"),
                    ("lifestyle-cult", "footage-montage", "montage"),
                ):
                    info = resolve_vault.resolve_vault(style)
                    self.assertFalse(info["available"])
                    self.assertTrue(info["standalone"])
                    self.assertEqual(info["production_mode"], expected_mode)
                    self.assertEqual(info["craft_type"], expected_type)
                    self.assertTrue(Path(info["author_spec_path"]).is_file())
                    self.assertTrue(Path(info["craft_rules_path"]).is_file())
                    self.assertIn("captionSafe", info["frame_defaults"])
            finally:
                if old_vault is None:
                    os.environ.pop("PLANNERS_VIDEO_VAULT", None)
                else:
                    os.environ["PLANNERS_VIDEO_VAULT"] = old_vault
                if old_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = old_home

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


if __name__ == "__main__":
    unittest.main()
