#!/usr/bin/env python3
"""Pre-delivery A/V verification for rendered videos.

Catches the failure classes that are silent by ear/eye:
  - per-segment AAC drift / loudnorm tail trim → track-duration mismatch + tail energy
  - wrong multi-camera offset            → pair correlation not peaking at ~0
  - stale preview / truncated segment    → duration guard already fails earlier

Exit code 0 = all checks passed, 1 = any check failed (--pair also exits 1
when the best lag is farther than 0.5s from 0).

Usage:
    python helpers/verify_av.py --tracks a.mp4 b.mp4        # V/A stream delta ≤ 0.05s
    python helpers/verify_av.py --tails  a.mp4              # last-loud window + silent-tail warning
    python helpers/verify_av.py --pair face.mp4 base.mp4    # envelope xcorr: expect lag ≈ 0, corr ≥ 0.5
    python helpers/verify_av.py --all   a.mp4 b.mp4         # tracks + tails
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np


def stream_duration(path: Path, stream: str) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", stream,
         "-show_entries", "stream=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True).stdout.strip()
    return float(out)


def check_tracks(path: Path) -> bool:
    v = stream_duration(path, "v:0")
    a = stream_duration(path, "a:0")
    delta = v - a
    ok = abs(delta) <= 0.05
    print(f"  {path.name}: V={v:.3f} A={a:.3f} delta={delta:+.3f}s {'OK' if ok else 'FAIL (tracks drift)'}")
    return ok


def check_tail(path: Path) -> bool:
    """Informational — a silent tail can be legitimate (wait segment, soft
    outro words). Prints the last-loud window; the loudnorm tail-trim symptom
    is a silent FINAL 0.5s, so it prints a warning but never fails the gate."""
    dur = stream_duration(path, "v:0")
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-ss", f"{max(0.0, dur - 1.5):.3f}",
         "-i", str(path), "-ac", "1", "-ar", "8000", "-bitexact", "/tmp/verify_tail.wav"],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    w = wave.open("/tmp/verify_tail.wav")
    a = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(float)
    n = len(a) // 800
    e = np.abs(a[: n * 800].reshape(-1, 800)).max(axis=1)
    last_loud = None
    for i in range(n - 1, -1, -1):
        if e[i] > 400:
            last_loud = max(0.0, dur - 1.5) + i * 0.1
            break
    tail_silent = last_loud is None or (dur - last_loud) > 0.5
    print(f"  {path.name}: dur={dur:.2f}s last loud at {last_loud if last_loud is not None else 'NONE'}"
          f" — {'OK' if not tail_silent else 'WARNING: tail may be silent/trimmed (check the final word)'}")
    return True


def check_pair(face: Path, base: Path) -> bool:
    """Envelope xcorr of the two renders — the same event must land at the
    same output time (lag ≈ 0). A wrong mirror offset shows up as a large lag."""
    envs: dict[Path, np.ndarray] = {}
    for p in (face, base):
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-i", str(p), "-ac", "1", "-ar", "16000",
             "-bitexact", "/tmp/verify_pair.wav"],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        w = wave.open("/tmp/verify_pair.wav")
        a = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(float)
        n = len(a) // 160
        envs[p] = np.abs(a[: n * 160].reshape(-1, 160)).mean(axis=1)
    be, fe = envs[base], envs[face]
    n = min(len(be), len(fe))
    best, bl = -1e18, 0
    for lag in range(-100, 101):
        if lag < 0:
            x, y = be[:lag], fe[-lag:]
        elif lag > 0:
            x, y = be[lag:], fe[:-lag]
        else:
            x, y = be[:n], fe[:n]
        m = min(len(x), len(y))
        c = np.corrcoef(x[:m], y[:m])[0, 1]
        if c > best:
            best, bl = c, lag
    lag_s = bl * 0.01
    ok = best >= 0.5 and abs(lag_s) <= 0.5
    print(f"  {face.name} vs {base.name}: corr {best:.3f} at lag {lag_s:+.2f}s "
          f"{'OK' if ok else 'FAIL (content misaligned — wrong mirror offset?)'}")
    return ok


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tracks", nargs="+", type=Path, help="check V/A track deltas")
    ap.add_argument("--tails", nargs="+", type=Path, help="check tail audio energy")
    ap.add_argument("--pair", nargs=2, metavar=("FACE", "BASE"), type=Path,
                    help="envelope xcorr between two renders (expect lag ≈ 0)")
    ap.add_argument("--all", nargs="+", type=Path, help="tracks + tails for each")
    args = ap.parse_args()

    ok = True
    if args.tracks:
        print("== track alignment ==")
        for p in args.tracks:
            ok = check_tracks(p) and ok
    if args.tails:
        print("== tail audio ==")
        for p in args.tails:
            ok = check_tail(p) and ok
    if args.pair:
        print("== pair alignment ==")
        ok = check_pair(args.pair[0], args.pair[1]) and ok
    if args.all:
        print("== tracks + tails ==")
        for p in args.all:
            ok = check_tracks(p) and ok
        for p in args.all:
            ok = check_tail(p) and ok

    print("\n" + ("ALL CHECKS PASSED" if ok else "CHECKS FAILED — see above"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
