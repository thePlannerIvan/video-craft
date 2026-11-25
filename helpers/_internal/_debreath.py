#!/usr/bin/env python3
"""Surgical inter-sentence / inter-word pause breath attenuation (0.000s drift).

Protects all speech syllables and unvoiced consonants (s/f/sh/x/q/ch/p/t/k) with
dual-band speech detection (<400Hz vocal fundamental + HF-ratio gating) and wide
morphological dilation (100ms pre, 70ms post), then attenuates only pause valleys
>= 140ms down to a natural -62 dBFS room floor with 35ms Hann fades.
"""
from __future__ import annotations

import math
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path
from typing import Any

import numpy as np

DEFAULT_FLOOR_DB = -62.0
DEFAULT_MIN_GAIN = 0.015  # up to -36.5 dB attenuation so even -25 dBFS breaths reach -62 dBFS
DEFAULT_FADE_MS = 35.0
BREATH_DETECT_THRESHOLD_DB = -48.0
MIN_VALLEY_MS = 140.0
PRE_DILATE_MS = 100.0
POST_DILATE_MS = 70.0
MAX_PROTECTED_SPEECH_DELTA_DB = 0.1


class DebreathInvariantError(RuntimeError):
    """Raised when sample-count or protected-speech energy invariants fail."""


def _compute_frame_features(
    mono_norm: np.ndarray,
    sr: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, int, int]:
    """Compute 20ms/10ms frame RMS, <400Hz low-band RMS, and SR-normalized HF ratio."""
    n_samples = len(mono_norm)
    hop = max(1, int(round(sr * 0.010)))
    win = max(2, int(round(sr * 0.020)))
    n_frames = n_samples // hop
    if n_frames == 0:
        empty = np.zeros(0, dtype=np.float32)
        return empty, empty, empty, hop, win

    freqs = np.fft.rfftfreq(n_samples, d=1.0 / sr)
    spec = np.fft.rfft(mono_norm.astype(np.float64))
    lp_gain = 1.0 / np.sqrt(1.0 + (freqs / 400.0) ** 4)
    low_band = np.fft.irfft(spec * lp_gain, n=n_samples)

    rms_db = np.empty(n_frames, dtype=np.float32)
    low_db = np.empty(n_frames, dtype=np.float32)
    hf_ratio = np.empty(n_frames, dtype=np.float32)

    eps = 1e-9
    sr_scale = float(sr) / 48000.0
    for fi in range(n_frames):
        s0 = fi * hop
        s1 = min(n_samples, s0 + win)
        seg = mono_norm[s0:s1]
        lseg = low_band[s0:s1]
        ms = float(np.mean(seg * seg))
        lms = float(np.mean(lseg * lseg))
        rms = math.sqrt(ms)
        dms = float(np.mean(np.diff(seg) ** 2)) if len(seg) > 1 else 0.0
        rms_db[fi] = 20.0 * math.log10(rms + eps)
        low_db[fi] = 20.0 * math.log10(math.sqrt(lms) + eps)
        hf_ratio[fi] = (math.sqrt(dms) / (rms + eps)) * sr_scale

    return rms_db, low_db, hf_ratio, hop, win


