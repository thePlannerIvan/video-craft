#!/usr/bin/env python3
"""A layer is only previewable in a page if it has a browser-compositable twin.

Overlays ship as MOV (PNG-in-MOV / ProRes 4444) because that is what ffmpeg
composites. No browser can composite those alpha channels — Chrome cannot do it at
all — so before `preview_layers.py` existed the only way to see an overlay was to
bake it into the film.

`export_one` must therefore produce a WebM whose alpha SURVIVES (verified through
the plane, not through pix_fmt, which reports yuv420p even when alpha is present)
and must reuse an existing twin instead of re-encoding every build.
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

HELPERS = Path(__file__).parents[1] / "helpers"
sys.path.insert(0, str(HELPERS))
sys.path.insert(0, str(Path(__file__).parents[1] / "visual" / "scripts"))

FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def _load(name: str, folder: Path):
    spec = importlib.util.spec_from_file_location(f"craft_{name}", folder / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


preview_layers = _load("preview_layers", HELPERS)


@unittest.skipUnless(FFMPEG, "ffmpeg required")
class PreviewLayerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        png = self.dir / "plate.png"
        img = Image.new("RGBA", (64, 64), (255, 0, 0, 0))
        for x in range(16, 48):
            for y in range(16, 48):
                img.putpixel((x, y), (0, 128, 255, 255))
        img.save(png)
        self.mov = self.dir / "layer.mov"
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-loop", "1", "-i", str(png), "-t", "0.4",
             "-r", "10", "-c:v", "png", "-pix_fmt", "rgba", str(self.mov)], check=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_exports_a_webm_whose_alpha_survives(self):
        record = preview_layers.export_one(self.mov)
        self.assertEqual(record["action"], "made")
        webm = Path(record["webm"])
        self.assertTrue(webm.is_file())
        self.assertEqual(webm.suffix, ".webm")
        # The plane, not pix_fmt: VP9 advertises yuv420p while carrying alpha.
        from encode_transparent import _alpha_range
        lo, hi = _alpha_range(webm)
        self.assertGreater(hi - lo, 16, f"alpha did not survive: [{lo},{hi}]")

    def test_an_existing_twin_is_reused(self):
        first = preview_layers.export_one(self.mov)
        again = preview_layers.export_one(self.mov)
        self.assertEqual(again["action"], "cached")
        self.assertEqual(first["webm"], again["webm"])

    def test_force_re_encodes(self):
        preview_layers.export_one(self.mov)
        again = preview_layers.export_one(self.mov, force=True)
        self.assertEqual(again["action"], "made")

    def test_cli_reports_a_missing_overlay_instead_of_passing(self):
        (self.dir / "edl.json").write_text(json.dumps({
            "version": 1, "sources": {"A": str(self.dir / "A.mp4")},
            "ranges": [{"source": "A", "start": 0.0, "end": 1.0}],
            "overlays": [{"file": str(self.dir / "nope.mov"), "start_in_output": 0.0,
                          "duration": 1.0, "kind": "alpha"}],
        }), encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, str(HELPERS / "preview_layers.py"), str(self.dir)],
            capture_output=True, text=True)
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("缺文件", proc.stdout)


if __name__ == "__main__":
    unittest.main()
