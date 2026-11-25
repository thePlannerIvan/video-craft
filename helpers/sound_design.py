#!/usr/bin/env python3
"""Visual Soundscape deep module: B-roll screening + dynamic motion SFX + loudness gate.

Consumes `storyboard.json` and the master Voice Polish WAV (`-14.0 LUFS` sidechain key)
to produce a lossless 48 kHz stereo Visual Soundscape stem (`soundscape.wav` /
`画面音效轨.wav`) and optional SFX-only review variant (`*_sfx_only.wav`).

Two-layer architecture:
  Layer A (B-roll Ambient Bed, controlled by `--broll-bed on|off`):
    Automatically screens `footage` / `video` segments by spectrum & syllabic modulation:
      - Tier A (clean music / ambience): vocal-pocket EQ
        `highpass=f=80,equalizer=f=1400:t=q:w=0.85:g=-9,lowpass=f=2400`
      - Tier B (bass-rich music with suspected soft VO): warm sub pad
        `highpass=f=65,lowpass=f=450`
      - Mute (clear dialogue, broadband noise/hiss, or silent): muted cleanly
    Applies smooth cosine fades and voice-keyed sidechain ducking (`-5 dB`, 45ms/420ms).

  Layer B (Dynamic Motion SFX):
    Drives synchronized "anticipation -> landing -> reveal" cues (`swell` / `riser` ->
    `whoosh` / `sub-drop` / `impact` -> `card-snap` / `chime` / `tick`) from
    `storyboard.json` (`model` / `motion` / `card-deck` / `xhs`) and/or `--sfx-plan`,
    using built-in CC0 procedural assets in `assets/sfx/` with `highshelf=f=4500:g=-4`.

Deterministic Acoustic Gate (`verify` and end of `build`):
  - Standalone stem: `-37.0 .. -30.0 LUFS` (unless `--allow-quiet`), `TP <= -13.5 dBTP`
  - Simulated combined mix (`voice + soundscape`): `-14.2 .. -13.4 LUFS`, `TP <= -1.0 dBTP`
  - Exits with code 1 on any violation.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path
from typing import Any

import numpy as np

SR = 48000
HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parent
SFX_DIR = SKILL_ROOT / "assets" / "sfx"
SFX_MANIFEST = SFX_DIR / "manifest.json"

FOOTAGE_KINDS = ("footage", "video")
MOTION_KINDS = ("motion", "model", "card-deck", "xhs")

# Acoustic gate thresholds
STEM_LUFS_MIN = -37.0
STEM_LUFS_MAX = -30.0
STEM_TP_MAX = -13.5
COMBINED_LUFS_MIN = -14.2
COMBINED_LUFS_MAX = -13.4
COMBINED_TP_MAX = -1.0

# Sidechain ducking parameters
DUCK_THRESH_DB = -36.0
DUCK_DB = -5.0
DUCK_ATTACK_S = 0.045
DUCK_RELEASE_S = 0.420

# Semantic cue -> built-in CC0 SFX preset mapping
CUE_PRESETS: dict[str, dict[str, Any]] = {
    "swell": {"id": "chapter-warm-swell", "role": "lead", "target_peak_db": -21.0, "fade_in": 0.02, "fade_out": 0.08},
    "warm-swell": {"id": "chapter-warm-swell", "role": "lead", "target_peak_db": -21.0, "fade_in": 0.02, "fade_out": 0.08},
    "riser": {"id": "motion-riser-warm", "role": "lead", "lowpass_hz": 1600, "target_peak_db": -22.5, "fade_in": 0.25, "fade_out": 0.12},
    "motion-riser-warm": {"id": "motion-riser-warm", "role": "lead", "lowpass_hz": 1600, "target_peak_db": -22.5, "fade_in": 0.25, "fade_out": 0.12},
    "whoosh": {"id": "motion-whoosh-cinematic", "role": "land", "lowpass_hz": 1900, "target_peak_db": -19.5, "fade_in": 0.05, "fade_out": 0.18},
    "soft-whoosh": {"id": "chapter-soft-whoosh", "role": "land", "target_peak_db": -21.5, "fade_in": 0.015, "fade_out": 0.08},
    "whoosh-cinematic": {"id": "motion-whoosh-cinematic", "role": "land", "lowpass_hz": 1900, "target_peak_db": -19.5, "fade_in": 0.05, "fade_out": 0.18},
    "sub-drop": {"id": "turn-sub-drop", "role": "land", "target_peak_db": -19.5, "fade_in": 0.015, "fade_out": 0.08},
    "impact": {"id": "motion-impact-sub", "role": "land", "lowpass_hz": 450, "target_peak_db": -19.0, "fade_in": 0.015, "fade_out": 0.28},
    "impact-sub": {"id": "motion-impact-sub", "role": "land", "lowpass_hz": 450, "target_peak_db": -19.0, "fade_in": 0.015, "fade_out": 0.28},
    "drop-thud": {"id": "motion-impact-sub", "role": "land", "lowpass_hz": 800, "target_peak_db": -19.5, "fade_in": 0.015, "fade_out": 0.25},
    "page-turn": {"id": "chapter-page-turn", "role": "land", "target_peak_db": -22.0, "fade_in": 0.01, "fade_out": 0.06},
    "card-snap": {"id": "card-snap-crisp", "role": "detail", "target_peak_db": -23.5, "fade_in": 0.008, "fade_out": 0.05},
    "crisp-tick": {"id": "card-snap-crisp", "role": "detail", "target_peak_db": -23.5, "fade_in": 0.008, "fade_out": 0.05},
    "crisp-click": {"id": "turn-crisp-click", "role": "detail", "target_peak_db": -24.5, "fade_in": 0.008, "fade_out": 0.04},
    "glass-tick": {"id": "reveal-glass-tick", "role": "detail", "target_peak_db": -21.5, "fade_in": 0.01, "fade_out": 0.06},
    "soft-pop": {"id": "reveal-soft-pop", "role": "detail", "target_peak_db": -24.0, "fade_in": 0.01, "fade_out": 0.05},
    "reveal-chime": {"id": "reveal-warm-chime", "role": "detail", "target_peak_db": -21.5, "fade_in": 0.015, "fade_out": 0.10},
    "warm-chime": {"id": "reveal-warm-chime", "role": "detail", "target_peak_db": -21.5, "fade_in": 0.015, "fade_out": 0.10},
    "chime": {"id": "reveal-warm-chime", "role": "detail", "target_peak_db": -21.5, "fade_in": 0.015, "fade_out": 0.10},
}


def db_to_lin(db: float) -> float:
    return 10.0 ** (db / 20.0)


def lin_to_db(lin: float) -> float:
    return 20.0 * math.log10(max(lin, 1e-12))


def apply_cosine_fades(buf: np.ndarray, fade_in_s: float, fade_out_s: float) -> np.ndarray:
    """Apply smooth raised-cosine fade-in and fade-out in-place on `(N, 2)` float32 audio."""
    n = len(buf)
    if n == 0:
        return buf
    fi = min(int(round(fade_in_s * SR)), n // 2)
    fo = min(int(round(fade_out_s * SR)), n - fi)
    if fi > 0:
        w = 0.5 * (1.0 - np.cos(np.pi * np.linspace(0.0, 1.0, fi, dtype=np.float32)))
        buf[:fi] *= w[:, None]
    if fo > 0:
        w = 0.5 * (1.0 + np.cos(np.pi * np.linspace(0.0, 1.0, fo, dtype=np.float32)))
        buf[n - fo :] *= w[:, None]
    return buf


def _onepole_lp_sweep(x: np.ndarray, cutoffs_hz: np.ndarray) -> np.ndarray:
    """Time-varying 1-pole low-pass filter for warm procedural risers & whooshes."""
    y = np.empty_like(x, dtype=np.float64)
    state = 0.0
    two_pi_dt = 2.0 * math.pi / SR
    for i in range(len(x)):
        a = min(0.99, two_pi_dt * float(cutoffs_hz[i]))
        state += a * (float(x[i]) - state)
        y[i] = state
    return y


def _fft_bandpass(x: np.ndarray, lo_hz: float, hi_hz: float) -> np.ndarray:
    """Zero-phase FFT bandpass filter with cosine rolloff edges for crisp procedural SFX."""
    n = len(x)
    freqs = np.fft.rfftfreq(n, 1.0 / SR)
    spec = np.fft.rfft(x)
    mask = np.ones_like(freqs, dtype=np.float64)
    if lo_hz > 0:
        lo_edge = max(20.0, lo_hz * 0.65)
        low_region = (freqs >= lo_edge) & (freqs < lo_hz)
        mask[freqs < lo_edge] = 0.0
        mask[low_region] = 0.5 * (1.0 - np.cos(np.pi * (freqs[low_region] - lo_edge) / (lo_hz - lo_edge)))
    if hi_hz < SR / 2:
        hi_edge = min(SR / 2.0, hi_hz * 1.45)
        high_region = (freqs > hi_hz) & (freqs <= hi_edge)
        mask[freqs > hi_edge] = 0.0
        mask[high_region] = 0.5 * (1.0 + np.cos(np.pi * (freqs[high_region] - hi_hz) / (hi_edge - hi_hz)))
    return np.fft.irfft(spec * mask, n=n)


def _write_pcm16_stereo(buf: np.ndarray, dest: Path) -> None:
    pcm = np.clip(np.round(buf * 32767.0), -32768, 32767).astype("<i2")
    with wave.open(str(dest), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes(pcm.tobytes())


def write_wav_atomic(buf: np.ndarray, dest: Path) -> Path:
    """Write 48 kHz stereo 16-bit PCM WAV to `/tmp` first, then atomically move to `dest`."""
    dest = dest.expanduser().resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix="vc_soundscape_", suffix=".wav", dir="/tmp")
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        _write_pcm16_stereo(buf, tmp_path)
        shutil.move(str(tmp_path), str(dest))
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
    return dest


def synthesize_builtin_sfx(target_dir: Path | None = None) -> list[Path]:
    """Procedurally synthesize the 4 CC0 48kHz stereo motion/card WAVs into `target_dir`."""
    out_dir = (target_dir or SFX_DIR).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(20261125)
    written: list[Path] = []

    def finalize(stereo: np.ndarray, peak_db: float, fi: float, fo: float, filename: str) -> None:
        buf = stereo.astype(np.float32)
        apply_cosine_fades(buf, fi, fo)
        pk = float(np.max(np.abs(buf)))
        if pk > 1e-8:
            buf *= db_to_lin(peak_db) / pk
        p = out_dir / filename
        write_wav_atomic(buf, p)
        written.append(p)

    # 1. motion-riser-warm.wav (1.80s): exponential LP-swept warm air + harmonic fifth glide
    dur_r = 1.80
    n_r = int(round(dur_r * SR))
    t_r = np.linspace(0.0, dur_r, n_r, endpoint=False)
    u_r = t_r / dur_r
    cutoffs_r = 180.0 * ((1650.0 / 180.0) ** (u_r ** 1.4))
    noise_l = _onepole_lp_sweep(rng.standard_normal(n_r), cutoffs_r)
    noise_r = _onepole_lp_sweep(rng.standard_normal(n_r), cutoffs_r)
    f_glide = 82.0 + 138.0 * (u_r ** 2.0)
    phase = 2.0 * math.pi * np.cumsum(f_glide) / SR
    pad = 0.45 * np.sin(phase) + 0.22 * np.sin(1.5 * phase)
    env_r = 0.08 + 0.92 * (u_r ** 2.2)
    riser = np.column_stack([(0.65 * noise_l + pad) * env_r, (0.65 * noise_r + pad) * env_r])
    finalize(riser, -4.5, 0.06, 0.14, "motion-riser-warm.wav")

    # 2. motion-whoosh-cinematic.wav (0.90s): smooth bell-swept air + warm low-mid body
    dur_w = 0.90
    n_w = int(round(dur_w * SR))
    t_w = np.linspace(0.0, dur_w, n_w, endpoint=False)
    u_w = t_w / dur_w
    bell = np.sin(math.pi * u_w) ** 1.6
    cutoffs_w = 240.0 + 1350.0 * bell
    wl = _onepole_lp_sweep(_fft_bandpass(rng.standard_normal(n_w), 120.0, 2600.0), cutoffs_w)
    wr = _onepole_lp_sweep(_fft_bandpass(rng.standard_normal(n_w), 120.0, 2600.0), cutoffs_w)
    body = 0.35 * np.sin(2.0 * math.pi * 105.0 * t_w) * (np.sin(math.pi * u_w) ** 2.0)
    whoosh = np.column_stack([wl * bell + body, wr * bell + body])
    finalize(whoosh, -4.0, 0.04, 0.22, "motion-whoosh-cinematic.wav")

    # 3. motion-impact-sub.wav (1.10s): pitch-dropping sub fundamental + soft low transient
    dur_i = 1.10
    n_i = int(round(dur_i * SR))
    t_i = np.linspace(0.0, dur_i, n_i, endpoint=False)
    f_sub = 42.0 + 74.0 * np.exp(-t_i / 0.105)
    ph_sub = 2.0 * math.pi * np.cumsum(f_sub) / SR
    sub = np.sin(ph_sub) * np.exp(-t_i / 0.36)
    thump = _fft_bandpass(rng.standard_normal(n_i), 50.0, 420.0) * np.exp(-t_i / 0.045) * 0.65
    sub_r = np.sin(ph_sub + 0.08) * np.exp(-t_i / 0.36)
    impact = np.column_stack([sub + thump, sub_r + 0.92 * thump])
    finalize(impact, -3.5, 0.012, 0.24, "motion-impact-sub.wav")

    # 4. card-snap-crisp.wav (0.14s): crisp band-limited tactile paper snap + wood body tap
    dur_c = 0.14
    n_c = int(round(dur_c * SR))
    t_c = np.linspace(0.0, dur_c, n_c, endpoint=False)
    snap_burst = _fft_bandpass(rng.standard_normal(n_c), 850.0, 3400.0) * np.exp(-t_c / 0.016)
    f_tap = 175.0 + 190.0 * np.exp(-t_c / 0.018)
    tap = 0.45 * np.sin(2.0 * math.pi * np.cumsum(f_tap) / SR) * np.exp(-t_c / 0.032)
    mono_c = 0.85 * snap_burst + tap
    shift = int(round(0.00035 * SR))
    right_c = np.concatenate([np.zeros(shift, dtype=np.float64), mono_c[:-shift]]) * 0.94
    card = np.column_stack([mono_c, right_c])
    finalize(card, -5.0, 0.004, 0.055, "card-snap-crisp.wav")

    return written


def load_sfx_catalog() -> list[dict]:
    """Load both voice-layer `items` and visual-soundscape `soundscape_items` from manifest.json."""
    if not SFX_MANIFEST.is_file():
        return []
    doc = json.loads(SFX_MANIFEST.read_text(encoding="utf-8"))
    raw_items = [*(doc.get("items") or []), *(doc.get("soundscape_items") or [])]
    out: list[dict] = []
    for item in raw_items:
        entry = dict(item)
        entry["path"] = str((SFX_DIR / item["file"]).resolve())
        out.append(entry)
    return out


def _run_ffmpeg(cmd: list[str], err_prefix: str = "ffmpeg failed") -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        lines = (proc.stderr or proc.stdout or "").strip().splitlines()
        detail = lines[-1][:240] if lines else f"exit {proc.returncode}"
        raise RuntimeError(f"{err_prefix}: {detail}")
    return proc


def has_audio_stream(path: Path) -> bool:
    proc = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "a:0",
            "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(path),
        ],
        capture_output=True, text=True,
    )
    return proc.returncode == 0 and bool(proc.stdout.strip())


def probe_duration(path: Path) -> float:
    proc = _run_ffmpeg(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "csv=p=0", str(path),
        ],
        "ffprobe duration failed",
    )
    return float(proc.stdout.strip())


def decode_ffmpeg(
    path: Path, af_filter: str | None = None, ss: float | None = None, dur: float | None = None
) -> np.ndarray:
    """Decode any audio/video stream to 48 kHz stereo float32 `(N, 2)` via FFmpeg."""
    cmd = ["ffmpeg", "-v", "error"]
    if ss is not None:
        cmd += ["-ss", f"{ss:.4f}"]
    if dur is not None:
        cmd += ["-t", f"{dur:.4f}"]
    cmd += ["-i", str(path), "-vn"]
    if af_filter:
        cmd += ["-af", af_filter]
    cmd += ["-ac", "2", "-ar", str(SR), "-f", "f32le", "-"]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg decode failed on {path}: {proc.stderr.decode('utf-8', 'replace')}")
    arr = np.frombuffer(proc.stdout, dtype=np.float32)
    n_frames = len(arr) // 2
    return arr[: n_frames * 2].reshape(n_frames, 2).copy()


def _parse_loudnorm_stats(stderr: str, path_label: str) -> tuple[float, float]:
    m = re.search(r'\{[^{}]*"input_i"[^{}]*\}', stderr, re.S)
    if not m:
        raise RuntimeError(f"Unable to measure EBU R128 loudness for {path_label}")
    blob = json.loads(m.group(0))
    lufs_val = float(blob["input_i"])
    tp_val = float(blob["input_tp"])
    return lufs_val, tp_val


def measure_loudness(path: Path) -> tuple[float, float]:
    """Return `(integrated_lufs, true_peak_dbtp)` for a single audio file."""
    proc = _run_ffmpeg(
        [
            "ffmpeg", "-hide_banner", "-i", str(path),
            "-af", "loudnorm=I=-14.0:TP=-1.5:LRA=9:print_format=json",
            "-f", "null", "-",
        ],
        f"loudness probe failed on {path}",
    )
    return _parse_loudnorm_stats(proc.stderr, str(path))


def measure_combined_loudness(voice_path: Path, stem_path: Path) -> tuple[float, float]:
    """Simulate `voice + soundscape` playback in-process via FFmpeg and measure LUFS / dBTP."""
    fc = (
        "[0:a]aformat=sample_rates=48000:channel_layouts=stereo[v];"
        "[1:a]aformat=sample_rates=48000:channel_layouts=stereo[s];"
        "[v][s]amix=inputs=2:duration=longest:dropout_transition=0:normalize=0,"
        "loudnorm=I=-14.0:TP=-1.5:LRA=9:print_format=json[out]"
    )
    proc = _run_ffmpeg(
        [
            "ffmpeg", "-hide_banner", "-i", str(voice_path), "-i", str(stem_path),
            "-filter_complex", fc, "-map", "[out]", "-f", "null", "-",
        ],
        "combined loudness simulation failed",
    )
    return _parse_loudnorm_stats(proc.stderr, f"{voice_path.name}+{stem_path.name}")


def classify_broll_segment(seg: np.ndarray) -> tuple[str, dict[str, float]]:
    """Classify decoded B-roll audio into `tier_a` (music), `tier_b` (bass+soft VO), or `mute`."""
    if len(seg) < int(0.1 * SR):
        return "mute", {"rms_db": -99.0}
    mono = np.mean(seg, axis=1).astype(np.float64)
    rms = float(np.sqrt(np.mean(mono ** 2)))
    rms_db = lin_to_db(rms)
    if rms_db < -55.0:
        return "mute", {"rms_db": round(rms_db, 2)}

    n = len(mono)
    spec = np.abs(np.fft.rfft(mono * np.hanning(n))) ** 2
    freqs = np.fft.rfftfreq(n, 1.0 / SR)

    def band_stats(lo: float, hi: float) -> tuple[float, float]:
        m = (freqs >= lo) & (freqs < hi)
        if not np.any(m):
            return -120.0, -120.0
        vals = spec[m]
        return 10.0 * math.log10(float(np.sum(vals)) + 1e-18), 10.0 * math.log10(float(np.mean(vals)) + 1e-18)

    e_bass, p_bass = band_stats(60.0, 220.0)
    e_warm, p_warm = band_stats(220.0, 450.0)
    e_vocal, _ = band_stats(450.0, 3000.0)
    _, p_hf = band_stats(3500.0, 10000.0)

    # 25ms vocal-band syllabic modulation spread (p90 - p20 dB)
    win = int(0.025 * SR)
    n_frames = n // win
    if n_frames >= 4:
        frames = mono[: n_frames * win].reshape(n_frames, win)
        f_spec = np.abs(np.fft.rfft(frames * np.hanning(win), axis=1)) ** 2
        f_freq = np.fft.rfftfreq(win, 1.0 / SR)
        mv = (f_freq >= 450.0) & (f_freq < 3000.0)
        v_frames = 10.0 * np.log10(np.mean(f_spec[:, mv], axis=1) + 1e-18)
        vocal_mod_db = float(np.percentile(v_frames, 90) - np.percentile(v_frames, 20))
    else:
        vocal_mod_db = 0.0

    hf_excess = p_hf - max(p_bass, p_warm)
    vocal_vs_bass = e_vocal - e_bass
    metrics = {
        "rms_db": round(rms_db, 2),
        "hf_excess_db": round(hf_excess, 2),
        "vocal_vs_bass_db": round(vocal_vs_bass, 2),
        "vocal_mod_db": round(vocal_mod_db, 2),
    }

    # Broadband hiss / high-frequency harsh noise -> mute
    if hf_excess > -3.0:
        return "mute", metrics

    # Clear speech / dialogue without strong bass music bed -> mute
    if vocal_vs_bass > 6.0 and (vocal_mod_db > 5.0 or (e_vocal - max(e_bass, e_warm)) > 4.0):
        return "mute", metrics

    # Bass-rich music bed with suspected soft/modulated vocal presence -> Tier B (<450 Hz pad)
    if vocal_mod_db > 5.0:
        return "tier_b", metrics

    return "tier_a", metrics


def _resolve_clip_path(raw: str, sb_dir: Path, project_root: Path) -> Path:
    p = Path(raw).expanduser()
    if p.is_absolute():
        return p
    for base in (sb_dir, project_root, project_root / "素材" / "clips", project_root / "material"):
        cand = (base / p).resolve()
        if cand.is_file():
            return cand
    return (project_root / p).resolve()


def _explicit_bed_tier(raw_bed: Any) -> str | None:
    if raw_bed is False:
        return "mute"
    if isinstance(raw_bed, str):
        val = raw_bed.strip().lower()
        if val in ("off", "mute"):
            return "mute"
        if val in ("tier-a", "tier_a", "clean", "music"):
            return "tier_a"
        if val in ("tier-b", "tier_b", "bass", "low-pad"):
            return "tier_b"
    return None


def _compute_sidechain_envelope(voice_mono: np.ndarray, total_samples: int) -> np.ndarray:
    """Compute smooth per-sample `-5 dB` ducking envelope (45ms attack / 420ms release)."""
    if len(voice_mono) < total_samples:
        key = np.pad(voice_mono, (0, total_samples - len(voice_mono)))
    else:
        key = voice_mono[:total_samples]

    hop = int(round(0.020 * SR))
    n_hops = max(1, total_samples // hop)
    thresh = db_to_lin(DUCK_THRESH_DB)
    duck_lin = db_to_lin(DUCK_DB)
    attack_coeff = math.exp(-0.020 / DUCK_ATTACK_S)
    release_coeff = math.exp(-0.020 / DUCK_RELEASE_S)

    env_hops = np.ones(n_hops + 1, dtype=np.float32)
    cur_gain = 1.0
    for i in range(n_hops):
        frame = key[i * hop : (i + 1) * hop]
        frms = float(np.sqrt(np.mean(frame ** 2))) if len(frame) else 0.0
        target = duck_lin if frms > thresh else 1.0
        coeff = attack_coeff if target < cur_gain else release_coeff
        cur_gain = coeff * cur_gain + (1.0 - coeff) * target
        env_hops[i] = cur_gain
    env_hops[n_hops] = cur_gain

    hop_x = np.arange(n_hops + 1, dtype=np.float32) * hop
    sample_x = np.arange(total_samples, dtype=np.float32)
    return np.interp(sample_x, hop_x, env_hops).astype(np.float32)


def build_ambient_bed(
    shots: list[dict],
    sb_dir: Path,
    project_root: Path,
    voice_mono: np.ndarray,
    total_samples: int,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Screen `footage` / `video` clips into Tier A / Tier B / Mute, apply EQ & sidechain ducking."""
    bed = np.zeros((total_samples, 2), dtype=np.float32)
    summary: dict[str, Any] = {"tier_a": 0, "tier_b": 0, "muted": 0, "shots": []}

    tier_cfg = {
        "tier_a": {
            "af": "highpass=f=80,equalizer=f=1400:t=q:w=0.85:g=-9,lowpass=f=2400",
            "target_rms_db": -32.0,
            "max_boost_db": 12.0,
        },
        "tier_b": {
            "af": "highpass=f=65,lowpass=f=450",
            "target_rms_db": -33.0,
            "max_boost_db": 12.0,
        },
    }

    for shot in shots:
        if not isinstance(shot, dict) or shot.get("kind") not in FOOTAGE_KINDS:
            continue
        sid = str(shot.get("id") or "shot")
        override = _explicit_bed_tier(shot.get("soundBed"))
        if override == "mute":
            summary["muted"] += 1
            summary["shots"].append({"id": sid, "tier": "mute", "reason": "explicit"})
            continue

        raw_clip = shot.get("clip") or shot.get("material") or shot.get("source")
        if not isinstance(raw_clip, str) or not raw_clip.strip():
            summary["muted"] += 1
            summary["shots"].append({"id": sid, "tier": "mute", "reason": "no-clip"})
            continue
        clip_path = _resolve_clip_path(raw_clip.strip(), sb_dir, project_root)
        if not clip_path.is_file():
            raise FileNotFoundError(f"Missing video clip for {sid}: {clip_path}")

        if not has_audio_stream(clip_path):
            summary["muted"] += 1
            summary["shots"].append({"id": sid, "tier": "mute", "reason": "no-audio-stream"})
            continue

        t0 = float(shot.get("startSec", 0.0))
        t1 = float(shot.get("endSec", t0))
        dur = float(shot.get("durationSec") or max(0.0, t1 - t0))
        if dur <= 0.05:
            continue
        ci = float(shot.get("clipIn") if shot.get("clipIn") is not None else (shot.get("in") or 0.0))

        raw_seg = decode_ffmpeg(clip_path, ss=ci, dur=dur)
        tier, metrics = (override, {"override": True}) if override else classify_broll_segment(raw_seg)
        if tier == "mute":
            summary["muted"] += 1
            summary["shots"].append({"id": sid, "tier": "mute", "metrics": metrics})
            continue

        cfg = tier_cfg[tier]
        seg = decode_ffmpeg(clip_path, af_filter=cfg["af"], ss=ci, dur=dur)
        if len(seg) < 100:
            summary["muted"] += 1
            continue

        rms = float(np.sqrt(np.mean(seg ** 2)))
        if rms > 1e-8:
            gain_db = min(cfg["target_rms_db"] - lin_to_db(rms), cfg["max_boost_db"])
            seg *= db_to_lin(gain_db)

        peak = float(np.max(np.abs(seg)))
        peak_cap = db_to_lin(-20.0)
        if peak > peak_cap:
            seg *= peak_cap / peak

        fade_s = min(0.45, 0.30 * dur)
        apply_cosine_fades(seg, fade_s, fade_s)

        idx0 = max(0, int(round(t0 * SR)))
        idx1 = min(total_samples, idx0 + len(seg))
        if idx1 > idx0:
            bed[idx0:idx1] += seg[: idx1 - idx0]
            summary[tier] += 1
            summary["shots"].append({"id": sid, "tier": tier, "metrics": metrics})

    duck_env = _compute_sidechain_envelope(voice_mono, total_samples)
    bed *= duck_env[:, None]
    return bed, summary


