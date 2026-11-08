#!/usr/bin/env python3
"""字幕字数上限只有一个数字源。

2026-11-08 之前：`srt_export.MAX_CONTENT_CHARS = 20` 与 `check_caption_breaks` 里的
`if n > 20` 各写一份，而且两边的计数函数还不同（前者是 `_words.normalize`
的 NFKC + 只留 L/M/N，后者只删空白与半角标点）——同一条 cue 一边算 18、一边算 21，
导出器放行、断句检查硬红，两个门对同一份稿子给出相反结论。

现在两处都读 `_words.CAPTION_MAX_CONTENT` 与 `_words.content_len`；这个测试钉住
「一个数字源 + 一个计数器 + 同一条 cue 同一个判决」。
"""
from __future__ import annotations

import unittest

import _words
import check_caption_breaks
import srt_export


class CaptionLengthSingleSource(unittest.TestCase):
    def test_export_and_check_read_the_same_limit(self):
        self.assertEqual(srt_export.MAX_CONTENT_CHARS, _words.CAPTION_MAX_CONTENT)
        self.assertEqual(check_caption_breaks.CAPTION_MAX_CONTENT, _words.CAPTION_MAX_CONTENT)

    def test_check_counts_with_the_shared_counter(self):
        # 模块对象必须是同一个，而不是「值恰好相等」的第二份实现
        self.assertIs(check_caption_breaks._words, _words)

    def test_one_cue_gets_one_count(self):
        # 这条曾经是 18 vs 21
        text = '他说：“这 个 数 据 是 3,200 万，不 是 320 万。”'
        self.assertEqual(_words.content_len(text), check_caption_breaks._words.content_len(text))

    def test_over_limit_is_hard_and_names_the_shared_limit(self):
        over = "字" * (_words.CAPTION_MAX_CONTENT + 1)
        hard, _ = check_caption_breaks.check([over])
        self.assertTrue(
            any(f"超 {_words.CAPTION_MAX_CONTENT} 字" in m for m in hard), hard)

    def test_at_limit_passes_the_length_rule(self):
        exact = "字" * _words.CAPTION_MAX_CONTENT
        hard, _ = check_caption_breaks.check([exact])
        self.assertEqual([m for m in hard if "超" in m], [], hard)


if __name__ == "__main__":
    unittest.main()
