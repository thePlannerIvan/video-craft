#!/usr/bin/env python3
"""阶段脚本的壳：入口、前置条件、退出码、JSON。

壳只做两件事——串既有命令、把"缺什么/下一步"说清楚。这里钉住的是壳的契约，
不是被包工具的行为（那些各有自己的用例）。
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable


def run(script: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([PYTHON, str(ROOT / "helpers" / script), *args],
                          capture_output=True, text=True)


class StageShells(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name) / "demo"
        (self.project / "edit").mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def test_help_is_available(self):
        for script in ("stage_cut.py", "stage_deliver.py"):
            self.assertEqual(run(script, "--help").returncode, 0, script)

    def test_missing_project_is_a_prerequisite_not_a_crash(self):
        for script in ("stage_cut.py", "stage_deliver.py"):
            proc = run(script, "status", "--project", str(self.project / "nope"))
            self.assertEqual(proc.returncode, 2, proc.stderr)

    def test_status_is_machine_readable(self):
        proc = run("stage_cut.py", "status", "--project", str(self.project), "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["stage"], "cut")
        self.assertIn("edit", payload)
        self.assertTrue(payload["next"])

    def test_cut_prepare_without_transcripts_says_what_is_missing(self):
        proc = run("stage_cut.py", "prepare", "--project", str(self.project))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("--source", proc.stderr)

    def test_cut_apply_without_selections_says_what_is_missing(self):
        proc = run("stage_cut.py", "apply", "--project", str(self.project))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("selections.json", proc.stderr)

    def test_deliver_fingerprint_requires_subaction(self):
        proc = run("stage_deliver.py", "fingerprint", "--project", str(self.project))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("--fingerprint-action", proc.stderr)


if __name__ == "__main__":
    unittest.main()
