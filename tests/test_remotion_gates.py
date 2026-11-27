#!/usr/bin/env python3
"""Black-box tests for historical visual bugfixes and Remotion 4 deterministic gates."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
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

import check_visual_quality as vq  # noqa: E402
import deliver  # noqa: E402
import film  # noqa: E402
import remotion_runtime  # noqa: E402
import remotion_stage  # noqa: E402
import remotion_svg_scene  # noqa: E402
import render_gate  # noqa: E402
import state_fingerprint  # noqa: E402
from _edl import edl_digest  # noqa: E402

GATES_SCRIPT = INTERNAL / "remotion_gates.py"
CHECK_VISUAL_SCRIPT = HELPERS / "check_visual.py"
DELIVER_SCRIPT = HELPERS / "deliver.py"
FILM_SCRIPT = HELPERS / "film.py"


def _packages_ready() -> bool:
    rep = remotion_runtime.inspect_runtime()
    checks = {c["name"]: c["ok"] for c in (rep.get("checks") or [])}
    return bool(checks.get("node") and checks.get("runtime_packages"))


def _resolve_browser_exe() -> str | None:
    browser_bin, _ = remotion_runtime.resolve_browser_executable()
    return str(browser_bin) if browser_bin else None


def _write_remotion_project(proj: Path, *, duration_frames: int = 90) -> None:
    (proj / "remotion" / "src" / "data").mkdir(parents=True, exist_ok=True)
    (proj / "remotion" / "public").mkdir(parents=True, exist_ok=True)
    (proj / "edit").mkdir(parents=True, exist_ok=True)

    (proj / "remotion" / "package.json").write_text(
        json.dumps(
            {
                "name": "gate-synthetic-remotion",
                "version": "1.0.0",
                "private": True,
                "dependencies": {"remotion": "4.0.547", "react": "18.3.1"},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (proj / "remotion" / "tsconfig.json").write_text(
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
        )
        + "\n",
        encoding="utf-8",
    )
    (proj / "remotion" / "src" / "data" / "anchors.ts").write_text(
        """export const FPS = 30;
export const WIDTH = 1080;
export const HEIGHT = 1920;
export const TOTAL_FRAMES = 90;

export const STEPS = {
  S01: { start: 0.0, end: 1.5, dur: 1.5 },
  S02: { start: 1.5, end: 3.0, dur: 1.5 },
};
""",
        encoding="utf-8",
    )
    (proj / "remotion" / "src" / "Main.tsx").write_text(
        """import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";

