#!/usr/bin/env python3
"""`montage` 的两个结构保证：坐标不混用，空镜不能蒙混过关。

2026-11 的哈雷片里，67 个镜头有 18 个渲成了「只有底图」的画面，ffmpeg 退 0、文件大小
正常、拼接也成功；花字还整体错位 41 秒。两个根因都是**坐标混用**：

- 素材入点 `in`（素材文件内的秒数）被当成了 EDL 源时间；
- 花字的词锚时间（源片时间）被直接当成了剪后时间。

这里钉住三件事：
1. `plan` 从「段 + 起始词」独立算出剪后时间，越界的入点必须被拒；
2. 花字的停留不得跨出所在镜头；
3. `check` 看得见像素：只有底图的镜头、缺渲染的镜头都必须 FAIL。
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HELPERS = Path(__file__).parents[1] / "helpers"
MONTAGE = HELPERS / "montage.py"
CHECK = HELPERS / "check_montage.py"


def ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-y", "-v", "error", *args], check=True)


class MontageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._tmp.name)
        cls.edit = cls.root / "edit"
        (cls.edit / "transcripts").mkdir(parents=True)
        (cls.root / "material").mkdir()
        # 两条素材：移动图案，避免统计值相同被误判成空镜
        for name in ("a", "b"):
            ffmpeg("-f", "lavfi", "-i", f"testsrc2=size=320x240:rate=30", "-t", "4",
                   "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "ultrafast",
                   str(cls.root / "material" / f"{name}.mp4"))
        # 画框底：深灰，用来判「只有底图」
        from PIL import Image
        cls.base = cls.root / "material" / "base.png"
        Image.new("RGB", (320, 640), (11, 11, 12)).save(cls.base)
        cls.edl = {
            "sources": {"A": str(cls.root / "material" / "a.mp4")},
            "ranges": [
                {"source": "A", "start": 0.0, "end": 2.0, "beat": "01", "quote": "一二"},
                {"source": "A", "start": 2.0, "end": 4.0, "beat": "02", "quote": "三四"},
            ],
        }
        (cls.edit / "edl.json").write_text(json.dumps(cls.edl, ensure_ascii=False), encoding="utf-8")
        words = []
        for i in range(16):                      # 0.25s 一词，覆盖 0–4s
            words.append({"text": "字", "type": "word", "start": round(i * 0.25, 3),
                          "end": round((i + 1) * 0.25, 3)})
        (cls.edit / "transcripts" / "A.json").write_text(
            json.dumps({"text": "字" * 16, "words": words}, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    # ── 夹具 ────────────────────────────────────────────────────────────
    def spec(self, shots: list[dict], labels: list[dict] | None = None) -> Path:
        spec = {
            "frame": {"width": 320, "height": 640, "fps": 30, "band": [120, 440],
                      "labelX": 20, "labelY": 360, "base": "material/base.png"},
            "grades": {"plain": "null"},
            "shots": [dict({"kind": "clip", "grade": "plain", "note": "t"}, **s) for s in shots],
            "labels": labels or [],
        }
        path = self.root / "spec.json"
        path.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
        return path

    def plan(self, spec: Path) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(MONTAGE), "plan", str(self.root),
                               "--shots", str(spec), "-o", str(self.root / "plan.json")],
                              capture_output=True, text=True)

    def plan_doc(self) -> dict:
        return json.loads((self.root / "plan.json").read_text(encoding="utf-8"))

    # ── plan ────────────────────────────────────────────────────────────
    def test_word_anchor_becomes_cut_time(self) -> None:
        """镜头从第 8 个词开始时，起点落在 2.0s（两词之间的停顿中点）。"""
        spec = self.spec([
            {"range": 1, "word": 0, "material": "material/a.mp4", "in": 0.0},
            {"range": 2, "word": 0, "material": "material/b.mp4", "in": 0.5},
        ])
        p = self.plan(spec)
        self.assertEqual(p.returncode, 0, p.stderr)
        doc = self.plan_doc()
        self.assertEqual(len(doc["shots"]), 2)
        self.assertAlmostEqual(doc["shots"][0]["dur"], 2.0, places=2)
        self.assertAlmostEqual(doc["shots"][1]["cutStart"], 2.0, places=2)
        # 素材入点保留在 in 里，不被 cutStart 覆盖
        self.assertAlmostEqual(doc["shots"][1]["in"], 0.5, places=3)
        self.assertAlmostEqual(doc["timeline"]["total"], 4.0, places=3)

    def test_rejects_in_point_beyond_material(self) -> None:
        """把素材入点写成 EDL 源时间（900s）必须被拒——这就是 18 个空镜的根因。"""
        spec = self.spec([{"range": 1, "word": 0, "material": "material/a.mp4", "in": 900.0},
                          {"range": 2, "word": 0, "material": "material/b.mp4", "in": 0.0}])
        p = self.plan(spec)
        self.assertEqual(p.returncode, 1)
        self.assertIn("入点越界", p.stderr)
        self.assertIn("素材入点", p.stderr)

    def test_rejects_duplicate_material(self) -> None:
        spec = self.spec([{"range": 1, "word": 0, "material": "material/a.mp4", "in": 0.0},
                          {"range": 2, "word": 0, "material": "material/a.mp4", "in": 0.0}])
        p = self.plan(spec)
        self.assertEqual(p.returncode, 1)
        self.assertIn("素材重复", p.stderr)

    def test_label_clamped_inside_its_shot(self) -> None:
        """花字词锚在镜头尾部 → 停留被钳到镜头结束前，且落在本镜头内。"""
        spec = self.spec([
            {"range": 1, "word": 0, "material": "material/a.mp4", "in": 0.0},
            {"range": 2, "word": 0, "material": "material/b.mp4", "in": 0.0},
        ], labels=[{"range": 1, "word": 7, "text": "测试花字", "hold": 9.0}])
        p = self.plan(spec)
        self.assertEqual(p.returncode, 0, p.stderr)
        lab = self.plan_doc()["labels"][0]
        shot = [s for s in self.plan_doc()["shots"] if s["seq"] == lab["shot"]][0]
        self.assertLessEqual(lab["t"] + lab["hold"], shot["cutStart"] + shot["dur"] + 1e-3)
        self.assertGreaterEqual(lab["hold"], 0.8)

    # ── check ───────────────────────────────────────────────────────────
    def _render_two_shots(self) -> Path:
        spec = self.spec([{"range": 1, "word": 0, "material": "material/a.mp4", "in": 0.0},
                          {"range": 2, "word": 0, "material": "material/b.mp4", "in": 0.0}])
        p = self.plan(spec)
        self.assertEqual(p.returncode, 0, p.stderr)
        work = self.root / f"work_{self._testMethodName}"   # 每个用例独立工作目录，避免缓存串味
        r = subprocess.run([sys.executable, str(MONTAGE), "render", str(self.root),
                            "--plan", str(self.root / "plan.json"), "--work", str(work)],
                           capture_output=True, text=True)
        self.assertIn(r.returncode, (0,), r.stderr)
        return work

    def check(self, work: Path | None) -> subprocess.CompletedProcess:
        args = [sys.executable, str(CHECK), str(self.root),
                "--plan", str(self.root / "plan.json"), "--json"]
        if work:
            args += ["--shots-dir", str(work)]
        return subprocess.run(args, capture_output=True, text=True)

    def test_check_passes_on_good_render(self) -> None:
        work = self._render_two_shots()
        p = self.check(work)
        result = json.loads(p.stdout)
        self.assertTrue(result["ok"], p.stdout)

    def test_check_flags_base_only_shot(self) -> None:
        """复刻当时的空镜：只渲染底图，检查必须 FAIL。"""
        work = self._render_two_shots()
        plan = self.plan_doc()
        dur = float(plan["shots"][0]["dur"])
        ffmpeg("-loop", "1", "-framerate", "30", "-i", str(self.base),
               "-t", f"{dur:.3f}", "-vf", "noise=alls=3:allf=t",
               "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
               "-r", "30", str(work / "shot_001.mp4"))
        p = self.check(work)
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertIn("底图", p.stdout)

    def test_check_flags_missing_shot(self) -> None:
        work = self._render_two_shots()
        (work / "shot_002.mp4").unlink()
        p = self.check(work)
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertIn("没渲染", p.stdout)


if __name__ == "__main__":
    unittest.main()
