#!/usr/bin/env python3
"""Black-box CLI & hygiene tests for helpers/remotion_runtime.py."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SKILL_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SCRIPT = SKILL_ROOT / "helpers" / "remotion_runtime.py"

sys.path.insert(0, str(SKILL_ROOT / "helpers"))
import remotion_runtime  # noqa: E402


class RemotionRuntimeTests(unittest.TestCase):
    def _run_cli(self, *args: str, env_overrides: dict[str, str] | None = None) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env.pop("VIDEO_CRAFT_REMOTION_HOME", None)
        if env_overrides:
            env.update(env_overrides)
        return subprocess.run(
            [sys.executable, str(RUNTIME_SCRIPT), *args],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_path_resolution_precedence_and_portability(self):
        with tempfile.TemporaryDirectory() as td:
            custom = Path(td) / "custom-shell"
            proc = self._run_cli("path", env_overrides={"VIDEO_CRAFT_REMOTION_HOME": str(custom)})
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(Path(proc.stdout.strip()).resolve(), custom.resolve())

            xdg = Path(td) / "xdg-cache"
            proc2 = self._run_cli("path", env_overrides={"XDG_CACHE_HOME": str(xdg)})
            self.assertEqual(proc2.returncode, 0, proc2.stderr)
            self.assertEqual(
                Path(proc2.stdout.strip()).resolve(),
                (xdg / "video-craft" / "remotion-runtime").resolve(),
            )

    def test_doctor_fails_cleanly_on_empty_runtime_and_prints_single_fix(self):
        with tempfile.TemporaryDirectory() as td:
            empty_shell = Path(td) / "empty-runtime"
            proc = self._run_cli("doctor", "--json", "--runtime-home", str(empty_shell))
            self.assertEqual(proc.returncode, 1, proc.stderr)
            report = json.loads(proc.stdout)
            self.assertFalse(report["ok"])
            self.assertEqual(Path(report["runtimeHome"]).resolve(), empty_shell.resolve())
            self.assertEqual(report["fixCommand"], "python3 helpers/remotion_runtime.py setup")
            self.assertTrue(report["missingPackages"])

    def test_doctor_passes_when_runtime_packages_and_browser_exist(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td) / "ready-runtime"
            nm = home / "node_modules"
            for pkg in remotion_runtime.REQUIRED_PACKAGES:
                pkg_dir = nm.joinpath(*pkg.split("/"))
                pkg_dir.mkdir(parents=True, exist_ok=True)
                (pkg_dir / "package.json").write_text("{\"name\":\"stub\"}\n", encoding="utf-8")
            bin_dir = nm / ".bin"
            bin_dir.mkdir(parents=True, exist_ok=True)
            for b in remotion_runtime.REQUIRED_BINS:
                bp = bin_dir / (f"{b}.cmd" if os.name == "nt" else b)
                bp.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
                bp.chmod(0o755)
            chrome_dir = nm / ".remotion" / "chrome-headless-shell" / "mac-arm64"
            chrome_dir.mkdir(parents=True, exist_ok=True)
            (chrome_dir / "chrome-headless-shell").write_text("#!/bin/sh\n", encoding="utf-8")

            proc = self._run_cli("doctor", "--json", "--runtime-home", str(home))
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            report = json.loads(proc.stdout)
            self.assertTrue(report["ok"], report)
            self.assertEqual(report["missingPackages"], [])
            self.assertIsNone(report["fixCommand"])

            env = remotion_runtime.runtime_env(home)
            self.assertTrue(env["PATH"].startswith(str(bin_dir.resolve())))
            self.assertTrue(env["NODE_PATH"].startswith(str(nm.resolve())))

    def test_no_hardcoded_mirror_or_personal_paths_in_runtime_helper(self):
        src = RUNTIME_SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("npmmirror", src)
        self.assertNotIn("taobao", src)
        self.assertNotIn("dev-cache", src)
        self.assertNotRegex(src, re.compile(r"/Users/[A-Za-z0-9._-]+"))
        for doc_name in ("install.md", "README.md"):
            doc = (SKILL_ROOT / doc_name).read_text(encoding="utf-8")
            self.assertNotIn("dev-cache/CodexProject", doc)
            self.assertNotRegex(doc, re.compile(r"/Users/[A-Za-z0-9._-]+"))

    def test_resolve_browser_executable_env_precedence_and_portable_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td) / "rt-shell"
            nm = home / "node_modules"
            for pkg in remotion_runtime.REQUIRED_PACKAGES:
                pkg_dir = nm.joinpath(*pkg.split("/"))
                pkg_dir.mkdir(parents=True, exist_ok=True)
                (pkg_dir / "package.json").write_text('{"name":"stub"}\n', encoding="utf-8")
            bin_dir = nm / ".bin"
            bin_dir.mkdir(parents=True, exist_ok=True)
            for b in remotion_runtime.REQUIRED_BINS:
                bp = bin_dir / (f"{b}.cmd" if os.name == "nt" else b)
                bp.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
                bp.chmod(0o755)

            managed = nm / ".remotion" / "chrome-headless-shell" / "mac-arm64" / "chrome-headless-shell"
            managed.parent.mkdir(parents=True, exist_ok=True)
            managed.write_text("#!/bin/sh\n", encoding="utf-8")

            env_browser = Path(td) / "custom-browser"
            env_browser.write_text("#!/bin/sh\n", encoding="utf-8")

            # 1) REMOTION_BROWSER_EXECUTABLE takes precedence over remotion-managed & system-chrome
            with patch.dict(os.environ, {"REMOTION_BROWSER_EXECUTABLE": str(env_browser)}):
                bpath, bsrc = remotion_runtime.resolve_browser_executable(home)
                self.assertEqual(bpath, env_browser.resolve())
                self.assertEqual(bsrc, "env")
                rep = remotion_runtime.inspect_runtime(home)
                self.assertTrue(rep["ok"], rep)
                self.assertEqual(rep["browserSource"], "env")
                self.assertEqual(Path(rep["browserPath"]), env_browser.resolve())

            # 2) Nonexistent REMOTION_BROWSER_EXECUTABLE falls through to remotion-managed
            with patch.dict(os.environ, {"REMOTION_BROWSER_EXECUTABLE": str(Path(td) / "missing-chrome")}):
                bpath, bsrc = remotion_runtime.resolve_browser_executable(home)
                self.assertEqual(bpath, managed.resolve())
                self.assertEqual(bsrc, "remotion-managed")

            # 3) Missing remotion-managed falls through cleanly to mocked system-chrome
            managed.unlink()
            fake_sys = Path(td) / "system-chrome"
            fake_sys.write_text("#!/bin/sh\n", encoding="utf-8")
            with patch.dict(os.environ, {"REMOTION_BROWSER_EXECUTABLE": ""}):
                with patch.object(remotion_runtime, "_find_system_chrome", return_value=fake_sys.resolve()):
                    bpath, bsrc = remotion_runtime.resolve_browser_executable(home)
                    self.assertEqual(bpath, fake_sys.resolve())
                    self.assertEqual(bsrc, "system-chrome")
                    rep = remotion_runtime.inspect_runtime(home)
                    self.assertTrue(rep["ok"], rep)
                    self.assertEqual(rep["browserSource"], "system-chrome")

                    # Corrupt .runtime-state.json recovers cleanly via ensure_runtime without crashing
                    (home / remotion_runtime.RUNTIME_STATE_FILE).write_text("{broken json", encoding="utf-8")
                    with patch("subprocess.run") as mock_run:
                        mock_run.return_value = subprocess.CompletedProcess([], 0, "", "")
                        resolved = remotion_runtime.ensure_runtime(home, auto_setup=True, skip_browser=False)
                        self.assertEqual(resolved, home.resolve())
                        # Should NOT stall calling `remotion browser ensure` since system-chrome resolved
                        self.assertFalse(any("browser" in str(c) for c in mock_run.call_args_list))


if __name__ == "__main__":
    unittest.main()
