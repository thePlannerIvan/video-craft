#!/usr/bin/env python3
"""A step key the generator reads may not be silently dropped by the derive.

This is the guard for a class of bug that cost a whole picture track. The step
dict in `timeline_derive.build_timeline` used to be a hand-maintained whitelist
whose own comment claimed it listed "what `generate-composition.py` reads". It
did not: `mediaClips` and `mediaBox` were missing, so a grouping that declared
the screen recording lost it at the derive step — and `generate-composition.py
--verify` still reported success, because verify counts N videos when
`mediaClips` exists and exactly 1 section when it does not. A composition with
no media is indistinguishable, to that check, from a composition that never
declared any. The symptom was a picture track that simply was not there.

The fix is an exclusion set (`OWNED_STEP_KEYS`): everything the author declared
passes through unless this module owns it. The property that makes it safe is
what this file pins — **the set of keys the GENERATOR reads must survive the
derive**. The generator's source is scraped rather than restated, so adding a key
to `generate-composition.py` and forgetting this module fails here instead of
shipping an empty track.
"""
from __future__ import annotations

import importlib.util
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
HELPERS = ROOT / "helpers"
# page 十步路线已存档：真正的生成器在 _legacy_page/，原路径只剩 CLI 转发 shim
GENERATOR = ROOT / "visual" / "scripts" / "_legacy_page" / "generate-composition.py"
sys.path.insert(0, str(HELPERS))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"craft_{name}", HELPERS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


timeline_derive = _load("timeline_derive")

# The generator's own local names for a step. Kept here because the scrape has to
# know what to look for; if the generator renames these the count guard below
# fails loudly rather than passing vacuously.
STEP_VARS = ("step", "st", "s")


def generator_step_keys() -> set[str]:
    """Every key `generate-composition.py` reads off a step, scraped from source.

    Covers both `st.get("k")` and the direct `st["k"]` that `verify()` uses; the
    latter matters because `verify` indexes `mc["startMs"]` rather than defaulting
    it, so a missing key is a crash there and a silent omission before it.
    """
    source = GENERATOR.read_text(encoding="utf-8")
    pattern = r'\b(?:' + "|".join(STEP_VARS) + r')(?:\.get\(|\[)\s*"([A-Za-z_][A-Za-z0-9_]*)"'
    return set(re.findall(pattern, source))


def _entries(n: int = 2) -> list[dict]:
    """Minimal entries — `build_timeline` reads only these six fields."""
    return [
        {"startMs": i * 1000, "endMs": (i + 1) * 1000, "text": f"cue{i}",
         "segment": 0, "wordIndices": [i], "sourceRange": [float(i), float(i) + 1.0]}
        for i in range(n)
    ]


def _derive(step_extra: dict) -> dict:
    grouping = {"chapters": [{"id": "c", "title": "t", "steps": [
        {"cueIndices": [0, 1], **step_extra},
    ]}]}
    timeline, _ = timeline_derive.build_timeline(_entries(), grouping)
    return timeline["chapters"][0]["steps"][0]


class GeneratorKeyPassthroughTests(unittest.TestCase):

    def test_the_scrape_finds_the_generators_reads(self):
        """A vacuous guard is worse than none: prove the scrape still bites."""
        keys = generator_step_keys()
        self.assertGreaterEqual(
            len(keys), 6,
            f"只在 {GENERATOR.name} 里刮到 {sorted(keys)}；生成器换了写法，"
            f"守卫已失效，请更新 STEP_VARS")
        # The two that actually went missing, named so the regression is pinned
        # even if the scrape later widens.
        self.assertIn("mediaClips", keys)
        self.assertIn("mediaBox", keys)

    def test_no_key_the_generator_reads_is_dropped_by_the_derive(self):
        keys = generator_step_keys()
        declared = {k: f"<{k}>" for k in sorted(keys)}
        step = _derive(declared)
        dropped = sorted(k for k in keys if k not in step)
        self.assertEqual(
            dropped, [],
            f"这些键生成器会读，但 derive 把它们丢了：{dropped}。"
            f"要么让它们透传（不要放进 OWNED_STEP_KEYS），"
            f"要么在 build_timeline 的 dict 里显式算出来。当前 OWNED_STEP_KEYS="
            f"{sorted(timeline_derive.OWNED_STEP_KEYS)}")

    def test_an_unknown_future_key_passes_through(self):
        """The whole point of an exclusion set: a new key needs no edit here."""
        step = _derive({"aKeyNoOneHasInventedYet": {"nested": [1, 2]}})
        self.assertEqual(step["aKeyNoOneHasInventedYet"], {"nested": [1, 2]})

    def test_the_picture_track_survives_verbatim(self):
        """The concrete regression: a declared screen clip reaches the timeline."""
        clips = [{"src": "edit/_engineering/screen.mp4", "in": 55.433,
                  "startMs": 55433, "durationMs": 5744,
                  "box": [628, 82, 1236, 916]}]
        step = _derive({"mediaClips": clips, "mediaBox": [0, 0, 1920, 1080]})
        self.assertEqual(step["mediaClips"], clips)
        self.assertEqual(step["mediaBox"], [0, 0, 1920, 1080])

    def test_time_keys_are_recomputed_not_copied(self):
        """An author value for a derived time must not leak through."""
        step = _derive({"startMs": 999999, "endMs": 123, "durationMs": 5})
        self.assertEqual(step["startMs"], 0)
        self.assertEqual(step["endMs"], 2000)
        self.assertEqual(step["durationMs"], 2000)

    def test_caption_is_the_one_owned_key_with_an_author_override(self):
        """Every owned key is recomputed — except `caption`, which the author may
        replace on purpose (`step.get("caption") or caption`). Pinned so a future
        refactor cannot quietly turn that override into a no-op."""
        self.assertEqual(_derive({})["caption"], "cue0 cue1")
        self.assertEqual(_derive({"caption": "作者改过的"})["caption"], "作者改过的")

    def test_existing_key_order_is_preserved(self):
        """Pass-through runs after the literal, so old timelines stay byte-identical."""
        step = _derive({"screenIntent": "hook", "visualModel": "m", "mediaClips": []})
        keys = list(step)
        self.assertLess(keys.index("screenIntent"), keys.index("mediaClips"))
        self.assertEqual(keys[-1], "mediaClips")


if __name__ == "__main__":
    unittest.main()
