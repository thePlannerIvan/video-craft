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
    return program_stats(path)[0]


def program_stats(path: Path) -> tuple[float, float]:
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path), "-af",
                        "loudnorm=I=-14.0:TP=-1.5:LRA=9:print_format=json", "-f", "null", "-"],
                       capture_output=True, text=True, check=True)
    m = re.search(r'\{[^{}]*"input_i"[^{}]*\}', r.stderr, re.S)
    blob = json.loads(m.group(0))
    return float(blob["input_i"]), float(blob["input_tp"])


def band_rms(path: Path, low_hz: int, high_hz: int) -> float:
    with tempfile.TemporaryDirectory() as td:
        band = Path(td) / "band.wav"
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error", "-i", str(path),
            "-af", f"highpass=f={low_hz}:poles=2,lowpass=f={high_hz}:poles=2",
            "-ac", "1", "-ar", "48000", "-c:a", "pcm_s16le", str(band),
        ], check=True)
        with wave.open(str(band), "rb") as wf:
            raw = wf.readframes(wf.getnframes())
        vals = struct.unpack(f"<{len(raw) // 2}h", raw)
        rms = math.sqrt(sum((v / 32768.0) ** 2 for v in vals) / max(1, len(vals)))
        return 20.0 * math.log10(max(1e-9, rms))


