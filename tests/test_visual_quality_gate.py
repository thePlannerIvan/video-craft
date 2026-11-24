#!/usr/bin/env python3
"""Tests for unified build-time visual quality gate (Q1-Q6, demo-footage routing,
and check_render_fidelity adjacent-frame + full-res transition rescue).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HELPERS = Path(__file__).parents[1] / "helpers"
INTERNAL = HELPERS / "_internal"
sys.path.insert(0, str(HELPERS))
sys.path.insert(0, str(INTERNAL))

import check_render_fidelity as fid  # noqa: E402
import check_visual_quality as vq    # noqa: E402


def _make_clean_project(root: Path, *, duration_s: float = 9.0) -> Path:
    comp = root / "composition"
    src = comp / "src"
    comp.mkdir(parents=True, exist_ok=True)
    src.mkdir(parents=True, exist_ok=True)
    (comp / "assets").mkdir(exist_ok=True)
    (comp / "index.html").write_text(f"""<!doctype html>
<html><head><style>
  .title {{ font-size: 48px; font-family: "PingFang SC", sans-serif; }}
  .caption {{ font-size: 22px; }}
</style></head>
<body>
  <div id="root" data-composition-id="main" data-start="0" data-width="1920" data-height="1080" data-duration="{duration_s}" data-fps="30">
    <svg viewBox="0 0 1920 1080">
      <defs>
        <filter id="glow" filterUnits="userSpaceOnUse"><feGaussianBlur stdDeviation="4"/></filter>
      </defs>
      <rect x="0" y="0" width="1920" height="1080" fill="#11131a"/>
      <g id="ch01">
        <rect x="700" y="120" width="400" height="200" fill="#38bdf8"/>
        <text x="740" y="220" font-size="44" font-family="PingFang SC">核心洞察</text>
        <line x1="700" y1="360" x2="1100" y2="360" filter="url(#glow)" stroke="#fff"/>
      </g>
    </svg>
  </div>
  <script src="src/main.js"></script>
</body></html>""", encoding="utf-8")
    (src / "main.js").write_text("""