def analyze_pause_breaths(
    mono_norm: np.ndarray,
    sr: int,
    *,
    breath_threshold_db: float = BREATH_DETECT_THRESHOLD_DB,
    adaptive: bool = True,
) -> dict[str, Any]:
    """Detect protected speech, dilated speech mask, and >=140ms pause valleys."""
    rms_db, low_db, hf_ratio, hop, win = _compute_frame_features(mono_norm, sr)
    n_frames = len(rms_db)
    if n_frames == 0:
        empty_bool = np.zeros(0, dtype=bool)
        return {
            "hop": hop,
            "win": win,
            "rms_db": rms_db,
            "speech": empty_bool,
            "dilated": empty_bool,
            "valleys": [],
            "valley_stats": [],
            "pause_valleys": 0,
            "breath_valleys": 0,
            "pause_breath_max_db": None,
            "pause_breath_mean_db": None,
        }

    ref_shift = 0.0
    if adaptive:
        active_frames = rms_db[rms_db > -55.0]
        if len(active_frames) > 0:
            p90 = float(np.percentile(active_frames, 90))
            if p90 < -18.0:
                ref_shift = max(-20.0, p90 - (-16.0))

    rms_gate = -29.0 + ref_shift
    low_gate = -32.0 + ref_shift
    loud_gate = -22.0 + ref_shift
    eff_breath_thresh = breath_threshold_db + ref_shift

    speech = ((rms_db > rms_gate) & ((hf_ratio < 0.24) | (low_db > low_gate))) | (rms_db > loud_gate)

    pre_frames = max(1, int(round((PRE_DILATE_MS / 1000.0) * sr / hop)))
    post_frames = max(1, int(round((POST_DILATE_MS / 1000.0) * sr / hop)))
    dilated = speech.copy()
    for shift in range(-pre_frames, post_frames + 1):
        if shift < 0:
            k = -shift
            if k < n_frames:
                dilated[:-k] |= speech[k:]
        elif shift > 0:
            k = shift
            if k < n_frames:
                dilated[k:] |= speech[:-k]

    min_gap_frames = max(1, int(round((MIN_VALLEY_MS / 1000.0) * sr / hop)))
    gap_mask = ~dilated
    padded = np.concatenate(([False], gap_mask, [False]))
    starts = np.flatnonzero(~padded[:-1] & padded[1:])
    ends = np.flatnonzero(padded[:-1] & ~padded[1:])

    valleys: list[tuple[int, int]] = []
    valley_stats: list[dict[str, float]] = []
    for st, en in zip(starts, ends):
        st_i, en_i = int(st), int(en)
        if (en_i - st_i) < min_gap_frames:
            dilated[st_i:en_i] = True
        else:
            valleys.append((st_i, en_i))
            seg_db = rms_db[st_i:en_i]
            valley_stats.append({
                "start_s": round(st_i * hop / sr, 3),
                "end_s": round(en_i * hop / sr, 3),
                "max_db": round(float(np.max(seg_db)), 2),
                "mean_db": round(float(np.mean(seg_db)), 2),
            })

    breathy = [v for v in valley_stats if v["max_db"] > eff_breath_thresh]
    max_db = max((v["max_db"] for v in valley_stats), default=None)
    mean_db = (
        round(sum(v["mean_db"] for v in breathy) / len(breathy), 2)
        if breathy
        else (round(sum(v["mean_db"] for v in valley_stats) / len(valley_stats), 2) if valley_stats else None)
    )

    return {
        "hop": hop,
        "win": win,
        "rms_db": rms_db,
        "speech": speech,
        "dilated": dilated,
        "valleys": valleys,
        "valley_stats": valley_stats,
        "pause_valleys": len(valleys),
        "breath_valleys": len(breathy),
        "pause_breath_max_db": max_db,
        "pause_breath_mean_db": mean_db,
    }


def _to_normalized_float(pcm: np.ndarray) -> tuple[np.ndarray, str, int]:
    """Convert int/float PCM array to float64 normalized to [-1.0, 1.0]."""
    arr = np.asarray(pcm)
    orig_ndim = arr.ndim
    if orig_ndim == 1:
        arr2 = arr[:, None]
    elif orig_ndim == 2:
        arr2 = arr
    else:
        raise ValueError(f"Unsupported PCM array shape: {arr.shape}")

    if np.issubdtype(arr.dtype, np.floating):
        return arr2.astype(np.float64), "float", orig_ndim
    if arr.dtype == np.int16:
        return arr2.astype(np.float64) / 32768.0, "int16", orig_ndim
    if arr.dtype == np.int32:
        return arr2.astype(np.float64) / 2147483648.0, "int32", orig_ndim
    if arr.dtype == np.uint8:
        return (arr2.astype(np.float64) - 128.0) / 128.0, "uint8", orig_ndim
    raise ValueError(f"Unsupported PCM dtype: {arr.dtype}")


def _from_normalized_float(norm: np.ndarray, kind: str, orig_dtype: np.dtype, orig_ndim: int) -> np.ndarray:
    if kind == "float":
        out = norm.astype(orig_dtype)
    elif kind == "int16":
        out = np.clip(np.rint(norm * 32768.0), -32768, 32767).astype(np.int16)
    elif kind == "int32":
        out = np.clip(np.rint(norm * 2147483648.0), -2147483648, 2147483647).astype(np.int32)
    elif kind == "uint8":
        out = np.clip(np.rint(norm * 128.0 + 128.0), 0, 255).astype(np.uint8)
    else:
        raise ValueError(f"Unknown sample kind: {kind}")
    return out[:, 0] if orig_ndim == 1 else out


