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
import subprocess
import shutil
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

    def test_explicit_measured_upgrade_ignores_old_projected_timeline(self):
        self.write_timeline(10_000, "projected")
        self.assertEqual(srt_export._measured_durations(self.edit, self.edl, 2, True,
                                                       time_source="measured"),
                         ([5.2, 5.3], "measured"))

    def test_measured_label_cannot_fall_back_to_projection(self):
        self.write_timeline(10_000, "measured")
        path = self.edit / "segment_durations.json"
        data = json.loads(path.read_text()); data["final"]["projected"] = True
        path.write_text(json.dumps(data))
        with self.assertRaises(SystemExit):
            srt_export._measured_durations(self.edit, self.edl, 2, True)

    def test_measured_request_refuses_missing_or_weak_evidence(self):
        path = self.edit / "segment_durations.json"
        original = json.loads(path.read_text())
        for change in ({"edl_sha256": "stale"}, {"edl_sha256": None},
                       {"durations": [5.2]}, {"durations": [0, float('nan')]}):
            data = json.loads(json.dumps(original)); data["final"].update(change)
            path.write_text(json.dumps(data))
            with self.subTest(change=change), self.assertRaises(SystemExit):
                srt_export._measured_durations(self.edit, self.edl, 2, True,
                                               time_source="measured")

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "needs ffmpeg/ffprobe")
    def test_cli_projected_to_measured_preserves_reviewed_lines(self):
        self.edl.write_text(json.dumps({"sources": {"A": "/tmp/A.mp4"}, "ranges": [
            {"source": "A", "start": 0, "end": 1}, {"source": "A", "start": 1, "end": 2}]}))
        (self.edit / "transcripts").mkdir()
        (self.edit / "transcripts/A.json").write_text(json.dumps({"words": [
            {"type": "word", "text": "你好", "start": .1, "end": .8},
            {"type": "word", "text": "世界", "start": 1.1, "end": 1.8}]}))
        record = {"projected": {"durations": [1., 1.], "total_s": 2.,
                                "projected": True, "edl_sha256": _edl.edl_digest(self.edl)}}
        duration_file = self.edit / "segment_durations.json"
        duration_file.write_text(json.dumps(record))
        timeline = self.edit / "timeline/timeline.json"
        timeline.parent.mkdir()
        grouping = timeline.parent / "grouping.json"
        grouping.write_text(json.dumps({"chapters": [{"id": "ch", "steps": [
            {"id": "one", "cueIndices": [0]}, {"id": "two", "cueIndices": [1]}]}]}))
        def cli(tool, *args):
            p = subprocess.run([sys.executable, str(ROOT / "helpers" / tool), str(self.edit), *map(str,args)],
                               capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        cli("srt_export.py", "--prepare", "--time-source", "projected")
        lines = self.edit / "semantic_lines.txt"; lines.write_text("你好\n\n世界\n")
        cli("srt_export.py", "--lock"); cli("srt_export.py", "--build")
        cli("timeline_derive.py", "--grouping", grouping, "--output-timeline", timeline)
        self.assertEqual(json.loads(timeline.read_text())["timeSource"], "projected")
        measured = []
        for index, length in enumerate((1.1, 1.2)):
            media = self.edit / f"measured-{index}.mp4"
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                            f"color=c=white:s=64x64:r=10:d={length}", "-c:v", "libx264", str(media)], check=True)
            p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                "-of", "default=nw=1:nk=1", str(media)], capture_output=True, text=True, check=True)
            measured.append(float(p.stdout))
        record["real"] = {"durations": measured, "total_s": sum(measured), "edl_sha256": _edl.edl_digest(self.edl)}
        duration_file.write_text(json.dumps(record))
        cli("srt_export.py", "--prepare", "--force-prepare", "--time-source", "measured")
        self.assertEqual(lines.read_text(), "你好\n\n世界\n")
        cli("srt_export.py", "--lock"); cli("srt_export.py", "--build")
        words = json.loads((self.edit / "caption_words.json").read_text())
        self.assertEqual(words["timeline_source"], "measured")
        self.assertAlmostEqual(words["segments"][1]["output_start"], 1.1)
        self.assertAlmostEqual(words["total_duration"], 2.3)
        cli("timeline_derive.py", "--grouping", grouping, "--output-timeline", timeline)
        cli("srt_export.py", "--check")
        self.assertEqual(json.loads(timeline.read_text())["measuredTotalMs"], 2300)


if __name__ == "__main__":
    unittest.main()
