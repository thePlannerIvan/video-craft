#!/usr/bin/env python3
"""check_review_playable 的纯逻辑单测（不启浏览器、不起宿主）。

浏览器断言那部分靠真实项目与 /tmp 夹具验收；这里钉住"取哪些 seek 点、期望时长怎么算"
这类一旦写错就会让检查**静默失效**的地方 —— 2026-10-21 的 0 秒事故里，
正是"看起来对的数字"让整轮排查走错方向。
"""
from __future__ import annotations

import sys
import unittest
import tempfile
import json
import io
from contextlib import redirect_stdout
from unittest.mock import patch
from pathlib import Path

HELPERS = Path(__file__).parents[1] / "helpers"
sys.path.insert(0, str(HELPERS))
sys.path.insert(0, str(HELPERS / "_internal"))
sys.path.insert(0, str(HELPERS / "_internal"))

import check_review_playable as crp  # noqa: E402


def _import_review_host():
    from lib.planners_modules import resolve_module
    lib_dir = str(resolve_module("planners-review-core") / "scripts" / "lib")
    if lib_dir not in sys.path:
        sys.path.insert(0, lib_dir)
    import review_host
    return review_host


class ExpectedDuration(unittest.TestCase):
    def test_prefers_totalDurationMs(self):
        self.assertEqual(crp._expected_duration({"totalDurationMs": 367610}), 367.61)

    def test_falls_back_to_timeline_chapters(self):
        data = {"timeline": {"chapters": [{"endMs": 20000}, {"endMs": 61000}]}}
        self.assertEqual(crp._expected_duration(data), 61.0)

    def test_none_when_nothing_known(self):
        self.assertIsNone(crp._expected_duration({}))


class SeekPoints(unittest.TestCase):
    def test_skips_zero_and_caps_at_three(self):
        data = {"beats": [{"startMs": 0}, {"startMs": 20000}, {"startMs": 110000},
                          {"startMs": 220000}, {"startMs": 350000}]}
        self.assertEqual(crp._seek_points(data, []), [20.6, 110.6, 220.6])

    def test_explicit_override_wins(self):
        self.assertEqual(crp._seek_points({"beats": [{"startMs": 5000}]}, [12.0, 30.0]),
                         [12.0, 30.0])

    def test_falls_back_to_timeline_steps(self):
        data = {"timeline": {"chapters": [{"steps": [{"startMs": 0}, {"startMs": 40000}]}]}}
        self.assertEqual(crp._seek_points(data, []), [40.6])


class UsableAudio(unittest.TestCase):
    """「能出声」的判据：解码就绪 + 未静音 + 有音量 + 有长度（不要求时钟在推进）。"""

    def _ch(self, **kw):
        base = {"tag": "audio", "timed": True, "muted": False, "volume": 1.0,
                "readyState": 4, "duration": 368.4, "advanced": False, "paused": True}
        base.update(kw)
        return base

    def test_decoded_unmuted_paused_still_counts(self):
        # 页面停在 seek 点时官方播放器会主动暂停媒体：没推进不代表没声音
        self.assertEqual(len(crp._usable_audio([self._ch()])), 1)

    def test_muted_is_not_usable(self):
        self.assertEqual(crp._usable_audio([self._ch(muted=True)]), [])

    def test_zero_volume_is_not_usable(self):
        self.assertEqual(crp._usable_audio([self._ch(volume=0.0)]), [])

    def test_undecoded_is_not_usable(self):
        self.assertEqual(crp._usable_audio([self._ch(readyState=0)]), [])


