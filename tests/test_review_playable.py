#!/usr/bin/env python3
"""check_review_playable 的纯逻辑单测（不启浏览器、不起宿主）。

浏览器断言那部分靠真实项目与 /tmp 夹具验收；这里钉住"取哪些 seek 点、期望时长怎么算"
这类一旦写错就会让检查**静默失效**的地方 —— 2026-10-21 的 0 秒事故里，
正是"看起来对的数字"让整轮排查走错方向。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

HELPERS = Path(__file__).parents[1] / "helpers"
sys.path.insert(0, str(HELPERS))

import check_review_playable as crp  # noqa: E402


class ExpectedDuration(unittest.TestCase):
    def test_prefers_totalDurationMs(self):
        self.assertEqual(crp._expected_duration({"totalDurationMs": 367610}), 367.61)

    def test_falls_back_to_timeline_chapters(self):
        data = {"timeline": {"chapters": [{"endMs": 20000}, {"endMs": 61000}]}}
        self.assertEqual(crp._expected_duration(data), 61.0)

    def test_none_when_nothing_known(self):
        self.assertIsNone(crp._expected_duration({}))


class SeekPoints(unittest.TestCase):
    def test_skips_zero_and_caps_at_three(self):
        data = {"beats": [{"startMs": 0}, {"startMs": 20000}, {"startMs": 110000},
                          {"startMs": 220000}, {"startMs": 350000}]}
        self.assertEqual(crp._seek_points(data, []), [20.6, 110.6, 220.6])

    def test_explicit_override_wins(self):
        self.assertEqual(crp._seek_points({"beats": [{"startMs": 5000}]}, [12.0, 30.0]),
                         [12.0, 30.0])

    def test_falls_back_to_timeline_steps(self):
        data = {"timeline": {"chapters": [{"steps": [{"startMs": 0}, {"startMs": 40000}]}]}}
        self.assertEqual(crp._seek_points(data, []), [40.6])


if __name__ == "__main__":
    unittest.main()
