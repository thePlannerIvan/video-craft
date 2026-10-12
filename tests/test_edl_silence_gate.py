#!/usr/bin/env python3
"""The EDL gate must judge cut edges on the audio, not on the transcript frame.

Both engines we use misplace word boundaries, in opposite directions:

  * SeedASR onsets run ~0.2s EARLY and its ends run into the following silence;
  * Scribe's token spans are unreliable (it merges 「。muji，」 into one 2.9s token).

So a transcript frame is neither necessary nor sufficient for "this cut clips
speech". A cut inside a loose ASR frame, but in measured silence, is a *correct*
cut and used to be a HARD failure; a cut with real audio energy at it used to pass
whenever no word frame happened to cover it.

The fixture synthesises audio with unambiguous tone/silence blocks and then makes
the transcript frames deliberately loose, so each test isolates one direction.
"""
from __future__ import annotations

import importlib.util
import json
import math
import shutil
import struct
import sys
import tempfile
import unittest
import wave
from pathlib import Path

HELPERS = Path(__file__).parents[1] / "helpers"
sys.path.insert(0, str(HELPERS))

FFMPEG = shutil.which("ffmpeg") is not None
SR = 16_000
# Tone/silence layout of the fixture, in seconds.
SILENCE_A = (0.0, 0.5)
TONE_A = (0.5, 1.5)
GAP = (1.5, 2.5)
TONE_B = (2.5, 3.5)
SILENCE_B = (3.5, 4.0)


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"craft_{name}", HELPERS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    # Register before exec: a module that uses @dataclass needs its own name
    # resolvable in sys.modules, and importlib does not do that for us.
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


silence = _load("_silence")
check_edl = _load("check_edl")


def _write_fixture_wav(path: Path) -> None:
    """Two tone bursts separated by silence, with digital-silence tails."""
    frames = bytearray()
    total = int(SILENCE_B[1] * SR)
    for i in range(total):
        t = i / SR
        loud = (TONE_A[0] <= t < TONE_A[1]) or (TONE_B[0] <= t < TONE_B[1])
        value = int(9000 * math.sin(2 * math.pi * 220 * t)) if loud else 0
        frames += struct.pack("<h", value)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(bytes(frames))


@unittest.skipUnless(FFMPEG, "ffmpeg required to measure audio")
class SilenceMapTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.edit = Path(self._tmp.name)
        self.media = self.edit / "take.wav"
        _write_fixture_wav(self.media)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_runs_land_on_the_synthesised_silence(self):
        smap = silence.measure(self.media)
        self.assertLess(smap.threshold_db, -20.0)
        self.assertEqual(len(smap.runs), 3, smap.runs)
        for (want_a, want_b), (got_a, got_b) in zip(
                (SILENCE_A, GAP, SILENCE_B), smap.runs):
            self.assertAlmostEqual(want_a, got_a, delta=0.05)
            self.assertAlmostEqual(want_b, got_b, delta=0.05)

    def test_is_silent_distinguishes_tone_from_gap(self):
        smap = silence.measure(self.media)
        self.assertTrue(smap.is_silent(0.2))
        self.assertTrue(smap.is_silent(2.0))
        self.assertFalse(smap.is_silent(1.0))
        self.assertFalse(smap.is_silent(3.0))

    def test_a_brief_dip_still_counts_as_a_cut_point(self):
        """A cut in a short real gap is legitimate; the default run test is short."""
        smap = silence.measure(self.media)
        self.assertFalse(smap.is_silent(2.0, min_run_s=2.0))   # run too short to count
        self.assertTrue(smap.is_silent(2.0, min_run_s=0.5))


@unittest.skipUnless(FFMPEG, "ffmpeg required to measure audio")
class EdlSilenceGateTests(unittest.TestCase):
    """`check_edl` grades edges by measured audio, not by the word frames."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.edit = Path(self._tmp.name)
        self.media = self.edit / "take.wav"
        _write_fixture_wav(self.media)
        (self.edit / "transcripts").mkdir()
        # ASR frames deliberately LOOSE, the way SeedASR behaves: each onset is
        # 0.15s early and each end reaches 0.15s into the silence.
        (self.edit / "transcripts" / "take.json").write_text(json.dumps({
            "words": [
                {"type": "word", "text": "甲", "start": 0.35, "end": 1.65},
                {"type": "word", "text": "乙", "start": 2.35, "end": 3.65},
            ]
        }, ensure_ascii=False), encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _edl(self, ranges: list[tuple[float, float]]) -> dict:
        return {
            "version": 1,
            "sources": {"take": str(self.media)},
            "ranges": [{"source": "take", "start": a, "end": b,
                        "beat": "b", "quote": "q"} for a, b in ranges],
            "grade": "none",
        }

    def _write(self, ranges: list[tuple[float, float]]) -> None:
        (self.edit / "edl.json").write_text(
            json.dumps(self._edl(ranges), ensure_ascii=False), encoding="utf-8")

    def test_gate_is_measured(self):
        self._write([(0.0, 1.5), (2.5, 4.0)])
        result = check_edl.check(self.edit, max_pause=10.0)
        self.assertEqual(result["silence_gate"], "measured")
        self.assertTrue(result["silence_thresholds_db"])

    def test_a_cut_in_measured_silence_passes(self):
        self._write([(0.0, 1.5), (2.5, 4.0)])
        result = check_edl.check(self.edit, max_pause=10.0)
        self.assertFalse([m for m in result["hard"] if "实测有语音" in m], result["hard"])

    def test_a_cut_in_a_loose_word_frame_but_in_silence_is_only_a_warning(self):
        """The 图拉斯 regression: a correct cut reported as "切在词内"."""
        # 1.6 sits inside the ASR frame 0.35-1.65 but in the measured gap 1.5-2.5.
        self._write([(0.0, 1.6), (2.5, 4.0)])
        result = check_edl.check(self.edit, max_pause=10.0)
        self.assertFalse([m for m in result["hard"] if "实测有语音" in m], result["hard"])
        self.assertTrue([m for m in result["warn"] if "但实测是静音" in m], result["warn"])

    def test_a_cut_with_audio_energy_at_it_is_hard(self):
        # 1.0 is inside the tone burst; no ASR frame boundary is near it, so the
        # word-frame test alone would have passed this.
        self._write([(0.0, 1.0), (2.5, 4.0)])
        result = check_edl.check(self.edit, max_pause=10.0)
        self.assertTrue([m for m in result["hard"] if "实测有语音" in m], result["hard"])
        self.assertFalse(result["ok"])


if __name__ == "__main__":
    unittest.main()
