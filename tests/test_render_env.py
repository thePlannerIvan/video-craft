"""The render environment, checked before the render instead of during it.

Measured failure: in a restricted sandbox `hyperframes render` stops with

    EPERM: operation not permitted, mkdir '~/.cache/hyperframes/fonts/noto-serif-sc'

The only suggestion it makes is `--docker` (needs Docker, absent here); the way
out is `HYPERFRAMES_FONT_CACHE_DIR`, which no help text lists and `hyperframes
doctor` does not check. `check_render_env.py` says so up front, and points at
`generate-composition.py` rather than `hyperframes init` when the composition is
missing — `init` would replace the generated one.
"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

HELPERS = Path(__file__).parents[1] / "helpers"


def load(name: str):
    spec = importlib.util.spec_from_file_location(f"video_craft_{name}", HELPERS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


env_check = load("check_render_env")


class RenderEnvTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.cache = self.root / "writable-cache"
        self.cache.mkdir()
        self.patch_node(22)

    def patch_node(self, major):
        original = env_check.node_major
        env_check.node_major = lambda: major
        self.addCleanup(setattr, env_check, "node_major", original)

    def run_check(self, env=None, composition=None):
        code, lines = env_check.check(composition, env or {"HOME": str(self.root),
                                                           env_check.FONT_CACHE_VAR: str(self.cache)})
        return code, "\n".join(lines)

    def test_a_writable_font_cache_passes_that_check(self):
        code, output = self.run_check()
        self.assertIn("font cache", output)
        self.assertNotIn("is not writable", output)

    def test_an_unwritable_font_cache_fails_and_names_the_variable(self):
        blocked = self.root / "a-file"
        blocked.write_text("not a directory", encoding="utf-8")
        env = {"HOME": str(self.root),
               env_check.FONT_CACHE_VAR: str(blocked / "fonts")}
        code, lines = env_check.check(None, env)
        output = "\n".join(lines)
        self.assertEqual(code, 1)
        self.assertIn("is not writable", output)
        self.assertIn(env_check.FONT_CACHE_VAR, output)
        self.assertIn("EPERM", output)
        self.assertIn("doctor", output, "the message must say doctor does not cover it")

    def test_the_default_cache_comes_from_home_when_the_variable_is_unset(self):
        env = {"HOME": str(self.root)}
        candidates = env_check.font_cache_candidates(env)
        self.assertEqual(candidates[0], self.root / ".cache" / "hyperframes")
        self.assertEqual(candidates[1], self.root / "Library" / "Caches" / "hyperframes")

    def test_node_below_the_minimum_fails(self):
        self.patch_node(18)
        code, output = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("below the required 22", output)

    def test_missing_node_fails(self):
        self.patch_node(None)
        code, output = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("not on PATH", output)

    def test_a_missing_composition_points_at_the_generator_not_at_init(self):
        code, output = self.run_check(composition=self.root / "composition")
        self.assertIn("generate-composition.py", output)
        self.assertIn("hyperframes init", output)
        self.assertIn("would replace it", output)

    def test_an_existing_composition_passes_that_check(self):
        composition = self.root / "composition"
        composition.mkdir()
        (composition / "index.html").write_text("<!doctype html>", encoding="utf-8")
        code, output = self.run_check(composition=composition)
        self.assertIn("composition:", output)
        self.assertNotIn("generate-composition.py", output)

    def test_the_reported_failure_is_reproducible_with_the_real_home(self):
        """The real default paths, untouched: this sandbox cannot write them."""
        ok, message = env_check.probe_writable(Path.home() / ".cache" / "hyperframes")
        if not ok:
            self.assertIn("not writable", message)


if __name__ == "__main__":
    unittest.main()
