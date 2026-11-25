#!/usr/bin/env python3
"""Black-box tests for default pause de-breathing, audio_diag breath reporting, and Voice Polish CLI consolidation."""
from __future__ import annotations

import json
import math
import shutil
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
AUDIO_MIX = ROOT / "helpers" / "audio_mix.py"
AUDIO_FIX = ROOT / "helpers" / "audio_fix.py"
AUDIO_DIAG = ROOT / "helpers" / "_internal" / "audio_diag.py"
FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def _band_noise(rng: np.random.Generator, n: int, sr: int, lo_hz: float, hi_hz: float, target_dbfs: float) -> np.ndarray:
    raw = rng.standard_normal(n).astype(np.float64)
    freqs = np.fft.rfftfreq(n, d=1.0 / sr)
    spec = np.fft.rfft(raw)
    mask = (freqs >= lo_hz) & (freqs <= hi_hz)
    spec[~mask] = 0.0
    sig = np.fft.irfft(spec, n=n)
    rms = float(np.sqrt(np.mean(sig * sig))) or 1e-12
    target_amp = 10.0 ** (target_dbfs / 20.0)
    return sig * (target_amp / rms)


def _voiced_burst(n: int, sr: int, f0: float, target_dbfs: float) -> np.ndarray:
    t = np.arange(n, dtype=np.float64) / sr
    sig = (
        0.55 * np.sin(2.0 * math.pi * f0 * t)
        + 0.30 * np.sin(2.0 * math.pi * (2.0 * f0) * t)
        + 0.15 * np.sin(2.0 * math.pi * (3.0 * f0) * t)
        + 0.08 * np.sin(2.0 * math.pi * (5.0 * f0) * t)
    )
    rms = float(np.sqrt(np.mean(sig * sig))) or 1e-12
    target_amp = 10.0 ** (target_dbfs / 20.0)
    return sig * (target_amp / rms)


def _write_speech_with_breaths_wav(
    path: Path,
    sr: int = 48000,
    channels: int = 2,
    seed: int = 42,
    level_shift_db: float = 0.0,
) -> None:
    """Create a 4.3s fixture with speech bursts, consonant onsets/tails, micro-gap, and >=140ms breathy pauses."""
    rng = np.random.default_rng(seed)
    dur_s = 4.30
    total = int(round(dur_s * sr))
    mono = rng.standard_normal(total).astype(np.float64) * (10.0 ** ((-64.0 + level_shift_db) / 20.0))

    def put(t0: float, t1: float, sig: np.ndarray) -> None:
        i0 = int(round(t0 * sr))
        i1 = min(total, i0 + len(sig))
        mono[i0:i1] = sig[: i1 - i0]

    def seg_len(t0: float, t1: float) -> int:
        return int(round(t1 * sr)) - int(round(t0 * sr))

    # Speech burst 1 + unvoiced consonant tail
    put(0.00, 0.80, _voiced_burst(seg_len(0.00, 0.80), sr, 150.0, -17.0 + level_shift_db))
    put(0.80, 0.84, _band_noise(rng, seg_len(0.80, 0.84), sr, 3500.0, min(7000.0, sr * 0.45), -26.0 + level_shift_db))

    # Pause valley 1 (>=140ms): breath at 0.98..1.30s
    put(0.98, 1.30, _band_noise(rng, seg_len(0.98, 1.30), sr, 600.0, min(3200.0, sr * 0.4), -31.0 + level_shift_db))

    # Unvoiced consonant onset + speech burst 2
    put(1.44, 1.48, _band_noise(rng, seg_len(1.44, 1.48), sr, 3500.0, min(7000.0, sr * 0.45), -25.0 + level_shift_db))
    put(1.48, 2.30, _voiced_burst(seg_len(1.48, 2.30), sr, 175.0, -17.0 + level_shift_db))

    # Short 90ms micro-gap (<140ms) -> must remain protected
    put(2.30, 2.39, _band_noise(rng, seg_len(2.30, 2.39), sr, 600.0, min(2800.0, sr * 0.4), -38.0 + level_shift_db))

    # Speech burst 3
    put(2.39, 3.10, _voiced_burst(seg_len(2.39, 3.10), sr, 140.0, -17.0 + level_shift_db))

    # Pause valley 2 (>=140ms): breath at 3.22..3.55s
    put(3.22, 3.55, _band_noise(rng, seg_len(3.22, 3.55), sr, 600.0, min(3200.0, sr * 0.4), -30.0 + level_shift_db))

    # Speech burst 4
    put(3.70, 4.30, _voiced_burst(seg_len(3.70, 4.30), sr, 160.0, -17.0 + level_shift_db))

    pcm = np.clip(np.rint(mono * 32767.0), -32768, 32767).astype(np.int16)
    if channels > 1:
        pcm = np.repeat(pcm[:, None], channels, axis=1)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())


