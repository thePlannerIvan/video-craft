#!/usr/bin/env python3
"""Open-source portable Remotion External Runtime Shell manager.

Keeps all Remotion / React / esbuild / TypeScript / headless browser dependencies
in a single shared directory outside cloud-synced workspaces and video projects:

  1. `$VIDEO_CRAFT_REMOTION_HOME` (if set)
  2. `<XDG_CACHE_HOME or ~/.cache>/video-craft/remotion-runtime/`

Never hardcodes developer machine paths or regional npm registries. Respects
the user's existing npm configuration and environment variables.

Interface
---------
    python3 helpers/remotion_runtime.py setup [--runtime-home PATH] [--skip-browser] [--force] [--json]
    python3 helpers/remotion_runtime.py doctor [--runtime-home PATH] [--json]
    python3 helpers/remotion_runtime.py path [--runtime-home PATH]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ENV_HOME_VAR = "VIDEO_CRAFT_REMOTION_HOME"
RUNTIME_STATE_FILE = ".runtime-state.json"
RUNTIME_SCHEMA = "video-craft/remotion-runtime/1"
MIN_NODE_MAJOR = 22
REMOTION_VERSION = "4.0.547"

RUNTIME_DEPS: dict[str, str] = {
    "remotion": REMOTION_VERSION,
    "@remotion/cli": REMOTION_VERSION,
    "@remotion/player": REMOTION_VERSION,
    "@remotion/media-utils": REMOTION_VERSION,
    "@remotion/paths": REMOTION_VERSION,
    "@remotion/noise": REMOTION_VERSION,
    "@remotion/transitions": REMOTION_VERSION,
    "esbuild": "^0.25.0",
    "lucide-react": "^1.81.0",
    "react": "18.3.1",
    "react-dom": "18.3.1",
    "typescript": "5.7.2",
    "@types/react": "18.3.12",
    "@types/react-dom": "18.3.6",
}

REQUIRED_PACKAGES: tuple[str, ...] = tuple(RUNTIME_DEPS.keys())
REQUIRED_BINS: tuple[str, ...] = ("remotion", "tsc")
FIX_COMMAND = "python3 helpers/remotion_runtime.py setup"


def resolve_runtime_home(explicit: str | Path | None = None) -> Path:
    """Resolve the shared External Runtime Shell directory cleanly."""
    if explicit is not None and str(explicit).strip():
        return Path(explicit).expanduser().resolve()
    env_home = os.environ.get(ENV_HOME_VAR, "").strip()
    if env_home:
        return Path(env_home).expanduser().resolve()
    xdg = os.environ.get("XDG_CACHE_HOME", "").strip()
    cache_root = Path(xdg).expanduser() if xdg else (Path.home() / ".cache")
    return (cache_root / "video-craft" / "remotion-runtime").resolve()


def _bin_name(name: str) -> str:
    return f"{name}.cmd" if os.name == "nt" else name


def bin_path(name: str, runtime_home: Path | None = None) -> Path:
    home = resolve_runtime_home(runtime_home)
    return home / "node_modules" / ".bin" / _bin_name(name)


def runtime_env(runtime_home: Path | None = None, base_env: dict[str, str] | None = None) -> dict[str, str]:
    """Return environment with external runtime binaries and NODE_PATH prepended."""
    home = resolve_runtime_home(runtime_home)
    env = dict(os.environ if base_env is None else base_env)
    bin_dir = str(home / "node_modules" / ".bin")
    nm_dir = str(home / "node_modules")
    old_path = env.get("PATH", "")
    env["PATH"] = f"{bin_dir}{os.pathsep}{old_path}" if old_path else bin_dir
    old_node_path = env.get("NODE_PATH", "")
    env["NODE_PATH"] = f"{nm_dir}{os.pathsep}{old_node_path}" if old_node_path else nm_dir
    return env


def _probe_node() -> tuple[bool, int | None, str]:
    node_bin = shutil.which("node")
    if not node_bin:
        return False, None, "node not found on PATH (Node >= 22 required)"
    try:
        out = subprocess.run([node_bin, "--version"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, None, f"node failed to execute: {exc}"
    ver = (out.stdout or "").strip()
    m = re.match(r"^v?(\d+)\.", ver)
    if not m:
        return False, None, f"unrecognized node version: {ver!r}"
    major = int(m.group(1))
    if major < MIN_NODE_MAJOR:
        return False, major, f"node {ver} < v{MIN_NODE_MAJOR} (Node >= {MIN_NODE_MAJOR} required)"
    return True, major, f"{ver} ({node_bin})"


def _probe_ffmpeg() -> tuple[bool, str]:
    ff = shutil.which("ffmpeg")
    fp = shutil.which("ffprobe")
    if not ff or not fp:
        missing = [n for n, p in (("ffmpeg", ff), ("ffprobe", fp)) if not p]
        return False, f"missing on PATH: {', '.join(missing)}"
    return True, f"ffmpeg={ff}, ffprobe={fp}"


def _missing_packages(home: Path) -> list[str]:
    nm = home / "node_modules"
    missing: list[str] = []
    for pkg in REQUIRED_PACKAGES:
        pkg_json = nm.joinpath(*pkg.split("/"), "package.json")
        if not pkg_json.is_file():
            missing.append(pkg)
    for b in REQUIRED_BINS:
        if not bin_path(b, home).exists():
            missing.append(f".bin/{b}")
    return missing


def _find_remotion_browser(home: Path) -> Path | None:
    """Detect Remotion-managed chrome-headless-shell inside the runtime shell."""
    dot_remotion = home / "node_modules" / ".remotion"
    if dot_remotion.is_dir():
        for name in ("chrome-headless-shell", "chrome-headless-shell.exe", "chrome", "Chromium"):
            for cand in dot_remotion.rglob(name):
                if cand.is_file():
                    return cand.resolve()
    state_file = home / RUNTIME_STATE_FILE
    if state_file.is_file():
        try:
            doc = json.loads(state_file.read_text(encoding="utf-8"))
            if (
                doc.get("browserEnsured") is True
                and doc.get("browserPath")
                and doc.get("browserSource") in (None, "remotion-managed")
            ):
                p = Path(str(doc["browserPath"]))
                if p.is_file() and (dot_remotion in p.resolve().parents or doc.get("browserSource") == "remotion-managed"):
                    return p.resolve()
        except (OSError, ValueError):
            pass
    return None


def _find_system_chrome() -> Path | None:
    """Locate a standard OS Chrome/Chromium executable without hardcoded personal paths."""
    candidates: list[Path] = [
        Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
    ]
    for cmd_name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        found = shutil.which(cmd_name)
        if found:
            candidates.append(Path(found))
    for env_var in ("ProgramFiles", "ProgramFiles(x86)", "LocalAppData"):
        base = os.environ.get(env_var, "").strip()
        if base:
            candidates.append(Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe")
            candidates.append(Path(base) / "Chromium" / "Application" / "chrome.exe")
    for cand in candidates:
        try:
            if cand.is_file():
                return cand.resolve()
        except OSError:
            continue
    return None


def resolve_browser_executable(runtime_home: Path | None = None) -> tuple[Path | None, str]:
    """Resolve browser executable with portable priority: env -> remotion-managed -> system-chrome."""
    env_raw = os.environ.get("REMOTION_BROWSER_EXECUTABLE", "").strip()
    if env_raw:
        env_path = Path(env_raw).expanduser()
        if env_path.is_file():
            return env_path.resolve(), "env"

    home = resolve_runtime_home(runtime_home)
    managed = _find_remotion_browser(home)
    if managed is not None:
        return managed, "remotion-managed"

    system_chrome = _find_system_chrome()
    if system_chrome is not None:
        return system_chrome, "system-chrome"

    return None, "missing"


def inspect_runtime(runtime_home: Path | None = None) -> dict:
    """Inspect Node, ffmpeg/ffprobe, External Runtime Shell packages, and browser."""
    home = resolve_runtime_home(runtime_home)
    node_ok, node_major, node_detail = _probe_node()
    ffmpeg_ok, ffmpeg_detail = _probe_ffmpeg()
    missing_pkgs = _missing_packages(home)
    packages_ok = not missing_pkgs
    browser_bin, browser_source = resolve_browser_executable(home)
    browser_ok = browser_bin is not None

    checks = [
        {"name": "node", "ok": node_ok, "detail": node_detail},
        {"name": "ffmpeg", "ok": ffmpeg_ok, "detail": ffmpeg_detail},
        {
            "name": "runtime_packages",
            "ok": packages_ok,
            "detail": (
                f"{len(REQUIRED_PACKAGES)} packages ready at {home}"
                if packages_ok
                else f"missing at {home}: {', '.join(missing_pkgs[:6])}"
                + ("..." if len(missing_pkgs) > 6 else "")
            ),
        },
        {
            "name": "headless_browser",
            "ok": browser_ok,
            "detail": f"{browser_bin} ({browser_source})" if browser_bin else "headless browser not ensured",
        },
    ]
    ok = all(c["ok"] for c in checks)
    fix_commands: list[str] = []
    if not node_ok:
        fix_commands.append("install Node.js >= 22")
    if not ffmpeg_ok:
        fix_commands.append("install ffmpeg and ffprobe onto PATH")
    if not packages_ok or not browser_ok:
        fix_commands.append(FIX_COMMAND)
    return {
        "ok": ok,
        "runtimeHome": str(home),
        "nodeMajor": node_major,
        "missingPackages": missing_pkgs,
        "browserPath": str(browser_bin) if browser_bin else None,
        "browserSource": browser_source,
        "checks": checks,
        "fixCommand": FIX_COMMAND if (not packages_ok or not browser_ok) else None,
        "fixCommands": fix_commands,
    }


def _desired_package_json() -> dict:
    return {
        "name": "video-craft-remotion-runtime",
        "version": "3.0.0",
        "private": True,
        "description": "Shared External Runtime Shell dependencies for video-craft Remotion compositions",
        "dependencies": dict(RUNTIME_DEPS),
    }


def _packages_up_to_date(home: Path) -> bool:
    if _missing_packages(home):
        return False
    state_file = home / RUNTIME_STATE_FILE
    if not state_file.is_file():
        return False
    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return (
        isinstance(state, dict)
        and state.get("schema") == RUNTIME_SCHEMA
        and state.get("dependencies") == RUNTIME_DEPS
    )


def setup_runtime(
    runtime_home: Path | None = None,
    *,
    skip_browser: bool = False,
    force: bool = False,
    download_browser: bool = False,
) -> dict:
    """Idempotently provision the External Runtime Shell and resolve/ensure a browser."""
    home = resolve_runtime_home(runtime_home)
    node_ok, _major, node_detail = _probe_node()
    if not node_ok:
        return {
            "ok": False,
            "runtimeHome": str(home),
            "error": node_detail,
            "fixCommand": "install Node.js >= 22",
        }

    npm_bin = shutil.which("npm")
    if not npm_bin:
        return {
            "ok": False,
            "runtimeHome": str(home),
            "error": "npm not found on PATH",
            "fixCommand": "install Node.js / npm >= 22",
        }

    home.mkdir(parents=True, exist_ok=True)
    pkg_path = home / "package.json"
    pkg_payload = json.dumps(_desired_package_json(), ensure_ascii=False, indent=2) + "\n"
    if not pkg_path.is_file() or pkg_path.read_text(encoding="utf-8") != pkg_payload or force:
        pkg_path.write_text(pkg_payload, encoding="utf-8")

    installed_now = False
    if force or not _packages_up_to_date(home):
        proc = subprocess.run(
            [npm_bin, "install", "--no-audit", "--no-fund"],
            cwd=str(home),
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            return {
                "ok": False,
                "runtimeHome": str(home),
                "step": "npm install",
                "error": ((proc.stderr or proc.stdout or "npm install failed")[-1200:]).strip(),
                "fixCommand": FIX_COMMAND,
            }
        installed_now = True

    browser_ensured = False
    browser_bin, browser_source = resolve_browser_executable(home)
    if not skip_browser:
        remotion_bin = bin_path("remotion", home)
        if not remotion_bin.exists():
            return {
                "ok": False,
                "runtimeHome": str(home),
                "step": "remotion browser ensure",
                "error": f"remotion CLI binary missing at {remotion_bin}",
                "fixCommand": f"{FIX_COMMAND} --force",
            }
        should_download = (browser_bin is None) or download_browser or force
        if should_download:
            bproc = subprocess.run(
                [str(remotion_bin), "browser", "ensure"],
                cwd=str(home),
                env=runtime_env(home),
                capture_output=True,
                text=True,
            )
            if bproc.returncode != 0:
                fallback_bin, fallback_source = resolve_browser_executable(home)
                if fallback_bin is not None:
                    browser_bin, browser_source = fallback_bin, fallback_source
                else:
                    return {
                        "ok": False,
                        "runtimeHome": str(home),
                        "step": "remotion browser ensure",
                        "error": ((bproc.stderr or bproc.stdout or "remotion browser ensure failed")[-1200:]).strip(),
                        "fixCommand": FIX_COMMAND,
                    }
            else:
                browser_bin, browser_source = resolve_browser_executable(home)
        browser_ensured = browser_bin is not None

    state = {
        "schema": RUNTIME_SCHEMA,
        "updatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "remotionVersion": REMOTION_VERSION,
        "dependencies": dict(RUNTIME_DEPS),
        "browserEnsured": browser_ensured or (browser_bin is not None),
        "browserPath": str(browser_bin) if browser_bin else None,
        "browserSource": browser_source,
    }
    (home / RUNTIME_STATE_FILE).write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    report = inspect_runtime(home)
    report["installedNow"] = installed_now
    report["skippedBrowser"] = skip_browser
    return report


def ensure_runtime(runtime_home: Path | None = None, *, auto_setup: bool = True, skip_browser: bool = False) -> Path:
    """Return ready runtime home; lazily triggers setup on first motion run if allowed."""
    home = resolve_runtime_home(runtime_home)
    missing = _missing_packages(home)
    browser_bin, _ = resolve_browser_executable(home)
    need_browser = not skip_browser and browser_bin is None
    if not missing and not need_browser:
        return home
    if not auto_setup:
        raise RuntimeError(f"Remotion External Runtime Shell not ready at {home}; run: {FIX_COMMAND}")
    res = setup_runtime(home, skip_browser=skip_browser)
    if not res.get("ok"):
        raise RuntimeError(
            f"Remotion External Runtime Shell setup failed at {home}: "
            f"{res.get('error') or res.get('checks')} — run: {FIX_COMMAND}"
        )
    return home


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="remotion_runtime.py",
        description="Manage the portable Remotion External Runtime Shell outside workspaces.",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_path = sub.add_parser("path", help="Print resolved External Runtime Shell path")
    p_path.add_argument("--runtime-home", default=None, help=f"Override ${ENV_HOME_VAR}")

    p_setup = sub.add_parser("setup", help="Install pinned Remotion packages and ensure browser")
    p_setup.add_argument("--runtime-home", default=None, help=f"Override ${ENV_HOME_VAR}")
    p_setup.add_argument("--skip-browser", action="store_true", help="Skip browser resolution/download")
    p_setup.add_argument("--download-browser", action="store_true", help="Force `remotion browser ensure` download")
    p_setup.add_argument("--force", action="store_true", help="Re-run npm install & browser ensure")
    p_setup.add_argument("--json", action="store_true", help="Emit JSON output")

    p_doc = sub.add_parser("doctor", help="Inspect Node, ffmpeg, External Runtime Shell & browser readiness")
    p_doc.add_argument("--runtime-home", default=None, help=f"Override ${ENV_HOME_VAR}")
    p_doc.add_argument("--json", action="store_true", help="Emit JSON output")

    args = ap.parse_args(argv)
    if args.cmd == "path":
        print(resolve_runtime_home(args.runtime_home))
        return 0

    if args.cmd == "setup":
        report = setup_runtime(
            args.runtime_home,
            skip_browser=args.skip_browser,
            force=args.force,
            download_browser=args.download_browser,
        )
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        elif report.get("ok"):
            print(f"✓ Remotion External Runtime Shell ready → {report['runtimeHome']}")
        else:
            print(f"✗ Setup failed: {report.get('error')}", file=sys.stderr)
            if report.get("fixCommand"):
                print(f"  fix: {report['fixCommand']}", file=sys.stderr)
        return 0 if report.get("ok") else 1

    report = inspect_runtime(args.runtime_home)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"Remotion External Runtime Shell · {report['runtimeHome']}")
        for c in report["checks"]:
            mark = "✓" if c["ok"] else "✗"
            print(f"  {mark} {c['name']}: {c['detail']}")
        if not report["ok"] and report.get("fixCommand"):
            print(f"\nFix: {report['fixCommand']}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
