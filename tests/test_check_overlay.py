"""The overlay interface contract, tested against real files.

Every test builds a tiny real video with ffmpeg rather than mocking the probe:
the failure this module exists for (a container that CLAIMS alpha but decodes
fully opaque) is invisible to a mock and to `pix_fmt` alone. Today's incident is
`test_baked_opaque_alpha_is_rejected` — a WebM 花字 layer on an ffmpeg without
libvpx alpha support.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import check_overlay as co

HAVE_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg/ffprobe not on PATH")
class OverlayContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # ---- fixtures -----------------------------------------------------------
    def _alpha_mov(self, name: str = "alpha.mov", *, opaque: bool = False,
                   seconds: str = "1", fps: int = 30, size: int = 64) -> Path:
        out = self.tmp / name
        colour = "red" if opaque else "red@0.35"
        run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
             "-i", f"color=c={colour}:s={size}x{size}:d={seconds},format=rgba",
             "-r", str(fps), "-c:v", "qtrle", "-pix_fmt", "rgba", str(out)])
        return out

    def _plain_mp4(self, name: str = "plain.mp4", *, seconds: str = "1",
                   fps: int = 30, size: int = 64) -> Path:
        out = self.tmp / name
        run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
             "-i", f"color=c=blue:s={size}x{size}:d={seconds}",
             "-r", str(fps), "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)])
        return out

    # ---- the contract holds -------------------------------------------------
    def test_a_real_alpha_layer_passes(self):
        hard, warn = co.verify_overlay(self._alpha_mov(), kind="alpha",
                                       declared_duration=1.0)
        self.assertEqual(hard, [], f"真实 alpha 层不该报硬问题: {hard}")

    def test_opaque_kind_on_an_opaque_file_passes(self):
        hard, _ = co.verify_overlay(self._plain_mp4(), kind="opaque",
                                    declared_duration=1.0)
        self.assertEqual(hard, [])

    # ---- the failure that motivated the module ------------------------------
    def test_baked_opaque_alpha_is_rejected(self):
        """Container claims alpha; the alpha plane is 255 everywhere.

        This is what a VP9/WebM overlay decodes to on ffmpeg builds without
        libvpx alpha support. Compositing it replaces the base with black.
        """
        path = self._alpha_mov("baked.mov", opaque=True)
        info = co.probe_video(path)
        self.assertTrue(co.pix_fmt_has_alpha(info["pix_fmt"]),
                        "fixture 必须真的带 alpha 通道，否则测的不是这个失败")
        hard, _ = co.verify_overlay(path, kind="alpha", declared_duration=1.0)
        self.assertTrue(any("不透明" in m or "透明信息" in m for m in hard),
                        f"应当拒绝被烘成不透明的 alpha 层，实际: {hard}")

    def test_no_alpha_plane_is_rejected(self):
        hard, _ = co.verify_overlay(self._plain_mp4(), kind="alpha",
                                    declared_duration=1.0)
        self.assertTrue(any("没有 alpha 通道" in m for m in hard),
                        f"应当拒绝没有 alpha 平面的文件，实际: {hard}")

    # ---- the other three ways an overlay can be wrong ------------------------
    def test_duration_drift_is_rejected(self):
        hard, _ = co.verify_overlay(self._alpha_mov(seconds="1"), kind="alpha",
                                    declared_duration=1.4)
        self.assertTrue(any("时长" in m for m in hard), hard)

    def test_duration_within_tolerance_passes(self):
        hard, _ = co.verify_overlay(self._alpha_mov(seconds="1"), kind="alpha",
                                    declared_duration=1.02)
        self.assertEqual([m for m in hard if "时长" in m], [])

    def test_rate_mismatch_is_rejected(self):
        hard, _ = co.verify_overlay(self._alpha_mov(fps=24), kind="alpha",
                                    declared_duration=1.0, expected_fps=30.0)
        self.assertTrue(any("帧率" in m for m in hard), hard)

    def test_size_mismatch_is_rejected(self):
        hard, _ = co.verify_overlay(self._alpha_mov(size=64), kind="alpha",
                                    declared_duration=1.0, expected_size=(1080, 1920))
        self.assertTrue(any("尺寸" in m for m in hard), hard)

    def test_rate_and_size_tolerate_what_matches(self):
        hard, _ = co.verify_overlay(self._alpha_mov(fps=30, size=64), kind="alpha",
                                    declared_duration=1.0, expected_fps=30.0,
                                    expected_size=(64, 64))
        self.assertEqual(hard, [])

    # ---- identity and edges -------------------------------------------------
    def test_missing_file_is_a_hard_problem_not_a_crash(self):
        hard, _ = co.verify_overlay(self.tmp / "nope.mov", kind="alpha")
        self.assertTrue(any("不存在" in m for m in hard), hard)

    def test_unknown_kind_is_rejected(self):
        hard, _ = co.verify_overlay(self._alpha_mov(), kind="translucent")
        self.assertTrue(any("kind" in m for m in hard), hard)

    def test_alpha_kind_is_the_default_so_the_loud_failure_wins(self):
        """An opaque file with no `kind` must be caught, not silently accepted."""
        hard, _ = co.verify_overlay(self._plain_mp4(), declared_duration=1.0)
        self.assertTrue(hard)

    def test_pix_fmt_classifier(self):
        for fmt in ("yuva420p", "yuva444p12le", "rgba", "bgra", "argb", "pal8"):
            with self.subTest(fmt=fmt):
                self.assertTrue(co.pix_fmt_has_alpha(fmt))
        for fmt in ("yuv420p", "yuv444p12le", "rgb24", None, ""):
            with self.subTest(fmt=fmt):
                self.assertFalse(co.pix_fmt_has_alpha(fmt))


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg/ffprobe not on PATH")
class RenderRefusesBadOverlayTests(unittest.TestCase):
    """The checker existing is not the contract — render.py must actually refuse.

    Without this wiring the check is advisory, and the failure mode (a six-minute
    render that ends in a black video) is exactly the one it was written for.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.base = self.tmp / "base.mp4"
        # The composite maps 0:a, so the base fixture needs a real audio track —
        # without it ffmpeg fails on "Stream map '0:a' matches no streams" and
        # the test would be measuring the fixture, not the guard.
        run(["ffmpeg", "-v", "error", "-y",
             "-f", "lavfi", "-i", "color=c=green:s=64x64:d=1",
             "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
             "-map", "0:v", "-map", "1:a", "-shortest", "-r", "30",
             "-c:v", "libx264", "-pix_fmt", "yuv420p",
             "-c:a", "aac", str(self.base)])
        self.good = self.tmp / "good.mov"
        run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
             "-i", "color=c=red@0.35:s=64x64:d=1,format=rgba", "-r", "30",
             "-c:v", "qtrle", "-pix_fmt", "rgba", str(self.good)])
        self.bad = self.tmp / "bad.mp4"
        run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
             "-i", "color=c=blue:s=64x64:d=1", "-r", "30",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", str(self.bad)])

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _import_render(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "craft_render", Path(__file__).parents[1] / "helpers" / "render.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_render_refuses_an_overlay_with_no_alpha(self):
        render = self._import_render()
        with self.assertRaises(SystemExit) as ctx:
            render.build_final_composite(
                self.base,
                [{"file": str(self.bad), "start_in_output": 0.0, "duration": 1.0,
                  "kind": "alpha"}],
                None, self.tmp / "out.mp4", self.tmp)
        self.assertIn("拒绝合成", str(ctx.exception))

    def test_render_accepts_a_real_alpha_overlay(self):
        render = self._import_render()
        out = self.tmp / "out_ok.mp4"
        render.build_final_composite(
            self.base,
            [{"file": str(self.good), "start_in_output": 0.0, "duration": 1.0,
              "kind": "alpha"}],
            None, out, self.tmp)
        self.assertTrue(out.exists() and out.stat().st_size > 0)

    def test_an_overlay_declared_opaque_is_not_forced_to_carry_alpha(self):
        render = self._import_render()
        out = self.tmp / "out_opaque.mp4"
        render.build_final_composite(
            self.base,
            [{"file": str(self.bad), "start_in_output": 0.0, "duration": 1.0,
              "kind": "opaque"}],
            None, out, self.tmp)
        self.assertTrue(out.exists() and out.stat().st_size > 0)
