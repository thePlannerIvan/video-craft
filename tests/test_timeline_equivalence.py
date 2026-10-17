"""The equivalence that let the SRT re-parse be retired.

`parse-srt.py` derived the visual timeline by parsing `subtitles.srt`. The
replacement derives it from the captions contract. The retirement is only safe if
both produce the SAME numbers, so that is what this asserts — on a synthetic
project, mechanically, without needing real media.

The end-to-end acceptance on a real project was: same grouping in, `cmp`-identical
`composition/index.html` out. These tests pin the property that makes that true.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

HELPERS = Path(__file__).parents[1] / "helpers"
sys.path.insert(0, str(HELPERS))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"craft_{name}", HELPERS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


timeline_derive = _load("timeline_derive")
srt_export = _load("srt_export")
from _edl import edl_digest  # noqa: E402


def _ms(seconds: float) -> int:
    return int(round(seconds * 1000))


class EquivalenceTests(unittest.TestCase):
    """A cue read from the SRT and the same cue derived from the EDL agree."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.edit = Path(self._tmp.name)
        # Two EDL segments; cues must be contiguous and ordered.
        self.cues = [
            {"segment": 0, "line": "有时候很荒谬", "start": 0.300, "end": 1.420,
             "source_start": 0.680, "source_end": 1.800},
            {"segment": 0, "line": "你觉得罗永浩是不是有什么KPI", "start": 1.540,
             "end": 4.180, "source_start": 1.920, "source_end": 4.560},
            {"segment": 1, "line": "结果西贝一通操作把自己给弄死了", "start": 12.200,
             "end": 14.440, "source_start": 16.600, "source_end": 18.840},
            {"segment": 1, "line": "我们就学吧", "start": 274.746666, "end": 276.106666,
             "source_start": 310.570, "source_end": 312.930},
        ]
        self.edl = {
            "version": 1,
            "sources": {"A": str(self.edit / "A.mp4")},
            "ranges": [
                {"source": "A", "start": 0.38, "end": 12.58, "beat": "HOOK"},
                {"source": "A", "start": 268.99, "end": 313.01, "beat": "CLOSE"},
            ],
            "grade": "none",
        }
        (self.edit / "edl.json").write_text(
            json.dumps(self.edl, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (self.edit / "captions.json").write_text(
            json.dumps(self.cues, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        # Words: two per cue, inside the cue's output window.
        words, per_segment = [], {}
        for cue in self.cues:
            seg = cue["segment"]
            per_segment[seg] = per_segment.get(seg, 0)
            mid = (cue["start"] + cue["end"]) / 2
            for k, (out_s, out_e) in enumerate([(cue["start"], mid), (mid, cue["end"])]):
                words.append({
                    "segment": seg, "segment_word": per_segment[seg] + k,
                    "transcript_index": len(words) + 1,
                    "text": f"w{len(words)}",
                    "source_start": cue["source_start"] + k, "source_end": cue["source_start"] + k + 0.2,
                    "out_start": out_s, "out_end": out_e,
                })
            per_segment[seg] += 2

        segs = []
        for i, r in enumerate(self.edl["ranges"]):
            seg_words = [w for w in words if w["segment"] == i]
            segs.append({
                "index": i, "source": "A", "source_start": r["start"], "source_end": r["end"],
                "speed": 1.0,
                "output_start": seg_words[0]["out_start"] if seg_words else 0.0,
                "output_end": seg_words[-1]["out_end"] if seg_words else 0.0,
                "word_count": len(seg_words),
            })
        (self.edit / "caption_words.json").write_text(json.dumps({
            "version": 2, "edl_sha256": edl_digest(self.edit / "edl.json"),
            "transcript_sha256": {"A": "x" * 64}, "corrections_sha256": "none",
            "segments": segs, "total_duration": 276.2, "timeline_source": "measured",
            "words": words,
        }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

        # The SRT exactly as srt_export would write it from these cues.
        lines = []
        for i, cue in enumerate(self.cues, start=1):
            lines += [str(i), f"{srt_export._srt_timestamp(cue['start'])} --> "
                              f"{srt_export._srt_timestamp(cue['end'])}", cue["line"], ""]
        (self.edit / "subtitles.srt").write_text("\n".join(lines), encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # ---- the property --------------------------------------------------------
    def test_every_cue_matches_between_the_two_derivations(self):
        derived = timeline_derive.derive_entries(self.edit)
        from_srt = srt_export.parse_srt(self.edit / "subtitles.srt")
        self.assertEqual(len(derived), len(from_srt), "cue counts must agree")
        for d, (s_start, s_end, s_text) in zip(derived, from_srt):
            self.assertEqual(d["startMs"], _ms(s_start))
            self.assertEqual(d["endMs"], _ms(s_end))
            self.assertEqual(d["durationMs"], _ms(s_end) - _ms(s_start))
            self.assertEqual(d["text"], s_text)

    def test_sub_millisecond_cue_survives_the_round_trip(self):
        """274.746666 must come back as 274747 from both sides, not 274746."""
        derived = timeline_derive.derive_entries(self.edit)
        last = derived[-1]
        self.assertEqual(last["startMs"], 274747)
        self.assertEqual(last["startMs"], _ms(srt_export.parse_srt(
            self.edit / "subtitles.srt")[-1][0]))

    # ---- what only the EDL side knows ---------------------------------------
    def test_entries_carry_the_edl_binding(self):
        derived = timeline_derive.derive_entries(self.edit)
        self.assertEqual([d["segment"] for d in derived], [0, 0, 1, 1])
        self.assertEqual(sum(len(d["wordIndices"]) for d in derived), 8)
        self.assertEqual(derived[0]["wordIndices"], [0, 1])
        self.assertEqual(derived[0]["sourceRange"], [0.680, 1.800])

    def test_a_cue_only_claims_words_from_its_own_segment(self):
        """The word lookup is scoped by the cue's own EDL segment, so a cue near a
        cut boundary cannot claim a word that belongs to the neighbouring segment."""
        derived = timeline_derive.derive_entries(self.edit)
        self.assertEqual(derived[2]["segment"], 1)
        self.assertTrue(all(i >= 4 for i in derived[2]["transcriptIndices"]),
                        derived[2]["transcriptIndices"])

    # ---- the guards ---------------------------------------------------------
    def test_a_nominal_timeline_is_refused(self):
        path = self.edit / "caption_words.json"
        blob = json.loads(path.read_text(encoding="utf-8"))
        blob["timeline_source"] = "nominal"
        path.write_text(json.dumps(blob, ensure_ascii=False), encoding="utf-8")
        with self.assertRaises(SystemExit) as ctx:
            timeline_derive.derive_entries(self.edit)
        self.assertIn("measured", str(ctx.exception).lower())

    def test_a_stale_edl_is_refused(self):
        path = self.edit / "caption_words.json"
        blob = json.loads(path.read_text(encoding="utf-8"))
        blob["edl_sha256"] = "0" * 64
        path.write_text(json.dumps(blob, ensure_ascii=False), encoding="utf-8")
        with self.assertRaises(SystemExit) as ctx:
            timeline_derive.derive_entries(self.edit)
        self.assertIn("different EDL", str(ctx.exception))


class BuildTimelineTests(unittest.TestCase):
    """`build_timeline` keeps the SRT path's numbers exactly."""

    def setUp(self) -> None:
        EquivalenceTests.setUp(self)

    def tearDown(self) -> None:
        EquivalenceTests.tearDown(self)

    def _grouping(self, key: str = "cueIndices") -> dict:
        return {"chapters": [
            {"id": "intro", "title": "开场", "steps": [
                {key: [0, 1], "screenIntent": "hook"},
                {key: [2, 3], "screenIntent": "close"},
            ]},
        ]}

    def test_numbers_and_caption_come_from_first_and_last_cue(self):
        entries = timeline_derive.derive_entries(self.edit)
        timeline, durations = timeline_derive.build_timeline(entries, self._grouping())
        steps = timeline["chapters"][0]["steps"]
        self.assertEqual(steps[0]["startMs"], entries[0]["startMs"])
        self.assertEqual(steps[0]["endMs"], entries[1]["endMs"])
        self.assertEqual(steps[0]["durationMs"],
                         entries[1]["endMs"] - entries[0]["startMs"])
        self.assertEqual(steps[0]["caption"],
                         f"{entries[0]['text']} {entries[1]['text']}")
        self.assertEqual(durations["intro"], [s["durationMs"] for s in steps])
        self.assertEqual(timeline["source"], "edl")

    def test_step_carries_its_cue_range_and_segments(self):
        entries = timeline_derive.derive_entries(self.edit)
        timeline, _ = timeline_derive.build_timeline(entries, self._grouping())
        step = timeline["chapters"][0]["steps"][1]
        self.assertEqual(step["cueRange"], [2, 3])
        self.assertEqual(step["segments"], [1])
        self.assertEqual(step["wordCount"], 4)

    def test_the_old_key_is_still_accepted(self):
        entries = timeline_derive.derive_entries(self.edit)
        with_alias, _ = timeline_derive.build_timeline(entries, self._grouping("srtIndices"))
        with_new, _ = timeline_derive.build_timeline(entries, self._grouping("cueIndices"))
        self.assertEqual(json.dumps(with_alias, sort_keys=True),
                         json.dumps(with_new, sort_keys=True))

    def test_a_step_may_span_a_cut(self):
        entries = timeline_derive.derive_entries(self.edit)
        grouping = {"chapters": [{"id": "all", "steps": [{"cueIndices": [1, 2]}]}]}
        timeline, _ = timeline_derive.build_timeline(entries, grouping)
        self.assertEqual(timeline["chapters"][0]["steps"][0]["segments"], [0, 1])

    def test_a_missing_cue_index_is_an_error(self):
        entries = timeline_derive.derive_entries(self.edit)
        grouping = {"chapters": [{"id": "x", "steps": [{"cueIndices": [99]}]}]}
        with self.assertRaises(ValueError):
            timeline_derive.build_timeline(entries, grouping)

    def test_an_empty_step_is_an_error(self):
        entries = timeline_derive.derive_entries(self.edit)
        grouping = {"chapters": [{"id": "x", "steps": [{"cueIndices": []}]}]}
        with self.assertRaises(ValueError):
            timeline_derive.build_timeline(entries, grouping)

    def test_total_duration_is_the_span_not_the_sum_of_steps(self):
        """The axis length is末步止 − 首步起, not the sum of step durations.

        Regression: `totalDurationMs` used to be `sum(sum(v) for v in
        duration_map.values())`. Cues have real gaps between them (4.180 -> 12.200
        in this fixture; 11.4s across the 图拉斯 project), so summing dropped them.
        That project's 251.41s timeline was reported as exactly 240.0s, and
        `build_review.py` adopts this number as the console's axis length — so the
        last ~12s were unreachable and every step after a gap sat early.
        """
        entries = timeline_derive.derive_entries(self.edit)
        timeline, _ = timeline_derive.build_timeline(entries, self._grouping())
        steps = timeline["chapters"][0]["steps"]
        self.assertEqual(timeline["totalDurationMs"],
                         steps[-1]["endMs"] - steps[0]["startMs"])

    def test_a_gap_between_steps_is_counted_in_the_total(self):
        """Splitting at a real gap must make the span strictly larger than the sum."""
        entries = timeline_derive.derive_entries(self.edit)
        grouping = {"chapters": [{"id": "g", "steps": [
            {"cueIndices": [0, 1]}, {"cueIndices": [2, 3]}]}]}
        timeline, _ = timeline_derive.build_timeline(entries, grouping)
        steps = timeline["chapters"][0]["steps"]
        summed = sum(s["durationMs"] for s in steps)
        self.assertLess(summed, timeline["totalDurationMs"])
        self.assertEqual(timeline["totalDurationMs"],
                         steps[-1]["endMs"] - steps[0]["startMs"])

    def test_measured_total_pins_the_spine_and_closes_the_cue_gaps(self):
        """The cue span is shorter than the measured cut, and steps do not touch.

        Both defects render as: clips end before the next one starts (black flash
        at every seam) and the tail is cut. 2026-10-17 cost a full render before
        verify_delivery's black budget found them, so the spine is pinned to the
        measured total up front.
        """
        entries = timeline_derive.derive_entries(self.edit)
        grouping = {"chapters": [{"id": "g", "steps": [
            {"cueIndices": [0, 1]}, {"cueIndices": [2, 3]}]}]}
        cue_span, _ = timeline_derive.build_timeline(entries, grouping)
        measured = cue_span["chapters"][0]["steps"][-1]["endMs"] + 400

        timeline, durations = timeline_derive.build_timeline(
            entries, grouping, measured_total_ms=measured)
        steps = timeline["chapters"][0]["steps"]

        self.assertEqual(steps[0]["startMs"], 0, "片头 pad 必须补上")
        self.assertEqual(steps[0]["endMs"], steps[1]["startMs"], "步与步之间不能留缝")
        self.assertEqual(steps[-1]["endMs"], measured, "片尾 pad 必须补上")
        self.assertEqual(timeline["totalDurationMs"], measured)
        self.assertEqual(durations["g"], [st["durationMs"] for st in steps])
        for st in steps:
            self.assertEqual(st["durationMs"], st["endMs"] - st["startMs"])


if __name__ == "__main__":
    unittest.main()
