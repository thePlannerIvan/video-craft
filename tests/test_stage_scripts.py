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
import io
from contextlib import redirect_stdout
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable


def run(script: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([PYTHON, str(ROOT / "helpers" / script), *args],
                          capture_output=True, text=True)


class StageShells(unittest.TestCase):
    def test_apply_retry_does_not_repeat_edl_edit_and_rebuilds_preview(self):
        sys.path.insert(0, str(ROOT / 'helpers')); import stage_cut
        edit = self.project / 'edit'; (edit / 'transcripts').mkdir()
        (edit / 'transcripts/A.json').write_text(json.dumps({'words':[
            {'type':'word', 'text':str(i), 'start':i, 'end':i+.5} for i in range(4)]}))
        (edit / 'edl.json').write_text(json.dumps({'sources':{'A':'unused.mp4'}, 'ranges':[{'source':'A','start':0,'end':4}]}))
        (edit / 'selections.json').write_text(json.dumps({'words':[{'src':'A','start':1,'end':1.5}]}))
        actual_run = stage_cut.Stage.run; applied = []; rebuilt = []
        def execute(stage, tool, *args, **kwargs):
            if tool == 'apply_selection.py':
                applied.append(tool); return actual_run(stage, tool, *args, **kwargs)
            if tool == 'edl_preview_build.py':
                rebuilt.append(tool)
                (edit / 'edl_preview.html').write_text('<meta name="video-craft-edl-sha256" content="'+stage_cut._digest(edit / 'edl.json')+'">')
            return 0
        with patch.object(stage_cut.Stage, 'run', execute), redirect_stdout(io.StringIO()):
            self.assertEqual(stage_cut.do_apply(self.project, edit, False), 0)
            first = (edit / 'edl.json').read_bytes()
            self.assertEqual(stage_cut.do_apply(self.project, edit, False), 0)
            self.assertEqual((edit / 'edl.json').read_bytes(), first)
            self.assertEqual(len(applied), 1); self.assertEqual(len(rebuilt), 2)
            self.assertTrue(stage_cut._state(edit)['preview_current'])
            (edit / 'edl.json').write_bytes(first + b' ')
            with self.assertRaises(stage_cut.Prereq): stage_cut.do_apply(self.project, edit, False)

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

    def test_verify_forwards_no_audio_and_run_rejects_it(self):
        sys.path.insert(0, str(ROOT / "helpers"))
        import stage_deliver
        calls = []
        with patch.object(stage_deliver.Stage, "run", side_effect=lambda *args: calls.append(args) or 0), redirect_stdout(io.StringIO()):
            self.assertEqual(stage_deliver.main(["verify", "--project", str(self.project), "--no-audio"]), 0)
        self.assertIn("--no-audio", calls[0])
        proc = run("stage_deliver.py", "run", "--project", str(self.project), "--no-audio", "--json")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("verify", json.loads(proc.stdout)["error"])

    def test_prepare_without_edl_does_not_send_user_to_review(self):
        sys.path.insert(0, str(ROOT / "helpers")); import stage_cut
        (self.project / "edit/transcripts").mkdir()
        (self.project / "edit/transcripts/A.json").write_text('{}')
        output = io.StringIO()
        with patch.object(stage_cut.Stage, "run", return_value=0), redirect_stdout(output):
            stage_cut.do_prepare(self.project, self.project / "edit", None, "auto", True)
        payload = json.JSONDecoder().raw_decode(output.getvalue()[output.getvalue().index('{'):])[0]
        self.assertIn("edl_from_keep", payload["next"])
        self.assertNotIn("stage_cut.py review", payload["next"])

    def test_stale_preview_is_not_a_complete_cut_stage(self):
        (self.project / "edit/edl.json").write_text('{"ranges":[]}')
        (self.project / "edit/edl_preview.html").write_text('old page')
        proc = run("stage_cut.py", "status", "--project", str(self.project), "--json")
        data = json.loads(proc.stdout)
        self.assertFalse(data["state"]["preview_current"])
        self.assertFalse(data["state"]["stage_complete"])

    def test_existing_delivery_files_do_not_imply_capture_is_safe(self):
        (self.project / "review").mkdir()
        (self.project / "review/review-submissions.json").write_text('{}')
        (self.project / "成品").mkdir()
        (self.project / "成品/failed-report.json").write_text('{"ok":false}')
        proc = run("stage_deliver.py", "status", "--project", str(self.project), "--json")
        data = json.loads(proc.stdout)
        self.assertFalse(data["state"]["stage_complete"])
        self.assertNotIn("fingerprint capture", data["next"])


if __name__ == "__main__":
    unittest.main()
