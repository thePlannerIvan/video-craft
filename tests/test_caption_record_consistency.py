#!/usr/bin/env python3
"""Captions and delivery must cite the same render record.

v3 audit: one EDL, two records with the same digest — first [1.1, 0.9],
last [1.0, 1.0], same total. srt_export took the FIRST, verify_delivery took the
LAST, so captions were built on a different timeline than the film was checked
against and cmp on the EDL could not see it. The policy now lives in
`_edl.duration_record`; this test pins "last matching measured wins" and that the
caption path calls it.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

HELPERS = Path(__file__).parents[1] / "helpers"
sys.path.insert(0, str(HELPERS))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"craft_{name}", HELPERS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


_edl = _load("_edl")


class CaptionRecordConsistency(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.edit = Path(self.tmp.name)
        (self.edit / "edl.json").write_text(json.dumps({
            "sources": {"SRC": "/tmp/x.mp4"},
            "ranges": [{"source": "SRC", "start": 0.0, "end": 1.0},
                       {"source": "SRC", "start": 1.0, "end": 2.0}],
        }), encoding="utf-8")
        digest = _edl.edl_digest(self.edit / "edl.json")
        (self.edit / "segment_durations.json").write_text(json.dumps({
            "poc": {"edl_sha256": digest, "durations": [1.1, 0.9]},
            "final": {"edl_sha256": digest, "durations": [1.0, 1.0]},
        }), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_last_matching_record_wins(self):
        durations, source, tag, problem = _edl.duration_record(self.edit, 2)
        self.assertEqual(durations, [1.0, 1.0])
        self.assertEqual(source, "measured")
        self.assertEqual(tag, "final")
        self.assertIsNone(problem)

    def test_caption_path_uses_the_same_record(self):
        srt_export = _load("srt_export")
        durations, source = srt_export._measured_durations(self.edit, self.edit / "edl.json", 2, False)
        self.assertEqual(durations, [1.0, 1.0])
        self.assertEqual(source, "measured")

    def test_projection_is_only_a_fallback(self):
        digest = _edl.edl_digest(self.edit / "edl.json")
        (self.edit / "segment_durations.json").write_text(json.dumps({
            "plan": {"edl_sha256": digest, "projected": True, "durations": [1.05, 0.95]},
        }), encoding="utf-8")
        durations, source, tag, problem = _edl.duration_record(self.edit, 2)
        self.assertEqual(durations, [1.05, 0.95])
        self.assertEqual(source, "projected")
        self.assertIsNone(problem)


    def test_explicit_edl_path_selects_its_own_record(self):
        # srt_export --edl may point outside edit_dir/edl.json; the digest must
        # follow the EDL in use, not the default one.
        other = self.edit / "other-edl.json"
        other.write_text(self.edit.joinpath("edl.json").read_text(), encoding="utf-8")
        other_digest = _edl.edl_digest(other)
        (self.edit / "edl.json").write_text('{"sources": {}, "ranges": []}', encoding="utf-8")
        (self.edit / "segment_durations.json").write_text(json.dumps({
            "final": {"edl_sha256": other_digest, "durations": [1.0, 1.0]},
        }), encoding="utf-8")
        durations, source, tag, problem = _edl.duration_record(self.edit, 2, edl_path=other)
        self.assertEqual(durations, [1.0, 1.0])
        self.assertEqual(source, "measured")
        # and the default EDL now has no matching record
        durations, source, tag, problem = _edl.duration_record(self.edit, 2)
        self.assertIsNone(durations)
        self.assertIn("哈希不符", problem or "")


    def test_legacy_record_without_digest_is_used(self):
        # pre-digest projects: verify_delivery accepts the newest no-digest record
        # via select_render_record; captions must not fall back to nominal time.
        (self.edit / "segment_durations.json").write_text(json.dumps({
            "final": {"durations": [0.9, 1.1]},
        }), encoding="utf-8")
        durations, source, tag, problem = _edl.duration_record(self.edit, 2)
        self.assertEqual(durations, [0.9, 1.1])
        self.assertEqual(source, "measured")
        self.assertEqual(tag, "final")
        self.assertIsNone(problem)


    def test_agrees_with_select_render_record(self):
        # One policy, two callers: whenever a record fits the segment count,
        # duration_record and select_render_record must name the same tag.
        scenarios = [
            {},  # digest-matched measured + projected
            {"drop_digest": True},  # legacy records
            {"only_projected": True},
        ]
        for case in scenarios:
            digest = _edl.edl_digest(self.edit / "edl.json")
            records = {
                "poc": {"durations": [1.1, 0.9]},
                "final": {"durations": [1.0, 1.0]},
                "plan": {"projected": True, "durations": [1.05, 0.95]},
            }
            if not case.get("drop_digest"):
                for entry in records.values():
                    entry["edl_sha256"] = digest
            if case.get("only_projected"):
                records = {"plan": records["plan"]}
            (self.edit / "segment_durations.json").write_text(json.dumps(records), encoding="utf-8")
            durations, source, tag, problem = _edl.duration_record(self.edit, 2)
            select_tag, select_entry, how = _edl.select_render_record(
                json.loads((self.edit / "segment_durations.json").read_text()), digest,
                allow_projected=source == "projected")
            if durations is not None:
                self.assertEqual(tag, select_tag, (case, tag, select_tag))


if __name__ == "__main__":
    unittest.main()
