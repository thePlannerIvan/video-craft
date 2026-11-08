#!/usr/bin/env python3
"""`frame` 的结构保证：token 一改，三个产物跟着变，且画框的硬约束还在。

哈雷片的画框是临场手写 PIL 脚本画的：坐标、字距、人物位圆、overlay 的透明区
都在会话里现算，换项目就得重写一遍，改一个数也没人核对。这里把「参考页 → token
→ base / overlay / spec」固化成工具后，用测试钉住四件容易静默坏掉的事：

1. 三件套的尺寸与模式（base 是 RGB、overlay 是 RGBA，差一个通道合成就变色）；
2. overlay 的透明区必须真透明，且素材带两条线真的压在 overlay 上（会盖住 base 的线）；
3. 人物位圆内保持空——画框最容易被肌理/颗粒/文字悄悄污染的地方；
4. spec.md 真的是从 token 生成的（文字与坐标对得上），而不是一份抄来的文档。

另外钉住两个运行契约：缺字段补默认值必须在 stderr 说明，退出码 0/1/2 不能混。
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

HELPERS = Path(__file__).parents[1] / "helpers"
FRAME = HELPERS / "frame.py"

# 与 references/frame-spec.md 里的竖屏示例同一份 token
TOKEN = {
    "canvas": {"width": 1080, "height": 1920, "fps": 30},
    "band": {"top": 320, "bottom": 1440, "inset": 90, "tick": 18},
    "palette": {
        "bg": "#0B0B0C",
        "band": "#121214",
        "line": "#000000",
        "text": "#F3F3F3",
        "muted": "#6E6E6A",
    },
    "texts": [
        {"id": "title-1", "text": "WEEKEND", "size": 32, "tracking": 7.7,
         "baseline": 161, "x": 90, "align": "left", "color": "text",
         "uppercase": True, "condense": 0.8},
        {"id": "title-2", "text": "OUTLAW", "size": 32, "tracking": 7.7,
         "baseline": 201, "x": 90, "align": "left", "color": "text",
         "uppercase": True, "condense": 0.8},
        {"id": "meta-1", "text": "CASE STUDY", "size": 11, "tracking": 2.0,
         "baseline": 166, "x": 990, "align": "right", "color": "muted",
         "uppercase": True, "condense": 1.0},
        {"id": "meta-2", "text": "OUTLAW MYTHOLOGY", "size": 11, "tracking": 2.0,
         "baseline": 181, "x": 990, "align": "right", "color": "muted",
         "uppercase": True, "condense": 1.0},
        {"id": "footer", "text": "MILWAUKEE, WISCONSIN · HARLEY-DAVIDSON",
         "size": 9, "tracking": 1.8, "baseline": 1842, "x": 90, "align": "left",
         "color": "muted", "uppercase": True, "condense": 1.0},
    ],
    "personSlot": {"cx": 540, "cy": 170, "r": 128,
                   "ringOffset": 5, "ringWidth": 1, "ringAlpha": 0.10},
    "cropMarks": {"inset": 40, "length": 18, "width": 1, "color": "line"},
    "grain": {"amplitude": 2, "dither": 1},
    "vignette": {"height": 28, "maxAlpha": 26, "color": "line"},
}


def run_frame(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(FRAME), *args],
                          capture_output=True, text=True)


def write_frames(root: Path) -> tuple[Path, Path]:
    """两张一眼能区分的占位帧：16:9 与 4:3，都是真实图片而不是色块。"""
    wide = Image.new("RGB", (1280, 720), (30, 40, 60))
    draw = ImageDraw.Draw(wide)
    draw.rectangle([0, 0, 640, 360], fill=(200, 70, 50))
    draw.ellipse([760, 220, 1080, 540], fill=(240, 220, 120))
    wide_path = root / "wide.png"
    wide.save(wide_path)

    tall = Image.new("RGB", (640, 480), (60, 60, 60))
    draw = ImageDraw.Draw(tall)
    draw.rectangle([0, 0, 320, 480], fill=(90, 160, 210))
    draw.rectangle([320, 120, 640, 360], fill=(250, 250, 250))
    tall_path = root / "tall.png"
    tall.save(tall_path)
    return wide_path, tall_path


class FrameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._tmp.name)
        cls.project = cls.root / "project"
        (cls.project / "material").mkdir(parents=True)
        cls.out = cls.project / "material" / "frame"
        cls.tokens = cls.root / "tokens.json"
        cls.tokens.write_text(json.dumps(TOKEN, ensure_ascii=False), encoding="utf-8")
        cls.wide, cls.tall = write_frames(cls.root)
        built = run_frame("build", str(cls.project), "--tokens", str(cls.tokens))
        if built.returncode != 0:
            raise RuntimeError(f"build 夹具失败：{built.stderr}")
        cls.build_stderr = built.stderr

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    # ── 三件套 ──────────────────────────────────────────────────────────
    def test_build_writes_three_products(self) -> None:
        base = self.out / "base.png"
        overlay = self.out / "overlay.png"
        spec = self.out / "spec.md"
        for path in (base, overlay, spec):
            self.assertTrue(path.is_file(), f"缺产物：{path}")
        with Image.open(base) as img:
            self.assertEqual(img.size, (1080, 1920))
            self.assertEqual(img.mode, "RGB")
        with Image.open(overlay) as img:
            self.assertEqual(img.size, (1080, 1920))
            self.assertEqual(img.mode, "RGBA")
        self.assertGreater(spec.stat().st_size, 500)

    def test_overlay_is_transparent_with_band_lines(self) -> None:
        with Image.open(self.out / "overlay.png") as img:
            alpha = img.convert("RGBA").getchannel("A")
            total = alpha.width * alpha.height
            transparent = alpha.histogram()[0]
            self.assertGreater(transparent / total, 0.90,
                               "overlay 的透明区没有真透明：会把素材整片压暗")
            # 素材带上下两条线必须在 overlay 上，且不透明
            for point in ((540, 320), (540, 1440), (90, 320), (990, 1440)):
                self.assertEqual(alpha.getpixel(point), 255, f"{point} 不是不透明线")
            # 带区中间保持透明：那里只该有素材
            self.assertEqual(alpha.getpixel((540, 700)), 0)
            self.assertEqual(alpha.getpixel((540, 960)), 0)

    def test_person_slot_stays_clean(self) -> None:
        """人物位空区里只允许有颗粒（±2 + 抖动 1），不能出现线/字/圆环。"""
        bg = (0x0B, 0x0B, 0x0C)
        with Image.open(self.out / "base.png") as img:
            worst = 0
            for x in range(540 - 60, 540 + 61, 4):
                for y in range(170 - 60, 170 + 61, 4):
                    pixel = img.getpixel((x, y))
                    worst = max(worst, max(abs(a - b) for a, b in zip(pixel, bg)))
        self.assertLessEqual(worst, 4, f"人物位圆内被画框污染（最大偏差 {worst}）")

    # ── spec.md ─────────────────────────────────────────────────────────
    def test_spec_is_generated_from_token(self) -> None:
        spec = (self.out / "spec.md").read_text(encoding="utf-8")
        for text in ("WEEKEND", "OUTLAW MYTHOLOGY",
                     "MILWAUKEE, WISCONSIN · HARLEY-DAVIDSON"):
            self.assertIn(text, spec)
        for coordinate in ("(90,320)", "(90,1440)", "(540,170)", "161", "201",
                           "7.7", "#F3F3F3", "#6E6E6A"):
            self.assertIn(coordinate, spec)
        self.assertIn("保持空", spec)
        self.assertIn("base.png", spec)
        self.assertIn("overlay.png", spec)
        self.assertIn("花字", spec)

    # ── preview ─────────────────────────────────────────────────────────
    def test_preview_is_two_canvases_side_by_side(self) -> None:
        out = self.root / "preview.jpg"
        result = run_frame("preview", str(self.project), "--tokens", str(self.tokens),
                           "--wide", str(self.wide), "--tall", str(self.tall),
                           "--out", str(out))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(out.is_file())
        with Image.open(out) as img:
            self.assertEqual(img.size, (2160, 1920), "预览必须是左右两格 1:1 画布")
            self.assertEqual(img.mode, "RGB")
            # 两格素材不同，说明左右确实各贴了一张
            self.assertNotEqual(img.getpixel((540, 960)), img.getpixel((1620, 960)))

    # ── token 兜底与退出码 ───────────────────────────────────────────────
    def test_missing_fields_filled_from_defaults(self) -> None:
        tokens = self.root / "minimal.json"
        tokens.write_text(json.dumps({"canvas": {"width": 1080, "height": 1920}}),
                          encoding="utf-8")
        out = self.root / "minimal_out"
        result = run_frame("build", str(self.project), "--tokens", str(tokens),
                           "--out-dir", str(out))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("补默认值", result.stderr)
        self.assertIn("band", result.stderr)
        for name in ("base.png", "overlay.png", "spec.md"):
            self.assertTrue((out / name).is_file(), f"缺产物：{name}")

    def test_bad_token_exits_1_with_reason(self) -> None:
        tokens = self.root / "bad.json"
        tokens.write_text("{not json", encoding="utf-8")
        result = run_frame("build", str(self.project), "--tokens", str(tokens),
                           "--out-dir", str(self.root / "bad_out"))
        self.assertEqual(result.returncode, 1)
        self.assertIn("不是合法 JSON", result.stderr)

    def test_usage_error_exits_2(self) -> None:
        result = run_frame("build", str(self.project))
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
