"""The theme library is read by other skills, so a broken theme is a library defect.

Four failure classes, all previously silent:

① **`theme.json` was never parsed.** Every theme could have shipped invalid JSON
   or lost a field and nothing would have noticed — `scaffold.sh` greps for three
   keys with `sed` and never validates.

② **A `var()` pointing at nothing.** All 23 themes wrote `--r-card: var(--r-sm)`
   while no `--r-*` was defined anywhere in v2 (the scale lived in an archived v1
   `base.css`). CSS drops the whole declaration and falls back to the initial
   value, so every card just went square and nobody failed.
   `test_unresolved_var_is_a_failure` is that bug.

③ **Contrast.** `--text` / `--text-2` on `--surface` is the one numeric rule
   `themes.md` states; the test against the real library pins it.

④ **A second source of truth for rhythm.** All 23 themes carried `--dur-*`, two
   carried `--ease-*`, and no code read any of them — while `themes.md` says the
   rhythm lives in `theme.json`'s `mood` and each step times its own tween to the
   spoken word. Left in place they invite timing tweens by theme instead of by
   speech. `test_a_theme_that_fixes_rhythm_is_a_failure` is that rule.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

SKILL = Path(__file__).parents[1]
SCRIPTS = SKILL / "visual" / "scripts"
THEMES = SKILL / "visual" / "themes"


def load(name: str):
    spec = importlib.util.spec_from_file_location(f"video_craft_{name}", SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


themes = load("check_themes")

META = {
    "id": "demo", "name": "Demo", "nameZh": "演示",
    "description": "A demo theme.", "descriptionZh": "一个演示主题。",
    "mood": ["quiet"], "bestFor": ["tests"],
    "preview": {"shell": "#000000", "surface": "#101010",
                "text": "#f5f5f5", "accent": "#ff4a2b"},
}

TOKENS = """
:root {
  --shell: #000000;
  --surface: #101010;
  --surface-2: #181818;
  --surface-3: #202020;
  --text: #f5f5f5;
  --text-2: #dfdfdf;
  --text-mute: #9a9a9a;
  --text-faint: #6a6a6a;
  --rule: #2f2f2f;
  --accent: #ff4a2b;
  --accent-soft: rgba(255, 74, 43, 0.14);
  --accent-glow: rgba(255, 74, 43, 0.55);
  --font-display-cn: "Noto Serif SC", serif;
  --font-display-en: "Instrument Serif", serif;
  --font-body: "Manrope", sans-serif;
  --font-mono: "JetBrains Mono", monospace;
  --r-flat:  0;
  --r-xs:    4px;
  --r-sm:    8px;
  --r-md:    16px;
  --r-lg:    20px;
  --r-xl:    32px;
  --r-card:  var(--r-sm);
  --r-stage: 0;
}
"""


class ThemeFixture(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def make(self, name: str = "demo", meta: dict | None = None,
             tokens: str | None = None) -> Path:
        theme = self.root / name
        theme.mkdir(parents=True, exist_ok=True)
        payload = dict(meta if meta is not None else META)
        payload.setdefault("id", name)
        theme.joinpath("theme.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        theme.joinpath("tokens.css").write_text(
            tokens if tokens is not None else TOKENS, encoding="utf-8")
        return theme

    def check(self, path: Path) -> dict:
        return themes.check_theme(path)


class MetadataTests(ThemeFixture):
    def test_a_complete_theme_passes(self):
        result = self.check(self.make())
        self.assertEqual(result["failures"], [])

    def test_invalid_json_is_a_failure_not_a_crash(self):
        theme = self.make()
        (theme / "theme.json").write_text("{ this is not json", encoding="utf-8")
        result = self.check(theme)
        self.assertTrue(any("not valid JSON" in f for f in result["failures"]),
                        result["failures"])

    def test_a_missing_field_is_a_failure(self):
        meta = {k: v for k, v in META.items() if k != "bestFor"}
        result = self.check(self.make(meta=meta))
        self.assertTrue(any("bestFor" in f for f in result["failures"]), result["failures"])

    def test_id_must_equal_the_directory_name(self):
        meta = dict(META, id="something-else")
        result = self.check(self.make(meta=meta))
        self.assertTrue(any("!= directory" in f for f in result["failures"]),
                        result["failures"])

    def test_preview_colours_must_be_hex(self):
        meta = dict(META, preview=dict(META["preview"], accent="orangered"))
        result = self.check(self.make(meta=meta))
        self.assertTrue(any("preview.accent" in f for f in result["failures"]),
                        result["failures"])


class TokenTests(ThemeFixture):
    def test_unresolved_var_is_a_failure(self):
        """The 23-theme defect: `--r-card: var(--r-sm)` with no `--r-sm`."""
        tokens = TOKENS.replace("  --r-sm:    8px;\n", "")
        result = self.check(self.make(tokens=tokens))
        self.assertTrue(
            any("var(--r-sm)" in f and "resolves to nothing" in f for f in result["failures"]),
            result["failures"])

    def test_a_fallback_value_is_not_a_failure(self):
        tokens = TOKENS.replace("--r-card:  var(--r-sm);", "--r-card:  var(--r-nope, 8px);")
        result = self.check(self.make(tokens=tokens))
        self.assertEqual(result["failures"], [])

    def test_a_required_token_must_be_defined(self):
        tokens = TOKENS.replace("  --rule: #2f2f2f;\n", "")
        result = self.check(self.make(tokens=tokens))
        self.assertTrue(any("--rule" in f for f in result["failures"]), result["failures"])

    def test_radius_scale_drift_is_a_failure(self):
        tokens = TOKENS.replace("--r-md:    16px;", "--r-md:    12px;")
        result = self.check(self.make(tokens=tokens))
        self.assertTrue(any("--r-md" in f and "shared scale" in f for f in result["failures"]),
                        result["failures"])

    def test_a_theme_that_fixes_rhythm_is_a_failure(self):
        tokens = TOKENS.replace("  --r-stage: 0;\n",
                                "  --r-stage: 0;\n  --dur-base: 700ms;\n  --ease-expo: linear;\n")
        result = self.check(self.make(tokens=tokens))
        self.assertTrue(any("--dur-base" in f and "mood" in f for f in result["failures"]),
                        result["failures"])

    def test_no_root_block_is_a_failure(self):
        result = self.check(self.make(tokens="body { color: red; }\n"))
        self.assertTrue(any("no :root block" in f for f in result["failures"]),
                        result["failures"])


class ContrastTests(ThemeFixture):
    def test_text_on_surface_below_4_5_is_a_failure(self):
        tokens = TOKENS.replace("--text: #f5f5f5;", "--text: #2a2a2a;")
        result = self.check(self.make(tokens=tokens))
        self.assertTrue(any("--text on --surface" in f for f in result["failures"]),
                        result["failures"])

    def test_text_mute_below_4_5_is_a_failure(self):
        """The doc asks for 4.5:1 on the tokens you read; six themes missed it."""
        tokens = TOKENS.replace("--text-mute: #9a9a9a;", "--text-mute: #3a3a3a;")
        result = self.check(self.make(tokens=tokens))
        self.assertTrue(any("--text-mute on --surface" in f for f in result["failures"]),
                        result["failures"])

    def test_text_faint_has_no_minimum_and_never_fails(self):
        tokens = TOKENS.replace("--text-faint: #6a6a6a;", "--text-faint: #2e2e2e;")
        result = self.check(self.make(tokens=tokens))
        self.assertEqual(result["failures"], [], "the hint tier must not fail the run")
        self.assertTrue(any("--text-faint" in n for n in result["notes"]), result["notes"])

    def test_the_faint_note_carries_a_measurement_not_a_threshold(self):
        result = self.check(self.make())
        note = next(n for n in result["notes"] if "--text-faint" in n)
        self.assertIn("no minimum", note)
        self.assertNotIn("need", note)
        self.assertNotRegex(note, r"<\s*[0-9]", note)

    def test_ratio_maths_matches_the_wcag_formula(self):
        self.assertAlmostEqual(themes.contrast_ratio("#ffffff", "#000000"), 21.0, places=3)
        self.assertAlmostEqual(themes.contrast_ratio("#000000", "#ffffff"), 21.0, places=3)
        self.assertAlmostEqual(themes.contrast_ratio("#767676", "#ffffff"), 4.54, places=1)
        self.assertIsNone(themes.contrast_ratio("rgba(0,0,0,.5)", "#ffffff"))


class RealLibraryTests(unittest.TestCase):
    """The shipped themes: no failures, and the radius scale is one scale."""

    def setUp(self) -> None:
        self.results, self.dirs = themes.check_all(THEMES)

    def test_there_are_themes_to_check(self):
        self.assertGreaterEqual(len(self.results), 20)

    def test_no_theme_fails(self):
        broken = {r["theme"]: r["failures"] for r in self.results if r["failures"]}
        self.assertEqual(broken, {})

    def test_every_theme_carries_the_same_radius_scale(self):
        for result in self.results:
            for token, expected in themes.RADIUS_SCALE.items():
                self.assertEqual(result["tokens"].get(token), expected,
                                 f"{result['theme']} {token}")

    def test_every_theme_states_the_documented_minimum_contrast(self):
        for result in self.results:
            surface = themes.resolve(result["tokens"], "--surface")
            for token, threshold in themes.ENFORCED_CONTRAST.items():
                ratio = themes.contrast_ratio(themes.resolve(result["tokens"], token), surface)
                self.assertIsNotNone(ratio, f"{result['theme']} {token}")
                self.assertGreaterEqual(ratio, threshold,
                                        f"{result['theme']} {token} is {ratio:.2f}:1")

    def test_the_hint_tier_is_measured_and_has_no_threshold_to_miss(self):
        """Every theme prints a `--text-faint` ratio, and none of them can fail it."""
        for result in self.results:
            note = next((n for n in result["notes"] if "--text-faint" in n), None)
            self.assertIsNotNone(note, f"{result['theme']} prints no faint measurement")
            self.assertIn("no minimum", note)
        self.assertNotIn("--text-faint", themes.ENFORCED_CONTRAST)

    def test_no_theme_carries_a_dead_rhythm_token(self):
        """`mood` is the only place the theme states rhythm — no ms, no easing."""
        for result in self.results:
            dead = [name for name in result["tokens"]
                    if name.startswith(themes.DEAD_RHYTHM_PREFIXES)]
            self.assertEqual(dead, [], f"{result['theme']} still defines {dead}")


if __name__ == "__main__":
    unittest.main()
