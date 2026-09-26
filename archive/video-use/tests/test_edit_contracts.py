"""Contracts added after the 2026-09-10 「新职场体系」 delivery.

Each test pins a failure that actually reached a render or a delivery:

  * a scripted deletion that addressed the wrong words (index space, not text);
  * an SRT built on the EDL's nominal timeline while the render disagreed;
  * sub-ranges left with no speech after a deletion;
  * a cleanup pass that must never touch the rebuildable minimum.
"""
import importlib.util
import json
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
    spec.loader.exec_module(module)
    return module


WORDS = load("_words")
EDL_LIB = load("_edl")
CHECK = load("check_edl")
EDIT = load("edl_edit")
CLEAN = load("clean_edit_dir")
VERIFY = load("verify_delivery")
SRT = load("srt_export")


def make_edit(segments=None) -> Path:
    """A two-segment project with one duplicated token to delete."""
    root = Path(tempfile.mkdtemp(prefix="video-use-edit-contract-"))
    (root / "transcripts").mkdir()
    ranges = segments or [
        {"source": "A", "start": 0.0, "end": 3.0},
        {"source": "A", "start": 6.0, "end": 9.0},
    ]
    edl = {"version": 1, "sources": {"A": str(root / "A.mp4")}, "ranges": ranges}
    (root / "edl.json").write_text(json.dumps(edl), encoding="utf-8")
    (root / "A.mp4").write_bytes(b"stub")
    words = [
        {"type": "word", "text": "那", "start": 0.60, "end": 0.80},
        {"type": "word", "text": "那", "start": 0.82, "end": 1.02},
        {"type": "word", "text": "反过来", "start": 1.04, "end": 1.60},
        {"type": "word", "text": "一样", "start": 1.62, "end": 2.10},
        {"type": "word", "text": "第二段", "start": 6.10, "end": 6.70},
        {"type": "word", "text": "收尾", "start": 6.80, "end": 7.20},
    ]
    (root / "transcripts" / "A.json").write_text(json.dumps({"words": words}), encoding="utf-8")
    return root


def write_measured(edit: Path, durations: list[float], fps: float = 30.0) -> None:
    edl_path = edit / "edl.json"
    (edit / "segment_durations.json").write_text(json.dumps({
        "final": {
            "durations": durations,
            "total_s": round(sum(durations), 6),
            "edl_sha256": EDL_LIB.edl_digest(edl_path),
            "fps": fps,
        }
    }, ensure_ascii=False), encoding="utf-8")


class WordHelperTests(unittest.TestCase):
    def test_normalization_ignores_punctuation_and_width(self) -> None:
        self.assertEqual(WORDS.normalize("你好，世界！"), WORDS.normalize("你好世界"))
        self.assertEqual(WORDS.normalize("ＡＩ native"), WORDS.normalize("ai native"))
        self.assertEqual(WORDS.content_len("要带 8~10 个人"), 7)

    def test_nfkc_generated_ascii_punctuation_is_stripped(self) -> None:
        """NFKC rewrites full-width punctuation to ASCII *before* the strip.

        A colon in the reviewed article used to survive normalize() (the strip
        listed ASCII ",.!?" but not ":"), so `srt_export --lock` failed with
        "article does not cover the kept word sequence" — blaming the article.
        """
        for full_width, ascii_form in [("：", ":"), ("；", ";"), ("～", "~"),
                                       ("／", "/"), ("％", "%"), ("＝", "="),
                                       ("＃", "#"), ("＋", "+"), ("＠", "@")]:
            self.assertEqual(WORDS.normalize(f"甲{full_width}乙"), "甲乙",
                             f"{full_width} (NFKC → {ascii_form}) must be stripped")
        self.assertEqual(WORDS.content_len("问我说："), 3)

    def test_caption_contract_shares_one_normalization(self) -> None:
        """`srt_export` must not carry its own copy of the rule.

        It used to, which made _words.py's "single source of truth" claim false
        and let the caption contract drift from the EDL contracts.
        """
        self.assertFalse(hasattr(SRT, "PUNCTUATION_RE"),
                         "srt_export re-defined the punctuation rule")
        for text in ["你好，世界！", "问我说：", "ＡＩ native", "甲；乙",
                     "DeepSeek V4 Flash 4.1"]:
            self.assertEqual(SRT._match_text(text), WORDS.normalize(text))
            self.assertEqual(SRT._content_len(text), WORDS.content_len(text))

    def test_raw_transcript_index_is_kept(self) -> None:
        edit = make_edit()
        words = WORDS.load_words(edit, "A")
        self.assertEqual([w["transcript_index"] for w in words], [0, 1, 2, 3, 4, 5])