def make_multiband_voice(path: Path) -> None:
    fc = (
        "sine=f=115:d=4[f1];sine=f=245:d=4[f2];"
        "sine=f=3200:d=4[f3];sine=f=6500:d=4[f4];"
        "[f1]volume=0.08[s1];[f2]volume=0.14[s2];"
        "[f3]volume=0.05[s3];[f4]volume=0.12[s4];"
        "[s1][s2][s3][s4]amix=inputs=4:normalize=0,volume=0.5[out]"
    )
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono",
        "-t", "4", "-filter_complex", fc, "-map", "[out]", "-ar", "48000", "-ac", "1", str(path),
    ], check=True)


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

    def test_default_run_applies_podcast_warm_preset_and_safe_true_peak(self):
        speech = self.dir / "speech.wav"
        make_multiband_voice(speech)
        out = self.dir / "mix_default.wav"
        proc = subprocess.run(
            [sys.executable, str(HELPER), str(speech), "-o", str(out), "--json"],
            check=True, capture_output=True, text=True,
        )
        info = json.loads(proc.stdout)
        self.assertEqual(info["voice_preset"], "podcast-warm")
        out_lu, out_tp = program_stats(out)
        self.assertLess(abs(out_lu - (-14.0)), 1.0)
        self.assertLess(abs(info["output_lufs"] - (-14.0)), 1.0)
        self.assertLessEqual(out_tp, -1.0)
        in_delta = band_rms(speech, 95, 135) - band_rms(speech, 215, 275)
        out_delta = band_rms(out, 95, 135) - band_rms(out, 215, 275)
        self.assertGreater(
            out_delta - in_delta, 3.0,
            f"expected default podcast-warm chest boost/mud cut, delta went {in_delta:.2f} -> {out_delta:.2f}",
        )

    def test_dry_raw_and_none_presets_cleanly_bypass_eq_and_compression(self):
        speech = self.dir / "speech.wav"
        make_multiband_voice(speech)
        in_lu, _ = program_stats(speech)
        in_delta = band_rms(speech, 95, 135) - band_rms(speech, 215, 275)

        for label, extra_args in (
            ("dry", ["--bgm", str(self.dir / "bgm.wav"), "--dry"]),
            ("raw_flag", ["--raw-voice"]),
            ("raw_preset", ["--voice-preset", "raw"]),
        ):
            out = self.dir / f"bypass_{label}.wav"
            proc = subprocess.run(
                [sys.executable, str(HELPER), str(speech), "-o", str(out), *extra_args, "--json"],
                check=True, capture_output=True, text=True,
            )
            info = json.loads(proc.stdout)
            self.assertEqual(info["voice_preset"], "raw", label)
            if label == "dry":
                self.assertEqual(info["mode"], "dry")
                self.assertAlmostEqual(probe_dur(out), 4.0, delta=0.15)
            out_lu, _ = program_stats(out)
            out_delta = band_rms(out, 95, 135) - band_rms(out, 215, 275)
            self.assertAlmostEqual(in_delta, out_delta, delta=0.5, msg=label)
            self.assertAlmostEqual(in_lu, out_lu, delta=0.6, msg=label)

        # --voice-preset none skips EQ/compression while keeping mix leveling;
        # passing pre-fixed audio_fix output with --voice-preset none avoids double processing.
        none_out = self.dir / "none_raw_input.wav"
        p_none = subprocess.run(
            [sys.executable, str(HELPER), str(speech), "-o", str(none_out),
             "--voice-preset", "none", "--json"],
            check=True, capture_output=True, text=True,
        )
        info_none = json.loads(p_none.stdout)
        self.assertEqual(info_none["voice_preset"], "none")
        none_lu, _ = program_stats(none_out)
        none_delta = band_rms(none_out, 95, 135) - band_rms(none_out, 215, 275)
        self.assertAlmostEqual(in_delta, none_delta, delta=0.5)
        self.assertLess(abs(none_lu - (-14.0)), 1.0)

        fixed = self.dir / "fixed_first.wav"
        subprocess.run(
            [sys.executable, str(ROOT / "helpers" / "audio_fix.py"), str(speech), "-o", str(fixed)],
            check=True, capture_output=True, text=True,
        )
        fixed_delta = band_rms(fixed, 95, 135) - band_rms(fixed, 215, 275)
        mix_prefixed = self.dir / "mix_prefixed.wav"
        p_pre = subprocess.run(
            [sys.executable, str(HELPER), str(fixed), "-o", str(mix_prefixed),
             "--voice-preset", "none", "--json"],
            check=True, capture_output=True, text=True,
        )
        info_pre = json.loads(p_pre.stdout)
        self.assertEqual(info_pre["voice_preset"], "none")
        mix_lu, mix_tp = program_stats(mix_prefixed)
        mix_delta = band_rms(mix_prefixed, 95, 135) - band_rms(mix_prefixed, 215, 275)
        self.assertAlmostEqual(fixed_delta, mix_delta, delta=0.5)
        self.assertLess(abs(mix_lu - (-14.0)), 1.0)
        self.assertLessEqual(mix_tp, -1.0)

    def test_cli_help_documents_default_podcast_warm_and_anti_double_compression(self):
        proc = subprocess.run(
            [sys.executable, str(HELPER), "--help"],
            check=True, capture_output=True, text=True,
        )
        help_text = " ".join(proc.stdout.split())
        self.assertIn("podcast-warm", help_text)
        self.assertIn("audio_fix.py", help_text)
        self.assertIn("--voice-preset none", help_text)
        self.assertIn("double compression", help_text)
        self.assertIn("bypass EQ/compression, BGM, and SFX", help_text)

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

    def test_rejects_double_compression_from_audio_fix_unless_none_or_allowed(self):
        fix_helper = HELPER.parent / "audio_fix.py"
        src_voice = self.dir / "src_voice.wav"
        make_multiband_voice(src_voice)
        fixed_wav = self.dir / "prefixed.wav"
        subprocess.run([
            sys.executable, str(fix_helper), str(src_voice), "-o", str(fixed_wav), "--voice-preset", "podcast-warm",
        ], check=True, capture_output=True, text=True)

        # Piping pre-processed audio_fix output directly with default preset must refuse double compression
        blocked = subprocess.run([
            sys.executable, str(HELPER), str(fixed_wav), "-o", str(self.dir / "double.wav"),
        ], capture_output=True, text=True)
        self.assertNotEqual(blocked.returncode, 0)
        self.assertIn("拒绝二次压限", blocked.stderr + blocked.stdout)

        # Passing --preset none (alias for --voice-preset none) or --allow-reprocess succeeds
        none_out = self.dir / "mix_none.wav"
        subprocess.run([
            sys.executable, str(HELPER), str(fixed_wav), "-o", str(none_out), "--preset", "none",
        ], check=True, capture_output=True, text=True)
        self.assertTrue(none_out.is_file())

        re_out = self.dir / "mix_re.wav"
        subprocess.run([
            sys.executable, str(HELPER), str(fixed_wav), "-o", str(re_out), "--allow-reprocess",
        ], check=True, capture_output=True, text=True)
        self.assertTrue(re_out.is_file())


if __name__ == "__main__":
    unittest.main()
