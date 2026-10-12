#!/usr/bin/env python3
"""An HTML composition is the source; alpha videos are exports of it.

The old shape made the encoded file the source: you could not look at a layer
without rendering the film, and could not tune it without re-encoding. `render_layer`
renders one composition into BOTH carriers from a single pass:

  * `.mov` for the film composite (ffmpeg);
  * `.webm` (VP9 + alpha) because that is the only alpha carrier a browser composites,
    which is what lets the review page stack the layer itself.

Two properties matter enough to pin without a real render: a non-alpha container is
refused rather than silently shipped as an opaque layer, and an "alpha" export whose
plane came back flat is refused too.

The render itself needs npx + Chrome, so it is covered by the project run rather than
by this unit test.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HELPERS = Path(__file__).parents[1] / "helpers"
sys.path.insert(0, str(HELPERS))
sys.path.insert(0, str(Path(__file__).parents[1] / "visual" / "scripts"))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"craft_{name}", HELPERS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


render_layer = _load("render_layer")


class RenderLayerContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_a_directory_without_index_html_is_refused(self):
        with self.assertRaises(SystemExit) as ctx:
            render_layer.render(self.dir, self.dir / "out", check=False)
        self.assertIn("index.html", str(ctx.exception))

    def test_only_alpha_capable_formats_are_accepted(self):
        self.assertEqual(set(render_layer.FORMATS), {"mov", "webm"})
        (self.dir / "index.html").write_text("<html></html>", encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, str(HELPERS / "render_layer.py"), str(self.dir),
             "-o", str(self.dir / "out"), "--formats", "mp4"],
            capture_output=True, text=True)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("不支持的格式", proc.stdout + proc.stderr)

    def test_the_missing_npx_path_is_reported_not_guessed(self):
        (self.dir / "index.html").write_text("<html></html>", encoding="utf-8")
        original = render_layer.shutil.which
        render_layer.shutil.which = lambda _name: None
        try:
            with self.assertRaises(SystemExit) as ctx:
                render_layer.render(self.dir, self.dir / "out", check=False)
            self.assertIn("npx", str(ctx.exception))
        finally:
            render_layer.shutil.which = original


class ReviewMediaModeTests(unittest.TestCase):
    """A declared base switches the console to live layer compositing."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name)
        self.edit = self.project / "edit"
        (self.edit / "review").mkdir(parents=True)
        for name in ("base.mp4", "final.mp4"):
            (self.edit / name).write_bytes(b"x")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _resolve(self):
        build_review = _load("build_review")
        return build_review.resolve_review_media(
            self.project, self.edit, allow_review_copy=False)

    def test_no_base_means_layers_are_already_baked(self):
        media, _ = self._resolve()
        self.assertTrue(media["layersBaked"])
        self.assertEqual(media["compositeVideo"], "edit/final.mp4")

    def test_a_declared_base_switches_to_live_layers(self):
        (self.edit / "review" / "media.json").write_text(json.dumps({
            "baseVideo": "edit/base.mp4", "compositeVideo": None,
        }), encoding="utf-8")
        media, notes = self._resolve()
        self.assertEqual(media["compositeVideo"], "edit/base.mp4")
        self.assertFalse(media["layersBaked"])
        self.assertTrue(any("底片" in n for n in notes), notes)


if __name__ == "__main__":
    unittest.main()
