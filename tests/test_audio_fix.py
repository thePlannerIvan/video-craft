#!/usr/bin/env python3
"""Tests for voice acoustic C-preset (`podcast-warm`) and raw dry bypass (`helpers/audio_fix.py`)."""
from __future__ import annotations

import json
import math
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "helpers" / "audio_fix.py"
FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def _band_rms(path: Path, low_hz: int, high_hz: int) -> float:
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "band.wav"
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error", "-i", str(path),
            "-af", f"highpass=f={low_hz}:poles=2,lowpass=f={high_hz}:poles=2",
            "-ac", "1", "-ar", "48000", "-c:a", "pcm_s16le", str(out),
        ], check=True)
        with wave.open(str(out), "rb") as wf:
            raw = wf.readframes(wf.getnframes())
        vals = struct.unpack(f"<{len(raw) // 2}h", raw)
        rms = math.sqrt(sum((v / 32768.0) ** 2 for v in vals) / max(1, len(vals)))
        return 20.0 * math.log10(max(1e-9, rms))


@unittest.skipUnless(FFMPEG, "needs ffmpeg")
class AudioFixTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        # Synthesize 4s synthetic voice-like signal: 115Hz chest + 245Hz boxy mud + 3.2kHz presence + 6.5kHz sibilance
        self.src = self.dir / "voice.wav"
        fc = (
            "sine=f=115:d=4[f1];"
            "sine=f=245:d=4[f2];"
            "sine=f=3200:d=4[f3];"
            "sine=f=6500:d=4[f4];"
            "[f1]volume=0.08[s1];"
            "[f2]volume=0.14[s2];"
            "[f3]volume=0.05[s3];"
            "[f4]volume=0.12[s4];"
            "[s1][s2][s3][s4]amix=inputs=4:normalize=0,volume=0.5[out]"
        )
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono",
            "-t", "4", "-filter_complex", fc, "-map", "[out]", "-ar", "48000", "-ac", "1", str(self.src),
        ], check=True)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_default_preset_is_podcast_warm_with_spectrum_and_loudness_targets(self) -> None:
        out = self.dir / "warm.wav"
        proc = subprocess.run(
            [sys.executable, str(HELPER), str(self.src), "-o", str(out), "--json"],
            capture_output=True, text=True, check=True,
        )
        stats = json.loads(proc.stdout)
        self.assertEqual(stats["preset"], "podcast-warm")
        self.assertFalse(stats["raw"])
        self.assertLess(abs(stats["output_lufs"] - (-14.0)), 1.0)
        self.assertLessEqual(stats["true_peak_dbtp"], -1.0)

        # Verify spectral shift: 115Hz boost vs 245Hz cut increases (115Hz - 245Hz) ratio!
        in_delta = _band_rms(self.src, 95, 135) - _band_rms(self.src, 215, 275)
        out_delta = _band_rms(out, 95, 135) - _band_rms(out, 215, 275)
        self.assertGreater(out_delta - in_delta, 3.0, f"expected chest boost/mud cut, delta went {in_delta:.2f} -> {out_delta:.2f}")

    def test_raw_flag_bypasses_eq_and_compression(self) -> None:
        out = self.dir / "raw.wav"
        proc = subprocess.run(
            [sys.executable, str(HELPER), str(self.src), "-o", str(out), "--raw", "--json"],
            capture_output=True, text=True, check=True,
        )
        stats = json.loads(proc.stdout)
        self.assertEqual(stats["preset"], "raw")
        self.assertTrue(stats["raw"])
        # Raw should NOT boost 115Hz relative to 245Hz or shift LUFS toward -14.0
        in_delta = _band_rms(self.src, 95, 135) - _band_rms(self.src, 215, 275)
        out_delta = _band_rms(out, 95, 135) - _band_rms(out, 215, 275)
        self.assertAlmostEqual(in_delta, out_delta, delta=0.5)
        self.assertAlmostEqual(stats["input_lufs"], stats["output_lufs"], delta=0.6)

    def test_cli_help_clarifies_auditioning_role_vs_audio_mix(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(HELPER), "--help"],
            check=True, capture_output=True, text=True,
        )
        help_text = " ".join(proc.stdout.split())
        self.assertIn("audio_mix.py", help_text)
        self.assertIn("podcast-warm", help_text)
        self.assertIn("--ab", help_text)
        self.assertIn("twice", help_text)
        self.assertIn("--voice-preset none", help_text)


if __name__ == "__main__":
    unittest.main()