class ServedProjectGuard(unittest.TestCase):
    def test_actual_route_proof_rejects_other_directory_even_with_same_body(self):
        import live_stage
        with tempfile.TemporaryDirectory() as td:
            comp = Path(td); (comp / 'index.html').write_text('<div data-duration="10"></div>')
            def response(url):
                if url.endswith('/api/projects'):
                    return json.dumps({'projects':[{'id':'composition', 'dir':'/another/composition'}]})
                return '<script data-hf-gsap-fallback></script><div data-duration="10"></div>'
            with patch.object(live_stage, 'fetch', side_effect=response):
                ok, reason = live_stage.prove_stage_route('http://localhost:9000', 'composition', comp)
            self.assertFalse(ok); self.assertIn('目录', reason)

    """端口上端出来的必须是本工程：三条片同 id `composition`，挤同一端口会互相顶掉。"""

    def test_same_duration_counts_as_same_project(self):
        import review as rv
        self.assertTrue(rv._same_project(354.10, 354.85))

    def test_another_projects_duration_is_rejected(self):
        import review as rv
        # V2 期望 354.10，端口回报 V1 的 367.61 → 必须判成"不是本工程"
        self.assertFalse(rv._same_project(354.10, 367.61))

    def test_unknown_values_are_not_judged(self):
        import review as rv
        self.assertIsNone(rv._same_project(None, 367.61))
        self.assertIsNone(rv._same_project(354.10, None))

    def test_current_timeline_wins_over_old_snapshot(self):
        import review as rv
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            (project / "review").mkdir(); (project / "timeline").mkdir(); (project / "edit").mkdir()
            (project / "review/review_data.json").write_text('{"totalDurationMs":10000}')
            (project / "timeline/timeline.json").write_text('{"totalDurationMs":12000,"chapters":[{"steps":[{"endMs":12000}]}]}')
            self.assertEqual(rv._expected_duration(project), 12.0)

    def test_old_snapshot_is_not_current_duration_evidence(self):
        import review as rv
        with tempfile.TemporaryDirectory() as td:
            project = Path(td); (project / "review").mkdir()
            (project / "review/review_data.json").write_text('{"totalDurationMs":10000}')
            self.assertIsNone(rv._expected_duration(project))

    def test_same_length_foreign_identity_fails_with_machine_readable_reason(self):
        import review as rv
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            (project / "review").mkdir(); (project / "edit").mkdir()
            (project / "review/index.html").touch(); (project / "review/review-surface.json").write_text('{}')
            (project / "review/review_data.json").write_text('{"totalDurationMs":10000}')
            info = {"ok": True, "stageUrl": "http://localhost:9000/stage", "identity": {
                "verified": True, "projectRoot": "/another/project", "compositionRoot": "/another/project/composition"}}
            def run(args):
                return 0, json.dumps(info) if "live_stage.py" in args[0] else '{}'
            output = io.StringIO()
            with patch.object(rv,"_run",side_effect=run), patch.object(rv,"_served_timeline_duration",return_value=10.), redirect_stdout(output):
                code = rv.review(project, open_surface=False, as_json=True, port=9000)
            self.assertNotEqual(code, 0)
            result = json.loads(output.getvalue())
            self.assertFalse(result["ok"])
            self.assertTrue(result["steps"][-1]["fix"])


