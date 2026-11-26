#!/usr/bin/env python3
"""Integration & protocol tests for Remotion 4 live-stage bridge & engine auto-routing."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
HELPERS = SKILL_ROOT / "helpers"
INTERNAL = HELPERS / "_internal"
for _p in (str(HELPERS), str(INTERNAL)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import build_review      # noqa: E402
import remotion_runtime  # noqa: E402
import remotion_stage    # noqa: E402
import remotion_svg_scene  # noqa: E402
import review_surface    # noqa: E402


def _have_playwright() -> bool:
    try:
        import playwright.sync_api  # noqa: F401
        return True
    except ImportError:
        return False


def _have_ready_runtime() -> bool:
    rep = remotion_runtime.inspect_runtime()
    checks = {c["name"]: c["ok"] for c in (rep.get("checks") or [])}
    return bool(checks.get("node") and not rep.get("missingPackages"))


def _write_synthetic_remotion_project(proj: Path) -> None:
    (proj / "remotion" / "src").mkdir(parents=True, exist_ok=True)
    (proj / "timeline").mkdir(parents=True, exist_ok=True)
    (proj / "remotion" / "src" / "Main.tsx").write_text(
        """import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";

export const MainComp: React.FC = () => {
  const frame = useCurrentFrame();
  const op = interpolate(frame, [0, 30], [0.4, 1], { extrapolateRight: "clamp" });
  return (
    <AbsoluteFill
      id="synthetic-canvas"
      style={{
        backgroundColor: "#141824",
        color: "#F8FAFC",
        alignItems: "center",
        justifyContent: "center",
        fontSize: 48,
        opacity: op,
      }}
    >
      <div id="frame-readout">frame:{frame}</div>
    </AbsoluteFill>
  );
};
""",
        encoding="utf-8",
    )
    (proj / "remotion" / "src" / "Root.tsx").write_text(
        """import React from "react";
import { Composition } from "remotion";
import { MainComp } from "./Main";

export const RemotionRoot: React.FC = () => (
  <Composition
    id="SyntheticMain"
    component={MainComp}
    durationInFrames={90}
    fps={30}
    width={1080}
    height={1920}
  />
);
""",
        encoding="utf-8",
    )
    (proj / "remotion" / "src" / "index.ts").write_text(
        'import { registerRoot } from "remotion";\n'
        'import { RemotionRoot } from "./Root";\n\n'
        "registerRoot(RemotionRoot);\n",
        encoding="utf-8",
    )
    (proj / "timeline" / "timeline.json").write_text(
        json.dumps(
            {
                "totalChapters": 1,
                "totalSteps": 2,
                "totalDurationMs": 3000,
                "chapters": [
                    {
                        "id": "c1",
                        "title": "开场",
                        "steps": [
                            {"id": "S01", "step": 1, "startMs": 0, "endMs": 1500, "durationMs": 1500, "caption": "第一句"},
                            {"id": "S02", "step": 2, "startMs": 1500, "endMs": 3000, "durationMs": 1500, "caption": "第二句"},
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (proj / "frame.json").write_text(
        json.dumps({"framePreset": "vertical-zine-head", "canvas": {"w": 1080, "h": 1920, "fps": 30}}),
        encoding="utf-8",
    )


class RemotionEngineRoutingAndSvgTests(unittest.TestCase):
    def test_detect_motion_engine_routes_remotion_and_frozen_hyperframes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            rem_proj = root / "rem"
            _write_synthetic_remotion_project(rem_proj)
            eng, target = remotion_stage.detect_motion_engine(rem_proj)
            self.assertEqual(eng, "remotion")
            self.assertEqual(target, (rem_proj / "remotion").resolve())

            hf_proj = root / "hf"
            (hf_proj / "composition").mkdir(parents=True)
            (hf_proj / "composition" / "index.html").write_text("<div data-composition-id='main'></div>", encoding="utf-8")
            eng2, target2 = remotion_stage.detect_motion_engine(hf_proj)
            self.assertEqual(eng2, "hyperframes")
            self.assertEqual(target2, (hf_proj / "composition").resolve())

    def test_import_svg_wraps_static_pages_into_remotion_without_composition(self):
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td) / "svg-ref"
            slides = Path(td) / "slides"
            slides.mkdir(parents=True)
            (proj / "timeline").mkdir(parents=True)
            (proj / "frame.json").write_text(json.dumps({"canvas": {"w": 1920, "h": 1080, "fps": 30}}), encoding="utf-8")
            (slides / "s01.svg").write_text(
                '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1920 1080"><rect width="1920" height="1080" fill="#111"/></svg>',
                encoding="utf-8",
            )
            res = remotion_svg_scene.import_svg_pages_to_remotion(proj, [slides], seconds_per_slide=3.0)
            self.assertTrue(res["ok"])
            self.assertFalse((proj / "composition").exists())
            self.assertTrue((proj / "remotion" / "src" / "Root.tsx").is_file())
            self.assertTrue((proj / "remotion" / "src" / "scenes" / "StaticSvgReference.tsx").is_file())
            self.assertTrue((proj / "remotion" / "public" / "assets" / "pages" / "s01.svg").is_file())
            self.assertEqual(res["totalFrames"], 90)

    def test_extract_metadata_resolves_pure_js_remotion_paths_at_module_top_level(self):
        if not _have_ready_runtime():
            self.skipTest("needs bootstrapped remotion external runtime packages")
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td).resolve()
            _write_synthetic_remotion_project(proj)
            (proj / "remotion" / "src" / "Main.tsx").write_text(
                """import React from "react";
