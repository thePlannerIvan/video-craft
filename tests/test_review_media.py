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


def _pattern_video(path: Path, seconds: float = 2.0, size: str = "960x540") -> None:
    """Moving test pattern: pixel count actually drives the byte count here.

    A flat gray frame is dominated by the container's fixed overhead at small
    sizes, so it cannot demonstrate a resolution ladder.
    """
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
         "-i", f"testsrc2=s={size}:d={seconds}:r=30",
         "-f", "lavfi", "-i", f"anullsrc=r=48000:cl=stereo:d={seconds}",
         "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18", "-pix_fmt", "yuv420p",
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

    def test_a_copy_that_fits_keeps_native_pixels(self):
        """The ladder must not step down when native pixels already fit."""
        before = review_copy._probe_media(self.src)
        record = review_copy.make(self.src, max_mb=80.0, force=True)
        self.assertEqual(record["action"], "made")
        out = Path(record["path"])
        self.assertTrue(out.is_file())
        self.assertEqual(out.name, self.src.stem + ".review.mp4")
        after = review_copy._probe_media(out)
        self.assertEqual(before[1:], after[1:], "审阅副本必须保持原生分辨率")
        self.assertAlmostEqual(before[0], after[0], delta=0.1)
        self.assertFalse(record["scaled"])
        self.assertEqual(record["scale"], 1.0)

    def test_native_pixels_that_cannot_fit_step_down_resolution(self):
        """2026-10-21: a 368s 720x1280 master stayed 52MB at native pixels.

        The copy has to step down rather than hand the page 70MB of base64.
        The budget here is chosen from the native encode's real size so the test
        is about the ladder, not about a particular encoder's byte count.
        """
        pattern = self.dir / "pattern.mp4"
        _pattern_video(pattern)
        native = review_copy.make(pattern, out=self.dir / "pattern.native.mp4",
                                  force=True, max_mb=999.0)
        budget_mb = native["bytes"] / 1e6 * 0.6
        record = review_copy.make(pattern, out=self.dir / "ladder.mp4",
                                  max_mb=budget_mb)
        self.assertEqual(record["action"], "made")
        self.assertTrue(record["scaled"], record)
        self.assertIn(record["scale"], {0.75, 0.5, 0.35})
        self.assertLess(record["width"], record["sourceWidth"])
        self.assertLess(record["height"], record["sourceHeight"])
        self.assertTrue(record["underBudget"], record)
        out = Path(record["path"])
        self.assertTrue(out.is_file())
        self.assertAlmostEqual(review_copy.media_duration(out),
                               review_copy.media_duration(pattern), delta=0.1)
        self.assertEqual(review_copy.media_size(out),
                         (record["width"], record["height"]))
        # Only the chosen copy survives; no .part / stepped-down leftovers.
        self.assertEqual([p.name for p in out.parent.glob("*.part*.mp4")], [])

    def test_the_bottom_of_the_ladder_is_reported_not_hidden(self):
        """If even 0.35x cannot fit, return the smallest copy and say so."""
        record = review_copy.make(self.src, out=self.dir / "tiny.mp4",
                                  max_mb=0.0001)
        self.assertEqual(record["action"], "made")
        self.assertTrue(record["scaled"])
        self.assertEqual(record["scale"], 0.35)
        self.assertFalse(record["underBudget"])
        self.assertIn("仍超", record.get("note", ""))

    def test_a_muted_video_can_drop_its_audio_track(self):
        """The live stage's person track carries a duplicate narration track."""
        record = review_copy.make(self.src, out=self.dir / "silent.mp4",
                                  force=True, max_mb=80.0, keep_audio=False)
        self.assertTrue(record["audioDropped"])
        self.assertFalse(record["audio"])
        stream_types = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type",
             "-of", "csv=p=0", record["path"]],
            capture_output=True, text=True, check=True).stdout.split()
        self.assertNotIn("audio", stream_types)

    def test_silent_asset_tokens_reads_the_compiled_html(self):
        html = """
        <video class="clip" src="__VC_ASSET_1__" muted data-has-audio="false"></video>
        <video class="clip" src="__VC_ASSET_2__" data-has-audio="true"></video>
        <audio src="__VC_ASSET_3__"></audio>
        """
        silent = build_review.silent_asset_tokens(html)
        self.assertEqual(silent, {"__VC_ASSET_1__"})

    def test_no_downscale_refuses_instead_of_lowering_the_picture(self):
        with self.assertRaises(SystemExit) as caught:
            review_copy.make(self.src, force=True, max_mb=0.0001,
                             allow_downscale=False)
        self.assertIn("禁止降分辨率", str(caught.exception))

    def test_the_resolver_swaps_in_a_review_copy_for_the_composite(self):
        """The console must load the copy, not the master."""
        media, notes = build_review.resolve_review_media(
            self.dir, self.edit, allow_review_copy=True, max_mb=0.001)
        self.assertTrue(media["compositeVideo"].endswith(".review.mp4"), media)
        self.assertTrue(any("审阅副本" in n for n in notes), notes)
        self.assertTrue((self.dir / media["compositeVideo"]).is_file())


@unittest.skipUnless(FFMPEG, "ffmpeg/ffprobe not installed")
class ProxyIntegrityTests(unittest.TestCase):
    """A truncated copy must never be judged fresh.

    2026-10-17: a muxer timeout left a 524KB proxy with no moov atom at the final
    path; build_review reused it by mtime, the page played the film with no sound,
    and the author reported it as "声音丢了". Decodability is the property.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.src = self._tone(self.dir / "narration.m4a", 2.0)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    @staticmethod
    def _tone(path: Path, seconds: float) -> Path:
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
             "-i", f"sine=frequency=440:duration={seconds}",
             "-c:a", "aac", "-b:a", "64k", str(path)],
            check=True, capture_output=True)
        return path

    def test_a_truncated_file_has_no_duration_and_is_not_fresh(self):
        broken = self.dir / "broken.review.m4a"
        data = self.src.read_bytes()
        broken.write_bytes(data[: max(1, len(data) // 2)])
        self.assertIsNone(review_copy.media_duration(broken))
        self.assertFalse(review_copy.is_fresh_copy(broken, 2.0))

    def test_a_real_copy_is_fresh_and_a_duration_mismatch_is_not(self):
        duration = review_copy.media_duration(self.src)
        self.assertIsNotNone(duration)
        self.assertTrue(review_copy.is_fresh_copy(self.src, duration))
        self.assertFalse(review_copy.is_fresh_copy(self.src, duration + 3.0))

    def test_make_writes_atomically_and_leaves_no_part_file(self):
        out = self.dir / "proxies" / "narration.review.m4a"
        out.parent.mkdir()
        record = review_copy.make(self.src, out, max_mb=0.001)
        self.assertEqual(record["action"], "made")
        self.assertTrue(out.is_file())
        self.assertFalse(out.with_name(out.stem + ".part" + out.suffix).exists(),
                         "编码中的临时文件必须改名到位，不能留在项目里")
        self.assertIsNotNone(review_copy.media_duration(out))


if __name__ == "__main__":
    unittest.main()
