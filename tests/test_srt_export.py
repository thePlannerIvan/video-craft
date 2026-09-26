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


if __name__ == "__main__":
    unittest.main()