def _resolve_cue_path(sound_id_or_path: str, base_dir: Path, catalog: dict[str, dict]) -> Path:
    if sound_id_or_path in catalog:
        p = Path(catalog[sound_id_or_path]["path"])
        if p.is_file():
            return p
    by_rel = SFX_DIR / sound_id_or_path
    if by_rel.is_file():
        return by_rel.resolve()
    p = Path(sound_id_or_path).expanduser()
    if not p.is_absolute():
        p = base_dir / p
    if p.is_file():
        return p.resolve()
    raise FileNotFoundError(f"Missing SFX asset: {sound_id_or_path}")


def load_sfx_clip(
    path: Path,
    trim_start: float = 0.0,
    trim_dur: float | None = None,
    lowpass_hz: int | None = None,
    fade_in: float = 0.015,
    fade_out: float = 0.08,
    target_peak_db: float = -20.5,
) -> np.ndarray:
    """Decode built-in SFX with high-shelf sibilance softening (`4500 Hz -4 dB`) and safe peak."""
    filters: list[str] = []
    if lowpass_hz is not None:
        filters.append(f"lowpass=f={int(lowpass_hz)}")
    filters.append("highshelf=f=4500:g=-4")
    arr = decode_ffmpeg(path, af_filter=",".join(filters))

    s0 = max(0, int(round(trim_start * SR)))
    s1 = min(len(arr), s0 + int(round(trim_dur * SR))) if trim_dur is not None else len(arr)
    arr = arr[s0:s1].copy()
    if len(arr) == 0:
        raise ValueError(f"Empty SFX slice for {path}")

    apply_cosine_fades(arr, fade_in, fade_out)
    pk = float(np.max(np.abs(arr)))
    if pk > 1e-8:
        arr *= db_to_lin(target_peak_db) / pk
    return arr


