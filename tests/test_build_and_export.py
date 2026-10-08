#!/usr/bin/env python3
"""Unit tests for build_review.py, serve_review.py, and export_video.py."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

HELPERS = Path(__file__).parents[1] / "helpers"
sys.path.insert(0, str(HELPERS))

import build_review
import serve_review
import export_video


class TestBuildReview(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="vc_test_build_")).resolve()
        self.edit_dir = self.tmp_dir / "edit"
        self.edit_dir.mkdir(parents=True, exist_ok=True)

        # Mock edl.json
        self.edl_data = {
            "version": 1,
            "sources": {"C01": "/path/to/c01.mp4"},
            "ranges": [
                {"source": "C01", "start": 0.0, "end": 5.0, "beat": "HOOK", "quote": "开场词句", "reason": "测试"}
            ],
            "total_duration_s": 5.0
        }
        (self.edit_dir / "edl.json").write_text(json.dumps(self.edl_data), encoding="utf-8")

        # Mock timeline.json
        self.timeline_data = {
            "source": "edl",
            "totalChapters": 1,
            "totalSteps": 1,
            "totalDurationMs": 5000,
            "chapters": [
                {
                    "id": "beat-01",
                    "title": "测试章节",
                    "steps": [
                        {
                            "id": "beat-01-01",
                            "step": 0,
                            "startMs": 0,
                            "endMs": 5000,
                            "durationMs": 5000,
                            "caption": "开场词句",
                            "screenIntent": "测试意图",
                            "sourcePageKey": "scene-01"
                        }
                    ]
                }
            ]
        }
        (self.edit_dir / "timeline").mkdir()
        (self.edit_dir / "timeline" / "timeline.json").write_text(
            json.dumps(self.timeline_data, ensure_ascii=False), encoding="utf-8"
        )

        # Mock subtitles.srt
        srt_content = "1\n00:00:00,000 --> 00:00:05,000\n开场词句测试字幕\n\n"
        (self.edit_dir / "subtitles.srt").write_text(srt_content, encoding="utf-8")

        # Mock SVG scene
        scenes_dir = self.tmp_dir / "scenes"
        scenes_dir.mkdir()
        (scenes_dir / "scene-01.svg").write_text(
            '<svg viewBox="0 0 1920 1080"><rect width="1920" height="1080" fill="#000"/></svg>',
            encoding="utf-8"
        )

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_build_review_data(self):
        data = build_review.build_review_data(self.tmp_dir, self.edit_dir, "auto")
        self.assertEqual(data["version"], "2.0.0")
        self.assertEqual(data["mode"], "composite")
        self.assertEqual(data["totalDurationMs"], 5000)
        self.assertIn("scene-01", data["svgs"])
        self.assertEqual(len(data["captions"]), 1)
        self.assertEqual(data["captions"][0]["text"], "开场词句测试字幕")

    def test_mode_override(self):
        data = build_review.build_review_data(self.tmp_dir, self.edit_dir, "speaker_only")
        self.assertEqual(data["mode"], "speaker_only")

    def test_write_review_files(self):
        data = build_review.build_review_data(self.tmp_dir, self.edit_dir, "auto")
        data_path, index_path = build_review.write_review_files(self.tmp_dir, data)
        self.assertTrue(data_path.is_file())
        self.assertTrue(index_path.is_file())

        # Assert {{REVIEW_BRIDGE}} was preserved
        content = index_path.read_text(encoding="utf-8")
        self.assertIn("{{REVIEW_BRIDGE}}", content)
        self.assertIn("window.__REVIEW_DATA__", content)


class TestServeReview(unittest.TestCase):
    def test_delegates_to_public_host(self):
        with patch.object(sys, 'argv', ['serve_review.py', '/tmp/fixture']), \
                patch.object(serve_review, 'build_review_data', return_value={}), \
                patch.object(serve_review, 'write_review_files'), \
                patch.object(serve_review, 'open_review', return_value={}) as host:
            serve_review.main()
            host.assert_called_once_with(Path('/tmp/fixture').resolve(), port=0, open_browser=False)


class TestExportVideo(unittest.TestCase):
    def test_resolve_paths(self):
        tmp_dir = Path(tempfile.mkdtemp(prefix="vc_test_export_")).resolve()
        edit_dir = tmp_dir / "edit"
        edit_dir.mkdir()
        (edit_dir / "edl.json").write_text("{}", encoding="utf-8")

        p_root, e_dir = export_video.resolve_project_paths(tmp_dir)
        self.assertEqual(p_root, tmp_dir)
        self.assertEqual(e_dir, edit_dir)

        p_root2, e_dir2 = export_video.resolve_project_paths(edit_dir)
        self.assertEqual(p_root2, tmp_dir)
        self.assertEqual(e_dir2, edit_dir)

        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
