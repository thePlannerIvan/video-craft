#!/usr/bin/env python3
"""Black-box CLI tests for v3 segment-spliced delivery, soundscape muxing, and empty pages/."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HELPERS = ROOT / "helpers"
INTERNAL = HELPERS / "_internal"
DELIVER_SCRIPT = HELPERS / "deliver.py"
VERIFY_SCRIPT = INTERNAL / "verify_delivery.py"

sys.path.insert(0, str(HELPERS))
sys.path.insert(0, str(INTERNAL))

import deliver  # noqa: E402
import verify_delivery  # noqa: E402
from _edl import edl_digest  # noqa: E402
from _timecode import parse_srt_file  # noqa: E402


def _have_media_tools() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def _make_color_video(path: Path, *, size: str, dur: float, color: str, fps: int = 30,
                      vf: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-v", "error", "-f", "lavfi",
        "-i", f"color=c={color}:s={size}:r={fps}:d={dur:.3f}",
    ]
    if vf:
        cmd += ["-vf", vf]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)]
    subprocess.run(cmd, check=True)


def _make_person_video(path: Path, *, size: str = "720x1280", dur: float = 4.0, fps: int = 30) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-f", "lavfi",
        "-i", f"testsrc2=s={size}:r={fps}:d={dur:.3f}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
    ], check=True)


def _make_tone_audio(path: Path, *, dur: float, freq: int = 440, codec: str = "aac") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-v", "error", "-f", "lavfi",
        "-i", f"sine=frequency={freq}:duration={dur:.3f}",
        "-ar", "48000", "-ac", "2",
    ]
    if codec == "pcm_s16le":
        cmd += ["-c:a", "pcm_s16le"]
    else:
        cmd += ["-c:a", "aac", "-b:a", "192k"]
    cmd.append(str(path))
    subprocess.run(cmd, check=True)


def _seed_edl(project: Path, dur: float) -> None:
    edit = project / "edit"
    edit.mkdir(parents=True, exist_ok=True)
    edl = edit / "edl.json"
    edl.write_text(json.dumps({"ranges": [{"start": 0, "end": dur}]}), encoding="utf-8")
    (edit / "segment_durations.json").write_text(json.dumps({
        "final": {"durations": [dur], "total_s": dur, "edl_sha256": edl_digest(edl)},
    }), encoding="utf-8")


def _run_deliver(project: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ, DSH_TEST="1")
    return subprocess.run(
        [sys.executable, str(DELIVER_SCRIPT), str(project), "--skip-gate", "--json", *extra],
        env=env, capture_output=True, text=True, check=False,
    )


@unittest.skipUnless(_have_media_tools(), "需要 ffmpeg/ffprobe")
class SegmentSplicedDeliveryTests(unittest.TestCase):
    def test_horizontal_storyboard_splices_ffmpeg_cut_and_hyperframes_segments(self) -> None:
        """16:9 storyboard mixes talk-only, footage, hyperframes motion, and screen-demo."""
        with tempfile.TemporaryDirectory() as td:
            proj = (Path(td) / "horiz_mix").resolve()
            (proj / "edit").mkdir(parents=True)
            (proj / "material").mkdir(parents=True)
            (proj / "recordings").mkdir(parents=True)
            (proj / "composition" / "_render").mkdir(parents=True)

            # Person (4.0s) & Voice Polish (4.0s)
            _make_person_video(proj / "edit" / "cut.mp4", size="720x1280", dur=4.0)
            _make_tone_audio(proj / "edit" / "_engineering" / "review_audio.m4a", dur=4.0, freq=330)
            _seed_edl(proj, 4.0)

            # Frame geometry: 1920x1080 landscape
            (proj / "frame.json").write_text(json.dumps({
                "canvas": {"w": 1920, "h": 1080, "fps": 30},
                "personSlot": {"x": 0, "y": 0, "w": 520, "h": 1080},
                "captionSafe": {"x": 0, "y": 880, "w": 1920, "h": 200},
            }), encoding="utf-8")

            # HD sources:
            # V01 footage (coral/orange bright) 3s -> slice 1.0..2.0 into timeline [0.8..1.8]
            _make_color_video(proj / "material" / "ad_clip.mp4", size="1920x1080", dur=3.0, color="0xFF7A33")
            # D01 screen-demo (cyan) 2s -> slice 0.2..1.2 into timeline [2.8..3.8]
            _make_color_video(
                proj / "recordings" / "app_demo.mp4", size="1920x1080", dur=2.0, color="0x38BDF8",
                vf="drawbox=x=100:y=100:w=400:h=80:color=0x0F172A@1:t=fill",
            )
            # Pre-rendered HyperFrames visuals.mp4 covering 4.0s (bone cream box in stage during [1.8..2.8])
            _make_color_video(
                proj / "composition" / "_render" / "visuals.mp4",
                size="1920x1080", dur=4.0, color="0x11131A",
                vf="drawbox=x=600:y=120:w=1100:h=600:color=0xF5EFE6@1:t=fill:enable='between(t,1.8,2.8)'",
            )

            storyboard = {
                "version": "storyboard/3",
                "canvas": {"width": 1920, "height": 1080, "fps": 30},
                "capabilities": ["footage", "motion", "screen-demo"],
                "shots": [
                    {"id": "T01", "kind": "talk-only", "engine": "ffmpeg-cut", "startSec": 0.0, "endSec": 0.8},
                    {
                        "id": "V01", "kind": "footage", "engine": "ffmpeg-cut",
                        "startSec": 0.8, "endSec": 1.8,
                        "clip": "material/ad_clip.mp4", "clipIn": 1.0, "clipOut": 2.0,
                    },
                    {
                        "id": "M01", "kind": "motion", "engine": "hyperframes",
                        "startSec": 1.8, "endSec": 2.8,
                    },
                    {
                        "id": "D01", "kind": "screen-demo", "engine": "ffmpeg-cut",
                        "startSec": 2.8, "endSec": 3.8,
                        "demo": {"source": "recordings/app_demo.mp4", "inSec": 0.2, "outSec": 1.2},
                    },
                    {"id": "T02", "kind": "talk-only", "engine": "ffmpeg-cut", "startSec": 3.8, "endSec": 4.0},
                ],
            }
            (proj / "edit" / "storyboard.json").write_text(json.dumps(storyboard, ensure_ascii=False), encoding="utf-8")
            subprocess.run([sys.executable, str(HELPERS / "film.py"), "lookdev", str(proj), "--approve"], check=True)
            deliver._record_visual_source(proj, proj / "composition" / "_render" / "visuals.mp4", "manual-confirmation")

            proc = _run_deliver(proj)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            report = json.loads((proj / "成品" / f"{proj.name}_核验报告.json").read_text(encoding="utf-8"))
            self.assertTrue(report["ok"], report)
            self.assertIn("segment_splice", report)
            self.assertTrue(report["segment_splice"]["screen_text_protection"])
            self.assertEqual(report["segment_splice"]["engine_counts"], {"ffmpeg-cut": 4, "hyperframes": 1})

            visual_out = proj / "成品" / f"{proj.name}_画面成片.mp4"
            vv, va = deliver._streams(visual_out)
            self.assertEqual((vv.get("width"), vv.get("height")), (1920, 1080))
            self.assertAlmostEqual(deliver._parse_fps(vv), 30.0, delta=0.05)
            self.assertEqual(va, {})
            self.assertAlmostEqual(deliver._duration(visual_out), 4.0, delta=0.1)
            self.assertEqual(verify_delivery.black_spans(visual_out), [])

            # Check each segment window inside stage (x=700..1500, y=200..600):
            # 0.4s (talk-only backdrop #11131A) < 40; 1.3s (orange footage) > 100; 2.3s (bone motion) > 180; 3.3s (cyan demo) > 100
            luma_t01 = deliver._frame_luma(visual_out, 0.4, (400, 300, 800, 250))
            luma_v01 = deliver._frame_luma(visual_out, 1.3, (400, 300, 800, 250))
            luma_m01 = deliver._frame_luma(visual_out, 2.3, (400, 300, 800, 250))
            luma_d01 = deliver._frame_luma(visual_out, 3.3, (400, 300, 800, 250))
            self.assertLess(luma_t01, 40.0)
            self.assertGreater(luma_v01, 100.0)
            self.assertGreater(luma_m01, 180.0)
            self.assertGreater(luma_d01, 100.0)

    def test_vertical_9_16_storyboard_with_per_shot_motion_render(self) -> None:
        """9:16 storyboard (no recompose.json) splices video + card-deck + screen-demo to 1080x1920."""
        with tempfile.TemporaryDirectory() as td:
            proj = (Path(td) / "vert_mix").resolve()
            (proj / "edit").mkdir(parents=True)
            (proj / "material").mkdir(parents=True)
            (proj / "recordings").mkdir(parents=True)
            (proj / "composition" / "_render").mkdir(parents=True)

            _make_person_video(proj / "edit" / "cut.mp4", size="1080x1920", dur=3.0)
            _make_tone_audio(proj / "edit" / "_engineering" / "review_audio.m4a", dur=3.0, freq=330)
            _seed_edl(proj, 3.0)

            _make_color_video(proj / "material" / "broll.mp4", size="1920x1080", dur=2.0, color="0xF59E0B")
            _make_color_video(
                proj / "composition" / "_render" / "X01.mp4", size="1080x1920", dur=1.0, color="0x11131A",
                vf="drawbox=x=100:y=360:w=880:h=960:color=0xE2E8F0@1:t=fill",
            )
            _make_color_video(proj / "recordings" / "mobile.mp4", size="1080x1920", dur=2.0, color="0x60A5FA")

            storyboard = {
                "version": "storyboard/3",
                "canvas": {"width": 1080, "height": 1920, "fps": 30},
                "framePreset": "vertical-zine-head",
                "capabilities": ["footage", "motion", "screen-demo"],
                "shots": [
                    {
                        "id": "V01", "kind": "video", "engine": "ffmpeg-cut",
                        "startSec": 0.0, "endSec": 1.0,
                        "clip": "material/broll.mp4", "clipIn": 0.5, "clipOut": 1.5,
                    },
                    {
                        "id": "X01", "kind": "card-deck", "engine": "hyperframes",
                        "startSec": 1.0, "endSec": 2.0,
                        "renderedClip": "composition/_render/X01.mp4",
                    },
                    {
                        "id": "D01", "kind": "screen-demo", "engine": "ffmpeg-cut",
                        "startSec": 2.0, "endSec": 3.0,
                        "demo": {"source": "recordings/mobile.mp4", "inSec": 0.2, "outSec": 1.2},
                    },
                ],
            }
            (proj / "storyboard.json").write_text(json.dumps(storyboard, ensure_ascii=False), encoding="utf-8")
            subprocess.run([sys.executable, str(HELPERS / "film.py"), "lookdev", str(proj), "--approve"], check=True)

            proc = _run_deliver(proj)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            report = json.loads((proj / "成品" / f"{proj.name}_核验报告.json").read_text(encoding="utf-8"))
            self.assertTrue(report["ok"], report)
            self.assertEqual((report["geometry"]["width"], report["geometry"]["height"]), (1080, 1920))

            visual_out = proj / "成品" / f"{proj.name}_画面成片.mp4"
            vv, va = deliver._streams(visual_out)
            self.assertEqual((vv.get("width"), vv.get("height")), (1080, 1920))
            self.assertAlmostEqual(deliver._parse_fps(vv), 30.0, delta=0.05)
            self.assertAlmostEqual(deliver._duration(visual_out), 3.0, delta=0.1)
            self.assertEqual(va, {})
            self.assertEqual(verify_delivery.black_spans(visual_out), [])

    def test_visual_audio_flag_muxes_losslessly_and_coexports_wav_while_keeping_person_clean(self) -> None:
        """--visual-audio muxes soundscape into 画面成片.mp4 (-c:v copy) & exports 画面音效轨.wav."""
        with tempfile.TemporaryDirectory() as td:
            proj = (Path(td) / "sfx_split").resolve()
            (proj / "edit").mkdir(parents=True)
            (proj / "material").mkdir(parents=True)
            (proj / "composition" / "_render").mkdir(parents=True)

            _make_person_video(proj / "edit" / "cut.mp4", size="720x1280", dur=2.0)
            _make_tone_audio(proj / "edit" / "_engineering" / "review_audio.m4a", dur=2.0, freq=260)
            soundscape_src = proj / "custom_soundscape.wav"
            _make_tone_audio(soundscape_src, dur=2.0, freq=880, codec="pcm_s16le")
            _seed_edl(proj, 2.0)

            raw_srt = (
                "1\n00:00:00,000 --> 00:00:00,800\n第一句字幕\n\n"
                "2\n00:00:00,800 --> 00:00:01,900\n第二句字幕\n\n"
            )
            (proj / "edit" / "subtitles.srt").write_text(raw_srt, encoding="utf-8")

            _make_color_video(proj / "material" / "clip.mp4", size="1920x1080", dur=3.0, color="0xF2EBDD")
            (proj / "frame.json").write_text(json.dumps({
                "canvas": {"w": 1920, "h": 1080, "fps": 30},
                "personSlot": {"x": 0, "y": 0, "w": 500, "h": 1080},
                "captionSafe": {"x": 0, "y": 880, "w": 1920, "h": 200},
            }), encoding="utf-8")
            (proj / "storyboard.json").write_text(json.dumps({
                "version": "storyboard/3",
                "canvas": {"width": 1920, "height": 1080, "fps": 30},
                "shots": [{
                    "id": "V01", "kind": "footage", "engine": "ffmpeg-cut",
                    "startSec": 0.0, "endSec": 2.0,
                    "clip": "material/clip.mp4", "clipIn": 0.2, "clipOut": 2.2,
                }],
            }), encoding="utf-8")

            proc = _run_deliver(proj, "--visual-audio", str(soundscape_src))
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            report = json.loads((proj / "成品" / f"{proj.name}_核验报告.json").read_text(encoding="utf-8"))
            self.assertTrue(report["ok"], report)
            self.assertTrue(report["delivery_ok"], report)

            visual_out = proj / "成品" / f"{proj.name}_画面成片.mp4"
            person_out = proj / "成品" / f"{proj.name}_人物成片.mp4"
            wav_out = proj / "成品" / f"{proj.name}_画面音效轨.wav"
            srt_out = proj / "成品" / f"{proj.name}_字幕.srt"

            self.assertTrue(visual_out.is_file())
            self.assertTrue(person_out.is_file())
            self.assertTrue(wav_out.is_file())
            self.assertTrue(srt_out.is_file())
            self.assertEqual(wav_out.read_bytes(), soundscape_src.read_bytes())
            self.assertEqual(report["deliverables"].get("visual_audio"), str(wav_out))

            vv, va = deliver._streams(visual_out)
            self.assertEqual((vv.get("width"), vv.get("height")), (1920, 1080))
            self.assertEqual(va.get("codec_name"), "aac")
            self.assertEqual(va.get("channels"), 2)
            self.assertEqual(int(float(va.get("sample_rate") or 0)), 48000)

            pv, pa = deliver._streams(person_out)
            self.assertEqual(pa.get("codec_name"), "aac")
            self.assertEqual(pa.get("channels"), 2)
            # Person audio & visual soundscape audio are distinct tracks
            self.assertNotEqual(
                verify_delivery.audio_fingerprint(person_out),
                verify_delivery.audio_fingerprint(visual_out),
            )

            # Delivered SRT has >= 30ms inter-cue gaps while edit/subtitles.srt stays untouched
            self.assertEqual((proj / "edit" / "subtitles.srt").read_text(encoding="utf-8"), raw_srt)
            cues = parse_srt_file(srt_out)
            self.assertEqual(len(cues), 2)
            self.assertGreaterEqual(cues[1]["startMs"] - cues[0]["endMs"], 30)

            # verify_delivery --deliver-dir must pass cleanly with soundscape-muxed 画面成片.mp4
            vd = subprocess.run(
                [sys.executable, str(VERIFY_SCRIPT), str(proj / "edit"),
                 "--video", str(person_out), "--deliver-dir", str(proj / "成品"), "--json"],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(vd.returncode, 0, vd.stdout + vd.stderr)
            vd_json = vd.stdout[vd.stdout.index("{"):]
            self.assertTrue(json.loads(vd_json)["ok"], vd.stdout)

    def test_autodetects_default_soundscape_wav_and_uses_lossless_video_copy(self) -> None:
        """Auto-detects edit/_engineering/soundscape.wav and preserves exact video packets (-c:v copy)."""
        with tempfile.TemporaryDirectory() as td:
            proj = (Path(td) / "auto_sfx").resolve()
            (proj / "edit" / "_engineering").mkdir(parents=True)
            (proj / "composition" / "_render").mkdir(parents=True)
            (proj / "composition" / "assets").mkdir(parents=True)

            vis_src = proj / "composition" / "_render" / "visuals.mp4"
            _make_color_video(
                vis_src, size="1920x1080", dur=1.5, color="0x050607",
                vf="drawbox=x=700:y=200:w=1000:h=500:color=0xF2EBDD@1:t=fill",
            )
            _make_person_video(proj / "edit" / "cut.mp4", size="720x1280", dur=1.5)
            _make_tone_audio(proj / "composition" / "assets" / "audio.m4a", dur=1.5, freq=220)
            sd_wav = proj / "edit" / "_engineering" / "soundscape.wav"
            _make_tone_audio(sd_wav, dur=1.5, freq=660, codec="pcm_s16le")
            _seed_edl(proj, 1.5)
            (proj / "recompose.json").write_text(json.dumps({
                "canvas": {"w": 1920, "h": 1080, "fps": 30},
                "personSlot": {"x": 0, "y": 0, "w": 500, "h": 1080},
                "captionSafe": {"x": 0, "y": 880, "w": 1920, "h": 200},
            }), encoding="utf-8")
            deliver._record_visual_source(proj, vis_src, "manual-confirmation")

            proc = _run_deliver(proj)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            visual_out = proj / "成品" / f"{proj.name}_画面成片.mp4"
            wav_out = proj / "成品" / f"{proj.name}_画面音效轨.wav"
            self.assertTrue(wav_out.is_file())
            with wave.open(str(wav_out), "rb") as wf:
                self.assertEqual((wf.getnchannels(), wf.getframerate()), (2, 48000))

            # Verify -c:v copy: decoded frame MD5s & packet stream hash match input visuals.mp4
            def _vstream_md5(p: Path) -> str:
                return subprocess.run(
                    ["ffmpeg", "-v", "error", "-i", str(p), "-map", "0:v:0", "-c:v", "copy", "-f", "streamhash", "-"],
                    capture_output=True, text=True, check=True,
                ).stdout.strip()

            self.assertEqual(_vstream_md5(visual_out), _vstream_md5(vis_src))

    def test_silent_split_delivery_without_soundscape_stays_zero_audio(self) -> None:
        """Without --visual-audio or soundscape.wav, 画面成片.mp4 keeps 0 audio streams."""
        with tempfile.TemporaryDirectory() as td:
            proj = (Path(td) / "silent_split").resolve()
            (proj / "edit").mkdir(parents=True)
            (proj / "material").mkdir(parents=True)
            _make_person_video(proj / "edit" / "cut.mp4", size="720x1280", dur=1.5)
            _make_tone_audio(proj / "edit" / "_engineering" / "review_audio.m4a", dur=1.5)
            _make_color_video(proj / "material" / "clip.mp4", size="1920x1080", dur=2.0, color="0xF2EBDD")
            _seed_edl(proj, 1.5)
            (proj / "frame.json").write_text(json.dumps({
                "canvas": {"w": 1920, "h": 1080, "fps": 30},
                "personSlot": {"x": 0, "y": 0, "w": 500, "h": 1080},
                "captionSafe": {"x": 0, "y": 880, "w": 1920, "h": 200},
            }), encoding="utf-8")
            (proj / "storyboard.json").write_text(json.dumps({
                "version": "storyboard/3",
                "canvas": {"width": 1920, "height": 1080, "fps": 30},
                "shots": [{
                    "id": "V01", "kind": "footage", "engine": "ffmpeg-cut",
                    "startSec": 0.0, "endSec": 1.5,
                    "clip": "material/clip.mp4", "clipIn": 0.0, "clipOut": 1.5,
                }],
            }), encoding="utf-8")

            proc = _run_deliver(proj)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            visual_out = proj / "成品" / f"{proj.name}_画面成片.mp4"
            self.assertEqual(deliver._streams(visual_out)[1], {})
            self.assertFalse((proj / "成品" / f"{proj.name}_画面音效轨.wav").exists())

    def test_empty_pages_placeholder_dir_does_not_trigger_legacy_page_failure(self) -> None:
        """An empty pages/ directory (0 .md/.svg/.json files) must NOT fail 原页拆解 in deliver.py."""
        with tempfile.TemporaryDirectory() as td:
            proj = (Path(td) / "empty_pages").resolve()
            (proj / "edit").mkdir(parents=True)
            (proj / "pages").mkdir(parents=True)
            # Optional non-page placeholder file like .gitkeep still counts as 0 page files
            (proj / "pages" / ".gitkeep").write_text("", encoding="utf-8")
            (proj / "composition" / "_render").mkdir(parents=True)
            (proj / "composition" / "assets").mkdir(parents=True)

            # Minimal valid composition/index.html (no hyperframes.json needed)
            (proj / "composition" / "index.html").write_text(
                "<!doctype html><html><body>"
                "<div id='root' data-composition-id='main' data-start='0' data-width='1920' data-height='1080' data-duration='1.5'>"
                "<div style='width:100px;height:100px;font-size:40px'>Hi</div></div>"
                "<script>window.__timelines = window.__timelines || {}; window.__timelines['main'] = { seek: function(){} };</script>"
                "</body></html>",
                encoding="utf-8",
            )
            (proj / "recompose").mkdir(parents=True, exist_ok=True)
            (proj / "recompose" / "lines.json").write_text(
                json.dumps({"beats": [{"id": "b1", "title": "Opening"}]}), encoding="utf-8"
            )
            vis = proj / "composition" / "_render" / "visuals.mp4"
            _make_color_video(
                vis, size="1920x1080", dur=1.5, color="0x050607",
                vf="drawbox=x=700:y=200:w=1000:h=500:color=0xF2EBDD@1:t=fill",
            )
            _make_person_video(proj / "edit" / "cut.mp4", size="720x1280", dur=1.5)
            _make_tone_audio(proj / "composition" / "assets" / "audio.m4a", dur=1.5)
            (proj / "recompose.json").write_text(json.dumps({
                "canvas": {"w": 1920, "h": 1080, "fps": 30},
                "personSlot": {"x": 0, "y": 0, "w": 500, "h": 1080},
                "captionSafe": {"x": 0, "y": 880, "w": 1920, "h": 200},
            }), encoding="utf-8")
            _seed_edl(proj, 1.5)
            deliver._record_visual_source(proj, vis, "manual-confirmation")

            proc = _run_deliver(proj)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            report = json.loads((proj / "成品" / f"{proj.name}_核验报告.json").read_text(encoding="utf-8"))
            self.assertTrue(report["ok"], report)
            check_names = [c["name"] for c in report["checks"]]
            self.assertNotIn("原页拆解", check_names)


@unittest.skipUnless(_have_media_tools(), "需要 ffmpeg/ffprobe")
class ReviewFixesIntegrationTests(unittest.TestCase):
    def test_preflight_enforces_lookdev_verify_and_visual_quality_without_composition(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            proj = (Path(td) / "preflight_sb").resolve()
            (proj / "edit").mkdir(parents=True)
            (proj / "recordings").mkdir(parents=True)
            (proj / "composition" / "_render").mkdir(parents=True)
            _make_person_video(proj / "edit" / "cut.mp4", size="720x1280", dur=2.0)
            _make_tone_audio(proj / "edit" / "_engineering" / "review_audio.m4a", dur=2.0, freq=280)
            _make_color_video(proj / "recordings" / "app.mp4", size="1920x1080", dur=2.0, color="0x38BDF8")
            _make_color_video(
                proj / "composition" / "_render" / "visuals.mp4", size="1920x1080", dur=2.0, color="0x11131A",
                vf="drawbox=x=600:y=120:w=1100:h=600:color=0xF5EFE6@1:t=fill",
            )
            _seed_edl(proj, 2.0)
            (proj / "frame.json").write_text(json.dumps({
                "canvas": {"w": 1920, "h": 1080, "fps": 30},
                "personSlot": {"x": 0, "y": 0, "w": 520, "h": 1080},
                "captionSafe": {"x": 0, "y": 880, "w": 1920, "h": 200},
            }), encoding="utf-8")

            # 1) Unapproved motion storyboard -> preflight fails Look-Dev gate
            sb_path = proj / "storyboard.json"
            sb_path.write_text(json.dumps({
                "version": "storyboard/3",
                "canvas": {"width": 1920, "height": 1080, "fps": 30},
                "capabilities": ["motion", "screen-demo"],
                "shots": [
                    {"id": "M01", "kind": "model", "engine": "hyperframes", "startSec": 0.0, "endSec": 1.0},
                    {"id": "D01", "kind": "screen-demo", "engine": "ffmpeg-cut", "startSec": 1.0, "endSec": 2.0,
                     "demo": {"source": "recordings/app.mp4", "inSec": 0.2, "outSec": 5.0}},
                ],
            }), encoding="utf-8")
            unapproved = _run_deliver(proj)
            self.assertNotEqual(unapproved.returncode, 0)
            rep1 = json.loads((proj / "成品" / f"{proj.name}_核验报告.json").read_text(encoding="utf-8"))
            self.assertTrue(any(c["name"] == "Look-Dev 样镜定调" and not c["ok"] for c in rep1["checks"]), rep1["checks"])

            # 2) Approve Look-Dev -> still blocked by check_visual_quality DEMO_RANGE when has_comp is False
            subprocess.run([sys.executable, str(HELPERS / "film.py"), "lookdev", str(proj), "--approve"], check=True)
            bad_demo = _run_deliver(proj)
            self.assertNotEqual(bad_demo.returncode, 0)
            rep2 = json.loads((proj / "成品" / f"{proj.name}_核验报告.json").read_text(encoding="utf-8"))
            self.assertTrue(any(c["name"] == "构建期画面体检" and not c["ok"] for c in rep2["checks"]), rep2["checks"])

            # 3) Fix demo outSec & record visual source -> passes preflight & delivers + state_fingerprint tracks storyboard/lookdev
            sb_path.write_text(json.dumps({
                "version": "storyboard/3",
                "canvas": {"width": 1920, "height": 1080, "fps": 30},
                "capabilities": ["motion", "screen-demo"],
                "shots": [
                    {"id": "M01", "kind": "model", "engine": "hyperframes", "startSec": 0.0, "endSec": 1.0},
                    {"id": "D01", "kind": "screen-demo", "engine": "ffmpeg-cut", "startSec": 1.0, "endSec": 2.0,
                     "demo": {"source": "recordings/app.mp4", "inSec": 0.2, "outSec": 1.2}},
                ],
            }), encoding="utf-8")
            deliver._record_visual_source(proj, proj / "composition" / "_render" / "visuals.mp4", "manual-confirmation")
            ok_run = _run_deliver(proj)
            self.assertEqual(ok_run.returncode, 0, ok_run.stdout + ok_run.stderr)

            from state_fingerprint import capture, compare
            snap1 = capture(proj)
            self.assertIn("storyboard.json", snap1["sources"])
            self.assertNotIn("lookdev/lookdev-manifest.json", snap1["sources"])
            sb_path.write_text(sb_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            diffs = compare(snap1, capture(proj))
            self.assertTrue(any("storyboard.json" in d for d in diffs), diffs)

    def test_v3_empty_capabilities_project_yaml_triggers_pure_talking_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            proj = (Path(td) / "v3_base_only").resolve()
            (proj / "edit" / "_engineering").mkdir(parents=True)
            (proj / "project.yaml").write_text(
                "slug: v3_base_only\ncolumn: 品牌判断\nstyle: default-clean\ncapabilities: []\nframe: vertical-zine-head\n",
                encoding="utf-8",
            )
            _make_person_video(proj / "edit" / "cut.mp4", size="720x1280", dur=1.5)
            _make_tone_audio(proj / "edit" / "_engineering" / "review_audio.m4a", dur=1.5)
            _seed_edl(proj, 1.5)

            proc = _run_deliver(proj)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            report = json.loads((proj / "成品" / f"{proj.name}_核验报告.json").read_text(encoding="utf-8"))
            self.assertEqual(report["delivery_mode"], "pure-talking")
            self.assertTrue((proj / "成品" / f"{proj.name}_人物成片.mp4").is_file())
            self.assertFalse((proj / "成品" / f"{proj.name}_画面成片.mp4").exists())

    def test_composite_and_no_person_mix_visual_audio_and_srt_import_split_verifies(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for mode_name, extra_args in (("composite", ["--composite"]), ("no_person", ["--no-person"])):
                proj = (root / mode_name).resolve()
                (proj / "edit" / "_engineering").mkdir(parents=True)
                (proj / "material").mkdir(parents=True)
                _make_person_video(proj / "edit" / "cut.mp4", size="720x1280", dur=2.0)
                voice_wav = proj / "edit" / "_engineering" / "review_audio.m4a"
                _make_tone_audio(voice_wav, dur=2.0, freq=260, codec="aac")
                snd_wav = proj / "custom_soundscape.wav"
                _make_tone_audio(snd_wav, dur=2.0, freq=880, codec="pcm_s16le")
                _make_color_video(proj / "material" / "clip.mp4", size="1920x1080", dur=3.0, color="0xF2EBDD")
                _seed_edl(proj, 2.0)
                (proj / "frame.json").write_text(json.dumps({
                    "canvas": {"w": 1920, "h": 1080, "fps": 30},
                    "personSlot": {"x": 0, "y": 0, "w": 500, "h": 1080},
                    "captionSafe": {"x": 0, "y": 880, "w": 1920, "h": 200},
                }), encoding="utf-8")
                (proj / "storyboard.json").write_text(json.dumps({
                    "version": "storyboard/3",
                    "canvas": {"width": 1920, "height": 1080, "fps": 30},
                    "shots": [
                        {"id": "V01", "kind": "footage", "engine": "ffmpeg-cut",
                         "startSec": 0.0, "endSec": 2.0, "clip": "material/clip.mp4", "clipIn": 0.0, "clipOut": 2.0},
                    ],
                }), encoding="utf-8")

                # Baseline without soundscape
                base_out = proj / "out_voice_only"
                proc_base = _run_deliver(proj, "--out", str(base_out), *extra_args)
                self.assertEqual(proc_base.returncode, 0, proc_base.stdout + proc_base.stderr)
                base_mp4 = base_out / f"{proj.name}_成片.mp4"

                # With --visual-audio soundscape
                mix_out = proj / "成品"
                proc_mix = _run_deliver(proj, "--out", str(mix_out), "--visual-audio", str(snd_wav), *extra_args)
                self.assertEqual(proc_mix.returncode, 0, proc_mix.stdout + proc_mix.stderr)
                mix_mp4 = mix_out / f"{proj.name}_成片.mp4"
                self.assertNotEqual(
                    verify_delivery.audio_fingerprint(base_mp4),
                    verify_delivery.audio_fingerprint(mix_mp4),
                )

            # srt-import + split delivery -> verify_delivery --deliver-dir passes cleanly
            import import_srt_timeline as imp
            srt_proj = (root / "srt_split").resolve()
            (srt_proj / "edit" / "_engineering").mkdir(parents=True)
            (srt_proj / "material").mkdir(parents=True)
            (srt_proj / "timeline").mkdir(parents=True)
            _make_person_video(srt_proj / "edit" / "cut.mp4", size="720x1280", dur=2.0)
            media_wav = srt_proj / "edit" / "_engineering" / "review_audio.wav"
            _make_tone_audio(media_wav, dur=2.0, freq=280, codec="pcm_s16le")
            _make_color_video(srt_proj / "material" / "clip.mp4", size="1920x1080", dur=3.0, color="0xF2EBDD")
            srt_file = srt_proj / "edit" / "subtitles.srt"
            srt_file.write_text("1\n00:00:00,000 --> 00:00:01,800\n外挂字幕测试\n\n", encoding="utf-8")
            script_md = srt_proj / "script.md"
            script_md.write_text("外挂字幕测试", encoding="utf-8")
            import hashlib
            sb_path = srt_proj / "storyboard.json"
            sb_path.write_text(json.dumps({
                "version": "storyboard/3",
                "script_hash": hashlib.sha256(script_md.read_bytes()).hexdigest(),
                "canvas": {"width": 1920, "height": 1080, "fps": 30},
                "shots": [
                    {"id": "V01", "kind": "footage", "engine": "ffmpeg-cut",
                     "startSec": 0.0, "endSec": 2.0, "clip": "material/clip.mp4", "clipIn": 0.0, "clipOut": 2.0},
                ],
            }), encoding="utf-8")
            align_path = srt_proj / "alignment.json"
            align_path.write_text(json.dumps({
                "sourcePlan": str(sb_path),
                "sourceScript": str(script_md),
                "timelineSource": "srt-import",
                "entriesHash": hashlib.sha256(
                    json.dumps(imp.aligner.parse_srt(srt_file), sort_keys=True).encode()
                ).hexdigest(),
                "beatAlignments": [{"beatId": "b1", "srtRange": [0, 0]}],
            }), encoding="utf-8")
            subprocess.run([
                sys.executable, str(INTERNAL / "import_srt_timeline.py"),
                str(srt_proj), "--srt", str(srt_file), "--alignment", str(align_path), "--media", str(media_wav),
            ], check=True)
            (srt_proj / "frame.json").write_text(json.dumps({
                "canvas": {"w": 1920, "h": 1080, "fps": 30},
                "personSlot": {"x": 0, "y": 0, "w": 500, "h": 1080},
                "captionSafe": {"x": 0, "y": 880, "w": 1920, "h": 200},
            }), encoding="utf-8")
            proc_srt = _run_deliver(srt_proj, "--audio", str(media_wav), "--srt", str(srt_file))
            self.assertEqual(proc_srt.returncode, 0, proc_srt.stdout + proc_srt.stderr)
            person_out = srt_proj / "成品" / f"{srt_proj.name}_人物成片.mp4"
            vd = subprocess.run([
                sys.executable, str(VERIFY_SCRIPT), str(srt_proj / "edit"),
                "--video", str(person_out), "--deliver-dir", str(srt_proj / "成品"),
                "--media", str(media_wav), "--srt", str(srt_file), "--json",
            ], capture_output=True, text=True)
            self.assertEqual(vd.returncode, 0, vd.stdout + vd.stderr)

    def test_end_to_end_storyboard_chain_init_proxy_quality_build_review_deliver(self) -> None:
        """End-to-end chain: film.py init -> film.py proxy -> check_visual_quality -> build_review -> deliver."""
        with tempfile.TemporaryDirectory() as td:
            proj = (Path(td) / "e2e_chain").resolve()
            (proj / "edit" / "_engineering").mkdir(parents=True)
            (proj / "timeline").mkdir(parents=True)
            (proj / "recordings").mkdir(parents=True)
            _make_person_video(proj / "edit" / "cut.mp4", size="720x1280", dur=2.0)
            _make_tone_audio(proj / "edit" / "_engineering" / "review_audio.m4a", dur=2.0, freq=300)
            _make_color_video(proj / "recordings" / "app.mp4", size="1280x720", dur=3.0, color="0x38BDF8")
            _seed_edl(proj, 2.0)
            (proj / "frame.json").write_text(json.dumps({
                "framePreset": "vertical-zine-head",
                "canvas": {"w": 1080, "h": 1920, "fps": 30},
            }), encoding="utf-8")
            (proj / "timeline" / "grouping.json").write_text(json.dumps({
                "chapters": [
                    {
                        "id": "ch01",
                        "title": "实操演示",
                        "steps": [
                            {"id": "D01", "title": "应用演示", "kind": "screen-demo", "startMs": 0, "endMs": 2000},
                        ],
                    }
                ]
            }, ensure_ascii=False), encoding="utf-8")
            (proj / "timeline" / "timeline.json").write_text(json.dumps({
                "totalChapters": 1,
                "totalSteps": 1,
                "totalDurationMs": 2000,
                "chapters": [
                    {
                        "id": "ch01",
                        "title": "实操演示",
                        "steps": [
                            {"id": "D01", "step": 1, "startMs": 0, "endMs": 2000, "durationMs": 2000, "caption": "实操演示"},
                        ],
                    }
                ],
            }, ensure_ascii=False), encoding="utf-8")

            # 1) film.py init -> storyboard.json
            init_proc = subprocess.run(
                [sys.executable, str(HELPERS / "film.py"), "init", str(proj), "--json"],
                capture_output=True, text=True, check=True,
            )
            self.assertTrue(json.loads(init_proc.stdout)["created"])
            sb = json.loads((proj / "storyboard.json").read_text(encoding="utf-8"))
            sb["shots"][0]["demo"] = {"source": "recordings/app.mp4", "inSec": 0.2, "outSec": 2.2}
            (proj / "storyboard.json").write_text(json.dumps(sb, ensure_ascii=False, indent=2), encoding="utf-8")

            # 2) film.py proxy -> review/demo_proxies/D01.mp4
            proxy_proc = subprocess.run(
                [sys.executable, str(HELPERS / "film.py"), "proxy", str(proj), "--json"],
                capture_output=True, text=True, check=True,
            )
            self.assertEqual(json.loads(proxy_proc.stdout)["count"], 1)

            # 3) check_visual_quality -> ok
            vq_proc = subprocess.run(
                [sys.executable, str(INTERNAL / "check_visual_quality.py"), str(proj), "--json"],
                capture_output=True, text=True, check=True,
            )
            self.assertTrue(json.loads(vq_proc.stdout)["ok"])

            # 4) review.resolve_review_mode & build_review -> picks final-cut & surfaces demoProxies
            import review
            self.assertEqual(review.resolve_review_mode(proj), "final-cut")
            br_proc = subprocess.run(
                [sys.executable, str(INTERNAL / "build_review.py"), str(proj), "--mode", "auto", "--slices", "off"],
                capture_output=True, text=True, check=True,
            )
            rev_data = json.loads((proj / "review" / "review_data.json").read_text(encoding="utf-8"))
            self.assertEqual(len(rev_data["media"]["demoProxies"]), 1)
            self.assertEqual(rev_data["media"]["demoProxies"][0]["proxy"], "review/demo_proxies/D01.mp4")

            # 5) deliver.py -> split delivery succeeds
            deliv = _run_deliver(proj)
            self.assertEqual(deliv.returncode, 0, deliv.stdout + deliv.stderr)
            self.assertTrue((proj / "成品" / f"{proj.name}_人物成片.mp4").is_file())
            self.assertTrue((proj / "成品" / f"{proj.name}_画面成片.mp4").is_file())


if __name__ == "__main__":
    unittest.main()
