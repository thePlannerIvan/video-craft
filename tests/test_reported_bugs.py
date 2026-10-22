#!/usr/bin/env python3
"""独立验收抓到的回归：时间轴总长、帧量化、projected 时间源。"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "helpers"))

import _edl  # noqa: E402
import duration_plan  # noqa: E402
import srt_export  # noqa: E402
import timeline_derive  # noqa: E402


class TotalDuration(unittest.TestCase):
    def test_total_is_last_end_not_the_span(self):
        entries = [{"startMs": 260, "endMs": 1000, "text": "甲", "segment": 0,
                    "wordIndices": [], "sourceRange": [0, 1]}]
        grouping = {"chapters": [{"id": "main", "title": "主段",
                                  "steps": [{"cueIndices": [0]}]}]}
        timeline, _durations = timeline_derive.build_timeline(entries, grouping)
        self.assertEqual(timeline["totalDurationMs"], 1000)


class FrameQuantisation(unittest.TestCase):
    def test_six_decimal_duration_does_not_gain_a_frame(self):
        with tempfile.TemporaryDirectory() as tmp:
            edit = Path(tmp) / "edit"
            edit.mkdir()
            (edit / "edl.json").write_text(json.dumps({"ranges": [
                {"source": "s", "start": 0.0, "end": 190.666667}]}), encoding="utf-8")
            durations, rate = duration_plan.plan_durations(edit, fps=30)
        self.assertEqual(rate, 30.0)
        self.assertAlmostEqual(durations[0], 5720 / 30, places=6)


class ProjectedTimeline(unittest.TestCase):
    def _edit(self, tmp: Path) -> Path:
        edit = tmp / "edit"
        edit.mkdir()
        edl = edit / "edl.json"
        edl.write_text(json.dumps({"ranges": [
            {"start": 0.0, "end": 5.0}, {"start": 5.0, "end": 10.0}]}), encoding="utf-8")
        digest = _edl.edl_digest(edl)
        (edit / "segment_durations.json").write_text(json.dumps({
            "final": {"durations": [5.1, 5.2], "total_s": 10.3, "edl_sha256": digest},
            "plan": {"durations": [5.05, 5.15], "total_s": 10.2,
                     "edl_sha256": digest, "projected": True},
        }), encoding="utf-8")
        timeline = edit / "timeline" / "timeline.json"
        timeline.parent.mkdir()
        timeline.write_text(json.dumps({
            "chapters": [{"steps": [{"startMs": 0, "endMs": 10200}]}],
            "timeSource": "projected"}), encoding="utf-8")
        return edit

    def test_duration_record_can_require_projected(self):
        with tempfile.TemporaryDirectory() as tmp:
            edit = self._edit(Path(tmp))
            durations, source, tag, problem = _edl.duration_record(
                edit, 2, require_projected=True)
        self.assertEqual(durations, [5.05, 5.15])
        self.assertEqual(source, "projected")
        self.assertIsNone(problem)

    def test_captions_use_projected_record_when_timeline_says_projected(self):
        with tempfile.TemporaryDirectory() as tmp:
            edit = self._edit(Path(tmp))
            durations, source = srt_export._measured_durations(
                edit, edit / "edl.json", 2, strict=False)
        self.assertEqual(durations, [5.05, 5.15])
        self.assertEqual(source, "projected")


if __name__ == "__main__":
    unittest.main()
