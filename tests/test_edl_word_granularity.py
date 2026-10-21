#!/usr/bin/env python3
"""Regression: the EDL preview must select words, not whole sentences.

The 2026-10-21 XHS delivery shipped three preview pages whose transcripts were
one token per sentence. The page rendered a `<span>` per token and the drag
handler selects tokens, so a drag on "上" highlighted an 11s sentence. Nothing
in the old static checks noticed, because the page itself was correct — the
data was coarse.

These tests pin the two halves of the fix:

1. `refine_transcript.py` turns a sentence-level transcript into per-character
   tokens while preserving the confirmed text byte for byte.
2. `edl_preview_build.py` warns loudly when it is handed coarse data instead of
   silently rendering another whole-sentence picker.
3. A real browser drag on a refined page selects a short interval; the same
   drag on a coarse page selects the sentence (the red-capable control).
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HELPERS = ROOT / "helpers"
sys.path.insert(0, str(HELPERS))

SENTENCE = "今天我们讲两个方法。"


def write_fixture(edit: Path, refined: bool = False):
    (edit / "transcripts").mkdir(parents=True, exist_ok=True)
    (edit / "edl.json").write_text(json.dumps({
        "sources": {"a": "../source.mp4"},
        "ranges": [{"source": "a", "start": 1.0, "end": 4.0, "beat": "TEST"}],
    }, ensure_ascii=False), encoding="utf-8")
    (edit / "transcripts" / "a.json").write_text(json.dumps({
        "language_code": "zho",
        "text": SENTENCE,
        "words": [{"text": SENTENCE, "type": "word", "start": 1.0, "end": 4.0,
                   "speaker_id": "speaker_0"}],
    }, ensure_ascii=False), encoding="utf-8")
    (edit / "takes_packed.md").write_text(
        "# Packed transcripts\n\n## a  (duration: 3.0s, 1 phrases)\n"
        "  [001.00-004.00] S0 今 天 我 们 讲 两 个 方 法 。\n", encoding="utf-8")
    asr = []
    for index, char in enumerate(SENTENCE):
        start = 1.0 + index * 0.25
        asr.append({"text": char, "start": round(start, 2), "end": round(start + 0.2, 2)})
    (edit / "asr.json").write_text(json.dumps({"tokens": asr}, ensure_ascii=False),
                                   encoding="utf-8")
    if refined:
        run([sys.executable, str(HELPERS / "refine_transcript.py"), str(edit),
             "--source", "a", "--asr", str(edit / "asr.json"), "--force"])


def run(cmd, env=None):
    merged = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    if env:
        merged.update(env)
    result = subprocess.run(cmd, capture_output=True, text=True, env=merged)
    if result.returncode != 0:
        raise AssertionError(f"{cmd} failed:\n{result.stdout}\n{result.stderr}")
    return result


def build_page(edit: Path):
    result = run([sys.executable, str(HELPERS / "edl_preview_build.py"), str(edit)])
    return result, (edit / "edl_preview.html").read_text(encoding="utf-8")


def have_playwright():
    try:
        import playwright.sync_api  # noqa: F401
        return True
    except ImportError:
        return False


class RefineTranscriptTest(unittest.TestCase):
    def test_refines_sentence_to_characters_and_preserves_text(self):
        with tempfile.TemporaryDirectory() as td:
            edit = Path(td)
            write_fixture(edit, refined=True)
            doc = json.loads((edit / "transcripts" / "a.json").read_text(encoding="utf-8"))
            words = [w for w in doc["words"] if w.get("type", "word") != "spacing"]
            self.assertGreaterEqual(len(words), len([c for c in SENTENCE if c not in "。，！？；："]))
            self.assertEqual("".join(w["text"] for w in words), SENTENCE)
            self.assertLess(max(w["end"] - w["start"] for w in words), 1.0)
            for left, right in zip(words, words[1:]):
                self.assertLessEqual(left["end"], right["start"] + 1e-3)
            self.assertTrue((edit / "transcripts" / "_coarse" / "a.json").exists())

    def test_empty_asr_fails_loudly(self):
        with tempfile.TemporaryDirectory() as td:
            edit = Path(td)
            write_fixture(edit)
            (edit / "asr.json").write_text(json.dumps({"tokens": []}), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(HELPERS / "refine_transcript.py"), str(edit),
                 "--source", "a", "--asr", str(edit / "asr.json"), "--force"],
                capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("no timed tokens", result.stderr)

    def test_mismatched_asr_never_rewrites_the_confirmed_text(self):
        with tempfile.TemporaryDirectory() as td:
            edit = Path(td)
            write_fixture(edit)
            # The ASR heard something else; alignment must still keep the
            # reviewed wording (timing may fall back to interpolation).
            (edit / "asr.json").write_text(json.dumps({"tokens": [
                {"text": "完", "start": 1.0, "end": 1.2},
                {"text": "全", "start": 1.2, "end": 1.4},
                {"text": "不", "start": 1.4, "end": 1.6},
                {"text": "同", "start": 1.6, "end": 1.8},
            ]}, ensure_ascii=False), encoding="utf-8")
            run([sys.executable, str(HELPERS / "refine_transcript.py"), str(edit),
                 "--source", "a", "--asr", str(edit / "asr.json"), "--force"])
            doc = json.loads((edit / "transcripts" / "a.json").read_text(encoding="utf-8"))
            words = [w for w in doc["words"] if w.get("type", "word") != "spacing"]
            self.assertEqual("".join(w["text"] for w in words), SENTENCE)


class PreviewGranularityTest(unittest.TestCase):
    def test_coarse_transcript_is_flagged_not_silently_shipped(self):
        with tempfile.TemporaryDirectory() as td:
            edit = Path(td)
            write_fixture(edit)
            result, html = build_page(edit)
            self.assertIn("句子级", result.stderr)
            self.assertIn('"count": 1', html)
            self.assertIn("coarse-warning", html)

    def test_refined_transcript_builds_without_warning(self):
        with tempfile.TemporaryDirectory() as td:
            edit = Path(td)
            write_fixture(edit, refined=True)
            result, html = build_page(edit)
            self.assertNotIn("句子级", result.stderr)
            self.assertIn('"count": 0', html)

    @unittest.skipIf(os.environ.get("VIDEO_CRAFT_BROWSER_TESTS") == "0",
                     "set VIDEO_CRAFT_BROWSER_TESTS=0 to skip local browser test")
    @unittest.skipUnless(have_playwright(), "needs playwright")
    def test_coarse_page_selects_the_sentence_control(self):
        """The red control: without refinement the same drag cuts 3 seconds."""
        from playwright.sync_api import sync_playwright

        with tempfile.TemporaryDirectory() as td:
            edit = Path(td)
            write_fixture(edit)
            _, _html = build_page(edit)
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                page = browser.new_page(viewport={"width": 1600, "height": 1000})
                page.goto((edit / "edl_preview.html").as_uri(), wait_until="domcontentloaded")
                page.wait_for_function(
                    "document.querySelectorAll('#w-root .w').length > 0", timeout=15000)
                box = page.eval_on_selector("#w-root .w", """el => {
                    const r = el.getBoundingClientRect();
                    return {x: r.x, y: r.y, h: r.height};
                }""")
                y = box["y"] + box["h"] / 2
                page.mouse.move(box["x"] + 3, y)
                page.mouse.down()
                page.mouse.move(box["x"] + 18, y, steps=5)
                page.mouse.up()
                stats = page.text_content("#wstats")
                match = re.search(r"约减 ([\d.]+)s", stats)
                self.assertIsNotNone(match, stats)
                self.assertGreater(float(match.group(1)), 2.0, stats)
                browser.close()

    @unittest.skipIf(os.environ.get("VIDEO_CRAFT_BROWSER_TESTS") == "0",
                     "set VIDEO_CRAFT_BROWSER_TESTS=0 to skip local browser test")
    @unittest.skipUnless(have_playwright(), "needs playwright")
    def test_drag_selects_a_short_word_not_the_sentence(self):
        from playwright.sync_api import sync_playwright

        with tempfile.TemporaryDirectory() as td:
            edit = Path(td)
            write_fixture(edit, refined=True)
            _, _html = build_page(edit)
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                page = browser.new_page(viewport={"width": 1600, "height": 1000})
                page.goto((edit / "edl_preview.html").as_uri(), wait_until="domcontentloaded")
                page.wait_for_function(
                    "document.querySelectorAll('#w-root .w').length > 0", timeout=15000)
                count = page.eval_on_selector_all("#w-root .w", "els => els.length")
                self.assertGreater(count, 5)
                box = page.eval_on_selector("#w-root .w", """el => {
                    const r = el.getBoundingClientRect();
                    return {x: r.x, y: r.y, h: r.height};
                }""")
                y = box["y"] + box["h"] / 2
                page.mouse.move(box["x"] + 3, y)
                page.mouse.down()
                page.mouse.move(box["x"] + 18, y, steps=5)
                page.mouse.up()
                stats = page.text_content("#wstats")
                match = re.search(r"约减 ([\d.]+)s", stats)
                self.assertIsNotNone(match, stats)
                self.assertLess(float(match.group(1)), 1.0, stats)
                browser.close()


class ApplySelectionTest(unittest.TestCase):
    def test_rounded_word_edges_snap_instead_of_walking_the_sentence(self):
        """A 10ms inset used to trigger the silence-edge chain walk, which on a
        character-level transcript runs to the end of the sentence. Word edges
        must snap to token boundaries instead."""
        with tempfile.TemporaryDirectory() as td:
            edit = Path(td)
            write_fixture(edit, refined=True)
            doc = json.loads((edit / "transcripts" / "a.json").read_text(encoding="utf-8"))
            words = [w for w in doc["words"] if w.get("type", "word") != "spacing"]
            target = words[3]
            (edit / "selections.json").write_text(json.dumps({
                "words": [{"src": "a", "start": round(target["start"] + 0.01, 3),
                           "end": round(target["end"] - 0.01, 3)}],
            }, ensure_ascii=False), encoding="utf-8")
            run([sys.executable, str(HELPERS / "apply_selection.py"), str(edit)])
            edl = json.loads((edit / "edl.json").read_text(encoding="utf-8"))
            removed = 3.0 - sum(r["end"] - r["start"] for r in edl["ranges"])
            self.assertAlmostEqual(removed, target["end"] - target["start"], places=2)
            self.assertGreater(len(edl["ranges"]), 1)

    def test_deleting_one_word_only_removes_that_word(self):
        with tempfile.TemporaryDirectory() as td:
            edit = Path(td)
            write_fixture(edit, refined=True)
            doc = json.loads((edit / "transcripts" / "a.json").read_text(encoding="utf-8"))
            words = [w for w in doc["words"] if w.get("type", "word") != "spacing"]
            target = words[3]
            (edit / "selections.json").write_text(json.dumps({
                "words": [{"src": "a", "start": target["start"], "end": target["end"]}],
            }, ensure_ascii=False), encoding="utf-8")
            run([sys.executable, str(HELPERS / "apply_selection.py"), str(edit)])
            edl = json.loads((edit / "edl.json").read_text(encoding="utf-8"))
            removed = 3.0 - sum(r["end"] - r["start"] for r in edl["ranges"])
            self.assertAlmostEqual(removed, target["end"] - target["start"], places=2)
            self.assertGreater(len(edl["ranges"]), 1)
            self.assertEqual(edl["ranges"][0]["start"], 1.0)
            self.assertEqual(edl["ranges"][-1]["end"], 4.0)


if __name__ == "__main__":
    unittest.main()
