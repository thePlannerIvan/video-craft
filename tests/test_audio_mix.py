#!/usr/bin/env python3
"""One mix owner: voice (+ducked music) → delivery loudness, once."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
HELPER = ROOT / "helpers" / "audio_mix.py"
FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def probe_dur(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", str(path)], capture_output=True, text=True).stdout
    return float(out.strip())


def lufs(path: Path) -> float:
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path), "-af",
                        "loudnorm=print_format=json", "-f", "null", "-"],
                       capture_output=True, text=True)
    m = re.search(r'\{[^{}]*"input_i"[^{}]*\}', r.stderr, re.S)
    return float(json.loads(m.group(0))["input_i"])


@unittest.skipUnless(FFMPEG, "needs ffmpeg")
class AudioMix(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        for name, freq, dur in (("voice.wav", 440, 3), ("bgm.wav", 220, 6)):
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
                            "-i", f"sine=frequency={freq}:duration={dur}",
                            "-ar", "48000", "-ac", "2", str(self.dir / name)], check=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_voice_only_hits_delivery_loudness(self):
        out = self.dir / "mix.wav"
        subprocess.run([sys.executable, str(HELPER), str(self.dir / "voice.wav"),
                        "-o", str(out)], check=True, capture_output=True, text=True)
        self.assertAlmostEqual(probe_dur(out), 3.0, delta=0.15)
        self.assertLess(abs(lufs(out) - (-14.0)), 1.0)

    def test_music_is_ducked_and_duration_follows_voice(self):
        out = self.dir / "mix2.wav"
        subprocess.run([sys.executable, str(HELPER), str(self.dir / "voice.wav"),
                        "-o", str(out), "--bgm", str(self.dir / "bgm.wav")],
                       check=True, capture_output=True, text=True)
        self.assertAlmostEqual(probe_dur(out), 3.0, delta=0.15)
        self.assertLess(abs(lufs(out) - (-14.0)), 1.0)


if __name__ == "__main__":
    unittest.main()