class PlayableProbeHostLifecycle(unittest.TestCase):
    """check_review_playable.run() 必须传 surface_path 给 open_review，并按归属传 started 给 stop_host。"""

    def _seed_project(self, root: Path) -> Path:
        (root / "review").mkdir(parents=True, exist_ok=True)
        (root / "review" / "review_data.json").write_text(
            json.dumps({"totalDurationMs": 10000}), encoding="utf-8"
        )
        surface_path = root / "review" / "review-surface.json"
        surface_path.write_text(json.dumps({"id": "video-craft/visual"}), encoding="utf-8")
        return surface_path

    def _fake_playwright_module(self):
        import types

        class _FakeLocator:
            def count(self):
                return 0

        class _FakePage:
            frames = []

            def on(self, *_args, **_kwargs):
                pass

            def goto(self, *_args, **_kwargs):
                pass

            def wait_for_function(self, *_args, **_kwargs):
                pass

            def wait_for_timeout(self, *_args, **_kwargs):
                pass

            def locator(self, *_args, **_kwargs):
                return _FakeLocator()

            def screenshot(self, *_args, **_kwargs):
                pass

            def evaluate(self, script, *_args, **_kwargs):
                if "return 'live'" in script:
                    return "speaker"
                if "decodedAudio" in script:
                    return {"duration": 10.0, "currentTime": 0.0, "muted": False,
                            "volume": 1.0, "videoWidth": 1280, "readyState": 4}
                if "const out={channels:[]}" in script:
                    return {"channels": [{"name": "speaker", "muted": False, "src": "http://127.0.0.1/s.mp4"}]}
                return None

        class _FakeBrowser:
            def new_page(self, **_kwargs):
                return _FakePage()

            def close(self):
                pass

        class _FakeChromium:
            def launch(self, **_kwargs):
                return _FakeBrowser()

        class _FakePlaywright:
            chromium = _FakeChromium()

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        pw_pkg = types.ModuleType("playwright")
        pw_sync = types.ModuleType("playwright.sync_api")
        pw_sync.sync_playwright = lambda: _FakePlaywright()
        pw_pkg.sync_api = pw_sync
        return {"playwright": pw_pkg, "playwright.sync_api": pw_sync}

    def test_stops_owned_host_with_state_dict_and_opens_with_surface_path(self):
        review_host = _import_review_host()

        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            surface_path = self._seed_project(project)
            state = {"url": "http://127.0.0.1:43210/review/index.html", "pid": 42424, "reused": False}
            open_calls = []
            stop_calls = []

            def fake_open(surface, port=0, open_browser=True):
                open_calls.append((surface, type(surface), port, open_browser))
                return dict(state)

            def fake_stop(host_state, timeout=5.0):
                stop_calls.append(host_state)
                return True

            with patch.dict(sys.modules, self._fake_playwright_module()), \
                    patch.object(review_host, "open_review", side_effect=fake_open), \
                    patch.object(review_host, "stop_host", side_effect=fake_stop), \
                    redirect_stdout(io.StringIO()):
                rc = crp.run(project, [], keep_host=False, verbose=False)

            self.assertEqual(rc, 0)
            self.assertEqual(len(open_calls), 1)
            self.assertIsInstance(open_calls[0][0], Path)
            self.assertEqual(open_calls[0][0], surface_path)
            self.assertEqual(open_calls[0][2:], (0, False))
            self.assertEqual(stop_calls, [state])

    def test_skips_stop_host_when_keep_host_or_reused(self):
        review_host = _import_review_host()

        cases = [
            {"keep_host": True, "reused": False},
            {"keep_host": False, "reused": True},
        ]
        for case in cases:
            with self.subTest(**case), tempfile.TemporaryDirectory() as td:
                project = Path(td)
                self._seed_project(project)
                state = {"url": "http://127.0.0.1:43210/review/index.html",
                         "pid": 42424, "reused": case["reused"]}
                stop_calls = []

                with patch.dict(sys.modules, self._fake_playwright_module()), \
                        patch.object(review_host, "open_review", return_value=dict(state)), \
                        patch.object(review_host, "stop_host", side_effect=lambda s, timeout=5.0: stop_calls.append(s) or True), \
                        redirect_stdout(io.StringIO()):
                    rc = crp.run(project, [], keep_host=case["keep_host"], verbose=False)

                self.assertEqual(rc, 0)
                self.assertEqual(stop_calls, [])


