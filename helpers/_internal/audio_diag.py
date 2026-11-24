"""Diagnose spoken-word audio quality (the "muddy / dark / harsh / quiet" question).

Answers the four classic complaints with numbers:

  band profile (dB, relative to 300-1k):
    120-300  > +2 dB          -> muddy / boxy (proximity effect, chesty voice)
    1k-4k    < -15 dB         -> dark / muffled (missing presence)
    4k-8k    vs 1k-4k crest   -> sibilance spikes (harsh transients) live here
  spectral tilt 500-8k: steeper than ~-6 dB/oct -> dark recording
  EBU R128 integrated loudness: below ~-16 LUFS -> quiet vs social-platform norm
  crest(4-8k) - crest(1-4k) > 3 dB -> de-ess candidate

Usage:
    python helpers/audio_diag.py <audio1> [audio2 ...]
    python helpers/audio_diag.py in.wav --chart diag.png
Inputs: wav/mp3/m4a/mp4 (ffmpeg-decoded, mono-converted internally).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

SR = 48000
BANDS = [
    ("sub   60-120", 60, 120),
    ("low-mid 120-300", 120, 300),
    ("mid   300-1k", 300, 1000),
    ("presence 1k-4k", 1000, 4000),
    ("harsh 4k-8k", 4000, 8000),
    ("air   8k-16k", 8000, 16000),
]
OCT_BANDS = [(500, 1000), (1000, 2000), (2000, 4000), (4000, 8000)]


def decode_to_wav(path: Path) -> Path:
    """ffmpeg-decode any audio/video input to mono 48k wav in a temp dir."""
    tmp = Path(tempfile.mkdtemp(prefix="audio_diag_"))
    out = tmp / "in.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(path),
         "-vn", "-ac", "1", "-ar", str(SR), "-c:a", "pcm_s16le", "-bitexact", str(out)],
        check=True)
    return out


def load_wav(path: Path) -> np.ndarray:
    import wave
    with wave.open(str(path), "rb") as w:
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float64) / 32768.0
    return data


def voice_gate(x: np.ndarray) -> np.ndarray:
    """Keep only speech-active regions (RMS gate + dilation) so silence
    doesn't drag the spectrum down."""
    from scipy.ndimage import binary_dilation
    win = int(0.05 * SR)
    n = len(x) // win * win
    rms = np.sqrt(np.mean(x[:n].reshape(-1, win) ** 2, axis=1))
    act = binary_dilation(rms > 0.008, iterations=3)
    if not act.any():
        return x
    idx = np.where(act)[0]
    return x[idx[0] * win: (idx[-1] + 1) * win]


def band_energy(x: np.ndarray, lo: float, hi: float) -> float:
    n = len(x)
    X = np.fft.rfft(x * np.hanning(n))
    f = np.fft.rfftfreq(n, 1 / SR)
    m = (f >= lo) & (f < hi)
    return 10 * np.log10(np.mean(np.abs(X[m]) ** 2) + 1e-12)


def crest_factor(x: np.ndarray, lo: float, hi: float) -> float:
    """Peak-vs-RMS of the band envelope over ~10ms windows: how spikey the
    band's transients are. Sibilance (4-8k) reads 3+ dB above presence."""
    win = int(0.01 * SR)
    n = len(x) // win * win
    frames = x[:n].reshape(-1, win)
    X = np.abs(np.fft.rfft(frames * np.hanning(win), axis=1))
    f = np.fft.rfftfreq(win, 1 / SR)
    m = (f >= lo) & (f < hi)
    band = X[:, m]
    env = np.sqrt(np.mean(band ** 2, axis=1))
    return float(10 * np.log10((np.max(env) + 1e-12) / (np.mean(env) + 1e-12)))


def ebur128(path: Path) -> dict:
    out = subprocess.run(
        ["ffmpeg", "-nostats", "-i", str(path), "-filter_complex", "ebur128",
         "-f", "null", "-bitexact", "-"],
        capture_output=True, text=True).stderr
    lu, tp, lra = None, None, None
    for line in out.splitlines():
        s = line.strip()
        if s.startswith("I:"):
            lu = float(s.split()[1])
        elif s.startswith("LRA:"):
            lra = float(s.split()[1])
        elif s.startswith("Peak:"):
            tp = float(s.split()[1])
    return {"lufs": lu, "true_peak": tp, "lra": lra}


