#!/usr/bin/env python3
"""keep list → EDL snaps cut edges onto measured silence, not word frames."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
HELPER = ROOT / "helpers" / "edl_from_keep.py"
FFMPEG = shutil.which("ffmpeg") is not None


@unittest.skipUnless(FFMPEG, "needs ffmpeg")
class EdlFromKeep(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        # 0-1 silence | 1-3 tone | 3-4 silence | 4-6 tone
        subprocess.run([
            "ffmpeg", "-v", "error", "-y", "-f", "lavfi",
            "-i", "sine=frequency=440:duration=6",
            "-af", "volume=volume='if(between(t,1,3)+between(t,4,6),1,0)':eval=frame",
            "-ar", "16000", "-ac", "1", str(self.dir / "src.wav")], check=True)

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, keeps, *extra):
        cfg = {"sources": {"SRC": "src.wav"}, "keeps": keeps}
        (self.dir / "keeps.json").write_text(json.dumps(cfg), encoding="utf-8")
        edit = self.dir / "edit"
        subprocess.run([sys.executable, str(HELPER), str(self.dir / "keeps.json"),
                        "--edit-dir", str(edit), *extra], check=True,
                       capture_output=True, text=True)
        return json.loads((edit / "edl.json").read_text(encoding="utf-8"))

    def test_edges_snap_to_silence_boundaries(self):
        edl = self._run([{"source": "SRC", "start": 1.05, "end": 3.95}])
        r = edl["ranges"][0]
        self.assertAlmostEqual(r["start"], 1.0, delta=0.05)
        self.assertAlmostEqual(r["end"], 4.0, delta=0.05)

    def test_no_snap_keeps_values(self):
        edl = self._run([{"source": "SRC", "start": 1.05, "end": 3.95}], "--no-snap")
        r = edl["ranges"][0]
        self.assertEqual((r["start"], r["end"]), (1.05, 3.95))

    def test_out_of_tolerance_keeps_value_and_warns(self):
        edl = self._run([{"source": "SRC", "start": 2.2, "end": 2.8}], "--snap-tol", "0.1")
        r = edl["ranges"][0]
        self.assertEqual((r["start"], r["end"]), (2.2, 2.8))


if __name__ == "__main__":
    unittest.main()
