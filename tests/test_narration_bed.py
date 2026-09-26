"""The pictureless project: narration audio + a full-frame visual layer.

Until this existed, 「满屏画面 + 口播，没有素材」 had no path through render.py at
all — probe_stream_duration("v:0") came back empty and the extraction raised — so
that mode had to go through the visual skill's own renderer and its separate audio
handling. These tests pin the two pieces that replaced it:

1. a narration bed: an audio-only source produces a synthetic canvas carrying the
   cut narration, at the frame size and rate the EDL declares;
2. a copy fast path: when the visual layer IS the frame, its video stream is
   copied, not re-encoded. Bit-identical MD5 is the assertion, because "no
   re-encode" is the whole point and a decoder-level check would not prove it.
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

HELPERS = Path(__file__).parents[1] / "helpers"
sys.path.insert(0, str(HELPERS))

HAVE_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def _load_render():
    spec = importlib.util.spec_from_file_location("craft_render", HELPERS / "render.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def probe(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "stream=codec_type,width,height,r_frame_rate", "-of", "json", str(path)],
        capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def video_md5(path: Path) -> str:
    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:v", "-f", "md5", "-"],
        capture_output=True, text=True, check=True).stdout
    return out.strip()


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg/ffprobe not on PATH")
class NarrationBedTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.edit = self.root / "edit"
        self.edit.mkdir()
        self.vo = self.edit / "narration.m4a"
        run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
             "-i", "sine=frequency=440:duration=4", "-c:a", "aac", str(self.vo)])
        # A full-frame visual layer at 30fps, matching the declared frame.
        self.visual = self.edit / "visual.mp4"
        run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
             "-i", "color=c=0x1a2b3c:s=216x384:d=4", "-r", "30",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", str(self.visual)])
        # A shorter opaque layer for the partial-coverage case: the declared
        # duration must equal the file's real duration, so reusing the 4s file with
        # a 1.0s declaration is correctly refused by the overlay check.
        self.visual_short = self.edit / "visual_short.mp4"
        run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
             "-i", "color=c=0xcc3333:s=216x384:d=1", "-r", "30",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", str(self.visual_short)])
        # A one-word transcript: check_edl requires every source to be word-level.
        (self.edit / "transcripts").mkdir()
        (self.edit / "transcripts" / "VO.json").write_text(json.dumps({
            "text": "narration", "language": "en",
            "words": [{"text": "narration", "type": "word", "speaker": "S0",
                       "start": 0.5, "end": 2.5}],
        }), encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write_edl(self, **overrides) -> Path:
        edl = {
            "version": 1,
            "sources": {"VO": str(self.vo)},
            "ranges": [{"source": "VO", "start": 0.0, "end": 4.0, "beat": "ALL",
                        "quote": "narration", "reason": "整条口播"}],
            "grade": "none",
            "canvas": [216, 384],
            "fps": "30/1",
            "overlays": [{"file": "visual.mp4", "start_in_output": 0.0,
                          "duration": 4.0, "kind": "opaque"}],
            "total_duration_s": 4.0,
        }
        edl.update(overrides)
        path = self.edit / "edl.json"
        path.write_text(json.dumps(edl, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return path

    def render(self, edl_path: Path, out: Path) -> None:
        render = _load_render()
        subprocess.run(
            [sys.executable, str(HELPERS / "render.py"), str(edl_path),
             "-o", str(out), "--no-loudnorm"],
            check=True, capture_output=True,
            env={**__import__("os").environ, "PYTHONPATH": str(HELPERS)})

    # ---- the probe ----------------------------------------------------------
    def test_source_has_video_distinguishes_audio_from_footage(self):
        render = _load_render()
        self.assertFalse(render.source_has_video(self.vo))
        self.assertTrue(render.source_has_video(self.visual))

    # ---- the bed ------------------------------------------------------------
    def test_an_audio_only_source_produces_the_declared_canvas(self):
        edl = self.write_edl()
        out = self.root / "final.mp4"
        self.render(edl, out)
        info = probe(out)
        kinds = {s["codec_type"] for s in info["streams"]}
        self.assertEqual(kinds, {"video", "audio"},
                         "输出必须同时有音轨和画轨（画轨是合成的黑底）")
        video = next(s for s in info["streams"] if s["codec_type"] == "video")
        self.assertEqual((video["width"], video["height"]), (216, 384))
        self.assertEqual(video["r_frame_rate"], "30/1")

    def test_the_edl_frame_rate_beats_the_24_fallback(self):
        """The bed must not silently be 24fps when the visual layer is 30."""
        edl = self.write_edl()
        out = self.root / "final.mp4"
        self.render(edl, out)
        video = next(s for s in probe(out)["streams"] if s["codec_type"] == "video")
        self.assertNotEqual(video["r_frame_rate"], "24/1")

    def test_a_portrait_canvas_is_not_rotated_by_probing_audio(self):
        """Orientation cannot be probed from an audio file; the declared canvas wins."""
        edl = self.write_edl(canvas=[216, 384])
        out = self.root / "final.mp4"
        self.render(edl, out)
        video = next(s for s in probe(out)["streams"] if s["codec_type"] == "video")
        self.assertGreater(video["height"], video["width"])

    # ---- the copy fast path -------------------------------------------------
    def test_a_full_frame_opaque_layer_is_copied_not_re_encoded(self):
        edl = self.write_edl()
        out = self.root / "final.mp4"
        self.render(edl, out)
        self.assertEqual(
            video_md5(out), video_md5(self.visual),
            "满屏不透明覆盖层的视频流必须逐比特 copy；重编码会白掉一代画质")

    def test_a_short_opaque_layer_is_composited_instead(self):
        """A partial opaque layer is NOT the frame, so it must be composited."""
        edl = self.write_edl(overlays=[{
            "file": "visual_short.mp4", "start_in_output": 0.5, "duration": 1.0,
            "kind": "opaque"}])
        out = self.root / "final.mp4"
        self.render(edl, out)
        self.assertTrue(out.exists())
        self.assertNotEqual(video_md5(out), video_md5(self.visual_short),
                            "部分覆盖必须合成，不能整条 copy 覆盖层")


if __name__ == "__main__":
    unittest.main()
