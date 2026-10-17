#!/usr/bin/env python3
"""Tests for recompose mode: line-level density plan, review data, inbox."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

HELPERS = Path(__file__).resolve().parents[1] / "helpers"
sys.path.insert(0, str(HELPERS))

import recompose_plan  # noqa: E402
import review_inbox  # noqa: E402
import build_review  # noqa: E402

SRT = """1
00:00:00,000 --> 00:00:02,000
第一句

2
00:00:02,000 --> 00:00:05,000
第二句

3
00:00:05,000 --> 00:00:08,000
第三句
"""


def make_project(root: Path) -> Path:
    (root / "timeline").mkdir(parents=True)
    (root / "composition").mkdir()
    (root / "edit").mkdir()
    (root / "review").mkdir()
    (root / "composition" / "index.html").write_text("<!doctype html><div></div>", encoding="utf-8")
    (root / "edit" / "subtitles.srt").write_text(SRT, encoding="utf-8")
    timeline = {
        "source": "edl",
        "totalDurationMs": 8000,
        "chapters": [
            {"id": "beat-01", "title": "A", "steps": [
                {"id": "beat-01", "chapterId": "beat-01", "chapterTitle": "A", "startMs": 0, "endMs": 4000}]},
            {"id": "beat-02", "title": "B", "steps": [
                {"id": "beat-02", "chapterId": "beat-02", "chapterTitle": "B", "startMs": 4000, "endMs": 8000}]},
        ],
    }
    (root / "timeline" / "timeline.json").write_text(json.dumps(timeline), encoding="utf-8")
    (root / "review" / "review-surface.json").write_text(json.dumps({
        "contract_version": "review-surface/2.0.0",
        "id": "video-craft/visual",
        "title": "motion",
        "project_root": "..",
        "dir": "..",
        "entry": "review/index.html",
        "feedback": "review-submissions.json",
        "wake": {"mode": "steer", "text": "x"},
    }), encoding="utf-8")
    return root


def init(root: Path, **kw) -> dict:
    args = SimpleNamespace(
        draft=kw.get("draft", "recompose/draft.mp4"),
        composition=kw.get("composition", "composition"),
        person_slot=kw.get("person_slot", "0,0,620,1080"),
        caption_safe=kw.get("caption_safe", "0,885,1920,195"),
        canvas=kw.get("canvas", "1920x1080"),
        fps=str(kw.get("fps", 30)),
        board=kw.get("board", ""),
        force=kw.get("force", False),
    )
    return recompose_plan.init_project(root, args)


class RecomposeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = make_project(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_init_groups_lines_by_beat(self):
        result = init(self.root)
        self.assertTrue(result["ok"])
        self.assertEqual(result["lineCount"], 3)
        doc = json.loads((self.root / "recompose/lines.json").read_text(encoding="utf-8"))
        self.assertEqual([l["id"] for l in doc["lines"]], ["l001", "l002", "l003"])
        self.assertEqual([l["beatId"] for l in doc["lines"]], ["beat-01", "beat-01", "beat-02"])
        self.assertTrue(all(l["state"] == "auto" and l["proposal"] == "still" for l in doc["lines"]))

    def test_check_validates_states_and_slots(self):
        init(self.root)
        self.assertTrue(recompose_plan.check_project(self.root)["ok"])
        path = self.root / "recompose/lines.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["lines"][0]["state"] = "wat"
        path.write_text(json.dumps(doc), encoding="utf-8")
        report = recompose_plan.check_project(self.root)
        self.assertFalse(report["ok"])
        self.assertIn("state", " ".join(report["problems"]))

    def test_build_density_feeds_review_data(self):
        init(self.root)
        beats = [
            {"id": "beat-01", "title": "A", "startMs": 0, "endMs": 4000},
            {"id": "beat-02", "title": "B", "startMs": 4000, "endMs": 8000},
        ]
        density = build_review.build_density(self.root, beats, [])
        self.assertTrue(density["enabled"])
        self.assertEqual(density["lineCount"], 3)
        self.assertEqual(len(density["beats"][0]["lines"]), 2)
        self.assertEqual(len(density["beats"][1]["lines"]), 1)
        self.assertEqual(density["beats"][0]["lines"][0]["state"], "auto")

    def test_page_mode_keeps_density_disabled(self):
        (self.root / "recompose/lines.json").unlink(missing_ok=True)
        density = build_review.build_density(self.root, [], [])
        self.assertFalse(density["enabled"])

    def test_density_inbox_applies_and_is_idempotent(self):
        init(self.root)
        submissions = self.root / "review/review-submissions.json"
        submissions.write_text(json.dumps({"records": [{
            "phase": "density", "kind": "density",
            "createdAt": "2026-10-17T12:00:00.000Z",
            "lines": [
                {"id": "l001", "state": "off", "note": "只要字幕"},
                {"id": "l002", "state": "full", "note": ""},
                {"id": "l003", "state": "auto", "note": ""},
            ],
        }]}, ensure_ascii=False), encoding="utf-8")
        first = review_inbox.import_submissions(self.root)
        self.assertTrue(first["ok"], first)
        self.assertEqual(len(first["imported"]), 1)
        doc = json.loads((self.root / "recompose/lines.json").read_text(encoding="utf-8"))
        self.assertEqual(doc["lines"][0]["state"], "off")
        self.assertEqual(doc["lines"][0]["note"], "只要字幕")
        self.assertEqual(doc["lines"][1]["state"], "full")
        log = (self.root / "feedback/density.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(log), 1)

        second = review_inbox.import_submissions(self.root)
        self.assertEqual(len(second["imported"]), 0)
        self.assertEqual(len(second["skipped"]), 1)
        self.assertEqual(len((self.root / "feedback/density.jsonl").read_text(encoding="utf-8").splitlines()), 1)

    def test_density_inbox_rejects_unknown_line(self):
        init(self.root)
        submissions = self.root / "review/review-submissions.json"
        submissions.write_text(json.dumps({"records": [{
            "phase": "density",
            "lines": [{"id": "l999", "state": "off", "note": ""}],
        }]}), encoding="utf-8")
        result = review_inbox.import_submissions(self.root)
        self.assertFalse(result["ok"])
        self.assertEqual(len(result["imported"]), 0)
        self.assertTrue(result["rejected"][0]["reason"].startswith("未知 line id"))
        doc = json.loads((self.root / "recompose/lines.json").read_text(encoding="utf-8"))
        self.assertEqual(doc["lines"][0]["state"], "auto")

    def test_template_has_density_panel(self):
        template = (Path(__file__).resolve().parents[1] / "visual/assets/review-page-template.html").read_text(encoding="utf-8")
        self.assertIn("feedback-panel", template)
        self.assertIn("beat-switcher", template)
        self.assertIn("window.__vcReview", template)
        self.assertIn('phase: "density"', template)


if __name__ == "__main__":
    unittest.main()
