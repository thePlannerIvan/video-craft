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

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "需要 ffmpeg/ffprobe")
    def test_storyboard_v3_routes_motion_tier_and_screen_demo_checks(self):
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
            (proj / "edit").mkdir(exist_ok=True)
            # A) screen-demo + talk-only in edit/storyboard.json -> exempts 14px & static, validates demo bounds
            sb_path = proj / "edit" / "storyboard.json"
            sb_path.write_text(json.dumps({
                "version": "storyboard/3",
                "canvas": {"width": 1920, "height": 1080, "fps": 30},
                "shots": [
                    {"id": "T1", "kind": "talk-only", "engine": "ffmpeg-cut", "startSec": 0.0, "endSec": 5.0},
                    {"id": "D1", "kind": "screen-demo", "engine": "ffmpeg-cut", "startSec": 5.0, "endSec": 10.0,
                     "demo": {"source": "recordings/demo.mp4", "inSec": 0.2, "outSec": 2.5}},
                ],
            }), encoding="utf-8")
            ok_rep = vq.run_checks(proj)
            self.assertTrue(ok_rep["ok"], ok_rep)

            # B) Out-of-bounds demo in storyboard.json -> fails DEMO_RANGE
            sb_path.write_text(json.dumps({
                "version": "storyboard/3",
                "canvas": {"width": 1920, "height": 1080, "fps": 30},
                "shots": [
                    {"id": "D1", "kind": "screen-demo", "engine": "ffmpeg-cut", "startSec": 0.0, "endSec": 5.0,
                     "demo": {"source": "recordings/demo.mp4", "inSec": 0.2, "outSec": 6.0}},
                ],
            }), encoding="utf-8")
            bad_demo = vq.run_checks(proj)
            self.assertFalse(bad_demo["ok"])
            self.assertTrue(any(e["rule"] == "DEMO_RANGE" for e in bad_demo["errors"]), bad_demo)

            # C) motion/model/card-deck shot activates Q1 & Q2 checks
            sb_path.write_text(json.dumps({
                "version": "storyboard/3",
                "canvas": {"width": 1920, "height": 1080, "fps": 30},
                "shots": [
                    {"id": "M1", "kind": "model", "engine": "hyperframes", "startSec": 0.0, "endSec": 10.0},
                ],
            }), encoding="utf-8")
            bad_motion = vq.run_checks(proj)
            self.assertFalse(bad_motion["ok"])
            rules = {e["rule"] for e in bad_motion["errors"]}
            self.assertIn("Q1_FONT_SIZE", rules, bad_motion)
            self.assertIn("Q2_STATIC_DURATION", rules, bad_motion)


