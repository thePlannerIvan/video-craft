#!/usr/bin/env python3
"""素材落位只有一个实现：渲染和画框预览必须算出同一块矩形。

2026-11 的画框工具第一次做出来时，预览用「4:3 按高铺满、裁两侧」，渲染用 contain，
两份口径差一次裁切——预览就不再是成片的预览。这里钉住三件事：

1. `fit_in_band` 的三个典型值（竖屏 1080×1920 / 素材带 320–1440）；
2. `frame.material_box` 与 `montage.py` 的渲染用的是同一个函数（不是同一条公式写两遍）；
3. 落位永远 contain：整幅可见，不裁素材。
"""
from __future__ import annotations

import ast
import importlib.util
import sys
import unittest
from pathlib import Path

HELPERS = Path(__file__).parents[1] / "helpers"
sys.path.insert(0, str(HELPERS))   # frame.py 顶层 `from _geometry import …`


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"craft_{name}", HELPERS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


geometry = _load("_geometry")
frame = _load("frame")

TOKEN = {"canvas": {"width": 1080, "height": 1920, "fps": 30},
         "band": {"top": 320, "bottom": 1440}}


class FitInBandTests(unittest.TestCase):
    def test_sixteen_by_nine_fills_width(self) -> None:
        self.assertEqual(geometry.fit_in_band(1920, 1080, 1080, 1120), (1080, 606))

    def test_four_by_three_fills_width(self) -> None:
        self.assertEqual(geometry.fit_in_band(640, 480, 1080, 1120), (1080, 810))

    def test_portrait_fills_band_height(self) -> None:
        w, h = geometry.fit_in_band(1393, 1800, 1080, 1120)
        self.assertEqual(h, 1120)
        self.assertLess(w, 1080)

    def test_never_crops_the_material(self) -> None:
        for sw, sh in ((1920, 1080), (640, 480), (1393, 1800)):
            fw, fh = geometry.fit_in_band(sw, sh, 1080, 1120)
            self.assertLessEqual(fw, 1080)
            self.assertLessEqual(fh, 1120)
            # contain：至少一边贴满，另一边不超
            self.assertTrue(fw == 1080 or fh == 1120)

    def test_rejects_bad_sizes(self) -> None:
        with self.assertRaises(ValueError):
            geometry.fit_in_band(0, 480, 1080, 1120)


class SharedWithRenderTests(unittest.TestCase):
    def test_montage_imports_the_same_function(self) -> None:
        source = (HELPERS / "montage.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "_geometry":
                imported |= {a.name for a in node.names}
        self.assertIn("fit_in_band", imported,
                      "montage.py 必须调 _geometry.fit_in_band，不能自己再写一套缩放")

    def test_material_box_matches_geometry(self) -> None:
        for sw, sh in ((640, 360), (640, 480), (1393, 1800)):
            x, y, fw, fh = frame.material_box(TOKEN, sw, sh)
            self.assertEqual((fw, fh), geometry.fit_in_band(sw, sh, 1080, 1120))
            self.assertEqual(x, (1080 - fw) // 2)
            self.assertEqual(y, 320 + (1120 - fh) // 2)


if __name__ == "__main__":
    unittest.main()
