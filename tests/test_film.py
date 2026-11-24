#!/usr/bin/env python3
"""film.py：原页拆解闸门。

2026-10-21 的根因是"没读原页就先动手"，所以这道闸门必须能变红：没填口播列 / 没映射
beat / 处置不合法，任何一种都要挡住 composition。
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HELPERS = Path(__file__).parents[1] / "helpers"
sys.path.insert(0, str(HELPERS))
sys.path.insert(0, str(HELPERS / "_internal"))
sys.path.insert(0, str(HELPERS / "_internal"))

import film  # noqa: E402

SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1920 1080">
  <rect x="0" y="0" width="1920" height="1080" fill="#F5F5F2"/>
  <text x="100" y="168" font-size="52" font-weight="900">BBDO 的 GWTB：用四个词逼问品牌真正的定位策略</text>
  <rect x="100" y="225" width="400" height="570" fill="#1A1A1A"/>
  <text x="140" y="300" font-size="70" fill="#E2F827">GET</text>
  <text x="140" y="556" font-size="18">拒绝泛化的人口统计标签，锁定特定生活情境的精准切片。</text>
  <text x="100" y="1010" font-size="18">IVAN · 从 4A 方法论到生产力系统</text>
  <text x="1820" y="1010" font-size="18">06 / 27</text>
  <line x1="140" y1="408" x2="460" y2="408" stroke="#3A3A3A"/>
  <circle cx="107" cy="74" r="8" fill="#E5322B"/>
</svg>
"""


def _project(tmp: Path) -> Path:
    (tmp / "recompose").mkdir(parents=True, exist_ok=True)
    (tmp / "recompose/lines.json").write_text(json.dumps(
        {"beats": [{"id": "ch01", "title": "开场"}, {"id": "ch02", "title": "GWTB"}]}),
        encoding="utf-8")
    (tmp / "composition").mkdir(exist_ok=True)
    (tmp / "page.svg").write_text(SVG, encoding="utf-8")
    return tmp