def _expand_shot_cues(shot: dict, total_sec: float) -> list[dict]:
    st0 = float(shot.get("startSec", 0.0))
    st1 = float(shot.get("endSec", st0))
    dur = max(0.2, st1 - st0)
    kind = str(shot.get("kind") or "")
    raw_cues = shot.get("soundCues")

    if not raw_cues:
        if kind in ("card-deck", "xhs"):
            cues: list[dict] = [{"t": st0, "preset": "page-turn"}]
            items = shot.get("items") or shot.get("covers") or []
            n_cards = max(1, min(4, len(items) if isinstance(items, list) and items else 2))
            for k in range(n_cards):
                frac = 0.28 + 0.50 * (k / max(1, n_cards))
                cues.append({"t": st0 + dur * frac, "preset": "card-snap"})
            return cues
        cues = [
            {"t": max(0.0, st0 - 0.30), "preset": "swell"},
            {"t": st0, "preset": "sub-drop"},
        ]
        if dur >= 2.8:
            cues.append({"t": st0 + 0.52 * dur, "preset": "reveal-chime"})
        return cues

    planned: list[dict] = []
    detail_cues: list[str] = []
    for entry in raw_cues:
        if isinstance(entry, dict):
            t = float(entry["t"]) if "t" in entry else st0 + float(entry.get("offsetSec", 0.0))
            planned.append({
                "t": max(0.0, min(total_sec, t)),
                "preset": str(entry.get("sound") or entry.get("cue") or "whoosh"),
                **{k: v for k, v in entry.items() if k not in ("t", "offsetSec", "sound", "cue")},
            })
            continue
        name = str(entry).strip().lower()
        spec = CUE_PRESETS.get(name, {"role": "detail"})
        role = spec.get("role", "detail")
        if role == "lead":
            lead_offset = 1.15 if "riser" in name else 0.30
            planned.append({"t": max(0.0, st0 - min(lead_offset, st0)), "preset": name})
        elif role == "land":
            planned.append({"t": st0, "preset": name})
        else:
            detail_cues.append(name)

    for idx, name in enumerate(detail_cues):
        frac = (idx + 1) / (len(detail_cues) + 1)
        planned.append({"t": min(total_sec, st0 + dur * (0.20 + 0.65 * frac)), "preset": name})
    return planned


