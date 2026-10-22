#!/usr/bin/env python3
"""时间码/SRT 统一入口的契约。

这是合并地图 M1 的第一步：先把"唯一一份解析"写对，暂不迁调用方；
等价性用老项目的真实字幕另做验收（见本文件末尾的说明）。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "helpers"))

import _timecode  # noqa: E402


SAMPLE = """1
00:00:01,000 --> 00:00:02,500
第一句

2
00:00:03.250 --> 00:00:04,000
第二句
换行的一行
"""


class TimeParsing(unittest.TestCase):
    def test_parse_accepts_comma_and_dot(self):
        self.assertEqual(_timecode.parse_time("00:00:01,500"), 1500)
        self.assertEqual(_timecode.parse_time("00:00:01.500"), 1500)

    def test_parse_accepts_one_digit_hour(self):
        self.assertEqual(_timecode.parse_time("0:00:02,000"), 2000)

    def test_format_round_trips(self):
        for ms in (0, 1500, 62_500, 3_600_000, 7_123_456):
            self.assertEqual(_timecode.parse_time(_timecode.format_time(ms)), ms)

    def test_format_dot_separator(self):
        self.assertEqual(_timecode.format_time(62_500, sep="."), "00:01:02.500")

    def test_unknown_time_is_rejected(self):
        with self.assertRaises(_timecode.TimecodeError):
            _timecode.parse_time("1:2")


class SrtParsing(unittest.TestCase):
    def test_parses_cues(self):
        cues = _timecode.parse_srt_text(SAMPLE)
        self.assertEqual([c["index"] for c in cues], [1, 2])
        self.assertEqual((cues[0]["startMs"], cues[0]["endMs"]), (1000, 2500))
        self.assertEqual(_timecode.flatten(cues[0]), "第一句")
        self.assertEqual(_timecode.flatten(cues[1], " "), "第二句 换行的一行")
        self.assertEqual(_timecode.flatten(cues[1], ""), "第二句换行的一行")

    def test_tolerates_bom_and_crlf(self):
        text = ("\ufeff1\r\n00:00:01,000 --> 00:00:02,000\r\n带 BOM 的字幕\r\n")
        cues = _timecode.parse_srt_text(text)
        self.assertEqual(len(cues), 1)
        self.assertEqual(_timecode.flatten(cues[0]), "带 BOM 的字幕")

    def test_missing_index_gets_sequential_number(self):
        text = "00:00:01,000 --> 00:00:02,000\n没序号\n\n00:00:03,000 --> 00:00:04,000\n第二条\n"
        cues = _timecode.parse_srt_text(text)
        self.assertEqual([c["index"] for c in cues], [1, 2])

    def test_end_before_start_is_rejected(self):
        with self.assertRaises(_timecode.TimecodeError):
            _timecode.parse_srt_text("1\n00:00:05,000 --> 00:00:04,000\n倒序\n")

    def test_loose_reader_skips_malformed_blocks(self):
        """旧调用方对畸形字幕是跳过；宽松读取保留这个语义。"""
        text = "1\n00:00:01,000 --> 00:00:02,000\n好的\n\n2\n乱码时间 --> 壞\n跳过\n"
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.srt"
            path.write_text(text, encoding="utf-8")
            cues = _timecode.parse_srt_file_loose(path)
        self.assertEqual(len(cues), 1)
        self.assertEqual((cues[0]["startMs"], cues[0]["endMs"]), (1000, 2000))


if __name__ == "__main__":
    unittest.main()
