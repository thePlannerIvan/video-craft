#!/usr/bin/env python3
"""实测总长必须按"剪辑指纹"认，不能按渲染文件名认。

回归背景：`render.py` 以输出名为键写 `segment_durations.json`，而
`timeline_derive` 曾经只读死键 `blob["cut"]`；真实项目里 8 个有 7 个叫
`final` / `preview` / `delivery` …，于是"按实测总长对齐"静默跳过。
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


if __name__ == "__main__":
    unittest.main()