def plan_storyboard_cues(shots: list[dict], total_sec: float, catalog: dict[str, dict]) -> list[dict]:
    """Generate time-ordered SFX cue specs from `model` / `motion` / `card-deck` / `xhs` shots."""
    events: list[dict] = []
    for shot in shots:
        if not isinstance(shot, dict) or shot.get("kind") not in MOTION_KINDS:
            continue
        for cue in _expand_shot_cues(shot, total_sec):
            preset_key = cue["preset"]
            preset = dict(CUE_PRESETS.get(preset_key, {}))
            sound_ref = preset.pop("id", preset_key)
            preset.pop("role", None)
            for opt_k in ("trim_start", "trim_dur", "lowpass_hz", "fade_in", "fade_out", "target_peak_db"):
                if opt_k in cue:
                    preset[opt_k] = cue[opt_k]
            events.append({
                "t": float(cue["t"]),
                "path": _resolve_cue_path(sound_ref, SFX_DIR, catalog),
                "sound": sound_ref,
                "kwargs": preset,
            })
    events.sort(key=lambda e: e["t"])
    return events


def load_explicit_sfx_plan(plan_path: Path, catalog: dict[str, dict]) -> list[dict]:
    """Load an explicit JSON SFX event plan using local catalog or plan-relative assets only."""
    doc = json.loads(plan_path.read_text(encoding="utf-8"))
    raw = doc.get("events") if isinstance(doc, dict) else doc
    if not isinstance(raw, list):
        raise ValueError(f"Invalid SFX plan format in {plan_path}")
    events: list[dict] = []
    for ev in raw:
        sound = str(ev.get("sound") or ev.get("id") or "").strip()
        if not sound:
            raise ValueError(f"SFX plan event missing `sound`: {ev}")
        kwargs: dict[str, Any] = {}
        for k in ("trim_start", "trim_dur", "lowpass_hz", "fade_in", "fade_out", "target_peak_db"):
            if k in ev and ev[k] is not None:
                kwargs[k] = ev[k]
        events.append({
            "t": float(ev["t"]),
            "path": _resolve_cue_path(sound, plan_path.parent, catalog),
            "sound": sound,
            "kwargs": kwargs,
        })
    events.sort(key=lambda e: e["t"])
    return events


