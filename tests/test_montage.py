#!/usr/bin/env python3
"""`montage` 的结构保证：坐标不混用、空镜不能蒙混过关、交付件必须过闸门。

2026-11 的哈雷片里，67 个镜头有 18 个渲成了「只有底图」的画面，ffmpeg 退 0、文件大小
正常、拼接也成功；花字还整体错位 41 秒。两个根因都是**坐标混用**：

- 素材入点 `in`（素材文件内的秒数）被当成了 EDL 源时间；
- 花字的词锚时间（源片时间）被直接当成了剪后时间。

这里钉住的是「用户能看见的结果」：退出码、打印语、文件落点。

1. `plan` 从「段 + 起始词」独立算出剪后时间，越界的入点必须被拒；
2. 花字的停留不得跨出所在镜头；
3. 素材唯一性：入点差 < 5s 拒、照片第二次出现拒，两个门（plan / check）结论一致；
4. 素材清单门：没登记 / summary 空 / usable=false 都不许 plan；
5. EDL 里的变速与静音段明确拒绝，不静默算错；
6. `render --concat` 默认只写审阅素材；写交付件要 `--deliver` + 人工提交覆盖快照；
7. `voice-cut` 按 EDL 剪竖屏人物轨，实测时长与计划差 > 0.5s 失败。
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HELPERS = Path(__file__).parents[1] / "helpers"
MONTAGE = HELPERS / "montage.py"
CHECK = HELPERS / "check_montage.py"
SCAN = HELPERS / "scan_materials.py"
SNAPSHOT = "abc123def456"


def ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-y", "-v", "error", *args], check=True)


def ffprobe(path: Path) -> dict:
    p = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "stream=codec_type,width,height:format=duration",
                        "-of", "json", str(path)],
                       capture_output=True, text=True, check=True)
    return json.loads(p.stdout)


def write_inventory(directory: Path, rows: list[dict]) -> Path:
    path = directory / "material-inventory.json"
    path.write_text(json.dumps({"version": "material-inventory/1", "root": str(directory),
                                "rows": rows}, ensure_ascii=False, indent=1),
                    encoding="utf-8")
    return path


def inv_row(path: Path, summary: str = "工厂门口 · 全景 · 黑白 · 无字",
            usable=None) -> dict:
    return {"path": str(path), "name": path.name, "duration": 4.0, "size": "320x240",
            "usable": usable, "summary": summary, "watermark": "", "source": ""}


class MontageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._tmp.name)
        cls.edit = cls.root / "edit"
        (cls.edit / "transcripts").mkdir(parents=True)
        cls.material = cls.root / "material"
        cls.material.mkdir()
        # 三条素材：移动图案，避免统计值相同被误判成空镜；long 用来试入点间距
        for name, seconds in (("a", 4), ("b", 4), ("long", 20)):
            ffmpeg("-f", "lavfi", "-i", "testsrc2=size=320x240:rate=30", "-t", str(seconds),
                   "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "ultrafast",
                   str(cls.material / f"{name}.mp4"))
        # 画框底：深灰，用来判「只有底图」；照片是另一张图，用来判照片重复
        from PIL import Image
        cls.base = cls.material / "base.png"
        Image.new("RGB", (320, 640), (11, 11, 12)).save(cls.base)
        cls.photo = cls.material / "photo.png"
        Image.new("RGB", (320, 240), (60, 90, 160)).save(cls.photo)
        write_inventory(cls.material, [
            inv_row(cls.material / "a.mp4", "车队 · 中景 · 彩色 · 无字"),
            inv_row(cls.material / "b.mp4", "公路 · 全景 · 彩色 · 无字"),
            inv_row(cls.material / "long.mp4", "城市 · 全景 · 黑白 · 无字"),
            inv_row(cls.photo, "厂房 · 全景 · 彩色 · 无字"),
        ])
        # 没有清单的素材目录（清单门必须退 1，不静默放行）
        cls.material2 = cls.root / "material2"
        cls.material2.mkdir()
        shutil.copy2(cls.material / "a.mp4", cls.material2 / "x.mp4")
        # 清单有行但没填好：x 缺 summary、y 标了不可用、z 合格
        cls.material3 = cls.root / "material3"
        cls.material3.mkdir()
        for name in ("x", "y", "z"):
            shutil.copy2(cls.material / "a.mp4", cls.material3 / f"{name}.mp4")
        write_inventory(cls.material3, [
            inv_row(cls.material3 / "x.mp4", summary=""),
            inv_row(cls.material3 / "y.mp4", summary="喷漆车间 · 中景 · 彩色", usable=False),
            inv_row(cls.material3 / "z.mp4", summary="装配线 · 全景 · 彩色 · 无字"),
        ])
        # proxy 母版：voice-cut 要提示「交付用母版不用 proxy」
        shutil.copy2(cls.material / "a.mp4", cls.material / "proxy_master.mp4")
        # 口播音轨 + 素材扫描专用目录
        cls.audio = cls.root / "audio.m4a"
        ffmpeg("-f", "lavfi", "-i", "sine=frequency=440:duration=4", "-c:a", "aac", str(cls.audio))
        cls.scan_dir = cls.root / "material_scan"
        cls.scan_dir.mkdir()
        shutil.copy2(cls.material / "a.mp4", cls.scan_dir / "clip.mp4")

        cls.edl = {
            "sources": {"A": str(cls.material / "a.mp4")},
            "ranges": [
                {"source": "A", "start": 0.0, "end": 2.0, "beat": "01", "quote": "一二"},
                {"source": "A", "start": 2.0, "end": 4.0, "beat": "02", "quote": "三四"},
            ],
        }
        (cls.edit / "edl.json").write_text(json.dumps(cls.edl, ensure_ascii=False),
                                           encoding="utf-8")
        words = []
        for i in range(16):                      # 0.25s 一词，覆盖 0–4s
            words.append({"text": "字", "type": "word", "start": round(i * 0.25, 3),
                          "end": round((i + 1) * 0.25, 3)})
        (cls.edit / "transcripts" / "A.json").write_text(
            json.dumps({"text": "字" * 16, "words": words}, ensure_ascii=False),
            encoding="utf-8")

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    # ── 夹具 ────────────────────────────────────────────────────────────
    def project(self, name: str) -> Path:
        """独立项目根：交付闸门用例必须各自有审阅状态，不能共用。"""
        root = self.root / name
        (root / "edit" / "transcripts").mkdir(parents=True)
        shutil.copy2(self.edit / "edl.json", root / "edit" / "edl.json")
        shutil.copy2(self.edit / "transcripts" / "A.json",
                     root / "edit" / "transcripts" / "A.json")
        return root

    def spec(self, shots: list[dict], labels: list[dict] | None = None,
             root: Path | None = None) -> Path:
        root = root or self.root
        spec = {
            "frame": {"width": 320, "height": 640, "fps": 30, "band": [120, 440],
                      "labelX": 20, "labelY": 360, "base": "material/base.png"},
            "grades": {"plain": "null"},
            "shots": [dict({"kind": "clip", "grade": "plain", "note": "t"}, **s) for s in shots],
            "labels": labels or [],
        }
        path = root / "spec.json"
        path.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
        return path

    def plan(self, spec: Path, root: Path | None = None) -> subprocess.CompletedProcess:
        root = root or self.root
        return subprocess.run([sys.executable, str(MONTAGE), "plan", str(root),
                               "--shots", str(spec), "-o", str(root / "plan.json")],
                              capture_output=True, text=True)

    def plan_doc(self, root: Path | None = None) -> dict:
        root = root or self.root
        return json.loads((root / "plan.json").read_text(encoding="utf-8"))

    def render(self, root: Path, work: Path, *extra: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(MONTAGE), "render", str(root),
                               "--plan", str(root / "plan.json"), "--work", str(work),
                               *extra], capture_output=True, text=True)

    def check(self, root: Path | None = None, work: Path | None = None,
              plan: Path | None = None) -> subprocess.CompletedProcess:
        root = root or self.root
        args = [sys.executable, str(CHECK), str(root),
                "--plan", str(plan or (root / "plan.json")), "--json"]
        if work:
            args += ["--shots-dir", str(work)]
        return subprocess.run(args, capture_output=True, text=True)

    def voice_cut(self, *extra: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(MONTAGE), "voice-cut", str(self.root),
                               *extra], capture_output=True, text=True)

    def write_plan(self, total: float = 4.0, width: int = 320, height: int = 640,
                   fps: int = 30) -> Path:
        path = self.edit / "montage-plan.json"
        path.write_text(json.dumps({
            "version": "montage-plan/1",
            "frame": {"width": width, "height": height, "fps": fps},
            "timeline": {"total": total},
            "shots": [],
        }), encoding="utf-8")
        return path

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

    # ── 素材唯一性（一个判据，两个门） ──────────────────────────────────
    def _long_pair(self, second_in: float, root: Path | None = None) -> subprocess.CompletedProcess:
        material = str(self.material / "long.mp4")
        spec = self.spec([{"range": 1, "word": 0, "material": material, "in": 0.0},
                          {"range": 2, "word": 0, "material": material, "in": second_in}],
                         root=root)
        return self.plan(spec, root=root)

    def test_reuse_gap_allows_just_under_ten_seconds(self) -> None:
        """入点差 9.9s ≥ 5s：同一素材的两段不同画面，放行。"""
        p = self._long_pair(9.9)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertAlmostEqual(self.plan_doc()["minReuseGap"], 5.0, places=3)

    def test_reuse_gap_rejects_under_five_seconds(self) -> None:
        """入点差 4.9s < 5s：同一段画面又用一次，拒（旧的 //10 分桶会漏）。"""
        p = self._long_pair(4.9)
        self.assertEqual(p.returncode, 1)
        self.assertIn("素材重复", p.stderr)
        self.assertIn("4.9", p.stderr)

    def test_photo_second_appearance_is_rejected(self) -> None:
        """照片没有入点：同一张图第二次出现即判重（不再有照片豁免）。"""
        photo = str(self.photo)
        spec = self.spec([
            {"range": 1, "word": 0, "kind": "photo", "material": photo},
            {"range": 2, "word": 0, "kind": "photo", "material": photo},
        ])
        p = self.plan(spec)
        self.assertEqual(p.returncode, 1)
        self.assertIn("素材重复", p.stderr)
        self.assertIn("照片", p.stderr)

    def test_check_and_plan_share_the_reuse_verdict(self) -> None:
        """同一个计划：plan 放行的，check 不报重；把入点改近，两个门都判重。"""
        root = self.project("reuse_agree")
        p = self._long_pair(9.9, root=root)
        self.assertEqual(p.returncode, 0, p.stderr)
        ok = json.loads(self.check(root=root).stdout)
        self.assertTrue(ok["ok"], ok)
        self.assertFalse([m for m in ok["hard"] if "素材重复" in m], ok["hard"])

        doc = self.plan_doc(root=root)
        doc["shots"][1]["in"] = 4.9          # 与第 1 镜的入点差 4.9s < 5s：同一段画面
        mutated = root / "plan-duplicate.json"
        mutated.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        bad = self.check(root=root, plan=mutated)
        self.assertEqual(bad.returncode, 1, bad.stdout)
        self.assertIn("素材重复", bad.stdout)

    # ── 素材清单门 ──────────────────────────────────────────────────────
    def test_plan_requires_material_inventory(self) -> None:
        """素材没登记进清单 → 退 1，并说清先跑 scan_materials（不静默放行）。"""
        spec = self.spec([
            {"range": 1, "word": 0, "material": "material2/x.mp4", "in": 0.0},
            {"range": 2, "word": 0, "material": "material2/x.mp4", "in": 1.0},
        ])
        p = self.plan(spec)
        self.assertEqual(p.returncode, 1)
        self.assertIn("第 1 镜", p.stderr)
        self.assertIn("scan_materials", p.stderr)
        self.assertIn("material-inventory.json", p.stderr)

    def test_plan_rejects_unfilled_inventory_summary(self) -> None:
        spec = self.spec([
            {"range": 1, "word": 0, "material": "material3/x.mp4", "in": 0.0},
            {"range": 2, "word": 0, "material": "material3/z.mp4", "in": 0.0},
        ])
        p = self.plan(spec)
        self.assertEqual(p.returncode, 1)
        self.assertIn("第 1 镜", p.stderr)
        self.assertIn("summary", p.stderr)
        self.assertIn("第 1 行", p.stderr)

    def test_plan_rejects_material_marked_unusable(self) -> None:
        spec = self.spec([
            {"range": 1, "word": 0, "material": "material3/y.mp4", "in": 0.0},
            {"range": 2, "word": 0, "material": "material3/z.mp4", "in": 0.0},
        ])
        p = self.plan(spec)
        self.assertEqual(p.returncode, 1)
        self.assertIn("usable=false", p.stderr)
        self.assertIn("第 1 镜", p.stderr)
        self.assertIn("第 2 行", p.stderr)

    # ── 变速 / 静音段 ───────────────────────────────────────────────────
    def _set_range(self, root: Path, index: int, **fields) -> None:
        path = root / "edit" / "edl.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["ranges"][index].update(fields)
        path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    def test_plan_rejects_variable_speed(self) -> None:
        """montage 按原速累加时间：变速段必须明确拒绝，不静默错算。"""
        root = self.project("speed")
        self._set_range(root, 0, speed=1.5)
        p = self.plan(self.spec([
            {"range": 1, "word": 0, "material": str(self.material / "a.mp4"), "in": 0.0},
            {"range": 2, "word": 0, "material": str(self.material / "b.mp4"), "in": 0.0},
        ], root=root), root=root)
        self.assertEqual(p.returncode, 1)
        self.assertIn("第 1 段 speed=1.5", p.stderr)
        self.assertIn("montage 的剪后时间按原速累加", p.stderr)
        self.assertIn("recompose", p.stderr)

    def test_plan_rejects_muted_range(self) -> None:
        root = self.project("muted")
        self._set_range(root, 1, mute=True)
        p = self.plan(self.spec([
            {"range": 1, "word": 0, "material": str(self.material / "a.mp4"), "in": 0.0},
            {"range": 2, "word": 0, "material": str(self.material / "b.mp4"), "in": 0.0},
        ], root=root), root=root)
        self.assertEqual(p.returncode, 1)
        self.assertIn("mute=true", p.stderr)
        self.assertIn("recompose", p.stderr)

    # ── 素材扫描的机器清单 ──────────────────────────────────────────────
    def test_scan_writes_machine_inventory_and_keeps_filled_rows(self) -> None:
        p = subprocess.run([sys.executable, str(SCAN), str(self.scan_dir),
                            "--frames", "1", "--per-sheet", "1"],
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        inv = self.scan_dir / "material-inventory.json"
        self.assertTrue(inv.exists())
        doc = json.loads(inv.read_text(encoding="utf-8"))
        self.assertEqual(len(doc["rows"]), 1)
        row = doc["rows"][0]
        for key in ("path", "name", "duration", "size", "usable", "summary",
                    "watermark", "source"):
            self.assertIn(key, row)
        self.assertIsNone(row["usable"])
        self.assertEqual(row["summary"], "")

        row["summary"] = "车间 · 全景 · 黑白 · 无字"
        row["usable"] = True
        inv.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        again = subprocess.run([sys.executable, str(SCAN), str(self.scan_dir),
                                "--frames", "1", "--per-sheet", "1"],
                               capture_output=True, text=True)
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertIn("已保留 1 行", again.stdout)
        kept = json.loads(inv.read_text(encoding="utf-8"))["rows"][0]
        self.assertEqual(kept["summary"], "车间 · 全景 · 黑白 · 无字")
        self.assertIs(kept["usable"], True)

    # ── 交付闸门 ────────────────────────────────────────────────────────
    def _concat_project(self, name: str) -> Path:
        root = self.project(name)
        p = self.plan(self.spec([
            {"range": 1, "word": 0, "material": str(self.material / "a.mp4"), "in": 0.0},
            {"range": 2, "word": 0, "material": str(self.material / "b.mp4"), "in": 0.0},
        ], root=root), root=root)
        self.assertEqual(p.returncode, 0, p.stderr)
        return root

    def test_render_default_output_is_review_material(self) -> None:
        """默认输出落在 edit/_engineering/，打印语是「审阅素材」，不打闸。"""
        root = self._concat_project("gate_default")
        r = self.render(root, root / "work", "--concat")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = root / "edit" / "_engineering" / "picture.mp4"
        self.assertTrue(out.exists(), r.stdout)
        self.assertIn("审阅素材：", r.stdout)
        self.assertNotIn("交付件：", r.stdout)

    def test_render_outside_engineering_needs_deliver_flag(self) -> None:
        """写到 成品/ 却没 --deliver：退 1、提示默认终点是审阅页、不落文件。"""
        root = self._concat_project("gate_no_flag")
        target = root / "成品" / "final.mp4"
        r = self.render(root, root / "work", "--concat", "--out", str(target))
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("默认终点是侧边栏审阅页", r.stderr)
        self.assertIn("交付需作者明确指令", r.stderr)
        self.assertFalse(target.exists())

    def test_render_deliver_without_submission_is_blocked(self) -> None:
        """有 --deliver 但没有人工提交覆盖快照：render_gate 拒绝，不落文件。"""
        root = self._concat_project("gate_no_review")
        target = root / "成品" / "final.mp4"
        r = self.render(root, root / "work", "--concat", "--out", str(target), "--deliver")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("交付闸门拒绝", r.stderr)
        self.assertIn("默认终点是侧边栏审阅页", r.stderr)
        self.assertFalse(target.exists())

    def test_render_deliver_passes_with_covering_submission(self) -> None:
        """人工提交覆盖当前快照 → 闸门放行，落 成品/ 并打印「交付件」。"""
        root = self._concat_project("gate_deliver")
        comp = root / "composition"
        comp.mkdir()
        (comp / "index.html").write_text("<html><body>cut</body></html>", encoding="utf-8")

        def entry(rel: str) -> dict:
            path = root / rel
            return {"path": rel, "size": path.stat().st_size,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

        (root / "review").mkdir()
        (root / "review" / "review_data.json").write_text(json.dumps({
            "snapshot": SNAPSHOT,
            "sourceManifest": [entry("composition/index.html"), entry("edit/edl.json")],
        }, ensure_ascii=False), encoding="utf-8")
        (root / "review" / "review-submissions.json").write_text(json.dumps({
            "records": [{"snapshot": SNAPSHOT, "text": "这一版可以"}],
        }, ensure_ascii=False), encoding="utf-8")

        target = root / "成品" / "final.mp4"
        r = self.render(root, root / "work", "--concat", "--out", str(target), "--deliver")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(target.exists(), r.stdout)
        self.assertIn("交付件：", r.stdout)
        self.assertIn("渲染闸门放行", r.stdout)

    def test_deliver_flag_on_engineering_output_is_contradictory(self) -> None:
        root = self._concat_project("gate_conflict")
        r = self.render(root, root / "work", "--concat", "--deliver")
        self.assertEqual(r.returncode, 1)
        self.assertIn("_engineering", r.stderr)
        self.assertIn("审阅素材", r.stderr)

    # ── check ───────────────────────────────────────────────────────────
    def _render_two_shots(self, name: str = "") -> Path:
        spec = self.spec([{"range": 1, "word": 0, "material": "material/a.mp4", "in": 0.0},
                          {"range": 2, "word": 0, "material": "material/b.mp4", "in": 0.0}])
        p = self.plan(spec)
        self.assertEqual(p.returncode, 0, p.stderr)
        work = self.root / f"work_{name or self._testMethodName}"  # 每例独立工作目录
        r = self.render(self.root, work)
        self.assertEqual(r.returncode, 0, r.stderr)
        return work

    def test_check_passes_on_good_render(self) -> None:
        work = self._render_two_shots()
        p = self.check(work=work)
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
        p = self.check(work=work)
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertIn("底图", p.stdout)

    def test_check_flags_missing_shot(self) -> None:
        work = self._render_two_shots()
        (work / "shot_002.mp4").unlink()
        p = self.check(work=work)
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertIn("没渲染", p.stdout)

    # ── voice-cut ───────────────────────────────────────────────────────
    def test_voice_cut_makes_silent_person_track(self) -> None:
        self.write_plan()
        p = self.voice_cut()
        self.assertEqual(p.returncode, 0, p.stderr)
        out = self.edit / "_engineering" / "voice_cut.mp4"
        self.assertTrue(out.exists(), p.stdout)
        doc = ffprobe(out)
        kinds = [s.get("codec_type") for s in doc.get("streams") or []]
        self.assertEqual(kinds, ["video"], doc)          # 默认无声
        self.assertAlmostEqual(float(doc["format"]["duration"]), 4.0, delta=0.5)
        self.assertIn("实测", p.stdout)
        self.assertIn("计划", p.stdout)
        self.assertIn("无声", p.stdout)
        stream = doc["streams"][0]
        self.assertEqual((stream["width"], stream["height"]), (320, 640))  # 缩到画框 canvas

    def test_voice_cut_mixes_audio_when_asked(self) -> None:
        self.write_plan()
        p = self.voice_cut("--audio", str(self.audio))
        self.assertEqual(p.returncode, 0, p.stderr)
        out = self.edit / "_engineering" / "voice_cut.mp4"
        kinds = [s.get("codec_type") for s in ffprobe(out).get("streams") or []]
        self.assertEqual(kinds, ["video", "audio"], kinds)
        self.assertIn("口播 audio.m4a", p.stdout)

    def test_voice_cut_fails_when_duration_drifts(self) -> None:
        """实测与 plan.timeline.total 差 > 0.5s 硬失败（母版和 EDL 不是同一版）。"""
        self.write_plan(total=6.0)
        p = self.voice_cut()
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertIn("> 0.5s", p.stderr)
        self.assertIn("实测", p.stderr)

    def test_voice_cut_defaults_to_1080x1920_without_a_plan(self) -> None:
        """没有 montage-plan.json 时按默认画框 1080×1920/30，计划时长取 EDL 段长合计。"""
        plan = self.edit / "montage-plan.json"
        if plan.exists():
            plan.unlink()
        out = self.root / "voice_cut_default.mp4"
        p = self.voice_cut("-o", str(out))
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("1080×1920@30", p.stdout)
        self.assertIn("没有 montage-plan.json", p.stdout)
        stream = ffprobe(out)["streams"][0]
        self.assertEqual((stream["width"], stream["height"]), (1080, 1920))

    def test_voice_cut_points_at_master_when_edl_gave_a_proxy(self) -> None:
        self.write_plan()
        p = self.voice_cut("--master", str(self.material / "proxy_master.mp4"))
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("交付用母版不用 proxy", p.stdout)


if __name__ == "__main__":
    unittest.main()
