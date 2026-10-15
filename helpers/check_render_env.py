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

Run this before **every** render of a project, from the composition directory —
not just the first. Exit 0 means the environment can render; non-zero names what
to set or fix.

It also checks the MACHINE, not just the toolchain. `hyperframes render
--workers auto` opens one Chrome per core, and that default is what took a system
down on 2026-10-15 (8 GB RAM, 6 cores, 9394 frames of 1920×1080: auto=6, swap went
to 8.2 GB used, the machine died). So this run also reports RAM, available memory
and swap, and prints the `--workers` value the machine can actually carry. Use it:
a render that crawls is a nuisance, a render that swaps the machine out is an
outage, and only one of those is recoverable.

Usage:
    python3 helpers/check_render_env.py [composition_dir]
    python3 helpers/check_render_env.py [composition_dir] --json   # {ok, workers, memory}
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

FONT_CACHE_VAR = "HYPERFRAMES_FONT_CACHE_DIR"
MIN_NODE_MAJOR = 22

# Memory budget for a full-film render. `hyperframes render --workers auto` opens
# one Chrome per core; each carries decoded frames for the composition's clips.
# Measured 2026-10-15 on an 8 GB / 6-core machine rendering 9394 frames of
# 1920x1080: auto opened 6 Chrome workers, swap went from 1 GB to 8.2 GB used and
# the system went down. So the budget is not a nicety — it is the difference
# between a slow render and a dead machine.
WORKER_RAM_GB = 1.5     # per Chrome render worker, measured headroom
MIN_FREE_GB = 4.0       # below this we do not start a full-film render at all


def _run(cmd: list) -> str | None:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout if out.returncode == 0 else None


def total_ram_gb() -> float | None:
    """Physical RAM, or None when the platform will not say."""
    if sys.platform == "darwin":
        out = _run(["sysctl", "-n", "hw.memsize"])
        if out and out.strip().isdigit():
            return int(out.strip()) / 1024 ** 3
    meminfo = Path("/proc/meminfo")
    if meminfo.is_file():
        for line in meminfo.read_text(errors="replace").splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) / 1024 ** 2
    try:
        return os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") / 1024 ** 3
    except (ValueError, OSError, AttributeError):
        return None


def available_ram_gb() -> float | None:
    """RAM the OS would hand out without evicting much: free + inactive.

    Deliberately reads *available*, not *free*: a machine sitting at 70% used is
    fine to render on, and a machine whose swap is nearly full is not, and only
    the second number tells those apart.
    """
    if sys.platform == "darwin":
        out = _run(["vm_stat"])
        if not out:
            return None
        page = 4096
        match = re.search(r"page size of (\d+) bytes", out)
        if match:
            page = int(match.group(1))
        pages = 0
        for name in ("Pages free", "Pages inactive", "Pages speculative"):
            found = re.search(rf"{name}:\s+(\d+)\.", out)
            if found:
                pages += int(found.group(1))
        return pages * page / 1024 ** 3 if pages else None
    meminfo = Path("/proc/meminfo")
    if meminfo.is_file():
        for line in meminfo.read_text(errors="replace").splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) / 1024 ** 2
    return None


def swap_used_gb() -> tuple:
    """(used, total) in GB, or (None, None) where unavailable.

    Swap already in use is the leading indicator: a render that pushes a machine
    into multi-GB swap has stopped being a render and become an outage.
    """
    if sys.platform == "darwin":
        out = _run(["sysctl", "-n", "vm.swapusage"])
        if not out:
            return (None, None)
        used = re.search(r"used = ([\d.]+)M", out)
        total = re.search(r"total = ([\d.]+)M", out)
        if used and total:
            return (float(used.group(1)) / 1024, float(total.group(1)) / 1024)
        return (None, None)
    meminfo = Path("/proc/meminfo")
    if meminfo.is_file():
        values = {}
        for line in meminfo.read_text(errors="replace").splitlines():
            for key in ("SwapTotal:", "SwapFree:"):
                if line.startswith(key):
                    values[key] = int(line.split()[1])
        if "SwapTotal:" in values and "SwapFree:" in values:
            return ((values["SwapTotal:"] - values["SwapFree:"]) / 1024 ** 2,
                    values["SwapTotal:"] / 1024 ** 2)
    return (None, None)


