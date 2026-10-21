#!/usr/bin/env python3
"""deliver.py：交付合成的两条硬判据 —— 有音轨、字幕安全区没有内容。

2026-10-21 的形态是「composition 只做画面层，人物与声音交付阶段贴回」。
这里用 1 秒的合成素材跑一遍真 ffmpeg，钉住两件事：
  · 成片必须真的有音轨（不是静音轨）；
  · 画面层若把内容画进 captionSafe 区域，必须报红 —— 否则字幕会压住画面。
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

import deliver  # noqa: E402


def _have(tool: str) -> bool:
    return shutil.which(tool) is not None


@unittest.skipUnless(_have("ffmpeg") and _have("ffprobe"), "需要 ffmpeg/ffprobe")
class DeliverIntegration(unittest.TestCase):
    def _fixture(self, tmp: Path, band_content: bool) -> Path:
        assets = tmp / "composition/assets"
        (tmp / "composition/_render").mkdir(parents=True, exist_ok=True)
        assets.mkdir(parents=True, exist_ok=True)
        box = "drawbox=x=700:y=200:w=1000:h=500:color=0xF2EBDD@1:t=fill"
        if band_content:  # 故意画进 y>880 的字幕区
            box += ",drawbox=x=700:y=920:w=1000:h=100:color=0xE2F827@1:t=fill"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                        "-i", "color=c=0x050607:s=1920x1080:r=30:d=1", "-vf", box,
                        "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        str(tmp / "composition/_render/visuals.mp4")], check=True)
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                        "-i", "testsrc2=s=720x1280:r=30:d=1", "-c:v", "libx264",
                        "-pix_fmt", "yuv420p", str(assets / "person.mp4")], check=True)
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                        "-i", "sine=frequency=440:duration=1", "-c:a", "aac",
                        str(assets / "audio.m4a")], check=True)
        (tmp / "recompose.json").write_text(json.dumps({
            "canvas": {"w": 1920, "h": 1080, "fps": 30},
            "personSlot": {"x": 0, "y": 0, "w": 500, "h": 1080},
            "captionSafe": {"x": 0, "y": 880, "w": 1920, "h": 200},
        }), encoding="utf-8")
        return tmp

    def _run(self, tmp: Path) -> dict:
        code = deliver.deliver(tmp, None, None, None, None, tmp / "成品", False, True, True)
        report = tmp / "成品" / f"{tmp.name}_核验报告.json"
        data = json.loads(report.read_text(encoding="utf-8")) if report.is_file() else {}
        data["exit"] = code
        return data

    def test_clean_visual_layer_passes_and_has_audio(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = self._fixture(Path(td) / "demo", band_content=False)
            tmp.mkdir(parents=True, exist_ok=True)
            data = self._run(tmp)
            self.assertEqual(data["exit"], 0, data)
            names = {c["name"]: c for c in data["checks"]}
            self.assertTrue(names["成片有音轨"]["ok"], names["成片有音轨"])
            self.assertTrue(names["字幕安全区无内容"]["ok"], names["字幕安全区无内容"])

    def test_no_person_layer_delivers_without_person(self):
        """纯画面 + 旁白的片子没有人物素材：--no-person 应该能出片，
        而不是把「人物素材缺失」当硬错误（recompose-mode 允许「仅画面层」）。"""
        with tempfile.TemporaryDirectory() as td:
            tmp = self._fixture(Path(td) / "demo", band_content=False)
            tmp.mkdir(parents=True, exist_ok=True)
            (tmp / "composition/assets/person.mp4").unlink()
            code = deliver.deliver(tmp, None, None, None, None, tmp / "成品",
                                   False, True, True, no_person=True)
            report = tmp / "成品" / f"{tmp.name}_核验报告.json"
            data = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(code, 0, data)
            self.assertTrue(data["ok"])
            self.assertTrue(any("无人物轨" in n for n in data["notes"]), data["notes"])

    def test_missing_person_still_red_without_flag(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = self._fixture(Path(td) / "demo", band_content=False)
            tmp.mkdir(parents=True, exist_ok=True)
            (tmp / "composition/assets/person.mp4").unlink()
            code = deliver.deliver(tmp, None, None, None, None, tmp / "成品",
                                   False, True, True)
            self.assertEqual(code, 1)

    def test_content_in_caption_band_goes_red(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = self._fixture(Path(td) / "demo", band_content=True)
            tmp.mkdir(parents=True, exist_ok=True)
            data = self._run(tmp)
            self.assertEqual(data["exit"], 1, data)
            names = {c["name"]: c for c in data["checks"]}
            self.assertFalse(names["字幕安全区无内容"]["ok"], names["字幕安全区无内容"])


if __name__ == "__main__":
    unittest.main()