def build_sfx_layer(cues: list[dict], total_samples: int) -> tuple[np.ndarray, int]:
    """Mix all scheduled motion/card SFX cues into a 48 kHz stereo buffer."""
    sfx = np.zeros((total_samples, 2), dtype=np.float32)
    for ev in cues:
        clip = load_sfx_clip(ev["path"], **ev["kwargs"])
        i0 = max(0, int(round(ev["t"] * SR)))
        i1 = min(total_samples, i0 + len(clip))
        if i1 > i0:
            sfx[i0:i1] += clip[: i1 - i0]
    return sfx, len(cues)


def verify_soundscape_gate(
    stem_path: Path,
    voice_path: Path,
    allow_quiet: bool = False,
) -> dict[str, Any]:
    """Enforce standalone stem (`[-37, -30] LUFS`, `TP <= -13.5`) & combined mix (`[-14.2, -13.4]`, `TP <= -1.0`)."""
    stem_lufs, stem_tp = measure_loudness(stem_path)
    comb_lufs, comb_tp = measure_combined_loudness(voice_path, stem_path)
    problems: list[str] = []

    if math.isfinite(stem_tp) and stem_tp > STEM_TP_MAX:
        problems.append(f"声景真峰值超标：{stem_tp:.2f} dBTP > {STEM_TP_MAX:.1f} dBTP")
    if math.isfinite(stem_lufs):
        if stem_lufs > STEM_LUFS_MAX:
            problems.append(f"声景过响：{stem_lufs:.2f} LUFS > {STEM_LUFS_MAX:.1f} LUFS")
        elif not allow_quiet and stem_lufs < STEM_LUFS_MIN:
            problems.append(f"声景过轻：{stem_lufs:.2f} LUFS < {STEM_LUFS_MIN:.1f} LUFS（若刻意仅留稀疏音效，请加 --allow-quiet）")
    elif not allow_quiet:
        problems.append("声景全静音（-inf LUFS），未通过独立声景响度下限")

    if not math.isfinite(comb_lufs) or not (COMBINED_LUFS_MIN <= comb_lufs <= COMBINED_LUFS_MAX):
        problems.append(
            f"模拟合播响度越界：{comb_lufs:.2f} LUFS 不在 [{COMBINED_LUFS_MIN:.1f}, {COMBINED_LUFS_MAX:.1f}] LUFS"
        )
    if math.isfinite(comb_tp) and comb_tp > COMBINED_TP_MAX:
        problems.append(f"模拟合播真峰值削波：{comb_tp:.2f} dBTP > {COMBINED_TP_MAX:.1f} dBTP")

    return {
        "ok": not problems,
        "stem": {
            "path": str(stem_path),
            "lufs": None if not math.isfinite(stem_lufs) else round(stem_lufs, 2),
            "true_peak_dbtp": None if not math.isfinite(stem_tp) else round(stem_tp, 2),
        },
        "combined": {
            "voice": str(voice_path),
            "lufs": None if not math.isfinite(comb_lufs) else round(comb_lufs, 2),
            "true_peak_dbtp": None if not math.isfinite(comb_tp) else round(comb_tp, 2),
        },
        "allow_quiet": allow_quiet,
        "problems": problems,
    }