export const MainComp: React.FC = () => {
  const frame = useCurrentFrame();
  const x = interpolate(frame, [0, 89], [80, 260], { extrapolateRight: "clamp" });
  return (
    <AbsoluteFill
      style={{
        backgroundColor: "#0B0F19",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <div
        style={{
          width: 480,
          height: 220,
          borderRadius: 24,
          backgroundColor: "#F8FAFC",
          color: "#0F172A",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: 48,
          fontWeight: 700,
          transform: `translateY(${x * 0.1}px)`,
        }}
      >
        FRAME {frame}
      </div>
    </AbsoluteFill>
  );
};
""",
        encoding="utf-8",
    )
    (proj / "remotion" / "src" / "Root.tsx").write_text(
        f"""import React from "react";
import {{ Composition }} from "remotion";
import {{ MainComp }} from "./Main";

export const RemotionRoot: React.FC = () => (
  <Composition
    id="GateMain"
    component={{MainComp}}
    durationInFrames={{{duration_frames}}}
    fps={{30}}
    width={{1080}}
    height={{1920}}
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
    (proj / "frame.json").write_text(
        json.dumps({"framePreset": "vertical-zine-head", "canvas": {"w": 1080, "h": 1920, "fps": 30}}),
        encoding="utf-8",
    )
    (proj / "storyboard.json").write_text(
        json.dumps(
            {
                "version": "storyboard/3",
                "canvas": {"width": 1080, "height": 1920, "fps": 30},
                "capabilities": ["motion"],
                "shots": [
                    {"id": "S01", "kind": "motion", "engine": "remotion", "startSec": 0.0, "endSec": 1.5},
                    {"id": "S02", "kind": "model", "engine": "remotion", "startSec": 1.5, "endSec": 3.0},
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )


class HistoricalBugfixTests(unittest.TestCase):
    def test_q3_safezone_accumulates_ancestor_stage_offset(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td)
            (proj / "composition").mkdir(parents=True)
            (proj / "recompose.json").write_text(
                json.dumps(
                    {
                        "canvas": {"w": 1920, "h": 1080, "fps": 30},
                        "personSlot": {"x": 0, "y": 0, "w": 500, "h": 1080},
                        "captionSafe": {"x": 0, "y": 900, "w": 1920, "h": 180},
                    }
                ),
                encoding="utf-8",
            )
            html_path = proj / "composition" / "index.html"
            # Circle at local cx=200, r=100 inside #stage (left: 500px) -> global x=600..800, clear of personSlot (0..500).
            html_path.write_text(
                """<!doctype html>
<html>
<head><style>#stage { position: absolute; left: 500px; top: 0px; width: 1420px; height: 900px; }</style></head>
<body>
  <div id="root" data-composition-id="main" data-start="0" data-duration="5">
    <div id="stage">
      <svg viewBox="0 0 1420 900" width="1420" height="900">
        <circle id="ring" cx="200" cy="400" r="100" fill="#38bdf8" />
      </svg>
    </div>
  </div>
</body>
</html>
""",
                encoding="utf-8",
            )
            rep = vq.run_checks(proj)
            q3_errs = [e for e in rep["errors"] if e["rule"] == "Q3_SAFEZONE"]
            self.assertEqual(q3_errs, [], rep)

            # Negative control: global x=20..180 genuinely overlaps personSlot (0..500) -> caught.
            html_path.write_text(
                html_path.read_text(encoding="utf-8").replace('cx="200" cy="400" r="100"', 'cx="-400" cy="400" r="80"'),
                encoding="utf-8",
            )
            bad = vq.run_checks(proj)
            self.assertTrue(any(e["rule"] == "Q3_SAFEZONE" for e in bad["errors"]), bad)

    def test_lookdev_manifest_approval_does_not_trigger_source_drift(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td)
            _write_remotion_project(proj)
            subprocess.run([sys.executable, str(FILM_SCRIPT), "lookdev", str(proj)], check=True, capture_output=True)

            before_paths = state_fingerprint.source_paths(proj)
            self.assertNotIn("lookdev/lookdev-manifest.json", before_paths)
            digest_before = state_fingerprint.source_digest(proj)

            # Build snapshot manifest and submission covering current review state
            manifest = []
            for rel, p in sorted(before_paths.items()):
                manifest.append({"path": rel, "size": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()})
            (proj / "review").mkdir(parents=True, exist_ok=True)
            (proj / "review" / "review_data.json").write_text(
                json.dumps({"snapshot": "snap-lookdev-1", "sourceManifest": manifest}),
                encoding="utf-8",
            )
            (proj / "review" / "review-submissions.json").write_text(
                json.dumps({"records": [{"snapshot": "snap-lookdev-1", "text": "ok"}]}),
                encoding="utf-8",
            )

            # Approving lookdev updates lookdev-manifest.json & lookdev-sample.json -> zero drift!
            subprocess.run(
                [sys.executable, str(FILM_SCRIPT), "lookdev", str(proj), "--approve"],
                check=True,
                capture_output=True,
            )
            digest_after = state_fingerprint.source_digest(proj)
            self.assertEqual(digest_before, digest_after)
            gate_rep = render_gate.evaluate(proj, None, False)
            self.assertTrue(gate_rep["ok"], gate_rep)


@unittest.skipUnless(_packages_ready(), "needs bootstrapped remotion external runtime packages")
class RemotionGatesTests(unittest.TestCase):
    def _run_gates(self, proj: Path, *args: str, env_extra: dict[str, str] | None = None) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        if env_extra:
            env.update(env_extra)
        return subprocess.run(
            [sys.executable, str(GATES_SCRIPT), str(proj), *args],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_gate1_typecheck_passes_and_blocks_ts_error(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td).resolve()
            _write_remotion_project(proj)
            self.assertFalse((proj / "remotion" / "node_modules").exists())

            ok = self._run_gates(proj, "--only", "typecheck", "--json")
            self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)
            self.assertTrue(json.loads(ok.stdout)["ok"])
            self.assertTrue((proj / "edit" / "_engineering" / "remotion-stage" / "tsconfig.check.json").is_file())

            # Inject TS type error
            main_tsx = proj / "remotion" / "src" / "Main.tsx"
            main_tsx.write_text(
                main_tsx.read_text(encoding="utf-8") + '\nconst brokenType: number = "bad";\n',
                encoding="utf-8",
            )
            bad = self._run_gates(proj, "--only", "typecheck", "--json")
            self.assertEqual(bad.returncode, 1, bad.stdout + bad.stderr)
            payload = json.loads(bad.stdout)
            self.assertFalse(payload["ok"])
            self.assertTrue(payload["errors"])

    def test_gate2_storyboard_sync_zero_frame_pass_and_one_frame_fail(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td).resolve()
            _write_remotion_project(proj, duration_frames=90)

            ok = self._run_gates(proj, "--only", "sync", "--json")
            self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)
            self.assertTrue(json.loads(ok.stdout)["ok"])

            # Off by 1 frame in Root.tsx -> fails
            root_tsx = proj / "remotion" / "src" / "Root.tsx"
            orig_root = root_tsx.read_text(encoding="utf-8")
            root_tsx.write_text(orig_root.replace("durationInFrames={90}", "durationInFrames={91}"), encoding="utf-8")
            bad_total = self._run_gates(proj, "--only", "sync", "--json")
            self.assertEqual(bad_total.returncode, 1, bad_total.stdout + bad_total.stderr)
            self.assertFalse(json.loads(bad_total.stdout)["ok"])

            # Restore Root.tsx, shift anchors cut-point by 1 frame (1.5s -> 1.533s = frame 46 vs 45) -> fails
            root_tsx.write_text(orig_root, encoding="utf-8")
            anchors_ts = proj / "remotion" / "src" / "data" / "anchors.ts"
            anchors_ts.write_text(
                anchors_ts.read_text(encoding="utf-8").replace("end: 1.5", "end: 1.533").replace("start: 1.5", "start: 1.533"),
                encoding="utf-8",
            )
            bad_cut = self._run_gates(proj, "--only", "sync", "--json")
            self.assertEqual(bad_cut.returncode, 1, bad_cut.stdout + bad_cut.stderr)
            self.assertFalse(json.loads(bad_cut.stdout)["ok"])

            # check_visual.py --only all delegates to remotion gates cleanly
            anchors_ts.write_text(
                anchors_ts.read_text(encoding="utf-8").replace("end: 1.533", "end: 1.5").replace("start: 1.533", "start: 1.5"),
                encoding="utf-8",
            )
            cv = subprocess.run(
                [sys.executable, str(CHECK_VISUAL_SCRIPT), str(proj), "--only", "all", "--json"],
                capture_output=True, text=True, check=False,
            )
            cv_doc = json.loads(cv.stdout)
            self.assertEqual([c["check"] for c in cv_doc["checks"]], ["live-stage", "typecheck", "sync", "quality", "screen-text"])
            by_name = {c["check"]: c for c in cv_doc["checks"]}
            self.assertTrue(by_name["typecheck"]["ok"], by_name["typecheck"])
            self.assertTrue(by_name["sync"]["ok"], by_name["sync"])
            self.assertTrue(by_name["quality"]["ok"], by_name["quality"])
            self.assertTrue(by_name["screen-text"]["ok"], by_name["screen-text"])
            if remotion_runtime.inspect_runtime().get("ok"):
                self.assertEqual(cv.returncode, 0, cv.stdout + cv.stderr)
                self.assertTrue(cv_doc["ok"])

    def test_gate3_extract_shot_stills_and_fallback_samples(self) -> None:
        browser_exe = _resolve_browser_exe()
        if not browser_exe:
            self.skipTest("needs headless browser or REMOTION_BROWSER_EXECUTABLE")
        env_extra = {"REMOTION_BROWSER_EXECUTABLE": browser_exe}

        with tempfile.TemporaryDirectory() as td:
            proj = Path(td).resolve()
            _write_remotion_project(proj, duration_frames=90)

            res = self._run_gates(proj, "--only", "stills", "--max-stills", "2", "--json", env_extra=env_extra)
            self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
            doc = json.loads(res.stdout)
            self.assertTrue(doc["ok"], doc)
            stills_dir = proj / "edit" / "_engineering" / "stills"
            manifest = json.loads((stills_dir / "manifest.json").read_text(encoding="utf-8"))
            self.assertTrue(manifest["ok"])
            self.assertEqual(len(manifest["stills"]), 2)
            for item in manifest["stills"]:
                self.assertTrue(item["ok"], item)
                self.assertTrue((proj / item["path"]).is_file())
            self.assertFalse((proj / "remotion" / "node_modules").exists())

            # Delegate check_visual --only typecheck/sync/stills
            for only in ("typecheck", "sync", "stills"):
                cv_sub = subprocess.run(
                    [sys.executable, str(CHECK_VISUAL_SCRIPT), str(proj), "--only", only, "--max-stills", "1", "--json"],
                    env={**os.environ, **env_extra},
                    capture_output=True, text=True, check=False,
                )
                self.assertEqual(cv_sub.returncode, 0, cv_sub.stdout + cv_sub.stderr)

    def test_remotion_deliver_end_to_end_with_chat_approval_and_delivery_fingerprint(self) -> None:
        browser_exe = _resolve_browser_exe()
        if not browser_exe or not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            self.skipTest("needs headless browser and ffmpeg/ffprobe")
        env_extra = {**os.environ, "REMOTION_BROWSER_EXECUTABLE": browser_exe}

        with tempfile.TemporaryDirectory() as td:
            proj = Path(td).resolve()
            _write_remotion_project(proj, duration_frames=30)
            (proj / "remotion" / "src" / "data" / "anchors.ts").write_text(
                """export const FPS = 30;
export const TOTAL_FRAMES = 30;
export const STEPS = {
  S01: { start: 0.0, end: 1.0, dur: 1.0 },
};
""",
                encoding="utf-8",
            )
            (proj / "storyboard.json").write_text(
                json.dumps(
                    {
                        "version": "storyboard/3",
                        "canvas": {"width": 1080, "height": 1920, "fps": 30},
                        "capabilities": ["motion"],
                        "shots": [
                            {"id": "S01", "kind": "motion", "engine": "remotion", "startSec": 0.0, "endSec": 1.0},
                        ],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            subprocess.run([
                "ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                "-i", "testsrc2=s=720x1280:r=30:d=1.0",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", str(proj / "edit" / "cut.mp4"),
            ], check=True)
            (proj / "edit" / "_engineering").mkdir(parents=True, exist_ok=True)
            subprocess.run([
                "ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                "-i", "sine=frequency=330:duration=1.0",
                "-ar", "48000", "-ac", "2", "-c:a", "aac", "-b:a", "192k",
                str(proj / "edit" / "_engineering" / "review_audio.m4a"),
            ], check=True)
            edl = proj / "edit" / "edl.json"
            edl.write_text(json.dumps({"ranges": [{"start": 0.0, "end": 1.0}]}), encoding="utf-8")
            (proj / "edit" / "segment_durations.json").write_text(
                json.dumps({"final": {"durations": [1.0], "total_s": 1.0, "edl_sha256": edl_digest(edl)}}),
                encoding="utf-8",
            )
            subprocess.run([sys.executable, str(FILM_SCRIPT), "lookdev", str(proj), "--approve"], check=True)
            self.assertFalse(deliver._is_pure_talking_project(proj))

            # Build minimal review_data.json, then edit a source file after review -> --approve-in-chat still permits export
            manifest = [
                {"path": rel, "size": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                for rel, p in sorted(state_fingerprint.source_paths(proj, include_review=False).items())
            ]
            (proj / "review").mkdir(parents=True, exist_ok=True)
            (proj / "review" / "review_data.json").write_text(
                json.dumps({"snapshot": "snap-rem-1", "sourceManifest": manifest}),
                encoding="utf-8",
            )
            main_tsx = proj / "remotion" / "src" / "Main.tsx"
            main_tsx.write_text(main_tsx.read_text(encoding="utf-8") + "\n// tweaked after review\n", encoding="utf-8")

            proc = subprocess.run(
                [
                    sys.executable, str(DELIVER_SCRIPT), str(proj),
                    "--render", "--approve-in-chat", "--approval-note", "微调后直接导出", "--json",
                ],
                env=env_extra,
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            report = json.loads((proj / "成品" / f"{proj.name}_核验报告.json").read_text(encoding="utf-8"))
            self.assertTrue(report["ok"], report)
            self.assertEqual(report["segment_splice"]["engine_counts"].get("remotion"), 1)
            self.assertTrue((proj / "remotion" / "_render" / "visuals.mp4").is_file())
            self.assertFalse((proj / "remotion" / "node_modules").exists())
            self.assertTrue((proj / "成品" / "delivery.json").is_file())
            verify_fp = subprocess.run(
                [sys.executable, str(INTERNAL / "state_fingerprint.py"), "verify", str(proj)],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(verify_fp.returncode, 0, verify_fp.stdout + verify_fp.stderr)

    def test_omitted_engine_routing_tsconfig_aliases_and_svg_collisions(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            # 1) Omitted-engine routing: remotion project -> remotion; legacy composition -> hyperframes
            rem_proj = root / "rem_proj"
            _write_remotion_project(rem_proj)
            motion_shot = {"id": "M1", "kind": "motion", "startSec": 0.0, "endSec": 1.0}
            self.assertEqual(deliver._shot_engine(motion_shot, deliver._default_motion_engine(rem_proj)), "remotion")
            self.assertEqual(film._resolve_shot_engine(motion_shot, project=rem_proj), "remotion")

            hf_proj = root / "hf_proj"
            (hf_proj / "composition").mkdir(parents=True)
            (hf_proj / "composition" / "index.html").write_text("<div data-composition-id='main'></div>", encoding="utf-8")
            self.assertEqual(deliver._shot_engine(motion_shot, deliver._default_motion_engine(hf_proj)), "hyperframes")
            self.assertEqual(film._resolve_shot_engine(motion_shot, project=hf_proj), "hyperframes")

            # 2) Custom tsconfig baseUrl + paths alias preserved in tsconfig.check.json
            (rem_proj / "remotion" / "tsconfig.json").write_text(
                json.dumps({
                    "compilerOptions": {
                        "baseUrl": ".",
                        "paths": {"@/*": ["src/*"]},
                        "strict": True,
                    }
                }),
                encoding="utf-8",
            )
            (rem_proj / "remotion" / "src" / "Root.tsx").write_text(
                'import React from "react";\nimport { Composition } from "remotion";\n'
                'import { MainComp } from "@/Main";\n'
                'export const RemotionRoot: React.FC = () => (\n'
                '  <Composition id="GateMain" component={MainComp} durationInFrames={90} fps={30} width={1080} height={1920} />\n'
                ');\n',
                encoding="utf-8",
            )
            tc = self._run_gates(rem_proj, "--only", "typecheck", "--json")
            self.assertEqual(tc.returncode, 0, tc.stdout + tc.stderr)

            # 3) explicit_remotion missing Root.tsx falls back instead of blindly returning "remotion"
            self.assertEqual(remotion_stage.detect_motion_engine(hf_proj, explicit_remotion=str(root / "nonexistent"))[0], "hyperframes")

            # 4) SVG importer disambiguates colliding stems & asset basenames and wraps ET.ParseError
            svg_proj = root / "svg_proj"
            d1, d2 = root / "s1", root / "s2"
            (d1 / "a").mkdir(parents=True)
            (d1 / "b").mkdir(parents=True)
            d2.mkdir(parents=True)
            (d1 / "a" / "logo.png").write_bytes(b"pngA")
            (d1 / "b" / "logo.png").write_bytes(b"pngB")
            (d1 / "slide.svg").write_text(
                '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
                '<image href="a/logo.png"/><image href="b/logo.png"/></svg>',
                encoding="utf-8",
            )
            (d2 / "slide.svg").write_text(
                '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><rect width="10" height="10"/></svg>',
                encoding="utf-8",
            )
            imp_res = remotion_svg_scene.import_svg_pages_to_remotion(svg_proj, [d1, d2])
            self.assertEqual(len({s["key"] for s in imp_res["slides"]}), 2)
            copied_logos = list((svg_proj / "remotion" / "public" / "assets" / "pages" / "slide").glob("logo*.png"))
            self.assertEqual(len(copied_logos), 2)

            bad_svg = root / "bad.svg"
            bad_svg.write_text("<svg><broken", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "bad\\.svg"):
                remotion_svg_scene.import_svg_pages_to_remotion(root / "svg_err", [bad_svg])


if __name__ == "__main__":
    unittest.main()
