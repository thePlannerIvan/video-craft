#!/usr/bin/env python3
"""The subtitle sync gate must compare against the caption contract, not the film length.

`check_edl` used to fail when `|last cue end − film duration| > 0.15s`. A film
legitimately keeps a tail after the last word — on the 图拉斯 project `TRAIL_PAD`
is 0.55s, so a perfectly synchronised 251.41s cue list in a 251.87s film was
reported as "字幕与成片不同步，重建字幕后再交付".

The property that actually matters is that the SRT still reproduces the cue list
it was built from (`captions.json`), plus that no cue runs PAST the picture. Both
are pinned here, together with the nominal-timeline refusal that was already
correct.
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
FILM_S = 4.0


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"craft_{name}", HELPERS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


check_edl = _load("check_edl")
from _edl import edl_digest  # noqa: E402


def _write_wav(path: Path) -> None:
    frames = bytearray()
    for i in range(int(FILM_S * SR)):
        t = i / SR
        value = int(9000 * math.sin(2 * math.pi * 220 * t)) if 1.0 <= t < 2.0 else 0
        frames += struct.pack("<h", value)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(bytes(frames))


def _stamp(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


@unittest.skipUnless(FFMPEG, "ffmpeg required to measure audio")
class CaptionSyncGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.edit = Path(self._tmp.name)
        self.media = self.edit / "take.wav"
        _write_wav(self.media)
        (self.edit / "transcripts").mkdir()
        (self.edit / "transcripts" / "take.json").write_text(json.dumps({
            "words": [
                {"type": "word", "text": "甲", "start": 1.05, "end": 1.45},
                {"type": "word", "text": "乙", "start": 2.05, "end": 2.45},
            ]
        }, ensure_ascii=False), encoding="utf-8")
        (self.edit / "edl.json").write_text(json.dumps({
            "version": 1, "sources": {"take": str(self.media)},
            "ranges": [{"source": "take", "start": 0.0, "end": FILM_S,
                        "beat": "b", "quote": "q"}],
            "grade": "none",
        }, ensure_ascii=False), encoding="utf-8")
        (self.edit / "segment_durations.json").write_text(json.dumps({
            "final": {"durations": [FILM_S], "total_s": FILM_S,
                      "edl_sha256": edl_digest(self.edit / "edl.json"), "fps": 30.0}
        }), encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _caption_contract(self, start: float, end: float,
                          timeline_source: str = "measured") -> None:
        (self.edit / "captions.json").write_text(json.dumps(
            [{"segment": 0, "line": "甲", "start": start, "end": end,
              "source_start": 1.05, "source_end": 1.45}], ensure_ascii=False),
            encoding="utf-8")
        (self.edit / "caption_words.json").write_text(json.dumps({
            "version": 2, "timeline_source": timeline_source,
            "edl_sha256": edl_digest(self.edit / "edl.json"),
            "segments": [{"index": 0, "output_start": 0.0, "output_end": FILM_S,
                          "word_count": 2}],
            "total_duration": FILM_S,
            "words": [
                {"segment": 0, "segment_word": 0, "transcript_index": 1, "text": "甲",
                 "source_start": 1.05, "source_end": 1.45, "out_start": start, "out_end": end},
            ],
        }, ensure_ascii=False), encoding="utf-8")

    def _srt(self, start: float, end: float) -> None:
        (self.edit / "subtitles.srt").write_text(
            f"1\n{_stamp(start)} --> {_stamp(end)}\n甲\n", encoding="utf-8")

    def _run(self) -> dict:
        return check_edl.check(self.edit, max_pause=10.0)

    def test_a_tail_after_the_last_word_is_not_a_desync(self):
        """Regression: 3.5s of cues in a 4.0s film is synchronised, not stale."""
        self._caption_contract(1.05, 3.5)
        self._srt(1.05, 3.5)
        result = self._run()
        self.assertFalse([m for m in result["hard"] if "不同步" in m], result["hard"])
        self.assertFalse([m for m in result["hard"] if "超出成片" in m], result["hard"])
        self.assertTrue(result["ok"], result["hard"])

    def test_cues_running_past_the_picture_are_hard(self):
        self._caption_contract(1.05, 4.6)
        self._srt(1.05, 4.6)
        result = self._run()
        self.assertTrue([m for m in result["hard"] if "超出成片" in m], result["hard"])

    def test_an_srt_that_disagrees_with_the_contract_is_hard(self):
        self._caption_contract(1.05, 3.5)
        self._srt(1.45, 3.9)          # a stale SRT from an earlier render
        result = self._run()
        self.assertTrue([m for m in result["hard"] if "captions.json" in m], result["hard"])

    def test_a_cue_count_difference_is_hard(self):
        self._caption_contract(1.05, 3.5)
        (self.edit / "subtitles.srt").write_text(
            f"1\n{_stamp(1.05)} --> {_stamp(3.5)}\n甲\n"
            f"2\n{_stamp(3.6)} --> {_stamp(3.9)}\n乙\n", encoding="utf-8")
        result = self._run()
        self.assertTrue([m for m in result["hard"] if "不同版本" in m], result["hard"])

    def test_a_nominal_caption_timeline_is_still_refused(self):
        self._caption_contract(1.05, 3.5, timeline_source="nominal")
        self._srt(1.05, 3.5)
        result = self._run()
        self.assertTrue([m for m in result["hard"] if "标称时间轴" in m], result["hard"])


if __name__ == "__main__":
    unittest.main()