def _resolve_storyboard_file(path: Path) -> tuple[Path, Path]:
    p = path.expanduser().resolve()
    if p.is_file():
        project_root = p.parent.parent if p.parent.name == "edit" else p.parent
        return p, project_root
    if p.is_dir():
        for cand in (p / "edit" / "storyboard.json", p / "storyboard.json"):
            if cand.is_file():
                return cand, p
    raise FileNotFoundError(f"Storyboard not found: {path}")


def _finalize_stem_buffer(buf: np.ndarray) -> np.ndarray:
    cap = db_to_lin(-14.0)
    limited = (cap * np.tanh(buf / cap)).astype(np.float32)
    return apply_cosine_fades(limited, 0.020, 0.250)


def _stage_and_verify(
    buf: np.ndarray,
    dest: Path,
    voice_path: Path,
    allow_quiet: bool,
) -> tuple[Path, dict[str, Any]]:
    fd, tmp_name = tempfile.mkstemp(prefix="vc_sd_stage_", suffix=".wav", dir="/tmp")
    os.close(fd)
    tmp_wav = Path(tmp_name)
    try:
        _write_pcm16_stereo(buf, tmp_wav)
        gate = verify_soundscape_gate(tmp_wav, voice_path, allow_quiet=allow_quiet)
        if not gate["ok"]:
            tmp_wav.unlink(missing_ok=True)
            gate["stem"]["path"] = str(dest)
            return dest, gate
        dest = dest.expanduser().resolve()
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(tmp_wav), str(dest))
        gate["stem"]["path"] = str(dest)
        return dest, gate
    except Exception:
        tmp_wav.unlink(missing_ok=True)
        raise


