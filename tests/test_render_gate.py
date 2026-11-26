#!/usr/bin/env python3
"""No human submission covering the current review snapshot → no render.

2026-10-21: SKILL.md said "确认前不要渲染成片", and a 43-second film was rendered
anyway — the command itself checked nothing. This gate makes the sentence
executable: a submission whose `snapshot` equals the review's current snapshot,
and a source tree that has not drifted since that review was built.
"""
from __future__ import annotations

import json
import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

HELPERS = Path(__file__).parents[1] / "helpers"
sys.path.insert(0, str(HELPERS))
sys.path.insert(0, str(HELPERS / "_internal"))

import render_gate  # noqa: E402

GATE_SCRIPT = HELPERS / "_internal" / "render_gate.py"
DELIVER_SCRIPT = HELPERS / "deliver.py"
SNAPSHOT = "abc123def456"


def _write_json(path: Path, doc) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")


class RenderGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name).resolve()
        self.edit = self.project / "edit"
        self.edit.mkdir()
        self.source = self.project / "composition" / "index.html"
        self.source.parent.mkdir()
        self.source.write_text("<html><body>draft</body></html>", encoding="utf-8")
        stat = self.source.stat()
        self.manifest = [{"path": "composition/index.html", "size": stat.st_size,
                          "mtime_ns": stat.st_mtime_ns, "sha256": hashlib.sha256(self.source.read_bytes()).hexdigest()}]

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _review(self) -> None:
        _write_json(self.project / "review" / "review_data.json", {
            "snapshot": SNAPSHOT,
            "sourceManifest": self.manifest,
        })

    def _submissions(self, *snapshots: str) -> None:
        _write_json(self.project / "review" / "review-submissions.json", {
            "records": [
                {"type": "text", "text": "看看", "snapshot": snap}
                for snap in snapshots
            ],
        })

    def test_no_review_data_blocks_and_says_how_to_start(self):
        report = render_gate.evaluate(self.project, None, False)
        self.assertFalse(report["ok"])
        self.assertTrue(any("build_review" in reason for reason in report["reasons"]),
                        report)
        self.assertEqual(render_gate.main([str(self.project)]), 2)

    def test_a_review_without_a_submission_blocks(self):
        self._review()
        report = render_gate.evaluate(self.project, None, False)
        self.assertFalse(report["ok"])
        self.assertTrue(any("没有任何人工提交" in r for r in report["reasons"]), report)
        self.assertEqual(render_gate.main([str(self.project)]), 1)

    def test_a_submission_for_the_current_snapshot_passes(self):
        self._review()
        self._submissions(SNAPSHOT)
        report = render_gate.evaluate(self.project, self.project / "final.mp4", False)
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["covering"], 1)
        self.assertEqual(render_gate.main([str(self.project)]), 0)

    def test_a_submission_for_an_older_snapshot_blocks(self):
        self._review()
        self._submissions("old000")
        report = render_gate.evaluate(self.project, None, False)
        self.assertFalse(report["ok"])
        self.assertEqual(report["covering"], 0)
        self.assertTrue(any("old000" in r for r in report["reasons"]), report)

    def test_source_drift_since_the_review_blocks_even_with_a_submission(self):
        self._review()
        self._submissions(SNAPSHOT)
        self.source.write_text("<html><body>changed after review</body></html>",
                               encoding="utf-8")
        report = render_gate.evaluate(self.project, None, False)
        self.assertFalse(report["ok"])
        self.assertTrue(any("源又改过" in r for r in report["reasons"]), report)

    def test_same_size_and_mtime_changed_content_blocks(self):
        self._review(); self._submissions(SNAPSHOT)
        stat = self.source.stat()
        self.source.write_bytes(self.source.read_bytes().replace(b'draft', b'other'))
        os.utime(self.source, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        self.assertFalse(render_gate.evaluate(self.project, None, False)['ok'])

    def test_missing_manifest_hash_or_critical_entry_blocks(self):
        for manifest in (None, [], [{}], [{k:v for k,v in self.manifest[0].items() if k != 'sha256'}]):
            with self.subTest(manifest=manifest):
                self.manifest = manifest
                self._review(); self._submissions(SNAPSHOT)
                self.assertFalse(render_gate.evaluate(self.project, None, False)['ok'])

    def test_surface_declared_feedback_file_is_read(self):
        self._review()
        _write_json(self.project / "review" / "review-surface.json", {
            "feedback": "subs.json",
        })
        _write_json(self.project / "review" / "subs.json", {
            "records": [{"snapshot": SNAPSHOT, "text": "这里"}],
        })
        report = render_gate.evaluate(self.project, None, False)
        self.assertTrue(report["ok"], report)

    def test_feedback_jsonl_records_count(self):
        self._review()
        path = self.project / "feedback" / "ch01.jsonl"
        path.parent.mkdir()
        path.write_text(json.dumps({"snapshot": SNAPSHOT, "text": "改这里"},
                                   ensure_ascii=False) + "\n", encoding="utf-8")
        report = render_gate.evaluate(self.project, None, False)
        self.assertTrue(report["ok"], report)

    def test_engineering_preview_is_allowed_only_under_engineering(self):
        out = self.edit / "_engineering" / "cut.mp4"
        report = render_gate.evaluate(self.project, out, True)
        self.assertTrue(report["ok"], report)
        self.assertTrue(report.get("engineeringBypass"))
        # The same switch must not be a way to render the deliverable.
        blocked = render_gate.evaluate(self.project, self.project / "final.mp4", True)
        self.assertFalse(blocked["ok"])
        self.assertTrue(any("edit/_engineering" in r for r in blocked["reasons"]))
        # And it needs an output at all.
        self.assertFalse(render_gate.evaluate(self.project, None, True)["ok"])

    def test_gate_works_on_a_final_cut_project_without_composition(self):
        """montage / final-cut 项目没有 composition/：判据只看快照与提交，照样放行。"""
        edl = self.edit / "edl.json"
        edl.write_text(json.dumps({"ranges": [{"start": 0.0, "end": 2.0}]}), encoding="utf-8")
        self.source.unlink()                       # 没有合成页，这条路线也不该有
        (self.project / "composition").rmdir()
        stat = edl.stat()
        self.manifest = [{"path": "edit/edl.json", "size": stat.st_size,
                          "sha256": hashlib.sha256(edl.read_bytes()).hexdigest()}]
        self._review()
        self._submissions(SNAPSHOT)
        report = render_gate.evaluate(self.project, self.project / "成品" / "final.mp4", False)
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["covering"], 1)
        self.assertEqual(render_gate.main([str(self.project)]), 0)

    def _run_cli(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(GATE_SCRIPT), *args],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_approve_in_chat_without_review_data_refuses_and_writes_nothing(self):
        report = render_gate.record_chat_approval(self.project)
        self.assertFalse(report["ok"])
        self.assertFalse(report["evaluable"])
        self.assertFalse((self.project / "review" / "review-submissions.json").exists())
        proc = self._run_cli(str(self.project), "--approve-in-chat", "--json")
        self.assertEqual(proc.returncode, 2, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertFalse(payload["ok"])
        self.assertFalse(payload["evaluable"])
        self.assertFalse((self.project / "review" / "review-submissions.json").exists())

    def test_approve_in_chat_without_snapshot_field_refuses_and_writes_nothing(self):
        _write_json(self.project / "review" / "review_data.json", {
            "snapshot": "   ",
            "sourceManifest": self.manifest,
        })
        proc = self._run_cli(str(self.project), "--approve-in-chat", "--json")
        self.assertEqual(proc.returncode, 2, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertFalse(payload["ok"])
        self.assertFalse(payload["evaluable"])
        self.assertFalse((self.project / "review" / "review-submissions.json").exists())

    def test_approve_in_chat_with_drifted_source_records_live_hash_and_passes(self):
        from state_fingerprint import source_digest

        self._review()
        self.source.write_text("<html><body>modified after review</body></html>", encoding="utf-8")
        expected_hash = source_digest(self.project)

        report = render_gate.record_chat_approval(self.project, "微调后直接导出")
        self.assertTrue(report["ok"], report)
        self.assertTrue(report["evaluable"])
        self.assertEqual(report["covering"], 1)
        self.assertEqual(report["liveSourceHash"], expected_hash)

        submissions_file = self.project / "review" / "review-submissions.json"
        self.assertTrue(submissions_file.is_file())
        doc = json.loads(submissions_file.read_text(encoding="utf-8"))
        entry = doc["records"][-1]
        self.assertEqual(entry["kind"], "chat-approval")
        self.assertEqual(entry["liveSourceHash"], expected_hash)
        self.assertTrue(entry["driftedFromReview"])
        self.assertTrue(entry.get("driftSummary"))

        # CLI --approve-in-chat appends audit record preserving older records and passes.
        proc = self._run_cli(str(self.project), "--approve-in-chat", "--approval-note", "继续导出", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(payload["liveSourceHash"], expected_hash)
        self.assertEqual(payload["covering"], 2)

        # Bare gate passes immediately after approval, but any post-approval edit still blocks.
        self.assertEqual(self._run_cli(str(self.project)).returncode, 0)
        self.source.write_text("<html><body>edited after chat approval</body></html>", encoding="utf-8")
        self.assertEqual(self._run_cli(str(self.project)).returncode, 1)

    def test_approve_in_chat_with_empty_manifest_succeeds_with_live_hash(self):
        from state_fingerprint import source_digest

        self.manifest = []
        self._review()
        expected_hash = source_digest(self.project)

        proc = self._run_cli(str(self.project), "--approve-in-chat", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(payload["liveSourceHash"], expected_hash)

        doc = json.loads((self.project / "review" / "review-submissions.json").read_text(encoding="utf-8"))
        entry = doc["records"][-1]
        self.assertEqual(entry["liveSourceHash"], expected_hash)
        self.assertTrue(entry["driftedFromReview"])

        # Post-approval edit still blocks bare render_gate.py.
        self.source.write_text("<html><body>post approval drift</body></html>", encoding="utf-8")
        self.assertEqual(self._run_cli(str(self.project)).returncode, 1)

    def test_approve_in_chat_records_audit_entry_and_bare_gate_subsequently_passes(self):
        self._review()
        # Before chat approval, bare gate blocks.
        self.assertEqual(self._run_cli(str(self.project)).returncode, 1)

        proc = self._run_cli(str(self.project), "--approve-in-chat", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(payload["covering"], 1)

        submissions_file = self.project / "review" / "review-submissions.json"
        self.assertTrue(submissions_file.is_file())
        doc = json.loads(submissions_file.read_text(encoding="utf-8"))
        self.assertEqual(doc["contract_version"], "video-craft-review-submissions/1.0.0")
        self.assertEqual(doc["surface"], "video-craft/visual")
        self.assertEqual(len(doc["records"]), 1)

        entry = doc["records"][0]
        self.assertEqual(entry["phase"], "approval")
        self.assertEqual(entry["kind"], "chat-approval")
        self.assertEqual(entry["source"], "chat")
        self.assertEqual(entry["snapshot"], SNAPSHOT)
        self.assertEqual(entry["note"], "作者在对话中明确授权导出")
        parsed_ts = datetime.fromisoformat(entry["createdAt"])
        self.assertIsNotNone(parsed_ts.tzinfo)

        # Subsequent bare render_gate.py check passes without repeating --approve-in-chat.
        bare = self._run_cli(str(self.project), "--json")
        self.assertEqual(bare.returncode, 0, bare.stderr)
        bare_payload = json.loads(bare.stdout)
        self.assertTrue(bare_payload["ok"], bare_payload)
        self.assertEqual(bare_payload["covering"], 1)

        # Any later source drift still invalidates approval.
        self.source.write_text("<html><body>edited after chat approval</body></html>", encoding="utf-8")
        self.assertEqual(self._run_cli(str(self.project)).returncode, 1)

    def test_approve_in_chat_respects_surface_feedback_file_and_custom_note(self):
        self._review()
        _write_json(self.project / "review" / "review-surface.json", {
            "feedback": "custom-subs.json",
        })
        custom_subs = self.project / "review" / "custom-subs.json"
        _write_json(custom_subs, {
            "records": [{"snapshot": "old000", "text": "上一版意见"}],
            "choreography_overrides": {"s1": {"density": "low"}},
        })

        proc = self._run_cli(
            str(self.project),
            "--approve-in-chat",
            "--approval-note",
            "  作者在对话确认导出分轨成片  ",
            "--out",
            "成品/final.mp4",
            "--json",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(payload["submissions"], 2)
        self.assertEqual(payload["covering"], 1)
        self.assertEqual(Path(payload["out"]).name, "final.mp4")

        self.assertFalse((self.project / "review" / "review-submissions.json").exists())
        doc = json.loads(custom_subs.read_text(encoding="utf-8"))
        self.assertEqual(doc["contract_version"], "video-craft-review-submissions/1.0.0")
        self.assertEqual(doc["surface"], "video-craft/visual")
        self.assertEqual(doc["choreography_overrides"], {"s1": {"density": "low"}})
        self.assertEqual(len(doc["records"]), 2)
        self.assertEqual(doc["records"][0]["snapshot"], "old000")
        self.assertEqual(doc["records"][1]["kind"], "chat-approval")
        self.assertEqual(doc["records"][1]["note"], "作者在对话确认导出分轨成片")

        # Blank approval note falls back to default Chinese audit note.
        blank_proc = self._run_cli(str(self.project), "--approve-in-chat", "--approval-note", "   ")
        self.assertEqual(blank_proc.returncode, 0, blank_proc.stderr)
        doc_after = json.loads(custom_subs.read_text(encoding="utf-8"))
        self.assertEqual(doc_after["records"][-1]["note"], "作者在对话中明确授权导出")

    def test_approve_in_chat_help_warning_and_flag_guards(self):
        help_proc = self._run_cli("--help")
        self.assertEqual(help_proc.returncode, 0)
        self.assertIn("--approve-in-chat", help_proc.stdout)
        self.assertIn("--approval-note", help_proc.stdout)
        self.assertIn("explicitly instructed exporting in the active conversation", help_proc.stdout)

        self._review()
        note_only = self._run_cli(str(self.project), "--approval-note", "未授权参数")
        self.assertNotEqual(note_only.returncode, 0)
        self.assertFalse((self.project / "review" / "review-submissions.json").exists())

        conflict = self._run_cli(
            str(self.project),
            "--approve-in-chat",
            "--engineering",
            "--out",
            "edit/_engineering/cut.mp4",
        )
        self.assertNotEqual(conflict.returncode, 0)
        self.assertFalse((self.project / "review" / "review-submissions.json").exists())

    def test_deliver_skip_gate_still_requires_dsh_test_env(self):
        env = dict(os.environ)
        env.pop("DSH_TEST", None)
        proc = subprocess.run(
            [sys.executable, str(DELIVER_SCRIPT), str(self.project), "--skip-gate"],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("DSH_TEST=1", proc.stderr)


if __name__ == "__main__":
    unittest.main()