def diagnose(label: str, x: np.ndarray, loud: dict) -> dict:
    ref = band_energy(x, 300, 1000)
    bands = {name: band_energy(x, lo, hi) - ref for name, lo, hi in BANDS}
    tilt = np.polyfit(
        [np.log2(np.sqrt(lo * hi)) for lo, hi in OCT_BANDS],
        [band_energy(x, lo, hi) for lo, hi in OCT_BANDS], 1)[0]
    crest_pres = crest_factor(x, 1000, 4000)
    crest_harsh = crest_factor(x, 4000, 8000)
    centroid = float(np.sum(
        np.abs(np.fft.rfft(x * np.hanning(len(x)))) * np.fft.rfftfreq(len(x), 1 / SR)
    ) / (np.sum(np.abs(np.fft.rfft(x * np.hanning(len(x))))) + 1e-12))

    issues: list[str] = []
    if bands["low-mid 120-300"] > 2.0:
        issues.append(f"muddy: low-mid {bands['low-mid 120-300']:+.1f}dB vs 300-1k — cut ~200-300Hz 2-3dB")
    if bands["presence 1k-4k"] < -15.0:
        issues.append(f"dark: presence {bands['presence 1k-4k']:+.1f}dB vs 300-1k — boost 2.5-4k +2-3dB")
    if tilt < -6.0:
        issues.append(f"dark: spectral tilt {tilt:.1f}dB/oct 500-8k — steep high rolloff")
    if crest_harsh - crest_pres > 3.0:
        issues.append(f"sibilance: crest 4-8k {crest_harsh:.1f}dB vs 1-4k {crest_pres:.1f}dB — de-ess 5-8k transients")
    if loud.get("lufs") is not None and loud["lufs"] < -16.0:
        issues.append(f"quiet: {loud['lufs']:.1f} LUFS — social norm ~-14, normalize +{ -16.0 - loud['lufs']:.1f}dB")
    if not issues:
        issues.append("no strong issues detected")

    return {
        "label": label,
        "rms_dbfs": round(float(20 * np.log10(np.sqrt(np.mean(x ** 2)) + 1e-12)), 1),
        "peak_dbfs": round(float(20 * np.log10(np.max(np.abs(x)) + 1e-12)), 1),
        "spectral_centroid_khz": round(centroid / 1000, 2),
        "bands_rel_300_1k": {k: round(v, 1) for k, v in bands.items()},
        "tilt_db_per_oct": round(float(tilt), 1),
        "crest_1_4k_db": round(crest_pres, 1),
        "crest_4_8k_db": round(crest_harsh, 1),
        "loudness": {k: (round(v, 1) if v is not None else None) for k, v in loud.items()},
        "issues": issues,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Diagnose spoken-word audio quality")
    ap.add_argument("inputs", nargs="+", type=Path)
    ap.add_argument("--chart", type=Path, default=None, help="Optional PNG: 1/3-octave levels + crest")
    ap.add_argument("--json", action="store_true", help="Emit machine-readable report")
    args = ap.parse_args()

    reports = []
    for inp in args.inputs:
        wav = decode_to_wav(inp)
        x = voice_gate(load_wav(wav))
        loud = ebur128(wav)
        rep = diagnose(inp.name, x, loud)
        reports.append(rep)
        if args.json:
            print(json.dumps(rep, ensure_ascii=False, indent=1))
            continue
        print(f"\n=== {inp.name} ===  voice {len(x)/SR:.1f}s | RMS {rep['rms_dbfs']}dBFS | "
              f"peak {rep['peak_dbfs']}dBFS | centroid {rep['spectral_centroid_khz']}kHz")
        print(f"  loudness {loud['lufs']} LUFS (LRA {loud['lra']}, TP {loud['true_peak']})")
        print("  bands (rel 300-1k): " + " | ".join(f"{k.split()[0]}:{v:+.1f}" for k, v in rep["bands_rel_300_1k"].items()))
        print(f"  tilt {rep['tilt_db_per_oct']} dB/oct | crest 1-4k {rep['crest_1_4k_db']}dB / 4-8k {rep['crest_4_8k_db']}dB")
        for issue in rep["issues"]:
            print(f"  ⚠ {issue}")

    if args.chart:
        try:
            _chart(args.inputs, args.chart)
        except ImportError:
            print("--chart needs matplotlib (video-use venv has it)", file=sys.stderr)


def _chart(inputs: list[Path], out: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    centers = np.geomspace(50, 16000, 25)
    lo = centers / 2 ** (1 / 6)
    hi = centers * 2 ** (1 / 6)
    fig, axes = plt.subplots(2, 1, figsize=(11, 7))
    for inp in inputs:
        wav = decode_to_wav(inp)
        x = voice_gate(load_wav(wav))
        n = len(x)
        X = np.abs(np.fft.rfft(x * np.hanning(n)))
        f = np.fft.rfftfreq(n, 1 / SR)
        levels, crests = [], []
        for a, b in zip(lo, hi):
            m = (f >= a) & (f < b)
            P = X[m] ** 2
            levels.append(10 * np.log10(np.mean(P) + 1e-12))
            crests.append(10 * np.log10(np.max(P) / (np.mean(P) + 1e-12) + 1e-12))
        levels = np.array(levels) - np.max(levels)
        axes[0].semilogx(centers, levels, label=inp.name)
        axes[1].semilogx(centers, crests, label=inp.name)
    axes[0].set_title("1/3-octave levels (rel peak)"); axes[0].grid(True, which="both", alpha=0.3)
    axes[1].set_title("1/3-octave crest factor (harshness)"); axes[1].grid(True, which="both", alpha=0.3)
    for ax in axes:
        ax.legend()
    fig.tight_layout()
    fig.savefig(out, dpi=110)
    print(f"chart -> {out}")


if __name__ == "__main__":
    main()
