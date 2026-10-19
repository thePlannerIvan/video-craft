#!/usr/bin/env python3
"""Self-contained 4-second fixture: base + time-mapped portrait + external SRT + one mix.

This replaces the ad-hoc /tmp spike the 2026-10 session used to check a segment.
It pins the four shared facts on synthetic media (no project assets):

  * one mix output (audio_mix.py) at the delivery loudness;
  * the portrait comes from the same cut/timeline, so the frame at t admits a
    direct pixel comparison with the portrait source at the same t;
  * captions stay an external file (the delivery contract when libass is absent);
  * provenance is recorded when the output is generated, not reconstructed later.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageChops, ImageStat

ROOT = Path(__file__).parents[1]
MIX = ROOT / "helpers" / "audio_mix.py"
FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
DUR = 4.0
SIZE = 200
X = 640 - 8 - SIZE
Y = 360 - 8 - SIZE


def sh(cmd):
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@unittest.skipUnless(FFMPEG, "needs ffmpeg/ffprobe")
class SegmentFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.dir = Path(self.tmp.name)
        sh(["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
            "-i", "testsrc2=size=640x360:rate=24", "-t", str(DUR),
            "-pix_fmt", "yuv420p", str(d / "base.mp4")])
        sh(["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
            "-i", "testsrc2=size=200x200:rate=24", "-t", str(DUR),
            "-pix_fmt", "yuv420p", str(d / "portrait.mp4")])
        sh(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
            f"color=c=black:s={SIZE}x{SIZE},format=gray,"
            f"geq=lum='if(lte((X-{SIZE//2})^2+(Y-{SIZE//2})^2,92^2),255,0)'",
            "-frames:v", "1", str(d / "mask.png")])
        sh(["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
            "-i", "sine=frequency=440:duration=4", "-ar", "48000", "-ac", "2",
            str(d / "voice.wav")])
        sh(["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
            "-i", "sine=frequency=220:duration=8", "-ar", "48000", "-ac", "2",
            str(d / "bgm.wav")])
        sh([sys.executable, str(MIX), str(d / "voice.wav"), "-o", str(d / "mix.wav"),
            "--bgm", str(d / "bgm.wav")])

    def tearDown(self):
        self.tmp.cleanup()

    def _compose(self):
        d = self.dir
        # two inputs + mask; audio is the mixed wav as a third input
        fc = (f"[1:v]scale={SIZE}:{SIZE},format=rgba[p];"
              f"[p][2:v]alphamerge[pa];"
              f"[0:v][pa]overlay={X}:{Y}[v]")
        sh(["ffmpeg", "-v", "error", "-y", "-i", str(d / "base.mp4"),
            "-i", str(d / "portrait.mp4"), "-i", str(d / "mask.png"),
            "-i", str(d / "mix.wav"), "-filter_complex", fc,
            "-map", "[v]", "-map", "3:a", "-t", str(DUR),
            "-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "160k", str(d / "segment.mp4")])
        cues = [(0.0, 1.6, "第一句"), (1.8, 3.8, "第二句")]
        (d / "segment.srt").write_text(
            "\n\n".join(f"{i+1}\n00:00:0{a:.0f},000 --> 00:00:0{b:.0f},000\n{t}"
                        for i, (a, b, t) in enumerate(cues)) + "\n", encoding="utf-8")
        prov = {"schema": "video-craft/segment-fixture",
                "inputs": {n: sha(d / n) for n in
                           ("base.mp4", "portrait.mp4", "voice.wav", "bgm.wav", "mix.wav")},
                "outputs": {n: sha(d / n) for n in ("segment.mp4", "segment.srt")}}
        (d / "provenance.json").write_text(json.dumps(prov), encoding="utf-8")

    def _frame(self, name, t):
        f = self.dir / f"{name}-{t}.png"
        sh(["ffmpeg", "-v", "error", "-y", "-ss", str(t), "-i", str(self.dir / name),
            "-frames:v", "1", str(f)])
        return Image.open(f).convert("L")

    def test_duration_loudness_sync_captions_provenance(self):
        self._compose()
        d = self.dir
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                              "-of", "csv=p=0", str(d / "segment.mp4")],
                             capture_output=True, text=True).stdout
        self.assertAlmostEqual(float(out.strip()), DUR, delta=0.2)

        r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(d / "segment.mp4"),
                            "-af", "loudnorm=print_format=json", "-f", "null", "-"],
                           capture_output=True, text=True)
        m = re.search(r'\{[^{}]*"input_i"[^{}]*\}', r.stderr, re.S)
        self.assertLess(abs(float(json.loads(m.group(0))["input_i"]) - (-14.0)), 1.0)

        inner = (X + 60, Y + 60, X + SIZE - 60, Y + SIZE - 60)
        out2 = self._frame("segment.mp4", 2).crop(inner)
        por2 = self._frame("portrait.mp4", 2).resize((SIZE, SIZE)).crop((60, 60, SIZE - 60, SIZE - 60))
        por0 = self._frame("portrait.mp4", 0).resize((SIZE, SIZE)).crop((60, 60, SIZE - 60, SIZE - 60))
        near = ImageStat.Stat(ImageChops.difference(out2, por2)).mean[0]
        far = ImageStat.Stat(ImageChops.difference(out2, por0)).mean[0]
        self.assertLess(near, 26, f"t=2 头像区与源同帧不一致（MAE {near:.1f}）")
        self.assertGreater(far, near + 3, f"头像没有随源时间变化（{near:.1f} vs {far:.1f}）")

        srt = (d / "segment.srt").read_text(encoding="utf-8")
        self.assertEqual(len(re.findall(r"^\d+$", srt, re.M)), 2)

        prov = json.loads((d / "provenance.json").read_text(encoding="utf-8"))
        self.assertEqual(len(prov["inputs"]), 5)
        self.assertEqual(len(prov["outputs"]), 2)


if __name__ == "__main__":
    unittest.main()
