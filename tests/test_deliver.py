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

import deliver  # noqa: E402


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

    def _run(self, tmp: Path) -> dict:
        self._edl(tmp)
        code = deliver.deliver(tmp, None, None, None, None, tmp / "成品", False, True, True)
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

            data = self._run(tmp)
            self.assertEqual(data["exit"], 0, data)
            names = {c["name"]: c for c in data["checks"]}
            self.assertTrue(names["时长"]["ok"], names["时长"])
            out = tmp / "成品" / f"{tmp.name}_成片.mp4"
            got = float(deliver._duration(out))
            self.assertAlmostEqual(got, 1.0, delta=0.15, msg=f"成片 {got:.2f}s，应跟画面层 1s")

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
                                                   burn, True, True, no_person=no_person)
                        self.assertEqual(code, 0, (out / f"{project.name}_核验报告.json").read_text())
                        video = out / f"{project.name}_成片.mp4"
                        values.append(deliver._frame_luma(video, .5, (1920, 200, 0, 880)))
                        if burn:
                            before = deliver._frame_luma(video, .1, (1920, 200, 0, 880))
                            self.assertGreater(values[-1], before + .3)
                    self.assertGreater(values[1], values[0] + .3, values)


if __name__ == "__main__":
    unittest.main()