def _read_wav_mono_and_meta(path: Path) -> tuple[np.ndarray, int, int, int]:
    with wave.open(str(path), "rb") as wf:
        sr = wf.getframerate()
        nc = wf.getnchannels()
        nf = wf.getnframes()
        raw = wf.readframes(nf)
    pcm = np.frombuffer(raw, dtype=np.int16).reshape(-1, nc).astype(np.float64) / 32768.0
    return pcm.mean(axis=1), sr, nc, nf


def _window_rms_db(mono: np.ndarray, sr: int, t0: float, t1: float) -> float:
    i0 = max(0, int(round(t0 * sr)))
    i1 = min(len(mono), int(round(t1 * sr)))
    seg = mono[i0:i1]
    rms = float(np.sqrt(np.mean(seg * seg))) + 1e-12
    return 20.0 * math.log10(rms)


@unittest.skipUnless(FFMPEG, "needs ffmpeg and ffprobe")
class DebreathAndVoicePolishTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.src = self.dir / "voice_breathy.wav"
        _write_speech_with_breaths_wav(self.src, sr=48000, channels=2)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_default_podcast_warm_debreaths_pauses_with_zero_drift_and_protected_speech(self) -> None:
        out_debreath = self.dir / "mix_default.wav"
        out_nodebreath = self.dir / "mix_nodebreath.wav"

        proc_on = subprocess.run(
            [sys.executable, str(AUDIO_MIX), str(self.src), "-o", str(out_debreath), "--json"],
            check=True, capture_output=True, text=True,
        )
        info_on = json.loads(proc_on.stdout)
        self.assertEqual(info_on["voice_preset"], "podcast-warm")
        self.assertTrue(info_on["debreath"])
        self.assertEqual(info_on["sfx_count"], 0)
        self.assertLess(abs(info_on["output_lufs"] - (-14.0)), 1.0)

        proc_off = subprocess.run(
            [sys.executable, str(AUDIO_MIX), str(self.src), "-o", str(out_nodebreath), "--no-debreath", "--json"],
            check=True, capture_output=True, text=True,
        )
        info_off = json.loads(proc_off.stdout)
        self.assertFalse(info_off["debreath"])

        _, _, _, nf_src = _read_wav_mono_and_meta(self.src)
        mono_on, sr_on, _, nf_on = _read_wav_mono_and_meta(out_debreath)
        mono_off, sr_off, _, nf_off = _read_wav_mono_and_meta(out_nodebreath)

        # 1. Exact sample count preservation (0.000s drift)
        self.assertEqual(nf_on, nf_src)
        self.assertEqual(nf_off, nf_src)

        # 2. Protected speech bursts, unvoiced consonant onset/tail, and <140ms micro-gap stay within <= 0.1 dB
        for label, t0, t1 in (
            ("speech_1", 0.05, 0.75),
            ("consonant_tail", 0.80, 0.84),
            ("consonant_onset", 1.44, 1.48),
            ("speech_2", 1.50, 2.25),
            ("micro_gap", 2.31, 2.38),
            ("speech_3", 2.42, 3.05),
            ("speech_4", 3.75, 4.25),
        ):
            delta = abs(_window_rms_db(mono_on, sr_on, t0, t1) - _window_rms_db(mono_off, sr_off, t0, t1))
            self.assertLessEqual(delta, 0.1, f"{label} RMS shifted by {delta:.3f} dB (> 0.1 dB)")

        # 3. >=140ms pause breath valleys are cleanly attenuated toward -62 dBFS floor
        for label, t0, t1 in (("breath_1", 1.02, 1.26), ("breath_2", 3.26, 3.51)):
            db_on = _window_rms_db(mono_on, sr_on, t0, t1)
            db_off = _window_rms_db(mono_off, sr_off, t0, t1)
            self.assertLess(db_on, -52.0, f"{label} expected <= -52 dBFS after debreath, got {db_on:.2f}")
            self.assertGreater(db_off - db_on, 15.0, f"{label} expected >15 dB drop, got {db_off:.2f} -> {db_on:.2f}")

    def test_arbitrary_sample_rate_and_mono_in_audio_fix_and_audio_mix(self) -> None:
        mono_44k = self.dir / "voice_44k_mono.wav"
        _write_speech_with_breaths_wav(mono_44k, sr=44100, channels=1)

        out_mix = self.dir / "out_44k_mix.wav"
        proc_mix = subprocess.run(
            [sys.executable, str(AUDIO_MIX), str(mono_44k), "-o", str(out_mix), "--json"],
            check=True, capture_output=True, text=True,
        )
        info_mix = json.loads(proc_mix.stdout)
        self.assertTrue(info_mix["debreath"])
        mono_out, sr_out, nc_out, _ = _read_wav_mono_and_meta(out_mix)
        self.assertEqual(sr_out, 48000)
        self.assertEqual(nc_out, 2)
        self.assertLess(_window_rms_db(mono_out, sr_out, 1.02, 1.26), -52.0)

        out_fix = self.dir / "out_fix.wav"
        proc_fix = subprocess.run(
            [sys.executable, str(AUDIO_FIX), str(self.src), "-o", str(out_fix), "--json"],
            check=True, capture_output=True, text=True,
        )
        stats_fix = json.loads(proc_fix.stdout)
        self.assertTrue(stats_fix["debreath"])
        _, _, _, nf_src = _read_wav_mono_and_meta(self.src)
        mono_fix, sr_fix, _, nf_fix = _read_wav_mono_and_meta(out_fix)
        self.assertEqual(nf_fix, nf_src)
        self.assertLess(_window_rms_db(mono_fix, sr_fix, 1.02, 1.26), -52.0)

        out_fix_off = self.dir / "out_fix_nodebreath.wav"
        proc_fix_off = subprocess.run(
            [sys.executable, str(AUDIO_FIX), str(self.src), "-o", str(out_fix_off), "--no-debreath", "--json"],
            check=True, capture_output=True, text=True,
        )
        self.assertFalse(json.loads(proc_fix_off.stdout)["debreath"])
        mono_fix_off, sr_fix_off, _, _ = _read_wav_mono_and_meta(out_fix_off)
        self.assertGreater(_window_rms_db(mono_fix_off, sr_fix_off, 1.02, 1.26), -38.0)

    def test_audio_diag_json_reports_pause_breath_metrics_before_and_after(self) -> None:
        proc_before = subprocess.run(
            [sys.executable, str(AUDIO_DIAG), str(self.src), "--json"],
            check=True, capture_output=True, text=True,
        )
        rep_before = json.loads(proc_before.stdout)
        self.assertGreaterEqual(rep_before["breath_valleys"], 2)
        self.assertGreater(rep_before["pause_breath_max_db"], -45.0)

        cleaned = self.dir / "cleaned.wav"
        subprocess.run(
            [sys.executable, str(AUDIO_MIX), str(self.src), "-o", str(cleaned)],
            check=True, capture_output=True, text=True,
        )
        proc_after = subprocess.run(
            [sys.executable, str(AUDIO_DIAG), str(cleaned), "--json"],
            check=True, capture_output=True, text=True,
        )
        rep_after = json.loads(proc_after.stdout)
        self.assertEqual(rep_after["breath_valleys"], 0)
        self.assertLess(rep_after["pause_breath_max_db"], -52.0)

    def test_audio_mix_ab_mode_runs_directly_and_supports_no_debreath(self) -> None:
        ab_dir = self.dir / "ab_default"
        proc_ab = subprocess.run(
            [sys.executable, str(AUDIO_MIX), str(self.src), "--ab", "0.5,3", "--ab-out", str(ab_dir), "--json"],
            check=True, capture_output=True, text=True,
        )
        info_ab = json.loads(proc_ab.stdout)
        self.assertEqual(info_ab["mode"], "ab")
        self.assertTrue(info_ab["debreath"])
        raw_ab = ab_dir / f"{self.src.stem}-原始-3s.wav"
        proc_ab_wav = ab_dir / f"{self.src.stem}-处理-3s.wav"
        self.assertTrue(raw_ab.is_file())
        self.assertTrue(proc_ab_wav.is_file())

        # Breath at original t=1.02..1.26s maps to 0.52..0.76s in the 0.5s-offset excerpt
        m_raw, sr_raw, _, _ = _read_wav_mono_and_meta(raw_ab)
        m_proc, sr_proc, _, _ = _read_wav_mono_and_meta(proc_ab_wav)
        self.assertGreater(_window_rms_db(m_raw, sr_raw, 0.52, 0.76), -38.0)
        self.assertLess(_window_rms_db(m_proc, sr_proc, 0.52, 0.76), -52.0)

        ab_off_dir = self.dir / "ab_nodebreath"
        proc_ab_off = subprocess.run(
            [sys.executable, str(AUDIO_MIX), str(self.src), "--ab", "0.5,3",
             "--ab-out", str(ab_off_dir), "--no-debreath", "--json"],
            check=True, capture_output=True, text=True,
        )
        self.assertFalse(json.loads(proc_ab_off.stdout)["debreath"])
        m_proc_off, sr_off, _, _ = _read_wav_mono_and_meta(ab_off_dir / f"{self.src.stem}-处理-3s.wav")
        self.assertGreater(_window_rms_db(m_proc_off, sr_off, 0.52, 0.76), -38.0)

    def test_voice_polish_default_does_not_auto_mix_nearby_sfx_plan(self) -> None:
        # Even if an sfx.json sits beside the input voice, default audio_mix stays pure voice-only
        (self.dir / "sfx.json").write_text(
            json.dumps([{"t": 1.1, "kind": "chapter", "sound": "chapter-soft-whoosh"}]),
            encoding="utf-8",
        )
        out = self.dir / "pure_voice.wav"
        proc = subprocess.run(
            [sys.executable, str(AUDIO_MIX), str(self.src), "-o", str(out), "--json"],
            check=True, capture_output=True, text=True,
        )
        info = json.loads(proc.stdout)
        self.assertEqual(info["mode"], "voice-only")
        self.assertEqual(info["sfx_count"], 0)
        mono, sr, _, _ = _read_wav_mono_and_meta(out)
        self.assertLess(_window_rms_db(mono, sr, 1.02, 1.26), -52.0)

    def test_quiet_raw_recording_adaptive_debreath_and_invalid_ab_rejection(self) -> None:
        quiet_src = self.dir / "quiet_raw.wav"
        _write_speech_with_breaths_wav(quiet_src, level_shift_db=-10.0)

        diag = subprocess.run(
            [sys.executable, str(AUDIO_DIAG), str(quiet_src), "--json"],
            check=True, capture_output=True, text=True,
        )
        rep = json.loads(diag.stdout)
        self.assertGreaterEqual(rep["breath_valleys"], 2)

        out_on = self.dir / "quiet_on.wav"
        out_off = self.dir / "quiet_off.wav"
        subprocess.run([sys.executable, str(AUDIO_MIX), str(quiet_src), "-o", str(out_on)], check=True, capture_output=True)
        subprocess.run([sys.executable, str(AUDIO_MIX), str(quiet_src), "-o", str(out_off), "--no-debreath"], check=True, capture_output=True)

        m_on, sr, _, _ = _read_wav_mono_and_meta(out_on)
        m_off, _, _, _ = _read_wav_mono_and_meta(out_off)
        self.assertLessEqual(abs(_window_rms_db(m_on, sr, 0.05, 0.75) - _window_rms_db(m_off, sr, 0.05, 0.75)), 0.1)
        self.assertLess(_window_rms_db(m_on, sr, 1.02, 1.26), -52.0)

        bad_ab = subprocess.run(
            [sys.executable, str(AUDIO_MIX), str(self.src), "--ab", "bad"],
            capture_output=True, text=True,
        )
        self.assertNotEqual(bad_ab.returncode, 0)


if __name__ == "__main__":
    unittest.main()