const tl = HF.tl;
tl.to("#ch01", { opacity: 1, duration: 1 }, 0.5);
tl.to("#ch01", { y: 20, duration: 1 }, 4.5);
""", encoding="utf-8")
    (root / "recompose.json").write_text(json.dumps({
        "canvas": {"w": 1920, "h": 1080, "fps": 30},
        "personSlot": {"x": 0, "y": 0, "w": 620, "h": 1080},
        "captionSafe": {"x": 0, "y": 885, "w": 1920, "h": 195},
    }), encoding="utf-8")
    return root


class VisualQualityGateTests(unittest.TestCase):
    def test_clean_project_and_cli_smoke(self):
        with tempfile.TemporaryDirectory() as td:
            proj = _make_clean_project(Path(td))
            report = vq.run_checks(proj)
            self.assertTrue(report["ok"], report)
            proc = subprocess.run(
                [sys.executable, str(HELPERS / "check_visual.py"), str(proj), "--only", "quality", "--json"],
                capture_output=True, text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_q1_blocks_sub_32px_and_exempts_caption(self):
        with tempfile.TemporaryDirectory() as td:
            proj = _make_clean_project(Path(td))
            html = proj / "composition" / "index.html"
            html.write_text(html.read_text(encoding="utf-8").replace('font-size="44"', 'font-size="22"'), encoding="utf-8")
            report = vq.run_checks(proj)
            self.assertFalse(report["ok"])
            self.assertTrue(any(e["rule"] == "Q1_FONT_SIZE" for e in report["errors"]), report)

    def test_q2_blocks_static_logic_diagram_and_allows_talk_only(self):
        with tempfile.TemporaryDirectory() as td:
            proj = _make_clean_project(Path(td), duration_s=10.0)
            (proj / "composition" / "src" / "main.js").write_text('tl.to("#ch01", { opacity: 1 }, 0.0);', encoding="utf-8")
            (proj / "visual-plan.json").write_text(json.dumps({
                "version": 2,
                "segments": [{"id": "s1", "tier": "logic-diagram", "startMs": 0, "endMs": 10000,
                              "hero": "圈", "anchors": ["核心"]}],
            }), encoding="utf-8")
            bad = vq.run_checks(proj)
            self.assertFalse(bad["ok"])
            self.assertTrue(any(e["rule"] == "Q2_STATIC_DURATION" for e in bad["errors"]), bad)

            # Talk-only segment with zero composition animations passes Q2
            (proj / "visual-plan.json").write_text(json.dumps({
                "version": 2,
                "segments": [{"id": "s1", "tier": "talk-only", "startMs": 0, "endMs": 10000}],
            }), encoding="utf-8")
            ok = vq.run_checks(proj)
            self.assertTrue(ok["ok"], ok)

    def test_q3_blocks_person_or_caption_safezone_intrusion(self):
        with tempfile.TemporaryDirectory() as td:
            proj = _make_clean_project(Path(td))
            html = proj / "composition" / "index.html"
            # Invade personSlot (x=0..620)
            html.write_text(html.read_text(encoding="utf-8").replace('x="700" y="120"', 'x="200" y="120"'), encoding="utf-8")
            bad1 = vq.run_checks(proj)
            self.assertFalse(bad1["ok"])
            self.assertTrue(any(e["rule"] == "Q3_SAFEZONE" for e in bad1["errors"]), bad1)

            # Invade captionSafe (y=885..1080)
            proj2 = _make_clean_project(Path(td) / "p2")
            html2 = proj2 / "composition" / "index.html"
            html2.write_text(html2.read_text(encoding="utf-8").replace('x="700" y="120"', 'x="700" y="920"'), encoding="utf-8")
            bad2 = vq.run_checks(proj2)
            self.assertFalse(bad2["ok"])
            self.assertTrue(any(e["rule"] == "Q3_SAFEZONE" for e in bad2["errors"]), bad2)

    def test_q4_blocks_axis_line_filter_missing_userspace(self):
        with tempfile.TemporaryDirectory() as td:
            proj = _make_clean_project(Path(td))
            html = proj / "composition" / "index.html"
            html.write_text(html.read_text(encoding="utf-8").replace(' filterUnits="userSpaceOnUse"', ""), encoding="utf-8")
            report = vq.run_checks(proj)
            self.assertFalse(report["ok"])
            self.assertTrue(any(e["rule"] == "Q4_AXIS_FILTER" for e in report["errors"]), report)

    def test_q5_blocks_unregistered_font_and_allows_declared_font_face(self):
        with tempfile.TemporaryDirectory() as td:
            proj = _make_clean_project(Path(td))
            html = proj / "composition" / "index.html"
            raw = html.read_text(encoding="utf-8").replace('"PingFang SC"', '"CustomMissingDisplay"')
            html.write_text(raw, encoding="utf-8")
            bad = vq.run_checks(proj)
            self.assertFalse(bad["ok"])
            self.assertTrue(any(e["rule"] == "Q5_UNREGISTERED_FONT" for e in bad["errors"]), bad)

            # Register @font-face with real file -> passes
            (proj / "composition" / "custom.woff2").write_bytes(b"font")
            with_ff = raw.replace(
                "<style>",
                '<style>\n@font-face { font-family: "CustomMissingDisplay"; src: url("custom.woff2"); }\n',
            )
            html.write_text(with_ff, encoding="utf-8")
            ok = vq.run_checks(proj)
            self.assertTrue(ok["ok"], ok)

    def test_q6_blocks_cross_chapter_leak_without_exit_hide(self):
        with tempfile.TemporaryDirectory() as td:
            proj = _make_clean_project(Path(td))
            html = proj / "composition" / "index.html"
            html.write_text(
                html.read_text(encoding="utf-8").replace("</svg>", '<g id="ch02"><rect x="700" y="420" width="300" height="100" fill="#fff"/></g></svg>'),
                encoding="utf-8",
            )
            bad = vq.run_checks(proj)
            self.assertFalse(bad["ok"])
            self.assertTrue(any(e["rule"] == "Q6_CHAPTER_RESIDUAL" for e in bad["errors"]), bad)

            (proj / "composition" / "src" / "main.js").write_text("""
