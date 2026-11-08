#!/usr/bin/env python3
"""成片态审阅（final-cut）的合法入口。

蒙太奇片做完只有 `edit/edl.json` + `edit/montage-plan.json` + 一份渲好的成片，
没有 composition。旧行为把它判成 `page`（已退休的旧十步页），只能加 `--allow-page`
硬开——文档说 page 退休了，但 montage 项目没有替代入口。这里钉住四条：

1. 有 `montage-plan.json` → 不带 `--allow-page` 也退 0，`buildMode == "final-cut"`；
2. 没有 `montage-plan.json`、也不给 `--final-cut` → 仍退 2（page 拒绝不变）；
3. 没有 `montage-plan.json` 但显式 `--final-cut` → 退 0，`buildMode == "final-cut"`；
4. `--allow-page` 对旧 page 项目仍能构建（回归）。

成片用 ffmpeg 生成 2 秒小视频，不连网、不跑渲染与浏览器。
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
HELPERS = SKILL / "helpers"
BUILD_REVIEW = HELPERS / "build_review.py"
FFMPEG = shutil.which("ffmpeg") is not None


def _tiny_final(path: Path) -> None:
    """2 秒、带音轨的小成片：够 build_review 认成 compositeVideo 即可。"""
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y",
         "-f", "lavfi", "-i", "color=c=#203040:s=320x180:d=2:r=30",
         "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo:d=2",
         "-c:v", "libx264", "-preset", "ultrafast", "-crf", "30",
         "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)],
        check=True)


@unittest.skipUnless(FFMPEG, "ffmpeg required")
class FinalCutBuildModeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls._template = Path(cls._tmp.name) / "final.mp4"
        _tiny_final(cls._template)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def setUp(self) -> None:
        self._case = tempfile.TemporaryDirectory()
        self.project = Path(self._case.name) / "demo"
        (self.project / "edit").mkdir(parents=True)
        (self.project / "review").mkdir()
        shutil.copy(self._template, self.project / "edit" / "final.mp4")
        (self.project / "edit" / "edl.json").write_text(json.dumps({
            "sources": {"A": "edit/final.mp4"},
            "ranges": [
                {"source": "A", "start": 0.0, "end": 1.0,
                 "beat": "01", "quote": "第一句"},
                {"source": "A", "start": 1.0, "end": 2.0,
                 "beat": "02", "quote": "第二句"},
            ],
        }, ensure_ascii=False), encoding="utf-8")
        (self.project / "review" / "media.json").write_text(json.dumps({
            "compositeVideo": "edit/final.mp4",
        }), encoding="utf-8")

    def tearDown(self) -> None:
        self._case.cleanup()

    # ── 夹具 ────────────────────────────────────────────────────────────
    def add_montage_plan(self) -> None:
        (self.project / "edit" / "montage-plan.json").write_text(
            json.dumps({"version": "montage-plan/1", "shots": [
                {"seq": 1, "cutStart": 0.0, "dur": 2.0},
            ]}, ensure_ascii=False), encoding="utf-8")

    def build(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(BUILD_REVIEW), str(self.project), *args],
            capture_output=True, text=True, timeout=60)

    def review_data(self) -> dict:
        path = self.project / "review" / "review_data.json"
        return json.loads(path.read_text(encoding="utf-8"))

    # ── 用例 ────────────────────────────────────────────────────────────
    def test_montage_plan_gets_final_cut_without_allow_page(self) -> None:
        """蒙太奇项目：成片态是合法审阅形态，不该再要 --allow-page。"""
        self.add_montage_plan()
        proc = self.build()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        data = self.review_data()
        self.assertEqual(data["buildMode"], "final-cut")
        self.assertIs(data["media"]["layersBaked"], True)
        self.assertIn(data["mode"], {"composite", "speaker_only"})
        # 页面顶部要能看出这是成片态、没有工程态，别让作者当成工程快照。
        html = (self.project / "review" / "index.html").read_text(encoding="utf-8")
        self.assertIn("成片态·无工程态", html)

    def test_no_montage_plan_still_rejected_as_page(self) -> None:
        """没有 montage 计划、也没声明 --final-cut：page 拒绝逻辑保持原样。"""
        proc = self.build()
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("已退休", proc.stderr)
        self.assertFalse((self.project / "review" / "review_data.json").exists())

    def test_explicit_final_cut_flag_builds(self) -> None:
        """只有渲好的成片、没有 montage 计划：显式 --final-cut 是合法入口。"""
        proc = self.build("--final-cut")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        data = self.review_data()
        self.assertEqual(data["buildMode"], "final-cut")
        self.assertIs(data["media"]["layersBaked"], True)

    def test_allow_page_keeps_old_projects_working(self) -> None:
        """--allow-page 仍能构建旧 page 十步页（回归不能破）。"""
        proc = self.build("--allow-page")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(self.review_data()["buildMode"], "page")


if __name__ == "__main__":
    unittest.main()

class ReviewEntryModeTests(unittest.TestCase):
    """`review.py` 是给人用的唯一入口：成片态项目不能卡在入口闸门上。

    batch 4 先只改了 build_review.py，入口仍会因为没有 recompose.json 退 2 ——
    文档说「跑 review.py」，实际跑不通，等于把临时开法（--allow-page）留在了流程里。
    """

    def setUp(self) -> None:
        import importlib.util
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "edit").mkdir()
        spec = importlib.util.spec_from_file_location("craft_review", HELPERS / "review.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        self.review = mod

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_montage_project_resolves_to_final_cut(self) -> None:
        (self.root / "edit" / "montage-plan.json").write_text("{}", encoding="utf-8")
        self.assertEqual(self.review.resolve_review_mode(self.root), "final-cut")

    def test_recompose_project_still_wins(self) -> None:
        (self.root / "edit" / "montage-plan.json").write_text("{}", encoding="utf-8")
        (self.root / "recompose.json").write_text("{}", encoding="utf-8")
        self.assertEqual(self.review.resolve_review_mode(self.root), "recompose")

    def test_explicit_flag_for_final_cut_only_project(self) -> None:
        self.assertEqual(self.review.resolve_review_mode(self.root, final_cut=True), "final-cut")
        with self.assertRaises(SystemExit) as ctx:
            self.review.resolve_review_mode(self.root)
        self.assertEqual(ctx.exception.code, 2)