class ScriptedEditTests(unittest.TestCase):
    def run_edit(self, edit: Path, *argv: str) -> int:
        argv_backup = sys.argv
        sys.argv = ["edl_edit.py", str(edit), *argv]
        try:
            return EDIT.main()
        finally:
            sys.argv = argv_backup

    def test_wrong_assertion_refuses_to_write(self) -> None:
        edit = make_edit()
        before = (edit / "edl.json").read_text(encoding="utf-8")
        with self.assertRaises(SystemExit):
            self.run_edit(edit, "--delete", "0.82,1.02=不存在的词")
        self.assertEqual((edit / "edl.json").read_text(encoding="utf-8"), before)

    def test_matching_assertion_splits_on_word_boundaries(self) -> None:
        edit = make_edit()
        self.assertEqual(self.run_edit(edit, "--delete", "0.82,1.02=那"), 0)
        edl = json.loads((edit / "edl.json").read_text(encoding="utf-8"))
        kept = [(r["start"], r["end"]) for r in edl["ranges"]]
        self.assertIn((0.0, 0.82), kept)
        self.assertIn((1.02, 3.0), kept)
        self.assertTrue((edit / "edl.previous.json").exists())

    def test_fragment_ranges_are_dropped(self) -> None:
        edit = make_edit()
        # delete both duplicated tokens; the sliver between them holds no word
        self.assertEqual(self.run_edit(edit, "--delete", "0.60,0.80=那"), 0)
        self.assertEqual(self.run_edit(edit, "--delete", "0.82,1.02=那"), 0)
        edl = json.loads((edit / "edl.json").read_text(encoding="utf-8"))
        for r in edl["ranges"]:
            words = WORDS.words_inside(WORDS.load_words(edit, "A"), r["start"], r["end"])
            self.assertTrue(words, f"range {r['start']}-{r['end']} has no complete word")

    def test_edit_refuses_when_it_would_break_the_cut(self) -> None:
        edit = make_edit()
        # restore a span that overlaps an existing range: the merge must not
        # leave a cut inside a word, so the health check is what guards it
        self.assertEqual(self.run_edit(edit, "--delete", "0.82,1.02=那"), 0)
        self.assertEqual(self.run_edit(edit, "--restore", "0.82,1.02=那"), 0)
        result = CHECK.check(edit)
        self.assertTrue(result["ok"], result["hard"])


class EdlHealthTests(unittest.TestCase):
    def test_cut_inside_word_is_hard(self) -> None:
        edit = make_edit(segments=[{"source": "A", "start": 0.0, "end": 0.90}])
        result = CHECK.check(edit)
        self.assertFalse(result["ok"])
        self.assertTrue(any("切在词内" in m for m in result["hard"]))

    def test_fragment_range_is_warning_not_hard(self) -> None:
        edit = make_edit(segments=[{"source": "A", "start": 2.20, "end": 2.80}])
        result = CHECK.check(edit)
        self.assertTrue(any("没有完整词" in m for m in result["warn"]))
        self.assertTrue(result["ok"], result["hard"])

    def test_pause_budget_is_hard(self) -> None:
        edit = make_edit(segments=[
            {"source": "A", "start": 0.00, "end": 1.40},
            {"source": "A", "start": 5.80, "end": 7.30},
        ])
        result = CHECK.check(edit, max_pause=0.3)
        self.assertFalse(result["ok"])
        self.assertTrue(any("停顿" in m or "静音" in m for m in result["hard"]))

    def test_stale_render_hash_is_reported(self) -> None:
        edit = make_edit()
        write_measured(edit, [3.0, 3.0])
        (edit / "edl.json").write_text(
            (edit / "edl.json").read_text(encoding="utf-8").replace("9.0", "8.5"),
            encoding="utf-8")
        result = CHECK.check(edit)
        self.assertTrue(any("哈希不符" in m for m in result["warn"]), result["warn"])

    def test_srt_on_nominal_timeline_is_hard_once_a_render_exists(self) -> None:
        edit = make_edit()
        SRT.prepare_article(edit)
        (edit / "captions_article.txt").write_text("那那反过来一样\n\n第二段收尾\n", encoding="utf-8")
        (edit / "semantic_lines.txt").write_text("那那反过来一样\n\n第二段收尾\n", encoding="utf-8")
        SRT.lock_article(edit)
        SRT.build_article_srt(edit)
        # the cues were built with no render present
        self.assertEqual(json.loads((edit / "caption_words.json").read_text(
            encoding="utf-8"))["timeline_source"], "nominal")
        write_measured(edit, [3.2, 3.2])
        result = CHECK.check(edit)
        self.assertFalse(result["ok"])
        self.assertTrue(any("标称时间轴" in m for m in result["hard"]), result["hard"])