def _make_clean_remotion_project(root: Path, *, duration_s: float = 10.0) -> Path:
    fps = 30
    total_frames = int(round(duration_s * fps))
    (root / "remotion" / "src" / "data").mkdir(parents=True, exist_ok=True)
    (root / "remotion" / "public" / "assets").mkdir(parents=True, exist_ok=True)
    (root / "remotion" / "package.json").write_text(
        json.dumps({"name": "remotion-vq-test", "version": "1.0.0", "private": True}, indent=2),
        encoding="utf-8",
    )
    (root / "remotion" / "tsconfig.json").write_text(
        json.dumps(
            {
                "compilerOptions": {
                    "target": "ES2022",
                    "module": "ES2022",
                    "moduleResolution": "bundler",
                    "jsx": "react-jsx",
                    "strict": True,
                    "esModuleInterop": True,
                    "skipLibCheck": True,
                    "noEmit": True,
                },
                "include": ["src"],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (root / "remotion" / "src" / "data" / "anchors.ts").write_text(
        f"""export const FPS = {fps};
export const TOTAL_FRAMES = {total_frames};
export const STEPS = {{
  S01: {{ start: 0.0, end: {duration_s}, dur: {duration_s} }},
}};
""",
        encoding="utf-8",
    )
    (root / "remotion" / "src" / "Main.tsx").write_text(
        """import React from "react";
import { AbsoluteFill, spring, useCurrentFrame, useVideoConfig } from "remotion";

export const MainComp: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const s = spring({ frame, fps });
  return (
    <AbsoluteFill data-role="background" style={{ backgroundColor: "#0B0F19" }}>
      <div
        id="ch01"
        style={{
          position: "absolute",
          left: 700,
          top: 120,
          width: 480,
          height: 220,
          fontSize: 48,
          fontFamily: "Inter",
          transform: `scale(${s})`,
        }}
      >
        核心洞察
      </div>
    </AbsoluteFill>
  );
};
""",
        encoding="utf-8",
    )
    (root / "remotion" / "src" / "Root.tsx").write_text(
        f"""import React from "react";
import {{ Composition }} from "remotion";
import {{ MainComp }} from "./Main";

export const RemotionRoot: React.FC = () => (
  <Composition
    id="GateMain"
    component={{MainComp}}
    durationInFrames={{{total_frames}}}
    fps={{{fps}}}
    width={{1920}}
    height={{1080}}
  />
);
""",
        encoding="utf-8",
    )
    (root / "remotion" / "src" / "index.ts").write_text(
        'import { registerRoot } from "remotion";\n'
        'import { RemotionRoot } from "./Root";\n\n'
        "registerRoot(RemotionRoot);\n",
        encoding="utf-8",
    )
    (root / "recompose.json").write_text(
        json.dumps(
            {
                "canvas": {"w": 1920, "h": 1080, "fps": fps},
                "personSlot": {"x": 0, "y": 0, "w": 620, "h": 1080},
                "captionSafe": {"x": 0, "y": 885, "w": 1920, "h": 195},
            }
        ),
        encoding="utf-8",
    )
    (root / "storyboard.json").write_text(
        json.dumps(
            {
                "version": "storyboard/3",
                "canvas": {"width": 1920, "height": 1080, "fps": fps},
                "capabilities": ["motion"],
                "shots": [
                    {"id": "S01", "kind": "motion", "engine": "remotion", "startSec": 0.0, "endSec": duration_s},
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return root


class RemotionVisualQualityGateTests(unittest.TestCase):
    def test_remotion_check_visual_runs_quality_and_blocks_sub_32px_font(self):
        with tempfile.TemporaryDirectory() as td:
            proj = _make_clean_remotion_project(Path(td))
            main_tsx = proj / "remotion" / "src" / "Main.tsx"
            main_tsx.write_text(
                main_tsx.read_text(encoding="utf-8").replace("fontSize: 48", "fontSize: 22"),
                encoding="utf-8",
            )
            proc = subprocess.run(
                [sys.executable, str(HELPERS / "check_visual.py"), str(proj), "--json"],
                capture_output=True, text=True,
            )
            self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
            doc = json.loads(proc.stdout)
            by_name = {c["check"]: c for c in doc["checks"]}
            self.assertIn("quality", by_name, doc)
            self.assertFalse(by_name["quality"]["ok"])
            q_errs = by_name["quality"]["report"]["errors"]
            self.assertTrue(any(e["rule"] == "Q1_FONT_SIZE" for e in q_errs), q_errs)

            only_q = subprocess.run(
                [sys.executable, str(HELPERS / "check_visual.py"), str(proj), "--only", "quality", "--json"],
                capture_output=True, text=True,
            )
            self.assertEqual(only_q.returncode, 1, only_q.stdout + only_q.stderr)
            q_doc = json.loads(only_q.stdout)
            self.assertTrue(any(e["rule"] == "Q1_FONT_SIZE" for e in q_doc["errors"]), q_doc)

    def test_remotion_q3_blocks_person_or_caption_safezone_and_allows_background(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            # 1) JSX div overlapping personSlot (x=0..620)
            proj1 = _make_clean_remotion_project(root / "p1")
            m1 = proj1 / "remotion" / "src" / "Main.tsx"
            m1.write_text(m1.read_text(encoding="utf-8").replace("left: 700,", "left: 200,"), encoding="utf-8")
            proc1 = subprocess.run(
                [sys.executable, str(HELPERS / "check_visual.py"), str(proj1), "--json"],
                capture_output=True, text=True,
            )
            self.assertEqual(proc1.returncode, 1, proc1.stdout + proc1.stderr)
            doc1 = json.loads(proc1.stdout)
            q1 = next(c for c in doc1["checks"] if c["check"] == "quality")
            self.assertTrue(any(e["rule"] == "Q3_SAFEZONE" for e in q1["report"]["errors"]), q1)

            # 2) SVG <rect> overlapping captionSafe (y=885..1080)
            proj2 = _make_clean_remotion_project(root / "p2")
            m2 = proj2 / "remotion" / "src" / "Main.tsx"
            m2.write_text(
                m2.read_text(encoding="utf-8").replace(
                    "核心洞察",
                    '<svg width={1920} height={1080}><rect x={700} y={920} width={300} height={100} fill="#38bdf8" /></svg>',
                ),
                encoding="utf-8",
            )
            proc2 = subprocess.run(
                [sys.executable, str(HELPERS / "check_visual.py"), str(proj2), "--only", "quality", "--json"],
                capture_output=True, text=True,
            )
            self.assertEqual(proc2.returncode, 1, proc2.stdout + proc2.stderr)
            q2 = json.loads(proc2.stdout)
            self.assertTrue(any(e["rule"] == "Q3_SAFEZONE" for e in q2["errors"]), q2)

            # 3) Explicit data-role="background" and full-canvas rect are allowed
            proj3 = _make_clean_remotion_project(root / "p3")
            m3 = proj3 / "remotion" / "src" / "Main.tsx"
            m3.write_text(
                m3.read_text(encoding="utf-8").replace(
                    "核心洞察",
                    '<div data-role="background" style={{ left: 0, top: 0, width: 600, height: 1080 }} />'
                    '<svg width={1920} height={1080}><rect x={0} y={0} width={1920} height={1080} fill="#0B0F19" /></svg>',
                ),
                encoding="utf-8",
            )
            proc3 = subprocess.run(
                [sys.executable, str(HELPERS / "check_visual.py"), str(proj3), "--only", "quality", "--json"],
                capture_output=True, text=True,
            )
            self.assertEqual(proc3.returncode, 0, proc3.stdout + proc3.stderr)

    def test_remotion_demo_in_public_assets_blocked_and_clean_project_passes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            # 1) screen-demo with demo.source inside remotion/public/assets/ -> blocked with DEMO_IN_ASSETS
            proj_bad = _make_clean_remotion_project(root / "bad_demo")
            bad_rec = proj_bad / "remotion" / "public" / "assets" / "demo.mp4"
            bad_rec.write_bytes(b"fake-demo")
            (proj_bad / "storyboard.json").write_text(
                json.dumps(
                    {
                        "version": "storyboard/3",
                        "canvas": {"width": 1920, "height": 1080, "fps": 30},
                        "capabilities": ["motion", "screen-demo"],
                        "shots": [
                            {"id": "S01", "kind": "motion", "engine": "remotion", "startSec": 0.0, "endSec": 5.0},
                            {
                                "id": "D01",
                                "kind": "screen-demo",
                                "engine": "ffmpeg-cut",
                                "startSec": 5.0,
                                "endSec": 10.0,
                                "demo": {"source": "remotion/public/assets/demo.mp4", "inSec": 0.0, "outSec": 2.0},
                            },
                        ],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            proc_bad = subprocess.run(
                [sys.executable, str(HELPERS / "check_visual.py"), str(proj_bad), "--json"],
                capture_output=True, text=True,
            )
            self.assertEqual(proc_bad.returncode, 1, proc_bad.stdout + proc_bad.stderr)
            doc_bad = json.loads(proc_bad.stdout)
            q_bad = next(c for c in doc_bad["checks"] if c["check"] == "quality")
            self.assertTrue(any(e["rule"] == "DEMO_IN_ASSETS" for e in q_bad["report"]["errors"]), q_bad)

            # 2) Clean Remotion project (>8s duration, no GSAP tl.to, multiple scenes, caption helper, dynamic fontSize, allowed fonts) exits 0
            proj_ok = _make_clean_remotion_project(root / "clean_ok", duration_s=12.0)
            (proj_ok / "remotion" / "public" / "assets" / "BrandDisplay.woff2").write_bytes(b"font")
            (proj_ok / "remotion" / "src" / "Main.tsx").write_text(
                """import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";

const CaptionLine: React.FC<{ text: string }> = ({ text }) => (
  <div className="caption-bar" style={{ fontSize: 22, fontFamily: "Source Han Sans SC" }}>
    {text}
  </div>
);

export const MainComp: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const s = spring({ frame, fps });
  const dynamicScale = interpolate(frame, [0, 360], [1, 1.1]);
  return (
    <AbsoluteFill data-role="background" style={{ backgroundColor: "#0B0F19" }}>
      <div id="ch01" style={{ position: "absolute", left: 700, top: 120, width: 480, height: 220, fontSize: 48, fontFamily: "Noto Sans SC", transform: `scale(${s})` }}>
        第一幕
      </div>
      <div id="ch02" style={{ position: "absolute", left: 700, top: 380, width: 480, height: 220, fontSize: 22 * 2 * dynamicScale, fontFamily: "BrandDisplay" }}>
        第二幕
      </div>
      <CaptionLine text="字幕安全区豁免" />
    </AbsoluteFill>
  );
};
""",
                encoding="utf-8",
            )
            proc_ok = subprocess.run(
                [sys.executable, str(HELPERS / "check_visual.py"), str(proj_ok), "--json"],
                capture_output=True, text=True,
            )
            self.assertEqual(proc_ok.returncode, 0, proc_ok.stdout + proc_ok.stderr)
            doc_ok = json.loads(proc_ok.stdout)
            self.assertTrue(doc_ok["ok"], doc_ok)

            # 3) Unregistered custom fontFamily in Remotion -> Q5_UNREGISTERED_FONT
            (proj_ok / "remotion" / "src" / "Main.tsx").write_text(
                (proj_ok / "remotion" / "src" / "Main.tsx").read_text(encoding="utf-8").replace(
                    '"Noto Sans SC"', '"UnknownFancyFont"'
                ),
                encoding="utf-8",
            )
            proc_font = subprocess.run(
                [sys.executable, str(HELPERS / "check_visual.py"), str(proj_ok), "--only", "quality", "--json"],
                capture_output=True, text=True,
            )
            self.assertEqual(proc_font.returncode, 1, proc_font.stdout + proc_font.stderr)
            q_font = json.loads(proc_font.stdout)
            self.assertTrue(any(e["rule"] == "Q5_UNREGISTERED_FONT" for e in q_font["errors"]), q_font)

    def test_remotion_check_visual_handles_explicit_composition_and_custom_dir(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            proj1 = _make_clean_remotion_project(root / "explicit_rem")
            main1 = proj1 / "remotion" / "src" / "Main.tsx"
            main1.write_text(main1.read_text(encoding="utf-8").replace("fontSize: 48", "fontSize: 22"), encoding="utf-8")

            # Passing --composition remotion must NOT silently skip Remotion quality checks
            proc1 = subprocess.run(
                [sys.executable, str(HELPERS / "check_visual.py"), str(proj1), "--composition", "remotion", "--json"],
                capture_output=True, text=True,
            )
            self.assertEqual(proc1.returncode, 1, proc1.stdout + proc1.stderr)
            doc1 = json.loads(proc1.stdout)
            q1 = next(c for c in doc1["checks"] if c["check"] == "quality")
            self.assertTrue(any(e["rule"] == "Q1_FONT_SIZE" for e in q1["report"]["errors"]), q1)

            only_q1 = subprocess.run(
                [sys.executable, str(HELPERS / "check_visual.py"), str(proj1), "--only", "quality", "--composition", "remotion", "--json"],
                capture_output=True, text=True,
            )
            self.assertEqual(only_q1.returncode, 1, only_q1.stdout + only_q1.stderr)
            self.assertTrue(any(e["rule"] == "Q1_FONT_SIZE" for e in json.loads(only_q1.stdout)["errors"]))

            # Custom Remotion dir named via --composition custom_rem must also resolve Remotion checks
            proj2 = _make_clean_remotion_project(root / "custom_rem_proj")
            custom_dir = proj2 / "custom_rem"
            shutil.move(str(proj2 / "remotion"), str(custom_dir))
            (custom_dir / "src" / "Main.tsx").write_text(
                (custom_dir / "src" / "Main.tsx").read_text(encoding="utf-8").replace("fontSize: 48", "fontSize: 22"),
                encoding="utf-8",
            )
            rep2 = vq.run_checks(proj2, comp_name="custom_rem")
            self.assertFalse(rep2["ok"], rep2)
            self.assertTrue(any(e["rule"] == "Q1_FONT_SIZE" for e in rep2["errors"]), rep2)

    def test_remotion_q3_tracks_nested_svg_translate_and_svg_xy_offsets(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            # 1) Nested <svg x={500} y={0}> + <g transform="translate(200, 100)"> + <g transform="translate(50, 50)">
            #    Global rect: x = 500 + 200 + 50 = 750 (clear of personSlot 0..620), y = 150..250 -> passes
            proj_ok = _make_clean_remotion_project(root / "nested_ok")
            m_ok = proj_ok / "remotion" / "src" / "Main.tsx"
            m_ok.write_text(
                m_ok.read_text(encoding="utf-8").replace(
                    "</AbsoluteFill>",
                    '  <svg x={500} y={0} width={1420} height={885}>'
                    '<g transform="translate(200, 100)">'
                    '<g transform="translate(50, 50)">'
                    '<rect x={0} y={0} width={200} height={100} fill="#38bdf8" />'
                    '</g></g></svg>\n    </AbsoluteFill>',
                ),
                encoding="utf-8",
            )
            rep_ok = vq.run_checks(proj_ok)
            self.assertTrue(rep_ok["ok"], rep_ok)

            # 2) Shifted intrusion into personSlot via nested <g transform="translate(-400, 0)"> (500 + 200 - 400 = 300 < 620)
            proj_bad_person = _make_clean_remotion_project(root / "nested_bad_person")
            m_bad_p = proj_bad_person / "remotion" / "src" / "Main.tsx"
            m_bad_p.write_text(
                m_bad_p.read_text(encoding="utf-8").replace(
                    "</AbsoluteFill>",
                    '  <svg x={500} y={0} width={1420} height={885}>'
                    '<g transform="translate(200, 100)">'
                    '<g transform="translate(-400, 0)">'
                    '<rect x={0} y={0} width={200} height={100} fill="#38bdf8" />'
                    '</g></g></svg>\n    </AbsoluteFill>',
                ),
                encoding="utf-8",
            )
            rep_bad_p = vq.run_checks(proj_bad_person)
            self.assertFalse(rep_bad_p["ok"], rep_bad_p)
            self.assertTrue(any(e["rule"] == "Q3_SAFEZONE" for e in rep_bad_p["errors"]), rep_bad_p)

            # 3) Shifted intrusion into captionSafe via nested <g transform="translate(0, 750)"> (100 + 750 = 850, h=100 -> 850..950 > 885)
            proj_bad_cap = _make_clean_remotion_project(root / "nested_bad_cap")
            m_bad_c = proj_bad_cap / "remotion" / "src" / "Main.tsx"
            m_bad_c.write_text(
                m_bad_c.read_text(encoding="utf-8").replace(
                    "</AbsoluteFill>",
                    '  <svg x={500} y={0} width={1420} height={1080}>'
                    '<g transform="translate(200, 100)">'
                    '<g transform="translate(0, 750)">'
                    '<rect x={0} y={0} width={200} height={100} fill="#38bdf8" />'
                    '</g></g></svg>\n    </AbsoluteFill>',
                ),
                encoding="utf-8",
            )
            rep_bad_c = vq.run_checks(proj_bad_cap)
            self.assertFalse(rep_bad_c["ok"], rep_bad_c)
            self.assertTrue(any(e["rule"] == "Q3_SAFEZONE" for e in rep_bad_c["errors"]), rep_bad_c)

    def test_remotion_q3_blocks_canvas_stage_and_text_anchor_label_bounds(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            # 1) Right-edge overflowing <text> label
            proj1 = _make_clean_remotion_project(root / "text_right")
            m1 = proj1 / "remotion" / "src" / "Main.tsx"
            m1.write_text(
                m1.read_text(encoding="utf-8").replace(
                    "</AbsoluteFill>",
                    '  <svg width={1920} height={1080}><text x={1850} y={240} fontSize={48}>右侧超长锚点标签</text></svg>\n    </AbsoluteFill>',
                ),
                encoding="utf-8",
            )
            rep1 = vq.run_checks(proj1)
            self.assertFalse(rep1["ok"], rep1)
            self.assertTrue(any(e["rule"] == "Q3_ANCHOR_BOUNDS" for e in rep1["errors"]), rep1)

            # 2) Negative coordinate <text>
            proj2 = _make_clean_remotion_project(root / "text_neg")
            m2 = proj2 / "remotion" / "src" / "Main.tsx"
            m2.write_text(
                m2.read_text(encoding="utf-8").replace(
                    "</AbsoluteFill>",
                    '  <svg width={1920} height={1080}><text x={-20} y={240} fontSize={48}>越界</text></svg>\n    </AbsoluteFill>',
                ),
                encoding="utf-8",
            )
            rep2 = vq.run_checks(proj2)
            self.assertFalse(rep2["ok"], rep2)
            self.assertTrue(any(e["rule"] == "Q3_ANCHOR_BOUNDS" for e in rep2["errors"]), rep2)

            # 3) Container box extending outside [0..cw, 0..ch]
            proj3 = _make_clean_remotion_project(root / "box_oob")
            m3 = proj3 / "remotion" / "src" / "Main.tsx"
            m3.write_text(
                m3.read_text(encoding="utf-8").replace("left: 700,\n          top: 120,\n          width: 480,", "left: 1650,\n          top: 120,\n          width: 480,"),
                encoding="utf-8",
            )
            rep3 = vq.run_checks(proj3)
            self.assertFalse(rep3["ok"], rep3)
            self.assertTrue(any(e["rule"] == "Q3_ANCHOR_BOUNDS" for e in rep3["errors"]), rep3)

            # 4) Properly right-aligned <text textAnchor="end"> fits inside [0..1920] and passes
            proj4 = _make_clean_remotion_project(root / "text_ok")
            m4 = proj4 / "remotion" / "src" / "Main.tsx"
            m4.write_text(
                m4.read_text(encoding="utf-8").replace(
                    "</AbsoluteFill>",
                    '  <svg width={1920} height={1080}><text x={1880} y={240} textAnchor="end" fontSize={48}>右对齐标签</text></svg>\n    </AbsoluteFill>',
                ),
                encoding="utf-8",
            )
            rep4 = vq.run_checks(proj4)
            self.assertTrue(rep4["ok"], rep4)


if __name__ == "__main__":
    unittest.main()
