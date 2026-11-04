#!/usr/bin/env python3
"""The picture track can diverge from the composition while every other gate is green.

2026-11-04 品牌屋: `hyperframes render -w 4` exited 0, `check` green, 30fps/310.333s,
motion plenty, no black frames — and from ~78s on the house was not drawn at all.
These tests pin the two decisions inside `check_render_fidelity.py` that keep it
usable as a gate: a one-frame-offset frame still matches, and a nearly-black frame
is judged by ink collapse rather than by a correlation that is pure noise.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

HELPERS = Path(__file__).parents[1] / "helpers"
sys.path.insert(0, str(HELPERS))

import check_render_fidelity as fid  # noqa: E402

W, H = fid.W, fid.H


def frame(paint) -> list[int]:
    out = [0] * (W * H)
    paint(out)
    return out


def house(offset: int = 0, ink: int = 255) -> list[int]:
    """A crude 'roof + bands' drawing: rows of ink with a couple of gaps."""
    def paint(buf: list[int]) -> None:
        for y in range(20 + offset, 40 + offset):
            for x in range(30, 130):
                buf[y * W + x] = ink
        for y in range(45 + offset, 55 + offset):
            for x in range(10, 150):
                buf[y * W + x] = ink
    return frame(paint)


class FidelityMath(unittest.TestCase):
    def test_identical_frames_match(self) -> None:
        a, ink_a = fid.blur_refs_ink(house())
        b, ink_b = fid.blur_refs_ink(house())
        self.assertEqual(ink_a, ink_b)
        self.assertGreater(fid.correlation(a, b), 0.999)

    def test_one_pixel_offset_still_matches(self) -> None:
        """抽帧差一帧不该判红：160×90 网格上 1px ≈ 1080p 的 12px，模糊就是为吸收这点偏移。

        实测 1px→0.966、2px→0.888：闸门容忍约 1% 画幅的错位。运动更快的镜头
        （甩镜、快速推拉）在相邻帧间位移大于这个量级时会误报 —— 看提示里给的时间点再定。
        """
        a, _ = fid.blur_refs_ink(house())
        b, _ = fid.blur_refs_ink(house(offset=1))
        self.assertGreater(fid.correlation(a, b), 0.93)

    def test_lost_content_is_visible_in_ink(self) -> None:
        """整栋没画 = 墨量塌掉，结构相关直接掉到 0。"""
        _, ink_ref = fid.blur_refs_ink(house())
        _, ink_lost = fid.blur_refs_ink(frame(lambda buf: None))
        self.assertGreater(ink_ref, 100)
        self.assertEqual(ink_lost, 0)
        self.assertLess(ink_lost * fid.LOST, ink_ref)

    def test_nearly_black_frames_are_not_judged_by_correlation(self) -> None:
        """两张都接近全黑时相关系数只是噪声：低墨量帧只查内容塌没塌。"""
        speck_a = frame(lambda buf: buf.__setitem__(10 * W + 10, 200))
        speck_b = frame(lambda buf: buf.__setitem__(60 * W + 120, 200))
        a, ink_a = fid.blur_refs_ink(speck_a)
        b, ink_b = fid.blur_refs_ink(speck_b)
        self.assertLess(max(ink_a, ink_b), fid.LOW_INK)
        self.assertLess(fid.correlation(a, b), 0.93)      # 相关性判不出来
        # 与 main() 同一条判据：低墨量帧忽略相关性，只看有没有塌
        low_content = max(ink_a, ink_b) < fid.LOW_INK
        lost = ink_b > 0 and ink_a * fid.LOST < ink_b
        self.assertFalse(lost)
        self.assertTrue(low_content)


if __name__ == "__main__":
    unittest.main()