tl.to("#ch01", { opacity: 1 }, 0.5);
tl.to("#ch01", { opacity: 0 }, 4.5);
tl.to("#ch02", { opacity: 1 }, 4.5);
""", encoding="utf-8")
            ok = vq.run_checks(proj)
            self.assertTrue(ok["ok"], ok)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "需要 ffmpeg/ffprobe")
    def test_demo_footage_exempts_font_static_and_validates_source_bounds_luma_safezone(self):
        with tempfile.TemporaryDirectory() as td:
            proj = _make_clean_project(Path(td), duration_s=10.0)
            (proj / "composition" / "src" / "main.js").write_text("", encoding="utf-8")
            html = proj / "composition" / "index.html"
            html.write_text(html.read_text(encoding="utf-8").replace('font-size="44"', 'font-size="14"'), encoding="utf-8")
            rec = proj / "recordings" / "demo.mp4"
            rec.parent.mkdir(parents=True)
            subprocess.run([
                "ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                "-i", "color=c=0x38BDF8:s=1280x720:r=30:d=3",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", str(rec),
            ], check=True)
            # Clean demo-only project passes despite 14px SVG font & 10s static composition
            (proj / "visual-plan.json").write_text(json.dumps({
                "version": 2,
                "segments": [{"id": "d1", "tier": "demo-footage", "startMs": 0, "endMs": 10000,
                              "demo": {"source": "recordings/demo.mp4", "inSec": 0.2, "outSec": 2.5}}],
            }), encoding="utf-8")
            ok = vq.run_checks(proj)
            self.assertTrue(ok["ok"], ok)

            # Out-of-bounds outSec -> blocked
            (proj / "visual-plan.json").write_text(json.dumps({
                "version": 2,
                "segments": [{"id": "d1", "tier": "demo-footage", "startMs": 0, "endMs": 10000,
                              "demo": {"source": "recordings/demo.mp4", "inSec": 0.2, "outSec": 5.0}}],
            }), encoding="utf-8")
            oob = vq.run_checks(proj)
            self.assertFalse(oob["ok"])
            self.assertTrue(any(e["rule"] == "DEMO_RANGE" for e in oob["errors"]), oob)

            # Safezone intrusion -> blocked
            (proj / "visual-plan.json").write_text(json.dumps({
                "version": 2,
                "segments": [{"id": "d1", "tier": "demo-footage", "startMs": 0, "endMs": 10000,
                              "demo": {"source": "recordings/demo.mp4", "inSec": 0.2, "outSec": 2.5,
                                       "box": {"x": 100, "y": 100, "w": 800, "h": 500}}}],
            }), encoding="utf-8")
            sz = vq.run_checks(proj)
            self.assertFalse(sz["ok"])
            self.assertTrue(any(e["rule"] == "DEMO_SAFEZONE" for e in sz["errors"]), sz)

            # All-black frame -> blocked
            blk = proj / "recordings" / "black.mp4"
            subprocess.run([
                "ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                "-i", "color=c=0x000000:s=1280x720:r=30:d=2",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", str(blk),
            ], check=True)
            (proj / "visual-plan.json").write_text(json.dumps({
                "version": 2,
                "segments": [{"id": "d1", "tier": "demo-footage", "startMs": 0, "endMs": 2000,
                              "demo": {"source": "recordings/black.mp4", "inSec": 0.2, "outSec": 1.8}}],
            }), encoding="utf-8")
            black_rep = vq.run_checks(proj)
            self.assertFalse(black_rep["ok"])
            self.assertTrue(any(e["rule"] == "DEMO_BLACK_FRAME" for e in black_rep["errors"]), black_rep)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "需要 ffmpeg/ffprobe")
    def test_fidelity_rescues_fast_slide_transition_and_still_blocks_missing_render(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            vid = tmp / "slide.mp4"
            # Fast horizontal slide via animated overlay (~33px/frame at 30fps -> ~8px shift in 160x90)
            subprocess.run([
                "ffmpeg", "-y", "-v", "error",
                "-f", "lavfi", "-i", "color=c=0x080A0F:s=640x360:r=30:d=2",
                "-f", "lavfi", "-i", "color=c=0xFFFFFF:s=140x140:r=30:d=2",
                "-filter_complex", "[0:v][1:v]overlay=x='40+t*1000':y=100:shortest=1[out]",
                "-map", "[out]", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(vid),
            ], check=True)
            # Extract reference PNG at t + 1 frame (0.2 + 0.0333 = 0.2333s) and evaluate at t=0.20s
            ref_shift = tmp / "ref_shift.png"
            dt = 1.0 / fid.probe_fps(vid)
            subprocess.run([
                "ffmpeg", "-y", "-v", "error", "-ss", f"{0.2 + dt:.4f}", "-i", str(vid),
                "-frames:v", "1", str(ref_shift),
            ], check=True)
            res = fid.evaluate_sample(ref_shift, vid, t=0.2, dur=2.0, dt=dt, min_corr=0.93)
            self.assertTrue(res["ok"], res)
            self.assertTrue(res["transition_rescued"], res)

            # Negative control: missing box content -> must NOT rescue
            blank_vid = tmp / "blank.mp4"
            subprocess.run([
                "ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                "-i", "color=c=0x080A0F:s=640x360:r=30:d=2",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", str(blank_vid),
            ], check=True)
            bad = fid.evaluate_sample(ref_shift, blank_vid, t=0.2, dur=2.0, dt=dt, min_corr=0.93)
            self.assertFalse(bad["ok"], bad)
            self.assertFalse(bad["transition_rescued"], bad)

    def test_positioned_svg_stage_anchor_cues_and_child_cleared_chapter_pass(self):
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td)
            (proj / "composition" / "src" / "scenes").mkdir(parents=True)
            (proj / "recompose.json").write_text(json.dumps({
                "canvas": {"w": 1920, "h": 1080, "fps": 30},
                "personSlot": {"x": 0, "y": 0, "w": 500, "h": 1080},
                "captionSafe": {"x": 0, "y": 920, "w": 1920, "h": 160},
            }), encoding="utf-8")
            (proj / "visual-plan.json").write_text(json.dumps({
                "version": 2,
                "segments": [
                    {"id": "seg-1", "tier": "logic-diagram", "startMs": 0, "endMs": 14000, "hero": "圆", "anchors": ["核"]},
                ],
            }), encoding="utf-8")
            (proj / "composition" / "index.html").write_text("""<!doctype html>
