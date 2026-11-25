#!/usr/bin/env python3
"""Black-box CLI & asset tests for `helpers/sound_design.py` and `assets/sfx/`."""
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
HELPER = ROOT / "helpers" / "sound_design.py"
AUDIO_MIX = ROOT / "helpers" / "audio_mix.py"
SFX_DIR = ROOT / "assets" / "sfx"
SFX_MANIFEST = SFX_DIR / "manifest.json"
FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None

NEW_MOTION_SFX = (
    "motion-riser-warm.wav",
    "motion-whoosh-cinematic.wav",
    "motion-impact-sub.wav",
    "card-snap-crisp.wav",
)


class SfxCatalogAndAssetsTests(unittest.TestCase):
    def test_builtin_sfx_catalog_includes_new_cc0_48k_stereo_wavs_without_breaking_audio_mix(self):
        # 1. All 4 new procedural CC0 WAVs exist as 48kHz stereo 16-bit PCM with non-silent energy
        for fname in NEW_MOTION_SFX:
            wav_path = SFX_DIR / fname
            self.assertTrue(wav_path.is_file(), f"Missing built-in SFX: {wav_path}")
            with wave.open(str(wav_path), "rb") as wf:
                self.assertEqual(wf.getnchannels(), 2, f"{fname} must be stereo")
                self.assertEqual(wf.getsampwidth(), 2, f"{fname} must be 16-bit PCM")
                self.assertEqual(wf.getframerate(), 48000, f"{fname} must be 48kHz")
                n_frames = wf.getnframes()
                self.assertGreater(n_frames, 4800, f"{fname} too short")
                raw = wf.readframes(n_frames)
            samples = struct.unpack(f"<{len(raw) // 2}h", raw)
            peak = max(abs(x) for x in samples) / 32768.0
            self.assertGreater(peak, 0.05, f"{fname} peak too low ({peak})")
            self.assertLessEqual(peak, 0.99, f"{fname} clips ({peak})")

        # 2. sound_design.py --list-sfx --json returns all 12 catalog entries with CC0 license and no external paths
        proc = subprocess.run(
            [sys.executable, str(HELPER), "--list-sfx", "--json"],
            capture_output=True, text=True, check=True,
        )
        payload = json.loads(proc.stdout)
        items = payload["items"]
        self.assertGreaterEqual(len(items), 12)
        ids = {item["id"] for item in items}
        for fname in NEW_MOTION_SFX:
            stem = Path(fname).stem
            self.assertIn(stem, ids)
        for item in items:
            self.assertIn("CC0", item.get("license", ""))
            self.assertTrue(Path(item["path"]).is_file(), item["path"])
            self.assertTrue(Path(item["path"]).resolve().is_relative_to(SFX_DIR.resolve()))

        # 3. audio_mix.py --list-sfx --json still passes its restrained 8-item contract
        mix_proc = subprocess.run(
            [sys.executable, str(AUDIO_MIX), "--list-sfx", "--json"],
            capture_output=True, text=True, check=True,
        )
        mix_items = json.loads(mix_proc.stdout)["items"]
        self.assertTrue(6 <= len(mix_items) <= 10)
        for item in mix_items:
            self.assertIn(item["kind"], ("chapter", "reveal", "turn"))


def _make_wav_from_expr(path: Path, dur: float, fc: str, norm_lufs: float | None = None) -> None:
    af = f",loudnorm=I={norm_lufs}:TP=-1.5:LRA=9" if norm_lufs is not None else ""
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"anullsrc=r=48000:cl=stereo",
        "-t", f"{dur:.3f}", "-filter_complex", f"{fc}[raw];[raw]aformat=sample_rates=48000:channel_layouts=stereo{af}[out]",
        "-map", "[out]", "-c:a", "pcm_s16le", str(path),
    ], check=True)


