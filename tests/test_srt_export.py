import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


HELPER = Path(__file__).parents[1] / "helpers" / "srt_export.py"
SPEC = importlib.util.spec_from_file_location("video_use_srt_export", HELPER)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class ArticleFirstSrtTests(unittest.TestCase):
    def make_edit(self) -> Path:
        root = Path(tempfile.mkdtemp(prefix="video-use-caption-test-"))
        (root / "transcripts").mkdir()
        edl = {
            "version": 1,
            "sources": {"A": "/tmp/A.mp4"},
            "ranges": [
                {"source": "A", "start": 0.0, "end": 3.0},
                {"source": "A", "start": 10.0, "end": 12.0},
            ],
        }
        (root / "edl.json").write_text(json.dumps(edl), encoding="utf-8")
        transcript = {
            "words": [
                {"type": "word", "text": "你好", "start": 0.1, "end": 0.8},
                {"type": "word", "text": "世界", "start": 0.9, "end": 1.5},
                {"type": "word", "text": "Brand", "start": 10.1, "end": 10.6},
                {"type": "word", "text": "Vision", "start": 10.7, "end": 11.4},
            ]
        }
        (root / "transcripts" / "A.json").write_text(json.dumps(transcript), encoding="utf-8")
        return root

    def test_article_first_matches_each_segment_on_output_timeline(self) -> None:
        edit = self.make_edit()
        MODULE.prepare_article(edit)
        (edit / "captions_article.txt").write_text("你好世界\n\nBrand Vision\n", encoding="utf-8")
        (edit / "semantic_lines.txt").write_text("你好\n世界\n\nBrand Vision\n", encoding="utf-8")
        MODULE.lock_article(edit)
        MODULE.build_article_srt(edit)
        MODULE.check_article_srt(edit)
        cues = MODULE.parse_srt(edit / "subtitles.srt")
        self.assertEqual([cue[2] for cue in cues], ["你好", "世界", "Brand Vision"])
        self.assertAlmostEqual(cues[0][0], 0.1, places=3)
        self.assertAlmostEqual(cues[-1][0], 3.1, places=3)

    def test_lock_rejects_article_that_drops_kept_words(self) -> None:
        edit = self.make_edit()
        MODULE.prepare_article(edit)
        (edit / "captions_article.txt").write_text("你好\n\nBrand Vision\n", encoding="utf-8")
        with self.assertRaises(SystemExit):
            MODULE.lock_article(edit)

    def test_builder_rejects_split_word_and_stale_lock(self) -> None:
        edit = self.make_edit()
        MODULE.prepare_article(edit)
        (edit / "captions_article.txt").write_text("你好世界\n\nBrand Vision\n", encoding="utf-8")
        (edit / "semantic_lines.txt").write_text("你\n好世界\n\nBrand Vision\n", encoding="utf-8")
        MODULE.lock_article(edit)
        with self.assertRaises(SystemExit):
            MODULE.build_article_srt(edit)

    def test_explicit_correction_map_is_bound_into_word_contract(self) -> None:
        edit = self.make_edit()
        corrections = [{
            "source": "A",
            "transcript_index": 0,
            "action": "replace",
            "text": "您好",
            "reason": "confirmed ASR correction",
        }]
        (edit / "caption_corrections.json").write_text(
            json.dumps(corrections, ensure_ascii=False), encoding="utf-8"
        )
        MODULE.prepare_article(edit)
        self.assertIn("您好", (edit / "captions_article.txt").read_text(encoding="utf-8"))
        (edit / "captions_article.txt").write_text("您好世界\n\nBrand Vision\n", encoding="utf-8")
        (edit / "semantic_lines.txt").write_text("您好\n世界\n\nBrand Vision\n", encoding="utf-8")
        MODULE.lock_article(edit)
        MODULE.build_article_srt(edit)
        self.assertEqual(MODULE.parse_srt(edit / "subtitles.srt")[0][2], "您好")
        (edit / "captions_article.txt").write_text("你好世界！\n\nBrand Vision\n", encoding="utf-8")
        with self.assertRaises(SystemExit):
            MODULE.build_article_srt(edit)

    def test_segment_ending_on_punctuation_is_consumed(self) -> None:
        """A sentence-final token carries no content, so the match loop misses it.

        The loop stops the moment `accumulated == target`, and targets are
        punctuation-free — so a trailing 。could never be reached. `--build` then
        refused with "semantic lines leave kept words unmatched in segment 1:
        '。'" on every segment that ended on 。or ，. Observed on a real 4m38s
        project whose first range ends with 「…抄袭和盗版。」.
        """
        root = Path(tempfile.mkdtemp(prefix="video-use-caption-punct-"))
        (root / "transcripts").mkdir()
        (root / "edl.json").write_text(json.dumps({
            "version": 1,
            "sources": {"A": "/tmp/A.mp4"},
            "ranges": [{"source": "A", "start": 0.0, "end": 3.0}],
        }), encoding="utf-8")
        (root / "transcripts" / "A.json").write_text(json.dumps({"words": [
            {"type": "word", "text": "你", "start": 0.1, "end": 0.4},
            {"type": "word", "text": "好", "start": 0.5, "end": 0.8},
            {"type": "word", "text": "。", "start": 0.8, "end": 0.8},
        ]}, ensure_ascii=False), encoding="utf-8")

        MODULE.prepare_article(root)
        (root / "captions_article.txt").write_text("你好。\n", encoding="utf-8")
        (root / "semantic_lines.txt").write_text("你好。\n", encoding="utf-8")
        MODULE.lock_article(root)
        MODULE.build_article_srt(root)
        MODULE.check_article_srt(root)

        cues = MODULE.parse_srt(root / "subtitles.srt")
        self.assertEqual([cue[2] for cue in cues], ["你好。"])
        # the cue still ends on the last CONTENT word, not on a zero-length token
        self.assertAlmostEqual(cues[0][1], 0.8, places=3)

    def test_measured_durations_skips_stale_history_until_matching_entry(self) -> None:
        edit = self.make_edit()
        edl = edit / "edl.json"
        durations = {"old": {"durations": [9.0], "edl_sha256": "stale"},
                     "current": {"durations": [1.25, 2.5], "edl_sha256": MODULE._sha256(edl)}}
        (edit / "segment_durations.json").write_text(json.dumps(durations), encoding="utf-8")
        self.assertEqual(MODULE._measured_durations(edit, edl, 2, True),
                         ([1.25, 2.5], "measured"))

    def test_a_projected_plan_is_usable_but_marked_projected(self) -> None:
        """duration_plan.py lets captions/timeline exist before the render.

        It must stay distinguishable from a render, because `verify_delivery`
        compares a real file against a recorded render.
        """
        edit = self.make_edit()
        edl = edit / "edl.json"
        (edit / "segment_durations.json").write_text(json.dumps({
            "plan": {"durations": [1.25, 2.5], "edl_sha256": MODULE._sha256(edl),
                     "projected": True, "fps": 30.0},
        }), encoding="utf-8")
        self.assertEqual(MODULE._measured_durations(edit, edl, 2, True),
                         ([1.25, 2.5], "projected"))

    def test_a_real_render_wins_over_a_projection(self) -> None:
        edit = self.make_edit()
        edl = edit / "edl.json"
        digest = MODULE._sha256(edl)
        (edit / "segment_durations.json").write_text(json.dumps({
            "plan": {"durations": [1.25, 2.5], "edl_sha256": digest,
                     "projected": True, "fps": 30.0},
            "final": {"durations": [1.3, 2.6], "edl_sha256": digest},
        }), encoding="utf-8")
        self.assertEqual(MODULE._measured_durations(edit, edl, 2, True),
                         ([1.3, 2.6], "measured"))

    def test_measured_durations_rejects_only_when_no_entry_matches(self) -> None:
        edit = self.make_edit()
        edl = edit / "edl.json"
        (edit / "segment_durations.json").write_text(json.dumps({
            "old": {"durations": [9.0], "edl_sha256": "stale"},
            "another": {"durations": [1.0, 2.0], "edl_sha256": "stale"},
        }), encoding="utf-8")
        with self.assertRaises(SystemExit):
            MODULE._measured_durations(edit, edl, 2, True)