class ReviewKeepHostFlag(unittest.TestCase):
    """review.review() 只在确认进入无插件本地宿主交付时给 check_review_playable.py 传 --keep-host。"""

    def _seed_project(self, root: Path) -> None:
        (root / "review").mkdir(parents=True, exist_ok=True)
        (root / "edit").mkdir(parents=True, exist_ok=True)
        (root / "review" / "index.html").write_text("<html></html>", encoding="utf-8")
        (root / "review" / "review-surface.json").write_text("{}", encoding="utf-8")
        (root / "review" / "review_data.json").write_text('{"totalDurationMs": 10000}', encoding="utf-8")

    def _run_review(self, project: Path, *, open_surface: bool):
        import review as rv
        calls = []

        def fake_run(args, expect_ok=True):
            calls.append(list(args))
            script = Path(args[0]).name
            if script == "check_review_playable.py":
                return 0, json.dumps({
                    "ok": True,
                    "channel": "speaker",
                    "checks": [{"name": "ok", "ok": True}],
                    "failures": [],
                })
            if script == "review_surface.py" and "--no-open" in args:
                return 0, json.dumps({"url": "http://127.0.0.1:43210/review/index.html"})
            return 0, "{}"

        out = io.StringIO()
        with patch.object(rv, "_run", side_effect=fake_run), redirect_stdout(out):
            rc = rv.review(project, open_surface=open_surface, live=False, as_json=True, build_mode="final-cut")
        playable_calls = [c for c in calls if Path(c[0]).name == "check_review_playable.py"]
        return rc, playable_calls[0], calls, json.loads(out.getvalue())

    def test_passes_keep_host_when_opening_without_bridge(self):
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            self._seed_project(project)
            with patch.dict(sys.modules, {"review_open_bridge": None}):
                rc, playable_args, _calls, payload = self._run_review(project, open_surface=True)
        self.assertEqual(rc, 0)
        self.assertIn("--keep-host", playable_args)
        self.assertEqual(payload["host"], "http://127.0.0.1:43210/review/index.html")

    def test_omits_keep_host_when_no_open(self):
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            self._seed_project(project)
            with patch.dict(sys.modules, {"review_open_bridge": None}):
                rc, playable_args, _calls, _payload = self._run_review(project, open_surface=False)
        self.assertEqual(rc, 0)
        self.assertNotIn("--keep-host", playable_args)

    def test_omits_keep_host_when_bridge_present_and_does_not_notify_before_probe(self):
        import types
        events = []
        fake_bridge = types.ModuleType("review_open_bridge")
        fake_bridge.notify = lambda surf: events.append(("notify", Path(surf)))

        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            self._seed_project(project)
            import review as rv

            def fake_run(args, expect_ok=True):
                script = Path(args[0]).name
                events.append(("run", script, list(args)))
                if script == "check_review_playable.py":
                    return 0, json.dumps({
                        "ok": True,
                        "channel": "speaker",
                        "checks": [{"name": "ok", "ok": True}],
                        "failures": [],
                    })
                return 0, "{}"

            out = io.StringIO()
            with patch.dict(sys.modules, {"review_open_bridge": fake_bridge}), \
                    patch.object(rv, "_run", side_effect=fake_run), \
                    redirect_stdout(out):
                rc = rv.review(project, open_surface=True, live=False, as_json=True, build_mode="final-cut")

        self.assertEqual(rc, 0)
        playable_idx = next(i for i, e in enumerate(events) if e[0] == "run" and e[1] == "check_review_playable.py")
        notify_idx = next(i for i, e in enumerate(events) if e[0] == "notify")
        self.assertLess(playable_idx, notify_idx)
        self.assertNotIn("--keep-host", events[playable_idx][2])

    def test_stops_newly_started_probe_host_when_playable_fails_with_keep_host(self):
        review_host = _import_review_host()
        import review as rv
        probe_state = {"url": "http://127.0.0.1:43210/review/index.html", "pid": 54321}
        stop_calls = []

        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            self._seed_project(project)

            def fake_run(args, expect_ok=True):
                script = Path(args[0]).name
                if script == "check_review_playable.py":
                    return 1, json.dumps({
                        "ok": False,
                        "channel": "speaker",
                        "checks": [{"name": "audio", "ok": False}],
                        "failures": [{"name": "audio", "detail": "muted"}],
                    })
                return 0, "{}"

            out = io.StringIO()
            with patch.dict(sys.modules, {"review_open_bridge": None}), \
                    patch.object(rv, "_run", side_effect=fake_run), \
                    patch.object(review_host, "host_alive", return_value=None), \
                    patch.object(review_host, "host_state", return_value=probe_state), \
                    patch.object(review_host, "stop_host", side_effect=lambda s, timeout=5.0: stop_calls.append(s) or True), \
                    redirect_stdout(out):
                rc = rv.review(project, open_surface=True, live=False, as_json=True, build_mode="final-cut")

        self.assertNotEqual(rc, 0)
        self.assertEqual(stop_calls, [probe_state])

    def test_preserves_preexisting_host_when_playable_fails(self):
        review_host = _import_review_host()
        import review as rv
        existing_state = {"url": "http://127.0.0.1:43211/review/index.html", "pid": 11111}
        stop_calls = []

        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            self._seed_project(project)

            def fake_run(args, expect_ok=True):
                if Path(args[0]).name == "check_review_playable.py":
                    return 1, json.dumps({
                        "ok": False,
                        "channel": "speaker",
                        "checks": [{"name": "audio", "ok": False}],
                        "failures": [{"name": "audio", "detail": "muted"}],
                    })
                return 0, "{}"

            out = io.StringIO()
            with patch.dict(sys.modules, {"review_open_bridge": None}), \
                    patch.object(rv, "_run", side_effect=fake_run), \
                    patch.object(review_host, "host_alive", return_value=existing_state), \
                    patch.object(review_host, "stop_host", side_effect=lambda s, timeout=5.0: stop_calls.append(s) or True), \
                    redirect_stdout(out):
                rc = rv.review(project, open_surface=True, live=False, as_json=True, build_mode="final-cut")

        self.assertNotEqual(rc, 0)
        self.assertEqual(stop_calls, [])


if __name__ == "__main__":
    unittest.main()