import { AbsoluteFill } from "remotion";
import { getLength } from "@remotion/paths";

const PATH_LEN = getLength("M 0 0 L 100 0");

export const MainComp: React.FC = () => (
  <AbsoluteFill>
    <div id="path-len">{PATH_LEN}</div>
  </AbsoluteFill>
);
""",
                encoding="utf-8",
            )
            (proj / "remotion" / "src" / "Root.tsx").write_text(
                """import React, { useState } from "react";
import { Composition, delayRender } from "remotion";
import { MainComp } from "./Main";

export const RemotionRoot: React.FC = () => {
  const [handle] = useState(() => delayRender("Load fonts"));
  return (
    <Composition
      id="SyntheticMain"
      component={MainComp}
      durationInFrames={90}
      fps={30}
      width={1080}
      height={1920}
      defaultProps={{ handle }}
    />
  );
};
""",
                encoding="utf-8",
            )
            meta = remotion_stage.extract_compositions_metadata(
                proj / "remotion",
                proj / "edit" / "_engineering" / "remotion-stage",
                skip_browser=True,
            )
            self.assertTrue(meta["ok"])
            self.assertEqual(meta["primary"]["id"], "SyntheticMain")
            self.assertEqual(meta["primary"]["durationInFrames"], 90)


@unittest.skipUnless(_have_playwright(), "needs playwright")
@unittest.skipUnless(_have_ready_runtime(), "needs bootstrapped remotion external runtime")
class RemotionLiveStageBrowserProtocolTests(unittest.TestCase):
    def test_kw1_postmessage_protocol_and_review_stage_integration(self):
        from playwright.sync_api import sync_playwright

        with tempfile.TemporaryDirectory() as td:
            proj = Path(td).resolve()
            _write_synthetic_remotion_project(proj)

            # Check static contract (no project node_modules)
            proc_chk = subprocess.run(
                [sys.executable, str(INTERNAL / "check_live_stage.py"), str(proj), "--json"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc_chk.returncode, 0, proc_chk.stdout + proc_chk.stderr)

            host = None
            try:
                # Start zero-render Remotion loopback server
                info = remotion_stage.start_or_reuse_stage(proj, proj / "remotion", port=0)
                self.assertTrue(info["ok"])
                self.assertEqual(info["engine"], "remotion")
                self.assertAlmostEqual(info["duration"], 3.0, places=2)
                self.assertFalse((proj / "remotion" / "node_modules").exists())

                # Build full review page pointing at Remotion stage
                data = build_review.build_review_data(proj, proj / "edit")
                self.assertEqual(data["media"]["liveStage"]["engine"], "remotion")
                build_review.write_review_files(proj, data)
                host = review_surface.open_review(proj, open_browser=False)

                with sync_playwright() as pw:
                    browser = pw.chromium.launch()
                    try:
                        page = browser.new_page(viewport={"width": 1440, "height": 900})
                        page.goto(host["url"], wait_until="domcontentloaded")
                        page.wait_for_function(
                            "() => window.__vcLiveStage && window.__vcLiveStage.ready === true",
                            timeout=20000,
                        )
                        self.assertEqual(page.evaluate("() => document.body.dataset.stage"), "live")
                        self.assertAlmostEqual(
                            page.evaluate("() => window.__vcLiveStage.durationMs"),
                            3000.0,
                            delta=50.0,
                        )

                        # Seek to t=1.5s via bridge
                        page.evaluate("() => window.__vcLiveStage.seek(1.5)")
                        page.wait_for_timeout(300)
                        t_after_seek = page.evaluate("() => window.__vcLiveStage.currentMs")
                        self.assertAlmostEqual(t_after_seek, 1500.0, delta=120.0)
                        stage_frame = next(f for f in page.frames if "stage.html" in f.url)
                        readout = stage_frame.inner_text("#frame-readout")
                        self.assertIn("frame:45", readout)

                        # Play and wait deterministically for 200ms ticks to advance time
                        page.evaluate("() => window.__vcLiveStage.play()")
                        page.wait_for_function(
                            "(target) => Boolean(window.__vcLiveStage && window.__vcLiveStage.currentMs > target)",
                            arg=t_after_seek + 150.0,
                            timeout=5000,
                        )
                        t_during_play = page.evaluate("() => window.__vcLiveStage.currentMs")
                        self.assertGreater(t_during_play, t_after_seek + 150.0)

                        # Pause and confirm time holds steady
                        page.evaluate("() => window.__vcLiveStage.pause()")
                        page.wait_for_timeout(150)
                        t_paused_1 = page.evaluate("() => window.__vcLiveStage.currentMs")
                        page.wait_for_timeout(350)
                        t_paused_2 = page.evaluate("() => window.__vcLiveStage.currentMs")
                        self.assertAlmostEqual(t_paused_1, t_paused_2, delta=80.0)
                    finally:
                        browser.close()
            finally:
                if host is not None:
                    review_surface.review_host.stop_host(host)
                remotion_stage.stop_stage(proj)


if __name__ == "__main__":
    unittest.main()