def cmd_build(args: argparse.Namespace) -> int:
    sb_path, project_root = _resolve_storyboard_file(args.storyboard)
    voice_path = args.voice.expanduser().resolve()
    if not voice_path.is_file():
        print(json.dumps({"ok": False, "error": f"Voice WAV not found: {voice_path}"}, ensure_ascii=False))
        return 2

    sb = json.loads(sb_path.read_text(encoding="utf-8"))
    shots = sb.get("shots") or []
    sb_end = max((float(s.get("endSec", 0.0)) for s in shots if isinstance(s, dict)), default=0.0)
    total_sec = float(args.total_sec) if args.total_sec else max(float(sb.get("totalSec") or 0.0), sb_end)
    if total_sec <= 0.0:
        total_sec = probe_duration(voice_path)
    total_samples = int(round(total_sec * SR))

    voice_stereo = decode_ffmpeg(voice_path)
    voice_mono = np.mean(voice_stereo, axis=1)

    catalog = {item["id"]: item for item in load_sfx_catalog()}
    if args.sfx_plan:
        cues = load_explicit_sfx_plan(args.sfx_plan.expanduser().resolve(), catalog)
    else:
        cues = plan_storyboard_cues(shots, total_sec, catalog)
    sfx_buf, cue_count = build_sfx_layer(cues, total_samples)

    bed_on = args.broll_bed == "on"
    if bed_on:
        bed_buf, bed_summary = build_ambient_bed(shots, sb_path.parent, project_root, voice_mono, total_samples)
        primary_buf = _finalize_stem_buffer(bed_buf + sfx_buf)
    else:
        bed_summary = {"tier_a": 0, "tier_b": 0, "muted": 0, "shots": [], "disabled": True}
        primary_buf = _finalize_stem_buffer(sfx_buf)

    out_path = args.out.expanduser().resolve()
    allow_quiet_primary = bool(args.allow_quiet or not bed_on)
    final_path, gate = _stage_and_verify(primary_buf, out_path, voice_path, allow_quiet=allow_quiet_primary)

    variants: dict[str, Any] = {}
    if gate["ok"] and args.preview_variants:
        sfx_only_path = out_path.with_name(f"{out_path.stem}_sfx_only{out_path.suffix}")
        sfx_only_buf = _finalize_stem_buffer(sfx_buf)
        v_path, v_gate = _stage_and_verify(sfx_only_buf, sfx_only_path, voice_path, allow_quiet=True)
        variants["sfx_only"] = {"path": str(v_path), "gate": v_gate}
        if not v_gate["ok"]:
            gate["ok"] = False
            gate["problems"].extend(f"[sfx_only] {p}" for p in v_gate["problems"])

    payload = {
        "ok": gate["ok"],
        "out": str(final_path),
        "duration_sec": round(total_samples / SR, 3),
        "sample_rate": SR,
        "channels": 2,
        "broll_bed": args.broll_bed,
        "bed_summary": bed_summary,
        "sfx_cue_count": cue_count,
        "stem": gate["stem"],
        "combined": gate["combined"],
        "variants": variants,
        "problems": gate["problems"],
    }

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        if payload["ok"]:
            print(
                f"✓ 画面声景已生成：{final_path} ({payload['duration_sec']:.3f}s, "
                f"stem={gate['stem']['lufs']} LUFS / {gate['stem']['true_peak_dbtp']} dBTP, "
                f"mix={gate['combined']['lufs']} LUFS)"
            )
        else:
            print("✗ 画面声景声学门禁未通过：", file=sys.stderr)
            for p in gate["problems"]:
                print(f"  - {p}", file=sys.stderr)
    return 0 if payload["ok"] else 1


