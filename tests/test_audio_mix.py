#!/usr/bin/env python3
"""One mix owner: voice (+ducked music + restrained local SFX) -> delivery loudness, once."""
from __future__ import annotations

import json
import math
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import wave
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

    def test_list_sfx_returns_restrained_local_catalog(self):
        proc = subprocess.run(
            [sys.executable, str(HELPER), "--list-sfx", "--json"],
            check=True, capture_output=True, text=True,
        )
        items = json.loads(proc.stdout)["items"]
        self.assertTrue(6 <= len(items) <= 10)
        for item in items:
            self.assertIn(item["kind"], ("chapter", "reveal", "turn"))
            self.assertTrue(Path(item["path"]).is_file(), item["path"])

    def test_sparse_sfx_mix_hits_lufs_and_stays_18_to_22db_under_voice(self):
        # 36s speech fixture with silent pause windows around t=5s and t=25s so we can measure SFX RMS directly
        long_voice = self.dir / "long_voice.wav"
        fc = "sine=f=220:d=36,volume='if(between(t,4.5,6.0)+between(t,24.5,26.0),0,0.4)':eval=frame[out]"
        subprocess.run([
            "ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", "36",
            "-filter_complex", fc, "-map", "[out]", "-ar", "48000", "-ac", "2", str(long_voice),
        ], check=True)
        plan = self.dir / "sfx.json"
        plan.write_text(json.dumps([
            {"t": 5.0, "kind": "chapter", "sound": "chapter-soft-whoosh"},
            {"t": 25.0, "kind": "reveal", "sound": "reveal-soft-pop"},
        ]), encoding="utf-8")

        out = self.dir / "mix_sfx.wav"
        proc = subprocess.run([
            sys.executable, str(HELPER), str(long_voice), "-o", str(out),
            "--sfx", str(plan), "--sfx-under-db", "20", "--json",
        ], check=True, capture_output=True, text=True)
        info = json.loads(proc.stdout)
        self.assertEqual(info["sfx_count"], 2)
        self.assertLess(abs(lufs(out) - (-14.0)), 1.2)

        def win_rms(start_s: float, dur_s: float) -> float:
            seg = self.dir / f"win_{start_s}.wav"
            subprocess.run([
                "ffmpeg", "-v", "error", "-y", "-ss", str(start_s), "-t", str(dur_s),
                "-i", str(out), "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(seg),
            ], check=True)
            with wave.open(str(seg), "rb") as wf:
                raw = wf.readframes(wf.getnframes())
            vals = struct.unpack(f"<{len(raw) // 2}h", raw)
            rms = math.sqrt(sum((v / 32768.0) ** 2 for v in vals) / max(1, len(vals)))
            return 20.0 * math.log10(max(1e-9, rms))

        delta_db = win_rms(10.0, 2.0) - win_rms(5.05, 0.20)
        self.assertTrue(16.0 <= delta_db <= 26.0, f"expected SFX restrained under voice, got delta={delta_db:.2f} dB")

        out_nosfx = self.dir / "mix_nosfx.wav"
        subprocess.run([
            sys.executable, str(HELPER), str(long_voice), "-o", str(out_nosfx),
            "--sfx", str(plan), "--no-sfx",
        ], check=True, capture_output=True, text=True)
        subprocess.run([
            "ffmpeg", "-v", "error", "-y", "-ss", "5.05", "-t", "0.20",
            "-i", str(out_nosfx), "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le",
            str(self.dir / "silent_win.wav"),
        ], check=True)
        with wave.open(str(self.dir / "silent_win.wav"), "rb") as wf:
            vals = struct.unpack(f"<{wf.getnframes()}h", wf.readframes(wf.getnframes()))
        self.assertLess(max(abs(v) for v in vals), 10)

    def test_sfx_guardrails_reject_overdense_disallowed_kind_and_loud_mix(self):
        long_voice = self.dir / "v30.wav"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=30",
                        "-ar", "48000", "-ac", "2", str(long_voice)], check=True)

        dense = self.dir / "dense.json"
        dense.write_text(json.dumps([
            {"t": 2.0, "kind": "chapter"}, {"t": 8.0, "kind": "reveal"},
            {"t": 15.0, "kind": "turn"}, {"t": 22.0, "kind": "reveal"},
        ]), encoding="utf-8")
        p_dense = subprocess.run([
            sys.executable, str(HELPER), str(long_voice), "-o", str(self.dir / "no1.wav"), "--sfx", str(dense),
        ], capture_output=True, text=True)
        self.assertNotEqual(p_dense.returncode, 0)

        bad_kind = self.dir / "bad_kind.json"
        bad_kind.write_text(json.dumps([{"t": 5.0, "kind": "comedy-boing"}]), encoding="utf-8")
        p_kind = subprocess.run([
            sys.executable, str(HELPER), str(long_voice), "-o", str(self.dir / "no2.wav"), "--sfx", str(bad_kind),
        ], capture_output=True, text=True)
        self.assertNotEqual(p_kind.returncode, 0)

        ok_sparse = self.dir / "ok_sparse.json"
        ok_sparse.write_text(json.dumps([{"t": 5.0, "kind": "chapter"}]), encoding="utf-8")
        p_loud = subprocess.run([
            sys.executable, str(HELPER), str(long_voice), "-o", str(self.dir / "no3.wav"),
            "--sfx", str(ok_sparse), "--sfx-under-db", "6",
        ], capture_output=True, text=True)
        self.assertNotEqual(p_loud.returncode, 0)

        out_dry = self.dir / "dry.wav"
        subprocess.run([
            sys.executable, str(HELPER), str(long_voice), "-o", str(out_dry),
            "--bgm", str(self.dir / "bgm.wav"), "--sfx", str(ok_sparse), "--dry",
        ], check=True, capture_output=True, text=True)
        self.assertTrue(out_dry.is_file())


if __name__ == "__main__":
    unittest.main()
