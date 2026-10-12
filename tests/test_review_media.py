#!/usr/bin/env python3
"""Review media must be declared, and a master must not be handed over whole.

Two failures this pins:

  * Filename guessing picked `anim_preview.mp4` — a full-length 720p copy of the
    whole film — as the "演示动画" track on the 图拉斯 project, purely because of
    its name. Booleans and anchors were then read off the wrong track.
  * The review host transfers whole files, so a 263MB master is a bad handoff. The
    审阅副本 rule (same duration, SAME native resolution, higher CRF) is what the
    console should load instead.
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HELPERS = Path(__file__).parents[1] / "helpers"
sys.path.insert(0, str(HELPERS))

FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"craft_{name}", HELPERS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


review_copy = _load("review_copy")
build_review = _load("build_review")


def _tiny_video(path: Path, seconds: float = 0.6, size: str = "320x480") -> None:
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
         "-i", f"color=c=gray:s={size}:d={seconds}:r=30",
         "-f", "lavfi", "-i", f"anullsrc=r=48000:cl=stereo:d={seconds}",
         "-c:v", "libx264", "-preset", "ultrafast", "-crf", "30", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-shortest", str(path)], check=True)


class MediaResolutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name)
        self.edit = self.project / "edit"
        self.edit.mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_explicit_media_json_wins_over_filename_guessing(self):
        # Two files a guesser could confuse; only the declared one is used.
        (self.edit / "final.mp4").write_bytes(b"x")
        (self.edit / "anim_preview.mp4").write_bytes(b"x")
        (self.edit / "review").mkdir()
        (self.edit / "review" / "media.json").write_text(json.dumps({
            "compositeVideo": "edit/final.mp4", "previewVideo": None,
        }), encoding="utf-8")
        media, notes = build_review.resolve_review_media(
            self.project, self.edit, allow_review_copy=False)
        self.assertEqual(media["compositeVideo"], "edit/final.mp4")
        self.assertIsNone(media["previewVideo"])
        self.assertEqual(notes, [])

    def test_guessing_is_reported(self):
        (self.edit / "anim_preview.mp4").write_bytes(b"x")
        media, notes = build_review.resolve_review_media(
            self.project, self.edit, allow_review_copy=False)
        self.assertEqual(media["previewVideo"], "edit/anim_preview.mp4")
        self.assertTrue(any("按文件名猜" in n for n in notes), notes)

    def test_a_declared_but_missing_track_is_reported(self):
        (self.edit / "review").mkdir()
        (self.edit / "review" / "media.json").write_text(json.dumps({
            "compositeVideo": "edit/nope.mp4",
        }), encoding="utf-8")
        media, notes = build_review.resolve_review_media(
            self.project, self.edit, allow_review_copy=False)
        self.assertIsNone(media["compositeVideo"])
        self.assertTrue(any("不存在" in n for n in notes), notes)

    def test_a_malformed_media_json_falls_back_and_says_so(self):
        (self.edit / "final.mp4").write_bytes(b"x")
        (self.edit / "review").mkdir()
        (self.edit / "review" / "media.json").write_text("{not json", encoding="utf-8")
        media, notes = build_review.resolve_review_media(
            self.project, self.edit, allow_review_copy=False)
        self.assertEqual(media["compositeVideo"], "edit/final.mp4")
        self.assertTrue(any("解析失败" in n for n in notes), notes)


@unittest.skipUnless(FFMPEG, "ffmpeg required")
class ReviewCopyTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.edit = self.dir / "edit"
        self.edit.mkdir()
        # Named final.mp4 so the resolver picks it up as the composite.
        self.src = self.edit / "final.mp4"
        _tiny_video(self.src)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_small_files_are_left_alone(self):
        self.assertFalse(review_copy.needs_copy(self.src, max_mb=80.0))
        record = review_copy.make(self.src, max_mb=80.0)
        self.assertEqual(record["action"], "skip")
        self.assertEqual(Path(record["path"]), self.src.resolve())

    def test_a_large_master_gets_a_time_preserving_native_copy(self):
        before = review_copy._probe_media(self.src)
        record = review_copy.make(self.src, max_mb=0.001)
        self.assertEqual(record["action"], "made")
        out = Path(record["path"])
        self.assertTrue(out.is_file())
        self.assertEqual(out.name, self.src.stem + ".review.mp4")
        after = review_copy._probe_media(out)
        self.assertEqual(before[1:], after[1:], "审阅副本必须保持原生分辨率")
        self.assertAlmostEqual(before[0], after[0], delta=0.1)

    def test_the_resolver_swaps_in_a_review_copy_for_the_composite(self):
        """The console must load the copy, not the master."""
        media, notes = build_review.resolve_review_media(
            self.dir, self.edit, allow_review_copy=True, max_mb=0.001)
        self.assertTrue(media["compositeVideo"].endswith(".review.mp4"), media)
        self.assertTrue(any("审阅副本" in n for n in notes), notes)
        self.assertTrue((self.dir / media["compositeVideo"]).is_file())


if __name__ == "__main__":
    unittest.main()