class Extract(unittest.TestCase):
    def test_reads_elements_and_prefills_disposition(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = _project(Path(td))
            elements = film.extract_elements(tmp / "page.svg")
            kinds = {e["kind"] for e in elements}
            self.assertIn("字", kinds)
            self.assertIn("框", kinds)
            # 页脚署名与页码必须预填为"删"，长句预填为"拆"，大字号关键概念"保留"
            actions = {e["text"]: e["action"] for e in elements if e["kind"] == "字"}
            self.assertEqual(actions["06 / 27"], "删")
            self.assertEqual(actions["IVAN · 从 4A 方法论到生产力系统"], "删")
            self.assertEqual(actions["GET"], "保留")
            long_line = [a for t, a in actions.items() if t.startswith("拒绝泛化")][0]
            self.assertEqual(long_line, "拆")

    def test_structural_archive_badges_are_preserved_not_deleted(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            svg_file = tmp / "collage.svg"
            svg_file.write_text(
                '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1920 1080">'
                '<text x="100" y="80" font-size="16">REF-01</text>'
                '<text x="100" y="120" font-size="16">STEP 01</text>'
                '<text x="1820" y="1010" font-size="18">06 / 27</text>'
                '</svg>',
                encoding="utf-8",
            )
            elements = film.extract_elements(svg_file)
            actions = {e["text"]: e["action"] for e in elements if e["kind"] == "字"}
            self.assertEqual(actions["REF-01"], "保留")
            self.assertEqual(actions["STEP 01"], "保留")
            self.assertEqual(actions["06 / 27"], "删")

    def test_line_and_circle_keep_their_geometry(self):
        """线用 x1/y1/x2/y2、点用 cx/cy；只读 x/y 会让它们全落在 (0,0)，
        拆解表里就分不清哪根线对应哪句口播。"""
        with tempfile.TemporaryDirectory() as td:
            tmp = _project(Path(td))
            elements = film.extract_elements(tmp / "page.svg")
            line = next(e for e in elements if e["kind"] == "线")
            self.assertEqual((line["x"], line["y"]), (140.0, 408.0))
            self.assertEqual((line["info"]["x2"], line["info"]["y2"]), (460.0, 408.0))
            dot = next(e for e in elements if e["kind"] == "点")
            self.assertEqual((dot["x"], dot["y"]), (107.0, 74.0))
            self.assertEqual(dot["info"]["r"], 8.0)


class Gate(unittest.TestCase):
    def test_outline_then_verify_red_then_green(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = _project(Path(td))
            self.assertEqual(film.cmd_outline(tmp, "page_04", tmp / "page.svg"), 0)
            # 没映射 → 红
            self.assertEqual(film.cmd_verify(tmp, as_json=True), 1)
            film.write_map(tmp, ["ch01=page_04", "ch02=page_04"])
            # 口播列还空着 → 仍然红
            self.assertEqual(film.cmd_verify(tmp, as_json=True), 1)
            # 填满 → 绿
            md = (tmp / "pages/page_04.md")
            lines = []
            for line in md.read_text(encoding="utf-8").splitlines():
                if line.startswith("|") and line.count("|") >= 8 and not line.startswith("| #"):
                    cells = line.rstrip("|").split("|")
                    if not cells[-1].strip():
                        cells[-1] = " 这句口播 "
                    line = "|".join(cells) + "|"
                lines.append(line)
            text = "\n".join(lines).replace(
                "（一句话。写不出来说明还没读懂原页 —— 回去再读。）",
                "用四个词逼问品牌定位。")
            md.write_text(text, encoding="utf-8")
            self.assertEqual(film.cmd_verify(tmp, as_json=True), 0)


class FourTierVisualPlan(unittest.TestCase):
    def test_v2_four_tier_plan_passes_without_legacy_pages(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            rec_dir = tmp / "recordings"
            rec_dir.mkdir(parents=True)
            demo_src = rec_dir / "screen.mp4"
            demo_src.write_bytes(b"hd-demo")
            (tmp / "visual-plan.json").write_text(json.dumps({
                "version": 2,
                "reference": {"styleNote": "配色参考", "keyframeSvgs": ["ref/slide_01.svg"]},
                "segments": [
                    {"id": "seg-01", "beatId": "b1", "tier": "talk-only", "startMs": 0, "endMs": 2000},
                    {"id": "seg-02", "beatId": "b2", "tier": "logic-diagram", "startMs": 2000, "endMs": 6000,
                     "hero": "三圆交集", "anchors": ["非遗", "传习", "商业"]},
                    {"id": "seg-03", "beatId": "b3", "tier": "theory-board", "startMs": 6000, "endMs": 10000,
                     "hero": "四步法则", "anchors": ["看人", "演逻辑", "拆模型", "看实操"], "focusMode": "spotlight"},
                    {"id": "seg-04", "beatId": "b4", "tier": "demo-footage", "startMs": 10000, "endMs": 14000,
                     "demo": {"source": "recordings/screen.mp4", "inSec": 1.0, "outSec": 5.0, "speed": 1.0}},
                ],
            }, ensure_ascii=False), encoding="utf-8")
            self.assertFalse((tmp / "pages").exists())
            self.assertEqual(film.cmd_verify(tmp, as_json=True), 0)

    def test_v2_rejects_demo_source_inside_composition_assets(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            assets = tmp / "composition" / "assets"
            assets.mkdir(parents=True)
            bad = assets / "big_recording.mp4"
            bad.write_bytes(b"hd")
            (tmp / "visual-plan.json").write_text(json.dumps({
                "version": 2,
                "segments": [
                    {"id": "seg-demo", "beatId": "b1", "tier": "demo-footage", "startMs": 0, "endMs": 3000,
                     "demo": {"source": "composition/assets/big_recording.mp4", "inSec": 0.0, "outSec": 3.0}},
                ],
            }), encoding="utf-8")
            self.assertEqual(film.cmd_verify(tmp, as_json=True), 1)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "需要 ffmpeg/ffprobe")
    def test_v2_proxy_generates_lightweight_review_proxy_without_touching_composition(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            (tmp / "recordings").mkdir(parents=True)
            comp_assets = tmp / "composition" / "assets"
            comp_assets.mkdir(parents=True)
            hd_src = tmp / "recordings" / "hd_demo.mp4"
            subprocess.run([
                "ffmpeg", "-y", "-v", "error",
                "-f", "lavfi", "-i", "color=c=0x1E293B:s=1280x720:r=30:d=2",
                "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                str(hd_src),
            ], check=True)
            (tmp / "visual-plan.json").write_text(json.dumps({
                "version": 2,
                "segments": [
                    {"id": "seg-demo", "beatId": "b1", "tier": "demo-footage", "startMs": 0, "endMs": 1300,
                     "demo": {"source": "recordings/hd_demo.mp4", "inSec": 0.2, "outSec": 1.5}},
                ],
            }), encoding="utf-8")
            self.assertEqual(film.cmd_proxy(tmp, max_width=640, crf=30, as_json=True), 0)
            plan = json.loads((tmp / "visual-plan.json").read_text(encoding="utf-8"))
            proxy_rel = plan["segments"][0]["demo"]["proxy"]
            self.assertEqual(proxy_rel, "review/demo_proxies/seg-demo.mp4")
            proxy_path = tmp / proxy_rel
            self.assertTrue(proxy_path.is_file())
            self.assertEqual(list(comp_assets.iterdir()), [])
            info = json.loads(subprocess.check_output([
                "ffprobe", "-v", "error", "-print_format", "json", "-show_streams", str(proxy_path),
            ], text=True))
            v_streams = [s for s in info["streams"] if s["codec_type"] == "video"]
            a_streams = [s for s in info["streams"] if s["codec_type"] == "audio"]
            self.assertEqual(len(v_streams), 1)
            self.assertLessEqual(v_streams[0]["width"], 640)
            self.assertEqual(len(a_streams), 0)


if __name__ == "__main__":
    unittest.main()
