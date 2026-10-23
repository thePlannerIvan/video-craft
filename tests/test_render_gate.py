#!/usr/bin/env python3
"""No human submission covering the current review snapshot → no render.

2026-10-21: SKILL.md said "确认前不要渲染成片", and a 43-second film was rendered
anyway — the command itself checked nothing. This gate makes the sentence
executable: a submission whose `snapshot` equals the review's current snapshot,
and a source tree that has not drifted since that review was built.
"""
from __future__ import annotations

import json
import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path

HELPERS = Path(__file__).parents[1] / "helpers"
sys.path.insert(0, str(HELPERS))

import render_gate  # noqa: E402

SNAPSHOT = "abc123def456"


def _write_json(path: Path, doc) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")


class RenderGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name)
        self.edit = self.project / "edit"
        self.edit.mkdir()
        self.source = self.project / "composition" / "index.html"
        self.source.parent.mkdir()
        self.source.write_text("<html><body>draft</body></html>", encoding="utf-8")
        stat = self.source.stat()
        self.manifest = [{"path": "composition/index.html", "size": stat.st_size,
                          "mtime_ns": stat.st_mtime_ns, "sha256": hashlib.sha256(self.source.read_bytes()).hexdigest()}]

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _review(self) -> None:
        _write_json(self.project / "review" / "review_data.json", {
            "snapshot": SNAPSHOT,
            "sourceManifest": self.manifest,
        })

    def _submissions(self, *snapshots: str) -> None:
        _write_json(self.project / "review" / "review-submissions.json", {
            "records": [
                {"type": "text", "text": "看看", "snapshot": snap}
                for snap in snapshots
            ],
        })

    def test_no_review_data_blocks_and_says_how_to_start(self):
        report = render_gate.evaluate(self.project, None, False)
        self.assertFalse(report["ok"])
        self.assertTrue(any("build_review" in reason for reason in report["reasons"]),
                        report)
        self.assertEqual(render_gate.main([str(self.project)]), 2)

    def test_a_review_without_a_submission_blocks(self):
        self._review()
        report = render_gate.evaluate(self.project, None, False)
        self.assertFalse(report["ok"])
        self.assertTrue(any("没有任何人工提交" in r for r in report["reasons"]), report)
        self.assertEqual(render_gate.main([str(self.project)]), 1)

    def test_a_submission_for_the_current_snapshot_passes(self):
        self._review()
        self._submissions(SNAPSHOT)
        report = render_gate.evaluate(self.project, self.project / "final.mp4", False)
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["covering"], 1)
        self.assertEqual(render_gate.main([str(self.project)]), 0)

    def test_a_submission_for_an_older_snapshot_blocks(self):
        self._review()
        self._submissions("old000")
        report = render_gate.evaluate(self.project, None, False)
        self.assertFalse(report["ok"])
        self.assertEqual(report["covering"], 0)
        self.assertTrue(any("old000" in r for r in report["reasons"]), report)

    def test_source_drift_since_the_review_blocks_even_with_a_submission(self):
        self._review()
        self._submissions(SNAPSHOT)
        self.source.write_text("<html><body>changed after review</body></html>",
                               encoding="utf-8")
        report = render_gate.evaluate(self.project, None, False)
        self.assertFalse(report["ok"])
        self.assertTrue(any("源又改过" in r for r in report["reasons"]), report)

    def test_same_size_and_mtime_changed_content_blocks(self):
        self._review(); self._submissions(SNAPSHOT)
        stat = self.source.stat()
        self.source.write_bytes(self.source.read_bytes().replace(b'draft', b'other'))
        os.utime(self.source, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        self.assertFalse(render_gate.evaluate(self.project, None, False)['ok'])

    def test_missing_manifest_hash_or_critical_entry_blocks(self):
        for manifest in (None, [], [{}], [{k:v for k,v in self.manifest[0].items() if k != 'sha256'}]):
            with self.subTest(manifest=manifest):
                self.manifest = manifest
                self._review(); self._submissions(SNAPSHOT)
                self.assertFalse(render_gate.evaluate(self.project, None, False)['ok'])

    def test_surface_declared_feedback_file_is_read(self):
        self._review()
        _write_json(self.project / "review" / "review-surface.json", {
            "feedback": "subs.json",
        })
        _write_json(self.project / "review" / "subs.json", {
            "records": [{"snapshot": SNAPSHOT, "text": "这里"}],
        })
        report = render_gate.evaluate(self.project, None, False)
        self.assertTrue(report["ok"], report)

    def test_feedback_jsonl_records_count(self):
        self._review()
        path = self.project / "feedback" / "ch01.jsonl"
        path.parent.mkdir()
        path.write_text(json.dumps({"snapshot": SNAPSHOT, "text": "改这里"},
                                   ensure_ascii=False) + "\n", encoding="utf-8")
        report = render_gate.evaluate(self.project, None, False)
        self.assertTrue(report["ok"], report)

    def test_engineering_preview_is_allowed_only_under_engineering(self):
        out = self.edit / "_engineering" / "cut.mp4"
        report = render_gate.evaluate(self.project, out, True)
        self.assertTrue(report["ok"], report)
        self.assertTrue(report.get("engineeringBypass"))
        # The same switch must not be a way to render the deliverable.
        blocked = render_gate.evaluate(self.project, self.project / "final.mp4", True)
        self.assertFalse(blocked["ok"])
        self.assertTrue(any("edit/_engineering" in r for r in blocked["reasons"]))
        # And it needs an output at all.
        self.assertFalse(render_gate.evaluate(self.project, None, True)["ok"])


if __name__ == "__main__":
    unittest.main()
