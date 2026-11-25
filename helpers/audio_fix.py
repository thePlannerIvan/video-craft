#!/usr/bin/env python3
"""Standalone voice acoustic diagnosis and short A/B auditioning (--ab, default: C 'podcast-warm').

Role boundary:
  Use `audio_fix.py` ONLY for standalone voice acoustic diagnosis, single-track checks, or
  short A/B loudness-matched auditioning (`--ab`). For final project audio mixing, pass the
  raw cut speech track directly to `helpers/audio_mix.py` (which already applies `podcast-warm`
  by default) rather than compressing twice; if an `audio_fix.py` output must enter
  `audio_mix.py`, pass `--voice-preset none` there.

Presets:
  - podcast-warm (default): 65Hz highpass, 115Hz +3.0dB, 245Hz -3.5dB,
    3.2kHz +2.5dB, 9.5kHz highshelf +1.8dB, 5.2-8.2kHz sidechain de-ess,
    mild acompressor, and two-pass loudnorm to -14.0 LUFS / -1.5 dBTP (48kHz stereo).
  - gentle: legacy 80Hz highpass, 250Hz -2dB, 3.2kHz +1.5dB, optional --deess, static gain.
  - raw (or --raw): bypass all EQ, de-ess, compression, and loudnorm; export clean PCM WAV.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

_INTERNAL_DIR = str(Path(__file__).resolve().parent / "_internal")
if _INTERNAL_DIR not in sys.path:
    sys.path.insert(0, _INTERNAL_DIR)

import _debreath

GENTLE_EQ = (
    "highpass=f=80,"
    "equalizer=f=250:t=q:w=1.2:g=-2,"
    "equalizer=f=3200:t=q:w=2.0:g=1.5"
)
DEESS = (
    "asplit=2[a][b];"
    "[b]highpass=f=5200,lowpass=f=8200[sc];"
    "[a][sc]sidechaincompress=threshold=0.025:ratio=6:attack=2:release=120[dc]"
)
PODCAST_WARM_FILTER = (
    "[0:a]aresample=48000,"
    "highpass=f=65:poles=2,"
    "equalizer=f=115:t=q:w=1.2:g=3.0,"
    "equalizer=f=245:t=q:w=1.8:g=-3.5,"
    "equalizer=f=3200:t=q:w=1.5:g=2.5,"
    "highshelf=f=9500:g=1.8,"
    "asplit=2[a][b];"
    "[b]highpass=f=5200,lowpass=f=8200[sc];"
    "[a][sc]sidechaincompress=threshold=0.025:ratio=6:attack=2:release=120[dc];"
    "[dc]acompressor=threshold=-20dB:ratio=2.4:attack=12:release=140:makeup=1.5dB[out]"
)


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "").strip().splitlines()
        detail = msg[-1][:240] if msg else f"exit {proc.returncode}"
        raise RuntimeError(f"ffmpeg failed: {detail}")
    return proc


def measure_program_stats(path: Path) -> tuple[float, float]:
    """Return (integrated_lufs, true_peak_dbtp) using loudnorm JSON summary."""
    proc = run([
        "ffmpeg", "-hide_banner", "-i", str(path),
        "-ar", "48000", "-ac", "2",
        "-af", "loudnorm=I=-14.0:TP=-1.5:LRA=9:print_format=json",
        "-f", "null", "-",
    ])
    m = re.search(r'\{[^{}]*"input_i"[^{}]*\}', proc.stderr, re.S)
    if not m:
        raise RuntimeError(f"could not measure loudness JSON of {path}")
    blob = json.loads(m.group(0))
    return float(blob["input_i"]), float(blob["input_tp"])


def measure_lufs(path: Path) -> float:
    out = subprocess.run(
        ["ffmpeg", "-nostats", "-i", str(path), "-filter_complex", "ebur128",
         "-f", "null", "-bitexact", "-"],
        capture_output=True, text=True,
    ).stderr
    for line in out.splitlines():
        m = re.match(r"\s*I:\s*(-?[\d.]+)\s+LUFS", line)
        if m:
            return float(m.group(1))
    sys.exit(f"could not measure loudness of {path}")


def measure_peak(path: Path) -> float:
    out = subprocess.run(
        ["ffmpeg", "-nostats", "-i", str(path), "-af", "volumedetect",
         "-f", "null", "-bitexact", "-"],
        capture_output=True, text=True,
    ).stderr
    for line in out.splitlines():
        m = re.search(r"max_volume:\s*(-?[\d.]+)\s+dB", line)
        if m:
            return float(m.group(1))
    sys.exit(f"could not measure peak of {path}")


def _loudnorm_pass1(path: Path, target_lufs: float, tp: float = -1.5, lra: float = 9.0) -> dict[str, float] | None:
    proc = run([
        "ffmpeg", "-hide_banner", "-i", str(path),
        "-ar", "48000", "-ac", "2",
        "-af", f"loudnorm=I={target_lufs}:TP={tp}:LRA={lra}:print_format=json",
        "-f", "null", "-",
    ])
    m = re.search(r'\{[^{}]*"input_i"[^{}]*\}', proc.stderr, re.S)
    if not m:
        return None
    blob = json.loads(m.group(0))
    keys = ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")
    parsed: dict[str, float] = {}
    for k in keys:
        try:
            v = float(blob[k])
        except (KeyError, TypeError, ValueError):
            return None
        if not math.isfinite(v):
            return None
        parsed[k] = v
    return parsed


def _two_pass_loudnorm(
    inp: Path,
    out: Path,
    target_lufs: float = -14.0,
    tp: float = -1.5,
    lra: float = 9.0,
    comment_tag: str | None = None,
) -> None:
    stats = _loudnorm_pass1(inp, target_lufs, tp=tp, lra=lra)
    if stats is not None:
        af = (
            f"loudnorm=I={target_lufs}:TP={tp}:LRA={lra}:"
            f"measured_I={stats['input_i']}:measured_TP={stats['input_tp']}:"
            f"measured_LRA={stats['input_lra']}:measured_thresh={stats['input_thresh']}:"
            f"offset={stats['target_offset']}:linear=true"
        )
    else:
        af = f"loudnorm=I={target_lufs}:TP={tp}:LRA={lra}"
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(inp), "-af", af]
    if comment_tag:
        cmd += ["-metadata", f"comment={comment_tag}"]
    cmd += ["-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", "-bitexact", str(out)]
    run(cmd)


def apply_chain(inp: Path, out: Path, deess: bool) -> None:
    if deess:
        fc = f"[0:a]{GENTLE_EQ},{DEESS}[out]"
        run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(inp),
             "-filter_complex", fc, "-map", "[out]", "-bitexact", str(out)])
    else:
        run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(inp),
             "-af", GENTLE_EQ, "-bitexact", str(out)])


def normalize_static(inp: Path, out: Path, target_lufs: float, comment_tag: str | None = None) -> tuple[float, float]:
    """Static gain to target LUFS without a limiter; returns (gain_db, final_peak_db)."""
    lu = measure_lufs(inp)
    gain = target_lufs - lu
    peak = measure_peak(inp)
    final_peak = peak + gain
    if final_peak > -1.0:
        gain -= (final_peak + 1.0)
        final_peak = -1.0
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(inp), "-af", f"volume={gain:.2f}dB"]
    if comment_tag:
        cmd += ["-metadata", f"comment={comment_tag}"]
    cmd += ["-bitexact", str(out)]
    run(cmd)
    return round(gain, 2), round(final_peak, 1)


def apply_voice_preset(
    inp: Path,
    out: Path,
    *,
    preset: str = "podcast-warm",
    target_lufs: float = -14.0,
    deess: bool = False,
    debreath: bool | None = None,
) -> dict[str, Any]:
    """Process audio file with the chosen preset and return telemetry."""
    out.parent.mkdir(parents=True, exist_ok=True)
    in_lufs, _ = measure_program_stats(inp)
    use_debreath = (preset == "podcast-warm") if debreath is None else bool(debreath)
    debreath_stats: dict[str, Any] | None = None

    if preset == "raw":
        if use_debreath:
            with tempfile.TemporaryDirectory() as td:
                raw_wav = Path(td) / "raw.wav"
                run([
                    "ffmpeg", "-y", "-loglevel", "error", "-i", str(inp),
                    "-vn", "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", "-bitexact", str(raw_wav),
                ])
                debreath_stats = _debreath.debreath_wav(raw_wav, out)
        else:
            run([
                "ffmpeg", "-y", "-loglevel", "error", "-i", str(inp),
                "-vn", "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", "-bitexact", str(out),
            ])
        out_lufs, out_tp = measure_program_stats(out)
        res: dict[str, Any] = {
            "preset": "raw",
            "raw": True,
            "debreath": use_debreath,
            "input_lufs": round(in_lufs, 2),
            "output_lufs": round(out_lufs, 2),
            "true_peak_dbtp": round(out_tp, 2),
            "output": str(out),
        }
        if debreath_stats is not None:
            res["debreath_valleys"] = debreath_stats["valleys_cleaned"]
            res["debreath_speech_delta_db"] = debreath_stats["max_speech_delta_db"]
        return res

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        if preset == "podcast-warm":
            if use_debreath:
                raw_48k = tmp / "raw_48k.wav"
                run([
                    "ffmpeg", "-y", "-loglevel", "error", "-i", str(inp), "-vn",
                    "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", "-bitexact", str(raw_48k),
                ])
                shaped = tmp / "shaped.wav"
                run([
                    "ffmpeg", "-y", "-loglevel", "error", "-i", str(raw_48k),
                    "-filter_complex", PODCAST_WARM_FILTER, "-map", "[out]",
                    "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", "-bitexact", str(shaped),
                ])
                normed = tmp / "normed.wav"
                _two_pass_loudnorm(shaped, normed, target_lufs=target_lufs, tp=-1.5, lra=9.0)
                debreathed = tmp / "debreathed.wav"
                debreath_stats = _debreath.debreath_wav(normed, debreathed, mask_wav=raw_48k)
                run([
                    "ffmpeg", "-y", "-loglevel", "error", "-i", str(debreathed),
                    "-c:a", "copy", "-metadata", "comment=video-craft:podcast-warm", "-bitexact", str(out),
                ])
            else:
                shaped = tmp / "shaped.wav"
                run([
                    "ffmpeg", "-y", "-loglevel", "error", "-i", str(inp), "-vn",
                    "-filter_complex", PODCAST_WARM_FILTER, "-map", "[out]",
                    "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", "-bitexact", str(shaped),
                ])
                _two_pass_loudnorm(shaped, out, target_lufs=target_lufs, tp=-1.5, lra=9.0,
                                   comment_tag="video-craft:podcast-warm")
        elif preset == "gentle":
            wav = tmp / "in.wav"
            run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(inp), "-vn", "-ac", "1", "-bitexact", str(wav)])
            proc = tmp / "proc.wav"
            apply_chain(wav, proc, deess)
            if use_debreath:
                normed = tmp / "normed.wav"
                normalize_static(proc, normed, target_lufs)
                debreathed = tmp / "debreathed.wav"
                debreath_stats = _debreath.debreath_wav(normed, debreathed, mask_wav=wav)
                run([
                    "ffmpeg", "-y", "-loglevel", "error", "-i", str(debreathed),
                    "-c:a", "copy", "-metadata", "comment=video-craft:gentle", "-bitexact", str(out),
                ])
            else:
                normalize_static(proc, out, target_lufs, comment_tag="video-craft:gentle")
        else:
            raise ValueError(f"unknown preset: {preset}")

    out_lufs, out_tp = measure_program_stats(out)
    res = {
        "preset": preset,
        "raw": False,
        "debreath": use_debreath,
        "input_lufs": round(in_lufs, 2),
        "output_lufs": round(out_lufs, 2),
        "true_peak_dbtp": round(out_tp, 2),
        "output": str(out),
    }
    if debreath_stats is not None:
        res["debreath_valleys"] = debreath_stats["valleys_cleaned"]
        res["debreath_speech_delta_db"] = debreath_stats["max_speech_delta_db"]
    return res


def make_ab(
    inp: Path,
    ab_out: Path,
    start: float,
    dur: float,
    target_lufs: float,
    deess: bool,
    preset: str = "podcast-warm",
    debreath: bool | None = None,
    quiet: bool = False,
) -> dict[str, Any]:
    effective = "podcast-warm" if preset in ("raw", "none") else preset
    use_debreath = (effective == "podcast-warm") if debreath is None else bool(debreath)
    ab_out.mkdir(parents=True, exist_ok=True)
    raw_out = ab_out / f"{inp.stem}-原始-{int(dur)}s.wav"
    proc_out = ab_out / f"{inp.stem}-处理-{int(dur)}s.wav"
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        orig_n = tmp / "orig_n.wav"
        proc_full = tmp / "proc_full.wav"
        _two_pass_loudnorm(inp, orig_n, target_lufs=target_lufs)
        stats = apply_voice_preset(
            inp, proc_full, preset=effective, target_lufs=target_lufs, deess=deess, debreath=use_debreath,
        )
        for src, dst in [(orig_n, raw_out), (proc_full, proc_out)]:
            run([
                "ffmpeg", "-y", "-loglevel", "error", "-ss", str(start), "-t", str(dur),
                "-i", str(src), "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", "-bitexact",
                str(dst),
            ])
    if not quiet:
        print(f"A/B ({effective}, debreath={use_debreath}) -> {ab_out}/ (loudness-matched {target_lufs} LUFS)")
    return {
        "mode": "ab",
        "voice_preset": effective,
        "debreath": bool(stats["debreath"]),
        "start": start,
        "duration": dur,
        "target_lufs": target_lufs,
        "ab_dir": str(ab_out),
        "raw_output": str(raw_out),
        "processed_output": str(proc_out),
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Standalone voice acoustic diagnosis & short A/B auditioning (--ab; default C-preset "
            "'podcast-warm' with pause de-breathing). For final project mixing, pass the raw cut track directly to "
            "helpers/audio_mix.py (which applies podcast-warm by default) instead of compressing "
            "twice; if passing an audio_fix.py output into audio_mix.py, pass --voice-preset none."
        )
    )
    ap.add_argument("input", type=Path)
    ap.add_argument("-o", "--output", type=Path, default=None, help="Processed wav output")
    ap.add_argument("--preset", "--voice-preset", dest="preset", choices=("podcast-warm", "gentle", "raw"),
                    default="podcast-warm",
                    help="Voice acoustic preset (default: podcast-warm; raw skips EQ/de-ess/comp/loudnorm)")
    ap.add_argument("--raw", "--raw-voice", dest="raw", action="store_true",
                    help="Bypass all EQ, compression, and loudnorm (--preset raw)")
    db_group = ap.add_mutually_exclusive_group()
    db_group.add_argument("--debreath", dest="debreath", action="store_const", const=True, default=None,
                          help="Attenuate >=140ms pause breaths to -62 dBFS (default ON for podcast-warm)")
    db_group.add_argument("--no-debreath", dest="debreath", action="store_const", const=False,
                          help="Disable pause de-breathing (useful for A/B comparison)")
    ap.add_argument("--target-lufs", type=float, default=-14.0,
                    help="Integrated loudness target in LUFS (default: -14.0)")
    ap.add_argument("--deess", action="store_true", help="Enable sidechain de-ess for gentle preset")
    ap.add_argument("--ab", type=str, default=None, help="A/B excerpt 'START,DUR' in seconds")
    ap.add_argument("--ab-out", type=Path, default=None, help="A/B output dir (default: input parent)")
    ap.add_argument("--json", action="store_true", help="Print machine-readable JSON result")
    args = ap.parse_args()

    inp = args.input.resolve()
    if not inp.exists():
        sys.exit(f"input not found: {inp}")

    preset = "raw" if args.raw else args.preset

    if args.ab:
        start, dur = (float(v) for v in args.ab.split(","))
        ab_out = (args.ab_out or inp.parent).resolve()
        ab_info = make_ab(
            inp, ab_out, start, dur, args.target_lufs, args.deess,
            preset=preset, debreath=args.debreath, quiet=args.json,
        )
        if args.json:
            print(json.dumps(ab_info, ensure_ascii=False, indent=2))
        return 0

    if not args.output:
        sys.exit("need -o out.wav (or --ab for an A/B sample)")
    out = args.output.resolve()
    stats = apply_voice_preset(
        inp, out, preset=preset, target_lufs=args.target_lufs, deess=args.deess, debreath=args.debreath,
    )
    if args.json:
        print(json.dumps(stats, ensure_ascii=False, indent=2))
    else:
        print(f"processed ({stats['preset']}) -> {out}  ({stats['output_lufs']} LUFS, peak {stats['true_peak_dbtp']} dBTP)")
        if not stats["raw"] and float(stats["true_peak_dbtp"]) > -1.0:
            print("  ⚠ peak above -1dBTP — audio may clip on playback; reduce --target-lufs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
