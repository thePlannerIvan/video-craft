#!/usr/bin/env python3
"""Pre-render check for the HyperFrames visual layer.

One failure this exists for, measured: in a restricted sandbox (or anywhere the
home directory is read-only) `hyperframes render` dies partway through with

    EPERM: operation not permitted, mkdir '<home>/.cache/hyperframes/fonts/noto-serif-sc'
    Try --docker for containerized rendering

`--docker` is the only thing the error suggests and it needs Docker; the way out
is `HYPERFRAMES_FONT_CACHE_DIR`, which moves the font cache to a writable
directory. It is one of 50-odd `HYPERFRAMES_*` variables in the packaged code and
appears in no help text. `hyperframes doctor` does **not** cover it either — its
nine checks are version / node / memory / disk / frames cache / ffmpeg / whisper
/ TTS / BGM.

Run this before the first render of a project, from the composition directory.
Exit 0 means the environment can render; non-zero names what to set.

Usage:
    python3 helpers/check_render_env.py [composition_dir]
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

FONT_CACHE_VAR = "HYPERFRAMES_FONT_CACHE_DIR"
MIN_NODE_MAJOR = 22


def font_cache_candidates(env: dict | None = None) -> list:
    """Where HyperFrames will try to put downloaded fonts, in its own order."""
    env = env if env is not None else os.environ
    explicit = (env.get(FONT_CACHE_VAR) or "").strip()
    if explicit:
        return [Path(explicit).expanduser()]
    home = Path(env.get("HOME") or Path.home())
    cache_root = Path(env.get("XDG_CACHE_HOME") or (home / ".cache"))
    return [cache_root / "hyperframes", home / "Library" / "Caches" / "hyperframes"]


def probe_writable(directory: Path) -> tuple:
    """(ok, message) — actually writes, because a mode bit is not the question."""
    probe = directory / "fonts" / ".video-craft-preflight"
    try:
        probe.parent.mkdir(parents=True, exist_ok=True)
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True, f"{directory} is writable"
    except OSError as exc:
        return False, f"{directory} is not writable ({exc.__class__.__name__}: {exc})"


def node_major() -> int | None:
    if shutil.which("node") is None:
        return None
    try:
        out = subprocess.run(["node", "--version"], capture_output=True, text=True,
                             check=True).stdout.strip()
    except (subprocess.CalledProcessError, OSError):
        return None
    try:
        return int(out.lstrip("v").split(".")[0])
    except ValueError:
        return None


def check(composition: Path | None = None, env: dict | None = None) -> tuple:
    """(exit code, list of lines)."""
    lines: list = []
    failed = False

    candidates = font_cache_candidates(env)
    ok = False
    for directory in candidates:
        writable, message = probe_writable(directory)
        lines.append(("ok   " if writable else "x    ") + f"font cache: {message}")
        if writable:
            ok = True
            break
    if not ok:
        failed = True
        lines.append("")
        lines.append("  hyperframes downloads fonts into that cache and fails with EPERM")
        lines.append("  once rendering has started. Point it somewhere writable:")
        lines.append(f"    export {FONT_CACHE_VAR}=\"$PWD/.hyperframes-cache\"")
        lines.append("  (that variable is not in --help and is not one of the checks")
        lines.append("   `hyperframes doctor` runs, so nothing else will tell you.)")

    major = node_major()
    if major is None:
        failed = True
        lines.append("x    node: not on PATH (the renderer needs Node >= 22)")
    elif major < MIN_NODE_MAJOR:
        failed = True
        lines.append(f"x    node: v{major} is below the required {MIN_NODE_MAJOR}")
    else:
        lines.append(f"ok   node: v{major}")

    if shutil.which("npx") is None:
        failed = True
        lines.append("x    npx: not on PATH")
    else:
        lines.append("ok   npx: on PATH")

    if composition is not None:
        composition = Path(composition)
        index = composition / "index.html"
        if not index.is_file():
            failed = True
            lines.append(f"x    composition: no index.html in {composition}")
            lines.append("     generate it with visual/scripts/generate-composition.py;"
                         " `hyperframes init` would replace it")
        else:
            lines.append(f"ok   composition: {index}")

    return (1 if failed else 0), lines


def main() -> int:
    ap = argparse.ArgumentParser(description="Check the HyperFrames render environment")
    ap.add_argument("composition", nargs="?", type=Path, default=None,
                    help="the composition directory (contains index.html)")
    args = ap.parse_args()
    code, lines = check(args.composition)
    print("\n".join(lines))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
