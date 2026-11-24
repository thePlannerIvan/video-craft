#!/usr/bin/env python3
"""实测总长必须按"剪辑指纹"认，不能按渲染文件名认。

回归背景：`render.py` 以输出名为键写 `segment_durations.json`，而
`timeline_derive` 曾经只读死键 `blob["cut"]`；真实项目里 8 个有 7 个叫
`final` / `preview` / `delivery` …，于是"按实测总长对齐"静默跳过。
"""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "helpers"))
sys.path.insert(0, str(ROOT / "helpers" / "_internal"))

import _edl  # noqa: E402


class MeasuredTotal(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.edit = Path(self._tmp.name)
        self.edl = self.edit / "edl.json"
        self.edl.write_text(json.dumps({"ranges": [{"start": 0, "end": 12.5}]}), encoding="utf-8")
        self.digest = _edl.edl_digest(self.edl)

    def tearDown(self):
        self._tmp.cleanup()

    def write_records(self, blob: dict) -> None:
        (self.edit / "segment_durations.json").write_text(json.dumps(blob), encoding="utf-8")

    def test_record_is_found_by_digest_whatever_the_name(self):
        self.write_records({
            "preview": {"durations": [1.0], "total_s": 9.0, "edl_sha256": "old"},
            "final": {"durations": [1.0], "total_s": 12.5, "edl_sha256": self.digest},
        })
        ms, how, tag = _edl.measured_total_ms(self.edit)
        self.assertEqual((ms, how, tag), (12500, "digest", "final"))

    def test_no_digest_falls_back_to_newest_and_says_so(self):
        self.write_records({
            "first": {"durations": [1.0], "total_s": 8.0},
            "second": {"durations": [1.0], "total_s": 11.0},
        })
        ms, how, tag = _edl.measured_total_ms(self.edit)
        self.assertEqual((ms, how, tag), (11000, "no-digest", "second"))

    def test_stale_records_are_refused_not_guessed(self):
        self.write_records({
            "final": {"durations": [1.0], "total_s": 12.5, "edl_sha256": "previous-edit"},
        })
        ms, how, _tag = _edl.measured_total_ms(self.edit)
        self.assertIsNone(ms)
        self.assertEqual(how, "mismatch")

    def test_projected_records_are_not_measured_evidence(self):
        self.write_records({
            "final": {"durations": [1.0], "total_s": 12.5, "edl_sha256": self.digest,
                      "projected": True},
        })
        ms, how, _tag = _edl.measured_total_ms(self.edit)
        self.assertIsNone(ms)

    def test_missing_record_file_is_reported(self):
        ms, how, _tag = _edl.measured_total_ms(self.edit)
        self.assertIsNone(ms)
        self.assertEqual(how, "none")

    def test_legacy_list_schema_counts_as_a_guess(self):
        """老项目记录是 `{输出名: [每段秒数]}`：没有指纹，按推定用最新一条。"""
        self.write_records({
            "preview": [1.0, 2.0],
            "final": [1.0, 2.5, 3.0],
        })
        ms, how, tag = _edl.measured_total_ms(self.edit)
        self.assertEqual((ms, how, tag), (6500, "no-digest", "final"))

    def test_directory_copy_and_formatting_keep_digest_and_measured_match(self):
        v1 = {
            "version": 1,
            "sources": {
                "B": "/workspace/creator/projects/my-film-v1/raw/b_roll.mp4",
                "A": "/workspace/creator/projects/my-film-v1/raw/talk.mp4",
            },
            "ranges": [
                {"source": "A", "start": 0.0, "end": 12.5, "beat": "HOOK", "quote": "原话", "reason": "初版"},
            ],
            "total_duration_s": 12.5,
        }
        v2 = {
            "total_duration_s": 12.5,
            "ranges": [
                {"reason": "迁移目录后润色注释", "quote": "改标点", "beat": "HOOK", "end": 12.5000, "start": 0, "source": "A"},
            ],
            "sources": {
                "A": "/Volumes/SSD/copied-film-v2/assets/talk.mp4",
                "B": "/Volumes/SSD/copied-film-v2/assets/b_roll.mp4",
            },
            "version": 2,
        }
        self.edl.write_text(json.dumps(v1, ensure_ascii=False), encoding="utf-8")
        digest_v1 = _edl.edl_digest(self.edl)
        expected_canonical = (
            '{"ranges":[{"beat":"HOOK","end":12.5,"source":"A","start":0.0}],'
            '"sources":{"A":"talk.mp4","B":"b_roll.mp4"}}'
        ).encode("utf-8")
        self.assertEqual(digest_v1, hashlib.sha256(expected_canonical).hexdigest())
        self.write_records({
            "final": {"durations": [12.5], "total_s": 12.5, "edl_sha256": digest_v1},
        })

        self.edl.write_text(json.dumps(v2, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self.assertNotEqual(_edl.edl_raw_digest(self.edl), digest_v1)
        self.assertEqual(_edl.edl_digest(self.edl), digest_v1)
        ms, how, tag = _edl.measured_total_ms(self.edit)
        self.assertEqual((ms, how, tag), (12500, "digest", "final"))

    def test_structural_edits_and_source_rename_cause_mismatch(self):
        base = {
            "sources": {"A": "/tmp/v1/talk.mp4", "B": "/tmp/v1/b.mp4"},
            "ranges": [
                {"source": "A", "start": 0.0, "end": 5.0, "beat": "HOOK", "speed": 1.0},
                {"source": "B", "start": 5.0, "end": 12.5, "beat": "BODY"},
            ],
        }
        self.edl.write_text(json.dumps(base), encoding="utf-8")
        base_digest = _edl.edl_digest(self.edl)
        self.write_records({
            "final": {"durations": [5.0, 7.5], "total_s": 12.5, "edl_sha256": base_digest},
        })

        mutations = {
            "change_start": {
                **base,
                "ranges": [
                    {"source": "A", "start": 0.05, "end": 5.0, "beat": "HOOK", "speed": 1.0},
                    base["ranges"][1],
                ],
            },
            "change_end": {
                **base,
                "ranges": [
                    {"source": "A", "start": 0.0, "end": 5.1, "beat": "HOOK", "speed": 1.0},
                    base["ranges"][1],
                ],
            },
            "change_beat": {
                **base,
                "ranges": [
                    {"source": "A", "start": 0.0, "end": 5.0, "beat": "OTHER", "speed": 1.0},
                    base["ranges"][1],
                ],
            },
            "change_speed": {
                **base,
                "ranges": [
                    {"source": "A", "start": 0.0, "end": 5.0, "beat": "HOOK", "speed": 1.5},
                    base["ranges"][1],
                ],
            },
            "add_range": {
                **base,
                "ranges": [*base["ranges"], {"source": "A", "start": 13.0, "end": 14.0}],
            },
            "remove_range": {
                **base,
                "ranges": [base["ranges"][0]],
            },
            "reorder_ranges": {
                **base,
                "ranges": [base["ranges"][1], base["ranges"][0]],
            },
            "rename_source_file": {
                **base,
                "sources": {"A": "/tmp/v1/talk_retake.mp4", "B": "/tmp/v1/b.mp4"},
            },
        }
        for label, mutated in mutations.items():
            with self.subTest(mutation=label):
                self.edl.write_text(json.dumps(mutated), encoding="utf-8")
                self.assertNotEqual(_edl.edl_digest(self.edl), base_digest)
                ms, how, tag = _edl.measured_total_ms(self.edit)
                self.assertEqual((ms, how, tag), (None, "mismatch", "final"))

    def test_invalid_or_nondict_edl_falls_back_to_raw_digest(self):
        for raw_payload in (b"{not valid json", b"[1, 2, 3]"):
            with self.subTest(payload=raw_payload):
                self.edl.write_bytes(raw_payload)
                self.assertEqual(
                    _edl.edl_digest(self.edl),
                    hashlib.sha256(raw_payload).hexdigest(),
                )


if __name__ == "__main__":
    unittest.main()