def cmd_verify(args: argparse.Namespace) -> int:
    stem_path = args.stem.expanduser().resolve()
    voice_path = args.voice.expanduser().resolve()
    for label, p in (("stem", stem_path), ("voice", voice_path)):
        if not p.is_file():
            print(json.dumps({"ok": False, "error": f"Missing {label} WAV: {p}"}, ensure_ascii=False))
            return 2

    gate = verify_soundscape_gate(stem_path, voice_path, allow_quiet=args.allow_quiet)
    if args.json:
        print(json.dumps(gate, ensure_ascii=False, indent=2))
    else:
        if gate["ok"]:
            print(
                f"✓ 画面声景门禁通过：stem={gate['stem']['lufs']} LUFS / {gate['stem']['true_peak_dbtp']} dBTP, "
                f"combined={gate['combined']['lufs']} LUFS / {gate['combined']['true_peak_dbtp']} dBTP"
            )
        else:
            print("✗ 画面声景门禁未通过：", file=sys.stderr)
            for p in gate["problems"]:
                print(f"  - {p}", file=sys.stderr)
    return 0 if gate["ok"] else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--list-sfx", action="store_true", help="List built-in CC0 soundscape SFX catalog")
    parser.add_argument("--json", action="store_true", help="Print JSON output")

    sub = parser.add_subparsers(dest="cmd")

    p_build = sub.add_parser("build", help="Build 48kHz stereo soundscape WAV from storyboard + voice")
    p_build.add_argument("--storyboard", "-s", required=True, type=Path, help="Path to storyboard.json or project dir")
    p_build.add_argument("--voice", "-v", required=True, type=Path, help="Master Voice Polish WAV (sidechain key)")
    p_build.add_argument("--out", "-o", required=True, type=Path, help="Destination soundscape WAV path")
    p_build.add_argument("--sfx-plan", type=Path, default=None, help="Optional explicit SFX event JSON plan")
    p_build.add_argument("--broll-bed", choices=("on", "off"), default="on", help="Enable screened B-roll ambient bed")
    p_build.add_argument("--preview-variants", action="store_true", help="Also emit *_sfx_only.wav review variant")
    p_build.add_argument("--total-sec", type=float, default=None, help="Override total output duration in seconds")
    p_build.add_argument("--allow-quiet", action="store_true", help="Allow stem below -37.0 LUFS for sparse cues")
    p_build.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Print structured JSON summary")

    p_verify = sub.add_parser("verify", help="Verify standalone stem and simulated combined mix loudness/TP gates")
    p_verify.add_argument("--stem", required=True, type=Path, help="Soundscape WAV to verify")
    p_verify.add_argument("--voice", "-v", required=True, type=Path, help="Master Voice Polish WAV for mix simulation")
    p_verify.add_argument("--allow-quiet", action="store_true", help="Relax -37.0 LUFS lower bound on sparse SFX stems")
    p_verify.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Print structured JSON report")

    p_make = sub.add_parser("make-sfx", help="(Maintainer) Regenerate built-in procedural CC0 SFX WAVs")
    p_make.add_argument("--out-dir", type=Path, default=None, help="Optional target directory (defaults to assets/sfx)")
    p_make.add_argument("--json", action="store_true", default=argparse.SUPPRESS)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.list_sfx:
        items = load_sfx_catalog()
        if args.json:
            print(json.dumps({"items": items}, ensure_ascii=False, indent=2))
        else:
            for it in items:
                print(f"{it['id']:24s} [{it.get('kind', '-')}] {it.get('duration_s')}s - {it.get('description', '')}")
        return 0

    if args.cmd == "build":
        return cmd_build(args)
    if args.cmd == "verify":
        return cmd_verify(args)
    if args.cmd == "make-sfx":
        files = synthesize_builtin_sfx(args.out_dir)
        if args.json:
            print(json.dumps({"ok": True, "files": [str(f) for f in files]}, ensure_ascii=False, indent=2))
        else:
            print(f"Generated {len(files)} procedural CC0 SFX WAVs")
        return 0

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