def suggest_workers(total_gb: float | None, free_gb: float | None,
                    cores: int | None = None) -> int:
    """How many Chrome render workers this machine can actually carry.

    Two ceilings, take the lower: RAM / WORKER_RAM_GB, and (when we can see free
    memory) the free-memory budget. Never zero — one worker is always allowed,
    because a slow correct render beats a fast dead machine, and never more than
    the core count, because past that the workers contend rather than parallelise.
    """
    ceiling = None
    if total_gb:
        ceiling = int(total_gb / WORKER_RAM_GB)
    if free_gb is not None:
        by_free = max(1, int(free_gb / WORKER_RAM_GB))
        ceiling = by_free if ceiling is None else min(ceiling, by_free)
    if ceiling is None:
        ceiling = 1
    if cores:
        ceiling = min(ceiling, cores)
    return max(1, ceiling)


def cpu_count() -> int | None:
    try:
        return os.cpu_count()
    except (NotImplementedError, OSError):
        return None


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


def check(composition: Path | None = None, env: dict | None = None,
          memory: dict | None = None) -> tuple:
    """(exit code, list of lines).

    `memory` injects the machine report so tests do not have to own the host's RAM
    situation; production leaves it None and the probes run.
    """
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

    # ---- memory and worker budget ------------------------------------------
    # The one check here that is about the MACHINE rather than the toolchain, and
    # the only one whose failure has taken a system down rather than a render.
    report = memory_report() if memory is None else memory
    workers, auto = report["suggestedWorkers"], (report["cores"] or 1)
    if report["totalGb"] is None:
        lines.append("ok   memory: unreadable on this platform — pass --workers 1")
    else:
        available = (f", {report['availableGb']:.1f} GB available"
                     if report["availableGb"] is not None else "")
        swap = (f", swap {report['swapUsedGb']:.1f}/{report['swapTotalGb']:.1f} GB"
                if report["swapUsedGb"] is not None else "")
        lines.append(f"ok   memory: {report['totalGb']:.1f} GB total{available}{swap}")
    if report["availableGb"] is not None and report["availableGb"] < MIN_FREE_GB:
        failed = True
        lines.append(f"x    workers: only {report['availableGb']:.1f} GB available, "
                     f"need >= {MIN_FREE_GB:.0f} GB for a full-film render")
        lines.append(f"     `--workers auto` opens one Chrome per core = {auto}, "
                     f"~{WORKER_RAM_GB} GB each.")
        lines.append("     Measured 2026-10-15: 8 GB machine, 9394 frames of 1920x1080,")
        lines.append("     auto=6 -> swap 8.2 GB used -> the system went down.")
        lines.append("     Free memory first, or render a short range with --workers 1.")
    else:
        suffix = f"   (`auto` opens {auto} — one Chrome per core)" if auto > workers else ""
        lines.append(f"ok   workers: pass --workers {workers}{suffix}")

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


def memory_report() -> dict:
    """The structured half of the memory check, for `--json` consumers."""
    total = total_ram_gb()
    free = available_ram_gb()
    swap_used, swap_total = swap_used_gb()
    cores = cpu_count()

    def rounded(value):
        return None if value is None else round(value, 2)

    return {
        "totalGb": rounded(total),
        "availableGb": rounded(free),
        "swapUsedGb": rounded(swap_used),
        "swapTotalGb": rounded(swap_total),
        "cores": cores,
        "suggestedWorkers": suggest_workers(total, free, cores),
        "minFreeGb": MIN_FREE_GB,
        "workerRamGb": WORKER_RAM_GB,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Check the HyperFrames render environment")
    ap.add_argument("composition", nargs="?", type=Path, default=None,
                    help="the composition directory (contains index.html)")
    ap.add_argument("--json", action="store_true",
                    help="emit {ok, workers, memory} for a calling script")
    args = ap.parse_args()
    code, lines = check(args.composition)
    if args.json:
        report = memory_report()
        print(json.dumps({"ok": code == 0, "workers": report["suggestedWorkers"],
                          "memory": report}, ensure_ascii=False, indent=2))
    else:
        print("\n".join(lines))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