def _make_mp4_with_audio(path: Path, dur: float, audio_fc: str | None) -> None:
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c=black:s=64x64:r=30:d={dur:.3f}"]
    if audio_fc is None:
        cmd += ["-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)]
    else:
        cmd += [
            "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
            "-t", f"{dur:.3f}", "-filter_complex", audio_fc,
            "-map", "0:v", "-map", "[out]", "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-ar", "48000", "-ac", "2", str(path),
        ]
    subprocess.run(cmd, check=True)


def _window_rms_db(wav_path: Path, start_s: float, dur_s: float, band: tuple[int, int] | None = None) -> float:
    with tempfile.TemporaryDirectory() as td:
        seg = Path(td) / "win.wav"
        cmd = ["ffmpeg", "-y", "-v", "error", "-ss", f"{start_s:.3f}", "-t", f"{dur_s:.3f}", "-i", str(wav_path)]
        if band is not None:
            cmd += ["-af", f"highpass=f={band[0]}:poles=2,lowpass=f={band[1]}:poles=2"]
        cmd += ["-ac", "1", "-ar", "48000", "-c:a", "pcm_s16le", str(seg)]
        subprocess.run(cmd, check=True)
        with wave.open(str(seg), "rb") as wf:
            raw = wf.readframes(wf.getnframes())
        if not raw:
            return -120.0
        vals = struct.unpack(f"<{len(raw) // 2}h", raw)
        rms = math.sqrt(sum((v / 32768.0) ** 2 for v in vals) / len(vals))
        return 20.0 * math.log10(max(1e-9, rms))


@unittest.skipUnless(FFMPEG, "needs ffmpeg")
class SoundDesignCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.proj = Path(self.tmp.name) / "demo_proj"
        self.clips_dir = self.proj / "material"
        self.edit_dir = self.proj / "edit"
        self.clips_dir.mkdir(parents=True)
        self.edit_dir.mkdir(parents=True)

        # Master voice at -14.0 LUFS with a clear pause at [8.0..12.0s]
        self.voice = self.edit_dir / "voice_polish.wav"
        voice_fc = (
            "sine=f=220:d=24[v1];sine=f=440:d=24[v2];"
            "[v1][v2]amix=inputs=2:normalize=0,"
            "volume='if(between(t,8.0,12.0),0,0.45)':eval=frame"
        )
        _make_wav_from_expr(self.voice, 24.0, voice_fc, norm_lufs=-14.0)

        # Clip 1: clear syllabic dialogue (500-2400 Hz bursts, weak bass) -> MUTE
        _make_mp4_with_audio(
            self.clips_dir / "dialogue.mp4", 6.5,
            "sine=f=750:d=6.5[s1];sine=f=1450:d=6.5[s2];sine=f=2200:d=6.5[s3];"
            "[s1][s2][s3]amix=inputs=3:normalize=0,"
            "volume='if(gt(sin(2*PI*3.5*t),-0.1),0.35,0.0)':eval=frame[out]",
        )
        # Clip 2: clean music with 1400 Hz + 4200 Hz harmonics -> TIER A (vocal-pocket EQ + ducking)
        _make_mp4_with_audio(
            self.clips_dir / "clean_music.mp4", 8.5,
            "sine=f=110:d=8.5[m1];sine=f=220:d=8.5[m2];sine=f=330:d=8.5[m3];"
            "sine=f=1400:d=8.5[m4];sine=f=4200:d=8.5[m5];"
            "[m1]volume=0.25[a1];[m2]volume=0.25[a2];[m3]volume=0.18[a3];"
            "[m4]volume=0.18[a4];[m5]volume=0.12[a5];"
            "[a1][a2][a3][a4][a5]amix=inputs=5:normalize=0[out]",
        )
        # Clip 3: bass-rich pad + soft modulated vocal -> TIER B (<=450 Hz pad only)
        _make_mp4_with_audio(
            self.clips_dir / "bass_soft_vo.mp4", 4.5,
            "sine=f=85:d=4.5[b1];sine=f=170:d=4.5[b2];"
            "sine=f=900:d=4.5[v1];sine=f=1800:d=4.5[v2];"
            "[v1][v2]amix=inputs=2:normalize=0,"
            "volume='0.12*(0.35+0.65*max(0,sin(2*PI*3.2*t)))':eval=frame[vo];"
            "[b1]volume=0.30[ba];[b2]volume=0.22[bb];"
            "[ba][bb][vo]amix=inputs=3:normalize=0[out]",
        )
        # Clip 4: video-only silent clip (no audio stream) -> MUTE cleanly
        _make_mp4_with_audio(self.clips_dir / "silent_clip.mp4", 2.0, None)

        self.sb = self.edit_dir / "storyboard.json"
        self.sb.write_text(json.dumps({
            "version": "storyboard/3",
            "totalSec": 24.0,
            "shots": [
                {"id": "V01_talk", "kind": "video", "engine": "ffmpeg-cut", "startSec": 0.0, "endSec": 6.0, "clip": "material/dialogue.mp4", "clipIn": 0.0, "clipOut": 6.0, "soundBed": "auto"},
                {"id": "V02_music", "kind": "footage", "engine": "ffmpeg-cut", "startSec": 6.0, "endSec": 14.0, "clip": "material/clean_music.mp4", "clipIn": 0.0, "clipOut": 8.0, "soundBed": "auto"},
                {"id": "V03_bass", "kind": "footage", "engine": "ffmpeg-cut", "startSec": 14.0, "endSec": 18.0, "clip": "material/bass_soft_vo.mp4", "clipIn": 0.0, "clipOut": 4.0, "soundBed": "auto"},
                {"id": "V04_silent", "kind": "video", "engine": "ffmpeg-cut", "startSec": 18.0, "endSec": 19.0, "clip": "material/silent_clip.mp4", "clipIn": 0.0, "clipOut": 1.0, "soundBed": "auto"},
                {"id": "M01", "kind": "model", "engine": "hyperframes", "startSec": 19.0, "endSec": 22.0, "soundCues": ["riser", "sub-drop", "reveal-chime"]},
                {"id": "X01", "kind": "card-deck", "engine": "hyperframes", "startSec": 22.0, "endSec": 24.0, "soundCues": ["whoosh", "card-snap", "card-snap"]},
            ],
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_build_screens_broll_tiers_ducks_voice_adds_motion_sfx_and_passes_gate(self):
        out = self.edit_dir / "soundscape.wav"
        proc = subprocess.run([
            sys.executable, str(HELPER), "build",
            "--storyboard", str(self.sb),
            "--voice", str(self.voice),
            "--out", str(out),
            "--json",
        ], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        info = json.loads(proc.stdout)
        self.assertTrue(info["ok"])
        self.assertEqual(info["sample_rate"], 48000)
        self.assertEqual(info["channels"], 2)
        self.assertAlmostEqual(info["duration_sec"], 24.0, delta=0.02)

        with wave.open(str(out), "rb") as wf:
            self.assertEqual(wf.getnchannels(), 2)
            self.assertEqual(wf.getframerate(), 48000)
            self.assertAlmostEqual(wf.getnframes() / 48000.0, 24.0, delta=0.01)

        # Verify 3-tier classification results
        by_id = {s["id"]: s["tier"] for s in info["bed_summary"]["shots"]}
        self.assertEqual(by_id["V01_talk"], "mute")
        self.assertEqual(by_id["V02_music"], "tier_a")
        self.assertEqual(by_id["V03_bass"], "tier_b")
        self.assertEqual(by_id["V04_silent"], "mute")

        # 1) Dialogue clip window [0.5..5.0s] must be muted
        self.assertLess(_window_rms_db(out, 0.5, 4.5), -70.0)

        # 2) Clean music Tier A [6.0..14.0s]: vocal-pocket notched at 1400 Hz & >2400 Hz rolled off,
        #    and ducked when voice is active [6.5..7.7s] vs pause [8.6..11.4s]
        ducked_rms = _window_rms_db(out, 6.5, 1.2)
        paused_rms = _window_rms_db(out, 8.6, 2.8)
        self.assertGreater(paused_rms - ducked_rms, 3.0, f"expected ~5dB sidechain ducking, got paused={paused_rms:.2f} ducked={ducked_rms:.2f}")
        low_band = _window_rms_db(out, 8.6, 2.8, band=(150, 400))
        pocket_band = _window_rms_db(out, 8.6, 2.8, band=(1200, 1600))
        hf_band = _window_rms_db(out, 8.6, 2.8, band=(3000, 6000))
        self.assertGreater(low_band - pocket_band, 8.0, "expected 1400 Hz vocal pocket cut")
        self.assertGreater(low_band - hf_band, 12.0, "expected >2400 Hz rolloff")

        # 3) Bass + soft VO Tier B [14.5..17.0s]: <=450 Hz preserved, >650 Hz vocal band attenuated
        bass_b = _window_rms_db(out, 14.5, 2.5, band=(70, 420))
        vo_b = _window_rms_db(out, 14.5, 2.5, band=(700, 2200))
        self.assertGreater(bass_b, -45.0)
        self.assertGreater(bass_b - vo_b, 15.0, f"expected Tier B lowpass <=450 Hz, got bass={bass_b:.2f} vo={vo_b:.2f}")

        # 4) Motion SFX layer active during M01/X01 [18.2..23.8s]
        sfx_rms = _window_rms_db(out, 18.2, 5.5)
        self.assertGreater(sfx_rms, -45.0)

        # 5) Loudness gate telemetry within spec bounds
        self.assertTrue(-37.0 <= info["stem"]["lufs"] <= -30.0, info["stem"])
        self.assertLessEqual(info["stem"]["true_peak_dbtp"], -13.5)
        self.assertTrue(-14.2 <= info["combined"]["lufs"] <= -13.4, info["combined"])
        self.assertLessEqual(info["combined"]["true_peak_dbtp"], -1.0)

    def test_broll_bed_off_and_preview_variants_emit_sfx_only_track(self):
        out_off = self.edit_dir / "off.wav"
        proc_off = subprocess.run([
            sys.executable, str(HELPER), "build",
            "--storyboard", str(self.sb),
            "--voice", str(self.voice),
            "--out", str(out_off),
            "--broll-bed", "off",
            "--json",
        ], capture_output=True, text=True, check=True)
        info_off = json.loads(proc_off.stdout)
        self.assertTrue(info_off["ok"])
        # Clean music window [6.5..13.5s] has NO B-roll bed when --broll-bed off
        self.assertLess(_window_rms_db(out_off, 6.5, 7.0), -70.0)
        # Motion SFX still present in [18.5..23.8s]
        self.assertGreater(_window_rms_db(out_off, 18.5, 5.0), -48.0)

        out_full = self.edit_dir / "soundscape.wav"
        proc_var = subprocess.run([
            sys.executable, str(HELPER), "build",
            "--storyboard", str(self.sb),
            "--voice", str(self.voice),
            "--out", str(out_full),
            "--preview-variants",
            "--json",
        ], capture_output=True, text=True, check=True)
        info_var = json.loads(proc_var.stdout)
        sfx_only_path = Path(info_var["variants"]["sfx_only"]["path"])
        self.assertEqual(sfx_only_path.name, "soundscape_sfx_only.wav")
        self.assertTrue(sfx_only_path.is_file())
        self.assertGreater(_window_rms_db(out_full, 8.6, 2.8), -45.0)
        self.assertLess(_window_rms_db(sfx_only_path, 8.6, 2.8), -70.0)

    def test_verify_gate_accepts_valid_and_rejects_overloud_clipping_and_bad_mix(self):
        out = self.edit_dir / "soundscape.wav"
        subprocess.run([
            sys.executable, str(HELPER), "build",
            "--storyboard", str(self.sb),
            "--voice", str(self.voice),
            "--out", str(out),
        ], capture_output=True, text=True, check=True)

        # Valid -> exit 0
        ok_proc = subprocess.run([
            sys.executable, str(HELPER), "verify",
            "--stem", str(out), "--voice", str(self.voice), "--json",
        ], capture_output=True, text=True)
        self.assertEqual(ok_proc.returncode, 0, ok_proc.stderr + ok_proc.stdout)

        # Over-loud stem (-22.0 LUFS) -> exit 1
        loud_stem = self.edit_dir / "too_loud.wav"
        _make_wav_from_expr(loud_stem, 8.0, "sine=f=330:d=8", norm_lufs=-22.0)
        p_loud = subprocess.run([
            sys.executable, str(HELPER), "verify",
            "--stem", str(loud_stem), "--voice", str(self.voice), "--json",
        ], capture_output=True, text=True)
        self.assertEqual(p_loud.returncode, 1)
        self.assertFalse(json.loads(p_loud.stdout)["ok"])

        # Clipping true-peak stem (peak ~ -4.4 dBTP from lavfi sine 0.1 amplitude * 6.0) -> exit 1
        clip_stem = self.edit_dir / "clip_tp.wav"
        _make_wav_from_expr(
            clip_stem, 8.0,
            "sine=f=440:d=8,volume='if(between(t,2.0,2.2),6.0,0.15)':eval=frame",
        )
        p_clip = subprocess.run([
            sys.executable, str(HELPER), "verify",
            "--stem", str(clip_stem), "--voice", str(self.voice), "--json",
        ], capture_output=True, text=True)
        self.assertEqual(p_clip.returncode, 1)
        self.assertTrue(any("峰值" in msg for msg in json.loads(p_clip.stdout)["problems"]))

        # Too-quiet stem (-48.0 LUFS) -> exit 1 by default, passes with --allow-quiet
        quiet_stem = self.edit_dir / "too_quiet.wav"
        _make_wav_from_expr(quiet_stem, 8.0, "sine=f=330:d=8,volume=0.004")
        p_quiet = subprocess.run([
            sys.executable, str(HELPER), "verify",
            "--stem", str(quiet_stem), "--voice", str(self.voice), "--json",
        ], capture_output=True, text=True)
        self.assertEqual(p_quiet.returncode, 1)
        p_quiet_ok = subprocess.run([
            sys.executable, str(HELPER), "verify",
            "--stem", str(quiet_stem), "--voice", str(self.voice), "--allow-quiet", "--json",
        ], capture_output=True, text=True)
        self.assertEqual(p_quiet_ok.returncode, 0, p_quiet_ok.stdout)

        # Bad combined mix (over-loud voice at -10.5 LUFS) -> build rejects exit 1 & does not write broken out
        hot_voice = self.edit_dir / "hot_voice.wav"
        _make_wav_from_expr(hot_voice, 24.0, "sine=f=220:d=24", norm_lufs=-10.5)
        rejected_out = self.edit_dir / "rejected_out.wav"
        p_bad_mix = subprocess.run([
            sys.executable, str(HELPER), "build",
            "--storyboard", str(self.sb),
            "--voice", str(hot_voice),
            "--out", str(rejected_out),
            "--json",
        ], capture_output=True, text=True)
        self.assertEqual(p_bad_mix.returncode, 1)
        self.assertFalse(rejected_out.exists())

    def test_explicit_sfx_plan_and_no_external_project_references(self):
        plan = self.edit_dir / "sfx-plan.json"
        plan.write_text(json.dumps({
            "events": [
                {"t": 18.5, "sound": "motion-riser-warm", "target_peak_db": -22.0},
                {"t": 20.3, "sound": "motion-impact-sub", "target_peak_db": -19.5},
                {"t": 22.0, "sound": "card-snap-crisp", "target_peak_db": -23.0},
            ]
        }), encoding="utf-8")
        out = self.edit_dir / "planned.wav"
        proc = subprocess.run([
            sys.executable, str(HELPER), "build",
            "--storyboard", str(self.sb),
            "--voice", str(self.voice),
            "--sfx-plan", str(plan),
            "--out", str(out),
            "--json",
        ], capture_output=True, text=True, check=True)
        info = json.loads(proc.stdout)
        self.assertEqual(info["sfx_cue_count"], 3)
        self.assertTrue(out.is_file())

        # Ensure zero external sibling project directories or copyrighted names leaked into code/manifest
        for artifact in (HELPER, SFX_MANIFEST):
            txt = artifact.read_text(encoding="utf-8")
            self.assertNotIn("Vans", txt)
            self.assertNotIn("05-VideoProject", txt)
            self.assertNotIn("亚朵", txt)

    def test_noisy_clip_and_explicit_mute_are_silenced_and_omitted_cues_auto_expand(self):
        # White noise / broadband hiss clip -> must auto-mute; clean music with soundBed=mute -> must mute
        _make_mp4_with_audio(
            self.clips_dir / "noisy_hiss.mp4", 3.5,
            "anoisesrc=d=3.5:c=white:a=0.15[out]",
        )
        sb_edge = self.edit_dir / "sb_edge.json"
        sb_edge.write_text(json.dumps({
            "version": "storyboard/3",
            "totalSec": 14.0,
            "shots": [
                {"id": "V_noisy", "kind": "footage", "startSec": 0.0, "endSec": 3.5, "clip": "material/noisy_hiss.mp4", "clipIn": 0.0, "clipOut": 3.5, "soundBed": "auto"},
                {"id": "V_muted_explicit", "kind": "footage", "startSec": 3.5, "endSec": 6.5, "clip": "material/clean_music.mp4", "clipIn": 0.0, "clipOut": 3.0, "soundBed": "mute"},
                {"id": "V_bed", "kind": "footage", "startSec": 6.5, "endSec": 10.5, "clip": "material/clean_music.mp4", "clipIn": 3.0, "clipOut": 7.0},
                {"id": "M_auto", "kind": "model", "startSec": 10.5, "endSec": 14.0},
            ],
        }), encoding="utf-8")
        voice_short = self.edit_dir / "voice_14.wav"
        _make_wav_from_expr(voice_short, 14.0, "sine=f=220:d=14", norm_lufs=-14.0)

        out = self.edit_dir / "edge.wav"
        proc = subprocess.run([
            sys.executable, str(HELPER), "build",
            "--storyboard", str(sb_edge),
            "--voice", str(voice_short),
            "--out", str(out),
            "--json",
        ], capture_output=True, text=True, check=True)
        info = json.loads(proc.stdout)
        by_id = {s["id"]: s["tier"] for s in info["bed_summary"]["shots"]}
        self.assertEqual(by_id["V_noisy"], "mute")
        self.assertEqual(by_id["V_muted_explicit"], "mute")
        self.assertEqual(by_id["V_bed"], "tier_a")
        self.assertGreaterEqual(info["sfx_cue_count"], 3)
        self.assertLess(_window_rms_db(out, 0.3, 2.5), -70.0)
        self.assertLess(_window_rms_db(out, 4.0, 2.0), -70.0)
        self.assertGreater(_window_rms_db(out, 10.2, 3.5), -48.0)

    def test_json_flag_works_both_before_and_after_subcommand(self):
        out = self.edit_dir / "json_pos.wav"
        proc_before = subprocess.run([
            sys.executable, str(HELPER), "--json", "build",
            "--storyboard", str(self.sb),
            "--voice", str(self.voice),
            "--out", str(out),
        ], capture_output=True, text=True)
        self.assertEqual(proc_before.returncode, 0, proc_before.stderr + proc_before.stdout)
        info_before = json.loads(proc_before.stdout)
        self.assertTrue(info_before["ok"])

        proc_verify_before = subprocess.run([
            sys.executable, str(HELPER), "--json", "verify",
            "--stem", str(out),
            "--voice", str(self.voice),
        ], capture_output=True, text=True)
        self.assertEqual(proc_verify_before.returncode, 0, proc_verify_before.stderr + proc_verify_before.stdout)
        self.assertTrue(json.loads(proc_verify_before.stdout)["ok"])


if __name__ == "__main__":
    unittest.main()
