#!/usr/bin/env python3
"""单一时间源：画面由 timeline.json 驱动，字幕必须跟同一条时间轴。

背景：v1/v2/v3 三条片子的画面时间轴按 ED逐段名义时长、字幕却按渲染实测记录
（逐段向上取整，累计多 0.4–0.8s），交付后字幕尾部超出画面，没有任何检查发现。
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "helpers"))

import _edl  # noqa: E402
import _paths  # noqa: E402
import srt_export  # noqa: E402


class TimelineHelpers(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.edit = Path(self._tmp.name) / "demo" / "edit"
        self.edit.mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def write_timeline(self, *, end_ms=10_000, source=None):
        path = self.edit / "timeline" / "timeline.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"chapters": [{"steps": [{"startMs": 0, "endMs": end_ms}]}]}
        if source:
            payload["timeSource"] = source
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_timeline_found_in_edit_and_project(self):
        path = self.write_timeline()
        self.assertEqual(_paths.timeline_file(self.edit), path.resolve())
        path.unlink()
        project_timeline = self.edit.parent / "timeline" / "timeline.json"
        project_timeline.parent.mkdir()
        project_timeline.write_text('{"chapters":[]}', encoding="utf-8")
        self.assertEqual(_paths.timeline_file(self.edit), project_timeline.resolve())

    def test_span_and_source(self):
        path = self.write_timeline(end_ms=12_345, source="nominal")
        self.assertEqual(_paths.timeline_span_ms(path), 12345)
        self.assertEqual(_paths.timeline_source(path), "nominal")


class CaptionFollowsPictureTimeline(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.edit = Path(self._tmp.name) / "demo" / "edit"
        self.edit.mkdir(parents=True)
        self.edl = self.edit / "edl.json"
        self.edl.write_text(json.dumps({"ranges": [
            {"start": 0.0, "end": 5.0}, {"start": 5.0, "end": 10.0}]}), encoding="utf-8")
        digest = _edl.edl_digest(self.edl)
        (self.edit / "segment_durations.json").write_text(json.dumps({
            "final": {"durations": [5.2, 5.3], "total_s": 10.5, "edl_sha256": digest},
        }), encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def write_timeline(self, end_ms, source):
        path = self.edit / "timeline" / "timeline.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "chapters": [{"steps": [{"startMs": 0, "endMs": end_ms}]}],
            "timeSource": source}), encoding="utf-8")

    def test_nominal_timeline_ignores_render_record(self):
        self.write_timeline(10_000, "nominal")
        durations, source = srt_export._measured_durations(self.edit, self.edl, 2, strict=False)
        self.assertIsNone(durations)
        self.assertIsNone(source)

    def test_measured_timeline_uses_render_record(self):
        self.write_timeline(10_500, "measured")
        durations, source = srt_export._measured_durations(self.edit, self.edl, 2, strict=False)
        self.assertEqual(durations, [5.2, 5.3])
        self.assertEqual(source, "measured")

    def test_drift_guard_reports_two_time_sources(self):
        self.write_timeline(10_000, "nominal")
        self.assertIsNone(srt_export.timeline_drift_message(self.edit, 10.05))
        self.assertIsNone(srt_export.timeline_drift_message(self.edit, 9.0))  # 尾静音正常
        message = srt_export.timeline_drift_message(self.edit, 10.81)
        self.assertIsNotNone(message)
        self.assertIn("不是同一条时间轴", message)

    def test_unmarked_timeline_is_treated_as_nominal(self):
        path = self.edit / "timeline" / "timeline.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"chapters": [{"steps": [{"startMs": 0, "endMs": 10_500}]}]}),
                        encoding="utf-8")
        durations, source = srt_export._measured_durations(self.edit, self.edl, 2, strict=False)
        self.assertIsNone(durations)
        self.assertIsNone(source)


if __name__ == "__main__":
    unittest.main()