class MeasuredTimelineTests(unittest.TestCase):
    def build(self, edit: Path) -> None:
        SRT.prepare_article(edit)
        (edit / "captions_article.txt").write_text("那那反过来一样\n\n第二段收尾\n", encoding="utf-8")
        (edit / "semantic_lines.txt").write_text("那那反过来一样\n\n第二段收尾\n", encoding="utf-8")
        SRT.lock_article(edit)
        SRT.build_article_srt(edit)

    def test_cues_use_measured_segment_durations(self) -> None:
        edit = make_edit()
        # the render came out 0.4s longer on the first segment than the EDL said
        write_measured(edit, [3.4, 3.0])
        self.build(edit)
        cues = SRT.parse_srt(edit / "subtitles.srt")
        # second segment starts on the nominal offset 3.0 + the 0.4s the encoder
        # actually produced
        self.assertAlmostEqual(cues[-1][0], 3.5, places=2)
        self.assertEqual(json.loads((edit / "caption_words.json").read_text(
            encoding="utf-8"))["timeline_source"], "measured")

    def test_build_refuses_a_stale_render(self) -> None:
        edit = make_edit()
        write_measured(edit, [3.4, 3.0])
        SRT.prepare_article(edit)
        # the EDL moves after the render: the durations no longer describe it
        (edit / "edl.json").write_text(
            (edit / "edl.json").read_text(encoding="utf-8").replace("9.0", "8.7"),
            encoding="utf-8")
        (edit / "captions_article.txt").write_text("那那反过来一样\n\n第二段收尾\n", encoding="utf-8")
        (edit / "semantic_lines.txt").write_text("那那反过来一样\n\n第二段收尾\n", encoding="utf-8")
        with self.assertRaises(SystemExit):
            SRT.lock_article(edit)

    def test_prepare_keeps_the_reviewed_line_plan(self) -> None:
        edit = make_edit()
        SRT.prepare_article(edit)
        (edit / "semantic_lines.txt").write_text("那那反过来一样\n\n第二段收尾\n", encoding="utf-8")
        SRT.prepare_article(edit, force=True)
        self.assertTrue((edit / "semantic_lines.txt").exists())


class CleanupTests(unittest.TestCase):
    def test_rebuildable_minimum_survives(self) -> None:
        edit = make_edit()
        (edit / "clips_final").mkdir()
        (edit / "clips_final" / "seg_00.mp4").write_bytes(b"x" * 1024)
        (edit / "base.mp4").write_bytes(b"x" * 2048)
        (edit / "final.mp4").write_bytes(b"x" * 4096)
        (edit / "subtitles.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\n你好\n",
                                            encoding="utf-8")
        (edit / "project.md").write_text("memory\n", encoding="utf-8")
        delete, keep = CLEAN.plan(edit)
        names = {n for n, _ in delete}
        kept = {n for n, _ in keep}
        self.assertIn("clips_final", names)
        self.assertIn("base.mp4", names)
        self.assertIn("final.mp4", names)
        self.assertIn("subtitles.srt", kept)
        self.assertIn("transcripts", kept)
        self.assertIn("edl.json", kept)
        self.assertNotIn("project.md", names)


class DeliveryParsingTests(unittest.TestCase):
    def test_srt_cue_parser(self) -> None:
        edit = make_edit()
        srt = edit / "x.srt"
        srt.write_text("1\n00:00:01,000 --> 00:00:02,500\n你好\n\n"
                       "2\n01:02:03,400 --> 01:02:05,000\n世界\n", encoding="utf-8")
        cues = VERIFY.srt_cues(srt)
        self.assertEqual(len(cues), 2)
        self.assertAlmostEqual(cues[0][0], 1.0, places=3)
        self.assertAlmostEqual(cues[1][1], 3725.0, places=3)


if __name__ == "__main__":
    unittest.main()
