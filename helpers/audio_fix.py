"""Apply the diagnosed voice fix chain and produce A/B samples at matched loudness.

The chain implements the proven "gentle" preset (from the 2026-08 种草大赏
session): highpass 80Hz, 250Hz -2dB, 3.2kHz +1.5dB wide-Q, static gain to a
target LUFS, NO limiter (static gain sized so the peak stays under -1 dBTP —
a limiter was found to add audible distortion on phone recordings).

Known failure modes (documented in the session log):
  - ffmpeg's built-in deesser produces artifact "electric" sounds -> not used
    by default; --deess enables a sidechain-compressor de-ess instead
  - static EQ cuts on sibilance dull the voice; transients need dynamic
    treatment, hence --deess over a 5-8k cut

Usage:
    python helpers/audio_fix.py in.wav -o out.wav
    python helpers/audio_fix.py in.wav -o out.wav --target-lufs -14
    python helpers/audio_fix.py in.wav -o out.wav --deess
    python helpers/audio_fix.py in.wav --ab 15,30 --ab-out /dir   # A/B excerpts, loudness-matched
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

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


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def measure_lufs(path: Path) -> float:
    out = subprocess.run(
        ["ffmpeg", "-nostats", "-i", str(path), "-filter_complex", "ebur128",
         "-f", "null", "-bitexact", "-"],
        capture_output=True, text=True).stderr
    for line in out.splitlines():
        # summary line only: `I:         -16.8 LUFS` at line start (the
        # per-second `t: ... I: -70.0 LUFS` lines start with the filter name)
        m = re.match(r"\s*I:\s*(-?[\d.]+)\s+LUFS", line)
        if m:
            return float(m.group(1))
    sys.exit(f"could not measure loudness of {path}")


def measure_peak(path: Path) -> float:
    out = subprocess.run(
        ["ffmpeg", "-nostats", "-i", str(path), "-af", "volumedetect",
         "-f", "null", "-bitexact", "-"],
        capture_output=True, text=True).stderr
    for line in out.splitlines():
        m = re.search(r"max_volume:\s*(-?[\d.]+)\s+dB", line)
        if m:
            return float(m.group(1))
    sys.exit(f"could not measure peak of {path}")


def apply_chain(inp: Path, out: Path, deess: bool) -> None:
    chain = GENTLE_EQ
    if deess:
        chain += f",{DEESS}"
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(inp), "-af", chain,
         "-bitexact", str(out)])


def normalize_static(inp: Path, out: Path, target_lufs: float) -> tuple[float, float]:
    """Static gain to target LUFS without a limiter; returns (gain_db, final_peak_db)."""
    lu = measure_lufs(inp)
    gain = target_lufs - lu
    peak = measure_peak(inp)
    final_peak = peak + gain
    if final_peak > -1.0:
        # back off so no peak clips; loudness lands slightly below target
        gain -= (final_peak + 1.0)
        final_peak = -1.0
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(inp), "-af",
         f"volume={gain:.2f}dB", "-bitexact", str(out)])
    return round(gain, 2), round(final_peak, 1)


def make_ab(inp: Path, ab_out: Path, start: float, dur: float, target_lufs: float, deess: bool) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        orig = tmp / "orig.wav"
        proc = tmp / "proc.wav"
        run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(inp), "-vn", "-ac", "1",
             "-bitexact", str(orig)])
        apply_chain(orig, proc, deess)
        o_g, o_p = normalize_static(orig, tmp / "orig_n.wav", target_lufs)
        p_g, p_p = normalize_static(proc, tmp / "proc_n.wav", target_lufs)
        for src, name in [(tmp / "orig_n.wav", "原始"), (tmp / "proc_n.wav", "处理")]:
            run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(start), "-t", str(dur),
                 "-i", str(src), "-bitexact",
                 str(ab_out / f"{inp.stem}-{name}-{int(dur)}s.wav")])
        print(f"A/B -> {ab_out}/  ({o_g}dB / {p_g}dB gain, peak {o_p}dB / {p_p}dB, "
              f"loudness-matched {target_lufs} LUFS)")


def main() -> None:
    ap = argparse.ArgumentParser(description="Voice fix chain + loudness-matched A/B")
    ap.add_argument("input", type=Path)
    ap.add_argument("-o", "--output", type=Path, default=None, help="Processed wav output")
    ap.add_argument("--target-lufs", type=float, default=-16.5, help="Material-preprocessing loudness target (default -16.5). The delivery standard is render.py's -14 LUFS normalisation; do not treat this number as the film standard.")
    ap.add_argument("--deess", action="store_true", help="Add sidechain de-ess (5-8k transients)")
    ap.add_argument("--ab", type=str, default=None, help="A/B excerpt 'START,DUR' in seconds")
    ap.add_argument("--ab-out", type=Path, default=None, help="A/B output dir (default: input parent)")
    args = ap.parse_args()

    inp = args.input.resolve()
    if not inp.exists():
        sys.exit(f"input not found: {inp}")

    if args.ab:
        start, dur = (float(v) for v in args.ab.split(","))
        ab_out = (args.ab_out or inp.parent).resolve()
        ab_out.mkdir(parents=True, exist_ok=True)
        make_ab(inp, ab_out, start, dur, args.target_lufs, args.deess)
        return

    if not args.output:
        sys.exit("need -o out.wav (or --ab for an A/B sample)")
    out = args.output.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        wav = tmp / "in.wav"
        run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(inp), "-vn", "-ac", "1",
             "-bitexact", str(wav)])
        proc = tmp / "proc.wav"
        apply_chain(wav, proc, args.deess)
        gain, peak = normalize_static(proc, out, args.target_lufs)
        print(f"processed -> {out}  (gain {gain}dB, peak {peak}dB, target {args.target_lufs} LUFS)")
        if peak > -1.0:
            print("  ⚠ peak above -1dBTP — audio may clip on playback; reduce --target-lufs")


if __name__ == "__main__":
    main()
