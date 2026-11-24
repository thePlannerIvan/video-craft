#!/usr/bin/env python3
"""deliver.py：交付合成的两条硬判据 —— 有音轨、字幕安全区没有内容。

2026-10-21 的形态是「composition 只做画面层，人物与声音交付阶段贴回」。
这里用 1 秒的合成素材跑一遍真 ffmpeg，钉住两件事：
  · 成片必须真的有音轨（不是静音轨）；
  · 画面层若把内容画进 captionSafe 区域，必须报红 —— 否则字幕会压住画面。
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import io
import os
from contextlib import redirect_stdout
from unittest.mock import patch
from pathlib import Path

HELPERS = Path(__file__).parents[1] / "helpers"
sys.path.insert(0, str(HELPERS))
sys.path.insert(0, str(HELPERS / "_internal"))
sys.path.insert(0, str(HELPERS / "_internal"))

import deliver  # noqa: E402


DELIVER_SCRIPT = Path(__file__).parents[1] / "helpers" / "deliver.py"


class DeliverChatApprovalAndCliTests(unittest.TestCase):
    def _seed_review_project(self, root: Path, *, drift: bool = False, with_index: bool = True) -> Path:
        import hashlib
        project = root / "chat_proj"
        (project / "edit").mkdir(parents=True, exist_ok=True)
        (project / "composition/_render").mkdir(parents=True, exist_ok=True)
        (project / "composition/assets").mkdir(parents=True, exist_ok=True)
        if with_index:
            src = project / "composition/index.html"
            src.write_text("<html><body>v1</body></html>", encoding="utf-8")
            stat = src.stat()
            manifest = [{
                "path": "composition/index.html",
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
                "sha256": hashlib.sha256(src.read_bytes()).hexdigest(),
            }]
        else:
            manifest = []
        (project / "review").mkdir(parents=True, exist_ok=True)
        (project / "review/review_data.json").write_text(
            json.dumps({"snapshot": "snap-v21-01", "sourceManifest": manifest}),
            encoding="utf-8",
        )
        if drift and with_index:
            src.write_text("<html><body>drifted-after-review</body></html>", encoding="utf-8")
        return project

    def test_cli_rejects_stray_approval_note_and_conflicting_skip_gate(self):
        with tempfile.TemporaryDirectory() as td:
            project = Path(td) / "demo"
            project.mkdir()
            p1 = subprocess.run(
                [sys.executable, str(DELIVER_SCRIPT), str(project), "--approval-note", "私自备注"],
                capture_output=True, text=True, check=False,
            )
            self.assertNotEqual(p1.returncode, 0)
            self.assertIn("--approve-in-chat", p1.stderr)

            env = dict(os.environ, DSH_TEST="1")
            p2 = subprocess.run(
                [sys.executable, str(DELIVER_SCRIPT), str(project), "--skip-gate", "--approve-in-chat"],
                env=env, capture_output=True, text=True, check=False,
            )
            self.assertNotEqual(p2.returncode, 0)
            self.assertIn("--skip-gate", p2.stderr)

    def test_approve_in_chat_blocks_without_review_or_on_source_drift(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            no_rev = root / "no_rev"
            (no_rev / "edit").mkdir(parents=True)
            with patch.object(deliver, "_preflight", return_value=(True, 1)), \
                 patch.object(deliver, "_run") as enc, redirect_stdout(io.StringIO()):
                code1 = deliver.deliver(
                    no_rev, None, None, None, None, no_rev / "成品",
                    False, False, True, approve_in_chat=True,
                )
            self.assertNotEqual(code1, 0)
            enc.assert_not_called()
            rep1 = json.loads((no_rev / "成品" / f"{no_rev.name}_核验报告.json").read_text(encoding="utf-8"))
            gate1 = next(c for c in rep1["checks"] if c["name"] == "渲染闸门")
            self.assertFalse(gate1["ok"])
            self.assertIn("review_data.json", gate1["detail"])
            self.assertFalse((no_rev / "review/review-submissions.json").exists())

            drifted = self._seed_review_project(root, drift=True)
            with patch.object(deliver, "_preflight", return_value=(True, 1)), \
                 patch.object(deliver, "_run") as enc2, redirect_stdout(io.StringIO()):
                code2 = deliver.deliver(
                    drifted, None, None, None, None, drifted / "成品",
                    False, False, True, approve_in_chat=True, approval_note="未建快照尝试导出",
                )
            self.assertNotEqual(code2, 0)
            enc2.assert_not_called()
            rep2 = json.loads((drifted / "成品" / f"{drifted.name}_核验报告.json").read_text(encoding="utf-8"))
            gate2 = next(c for c in rep2["checks"] if c["name"] == "渲染闸门")
            self.assertFalse(gate2["ok"])
            self.assertIn("源又改过", gate2["detail"])
            self.assertFalse((drifted / "review/review-submissions.json").exists())

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "需要 ffmpeg/ffprobe")
    def test_cli_approve_in_chat_records_audit_entry_and_delivers(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            project = self._seed_review_project(root, drift=False, with_index=False)
            # Build clean visuals, person, audio, EDL, and recompose.json
            subprocess.run([
                "ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                "-i", "color=c=0x050607:s=1920x1080:r=30:d=1",
                "-vf", "drawbox=x=700:y=200:w=1000:h=500:color=0xF2EBDD@1:t=fill",
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                str(project / "composition/_render/visuals.mp4"),
            ], check=True)
            subprocess.run([
                "ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                "-i", "testsrc2=s=720x1280:r=30:d=1",
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                str(project / "composition/assets/person.mp4"),
            ], check=True)
            subprocess.run([
                "ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                "-i", "sine=frequency=440:duration=1", "-c:a", "aac", "-ar", "48000", "-ac", "2",
                str(project / "composition/assets/audio.m4a"),
            ], check=True)
            (project / "recompose.json").write_text(json.dumps({
                "canvas": {"w": 1920, "h": 1080, "fps": 30},
                "personSlot": {"x": 0, "y": 0, "w": 500, "h": 1080},
                "captionSafe": {"x": 0, "y": 880, "w": 1920, "h": 200},
            }), encoding="utf-8")
            from _edl import edl_digest
            edl = project / "edit/edl.json"
            edl.write_text(json.dumps({"ranges": [{"start": 0, "end": 1}]}), encoding="utf-8")
            (project / "edit/segment_durations.json").write_text(json.dumps({
                "final": {"durations": [1.0], "total_s": 1.0, "edl_sha256": edl_digest(edl)},
            }), encoding="utf-8")
            # Refresh review manifest after adding composition/assets and recompose/edl
            from state_fingerprint import source_entries
            manifest = [
                {"path": k, "size": v["bytes"], "sha256": v["sha256"]}
                for k, v in source_entries(project).items()
                if not k.startswith("review/")
            ]
            (project / "review/review_data.json").write_text(
                json.dumps({"snapshot": "snap-v21-01", "sourceManifest": manifest}),
                encoding="utf-8",
            )
            deliver._record_visual_source(project, project / "composition/_render/visuals.mp4", "manual-confirmation")
            # Without --approve-in-chat, gate blocks
            blocked = subprocess.run(
                [sys.executable, str(DELIVER_SCRIPT), str(project), "--json"],
                capture_output=True, text=True, check=False,
            )
            self.assertNotEqual(blocked.returncode, 0)

            # With --approve-in-chat and custom note, gate approves and records audit entry
            note = "作者已在对话核对当前成片，确认导出"
            ok_proc = subprocess.run(
                [sys.executable, str(DELIVER_SCRIPT), str(project),
                 "--approve-in-chat", "--approval-note", note, "--json"],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(ok_proc.returncode, 0, ok_proc.stdout + ok_proc.stderr)
            subs = json.loads((project / "review/review-submissions.json").read_text(encoding="utf-8"))
            self.assertEqual(len(subs["records"]), 1)
            self.assertEqual(subs["records"][0]["kind"], "chat-approval")
            self.assertEqual(subs["records"][0]["snapshot"], "snap-v21-01")
            self.assertEqual(subs["records"][0]["note"], note)


class DeliveryVerdict(unittest.TestCase):
    def test_burn_without_libass_fails_before_encoder(self):
        with tempfile.TemporaryDirectory() as td:
            project = Path(td); (project / 'edit').mkdir()
            visual = project / 'v.mp4'; audio = project / 'a.wav'; srt = project / 'captions.srt'
            visual.touch(); audio.touch(); srt.write_text('subtitle')
            with patch.object(deliver, '_preflight', return_value=(True, 1)), \
                 patch('probe_env.ffmpeg_capabilities', return_value={'filters':{}}), \
                 patch.object(deliver, '_run') as encoder, redirect_stdout(io.StringIO()):
                code = deliver.deliver(project, visual, None, audio, srt, None, True, True, True, no_person=True)
            self.assertNotEqual(code, 0); encoder.assert_not_called()

    def test_failed_preflight_environment_selector_or_film_never_encodes(self):
        for failure in ('environment', 'film', 'hyperframes', 'selector'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as td:
                project = Path(td); (project/'edit').mkdir(); (project/'composition').mkdir(); (project/'pages').mkdir()
                (project/'composition/index.html').write_text('<script src="anim.js"></script>')
                (project/'composition/anim.js').write_text('gsap.to(".missing", {x:1})')
                calls=[]
                def run(cmd):
                    calls.append(cmd)
                    failed = ((failure == 'film' and 'film.py' in ' '.join(cmd))
                              or (failure == 'hyperframes' and cmd[:2] == ['hyperframes','check'])
                              or (failure == 'selector' and 'check_motion_targets.py' in ' '.join(cmd)))
                    return subprocess.CompletedProcess(cmd, 1 if failed else 0, 'invalid source' if failed else '{}', '')
                with patch.object(deliver, '_run', side_effect=run), \
                     patch.object(deliver, '_render_env', return_value=(failure!='environment',1,'fixture')), \
                     redirect_stdout(io.StringIO()):
                    code=deliver.deliver(project,None,None,None,None,None,False,True,True,no_person=True,render=True)
                self.assertNotEqual(code,0)
                self.assertFalse(any(c[0]=='ffmpeg' or c[:2]==['hyperframes','render'] for c in calls),calls)

    def test_explicit_unproven_visuals_are_blocked_before_encoding(self):
        with tempfile.TemporaryDirectory() as td:
            project = Path(td); (project / 'edit').mkdir()
            visual = project / 'external.mp4'; audio = project / 'voice.wav'
            visual.write_bytes(b'visual'); audio.write_bytes(b'audio')
            with patch.object(deliver, '_preflight', return_value=(True, 1)), \
                 patch.object(deliver, '_run') as encoder, redirect_stdout(io.StringIO()):
                code = deliver.deliver(project, visual, None, audio, None, None, False, True, True, no_person=True)
            self.assertNotEqual(code, 0); encoder.assert_not_called()

    def test_visual_proof_detects_same_metadata_change_and_source_deletion(self):
        with tempfile.TemporaryDirectory() as td:
            project = Path(td); (project / 'composition').mkdir()
            css = project / 'composition/style.css'; css.write_bytes(b'old')
            visual = project / 'external.mp4'; visual.write_bytes(b'visual')
            self.assertTrue(deliver._render_is_stale(project, visual))
            deliver._record_visual_source(project, visual, 'manual-confirmation')
            self.assertFalse(deliver._render_is_stale(project, visual))
            stat = css.stat(); css.write_bytes(b'new'); os.utime(css, ns=(stat.st_atime_ns, stat.st_mtime_ns))
            self.assertTrue(deliver._render_is_stale(project, visual))
            deliver._record_visual_source(project, visual, 'manual-confirmation'); css.unlink()
            self.assertTrue(deliver._render_is_stale(project, visual))

    def run_verdict(self, result=None, *, edl=True):
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            (project / "edit").mkdir()
            if edl:
                (project / "edit/edl.json").write_text('{"ranges": []}')
            visual, audio = project / "visual.mp4", project / "audio.m4a"
            visual.touch(); audio.touch()
            def compose(cmd):
                Path(cmd[-1]).touch()
                return subprocess.CompletedProcess(cmd, 0, "", "")
            video = {"width": 1920, "height": 1080, "r_frame_rate": "30/1"}
            with patch.object(deliver, "_run", side_effect=compose), \
                 patch.object(deliver, "_preflight", return_value=(True, 1)), \
                 patch.object(deliver, "_streams", return_value=(video, {"codec_name": "aac"})), \
                 patch.object(deliver, "_duration", return_value=1.0), \
                 patch.object(deliver, "_frame_luma", side_effect=lambda p,t,crop=None: 10), \
                 patch.object(deliver.subprocess, "run", side_effect=result if isinstance(result, Exception) else None,
                              return_value=result), redirect_stdout(io.StringIO()):
                code = deliver.deliver(project, visual, None, audio, None, None,
                                       False, True, True, no_person=True, visuals_confirm_current=True)
            report = json.loads((project / "成品" / f"{project.name}_核验报告.json").read_text())
            return code, report

    def test_strict_failure_blocks_overall_success(self):
        result = subprocess.CompletedProcess([], 1, json.dumps({"ok": False, "hard": ["wrong timeline"], "warn": []}), "")
        code, report = self.run_verdict(result)
        self.assertNotEqual(code, 0, report)
        self.assertFalse(report["ok"])
        self.assertTrue(report["composition_ok"])
        self.assertIn("wrong timeline", report["delivery_verdict"]["hard"])

    def test_strict_success_accepts_existing_diagnostic_preamble(self):
        payload = {"ok": True, "hard": [], "warn": []}
        code, report = self.run_verdict(subprocess.CompletedProcess([], 0, "diagnostic\n" + json.dumps(payload), ""))
        self.assertEqual(code, 0, report)
        self.assertTrue(report["delivery_ok"])

    def test_invalid_or_crashed_verifier_cannot_pass(self):
        for result in (subprocess.CompletedProcess([], 0, "not JSON", ""),
                       subprocess.CompletedProcess([], 0, '{}', ""),
                       subprocess.CompletedProcess([], 0, '{"ok":true,"hard":["bad"],"warn":[]}', ""),
                       OSError("verifier unavailable")):
            with self.subTest(result=result):
                code, report = self.run_verdict(result)
                self.assertNotEqual(code, 0, report)
                self.assertFalse(report["delivery_ok"])

    def test_missing_edl_is_explicitly_unverified(self):
        code, report = self.run_verdict(edl=False)
        self.assertNotEqual(code, 0, report)
        self.assertEqual(report["delivery_verdict"]["status"], "not-run")

    def test_explicit_visuals_do_not_bypass_failed_film_preflight(self):
        with tempfile.TemporaryDirectory() as td:
            project = Path(td); (project / "edit").mkdir(); (project / "composition").mkdir()
            (project / "composition/index.html").write_text('<div data-duration="1"></div>')
            (project / "pages").mkdir(parents=True)
            visual, audio = project / "visual.mp4", project / "audio.m4a"
            visual.touch(); audio.touch()
            encoded = []
            def run(cmd):
                if cmd[0] in ("ffmpeg", "hyperframes") and "render" in cmd or cmd[0] == "ffmpeg":
                    encoded.append(cmd)
                return subprocess.CompletedProcess(cmd, 1, "missing film mapping", "")
            with patch.object(deliver, "_run", side_effect=run), \
                 patch.object(deliver, "_render_env", return_value=(True, 1, "ok")), \
                 patch.object(deliver, "_streams", return_value=({"width": 1920,"height":1080,"r_frame_rate":"30/1"}, {"codec_name":"aac"})), redirect_stdout(io.StringIO()):
                code = deliver.deliver(project, visual, None, audio, None, None,
                                       False, True, True, no_person=True)
            self.assertNotEqual(code, 0)
            self.assertEqual(encoded, [])


def _have(tool: str) -> bool:
    return shutil.which(tool) is not None


@unittest.skipUnless(_have("ffmpeg") and _have("ffprobe"), "需要 ffmpeg/ffprobe")
class DeliverIntegration(unittest.TestCase):
    def _fixture(self, tmp: Path, band_content: bool) -> Path:
        assets = tmp / "composition/assets"
        (tmp / "composition/_render").mkdir(parents=True, exist_ok=True)
        assets.mkdir(parents=True, exist_ok=True)
        box = "drawbox=x=700:y=200:w=1000:h=500:color=0xF2EBDD@1:t=fill"
        if band_content:  # 故意画进 y>880 的字幕区
            box += ",drawbox=x=700:y=920:w=1000:h=100:color=0xE2F827@1:t=fill"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                        "-i", "color=c=0x050607:s=1920x1080:r=30:d=1", "-vf", box,
                        "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        str(tmp / "composition/_render/visuals.mp4")], check=True)
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                        "-i", "testsrc2=s=720x1280:r=30:d=1", "-c:v", "libx264",
                        "-pix_fmt", "yuv420p", str(assets / "person.mp4")], check=True)
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                        "-i", "sine=frequency=440:duration=1", "-c:a", "aac",
                        str(assets / "audio.m4a")], check=True)
        (tmp / "recompose.json").write_text(json.dumps({
            "canvas": {"w": 1920, "h": 1080, "fps": 30},
            "personSlot": {"x": 0, "y": 0, "w": 500, "h": 1080},
            "captionSafe": {"x": 0, "y": 880, "w": 1920, "h": 200},
        }), encoding="utf-8")
        self._edl(tmp)
        return tmp

    def _edl(self, tmp: Path):
        from _edl import edl_digest
        edit = tmp / "edit"
        edit.mkdir(exist_ok=True)
        edl = edit / "edl.json"
        edl.write_text(json.dumps({"ranges": [{"start": 0, "end": 1}]}))
        (edit / "segment_durations.json").write_text(json.dumps({"final": {"durations": [1.0], "total_s": 1.0, "edl_sha256": edl_digest(edl)}}))
        visual = tmp / 'composition/_render/visuals.mp4'
        if visual.is_file(): deliver._record_visual_source(tmp, visual, 'manual-confirmation')

    def _run(self, tmp: Path, *, composite: bool = False) -> dict:
        self._edl(tmp)
        code = deliver.deliver(tmp, None, None, None, None, tmp / "成品", False, True, True, composite=composite)
        report = tmp / "成品" / f"{tmp.name}_核验报告.json"
        data = json.loads(report.read_text(encoding="utf-8")) if report.is_file() else {}
        data["exit"] = code
        return data

    def test_clean_visual_layer_passes_and_has_audio(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = self._fixture(Path(td) / "demo", band_content=False)
            tmp.mkdir(parents=True, exist_ok=True)
            data = self._run(tmp)
            self.assertEqual(data["exit"], 0, data)
            names = {c["name"]: c for c in data["checks"]}
            self.assertTrue(names["成片有音轨"]["ok"], names["成片有音轨"])
            self.assertTrue(names["字幕安全区无内容"]["ok"], names["字幕安全区无内容"])

    def test_render_cache_older_than_composition_is_stale(self):
        """改过 composition 之后，旧的 _render/visuals.mp4 必须被判为新旧不符并重渲，
        否则审阅看的是新的、交付的是旧的。"""
        import os
        import time
        with tempfile.TemporaryDirectory() as td:
            tmp = self._fixture(Path(td) / "demo", band_content=False)
            tmp.mkdir(parents=True, exist_ok=True)
            comp = tmp / "composition"
            (comp / "index.html").write_text("<!doctype html><div></div>", encoding="utf-8")
            visual = comp / "_render/visuals.mp4"
            now = time.time()
            os.utime(visual, (now - 500, now - 500))
            self.assertTrue(deliver._render_is_stale(tmp, visual))
            for path in comp.rglob("*"):
                if path.is_file() and "_render" not in path.parts and path.suffix != ".mp4":
                    os.utime(path, (now - 900, now - 900))
            self.assertTrue(deliver._render_is_stale(tmp, visual))  # mtime cannot prove provenance
            deliver._record_visual_source(tmp, visual, 'manual-confirmation')
            self.assertFalse(deliver._render_is_stale(tmp, visual))

    def test_no_person_layer_delivers_without_person(self):
        """纯画面 + 旁白的片子没有人物素材：--no-person 应该能出片，
        而不是把「人物素材缺失」当硬错误（recompose-mode 允许「仅画面层」）。"""
        with tempfile.TemporaryDirectory() as td:
            tmp = self._fixture(Path(td) / "demo", band_content=False)
            tmp.mkdir(parents=True, exist_ok=True)
            (tmp / "composition/assets/person.mp4").unlink()
            deliver._record_visual_source(tmp, tmp / 'composition/_render/visuals.mp4', 'manual-confirmation')
            code = deliver.deliver(tmp, None, None, None, None, tmp / "成品",
                                   False, True, True, no_person=True)
            report = tmp / "成品" / f"{tmp.name}_核验报告.json"
            data = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(code, 0, data)
            self.assertTrue(data["ok"])
            self.assertTrue(any("无人物轨" in n for n in data["notes"]), data["notes"])

    def test_duration_follows_visual_layer_when_person_runs_longer(self):
        """人物/旁白比画面层长时，成片时长必须跟画面层走。

        2026-10-21 的真实素材上，母版 368.4s、画面层 367.6s，只写 `-shortest`
        在 filter_complex + overlay 下没截断，交付出 368.33s，核验「时长」报红。
        现在用 `-t <画面层时长>` 钉住；这条测试防它回来。
        """
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "demo"
            assets = tmp / "composition/assets"
            (tmp / "composition/_render").mkdir(parents=True, exist_ok=True)
            assets.mkdir(parents=True, exist_ok=True)
            # 画面层 1s，人物与旁白各 2s
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                            "-i", "color=c=0x050607:s=1920x1080:r=30:d=1",
                            "-vf", "drawbox=x=700:y=200:w=1000:h=500:color=0xF2EBDD@1:t=fill",
                            "-c:v", "libx264", "-pix_fmt", "yuv420p",
                            str(tmp / "composition/_render/visuals.mp4")], check=True)
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                            "-i", "testsrc2=s=720x1280:r=30:d=2", "-c:v", "libx264",
                            "-pix_fmt", "yuv420p", str(assets / "person.mp4")], check=True)
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                            "-i", "sine=frequency=440:duration=2", "-c:a", "aac",
                            str(assets / "audio.m4a")], check=True)
            (tmp / "recompose.json").write_text(json.dumps({
                "canvas": {"w": 1920, "h": 1080, "fps": 30},
                "personSlot": {"x": 0, "y": 0, "w": 500, "h": 1080},
                "captionSafe": {"x": 0, "y": 880, "w": 1920, "h": 200},
            }), encoding="utf-8")

            data = self._run(tmp, composite=True)
            self.assertEqual(data["exit"], 0, data)
            names = {c["name"]: c for c in data["checks"]}
            self.assertTrue(names["时长"]["ok"], names["时长"])
            out = tmp / "成品" / f"{tmp.name}_成片.mp4"
            got = float(deliver._duration(out))
            self.assertAlmostEqual(got, 1.0, delta=0.15, msg=f"成片 {got:.2f}s，应跟画面层 1s")

            # Default split mode also caps 人物成片 to 画面成片 duration within 0.5s
            split_out = tmp / "成品分轨"
            with redirect_stdout(io.StringIO()):
                split_code = deliver.deliver(tmp, None, None, None, None, split_out, False, True, True)
            self.assertEqual(split_code, 0)
            p_dur = float(deliver._duration(split_out / f"{tmp.name}_人物成片.mp4"))
            v_dur = float(deliver._duration(split_out / f"{tmp.name}_画面成片.mp4"))
            self.assertLessEqual(abs(p_dur - v_dur), 0.5, (p_dur, v_dur))

    def test_missing_person_still_red_without_flag(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = self._fixture(Path(td) / "demo", band_content=False)
            tmp.mkdir(parents=True, exist_ok=True)
            (tmp / "composition/assets/person.mp4").unlink()
            code = deliver.deliver(tmp, None, None, None, None, tmp / "成品",
                                   False, True, True)
            self.assertEqual(code, 1)

    def test_content_in_caption_band_goes_red(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = self._fixture(Path(td) / "demo", band_content=True)
            tmp.mkdir(parents=True, exist_ok=True)
            data = self._run(tmp)
            self.assertEqual(data["exit"], 1, data)
            names = {c["name"]: c for c in data["checks"]}
            self.assertFalse(names["字幕安全区无内容"]["ok"], names["字幕安全区无内容"])

    def test_missing_visual_layer_is_refused_without_render_flag(self):
        """审阅停在工程态：没有画面层时 deliver 必须拒绝，不能自动渲染。"""
        with tempfile.TemporaryDirectory() as td:
            tmp = self._fixture(Path(td) / "demo", band_content=False)
            (tmp / "composition/_render/visuals.mp4").unlink()
            code = deliver.deliver(tmp, None, None, None, None, tmp / "成品",
                                   False, True, False, True)
            report = tmp / "成品" / f"{tmp.name}_核验报告.json"
            data = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(code, 1)
            self.assertFalse(data["ok"])
            self.assertTrue([c for c in data["checks"] if c["name"] == "画面层" and not c["ok"]])

    def test_burned_subtitle_is_visible_for_both_person_routes(self):
        # A locally installed libass build exercises actual encoded pixels.
        libass_dir = Path("/opt/homebrew/opt/ffmpeg@7/bin")
        with patch.dict(os.environ, {"PATH": str(libass_dir) + os.pathsep + os.environ["PATH"]}):
            import probe_env
            if not probe_env.ffmpeg_capabilities()["filters"].get("subtitles"):
                self.skipTest("libass unavailable")
            for no_person in (False, True):
                with self.subTest(no_person=no_person), tempfile.TemporaryDirectory() as td:
                    project = self._fixture(Path(td) / "demo 空格", False)
                    srt = project / "edit" / "字幕 '含冒号:.srt"
                    srt.write_text("1\n00:00:00,200 --> 00:00:00,750\nCAPTION\n")
                    (project / "edit/subtitles.srt").write_bytes(srt.read_bytes())
                    deliver._record_visual_source(project, project / 'composition/_render/visuals.mp4', 'manual-confirmation')
                    values = []
                    for burn in (False, True):
                        out = project / ("burn" if burn else "sidecar")
                        with redirect_stdout(io.StringIO()):
                            code = deliver.deliver(project, None, None, None, srt, out,
                                                   burn, True, True, no_person=no_person,
                                                   composite=not no_person)
                        self.assertEqual(code, 0, (out / f"{project.name}_核验报告.json").read_text())
                        video = out / f"{project.name}_成片.mp4"
                        values.append(deliver._frame_luma(video, .5, (1920, 200, 0, 880)))
                        if burn:
                            before = deliver._frame_luma(video, .1, (1920, 200, 0, 880))
                            self.assertGreater(values[-1], before + .3)
                    self.assertGreater(values[1], values[0] + .3, values)

    def test_mixed_motion_and_demo_footage_splices_hd_demo_and_keeps_person_separate(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "demo_splice"
            assets = tmp / "composition/assets"
            rec_dir = tmp / "recordings"
            (tmp / "composition/_render").mkdir(parents=True, exist_ok=True)
            assets.mkdir(parents=True, exist_ok=True)
            rec_dir.mkdir(parents=True, exist_ok=True)

            # 3s motion base: dark 0x050607 canvas with cream motion band in upper-right only (y=100..420)
            subprocess.run([
                "ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                "-i", "color=c=0x050607:s=1920x1080:r=30:d=3",
                "-vf", "drawbox=x=700:y=100:w=900:h=320:color=0xF2EBDD@1:t=fill",
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                str(tmp / "composition/_render/visuals.mp4"),
            ], check=True)
            # 2s HD demo recording stored outside composition/assets/ (bright sky blue)
            subprocess.run([
                "ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                "-i", "color=c=0x7DD3FC:s=1920x1080:r=30:d=2",
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                str(rec_dir / "hd_demo.mp4"),
            ], check=True)
            subprocess.run([
                "ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                "-i", "testsrc2=s=720x1280:r=30:d=3", "-c:v", "libx264",
                "-pix_fmt", "yuv420p", str(assets / "person.mp4"),
            ], check=True)
            subprocess.run([
                "ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                "-i", "sine=frequency=440:duration=3", "-c:a", "aac",
                str(assets / "audio.m4a"),
            ], check=True)
            (tmp / "recompose.json").write_text(json.dumps({
                "canvas": {"w": 1920, "h": 1080, "fps": 30},
                "personSlot": {"x": 0, "y": 0, "w": 500, "h": 1080},
                "captionSafe": {"x": 0, "y": 880, "w": 1920, "h": 200},
            }), encoding="utf-8")
            (tmp / "visual-plan.json").write_text(json.dumps({
                "version": 2,
                "segments": [
                    {"id": "seg-01", "beatId": "b1", "tier": "talk-only", "startMs": 0, "endMs": 900},
                    {"id": "seg-02", "beatId": "b2", "tier": "logic-diagram", "startMs": 900, "endMs": 1500,
                     "hero": "逻辑圈", "anchors": ["洞察"]},
                    {"id": "seg-03", "beatId": "b3", "tier": "demo-footage", "startMs": 1500, "endMs": 2700,
                     "demo": {"source": "recordings/hd_demo.mp4", "inSec": 0.2, "outSec": 1.4, "speed": 1.0}},
                    {"id": "seg-04", "beatId": "b4", "tier": "talk-only", "startMs": 2700, "endMs": 3000},
                ],
            }), encoding="utf-8")
            from _edl import edl_digest
            edit = tmp / "edit"
            edit.mkdir(exist_ok=True)
            edl = edit / "edl.json"
            edl.write_text(json.dumps({"ranges": [{"start": 0, "end": 3}]}))
            (edit / "segment_durations.json").write_text(json.dumps({
                "final": {"durations": [3.0], "total_s": 3.0, "edl_sha256": edl_digest(edl)},
            }))
            deliver._record_visual_source(tmp, tmp / "composition/_render/visuals.mp4", "manual-confirmation")

            with redirect_stdout(io.StringIO()):
                code = deliver.deliver(tmp, None, None, None, None, tmp / "成品", False, True, True)
            report = json.loads((tmp / "成品" / f"{tmp.name}_核验报告.json").read_text(encoding="utf-8"))
            self.assertEqual(code, 0, report)
            self.assertTrue(report["ok"], report)
            self.assertEqual(report["demo_splice"]["count"], 1)
            self.assertTrue(report["demo_splice"]["screen_text_protection"])

            visual_track = tmp / "成品" / f"{tmp.name}_画面成片.mp4"
            person_track = tmp / "成品" / f"{tmp.name}_人物成片.mp4"
            final_video = tmp / "成品" / f"{tmp.name}_成片.mp4"
            self.assertTrue(visual_track.is_file())
            self.assertTrue(person_track.is_file())
            self.assertFalse(final_video.exists())
            pv, pa = deliver._streams(person_track)
            self.assertEqual((pv.get("width"), pv.get("height")), (720, 1280))
            self.assertEqual(pa.get("channels"), 2)

            vt_v, vt_a = deliver._streams(visual_track)
            self.assertEqual((vt_v.get("width"), vt_v.get("height")), (1920, 1080))
            self.assertEqual(vt_a, {})
            self.assertAlmostEqual(deliver._duration(visual_track), 3.0, delta=0.15)
            # Lower stage band (y=600..800, x=1000..1200) is dark before demo, bright sky-blue during [1.5..2.7s]
            before_luma = deliver._frame_luma(visual_track, 0.4, (200, 160, 1000, 620))
            demo_luma = deliver._frame_luma(visual_track, 2.1, (200, 160, 1000, 620))
            after_luma = deliver._frame_luma(visual_track, 2.85, (200, 160, 1000, 620))
            self.assertLess(before_luma, 20.0)
            self.assertGreater(demo_luma, 100.0)
            self.assertLess(after_luma, 20.0)


@unittest.skipUnless(_have("ffmpeg") and _have("ffprobe"), "需要 ffmpeg/ffprobe")
class SplitDeliveryContractTests(unittest.TestCase):
    def _make_video(self, path: Path, *, size: str, dur: float, vf: str | None = None, color: str | None = None) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        lavfi = f"color=c={color}:s={size}:r=30:d={dur}" if color else f"testsrc2=s={size}:r=30:d={dur}"
        cmd = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", lavfi]
        if vf:
            cmd += ["-vf", vf]
        cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)]
        subprocess.run(cmd, check=True)

    def _make_audio(self, path: Path, *, dur: float) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([
            "ffmpeg", "-y", "-v", "error", "-f", "lavfi",
            "-i", f"sine=frequency=440:duration={dur}",
            "-c:a", "aac", "-ar", "48000", "-ac", "2", str(path),
        ], check=True)

    def test_default_split_delivery_outputs_three_piece_tracks_with_gap_fixed_srt(self):
        with tempfile.TemporaryDirectory() as td:
            project = (Path(td) / "split_demo").resolve()
            (project / "composition/_render").mkdir(parents=True)
            (project / "composition/assets").mkdir(parents=True)
            (project / "edit").mkdir(parents=True)

            # Dark talk-only opening for first 0.6s, bright stage thereafter (empty captionSafe y>=880)
            self._make_video(
                project / "composition/_render/visuals.mp4",
                size="1920x1080",
                dur=1.5,
                color="0x030405",
                vf="drawbox=x=700:y=200:w=1000:h=500:color=0xF2EBDD@1:t=fill:enable='gte(t,0.6)'",
            )
            # High-res edit/cut.mp4 (2.5s, 720x1280) vs decoy low-res composition/assets/person.mp4 (360x640)
            self._make_video(project / "edit/cut.mp4", size="720x1280", dur=2.5)
            self._make_video(project / "composition/assets/person.mp4", size="360x640", dur=2.5)
            self._make_audio(project / "composition/assets/audio.m4a", dur=2.5)

            (project / "recompose.json").write_text(json.dumps({
                "canvas": {"w": 1920, "h": 1080, "fps": 30},
                "personSlot": {"x": 0, "y": 0, "w": 500, "h": 1080},
                "captionSafe": {"x": 0, "y": 880, "w": 1920, "h": 200},
            }), encoding="utf-8")

            raw_srt = (
                "1\n00:00:00,000 --> 00:00:00,500\n第一句开场\n\n"
                "2\n00:00:00,500 --> 00:00:01,000\n第二句紧接\n\n"
                "3\n00:00:01,000 --> 00:00:01,420\n第三句收尾\n\n"
            )
            srt_file = project / "edit/subtitles.srt"
            srt_file.write_text(raw_srt, encoding="utf-8")

            from _edl import edl_digest
            edl = project / "edit/edl.json"
            edl.write_text(json.dumps({"ranges": [{"start": 0, "end": 1.5}]}), encoding="utf-8")
            (project / "edit/segment_durations.json").write_text(json.dumps({
                "final": {"durations": [1.5], "total_s": 1.5, "edl_sha256": edl_digest(edl)},
            }), encoding="utf-8")
            deliver._record_visual_source(project, project / "composition/_render/visuals.mp4", "manual-confirmation")

            env = dict(os.environ, DSH_TEST="1")
            proc = subprocess.run(
                [sys.executable, str(DELIVER_SCRIPT), str(project), "--skip-gate", "--json"],
                env=env, capture_output=True, text=True, check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            report = json.loads((project / "成品" / f"{project.name}_核验报告.json").read_text(encoding="utf-8"))
            self.assertTrue(report["ok"], report)
            self.assertTrue(report["delivery_ok"], report)
            self.assertEqual(report["delivery_mode"], "split")

            person_out = project / "成品" / f"{project.name}_人物成片.mp4"
            visual_out = project / "成品" / f"{project.name}_画面成片.mp4"
            srt_out = project / "成品" / f"{project.name}_字幕.srt"
            composite_out = project / "成品" / f"{project.name}_成片.mp4"

            self.assertTrue(person_out.is_file())
            self.assertTrue(visual_out.is_file())
            self.assertTrue(srt_out.is_file())
            self.assertFalse(composite_out.exists(), "default split mode must not emit composite video")
            self.assertEqual(report["output"], str(person_out))
            self.assertEqual(report["deliverables"], {
                "person": str(person_out),
                "visuals": str(visual_out),
                "subtitles": str(srt_out),
            })

            pv, pa = deliver._streams(person_out)
            self.assertEqual((pv.get("width"), pv.get("height")), (720, 1280))
            self.assertEqual(pa.get("codec_name"), "aac")
            self.assertEqual(pa.get("channels"), 2)

            vv, va = deliver._streams(visual_out)
            self.assertEqual((vv.get("width"), vv.get("height")), (1920, 1080))
            self.assertEqual(va, {}, "visual track must have 0 audio streams")

            dur_p = deliver._duration(person_out)
            dur_v = deliver._duration(visual_out)
            self.assertLessEqual(abs(dur_p - dur_v), 0.5, (dur_p, dur_v))

            # edit/subtitles.srt stays untouched; delivered SRT has >= 30ms gaps
            self.assertEqual(srt_file.read_text(encoding="utf-8"), raw_srt)
            from _timecode import parse_srt_file
            cues = parse_srt_file(srt_out)
            self.assertEqual(len(cues), 3)
            for i in range(len(cues) - 1):
                self.assertGreaterEqual(cues[i + 1]["startMs"] - cues[i]["endMs"], 30, cues)

    def test_person_source_priority_picks_highest_bitrate_candidate_in_order(self):
        candidates = [
            ("edit/cut.mp4", (640, 360)),
            ("composition/assets/person.mp4", (480, 270)),
            ("edit/_engineering/person_master.mp4", (320, 180)),
            ("edit/_engineering/cut.mp4", (160, 90)),
        ]
        for idx in range(len(candidates)):
            with self.subTest(expected=candidates[idx][0]), tempfile.TemporaryDirectory() as td:
                project = (Path(td) / f"prio_{idx}").resolve()
                (project / "composition/_render").mkdir(parents=True)
                (project / "composition/assets").mkdir(parents=True)
                (project / "edit/_engineering").mkdir(parents=True)

                self._make_video(
                    project / "composition/_render/visuals.mp4",
                    size="1920x1080", dur=1.0,
                    color="0x050607",
                    vf="drawbox=x=700:y=200:w=1000:h=500:color=0xF2EBDD@1:t=fill",
                )
                self._make_audio(project / "composition/assets/audio.m4a", dur=1.0)
                for rel, (w, h) in candidates[idx:]:
                    self._make_video(project / rel, size=f"{w}x{h}", dur=1.0)

                (project / "recompose.json").write_text(json.dumps({
                    "canvas": {"w": 1920, "h": 1080, "fps": 30},
                    "personSlot": {"x": 0, "y": 0, "w": 500, "h": 1080},
                    "captionSafe": {"x": 0, "y": 880, "w": 1920, "h": 200},
                }), encoding="utf-8")
                from _edl import edl_digest
                edl = project / "edit/edl.json"
                edl.write_text(json.dumps({"ranges": [{"start": 0, "end": 1.0}]}), encoding="utf-8")
                (project / "edit/segment_durations.json").write_text(json.dumps({
                    "final": {"durations": [1.0], "total_s": 1.0, "edl_sha256": edl_digest(edl)},
                }), encoding="utf-8")
                deliver._record_visual_source(project, project / "composition/_render/visuals.mp4", "manual-confirmation")

                with redirect_stdout(io.StringIO()):
                    code = deliver.deliver(project, None, None, None, None, project / "成品", False, True, True)
                self.assertEqual(code, 0)
                person_out = project / "成品" / f"{project.name}_人物成片.mp4"
                pv, _ = deliver._streams(person_out)
                self.assertEqual((pv.get("width"), pv.get("height")), candidates[idx][1])

    def _seed_composite_ready_project(self, project: Path, *, tight_srt: bool = True) -> Path:
        (project / "composition/_render").mkdir(parents=True)
        (project / "composition/assets").mkdir(parents=True)
        (project / "edit").mkdir(parents=True)
        self._make_video(
            project / "composition/_render/visuals.mp4",
            size="1920x1080", dur=1.5, color="0x050607",
            vf="drawbox=x=700:y=200:w=1000:h=500:color=0xF2EBDD@1:t=fill",
        )
        self._make_video(project / "edit/cut.mp4", size="720x1280", dur=1.5)
        self._make_audio(project / "composition/assets/audio.m4a", dur=1.5)
        (project / "recompose.json").write_text(json.dumps({
            "canvas": {"w": 1920, "h": 1080, "fps": 30},
            "personSlot": {"x": 0, "y": 0, "w": 500, "h": 1080},
            "captionSafe": {"x": 0, "y": 880, "w": 1920, "h": 200},
        }), encoding="utf-8")
        if tight_srt:
            (project / "edit/subtitles.srt").write_text(
                "1\n00:00:00,000 --> 00:00:00,500\n第一行\n\n"
                "2\n00:00:00,500 --> 00:00:01,000\n第二行\n\n"
                "3\n00:00:01,000 --> 00:00:01,420\n第三行\n\n",
                encoding="utf-8",
            )
        from _edl import edl_digest
        edl = project / "edit/edl.json"
        edl.write_text(json.dumps({"ranges": [{"start": 0, "end": 1.5}]}), encoding="utf-8")
        (project / "edit/segment_durations.json").write_text(json.dumps({
            "final": {"durations": [1.5], "total_s": 1.5, "edl_sha256": edl_digest(edl)},
        }), encoding="utf-8")
        deliver._record_visual_source(project, project / "composition/_render/visuals.mp4", "manual-confirmation")
        return project

    def test_explicit_composite_cli_and_mode_flag_produce_single_video_and_gap_fixed_srt(self):
        env = dict(os.environ, DSH_TEST="1")
        for flag in (["--composite"], ["--mode", "composite"]):
            with self.subTest(flag=flag), tempfile.TemporaryDirectory() as td:
                project = self._seed_composite_ready_project((Path(td) / "comp_proj").resolve())
                raw_srt = (project / "edit/subtitles.srt").read_text(encoding="utf-8")
                proc = subprocess.run(
                    [sys.executable, str(DELIVER_SCRIPT), str(project), "--skip-gate", *flag, "--json"],
                    env=env, capture_output=True, text=True, check=False,
                )
                self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
                report = json.loads((project / "成品" / f"{project.name}_核验报告.json").read_text(encoding="utf-8"))
                self.assertTrue(report["ok"], report)
                self.assertEqual(report["delivery_mode"], "composite")

                target = project / "成品" / f"{project.name}_成片.mp4"
                srt_out = project / "成品" / f"{project.name}_字幕.srt"
                self.assertTrue(target.is_file())
                self.assertTrue(srt_out.is_file())
                self.assertFalse((project / "成品" / f"{project.name}_人物成片.mp4").exists())
                self.assertFalse((project / "成品" / f"{project.name}_画面成片.mp4").exists())
                self.assertEqual(report["deliverables"], {"video": str(target), "subtitles": str(srt_out)})
                self.assertEqual((project / "edit/subtitles.srt").read_text(encoding="utf-8"), raw_srt)

                from _timecode import parse_srt_file
                cues = parse_srt_file(srt_out)
                self.assertEqual(len(cues), 3)
                for i in range(len(cues) - 1):
                    self.assertGreaterEqual(cues[i + 1]["startMs"] - cues[i]["endMs"], 30, cues)

    def test_no_person_cli_outputs_single_video_and_gap_fixed_srt(self):
        env = dict(os.environ, DSH_TEST="1")
        with tempfile.TemporaryDirectory() as td:
            project = self._seed_composite_ready_project((Path(td) / "noperson_proj").resolve())
            (project / "edit/cut.mp4").unlink()
            proc = subprocess.run(
                [sys.executable, str(DELIVER_SCRIPT), str(project), "--no-person", "--skip-gate", "--json"],
                env=env, capture_output=True, text=True, check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            report = json.loads((project / "成品" / f"{project.name}_核验报告.json").read_text(encoding="utf-8"))
            self.assertTrue(report["ok"], report)
            self.assertEqual(report["delivery_mode"], "no-person")
            target = project / "成品" / f"{project.name}_成片.mp4"
            srt_out = project / "成品" / f"{project.name}_字幕.srt"
            self.assertTrue(target.is_file())
            self.assertTrue(srt_out.is_file())
            self.assertFalse((project / "成品" / f"{project.name}_人物成片.mp4").exists())
            self.assertFalse((project / "成品" / f"{project.name}_画面成片.mp4").exists())
            from _timecode import parse_srt_file
            cues = parse_srt_file(srt_out)
            for i in range(len(cues) - 1):
                self.assertGreaterEqual(cues[i + 1]["startMs"] - cues[i]["endMs"], 30, cues)

    def test_pure_talking_project_delivers_person_and_gap_fixed_srt_without_empty_visual_track(self):
        env = dict(os.environ, DSH_TEST="1")
        with tempfile.TemporaryDirectory() as td:
            project = (Path(td) / "talking_proj").resolve()
            (project / "edit/_engineering").mkdir(parents=True)
            (project / "edit/project.md").write_text("production_mode: pure-talking\n", encoding="utf-8")
            self._make_video(project / "edit/cut.mp4", size="720x1280", dur=1.5)
            self._make_audio(project / "edit/_engineering/review_audio.m4a", dur=1.5)
            (project / "edit/subtitles.srt").write_text(
                "1\n00:00:00,000 --> 00:00:00,500\n纯口播第一句\n\n"
                "2\n00:00:00,500 --> 00:00:01,400\n纯口播第二句\n\n",
                encoding="utf-8",
            )
            from _edl import edl_digest
            edl = project / "edit/edl.json"
            edl.write_text(json.dumps({"ranges": [{"start": 0, "end": 1.5}]}), encoding="utf-8")
            (project / "edit/segment_durations.json").write_text(json.dumps({
                "final": {"durations": [1.5], "total_s": 1.5, "edl_sha256": edl_digest(edl)},
            }), encoding="utf-8")

            proc = subprocess.run(
                [sys.executable, str(DELIVER_SCRIPT), str(project), "--skip-gate", "--json"],
                env=env, capture_output=True, text=True, check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            report = json.loads((project / "成品" / f"{project.name}_核验报告.json").read_text(encoding="utf-8"))
            self.assertTrue(report["ok"], report)
            self.assertEqual(report["delivery_mode"], "pure-talking")
            person_out = project / "成品" / f"{project.name}_人物成片.mp4"
            srt_out = project / "成品" / f"{project.name}_字幕.srt"
            self.assertTrue(person_out.is_file())
            self.assertTrue(srt_out.is_file())
            self.assertFalse((project / "成品" / f"{project.name}_画面成片.mp4").exists())
            self.assertFalse((project / "成品" / f"{project.name}_成片.mp4").exists())
            self.assertEqual(report["deliverables"], {"person": str(person_out), "subtitles": str(srt_out)})
            pv, pa = deliver._streams(person_out)
            self.assertEqual((pv.get("width"), pv.get("height")), (720, 1280))
            self.assertEqual(pa.get("channels"), 2)

    def test_burn_subtitles_with_person_auto_switches_to_composite_via_cli(self):
        libass_dir = Path("/opt/homebrew/opt/ffmpeg@7/bin")
        with patch.dict(os.environ, {"PATH": str(libass_dir) + os.pathsep + os.environ["PATH"]}):
            import probe_env
            if not probe_env.ffmpeg_capabilities()["filters"].get("subtitles"):
                self.skipTest("libass unavailable")
            env = dict(os.environ, DSH_TEST="1")
            with tempfile.TemporaryDirectory() as td:
                project = self._seed_composite_ready_project((Path(td) / "burn_auto").resolve())
                proc = subprocess.run(
                    [sys.executable, str(DELIVER_SCRIPT), str(project),
                     "--burn-subtitles", "--skip-gate", "--json"],
                    env=env, capture_output=True, text=True, check=False,
                )
                self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
                report = json.loads((project / "成品" / f"{project.name}_核验报告.json").read_text(encoding="utf-8"))
                self.assertEqual(report["delivery_mode"], "composite")
                self.assertTrue((project / "成品" / f"{project.name}_成片.mp4").is_file())
                self.assertFalse((project / "成品" / f"{project.name}_人物成片.mp4").exists())

    def test_rerun_with_existing_delivered_srt_does_not_double_trim_gaps(self):
        with tempfile.TemporaryDirectory() as td:
            project = self._seed_composite_ready_project((Path(td) / "idemp_srt").resolve(), tight_srt=False)
            delivered_srt = project / "成品" / f"{project.name}_字幕.srt"
            delivered_srt.parent.mkdir(parents=True, exist_ok=True)
            already_fixed = (
                "1\n00:00:00,000 --> 00:00:00,460\n第一行\n\n"
                "2\n00:00:00,500 --> 00:00:01,400\n第二行\n\n"
            )
            delivered_srt.write_text(already_fixed, encoding="utf-8")
            with redirect_stdout(io.StringIO()):
                code = deliver.deliver(project, None, None, None, None, project / "成品", False, True, True)
            self.assertEqual(code, 0)
            self.assertEqual(delivered_srt.read_text(encoding="utf-8"), already_fixed)

    def test_state_fingerprint_and_stage_deliver_status_accept_split_delivery(self):
        with tempfile.TemporaryDirectory() as td:
            project = self._seed_composite_ready_project((Path(td) / "fp_split").resolve())
            # Add review snapshot + chat approval so stage_deliver status sees green gate
            from state_fingerprint import capture, compare, source_entries
            manifest = [
                {"path": k, "size": v["bytes"], "sha256": v["sha256"]}
                for k, v in source_entries(project).items()
            ]
            (project / "review").mkdir(parents=True, exist_ok=True)
            (project / "review/review_data.json").write_text(
                json.dumps({"snapshot": "snap-fp-01", "sourceManifest": manifest}),
                encoding="utf-8",
            )
            deliver._record_visual_source(project, project / "composition/_render/visuals.mp4", "manual-confirmation")

            proc = subprocess.run(
                [sys.executable, str(DELIVER_SCRIPT), str(project), "--approve-in-chat", "--json"],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            doc = capture(project)
            (project / "成品/delivery.json").write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
            self.assertEqual(compare(doc, capture(project)), [])

            import stage_deliver
            out_buf = io.StringIO()
            with redirect_stdout(out_buf):
                rc = stage_deliver.main(["status", "--project", str(project), "--json"])
            self.assertEqual(rc, 0)
            st = json.loads(out_buf.getvalue())["state"]
            self.assertTrue(st["gate"]["ok"], st)
            self.assertTrue(st["report_current"], st)
            self.assertTrue(st["fingerprint_current"], st)
            self.assertTrue(st["stage_complete"], st)

    def test_split_delivery_flags_black_visual_mid_tail_and_verify_delivery_dir_tolerates_silent_visual(self):
        with tempfile.TemporaryDirectory() as td:
            project = self._seed_composite_ready_project((Path(td) / "split_blk").resolve())
            env = dict(os.environ, DSH_TEST="1")
            # Good split run first -> verify_delivery --deliver-dir accepts silent 画面成片.mp4
            ok_proc = subprocess.run(
                [sys.executable, str(DELIVER_SCRIPT), str(project), "--skip-gate", "--json"],
                env=env, capture_output=True, text=True, check=False,
            )
            self.assertEqual(ok_proc.returncode, 0, ok_proc.stdout + ok_proc.stderr)
            vd = subprocess.run(
                [sys.executable, str(DELIVER_SCRIPT.parent / "_internal" / "verify_delivery.py"), str(project / "edit"),
                 "--video", str(project / "成品" / f"{project.name}_人物成片.mp4"),
                 "--deliver-dir", str(project / "成品"), "--json"],
                capture_output=True, text=True, check=False,
            )
            vd_payload = deliver._delivery_verdict(project / "edit", project / "成品" / f"{project.name}_人物成片.mp4")
            self.assertTrue(vd_payload["ok"], vd.stdout + vd.stderr)
            # Direct CLI check with --deliver-dir must not complain about missing audio channels on _画面成片.mp4
            self.assertNotIn("声道数 None", vd.stdout + vd.stderr)

            # Corrupt visual track to pure black -> split delivery must fail 画面中帧/尾帧非全黑
            self._make_video(project / "composition/_render/visuals.mp4", size="1920x1080", dur=1.5, color="0x020202")
            deliver._record_visual_source(project, project / "composition/_render/visuals.mp4", "manual-confirmation")
            bad_proc = subprocess.run(
                [sys.executable, str(DELIVER_SCRIPT), str(project), "--skip-gate", "--json"],
                env=env, capture_output=True, text=True, check=False,
            )
            self.assertNotEqual(bad_proc.returncode, 0)
            bad_report = json.loads((project / "成品" / f"{project.name}_核验报告.json").read_text(encoding="utf-8"))
            failed_names = {c["name"] for c in bad_report["checks"] if not c["ok"]}
            self.assertTrue("画面中帧非全黑" in failed_names or "画面尾帧非全黑" in failed_names, bad_report["checks"])


if __name__ == "__main__":
    unittest.main()
