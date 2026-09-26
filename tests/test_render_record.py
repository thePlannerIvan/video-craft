"""Which render record belongs to the EDL in front of you.

`segment_durations.json` accumulates one key per output name — the reported
project had `poc` / `draft` / `draft2` / `mix-base` / `final`. Both delivery
gates iterated the keys and took the first one that looked like a record, so
they read the POC's 12.000s and judged a correct 84.000s film:

    check_edl        → "成片 12.000s ... EDL 在渲染之后又改过"
    verify_delivery  → "✗ 成片 84.000s 与渲染记录的实测合计 12.000s 相差 +72.000s
                        ——成片可能被截断或替换过   RESULT: FAIL"

The EDL's sha256 identifies its own record. History stays in the file for humans
and does not vote: `select_render_record` is the one place that decides.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HELPERS = Path(__file__).parents[1] / "helpers"
sys.path.insert(0, str(HELPERS))


def load(name: str):
    spec = importlib.util.spec_from_file_location(f"video_use_{name}", HELPERS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    module.__dict__.setdefault("__name__", spec.name)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


EDL_LIB = load("_edl")
CHECK = load("check_edl")
VERIFY = load("verify_delivery")

HAVE_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def record(durations, digest=None, fps=30.0) -> dict:
    entry = {"durations": durations, "total_s": round(sum(durations), 6), "fps": fps}
    if digest is not None:
        entry["edl_sha256"] = digest
    return entry


class SelectRenderRecordTests(unittest.TestCase):
    """The report's own file: POC 12.0s, final 84.0s, one EDL."""

    DIGEST = hashlib.sha256(b"the-64s-edl").hexdigest()

    def blob(self):
        return {
            "poc": record([6.0, 6.0], hashlib.sha256(b"poc-edl").hexdigest()),
            "draft": record([8.0] * 9 + [0.93], hashlib.sha256(b"draft-edl").hexdigest()),
            "mix-base": record([8.0] * 9 + [8.0], hashlib.sha256(b"other-edl").hexdigest()),
            "final": record([8.4] * 10, self.DIGEST),
        }

    def test_the_record_is_chosen_by_digest_not_by_position(self):
        tag, entry, how = EDL_LIB.select_render_record(self.blob(), self.DIGEST)
        self.assertEqual((tag, how), ("final", "digest"))
        self.assertAlmostEqual(sum(entry["durations"]), 84.0, places=6)

    def test_a_stale_render_is_reported_as_a_mismatch_not_silently_resolved(self):
        tag, entry, how = EDL_LIB.select_render_record(self.blob(), hashlib.sha256(b"new").hexdigest())
        self.assertEqual(how, "mismatch")
        self.assertIsNotNone(entry)

    def test_records_without_a_digest_are_read_but_flagged(self):
        blob = {"poc": record([6.0, 6.0]), "final": record([8.4] * 10)}
        tag, entry, how = EDL_LIB.select_render_record(blob, self.DIGEST)
        self.assertEqual((tag, how), ("final", "no-digest"))

    def test_an_empty_or_junk_file_selects_nothing(self):
        self.assertEqual(EDL_LIB.select_render_record({}, self.DIGEST), (None, None, "none"))
        self.assertEqual(EDL_LIB.select_render_record({"x": 1}, self.DIGEST), (None, None, "none"))


class FixtureTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.edit = Path(self._tmp.name) / "edit"
        self.edit.mkdir()
        self.ranges = [{"source": "A", "start": 0.0, "end": 8.4} for _ in range(10)]
        self.write_edl()
        (self.edit / "A.mp4").write_bytes(b"stub")
        (self.edit / "transcripts").mkdir()
        (self.edit / "transcripts" / "A.json").write_text(
            json.dumps({"words": [{"type": "word", "text": "一", "start": 0.1, "end": 0.4}]}),
            encoding="utf-8")

    def write_edl(self) -> None:
        (self.edit / "edl.json").write_text(
            json.dumps({"version": 1, "sources": {"A": str(self.edit / "A.mp4")},
                        "ranges": self.ranges}), encoding="utf-8")

    def digest(self) -> str:
        return EDL_LIB.edl_digest(self.edit / "edl.json")

    def write_records(self, *, final_digest=None, final_durations=None) -> None:
        blob = {
            "poc": record([6.0, 6.0], hashlib.sha256(b"poc").hexdigest()),
            "draft": record([7.0] * 12, hashlib.sha256(b"draft").hexdigest()),
            "final": record(final_durations if final_durations is not None else [8.4] * 10,
                            self.digest() if final_digest is None else final_digest),
        }
        (self.edit / "segment_durations.json").write_text(
            json.dumps(blob, ensure_ascii=False), encoding="utf-8")


class CheckEdlTests(FixtureTests):
    def test_no_more_false_twelve_seconds(self):
        self.write_records()
        result = CHECK.check(self.edit)
        self.assertEqual(result["measured_total_s"], 84.0, result)
        self.assertFalse(any("12.0" in w for w in result["warn"]), result["warn"])

    def test_the_accumulated_keys_do_not_produce_a_stale_render_warning(self):
        self.write_records()
        result = CHECK.check(self.edit)
        self.assertFalse(any("哈希不符" in w for w in result["warn"]), result["warn"])
        self.assertFalse(any("段" in w and "EDL 有" in w for w in result["warn"]), result["warn"])

    def test_a_genuinely_stale_render_is_still_reported(self):
        self.write_records(final_digest=hashlib.sha256(b"an-older-edl").hexdigest())
        result = CHECK.check(self.edit)
        self.assertTrue(any("哈希不符" in w for w in result["warn"]), result["warn"])


class VerifyDeliveryTests(FixtureTests):
    def test_measured_total_reads_the_current_edl_record(self):
        self.write_records()
        measured, tag, how = VERIFY.measured_total(self.edit)
        self.assertEqual((tag, how), ("final", "digest"))
        self.assertAlmostEqual(measured, 84.0, places=6)

    def test_a_render_from_another_edl_is_a_hard_failure(self):
        self.write_records(final_digest=hashlib.sha256(b"an-older-edl").hexdigest())
        measured, tag, how = VERIFY.measured_total(self.edit)
        self.assertEqual(how, "mismatch")

    @unittest.skipUnless(HAVE_FFMPEG, "ffmpeg/ffprobe not on PATH")
    def test_the_delivery_gate_no_longer_fails_a_correct_film(self):
        """Same shape as the report, at a size a test can render: a 2s film whose
        file also holds a much longer `poc` render."""
        self.ranges = [{"source": "A", "start": 0.0, "end": 2.0}]
        self.write_edl()
        video = self.edit / "final.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=30:duration=2",
             "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast",
             "-c:a", "aac", "-shortest", str(video)],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        (self.edit / "segment_durations.json").write_text(json.dumps({
            "poc": record([6.0, 6.0], hashlib.sha256(b"poc").hexdigest()),
            "draft": record([4.0], hashlib.sha256(b"draft").hexdigest()),
            "final": record([2.0], self.digest()),
        }, ensure_ascii=False), encoding="utf-8")

        backup = sys.argv
        sys.argv = ["verify_delivery.py", str(self.edit)]
        try:
            import io
            import contextlib
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                code = VERIFY.main()
        finally:
            sys.argv = backup
        output = buffer.getvalue()
        self.assertEqual(code, 0, output)
        self.assertIn("时长与渲染记录（final）一致", output)
        self.assertNotIn("可能被截断或替换过", output)


if __name__ == "__main__":
    unittest.main()
