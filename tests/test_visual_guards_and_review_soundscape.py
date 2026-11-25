#!/usr/bin/env python3
"""Black-box tests for Ticket #06:
1. Review page Visual Soundscape audition + B-roll bed ON/OFF toggle
2. Live-stage <video class="clip"> visibility:hidden + GSAP autoAlpha black-frame guard
3. Canvas/SVG anchor label / drawLeader / fillText bounds + data-role="background" guard
"""
from __future__ import annotations

import json
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HELPERS = ROOT / "helpers"
INTERNAL = HELPERS / "_internal"

sys.path.insert(0, str(HELPERS))
sys.path.insert(0, str(INTERNAL))

BUILD_REVIEW = INTERNAL / "build_review.py"
CHECK_TEMPLATE = INTERNAL / "check_review_template.py"
CHECK_LIVE_STAGE = INTERNAL / "check_live_stage.py"
CHECK_VISUAL_QUALITY = INTERNAL / "check_visual_quality.py"


def _write_silent_wav(path: Path, *, duration_s: float = 1.5, sr: int = 16000, channels: int = 1) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    nframes = int(round(duration_s * sr))
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(struct.pack("<" + "h" * (nframes * channels), *([0] * (nframes * channels))))


def _timeline_doc() -> dict:
    return {
        "totalChapters": 1,
        "totalSteps": 1,
        "totalDurationMs": 1500,
        "chapters": [
            {
                "id": "ch01",
                "title": "开场",
                "steps": [
                    {
                        "id": "ch01-01",
                        "step": 1,
                        "startMs": 0,
                        "endMs": 1500,
                        "durationMs": 1500,
                        "caption": "第一句口播测试",
                        "sourcePageKey": "ch01",
                    }
                ],
            }
        ],
    }


def _recompose_doc() -> dict:
    return {
        "mode": "recompose",
        "canvas": {"w": 1920, "h": 1080, "fps": 30},
        "personSlot": {"x": 0, "y": 0, "w": 500, "h": 1080},
        "captionSafe": {"x": 0, "y": 880, "w": 1920, "h": 200},
    }


def _make_live_stage_project(root: Path, *, style_css: str, body_html: str, main_js: str) -> Path:
    comp = root / "composition"
    (comp / "src").mkdir(parents=True, exist_ok=True)
    (comp / "assets").mkdir(parents=True, exist_ok=True)
    (comp / "assets" / "composition-embed-bridge.js").write_text("/* bridge */\n", encoding="utf-8")
    (comp / "assets" / "clip.mp4").write_bytes(b"mp4")
    (comp / "src" / "main.js").write_text(
        main_js + '\nwindow.__timelines = window.__timelines || {};\nwindow.__timelines["main"] = tl;\n',
        encoding="utf-8",
    )
    (comp / "index.html").write_text(
        f"""<!doctype html>
<html>
<head>
<style>
{style_css}
</style>
</head>
<body>
  <div id="root" data-composition-id="main" data-start="0" data-width="1080" data-height="1920" data-duration="8.0">
    {body_html}
  </div>
  <script src="src/main.js"></script>
  <script src="assets/composition-embed-bridge.js"></script>
  <script>window.__timelines = window.__timelines || {{}};</script>
</body>
</html>""",
        encoding="utf-8",
    )
    return root


