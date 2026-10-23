#!/usr/bin/env python3
"""二次剪成片（`edit/cut-map.json`）的声明、映射与交付闸门。

回归背景（2026-10-22 XHS v2）：成片渲染后又剪了 16 刀停顿，字幕按同一批剪点
重对时边遍历边改坐标，最多偏 3.2s；而旧交付核验只看字幕末条与总时长，全部通过。
这里的判据有两条：映射必须是可逐条复算的单调分段函数；对不上 cut-map 的交付字幕
必须被拒绝，而不是被当成「另一条合法字幕」。
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "helpers"))

import _cutmap  # noqa: E402

FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def stamp(ms: int) -> str:
    h, rest = divmod(ms, 3_600_000)
    m, rest = divmod(rest, 60_000)
    s, ms = divmod(rest, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(path: Path, cues: list[tuple[int, int, str]]) -> None:
    blocks = [f"{index}\n{stamp(start)} --> {stamp(end)}\n{text}\n"
              for index, (start, end, text) in enumerate(cues, start=1)]
    path.write_text("\n".join(blocks), encoding="utf-8")


def read_srt(path: Path) -> list[tuple[int, int, str]]:
    from _timecode import parse_srt_file
    return [(cue["startMs"], cue["endMs"], "\n".join(cue["lines"]))
            for cue in parse_srt_file(path)]


class RemapTests(unittest.TestCase):
    def test_window_collapses_to_its_start(self):
        cuts = [(2000, 4000)]
        self.assertEqual(_cutmap.remap_ms(1000, cuts), 1000)
        self.assertEqual(_cutmap.remap_ms(2500, cuts), 2000)
        self.assertEqual(_cutmap.remap_ms(3000, cuts), 2000)
        self.assertEqual(_cutmap.remap_ms(4000, cuts), 2000)
        self.assertEqual(_cutmap.remap_ms(5000, cuts), 3000)

    def test_multiple_cuts_accumulate(self):
        cuts = [(1000, 2000), (5000, 6000)]
        self.assertEqual(_cutmap.remap_ms(3000, cuts), 2000)
        self.assertEqual(_cutmap.remap_ms(5500, cuts), 4000)
        self.assertEqual(_cutmap.remap_ms(7000, cuts), 5000)

    def test_is_monotonic(self):
        cuts = [(500, 1200), (3000, 3600), (4800, 5000)]
        times = [_cutmap.remap_ms(t, cuts) for t in range(0, 8000, 37)]
        self.assertEqual(times, sorted(times))

    def test_expected_duration_clips_cut_at_the_tail(self):
        payload = {"masterDuration": 354.1, "cuts": [[353.44, 354.22]]}
        self.assertAlmostEqual(_cutmap.expected_film_duration_s(payload), 353.44, places=6)

    def test_expected_duration_subtracts_full_cuts(self):
        payload = {"masterDuration": 10.0, "cuts": [[2.0, 3.0], [6.0, 7.5]]}
        self.assertAlmostEqual(_cutmap.expected_film_duration_s(payload), 7.5, places=6)


class ValidateTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name)
        (self.project / "edit").mkdir()
        (self.project / "成品").mkdir()
        write_srt(self.project / "edit/subtitles.srt", [(0, 1000, "甲")])
        write_srt(self.project / "成品/film.srt", [(0, 1000, "甲")])
        self.payload = {
            "version": 1,
            "masterDuration": 10.0,
            "cuts": [[2.0, 3.0]],
            "srt": {"source": "edit/subtitles.srt", "film": "成品/film.srt"},
        }

    def tearDown(self):
        self._tmp.cleanup()

    def test_good_map_passes(self):
        self.assertEqual(_cutmap.validate(self.payload, self.project), [])

    def test_missing_fields_are_reported(self):
        payload = {"version": 1, "cuts": []}
        problems = _cutmap.validate(payload, self.project)
        self.assertTrue(any("masterDuration" in p for p in problems))
        self.assertTrue(any("cuts" in p for p in problems))

    def test_overlapping_or_unsorted_cuts_are_reported(self):
        payload = dict(self.payload, cuts=[[2.0, 4.0], [3.0, 5.0]])
        self.assertTrue(any("重叠" in p for p in _cutmap.validate(payload, self.project)))

    def test_degenerate_cut_is_reported(self):
        payload = dict(self.payload, cuts=[[3.0, 3.0]])
        self.assertTrue(any("end" in p for p in _cutmap.validate(payload, self.project)))

    def test_missing_film_srt_is_reported(self):
        (self.project / "成品/film.srt").unlink()
        problems = _cutmap.validate(self.payload, self.project)
        self.assertTrue(any("剪后字幕不存在" in p for p in problems))


class VerifyPairTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        # 两刀；第三条 cue 从第二刀之后开始，旧实现会把它误判成跨刀、少扣一刀
        self.payload = {
            "version": 1,
            "masterDuration": 12.0,
            "cuts": [[1.0, 2.0], [4.0, 6.0]],
            "srt": {"source": "source.srt", "film": "film.srt"},
        }
        self.source_cues = [
            (500, 900, "甲"),
            (2500, 3500, "乙"),
            (6500, 9000, "丙"),
            (9200, 9800, "丁"),
            (10500, 12000, "戊"),
        ]
        write_srt(self.dir / "source.srt", self.source_cues)

    def tearDown(self):
        self._tmp.cleanup()

    def _correct_film(self) -> list[tuple[int, int, str]]:
        cuts = _cutmap.cuts_ms(self.payload)
        limit = int(round(_cutmap.expected_film_duration_s(self.payload) * 1000))
        return [(*_cutmap.remap_cue(start, end, cuts, limit), text)
                for start, end, text in self.source_cues]

    def test_correct_remap_passes(self):
        write_srt(self.dir / "film.srt", self._correct_film())
        self.assertEqual(_cutmap.verify_srt_pair(self.dir / "source.srt",
                                                 self.dir / "film.srt", self.payload), [])

    def test_historical_bug_is_rejected(self):
        """旧实现（边改边比）把「在第二刀之后」的 cue 当成跨刀，起点少扣一刀。"""
        film = self._correct_film()
        # 第三条（丙）正确起点 = 6500 - 1000 - 2000 = 3500；旧实现会停在 4000
        film[2] = (4000, film[2][1], film[2][2])
        write_srt(self.dir / "film.srt", film)
        problems = _cutmap.verify_srt_pair(self.dir / "source.srt",
                                           self.dir / "film.srt", self.payload)
        self.assertTrue(any("第 3 条时间对不上" in p for p in problems), problems)

    def test_text_change_is_rejected(self):
        film = self._correct_film()
        film[0] = (film[0][0], film[0][1], "改过")
        write_srt(self.dir / "film.srt", film)
        problems = _cutmap.verify_srt_pair(self.dir / "source.srt",
                                           self.dir / "film.srt", self.payload)
        self.assertTrue(any("文字被改过" in p for p in problems), problems)

    def test_cue_count_difference_is_rejected(self):
        write_srt(self.dir / "film.srt", self._correct_film()[:-1])
        problems = _cutmap.verify_srt_pair(self.dir / "source.srt",
                                           self.dir / "film.srt", self.payload)
        self.assertTrue(any("条数不一致" in p for p in problems), problems)

    def test_actual_film_duration_clamps_last_cue(self):
        film = self._correct_film()
        expected = _cutmap.expected_film_duration_s(self.payload)
        # 编码后成片比整数表短 40ms：交付字幕按真实成片裁，核验要认这个差
        write_srt(self.dir / "film.srt",
                  film[:-1] + [(film[-1][0], film[-1][1] - 40, film[-1][2])])
        problems = _cutmap.verify_srt_pair(
            self.dir / "source.srt", self.dir / "film.srt", self.payload,
            film_duration_s=expected - 0.04)
        self.assertEqual(problems, [])


@unittest.skipUnless(FFMPEG, "ffmpeg required to build the film fixture")
class GateIntegrationTests(unittest.TestCase):
    """真实跑一遍 verify_delivery：有 cut-map 且字幕对得上 → 放行；旧字幕 → 拒绝。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name)
        edit = self.project / "edit"
        (self.project / "成品").mkdir()
        edit.mkdir()
        (edit / "edl.json").write_text(json.dumps({
            "sources": {}, "ranges": [{"source": "take", "start": 0.0, "end": 6.0}],
        }), encoding="utf-8")
        from _edl import edl_digest
        digest = edl_digest(edit / "edl.json")
        (edit / "segment_durations.json").write_text(json.dumps({
            "cut": {"durations": [6.0], "total_s": 6.0, "edl_sha256": digest},
        }), encoding="utf-8")

        self.source_cues = [(0, 1500, "甲"), (2500, 3500, "乙"), (4500, 5500, "丙")]
        write_srt(edit / "subtitles.srt", self.source_cues)
        self.payload = {
            "version": 1,
            "masterDuration": 6.0,
            "cuts": [[2.0, 4.0]],
            "srt": {"source": "edit/subtitles.srt", "film": "成品/film.srt"},
        }
        cuts = _cutmap.cuts_ms(self.payload)
        limit = int(round(_cutmap.expected_film_duration_s(self.payload) * 1000))
        film = [(*_cutmap.remap_cue(s, e, cuts, limit), text) for s, e, text in self.source_cues]
        write_srt(self.project / "成品/film.srt", film)
        (edit / "cut-map.json").write_text(json.dumps(self.payload), encoding="utf-8")

        self.film = self.project / "成品/film.mp4"
        subprocess.run([
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=24",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
            "-t", "4", "-shortest",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k", str(self.film),
        ], check=True)

    def tearDown(self):
        self._tmp.cleanup()

    def _verify(self) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(ROOT / "helpers/verify_delivery.py"),
             str(self.project / "edit"), "--video", str(self.film)],
            capture_output=True, text=True)

    def test_gate_accepts_recomputed_srt(self):
        proc = self._verify()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_gate_rejects_stale_srt(self):
        # 历史 bug：整条按旧刀长平移，第二条起点会晚 1s
        stale = [(0, 1500, "甲"), (3500, 4400, "乙"), (4500, 5500, "丙")]
        write_srt(self.project / "成品/film.srt", stale)
        proc = self._verify()
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertIn("cut-map", proc.stdout)

    def test_gate_refuses_undeclared_cut(self):
        (self.project / "edit/cut-map.json").unlink()
        proc = self._verify()
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertIn("cut-map.json", proc.stdout)


if __name__ == "__main__":
    unittest.main()
