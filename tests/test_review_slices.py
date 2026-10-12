#!/usr/bin/env python3
"""Per-step slices must be honest about where they actually start.

`review_slices.py` cuts with `-c copy`, which can only begin at a keyframe. A slice
whose manifest claims to start at the step boundary while the file actually starts
0.4s earlier shifts every annotation on the page, so the manifest records the real
start and the lead is asserted, not hoped for.

The 图拉斯 project is the reason this exists: at x264's default keyframe interval a
6-second step came out with a 7900ms lead, i.e. every "slice" was bigger than the
step it served. The review copy is written with a one-second GOP so the lead is
bounded.
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


review_slices = _load("review_slices")
review_copy = _load("review_copy")


@unittest.skipUnless(FFMPEG, "ffmpeg required")
class SliceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.edit = self.root / "edit"
        self.edit.mkdir()
        self.composite = self.edit / "final.mp4"
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
             "-i", "color=c=gray:s=320x480:d=6:r=30",
             "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo:d=6",
             "-c:v", "libx264", "-preset", "ultrafast", "-crf", "30",
             "-g", "30", "-keyint_min", "30", "-sc_threshold", "0",
             "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
             str(self.composite)], check=True)
        self.steps = [
            {"id": "s1", "startMs": 0, "endMs": 2500},
            {"id": "s2", "startMs": 3000, "endMs": 6000},
        ]

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_keyframe_lookup_never_overshoots(self):
        kfs = [0.0, 1.0, 2.0, 3.0]
        self.assertEqual(review_slices._keyframe_at_or_before(kfs, 2.5), 2.0)
        self.assertEqual(review_slices._keyframe_at_or_before(kfs, 3.0), 3.0)
        self.assertEqual(review_slices._keyframe_at_or_before(kfs, 0.4), 0.0)
        self.assertEqual(review_slices._keyframe_at_or_before(kfs, 9.0), 3.0)

    def test_slices_cover_every_step_and_start_honestly(self):
        manifest = review_slices.build_slices(
            self.root, composite_rel="edit/final.mp4", steps=self.steps)
        self.assertEqual(manifest["sliceCount"], 2)
        for entry, step in zip(manifest["slices"], self.steps):
            path = self.root / entry["file"]
            self.assertTrue(path.is_file(), entry["file"])
            # The slice may start EARLIER than the step (keyframe), never later.
            self.assertLessEqual(entry["startMs"], step["startMs"])
            self.assertLessEqual(entry["keyframeLeadMs"], 1000,
                                 "1s GOP should bound the lead")
            self.assertGreater(entry["durationS"], 0.2)

    def test_manifest_records_a_start_the_file_agrees_with(self):
        manifest = review_slices.build_slices(
            self.root, composite_rel="edit/final.mp4", steps=self.steps)
        entry = manifest["slices"][1]
        path = self.root / entry["file"]
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "frame=pts_time", "-of", "csv=p=0", str(path)],
            capture_output=True, text=True)
        first = float([x for x in proc.stdout.split() if x][0].strip(","))
        self.assertLess(abs(first), 0.05,
                        "slices are remuxed with make_zero, so the first frame is 0")

    def test_a_step_at_the_very_end_still_gets_a_slice(self):
        manifest = review_slices.build_slices(
            self.root, composite_rel="edit/final.mp4",
            steps=[{"id": "tail", "startMs": 5500, "endMs": 6000}])
        self.assertEqual(manifest["sliceCount"], 1)
        self.assertGreater(manifest["slices"][0]["durationS"], 0.1)


@unittest.skipUnless(FFMPEG, "ffmpeg required")
class ReviewCopyGopTests(unittest.TestCase):
    def test_review_copy_uses_a_one_second_gop(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src.mp4"
            subprocess.run(
                ["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
                 "-i", "color=c=gray:s=160x240:d=3:r=30",
                 "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                 str(src)], check=True)
            record = review_copy.make(src, Path(tmp) / "out.mp4", force=True)
            self.assertEqual(record["gop"], review_copy.DEFAULT_GOP)
            keys = review_slices._probe_keyframes(Path(record["path"]))
            gaps = [b - a for a, b in zip(keys, keys[1:])]
            self.assertTrue(gaps, keys)
            self.assertLessEqual(max(gaps), 1.05,
                                 f"keyframe gap too wide for slicing: {gaps}")


if __name__ == "__main__":
    unittest.main()