def _make_quality_project(
    root: Path,
    *,
    svg_body: str,
    main_js: str = 'const tl = HF.tl;\ntl.to("#ch01", { opacity: 1, duration: 0.5 }, 0.5);\ntl.to("#ch01", { y: 12, duration: 0.5 }, 4.5);\n',
    canvas_w: int = 1080,
    canvas_h: int = 1920,
) -> Path:
    comp = root / "composition"
    (comp / "src").mkdir(parents=True, exist_ok=True)
    (comp / "assets").mkdir(parents=True, exist_ok=True)
    (comp / "index.html").write_text(
        f"""<!doctype html>
<html>
<head>
<style>
  .label {{ font-size: 64px; font-family: "PingFang SC", sans-serif; }}
</style>
</head>
<body>
  <div id="root" data-composition-id="main" data-start="0" data-width="{canvas_w}" data-height="{canvas_h}" data-duration="8.0">
    <svg viewBox="0 0 {canvas_w} {canvas_h}" width="{canvas_w}" height="{canvas_h}">
      <rect x="0" y="0" width="{canvas_w}" height="{canvas_h}" fill="#11131a"/>
      {svg_body}
    </svg>
  </div>
  <script src="src/main.js"></script>
</body>
</html>""",
        encoding="utf-8",
    )
    (comp / "src" / "main.js").write_text(main_js, encoding="utf-8")
    (root / "frame.json").write_text(
        json.dumps(
            {
                "canvas": {"w": canvas_w, "h": canvas_h, "fps": 30},
                "personSlot": {"x": 0, "y": 1400, "w": 400, "h": 520},
                "captionSafe": {"x": 0, "y": 1520, "w": canvas_w, "h": 400},
            }
        ),
        encoding="utf-8",
    )
    return root


class ReviewSoundscapeAuditionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.proj = Path(self._tmp.name) / "proj"
        (self.proj / "edit" / "_engineering").mkdir(parents=True)
        (self.proj / "timeline").mkdir(parents=True)
        (self.proj / "timeline" / "timeline.json").write_text(
            json.dumps(_timeline_doc(), ensure_ascii=False), encoding="utf-8"
        )
        (self.proj / "recompose.json").write_text(
            json.dumps(_recompose_doc(), ensure_ascii=False), encoding="utf-8"
        )
        _write_silent_wav(self.proj / "edit" / "audio_mix.wav", duration_s=1.5)
        _write_silent_wav(self.proj / "edit" / "voice_dry.wav", duration_s=1.5)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_template_static_guardrails_and_proofs_remain_green(self) -> None:
        proc = subprocess.run([sys.executable, str(CHECK_TEMPLATE)], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        prove = subprocess.run([sys.executable, str(CHECK_TEMPLATE), "--prove"], capture_output=True, text=True)
        self.assertEqual(prove.returncode, 0, prove.stdout + prove.stderr)

    def test_build_review_discovers_soundscape_variants_and_excludes_when_absent(self) -> None:
        # 1) Without soundscape files: clean null metadata
        proc_no = subprocess.run(
            [sys.executable, str(BUILD_REVIEW), str(self.proj), "--mode", "auto", "--slices", "off"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc_no.returncode, 0, proc_no.stdout + proc_no.stderr)
        data_no = json.loads((self.proj / "review" / "review_data.json").read_text(encoding="utf-8"))
        self.assertIsNone(data_no["media"]["audioTracks"].get("soundscape"))
        self.assertIsNone(data_no["media"].get("soundscape"))

        # 2) With edit/_engineering/soundscape.wav and soundscape_sfx_only.wav
        _write_silent_wav(self.proj / "edit" / "_engineering" / "soundscape.wav", duration_s=1.5, sr=48000, channels=2)
        _write_silent_wav(
            self.proj / "edit" / "_engineering" / "soundscape_sfx_only.wav", duration_s=1.5, sr=48000, channels=2
        )
        proc_yes = subprocess.run(
            [sys.executable, str(BUILD_REVIEW), str(self.proj), "--mode", "auto", "--slices", "off"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc_yes.returncode, 0, proc_yes.stdout + proc_yes.stderr)
        data_yes = json.loads((self.proj / "review" / "review_data.json").read_text(encoding="utf-8"))
        self.assertEqual(data_yes["media"]["audioTracks"]["soundscape"], "edit/_engineering/soundscape.wav")
        self.assertEqual(
            data_yes["media"]["audioTracks"]["soundscapeSfxOnly"],
            "edit/_engineering/soundscape_sfx_only.wav",
        )
        self.assertEqual(data_yes["media"]["soundscape"]["bedOn"], "edit/_engineering/soundscape.wav")
        self.assertEqual(data_yes["media"]["soundscape"]["bedOff"], "edit/_engineering/soundscape_sfx_only.wav")
        manifest_paths = {item["path"] for item in data_yes["sourceManifest"]}
        self.assertIn("edit/_engineering/soundscape.wav", manifest_paths)
        self.assertIn("edit/_engineering/soundscape_sfx_only.wav", manifest_paths)

    def test_browser_broll_bed_toggle_and_non_soundscape_project(self) -> None:
        from playwright.sync_api import sync_playwright
        from lib.planners_modules import resolve_module
        import review_surface

        sys.path.insert(0, str(resolve_module("planners-review-core") / "scripts" / "lib"))
        import review_host

        # A) Project WITH soundscape + sfx_only
        _write_silent_wav(self.proj / "edit" / "_engineering" / "soundscape.wav", duration_s=1.5, sr=48000, channels=2)
        _write_silent_wav(
            self.proj / "edit" / "_engineering" / "soundscape_sfx_only.wav", duration_s=1.5, sr=48000, channels=2
        )
        proc = subprocess.run(
            [sys.executable, str(BUILD_REVIEW), str(self.proj), "--mode", "auto", "--slices", "off"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        host = review_surface.open_review(self.proj, open_browser=False)
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                try:
                    page = browser.new_page(viewport={"width": 1280, "height": 800})
                    page.route("**/localhost:5176/**", lambda route: route.abort())
                    page.route("**/cdn.jsdelivr.net/**", lambda route: route.abort())
                    page.goto(host["url"], wait_until="domcontentloaded")
                    page.wait_for_function("() => !document.getElementById('fb-save').disabled", timeout=15000)

                    bed_btn = page.locator("#btn-broll-bed")
                    self.assertTrue(bed_btn.is_visible(), "soundscape toggle button should be visible")
                    self.assertEqual(page.evaluate("() => document.body.dataset.brollBed"), "on")
                    page.wait_for_function(
                        "() => !!document.getElementById('review-soundscape-audio')?.getAttribute('src')",
                        timeout=10000,
                    )
                    on_src = page.evaluate("() => document.getElementById('review-soundscape-audio').getAttribute('src')")
                    self.assertFalse(page.evaluate("() => document.getElementById('review-soundscape-audio').muted"))

                    # Toggle B-roll ambient bed OFF -> switches to soundscape_sfx_only.wav (unmuted SFX)
                    bed_btn.click()
                    page.wait_for_function(
                        """(prev) => document.body.dataset.brollBed === 'off'
                            && !!document.getElementById('review-soundscape-audio')?.getAttribute('src')
                            && document.getElementById('review-soundscape-audio').getAttribute('src') !== prev""",
                        arg=on_src,
                        timeout=10000,
                    )
                    self.assertFalse(page.evaluate("() => document.getElementById('review-soundscape-audio').muted"))

                    # Toggle back ON -> restores soundscape.wav
                    bed_btn.click()
                    page.wait_for_function(
                        """(exp) => document.body.dataset.brollBed === 'on'
                            && document.getElementById('review-soundscape-audio')?.getAttribute('src') === exp""",
                        arg=on_src,
                        timeout=10000,
                    )

                    # Existing Voice A/B toggle still works independently
                    ab_btn = page.locator("#btn-audio-ab")
                    ab_btn.click()
                    page.wait_for_function("() => document.body.dataset.audioMode === 'dry'", timeout=10000)
                finally:
                    browser.close()
        finally:
            review_host.stop_host(host)

        # B) Project WITHOUT soundscape: toggle button stays hidden and audio element has no src
        proj_plain = Path(self._tmp.name) / "plain"
        shutil.copytree(self.proj, proj_plain)
        (proj_plain / "edit" / "_engineering" / "soundscape.wav").unlink()
        (proj_plain / "edit" / "_engineering" / "soundscape_sfx_only.wav").unlink()
        proc2 = subprocess.run(
            [sys.executable, str(BUILD_REVIEW), str(proj_plain), "--mode", "auto", "--slices", "off"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc2.returncode, 0, proc2.stdout + proc2.stderr)
        host2 = review_surface.open_review(proj_plain, open_browser=False)
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                try:
                    page = browser.new_page(viewport={"width": 1280, "height": 800})
                    page.route("**/localhost:5176/**", lambda route: route.abort())
                    page.route("**/cdn.jsdelivr.net/**", lambda route: route.abort())
                    page.goto(host2["url"], wait_until="domcontentloaded")
                    page.wait_for_function("() => !document.getElementById('fb-save').disabled", timeout=15000)
                    self.assertFalse(page.locator("#btn-broll-bed").is_visible())
                    self.assertIsNone(
                        page.evaluate("() => document.getElementById('review-soundscape-audio')?.getAttribute('src')")
                    )
                finally:
                    browser.close()
        finally:
            review_host.stop_host(host2)

        # C) Project WITH soundscape.wav ONLY (no soundscape_sfx_only.wav): OFF mutes soundscape audio
        proj_bed_only = Path(self._tmp.name) / "bed_only"
        shutil.copytree(self.proj, proj_bed_only)
        (proj_bed_only / "edit" / "_engineering" / "soundscape_sfx_only.wav").unlink()
        proc3 = subprocess.run(
            [sys.executable, str(BUILD_REVIEW), str(proj_bed_only), "--mode", "auto", "--slices", "off"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc3.returncode, 0, proc3.stdout + proc3.stderr)
        host3 = review_surface.open_review(proj_bed_only, open_browser=False)
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                try:
                    page = browser.new_page(viewport={"width": 1280, "height": 800})
                    page.route("**/localhost:5176/**", lambda route: route.abort())
                    page.route("**/cdn.jsdelivr.net/**", lambda route: route.abort())
                    page.goto(host3["url"], wait_until="domcontentloaded")
                    page.wait_for_function("() => !document.getElementById('fb-save').disabled", timeout=15000)
                    btn3 = page.locator("#btn-broll-bed")
                    self.assertTrue(btn3.is_visible())
                    page.wait_for_function(
                        "() => !!document.getElementById('review-soundscape-audio')?.getAttribute('src')",
                        timeout=10000,
                    )
                    self.assertFalse(page.evaluate("() => document.getElementById('review-soundscape-audio').muted"))
                    btn3.click()
                    page.wait_for_function("() => document.body.dataset.brollBed === 'off'", timeout=10000)
                    self.assertTrue(page.evaluate("() => document.getElementById('review-soundscape-audio').muted"))
                finally:
                    browser.close()
        finally:
            review_host.stop_host(host3)

    @unittest.skipUnless(shutil.which("ffmpeg") is not None, "ffmpeg required")
    def test_review_cli_surfaces_soundscape_preview_metadata(self) -> None:
        proj_fc = Path(self._tmp.name) / "fc_soundscape"
        (proj_fc / "edit" / "_engineering").mkdir(parents=True)
        (proj_fc / "review").mkdir(parents=True)
        subprocess.run(
            [
                "ffmpeg", "-v", "error", "-y",
                "-f", "lavfi", "-i", "color=c=#203040:s=320x180:d=1.5:r=30",
                "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo:d=1.5",
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "30",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
                str(proj_fc / "edit" / "final.mp4"),
            ],
            check=True,
        )
        (proj_fc / "edit" / "edl.json").write_text(
            json.dumps(
                {
                    "sources": {"A": "edit/final.mp4"},
                    "ranges": [{"source": "A", "start": 0.0, "end": 1.5, "beat": "01", "quote": "测试"}],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (proj_fc / "review" / "media.json").write_text(
            json.dumps({"compositeVideo": "edit/final.mp4"}), encoding="utf-8"
        )
        _write_silent_wav(proj_fc / "edit" / "_engineering" / "soundscape.wav", duration_s=1.5, sr=48000, channels=2)
        _write_silent_wav(
            proj_fc / "edit" / "_engineering" / "soundscape_sfx_only.wav", duration_s=1.5, sr=48000, channels=2
        )
        proc = subprocess.run(
            [
                sys.executable,
                str(HELPERS / "review.py"),
                str(proj_fc),
                "--final-cut",
                "--no-open",
                "--no-live",
                "--json",
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        import re as _re
        m_json = list(_re.finditer(r"(?m)^\{", proc.stdout))
        self.assertTrue(m_json, proc.stdout)
        payload = json.loads(proc.stdout[m_json[-1].start():])
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(payload["soundscape"]["bedOn"], "edit/_engineering/soundscape.wav")
        self.assertEqual(payload["soundscape"]["bedOff"], "edit/_engineering/soundscape_sfx_only.wav")


class LiveStageVideoBlackFrameGuardTests(unittest.TestCase):
    def test_catches_visibility_hidden_combined_with_autoalpha_on_video_slot(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            proj = _make_live_stage_project(
                Path(td),
                style_css=".vplate { position: absolute; inset: 0; visibility: hidden; }",
                body_html='<div class="vplate"><video class="clip" data-start="0" data-duration="4" src="assets/clip.mp4"></video></div>',
                main_js='const tl = gsap.timeline();\ntl.to(".vplate", { autoAlpha: 1, duration: 0.3 }, 0.5);',
            )
            proc = subprocess.run(
                [sys.executable, str(CHECK_LIVE_STAGE), str(proj), "--json"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
            report = json.loads(proc.stdout)
            self.assertFalse(report["ok"])
            self.assertTrue(
                any("visibility" in err.lower() and "autoalpha" in err.lower() for err in report["errors"]),
                report["errors"],
            )

    def test_catches_visibility_hidden_container_when_autoalpha_targets_video_clip(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            proj = _make_live_stage_project(
                Path(td),
                style_css=".vplate { visibility: hidden; }",
                body_html='<div class="vplate"><video class="clip" data-start="0" data-duration="4" src="assets/clip.mp4"></video></div>',
                main_js='const tl = gsap.timeline();\ntl.to("video.clip", { autoAlpha: 1, duration: 0.3 }, 0.5);',
            )
            proc = subprocess.run(
                [sys.executable, str(CHECK_LIVE_STAGE), str(proj), "--json"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
            report = json.loads(proc.stdout)
            self.assertFalse(report["ok"])

    def test_passes_clean_display_toggle_and_unrelated_autoalpha(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            proj = _make_live_stage_project(
                Path(td),
                style_css=".vplate { display: none; }\n#card { visibility: hidden; }",
                body_html=(
                    '<div class="vplate"><video class="clip" data-start="0" data-duration="4" src="assets/clip.mp4"></video></div>'
                    '<div id="card">非视频卡片</div>'
                ),
                main_js=(
                    'const tl = gsap.timeline();\n'
                    'tl.set(".vplate", { display: "block" }, 0.5);\n'
                    'tl.to("#card", { autoAlpha: 1, duration: 0.3 }, 1.0);'
                ),
            )
            proc = subprocess.run(
                [sys.executable, str(CHECK_LIVE_STAGE), str(proj), "--json"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            report = json.loads(proc.stdout)
            self.assertTrue(report["ok"], report)


class VisualQualityAnchorAndBackgroundGuardTests(unittest.TestCase):
    def test_catches_svg_anchor_label_overflowing_canvas_bounds(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            # Right-edge overflow on 1080px wide canvas with start-aligned text
            proj = _make_quality_project(
                Path(td),
                svg_body='<g id="ch01"><text x="980" y="320" font-size="64" font-family="PingFang SC">右侧超长锚点标题</text></g>',
            )
            proc = subprocess.run(
                [sys.executable, str(CHECK_VISUAL_QUALITY), str(proj), "--json"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
            report = json.loads(proc.stdout)
            self.assertFalse(report["ok"])

        with tempfile.TemporaryDirectory() as td:
            # Negative X coordinate
            proj_neg = _make_quality_project(
                Path(td),
                svg_body='<g id="ch01"><text x="-20" y="320" font-size="64" font-family="PingFang SC">越界</text></g>',
            )
            proc_neg = subprocess.run(
                [sys.executable, str(CHECK_VISUAL_QUALITY), str(proj_neg), "--json"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc_neg.returncode, 1, proc_neg.stdout + proc_neg.stderr)

        with tempfile.TemporaryDirectory() as td:
            # Properly right-aligned (`text-anchor="end"`) at x=1040 fits inside [0, 1080]
            proj_ok = _make_quality_project(
                Path(td),
                svg_body='<g id="ch01"><text x="1040" y="320" text-anchor="end" font-size="64" font-family="PingFang SC">右对齐标签</text></g>',
            )
            proc_ok = subprocess.run(
                [sys.executable, str(CHECK_VISUAL_QUALITY), str(proj_ok), "--json"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc_ok.returncode, 0, proc_ok.stdout + proc_ok.stderr)

    def test_catches_canvas_filltext_and_drawleader_out_of_bounds(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            proj_ft = _make_quality_project(
                Path(td),
                svg_body='<g id="ch01"><rect x="100" y="200" width="200" height="120" fill="#38bdf8"/></g>',
                main_js=(
                    'const tl = HF.tl;\n'
                    'tl.to("#ch01", { opacity: 1, duration: 0.5 }, 0.5);\n'
                    'tl.to("#ch01", { y: 12, duration: 0.5 }, 4.5);\n'
                    'ctx.font = "36px PingFang SC";\n'
                    'ctx.fillText("右边界溢出的画布文字", 980, 420);\n'
                ),
            )
            proc_ft = subprocess.run(
                [sys.executable, str(CHECK_VISUAL_QUALITY), str(proj_ft), "--json"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc_ft.returncode, 1, proc_ft.stdout + proc_ft.stderr)

        with tempfile.TemporaryDirectory() as td:
            proj_dl = _make_quality_project(
                Path(td),
                svg_body='<g id="ch01"><rect x="100" y="200" width="200" height="120" fill="#38bdf8"/></g>',
                main_js=(
                    'const tl = HF.tl;\n'
                    'tl.to("#ch01", { opacity: 1, duration: 0.5 }, 0.5);\n'
                    'tl.to("#ch01", { y: 12, duration: 0.5 }, 4.5);\n'
                    'drawLeader(ctx, 640, 420, 1120, 420, "越界标注");\n'
                ),
            )
            proc_dl = subprocess.run(
                [sys.executable, str(CHECK_VISUAL_QUALITY), str(proj_dl), "--json"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc_dl.returncode, 1, proc_dl.stdout + proc_dl.stderr)

        with tempfile.TemporaryDirectory() as td:
            # Clean right-aligned fillText + in-bounds drawLeader pass
            proj_ok = _make_quality_project(
                Path(td),
                svg_body='<g id="ch01"><rect x="100" y="200" width="200" height="120" fill="#38bdf8"/></g>',
                main_js=(
                    'const tl = HF.tl;\n'
                    'tl.to("#ch01", { opacity: 1, duration: 0.5 }, 0.5);\n'
                    'tl.to("#ch01", { y: 12, duration: 0.5 }, 4.5);\n'
                    'ctx.font = "32px PingFang SC";\n'
                    'ctx.textAlign = "right";\n'
                    'ctx.fillText("右对齐安全", 1040, 420);\n'
                    'drawLeader(ctx, 400, 420, 680, 420, "居中锚点");\n'
                ),
            )
            proc_ok = subprocess.run(
                [sys.executable, str(CHECK_VISUAL_QUALITY), str(proj_ok), "--json"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc_ok.returncode, 0, proc_ok.stdout + proc_ok.stderr)

    def test_honors_data_role_background_decorative_elements_with_zero_false_positives(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            proj = _make_quality_project(
                Path(td),
                svg_body=(
                    '<g data-role="background">\n'
                    '  <circle cx="120" cy="1550" r="180" fill="#1e293b"/>\n'
                    '  <rect x="0" y="1600" width="500" height="320" fill="#0f172a"/>\n'
                    '  <text x="1020" y="1880" font-size="14" font-family="PingFang SC">DECOR-BG</text>\n'
                    '</g>\n'
                    '<rect data-role="background" x="10" y="1450" width="300" height="200" fill="#1e293b"/>\n'
                    '<g id="ch01"><rect x="120" y="220" width="400" height="180" fill="#38bdf8"/></g>'
                ),
            )
            proc = subprocess.run(
                [sys.executable, str(CHECK_VISUAL_QUALITY), str(proj), "--json"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            report = json.loads(proc.stdout)
            self.assertTrue(report["ok"], report)
            self.assertEqual(report["errors"], [], report)


class StoryboardReviewWiringTests(unittest.TestCase):
    def test_resolve_review_and_build_mode_for_storyboard_v3_and_demo_proxies(self) -> None:
        import build_review
        import review

        with tempfile.TemporaryDirectory() as td:
            proj = Path(td) / "sb_rev"
            (proj / "edit").mkdir(parents=True)
            (proj / "timeline").mkdir(parents=True)
            (proj / "review" / "demo_proxies").mkdir(parents=True)
            (proj / "timeline" / "timeline.json").write_text(
                json.dumps(_timeline_doc(), ensure_ascii=False), encoding="utf-8"
            )
            _write_silent_wav(proj / "edit" / "audio_mix.wav", duration_s=1.5)
            (proj / "review" / "demo_proxies" / "D01.mp4").write_bytes(b"proxy-mp4")
            (proj / "storyboard.json").write_text(json.dumps({
                "version": "storyboard/3",
                "canvas": {"width": 1080, "height": 1920, "fps": 30},
                "shots": [
                    {
                        "id": "D01",
                        "kind": "screen-demo",
                        "engine": "ffmpeg-cut",
                        "startSec": 0.0,
                        "endSec": 1.5,
                        "demo": {
                            "source": "recordings/app.mp4",
                            "inSec": 0.0,
                            "outSec": 1.5,
                            "proxy": "review/demo_proxies/D01.mp4",
                        },
                    }
                ],
            }), encoding="utf-8")

            # Without composition/index.html -> final-cut
            self.assertEqual(review.resolve_review_mode(proj), "final-cut")
            self.assertEqual(build_review.resolve_build_mode(proj), "final-cut")

            # With composition/index.html -> recompose (live stage)
            (proj / "composition").mkdir(parents=True)
            (proj / "composition" / "index.html").write_text("<html></html>", encoding="utf-8")
            self.assertEqual(review.resolve_review_mode(proj), "recompose")
            self.assertEqual(build_review.resolve_build_mode(proj), "recompose")

            proc = subprocess.run(
                [sys.executable, str(BUILD_REVIEW), str(proj), "--mode", "auto", "--slices", "off", "--allow-static"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            data = json.loads((proj / "review" / "review_data.json").read_text(encoding="utf-8"))
            self.assertEqual(len(data["media"]["demoProxies"]), 1)
            self.assertEqual(data["media"]["demoProxies"][0]["id"], "D01")
            self.assertEqual(data["media"]["demoProxies"][0]["proxy"], "review/demo_proxies/D01.mp4")
            manifest_paths = {item["path"] for item in data["sourceManifest"]}
            self.assertIn("storyboard.json", manifest_paths)
            self.assertIn("review/demo_proxies/D01.mp4", manifest_paths)

    def test_template_sets_isGlobalPlaying_before_syncAltAudioState_and_check_template_proves_s11(self) -> None:
        tpl = (ROOT / "visual" / "assets" / "review-page-template.html").read_text(encoding="utf-8")
        m = __import__("re").search(r"function startGlobalPlayback\(\)\s*\{(.*?)\n\s{4}\}", tpl, __import__("re").S)
        self.assertIsNotNone(m)
        live_block = m.group(1).split("return;", 1)[0]
        self.assertIn("isGlobalPlaying = true;", live_block)
        self.assertLess(live_block.index("isGlobalPlaying = true;"), live_block.index("syncAltAudioState()"))

        import check_review_template
        self.assertIn("S11", check_review_template.PROOFS)
        prove = subprocess.run([sys.executable, str(CHECK_TEMPLATE), "--prove"], capture_output=True, text=True)
        self.assertEqual(prove.returncode, 0, prove.stdout + prove.stderr)
        self.assertIn("S11", prove.stdout)


if __name__ == "__main__":
    unittest.main()
