#!/usr/bin/env python3
"""Black-box CLI tests for unified `storyboard.json`, summary derivation, and Look-Dev gate."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HELPERS = Path(__file__).resolve().parents[1] / "helpers"
FILM = HELPERS / "film.py"


def _run_film(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(FILM), *args],
        capture_output=True,
        text=True,
    )


def _touch_media(path: Path, content: bytes = b"fake-media") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _write_inventory(directory: Path, rows: list[dict]) -> Path:
    inv = directory / "material-inventory.json"
    inv.write_text(
        json.dumps({"version": "material-inventory/1", "root": str(directory), "rows": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return inv


def _mixed_storyboard(project: Path) -> dict:
    _touch_media(project / "material" / "clip_a.mp4")
    _touch_media(project / "material" / "clip_b.mp4")
    _touch_media(project / "material" / "cover_01.jpg")
    _touch_media(project / "material" / "cover_02.jpg")
    _touch_media(project / "recordings" / "app_demo.mp4")
    return {
        "version": "storyboard/3",
        "project": "测试混合项目",
        "referenceStyle": "暗调几何极简",
        "canvas": {"width": 1080, "height": 1920, "fps": 30},
        "framePreset": "vertical-zine-head",
        "shots": [
            {
                "id": "T01",
                "kind": "talk-only",
                "engine": "ffmpeg-cut",
                "chapter": "01 · 开场",
                "startSec": 0.0,
                "endSec": 5.0,
            },
            {
                "id": "V01",
                "kind": "footage",
                "engine": "ffmpeg-cut",
                "chapter": "01 · 开场",
                "startSec": 5.0,
                "endSec": 15.0,
                "clip": "material/clip_a.mp4",
                "clipIn": 2.0,
                "clipOut": 12.0,
                "soundBed": "auto",
            },
            {
                "id": "X01",
                "kind": "card-deck",
                "engine": "hyperframes",
                "style": "fan",
                "chapter": "02 · 矩阵",
                "title": "封面展卷",
                "startSec": 15.0,
                "endSec": 25.0,
                "covers": ["material/cover_01.jpg", "material/cover_02.jpg"],
                "items": [
                    {"file": "material/cover_01.jpg", "aspect": "3x4"},
                    {"file": "material/cover_02.jpg", "aspect": "3x4"},
                ],
                "soundCues": ["whoosh", "crisp-tick"],
            },
            {
                "id": "M01",
                "kind": "model",
                "engine": "hyperframes",
                "modelId": "M01",
                "chapter": "02 · 矩阵",
                "title": "因果收束模型",
                "startSec": 25.0,
                "endSec": 40.0,
                "soundCues": ["swell", "sub-drop", "reveal-chime"],
            },
            {
                "id": "D01",
                "kind": "screen-demo",
                "engine": "ffmpeg-cut",
                "chapter": "03 · 实操",
                "startSec": 40.0,
                "endSec": 50.0,
                "demo": {"source": "recordings/app_demo.mp4", "inSec": 1.0, "outSec": 11.0},
            },
        ],
    }


class UnifiedStoryboardVerifyTests(unittest.TestCase):
    def test_verify_accepts_unified_storyboard_v3_and_edit_location(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td)
            doc = _mixed_storyboard(proj)
            (proj / "edit").mkdir(parents=True)
            # Empty placeholder pages/ must not break storyboard verification
            (proj / "pages").mkdir()
            (proj / "edit" / "storyboard.json").write_text(
                json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            res = _run_film("verify", str(proj), "--json")
            self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
            payload = json.loads(res.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["mode"], "storyboard/3")
            self.assertEqual(payload["shots"], 5)
            self.assertEqual(payload["framePreset"], "vertical-zine-head")

    def test_verify_supports_video_motion_xhs_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td)
            _touch_media(proj / "material" / "ad.mp4")
            _touch_media(proj / "material" / "c1.jpg")
            doc = {
                "version": "storyboard/3",
                "canvas": {"width": 1080, "height": 1920, "fps": 30},
                "framePreset": "vertical-zine-head",
                "shots": [
                    {
                        "id": "V02",
                        "kind": "video",
                        "engine": "ffmpeg-cut",
                        "startSec": 0.0,
                        "endSec": 6.0,
                        "clip": "material/ad.mp4",
                        "clipIn": 10.0,
                        "clipOut": 16.0,
                        "soundBed": "auto",
                    },
                    {
                        "id": "X1",
                        "kind": "xhs",
                        "engine": "hyperframes",
                        "startSec": 6.0,
                        "endSec": 10.0,
                        "items": [{"file": "material/c1.jpg", "aspect": "3x4"}],
                    },
                    {
                        "id": "MO1",
                        "kind": "motion",
                        "engine": "hyperframes",
                        "startSec": 10.0,
                        "endSec": 18.0,
                        "soundCues": ["swell", "sub-drop"],
                    },
                ],
            }
            (proj / "storyboard.json").write_text(json.dumps(doc), encoding="utf-8")
            res = _run_film("verify", str(proj), "--json")
            self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
            self.assertTrue(json.loads(res.stdout)["ok"])

    def test_verify_rejects_invalid_kind_engine_overlap_and_sound_fields(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td)
            _touch_media(proj / "material" / "ad.mp4")
            doc = {
                "version": "storyboard/3",
                "canvas": {"width": 1080, "height": 1920, "fps": 30},
                "shots": [
                    {
                        "id": "S1",
                        "kind": "video",
                        "engine": "browser-full",
                        "startSec": 0.0,
                        "endSec": 5.0,
                        "clip": "material/ad.mp4",
                        "clipIn": 0.0,
                        "soundBed": "loud-bad",
                    },
                    {
                        "id": "S2",
                        "kind": "model",
                        "engine": "ffmpeg-cut",
                        "startSec": 4.0,
                        "endSec": 9.0,
                        "soundCues": "not-a-list",
                    },
                    {
                        "id": "S3",
                        "kind": "unknown-kind",
                        "startSec": 9.0,
                        "endSec": 12.0,
                    },
                ],
            }
            (proj / "storyboard.json").write_text(json.dumps(doc), encoding="utf-8")
            res = _run_film("verify", str(proj), "--json")
            self.assertEqual(res.returncode, 1)
            payload = json.loads(res.stdout)
            self.assertFalse(payload["ok"])
            joined = "\n".join(payload["problems"])
            self.assertIn("S1", joined)
            self.assertIn("S2", joined)
            self.assertIn("S3", joined)

    def test_verify_rejects_video_reuse_under_5s_and_allows_5s_or_more(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td)
            _touch_media(proj / "material" / "long.mp4")
            base = {
                "version": "storyboard/3",
                "canvas": {"width": 1080, "height": 1920, "fps": 30},
                "shots": [
                    {
                        "id": "V01",
                        "kind": "footage",
                        "engine": "ffmpeg-cut",
                        "startSec": 0.0,
                        "endSec": 4.0,
                        "clip": "material/long.mp4",
                        "clipIn": 10.0,
                        "clipOut": 14.0,
                    },
                    {
                        "id": "V02",
                        "kind": "video",
                        "engine": "ffmpeg-cut",
                        "startSec": 4.0,
                        "endSec": 8.0,
                        "clip": "material/long.mp4",
                        "clipIn": 13.5,
                        "clipOut": 17.5,
                    },
                ],
            }
            sb = proj / "storyboard.json"
            sb.write_text(json.dumps(base), encoding="utf-8")
            bad = _run_film("verify", str(proj), "--json")
            self.assertEqual(bad.returncode, 1)
            payload = json.loads(bad.stdout)
            joined = "\n".join(payload["problems"])
            self.assertIn("V02", joined)
            self.assertIn("5s", joined)

            base["shots"][1]["clipIn"] = 16.0
            base["shots"][1]["clipOut"] = 20.0
            sb.write_text(json.dumps(base), encoding="utf-8")
            good = _run_film("verify", str(proj), "--json")
            self.assertEqual(good.returncode, 0, good.stdout + good.stderr)

    def test_verify_rejects_second_use_of_identical_static_photo_or_cover(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td)
            _touch_media(proj / "material" / "shared.jpg")
            _touch_media(proj / "material" / "other.png")
            doc = {
                "version": "storyboard/3",
                "canvas": {"width": 1080, "height": 1920, "fps": 30},
                "shots": [
                    {
                        "id": "X01",
                        "kind": "card-deck",
                        "engine": "hyperframes",
                        "startSec": 0.0,
                        "endSec": 4.0,
                        "covers": ["material/shared.jpg"],
                        "items": [{"file": "material/shared.jpg", "aspect": "3x4"}],
                    },
                    {
                        "id": "X02",
                        "kind": "xhs",
                        "engine": "hyperframes",
                        "startSec": 4.0,
                        "endSec": 8.0,
                        "items": [
                            {"file": "material/other.png", "aspect": "3x4"},
                            {"file": "material/shared.jpg", "aspect": "3x4"},
                        ],
                    },
                ],
            }
            (proj / "storyboard.json").write_text(json.dumps(doc), encoding="utf-8")
            res = _run_film("verify", str(proj), "--json")
            self.assertEqual(res.returncode, 1)
            payload = json.loads(res.stdout)
            self.assertIn("X02", "\n".join(payload["problems"]))

    def test_verify_validates_material_inventory_when_present_or_checks_clip_exists(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td)
            mat = proj / "material"
            clip_ok = _touch_media(mat / "ok.mp4")
            clip_bad = _touch_media(mat / "bad.mp4")
            clip_unlisted = _touch_media(mat / "unlisted.mp4")
            _write_inventory(
                mat,
                [
                    {"path": str(clip_ok), "name": "ok.mp4", "summary": "办公室 · 中景 · 彩色 · 无字", "usable": True},
                    {"path": str(clip_bad), "name": "bad.mp4", "summary": "有水印", "usable": False},
                ],
            )
            doc = {
                "version": "storyboard/3",
                "canvas": {"width": 1080, "height": 1920, "fps": 30},
                "shots": [
                    {
                        "id": "V01",
                        "kind": "footage",
                        "engine": "ffmpeg-cut",
                        "startSec": 0.0,
                        "endSec": 4.0,
                        "clip": "material/bad.mp4",
                        "clipIn": 0.0,
                    },
                    {
                        "id": "V02",
                        "kind": "footage",
                        "engine": "ffmpeg-cut",
                        "startSec": 4.0,
                        "endSec": 8.0,
                        "clip": "material/unlisted.mp4",
                        "clipIn": 0.0,
                    },
                    {
                        "id": "V03",
                        "kind": "footage",
                        "engine": "ffmpeg-cut",
                        "startSec": 8.0,
                        "endSec": 12.0,
                        "clip": "material/missing.mp4",
                        "clipIn": 0.0,
                    },
                ],
            }
            (proj / "storyboard.json").write_text(json.dumps(doc), encoding="utf-8")
            bad = _run_film("verify", str(proj), "--json")
            self.assertEqual(bad.returncode, 1)
            probs = "\n".join(json.loads(bad.stdout)["problems"])
            self.assertIn("V01", probs)
            self.assertIn("V02", probs)
            self.assertIn("V03", probs)

            # Fix to valid registered clip only
            doc["shots"] = [
                {
                    "id": "V01",
                    "kind": "footage",
                    "engine": "ffmpeg-cut",
                    "startSec": 0.0,
                    "endSec": 4.0,
                    "clip": "material/ok.mp4",
                    "clipIn": 0.0,
                }
            ]
            (proj / "storyboard.json").write_text(json.dumps(doc), encoding="utf-8")
            good = _run_film("verify", str(proj), "--json")
            self.assertEqual(good.returncode, 0, good.stdout + good.stderr)

    def test_verify_preserves_legacy_visual_plan_compatibility(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td)
            (proj / "visual-plan.json").write_text(
                json.dumps(
                    {
                        "version": 2,
                        "segments": [
                            {"id": "seg-01", "beatId": "b1", "tier": "talk-only", "startMs": 0, "endMs": 2000}
                        ],
                    }
                ),
                encoding="utf-8",
            )
            res = _run_film("verify", str(proj), "--json")
            self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
            self.assertEqual(json.loads(res.stdout)["mode"], "v2-visual-plan")


class StoryboardSummaryTests(unittest.TestCase):
    def test_summary_derives_deterministic_markdown_with_ids_spans_engines_and_mix(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td)
            doc = _mixed_storyboard(proj)
            (proj / "storyboard.json").write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")

            r1 = _run_film("summary", str(proj), "--json")
            self.assertEqual(r1.returncode, 0, r1.stdout + r1.stderr)
            default_md = proj / "edit" / "storyboard-overview.md"
            self.assertTrue(default_md.is_file())
            txt1 = default_md.read_text(encoding="utf-8")

            # Custom --out path
            r2 = _run_film("summary", str(proj), "--out", "visual-brief.md", "--json")
            self.assertEqual(r2.returncode, 0, r2.stdout + r2.stderr)
            custom_md = proj / "visual-brief.md"
            self.assertTrue(custom_md.is_file())
            txt2 = custom_md.read_text(encoding="utf-8")
            self.assertEqual(txt1, txt2)

            # Verify shot IDs, time spans, engines, and capability mix ratios
            # Total = 50.0s: talk-only 5s (10.0%), footage 10s (20.0%), motion+card-deck 25s (50.0%), screen-demo 10s (20.0%)
            for token in ("T01", "V01", "X01", "M01", "D01", "ffmpeg-cut", "hyperframes", "0.00–5.00s", "25.00–40.00s", "50.0%", "20.0%", "10.0%"):
                self.assertIn(token, txt1)


class LookDevGateTests(unittest.TestCase):
    def test_lookdev_required_for_motion_without_static_pages_until_approved(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td)
            doc = _mixed_storyboard(proj)
            # Empty pages/ directory should NOT grant static-reference exemption
            (proj / "pages").mkdir()
            (proj / "storyboard.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

            # 1) --verify before generating packet fails
            pre = _run_film("lookdev", str(proj), "--verify", "--json")
            self.assertEqual(pre.returncode, 1, pre.stdout + pre.stderr)
            self.assertFalse(json.loads(pre.stdout)["ok"])

            # 2) Generate Look-Dev packet (ratio/intent manifest + 1 sample model contract)
            gen = _run_film("lookdev", str(proj), "--json")
            self.assertEqual(gen.returncode, 0, gen.stdout + gen.stderr)
            manifest_path = proj / "lookdev" / "lookdev-manifest.json"
            sample_path = proj / "lookdev" / "sample-model.json"
            self.assertTrue(manifest_path.is_file())
            self.assertTrue(sample_path.is_file())

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            sample = json.loads(sample_path.read_text(encoding="utf-8"))
            self.assertFalse(manifest["approved"])
            self.assertIn("capabilityMix", manifest)
            self.assertIn("intent", manifest)
            self.assertEqual(manifest["sampleModel"]["shotId"], "M01")
            self.assertEqual(sample["shotId"], "M01")

            # 3) --verify still fails while unapproved
            unapproved = _run_film("lookdev", str(proj), "--verify", "--json")
            self.assertEqual(unapproved.returncode, 1)
            self.assertFalse(json.loads(unapproved.stdout)["ok"])

            # 4) --approve marks approved, and subsequent --verify passes
            app = _run_film("lookdev", str(proj), "--approve", "--json")
            self.assertEqual(app.returncode, 0, app.stdout + app.stderr)
            self.assertTrue(json.loads(app.stdout)["approved"])

            verified = _run_film("lookdev", str(proj), "--verify", "--json")
            self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)
            v_payload = json.loads(verified.stdout)
            self.assertTrue(v_payload["ok"])
            self.assertTrue(v_payload["required"])
            self.assertTrue(v_payload["approved"])

    def test_lookdev_exempts_footage_only_project(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td)
            _touch_media(proj / "material" / "a.mp4")
            doc = {
                "version": "storyboard/3",
                "canvas": {"width": 1080, "height": 1920, "fps": 30},
                "shots": [
                    {
                        "id": "T01",
                        "kind": "talk-only",
                        "engine": "ffmpeg-cut",
                        "startSec": 0.0,
                        "endSec": 3.0,
                    },
                    {
                        "id": "V01",
                        "kind": "footage",
                        "engine": "ffmpeg-cut",
                        "startSec": 3.0,
                        "endSec": 10.0,
                        "clip": "material/a.mp4",
                        "clipIn": 0.0,
                    },
                ],
            }
            (proj / "storyboard.json").write_text(json.dumps(doc), encoding="utf-8")
            res = _run_film("lookdev", str(proj), "--verify", "--json")
            self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
            payload = json.loads(res.stdout)
            self.assertTrue(payload["ok"])
            self.assertFalse(payload["required"])
            self.assertTrue(payload["exempt"])

    def test_lookdev_exempts_project_with_static_pages_reference(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td)
            doc = _mixed_storyboard(proj)
            (proj / "storyboard.json").write_text(json.dumps(doc), encoding="utf-8")
            pages = proj / "pages"
            pages.mkdir(parents=True)
            (pages / "page_01.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8")

            res = _run_film("lookdev", str(proj), "--verify", "--json")
            self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
            payload = json.loads(res.stdout)
            self.assertTrue(payload["ok"])
            self.assertFalse(payload["required"])
            self.assertTrue(payload["exempt"])


class StoryboardInitAndProxyTests(unittest.TestCase):
    def test_init_creates_v3_storyboard_mapped_from_grouping_and_supports_legacy_flag(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td)
            (proj / "timeline").mkdir(parents=True)
            (proj / "timeline" / "grouping.json").write_text(json.dumps({
                "chapters": [
                    {
                        "id": "ch01",
                        "title": "开场锚点",
                        "steps": [
                            {"id": "S01", "title": "先抛核心问题", "kind": "talk-only", "startMs": 0, "endMs": 3200},
                            {"id": "M01", "title": "三维因果模型", "kind": "model", "startMs": 3200, "endMs": 8500},
                        ],
                    }
                ]
            }, ensure_ascii=False), encoding="utf-8")
            (proj / "frame.json").write_text(json.dumps({
                "framePreset": "vertical-zine-head",
                "canvas": {"w": 1080, "h": 1920, "fps": 30},
            }), encoding="utf-8")

            res = _run_film("init", str(proj), "--json")
            self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
            payload = json.loads(res.stdout)
            self.assertTrue(payload["ok"])
            self.assertTrue(payload["created"])
            sb_path = proj / "storyboard.json"
            self.assertTrue(sb_path.is_file())
            self.assertFalse((proj / "visual-plan.json").exists())

            sb = json.loads(sb_path.read_text(encoding="utf-8"))
            self.assertEqual(sb["version"], "storyboard/3")
            self.assertEqual(sb["framePreset"], "vertical-zine-head")
            self.assertEqual(sb["canvas"], {"width": 1080, "height": 1920, "fps": 30})
            self.assertEqual(len(sb["shots"]), 2)
            self.assertEqual(sb["shots"][0]["id"], "S01")
            self.assertEqual(sb["shots"][0]["kind"], "talk-only")
            self.assertEqual(sb["shots"][0]["engine"], "ffmpeg-cut")
            self.assertAlmostEqual(sb["shots"][0]["startSec"], 0.0)
            self.assertAlmostEqual(sb["shots"][0]["endSec"], 3.2)
            self.assertEqual(sb["shots"][1]["id"], "M01")
            self.assertEqual(sb["shots"][1]["kind"], "model")
            self.assertEqual(sb["shots"][1]["engine"], "remotion")

            # Verify generated storyboard passes film.py verify
            v_res = _run_film("verify", str(proj), "--json")
            self.assertEqual(v_res.returncode, 0, v_res.stdout + v_res.stderr)

            # Legacy visual-plan mode via explicit flag
            leg_proj = Path(td) / "legacy"
            leg_proj.mkdir()
            leg_res = _run_film("init", str(leg_proj), "--legacy-visual-plan", "--json")
            self.assertEqual(leg_res.returncode, 0, leg_res.stdout + leg_res.stderr)
            self.assertTrue((leg_proj / "visual-plan.json").is_file())
            self.assertFalse((leg_proj / "storyboard.json").exists())

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "需要 ffmpeg/ffprobe")
    def test_proxy_generates_proxies_for_storyboard_screen_demo_and_demo_footage(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td)
            (proj / "recordings").mkdir(parents=True)
            comp_assets = proj / "composition" / "assets"
            comp_assets.mkdir(parents=True)
            hd_src = proj / "recordings" / "app.mp4"
            subprocess.run([
                "ffmpeg", "-y", "-v", "error",
                "-f", "lavfi", "-i", "color=c=0x1E293B:s=1280x720:r=30:d=3",
                "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                str(hd_src),
            ], check=True)
            (proj / "storyboard.json").write_text(json.dumps({
                "version": "storyboard/3",
                "canvas": {"width": 1080, "height": 1920, "fps": 30},
                "shots": [
                    {
                        "id": "D01", "kind": "screen-demo", "engine": "ffmpeg-cut",
                        "startSec": 0.0, "endSec": 1.2,
                        "demo": {"source": "recordings/app.mp4", "inSec": 0.1, "outSec": 1.3},
                    },
                    {
                        "id": "D02", "kind": "demo-footage", "engine": "ffmpeg-cut",
                        "startSec": 1.2, "endSec": 2.2,
                        "demo": {"source": "recordings/app.mp4", "inSec": 1.4, "outSec": 2.4},
                    },
                ],
            }), encoding="utf-8")

            res = _run_film("proxy", str(proj), "--max-width", "640", "--crf", "30", "--json")
            self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
            payload = json.loads(res.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["count"], 2)
            sb = json.loads((proj / "storyboard.json").read_text(encoding="utf-8"))
            self.assertEqual(sb["shots"][0]["demo"]["proxy"], "review/demo_proxies/D01.mp4")
            self.assertEqual(sb["shots"][1]["demo"]["proxy"], "review/demo_proxies/D02.mp4")
            self.assertTrue((proj / "review/demo_proxies/D01.mp4").is_file())
            self.assertTrue((proj / "review/demo_proxies/D02.mp4").is_file())
            self.assertEqual(list(comp_assets.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