if __name__ == "__main__":
    unittest.main()

class BoundaryWordInclusion(unittest.TestCase):
    """段尾被切点吃到一小截的词：整字丢掉会把句子断成「你要解决」。

    2026-10-21 的真实素材里，EDL 段尾系统性短一帧（0.04s），17/9 个尾字被整字
    丢弃。判据改为按"字头位置"分开：字头在段内 → 可见 ≥45% 就收；字头在段前
    （跨段首）→ 仍要 ≥80%，否则同一个词会同时塞进前后两段。
    """

    @staticmethod
    def _transcript(words):
        return {"words": [{"type": "word", "text": t, "start": a, "end": b}
                          for t, a, b in words]}

    def test_word_starting_inside_is_kept_when_tail_is_clipped(self):
        tr = self._transcript([("解", 0.0, 0.2), ("决", 0.2, 0.4), ("它。", 0.4, 0.6)])
        kept = MODULE._words_in_range(tr, 0.0, 0.5)
        self.assertIn("它。", [w["text"] for w in kept], kept)

    def test_word_straddling_segment_start_still_needs_80_percent(self):
        tr = self._transcript([("前", 0.0, 0.2), ("跨段", 0.2, 0.6), ("后", 0.7, 0.9)])
        kept = MODULE._words_in_range(tr, 0.3, 1.0)
        texts = [w["text"] for w in kept]
        self.assertNotIn("跨段", texts, texts)
        self.assertIn("后", texts, texts)
