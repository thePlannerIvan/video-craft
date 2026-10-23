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

import check_review_playable as crp  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
