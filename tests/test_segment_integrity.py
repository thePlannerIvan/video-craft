"""A segment that did not survive extraction must not reach the film.

The reported failure: ffmpeg exited 0 having written a 48-byte segment
(`moov atom not found`). The concat skipped it, the film came out 80.000s
against a nominal 84.000s, and `segment_durations.json` recorded 80.0 as if it
had been measured — so `check_edl` and `verify_av` both passed. The cache-hit
path read each segment back; the freshly-extracted path did not.

Three behaviours, all here:

① read back every segment, cached or fresh;
② re-extract once, then fail naming the segment index and its file;
③ refuse to write `segment_durations.json` when the total does not match the EDL.

The torn file is real (48 zero bytes), and a real ffmpeg extracts the good one —
a mocked probe would not have caught the original bug.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import render as r

HAVE_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
GRID = 30.0


def run(cmd: list) -> None:
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg/ffprobe not on PATH")
class SegmentIntegrityTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.edit = self.root / "edit"
        self.edit.mkdir()
        self.source = self.root / "src.mp4"
        run(["ffmpeg", "-y",
             "-f", "lavfi", "-i", "testsrc=size=320x240:rate=30:duration=4",
             "-f", "lavfi", "-i", "sine=frequency=440:duration=4",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast",
             "-c:a", "pcm_s16le", "-shortest", str(self.source)])

    def edl(self, *, seconds: float, count: int = 1) -> dict:
        return {
            "version": 1,
            "sources": {"S1": str(self.source)},
            "ranges": [{"source": "S1", "start": 0.0, "end": seconds}
                       for _ in range(count)],
            "grade": "none",
        }

    def extract(self, edl: dict, tag: str = "t"):
        edl_path = self.edit / f"edl-{tag}.json"
        edl_path.write_text(json.dumps(edl), encoding="utf-8")
        return r.extract_all_segments(edl, self.edit, preview=False, clips_tag=tag,
                                      use_cache=True, edl_path=edl_path)

    def torn(self, out_path: Path) -> None:
        """The exact artifact from the report: 48 zero bytes."""
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"\x00" * 48)

    def patch_extract(self, behaviour):
        """Replace extract_segment. `behaviour(real, out_path)` decides what happens."""
        calls: list = []
        original = r.extract_segment

        def wrapper(source, start, duration, grade_filter, out_path, **kwargs):
            calls.append(out_path)

            def real():
                return original(source, start, duration, grade_filter, out_path, **kwargs)

            return behaviour(real, out_path)

        r.extract_segment = wrapper
        self.addCleanup(setattr, r, "extract_segment", original)
        return calls

    # ① a torn segment is never accepted -------------------------------------

    def test_a_torn_segment_is_re_extracted_and_the_film_is_complete(self):
        def behaviour(real, out_path):
            if len(log) == 1:
                self.torn(out_path)
                return 0.0
            return real()

        log = self.patch_extract(behaviour)
        paths, vts = self.extract(self.edl(seconds=1.0))

        self.assertEqual(len(log), 2, "the torn segment was not re-extracted")
        self.assertEqual(len(paths), 1)
        self.assertAlmostEqual(vts[0], 1.0, places=2)
        # the recorded timeline matches the file that is actually on disk
        recorded = json.loads((self.edit / "segment_durations.json").read_text())
        self.assertAlmostEqual(recorded["t"]["total_s"], vts[0], places=6)

    def test_a_segment_that_stays_torn_fails_naming_index_and_path(self):
        log = self.patch_extract(lambda real, out_path: (self.torn(out_path), 0.0)[1])

        with self.assertRaises(r.SegmentError) as caught:
            self.extract(self.edl(seconds=1.0))

        message = str(caught.exception)
        self.assertIn("[00]", message, message)
        self.assertIn("seg_00_S1.mp4", message, message)
        self.assertIn("twice in a row", message, message)
        self.assertEqual(len(log), 2, "it must retry exactly once")
        self.assertFalse((self.edit / "segment_durations.json").exists(),
                         "a failed render must not record a timeline")

    def test_an_unreadable_segment_is_rejected(self):
        target = self.root / "junk.mp4"
        target.write_bytes(b"\x00" * 48)
        with self.assertRaises(r.SegmentError) as caught:
            r.check_segment(target, 1.0, GRID)
        self.assertIn("not a readable segment", str(caught.exception))

    def test_a_segment_of_the_wrong_length_is_rejected(self):
        short = self.root / "short.mp4"
        run(["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=30:duration=0.3",
             "-f", "lavfi", "-i", "sine=frequency=440:duration=0.3",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast",
             "-c:a", "pcm_s16le", "-shortest", str(short)])
        with self.assertRaises(r.SegmentError) as caught:
            r.check_segment(short, 2.0, GRID)
        self.assertIn("was requested", str(caught.exception))

    def test_a_good_segment_passes_read_back(self):
        log = self.patch_extract(lambda real, out_path: real())
        paths, vts = self.extract(self.edl(seconds=1.0))
        self.assertEqual(len(log), 1)
        self.assertAlmostEqual(r.check_segment(paths[0], 1.0, GRID), vts[0], places=6)

    def test_a_second_run_reuses_the_cache_without_re_extracting(self):
        self.patch_extract(lambda real, out_path: real())
        self.extract(self.edl(seconds=1.0))
        log = self.patch_extract(
            lambda real, out_path: self.fail("a valid cached segment must not be re-extracted"))
        paths, vts = self.extract(self.edl(seconds=1.0))
        self.assertEqual(log, [])
        self.assertEqual(len(paths), 1)

    # ③ the total is asserted before anything is written ----------------------

    def test_the_real_80_against_84_case_is_refused(self):
        ranges = [{"source": "S1", "start": 0.0, "end": 8.4} for _ in range(10)]
        with self.assertRaises(r.SegmentError) as caught:
            r.check_total_duration([8.0] * 10, ranges, GRID)
        message = str(caught.exception)
        self.assertIn("80.000s", message)
        self.assertIn("84.000s", message)

    def test_one_frame_per_segment_of_drift_is_allowed(self):
        ranges = [{"source": "S1", "start": 0.0, "end": 8.4} for _ in range(10)]
        self.assertAlmostEqual(r.check_total_duration([8.42] * 10, ranges, GRID),
                               84.2, places=6)

    def test_the_total_is_checked_before_the_timeline_is_written(self):
        seen = {}

        def guard(durations, ranges, grid):
            seen["called"] = True
            raise r.SegmentError("total guard tripped (test)")

        original = r.check_total_duration
        r.check_total_duration = guard
        self.addCleanup(setattr, r, "check_total_duration", original)
        self.patch_extract(lambda real, out_path: real())

        with self.assertRaises(r.SegmentError):
            self.extract(self.edl(seconds=1.0))
        self.assertTrue(seen.get("called"), "the total guard never ran")
        self.assertFalse((self.edit / "segment_durations.json").exists())


if __name__ == "__main__":
    unittest.main()