<html><head><style>#stage { position: absolute; left: 500px; top: 0; width: 1420px; height: 1080px; }</style></head>
<body><div data-composition-id="main" data-start="0" data-duration="14">
<svg id="stage" viewBox="0 0 1420 1080" width="1420" height="1080">
  <g id="ch01-stage"><circle id="c0" cx="350" cy="400" r="120" /></g>
  <g id="ch02-stage" opacity="0"><circle id="c1" cx="700" cy="400" r="120" /></g>
  <g id="solo"><rect id="soloDim" x="0" y="0" width="1420" height="1080" fill="#050505" opacity="0" />
    <text id="t1" x="710" y="485" font-size="48">核心概念</text></g>
</svg></div></body></html>""", encoding="utf-8")
            (proj / "composition" / "src" / "anchors.js").write_text(
                'window.__ANCHORS__ = {"cues": [[0, 1.0, 4.0], [1, 6.5, 9.0], [2, 11.5, 13.5]]};',
                encoding="utf-8",
            )
            (proj / "composition" / "src" / "scenes" / "stage.js").write_text("""const C = (i) => window.__ANCHORS__.cues[i][1];
const lo = (sel, v, t) => tl.to(sel, { attr: { opacity: v }, duration: 0.4 }, t);
lo("#c0", 1, C(0));
tl.to("#c0", { attr: { r: 160 } }, C(1));
lo("#c0", 0, C(2));
tl.to("#ch02-stage", { opacity: 1 }, C(2));
""", encoding="utf-8")
            rep = vq.run_checks(proj)
            self.assertTrue(rep["ok"], rep)
            self.assertEqual(rep["errors"], [], rep)


if __name__ == "__main__":
    unittest.main()