def debreath_samples(
    pcm: np.ndarray,
    sr: int,
    *,
    floor_db: float = DEFAULT_FLOOR_DB,
    min_gain: float = DEFAULT_MIN_GAIN,
    fade_ms: float = DEFAULT_FADE_MS,
    adaptive: bool = True,
    max_speech_delta_db: float = MAX_PROTECTED_SPEECH_DELTA_DB,
    mask_mono: np.ndarray | None = None,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Attenuate >=140ms pause breath valleys while strictly preserving sample count and speech RMS."""
    if sr <= 0:
        raise ValueError(f"Sample rate must be positive, got {sr}")
    pcm_arr = np.asarray(pcm)
    norm, kind, orig_ndim = _to_normalized_float(pcm_arr)
    n_samples = norm.shape[0]
    if n_samples == 0:
        return pcm_arr.copy(), {
            "frames": 0,
            "valleys_cleaned": 0,
            "breath_valleys_before": 0,
            "max_speech_delta_db": 0.0,
            "mean_speech_delta_db": 0.0,
        }

    mono = norm.mean(axis=1)
    detect_mono = mono if mask_mono is None else np.asarray(mask_mono, dtype=np.float64)
    if len(detect_mono) != n_samples:
        raise ValueError(f"mask_mono length {len(detect_mono)} != audio length {n_samples}")

    analysis = analyze_pause_breaths(detect_mono, sr, adaptive=adaptive)
    rms_db, _, _, hop, win = _compute_frame_features(mono, sr)
    speech = analysis["speech"]
    dilated = analysis["dilated"]
    valleys = analysis["valleys"]
    n_frames = len(rms_db)

    if n_frames == 0:
        return pcm_arr.copy(), {
            "frames": n_samples,
            "valleys_cleaned": 0,
            "breath_valleys_before": 0,
            "max_speech_delta_db": 0.0,
            "mean_speech_delta_db": 0.0,
        }

    # Hold local peak RMS across +/-20ms inside valleys so Hann fade-back never lifts breath tails.
    pad_r = max(1, int(round(0.020 * sr / hop)))
    frame_gain = np.ones(n_frames, dtype=np.float64)
    for fi in range(n_frames):
        if not dilated[fi]:
            lo = max(0, fi - pad_r)
            hi = min(n_frames, fi + pad_r + 1)
            local_mask = ~dilated[lo:hi]
            local_rms = float(np.max(rms_db[lo:hi][local_mask]))
            tg = 10.0 ** ((floor_db - local_rms) / 20.0)
            frame_gain[fi] = min(1.0, max(min_gain, tg))

    t_frames = np.arange(n_frames, dtype=np.float64) * hop + hop * 0.5
    t_samples = np.arange(n_samples, dtype=np.float64)
    sample_gain = np.interp(t_samples, t_frames, frame_gain)

    k_len = max(3, int(round((fade_ms / 1000.0) * sr)) | 1)
    hann = np.hanning(k_len)
    hann_sum = float(hann.sum())
    if hann_sum > 0:
        hann = hann / hann_sum
    # Edge padding prevents artificial fade dips when speech starts at sample 0 or ends at N-1.
    padded_gain = np.pad(sample_gain, pad_width=k_len // 2, mode="edge")
    smooth_gain = np.convolve(padded_gain, hann, mode="valid")
    np.clip(smooth_gain, min_gain, 1.0, out=smooth_gain)

    out_norm = norm * smooth_gain[:, None]
    out_pcm = _from_normalized_float(out_norm, kind, pcm_arr.dtype, orig_ndim)

    if out_pcm.shape != pcm_arr.shape:
        raise DebreathInvariantError(
            f"Sample count / shape mismatch: {out_pcm.shape} != {pcm_arr.shape}"
        )

    out_norm_recheck, _, _ = _to_normalized_float(out_pcm)
    out_mono = out_norm_recheck.mean(axis=1)

    eps = 1e-9
    sp_idx = np.flatnonzero(speech)
    delta_vals: list[float] = []
    for fi in sp_idx:
        s0 = int(fi) * hop
        s1 = min(n_samples, s0 + win)
        r_in = math.sqrt(float(np.mean(mono[s0:s1] ** 2)))
        if r_in < 1e-6:
            continue
        r_out = math.sqrt(float(np.mean(out_mono[s0:s1] ** 2))) + eps
        delta_vals.append(20.0 * math.log10(r_out / (r_in + eps)))

    max_abs_delta = max((abs(x) for x in delta_vals), default=0.0)
    mean_delta = (sum(delta_vals) / len(delta_vals)) if delta_vals else 0.0
    if max_abs_delta > max_speech_delta_db:
        raise DebreathInvariantError(
            f"Protected speech RMS delta {max_abs_delta:.3f} dB exceeds {max_speech_delta_db:.3f} dB"
        )

    after_analysis = analyze_pause_breaths(out_mono, sr, adaptive=adaptive)
    return out_pcm, {
        "frames": n_samples,
        "sample_rate": sr,
        "channels": norm.shape[1],
        "valleys_cleaned": len(valleys),
        "breath_valleys_before": analysis["breath_valleys"],
        "breath_valleys_after": after_analysis["breath_valleys"],
        "pause_breath_max_db_before": analysis["pause_breath_max_db"],
        "pause_breath_max_db_after": after_analysis["pause_breath_max_db"],
        "max_speech_delta_db": round(max_abs_delta, 4),
        "mean_speech_delta_db": round(mean_delta, 4),
    }


def _read_wav_pcm(path: Path) -> tuple[np.ndarray, int, Any]:
    """Read a WAV file into an (N, C) PCM array; decode non-standard WAV via ffmpeg if needed."""
    dtype_map = {1: np.uint8, 2: np.int16, 4: np.int32}
    try:
        with wave.open(str(path), "rb") as wf:
            params = wf.getparams()
            sr = wf.getframerate()
            nc = wf.getnchannels()
            sw = wf.getsampwidth()
            nf = wf.getnframes()
            raw = wf.readframes(nf)
    except wave.Error:
        sw = -1
        params = None
        sr = 0
        nc = 0
        nf = 0
        raw = b""

    if sw not in dtype_map:
        with tempfile.TemporaryDirectory() as td:
            decoded = Path(td) / "decoded.wav"
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-i", str(path),
                 "-c:a", "pcm_s16le", "-bitexact", str(decoded)],
                check=True,
            )
            with wave.open(str(decoded), "rb") as wf:
                params = wf.getparams()
                sr = wf.getframerate()
                nc = wf.getnchannels()
                sw = wf.getsampwidth()
                nf = wf.getnframes()
                raw = wf.readframes(nf)

    pcm = np.frombuffer(raw, dtype=dtype_map[sw]).reshape(-1, nc)
    if len(pcm) != nf:
        raise DebreathInvariantError(f"Decoded WAV frames {len(pcm)} != header {nf}")
    return pcm, sr, params


def debreath_wav(inp: Path, out: Path, *, mask_wav: Path | None = None, **kwargs: Any) -> dict[str, Any]:
    """Read a WAV file, apply debreath_samples, and atomically write output WAV."""
    pcm, sr, params = _read_wav_pcm(inp)
    nf = len(pcm)

    mask_mono = None
    if mask_wav is not None:
        m_pcm, m_sr, _ = _read_wav_pcm(mask_wav)
        if m_sr == sr and len(m_pcm) == nf:
            m_norm, _, _ = _to_normalized_float(m_pcm)
            mask_mono = m_norm.mean(axis=1)

    out_pcm, stats = debreath_samples(pcm, sr, mask_mono=mask_mono, **kwargs)
    if len(out_pcm) != nf:
        raise DebreathInvariantError(f"Output WAV frames {len(out_pcm)} != input {nf}")

    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        tmp_wav = Path(td) / out.name
        with wave.open(str(tmp_wav), "wb") as wf:
            wf.setparams(params)
            wf.writeframes(out_pcm.tobytes())
        shutil.move(str(tmp_wav), str(out))

    return stats
