# Upstream: browser-use/video-use tests/test_render_fps.py (commit 0c40770, PR #55).
# Local adaptation: extract_segment() here RETURNS the measured segment duration
# (this fork records it for segment_durations.json / caption timing), so the stub
# returns 1.0 instead of a MagicMock. Every rate assertion is unchanged.
#
# These three tests are about FRAME-RATE RESOLUTION. `extract_segment` is stubbed
# and writes no file, so `check_segment` (which reads the file back and refuses a
# torn or mis-sized segment) is stubbed too — otherwise every case here would fail
# at read-back for a reason that has nothing to do with the rate. The read-back
# behaviour itself is pinned against real ffmpeg output in
# `test_segment_integrity.py`, so nothing is relaxed by stubbing it here.
import argparse
import contextlib
import importlib.util
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).parents[1] / "helpers" / "render.py"
SPEC = importlib.util.spec_from_file_location("video_use_render", MODULE_PATH)
assert SPEC and SPEC.loader
render = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(render)


class ParseFpsTests(unittest.TestCase):
    def test_accepts_integer_decimal_and_rational_rates(self):
        expected = {
            "60": "60/1",
            "29.97": "2997/100",
            "30000/1001": "30000/1001",
        }
        for value, canonical in expected.items():
            with self.subTest(value=value):
                self.assertEqual(render.parse_fps(value), canonical)

    def test_canonical_rates_are_idempotent(self):
        for value in ("60", "29.97", "30000/1001"):
            with self.subTest(value=value):
                canonical = render.parse_fps(value)
                self.assertEqual(render.parse_fps(canonical), canonical)

    def test_rejects_invalid_or_non_positive_rates(self):
        for value in (
            "",
            "nope",
            "0",
            "-24",
            "1/0",
            "1e3",
            "1_000",
            "0.12345678901234567890",
            "1" * 33,
        ):
            with self.subTest(value=value):
                with self.assertRaises(argparse.ArgumentTypeError):
                    render.parse_fps(value)


class ProbeSourceFpsTests(unittest.TestCase):
    @staticmethod
    def _probe_result(avg: str, nominal: str) -> subprocess.CompletedProcess:
        stdout = json.dumps({
            "streams": [{"avg_frame_rate": avg, "r_frame_rate": nominal}]
        })
        return subprocess.CompletedProcess([], 0, stdout=stdout, stderr="")

    def test_prefers_average_rate(self):
        result = self._probe_result("30000/1001", "30/1")
        with patch.object(render.subprocess, "run", return_value=result):
            self.assertEqual(render.probe_source_fps(Path("source.mp4")), "30000/1001")

    def test_falls_back_to_nominal_rate(self):
        result = self._probe_result("0/0", "60/1")
        with patch.object(render.subprocess, "run", return_value=result):
            self.assertEqual(render.probe_source_fps(Path("source.mp4")), "60/1")

    def test_returns_none_for_unusable_probe_output(self):
        result = subprocess.CompletedProcess([], 0, stdout='{"streams": []}', stderr="")
        with patch.object(render.subprocess, "run", return_value=result):
            self.assertIsNone(render.probe_source_fps(Path("source.mp4")))

    def test_returns_none_when_ffprobe_fails(self):
        error = subprocess.CalledProcessError(1, ["ffprobe"])
        with patch.object(render.subprocess, "run", side_effect=error):
            self.assertIsNone(render.probe_source_fps(Path("source.mp4")))


class RenderRateTests(unittest.TestCase):
    @staticmethod
    def _edl() -> dict:
        return {
            "sources": {"first": "first.mp4", "second": "second.mp4"},
            "ranges": [
                {"source": "first", "start": 0, "end": 1},
                {"source": "second", "start": 0, "end": 1},
            ],
        }

    def test_multi_source_render_resolves_one_rate_from_first_source(self):
        edl = self._edl()
        with tempfile.TemporaryDirectory() as temp_dir:
            edit_dir = Path(temp_dir)
            with (
                patch.object(render, "probe_source_fps", return_value="60/1") as probe,
                patch.object(render, "extract_segment", return_value=1.0) as extract,
                patch.object(render, "check_segment", side_effect=lambda p, e, g: e),
            ):
                with contextlib.redirect_stdout(io.StringIO()):
                    render.extract_all_segments(edl, edit_dir, preview=False)

        probe.assert_called_once_with((edit_dir / "first.mp4").resolve())
        self.assertEqual([call.kwargs["rate"] for call in extract.call_args_list], ["60/1", "60/1"])

    def test_explicit_rate_skips_probe_and_applies_to_every_segment(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch.object(render, "probe_source_fps") as probe,
                patch.object(render, "extract_segment", return_value=1.0) as extract,
                patch.object(render, "check_segment", side_effect=lambda p, e, g: e),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                render.extract_all_segments(
                    self._edl(), Path(temp_dir), preview=False, fps="30"
                )

        probe.assert_not_called()
        self.assertEqual(
            [call.kwargs["rate"] for call in extract.call_args_list],
            ["30/1", "30/1"],
        )

    def test_failed_probe_falls_back_to_24_for_every_segment(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch.object(render, "probe_source_fps", return_value=None),
                patch.object(render, "extract_segment", return_value=1.0) as extract,
                patch.object(render, "check_segment", side_effect=lambda p, e, g: e),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                render.extract_all_segments(
                    self._edl(), Path(temp_dir), preview=False
                )

        self.assertEqual(
            [call.kwargs["rate"] for call in extract.call_args_list],
            ["24", "24"],
        )


if __name__ == "__main__":
    unittest.main()


# ----- Local addition (not upstream) -----------------------------------------
# Upstream preserves the observed average rate verbatim, which is right for a
# genuine 30000/1001 and wrong for a phone whose clock is 0.025% off. This fork
# snaps only non-standard rates that jitter around a standard one.
class NormalizeOutputRateTests(unittest.TestCase):
    def test_snaps_a_jittering_phone_rate_to_the_standard(self):
        self.assertEqual(
            render.normalize_output_rate("212265000/7073729"), "30/1")

    def test_leaves_a_real_broadcast_rational_alone(self):
        for rate in ("30000/1001", "24000/1001", "60000/1001"):
            with self.subTest(rate=rate):
                self.assertEqual(render.normalize_output_rate(rate), rate)

    def test_leaves_exact_standard_rates_alone(self):
        for rate in ("24/1", "25/1", "30/1", "50/1", "60/1"):
            with self.subTest(rate=rate):
                self.assertEqual(render.normalize_output_rate(rate), rate)

    def test_leaves_a_genuinely_odd_rate_alone(self):
        self.assertEqual(render.normalize_output_rate("17/1"), "17/1")
        self.assertEqual(render.normalize_output_rate("48/1"), "48/1")

    def test_is_idempotent_and_tolerates_garbage(self):
        once = render.normalize_output_rate("212265000/7073729")
        self.assertEqual(render.normalize_output_rate(once), once)
        self.assertEqual(render.normalize_output_rate("nonsense"), "nonsense")
