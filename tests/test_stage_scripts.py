#!/usr/bin/env python3
"""阶段脚本的壳：入口、前置条件、退出码、JSON。

壳只做两件事——串既有命令、把"缺什么/下一步"说清楚。这里钉住的是壳的契约，
不是被包工具的行为（那些各有自己的用例）。
"""
from __future__ import annotations

import json
import shutil
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
    return subprocess.run([PYTHON, str((ROOT / "helpers" / script) if (ROOT / "helpers" / script).is_file() else (ROOT / "helpers" / "_internal" / script)), *args],
                          capture_output=True, text=True)


class StageShells(unittest.TestCase):
    def test_apply_retry_does_not_repeat_edl_edit_and_rebuilds_preview(self):
        sys.path.insert(0, str(ROOT / 'helpers'))
        sys.path.insert(0, str(ROOT / 'helpers' / '_internal'))
        import stage_cut
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
                (edit / 'edl_preview.html').write_text('<meta name="video-craft-edl-sha256" content="'+stage_cut.edl_digest(edit / 'edl.json')+'">')
            return 0
        with patch.object(stage_cut.Stage, 'run', execute), redirect_stdout(io.StringIO()):
            self.assertEqual(stage_cut.do_apply(self.project, edit, False), 0)
            first = (edit / 'edl.json').read_bytes()
            self.assertEqual(stage_cut.do_apply(self.project, edit, False), 0)
            self.assertEqual((edit / 'edl.json').read_bytes(), first)
            self.assertEqual(len(applied), 1); self.assertEqual(len(rebuilt), 2)
            self.assertTrue(stage_cut._state(edit)['preview_current'])
            self.assertTrue(stage_cut._state(edit)['selection_applied'])
            # Formatting / whitespace changes alone keep canonical EDL digest invariant.
            (edit / 'edl.json').write_bytes(first + b' ')
            self.assertTrue(stage_cut._state(edit)['preview_current'])
            self.assertEqual(stage_cut.do_apply(self.project, edit, False), 0)
            # Modifying an actual cut range invalidates the receipt and raises Prereq.
            edited = json.loads(first.decode('utf-8'))
            edited['ranges'][0]['end'] = 3.5
            (edit / 'edl.json').write_text(json.dumps(edited), encoding='utf-8')
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
        sys.path.insert(0, str(ROOT / "helpers" / "_internal"))
        import stage_deliver
        calls = []
        with patch.object(stage_deliver.Stage, "run", side_effect=lambda *args: calls.append(args) or 0), redirect_stdout(io.StringIO()):
            self.assertEqual(stage_deliver.main(["verify", "--project", str(self.project), "--no-audio"]), 0)
        self.assertIn("--no-audio", calls[0])
        proc = run("stage_deliver.py", "run", "--project", str(self.project), "--no-audio", "--json")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("verify", json.loads(proc.stdout)["error"])

    def test_prepare_without_edl_does_not_send_user_to_review(self):
        sys.path.insert(0, str(ROOT / "helpers"))
        sys.path.insert(0, str(ROOT / "helpers" / "_internal"))
        import stage_cut
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

    def test_preview_current_matches_canonical_edl_digest_across_path_and_whitespace_changes(self):
        sys.path.insert(0, str(ROOT / "helpers" / "_internal"))
        import _edl

        edit = self.project / "edit"
        edl_path = edit / "edl.json"
        edl_path.write_text(
            json.dumps({
                "sources": {"A": "/tmp/proj_v1/raw/A.mp4"},
                "ranges": [{"source": "A", "start": 0.0, "end": 4.0}],
            }),
            encoding="utf-8",
        )
        canonical = _edl.edl_digest(edl_path)
        (edit / "edl_preview.html").write_text(
            f'<meta name="video-craft-edl-sha256" content="{canonical}">',
            encoding="utf-8",
        )
        proc = run("stage_cut.py", "status", "--project", str(self.project), "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(json.loads(proc.stdout)["state"]["preview_current"])

        edl_path.write_text(
            json.dumps(
                {
                    "sources": {"A": "/Volumes/copy/proj_v2/assets/A.mp4"},
                    "ranges": [{"source": "A", "start": 0, "end": 4.0}],
                },
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )
        proc_copied = run("stage_cut.py", "status", "--project", str(self.project), "--json")
        self.assertTrue(json.loads(proc_copied.stdout)["state"]["preview_current"])

        edl_path.write_text(
            json.dumps({
                "sources": {"A": "/Volumes/copy/proj_v2/assets/A.mp4"},
                "ranges": [{"source": "A", "start": 0.0, "end": 3.5}],
            }),
            encoding="utf-8",
        )
        proc_edited = run("stage_cut.py", "status", "--project", str(self.project), "--json")
        self.assertFalse(json.loads(proc_edited.stdout)["state"]["preview_current"])

    def test_real_edl_preview_build_and_stage_cut_agree_across_dir_copy(self):
        edit = self.project / "edit"
        (edit / "A.mp4").touch()
        edl_path = edit / "edl.json"
        edl_path.write_text(
            json.dumps({
                "sources": {"A": str(edit / "A.mp4")},
                "ranges": [{"source": "A", "start": 0.0, "end": 4.0}],
            }),
            encoding="utf-8",
        )
        build = run("edl_preview_build.py", str(edit))
        self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
        status1 = run("stage_cut.py", "status", "--project", str(self.project), "--json")
        self.assertEqual(status1.returncode, 0, status1.stderr)
        self.assertTrue(json.loads(status1.stdout)["state"]["preview_current"])

        copied_project = Path(self._tmp.name) / "demo_v2"
        shutil.copytree(self.project, copied_project)
        copied_edit = copied_project / "edit"
        (copied_edit / "edl.json").write_text(
            json.dumps(
                {
                    "sources": {"A": str(copied_edit / "A.mp4")},
                    "ranges": [{"source": "A", "start": 0, "end": 4.0}],
                },
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )
        status2 = run("stage_cut.py", "status", "--project", str(copied_project), "--json")
        self.assertEqual(status2.returncode, 0, status2.stderr)
        self.assertTrue(json.loads(status2.stdout)["state"]["preview_current"])


class StageCutSeedAsrAndReviewTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name).resolve() / "demo"
        (self.project / "edit").mkdir(parents=True)
        self.source = self.project / "take.mp4"
        self.source.write_bytes(b"")

    def tearDown(self):
        self._tmp.cleanup()

    def _clean_env(self, **extra: str) -> dict[str, str]:
        import os
        env = dict(os.environ)
        for key in ("DOUBAO_APP_ID", "DOUBAO_ACCESS_TOKEN", "ELEVENLABS_API_KEY", "ARK_API_KEY"):
            env.pop(key, None)
        env["VIDEO_CRAFT_ENV_FILE"] = "none"
        env.update(extra)
        return env

    def _write_env(self, env_path: Path, pairs: dict[str, str]) -> None:
        lines = ["# test credentials", *[f"{k}={v}" for k, v in pairs.items()]]
        env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def test_auto_without_credentials_raises_prereq_and_never_runs_ark(self):
        proc = subprocess.run(
            [PYTHON, str(ROOT / "helpers" / "stage_cut.py"), "prepare",
             "--project", str(self.project), "--source", str(self.source), "--json"],
            capture_output=True, text=True, env=self._clean_env(ARK_API_KEY="ark-present-must-not-auto-fallback"),
        )
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertFalse(payload["ok"])
        self.assertIn("DOUBAO_APP_ID", payload["error"])
        self.assertIn("DOUBAO_ACCESS_TOKEN", payload["error"])
        self.assertIn("ELEVENLABS_API_KEY", payload["error"])
        self.assertIn("--backend mlx", payload["error"])
        self.assertIn("GOTCHAS #1", payload["error"])

    def test_auto_prefers_seedasr_from_env_vars_without_leaking_values(self):
        sys.path.insert(0, str(ROOT / "helpers"))
        sys.path.insert(0, str(ROOT / "helpers" / "_internal"))
        import os
        import stage_cut

        secret_app = "env-doubao-app-111"
        secret_tok = "env-doubao-tok-222"
        calls = []
        output = io.StringIO()
        env = self._clean_env(
            DOUBAO_APP_ID=secret_app,
            DOUBAO_ACCESS_TOKEN=secret_tok,
            ELEVENLABS_API_KEY="env-scribe-333",
        )
        with patch.dict(os.environ, env, clear=True), \
                patch.object(stage_cut.Stage, "run", side_effect=lambda *a: calls.append(a) or 0), \
                redirect_stdout(output):
            rc = stage_cut.main(["prepare", "--project", str(self.project),
                                 "--source", str(self.source), "--json"])
        self.assertEqual(rc, 0)
        self.assertEqual(calls[0], ("transcribe_seedasr.py", "--edit-dir", self.project / "edit", str(self.source)))
        self.assertNotIn(secret_app, output.getvalue())
        self.assertNotIn(secret_tok, output.getvalue())

    def test_auto_prefers_seedasr_from_skill_root_env_without_leaking_values(self):
        sys.path.insert(0, str(ROOT / "helpers"))
        sys.path.insert(0, str(ROOT / "helpers" / "_internal"))
        import os
        import stage_cut

        fake_skill_root = Path(self._tmp.name) / "skill-root"
        fake_skill_root.mkdir()
        secret_app = "secret-doubao-app-999"
        secret_tok = "secret-doubao-tok-888"
        self._write_env(fake_skill_root / ".env", {
            "DOUBAO_APP_ID": secret_app,
            "DOUBAO_ACCESS_TOKEN": secret_tok,
            "ELEVENLABS_API_KEY": "secret-scribe-777",
            "ARK_API_KEY": "secret-ark-666",
        })
        calls = []
        output = io.StringIO()
        clean = {k: v for k, v in os.environ.items()
                 if k not in ("DOUBAO_APP_ID", "DOUBAO_ACCESS_TOKEN",
                              "ELEVENLABS_API_KEY", "ARK_API_KEY", "VIDEO_CRAFT_ENV_FILE")}
        with patch.object(stage_cut, "SKILL_ROOT", fake_skill_root), \
                patch.dict(os.environ, clean, clear=True), \
                patch.object(stage_cut.Stage, "run", side_effect=lambda *a: calls.append(a) or 0), \
                redirect_stdout(output):
            rc = stage_cut.main(["prepare", "--project", str(self.project),
                                 "--source", str(self.source), "--json"])
        self.assertEqual(rc, 0)
        self.assertEqual(calls[0], ("transcribe_seedasr.py", "--edit-dir", self.project / "edit", str(self.source)))
        self.assertEqual(calls[1], ("pack_transcripts.py", "--edit-dir", self.project / "edit"))
        rendered = output.getvalue()
        self.assertNotIn(secret_app, rendered)
        self.assertNotIn(secret_tok, rendered)

    def test_auto_falls_back_to_scribe_only_when_doubao_incomplete_and_scribe_present(self):
        sys.path.insert(0, str(ROOT / "helpers"))
        sys.path.insert(0, str(ROOT / "helpers" / "_internal"))
        import os
        import stage_cut

        env_file = Path(self._tmp.name) / "custom.env"
        self._write_env(env_file, {
            "DOUBAO_APP_ID": "only-app-id-no-token",
            "ELEVENLABS_API_KEY": "scribe-only-key-123",
            "ARK_API_KEY": "ark-key-must-not-run",
        })
        calls = []
        output = io.StringIO()
        with patch.dict(os.environ, self._clean_env(VIDEO_CRAFT_ENV_FILE=str(env_file)), clear=True), \
                patch.object(stage_cut.Stage, "run", side_effect=lambda *a: calls.append(a) or 0), \
                redirect_stdout(output):
            rc = stage_cut.main(["prepare", "--project", str(self.project),
                                 "--source", str(self.source), "--json"])
        self.assertEqual(rc, 0)
        self.assertEqual(
            calls[0],
            ("transcribe.py", "--edit-dir", self.project / "edit", "--audio-track", "0", "--backend", "scribe", str(self.source)),
        )

    def test_explicit_backends_passthrough_and_ark_warns(self):
        sys.path.insert(0, str(ROOT / "helpers"))
        sys.path.insert(0, str(ROOT / "helpers" / "_internal"))
        import os
        import stage_cut

        with patch.dict(os.environ, self._clean_env(), clear=True):
            for backend, expected_first in (
                ("seedasr", ("transcribe_seedasr.py", "--edit-dir", self.project / "edit", str(self.source))),
                ("scribe", ("transcribe.py", "--edit-dir", self.project / "edit", "--audio-track", "0", "--backend", "scribe", str(self.source))),
                ("mlx", ("transcribe.py", "--edit-dir", self.project / "edit", "--audio-track", "0", "--backend", "mlx", str(self.source))),
                ("ark", ("transcribe.py", "--edit-dir", self.project / "edit", "--audio-track", "0", "--backend", "ark", str(self.source))),
            ):
                calls = []
                output = io.StringIO()
                with patch.object(stage_cut.Stage, "run", side_effect=lambda *a: calls.append(a) or 0), \
                        redirect_stdout(output):
                    rc = stage_cut.main(["prepare", "--project", str(self.project),
                                         "--source", str(self.source), "--backend", backend, "--json"])
                self.assertEqual(rc, 0, backend)
                self.assertEqual(calls[0], expected_first, backend)
                payload = json.JSONDecoder().raw_decode(output.getvalue()[output.getvalue().index("{"):])[0]
                if backend == "ark":
                    self.assertTrue(any("GOTCHAS #1" in n for n in payload["notes"]))
                else:
                    self.assertFalse(any("GOTCHAS #1" in n for n in payload["notes"]))

    def test_legacy_transcribe_auto_missing_key_never_falls_back_to_ark(self):
        proc = subprocess.run(
            [PYTHON, str(ROOT / "helpers" / "_internal" / "transcribe.py"),
             str(self.source), "--edit-dir", str(self.project / "edit"), "--backend", "auto"],
            capture_output=True, text=True,
            env=self._clean_env(ARK_API_KEY="ark-must-not-run"),
        )
        self.assertNotEqual(proc.returncode, 0)
        combined = proc.stdout + proc.stderr
        self.assertIn("transcribe_seedasr.py", combined)
        self.assertIn("--backend mlx", combined)
        self.assertNotIn("[ark]", combined)

    def test_legacy_transcribe_auto_quota_and_401_do_not_fallback_to_ark(self):
        sys.path.insert(0, str(ROOT / "helpers" / "_internal"))
        import transcribe

        edit = self.project / "edit"
        with patch.object(transcribe, "count_audio_tracks", return_value=1), \
                patch.object(transcribe, "check_quota", return_value=(10.0, 100.0)), \
                patch.object(transcribe, "transcribe_ark") as mock_ark, \
                patch.object(transcribe, "transcribe_mlx") as mock_mlx:
            with self.assertRaises(SystemExit) as ctx:
                transcribe.transcribe_one(self.source, edit, api_key="fake-key", backend="auto", verbose=False)
            self.assertIn("transcribe_seedasr.py", str(ctx.exception))
            self.assertIn("--backend mlx", str(ctx.exception))
            mock_ark.assert_not_called()
            mock_mlx.assert_not_called()

        with patch.object(transcribe, "count_audio_tracks", return_value=1), \
                patch.object(transcribe, "check_quota", return_value=None), \
                patch.object(transcribe, "extract_audio", side_effect=lambda _s, dst, _t=0: Path(dst).write_bytes(b"RIFF")), \
                patch.object(transcribe, "silence_guard"), \
                patch.object(transcribe, "call_scribe", side_effect=RuntimeError("Scribe returned 401: invalid")), \
                patch.object(transcribe, "transcribe_ark") as mock_ark, \
                patch.object(transcribe, "transcribe_mlx") as mock_mlx:
            with self.assertRaises(RuntimeError) as ctx2:
                transcribe.transcribe_one(self.source, edit, api_key="fake-key", backend="auto", verbose=False)
            self.assertIn("transcribe_seedasr.py", str(ctx2.exception))
            self.assertIn("--backend mlx", str(ctx2.exception))
            mock_ark.assert_not_called()
            mock_mlx.assert_not_called()

    def test_legacy_transcribe_explicit_mlx_runs_without_scribe_key(self):
        sys.path.insert(0, str(ROOT / "helpers" / "_internal"))
        import os
        import transcribe

        edit = self.project / "edit"
        expected = edit / "transcripts" / "take.json"
        with patch.dict(os.environ, self._clean_env(), clear=True), \
                patch.object(transcribe, "transcribe_mlx", return_value=expected) as mock_mlx, \
                patch.object(sys, "argv", ["transcribe.py", str(self.source), "--edit-dir", str(edit), "--backend", "mlx"]):
            transcribe.main()
        mock_mlx.assert_called_once()

    def _seed_edl_fixture(self) -> Path:
        edit = self.project / "edit"
        (edit / "transcripts").mkdir(parents=True, exist_ok=True)
        (edit / "transcripts" / "A.json").write_text(json.dumps({
            "words": [
                {"text": "你", "type": "word", "start": 0.1, "end": 0.3, "speaker": "S0"},
                {"text": "好", "type": "word", "start": 0.4, "end": 0.7, "speaker": "S0"},
            ]
        }, ensure_ascii=False), encoding="utf-8")
        (edit / "edl.json").write_text(json.dumps({
            "sources": {"A": "../take.mp4"},
            "ranges": [{"source": "A", "start": 0.0, "end": 1.0}],
        }, ensure_ascii=False), encoding="utf-8")
        return edit

    def test_review_surface_only_writes_contract_without_starting_host(self):
        edit = self._seed_edl_fixture()
        proc = subprocess.run(
            [PYTHON, str(ROOT / "helpers" / "stage_cut.py"), "review",
             "--project", str(self.project), "--surface-only", "--json"],
            capture_output=True, text=True, env=self._clean_env(),
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertTrue((edit / "edl_preview.html").is_file())
        self.assertTrue((edit / "edl_review_surface.json").is_file())
        self.assertFalse((edit / "review_host.json").exists())
        payload = json.JSONDecoder().raw_decode(proc.stdout[proc.stdout.index("{"):])[0]
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["surface"], str(edit / "edl_review_surface.json"))
        self.assertFalse(payload.get("host_started", True))
        self.assertFalse(payload.get("host"))

    def test_review_standalone_launches_local_host_and_returns_reachable_url(self):
        import urllib.request
        sys.path.insert(0, str(ROOT / "helpers" / "_internal"))
        sys.path.insert(0, str(ROOT / "helpers" / "_internal" / "lib"))
        from lib.planners_modules import resolve_module
        sys.path.insert(0, str(resolve_module("planners-review-core") / "scripts" / "lib"))
        import review_host

        edit = self._seed_edl_fixture()
        state_file = edit / "review_host.json"
        try:
            proc_json = subprocess.run(
                [PYTHON, str(ROOT / "helpers" / "stage_cut.py"), "review",
                 "--project", str(self.project), "--json"],
                capture_output=True, text=True, env=self._clean_env(),
            )
            self.assertEqual(proc_json.returncode, 0, proc_json.stdout + proc_json.stderr)
            payload = json.JSONDecoder().raw_decode(proc_json.stdout[proc_json.stdout.index("{"):])[0]
            self.assertTrue(payload["ok"])
            self.assertTrue(payload["host_started"])
            host_url = payload["host"]
            self.assertRegex(host_url, r"^http://127\.0\.0\.1:\d+/")
            self.assertIn("stage_cut.py apply", payload["next"])
            self.assertTrue(state_file.is_file())

            with urllib.request.urlopen(host_url, timeout=5) as resp:
                self.assertEqual(resp.status, 200)
                body = resp.read().decode("utf-8")
                self.assertIn("/__review/bridge.js", body)
                self.assertNotIn("{{REVIEW_BRIDGE}}", body)

            proc_text = subprocess.run(
                [PYTHON, str(ROOT / "helpers" / "stage_cut.py"), "review",
                 "--project", str(self.project)],
                capture_output=True, text=True, env=self._clean_env(),
            )
            self.assertEqual(proc_text.returncode, 0, proc_text.stdout + proc_text.stderr)
            self.assertIn(host_url, proc_text.stdout)
            self.assertIn("stage_cut.py apply", proc_text.stdout)
        finally:
            if state_file.is_file():
                review_host.stop_host(json.loads(state_file.read_text(encoding="utf-8")))

    def test_review_uses_dsh_bridge_when_importable_and_falls_back_on_error(self):
        import types
        sys.path.insert(0, str(ROOT / "helpers"))
        sys.path.insert(0, str(ROOT / "helpers" / "_internal"))
        import stage_cut

        edit = self._seed_edl_fixture()
        notified = []
        fake_bridge = types.ModuleType("review_open_bridge")
        fake_bridge.notify = lambda surf: notified.append(Path(surf))

        calls = []
        def fake_run(stage, tool, *args):
            calls.append((tool, *args))
            if tool == "edl_review_surface.py":
                print(json.dumps({"surface": str(edit / "edl_review_surface.json"), "host_started": False}))
            return 0

        out1 = io.StringIO()
        with patch.dict(sys.modules, {"review_open_bridge": fake_bridge}), \
                patch.object(stage_cut.Stage, "run", fake_run), \
                redirect_stdout(out1):
            rc = stage_cut.do_review(self.project, edit, True, surface_only=False)
        self.assertEqual(rc, 0)
        self.assertEqual(notified, [edit / "edl_review_surface.json"])
        self.assertEqual(calls, [
            ("edl_preview_build.py", edit),
            ("edl_review_surface.py", edit, "--surface-only"),
        ])
        payload1 = json.JSONDecoder().raw_decode(out1.getvalue()[out1.getvalue().index("{"):])[0]
        self.assertEqual(payload1["host"], "DSH 侧栏（review_open）")

        # Now notify raises -> falls back to standalone local host
        def failing_notify(_surf):
            raise RuntimeError("bridge offline")
        fake_bridge.notify = failing_notify
        calls2 = []
        def fake_run_fallback(stage, tool, *args):
            calls2.append((tool, *args))
            if tool == "edl_review_surface.py" and "--no-open" in args:
                print(json.dumps({"surface": str(edit / "edl_review_surface.json"), "url": "http://127.0.0.1:43210/edit/edl_preview.html"}))
            elif tool == "edl_review_surface.py":
                print(json.dumps({"surface": str(edit / "edl_review_surface.json"), "host_started": False}))
            return 0

        out2 = io.StringIO()
        with patch.dict(sys.modules, {"review_open_bridge": fake_bridge}), \
                patch.object(stage_cut.Stage, "run", fake_run_fallback), \
                redirect_stdout(out2):
            rc2 = stage_cut.do_review(self.project, edit, True, surface_only=False)
        self.assertEqual(rc2, 0)
        self.assertIn(("edl_review_surface.py", edit, "--no-open", "--port", "0"), calls2)
        payload2 = json.JSONDecoder().raw_decode(out2.getvalue()[out2.getvalue().index("{"):])[0]
        self.assertEqual(payload2["host"], "http://127.0.0.1:43210/edit/edl_preview.html")


if __name__ == "__main__":
    unittest.main()
