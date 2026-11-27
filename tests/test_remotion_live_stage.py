#!/usr/bin/env python3
"""Integration & protocol tests for Remotion 4 live-stage bridge & engine auto-routing."""
from __future__ import annotations

import http.client
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
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


def _write_synthetic_remotion_project(
    proj: Path,
    *,
    duration_frames: int = 90,
    step_duration_ms: int = 1500,
) -> None:
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
        f"""import React from "react";
import {{ Composition }} from "remotion";
import {{ MainComp }} from "./Main";

export const RemotionRoot: React.FC = () => (
  <Composition
    id="SyntheticMain"
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
    total_duration_ms = step_duration_ms * 2
    (proj / "timeline" / "timeline.json").write_text(
        json.dumps(
            {
                "totalChapters": 1,
                "totalSteps": 2,
                "totalDurationMs": total_duration_ms,
                "chapters": [
                    {
                        "id": "c1",
                        "title": "开场",
                        "steps": [
                            {"id": "S01", "step": 1, "startMs": 0, "endMs": step_duration_ms, "durationMs": step_duration_ms, "caption": "第一句"},
                            {"id": "S02", "step": 2, "startMs": step_duration_ms, "endMs": total_duration_ms, "durationMs": step_duration_ms, "caption": "第二句"},
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


class RemotionStageHttpServerTests(unittest.TestCase):
    def _start_server(self, stage_dir: Path, remotion_dir: Path):
        server = remotion_stage._StageTCPServer(
            ("127.0.0.1", 0),
            remotion_stage._make_handler(stage_dir, remotion_dir),
        )
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server, port, thread

    def test_head_requests_return_headers_without_body(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            stage_dir = root / "stage"
            rem_dir = root / "remotion"
            (rem_dir / "public").mkdir(parents=True)
            stage_dir.mkdir(parents=True)

            stage_html = "<!doctype html><html><body>stage</body></html>\n"
            stage_meta = json.dumps({"ok": True, "engine": "remotion"}) + "\n"
            pub_bytes = b"A" * 4096
            (stage_dir / "stage.html").write_text(stage_html, encoding="utf-8")
            (stage_dir / "stage-meta.json").write_text(stage_meta, encoding="utf-8")
            (rem_dir / "public" / "sample.bin").write_bytes(pub_bytes)

            server, port, thread = self._start_server(stage_dir, rem_dir)
            try:
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                try:
                    conn.request("HEAD", "/stage.html")
                    r1 = conn.getresponse()
                    b1 = r1.read()
                    self.assertEqual(r1.status, 200)
                    self.assertEqual(b1, b"")
                    self.assertIn("text/html", r1.getheader("Content-Type", ""))
                    self.assertEqual(r1.getheader("Accept-Ranges"), "bytes")
                    self.assertEqual(r1.getheader("Content-Length"), str(len(stage_html.encode("utf-8"))))

                    conn.request("HEAD", "/api/stage-meta")
                    r2 = conn.getresponse()
                    b2 = r2.read()
                    self.assertEqual(r2.status, 200)
                    self.assertEqual(b2, b"")
                    self.assertIn("application/json", r2.getheader("Content-Type", ""))
                    self.assertEqual(r2.getheader("Content-Length"), str(len(stage_meta.encode("utf-8"))))

                    conn.request("HEAD", "/public/sample.bin", headers={"Range": "bytes=0-1023"})
                    r3 = conn.getresponse()
                    b3 = r3.read()
                    self.assertEqual(r3.status, 206)
                    self.assertEqual(b3, b"")
                    self.assertEqual(r3.getheader("Content-Length"), "1024")
                    self.assertEqual(r3.getheader("Content-Range"), f"bytes 0-1023/{len(pub_bytes)}")
                    self.assertEqual(r3.getheader("Accept-Ranges"), "bytes")

                    conn.request("HEAD", "/public/sample.bin", headers={"Range": "bytes=99999-100000"})
                    r4 = conn.getresponse()
                    b4 = r4.read()
                    self.assertEqual(r4.status, 416)
                    self.assertEqual(b4, b"")

                    conn.request("HEAD", "/public/missing.bin")
                    r5 = conn.getresponse()
                    b5 = r5.read()
                    self.assertEqual(r5.status, 404)
                    self.assertEqual(b5, b"")
                finally:
                    conn.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_chunked_range_exact_bytes_and_abrupt_disconnect_keeps_server_healthy(self):
        import struct

        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            stage_dir = root / "stage"
            rem_dir = root / "remotion"
            (rem_dir / "public").mkdir(parents=True)
            stage_dir.mkdir(parents=True)
            (stage_dir / "stage.html").write_text("<html></html>", encoding="utf-8")
            (stage_dir / "stage-meta.json").write_text(json.dumps({"ok": True}), encoding="utf-8")

            # >256 KB deterministic asset (2 MB so mid-stream disconnect reliably hits write loop)
            pattern = bytes((i * 31 + 7) % 251 for i in range(256))
            payload = pattern * (2 * 1024 * 1024 // len(pattern))
            asset_path = rem_dir / "public" / "large_audio.bin"
            asset_path.write_bytes(payload)

            port = remotion_stage._pick_free_port(0)
            log_path = stage_dir / "server.log"
            with log_path.open("wb") as log_fh:
                proc = subprocess.Popen(
                    [
                        sys.executable,
                        str(INTERNAL / "remotion_stage.py"),
                        "serve",
                        "--stage-dir",
                        str(stage_dir),
                        "--remotion-dir",
                        str(rem_dir),
                        "--port",
                        str(port),
                    ],
                    stdin=subprocess.DEVNULL,
                    stdout=log_fh,
                    stderr=log_fh,
                )
            try:
                meta = None
                deadline = time.time() + 10.0
                while time.time() < deadline:
                    meta = remotion_stage.fetch_stage_meta(f"http://127.0.0.1:{port}", timeout=0.5)
                    if meta and meta.get("ok"):
                        break
                    time.sleep(0.05)
                self.assertTrue(meta and meta.get("ok"), "remotion_stage serve did not start")

                # 1) Exact Range slices on >256 KB asset
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                try:
                    for start, end in ((0, 1023), (131072, 196607)):
                        conn.request("GET", "/public/large_audio.bin", headers={"Range": f"bytes={start}-{end}"})
                        resp = conn.getresponse()
                        body = resp.read()
                        self.assertEqual(resp.status, 206)
                        self.assertEqual(resp.getheader("Content-Range"), f"bytes {start}-{end}/{len(payload)}")
                        self.assertEqual(resp.getheader("Content-Length"), str(end - start + 1))
                        self.assertEqual(body, payload[start : end + 1])
                finally:
                    conn.close()

                # 2) Abrupt mid-stream client disconnects (both 200 and 206)
                for req_hdrs in (
                    f"GET /public/large_audio.bin HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n",
                    f"GET /public/large_audio.bin HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nRange: bytes=0-{len(payload) - 1}\r\nConnection: close\r\n\r\n",
                ):
                    sock = socket.create_connection(("127.0.0.1", port), timeout=5)
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
                    sock.sendall(req_hdrs.encode("ascii"))
                    sock.recv(256)
                    sock.close()

                time.sleep(0.2)

                # 3) Server remains healthy on subsequent 200 request and server.log has no tracebacks
                conn2 = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                try:
                    conn2.request("GET", "/public/large_audio.bin")
                    resp2 = conn2.getresponse()
                    full_body = resp2.read()
                    self.assertEqual(resp2.status, 200)
                    self.assertEqual(len(full_body), len(payload))
                    self.assertEqual(full_body, payload)
                finally:
                    conn2.close()

                log_text = log_path.read_text(encoding="utf-8", errors="replace")
                self.assertNotIn("Traceback", log_text, log_text)
                self.assertNotIn("BrokenPipeError", log_text, log_text)
                self.assertNotIn("ConnectionResetError", log_text, log_text)
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=2)


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

    def test_live_playback_throttles_small_audio_drift_while_step_click_and_seek_snap_immediately(self):
        import wave
        from playwright.sync_api import sync_playwright

        def write_wav(path: Path, seconds: float = 6.0, sr: int = 16000) -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            with wave.open(str(path), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sr)
                wf.writeframes(b"\x00\x00" * int(seconds * sr))

        with tempfile.TemporaryDirectory() as td:
            proj = Path(td).resolve()
            # 6.0s (180 frames @ 30fps) so playback has room
            _write_synthetic_remotion_project(proj, duration_frames=180, step_duration_ms=3000)
            write_wav(proj / "edit" / "audio_mix.wav", seconds=6.0)
            write_wav(proj / "edit" / "_engineering" / "soundscape.wav", seconds=6.0)

            host = None
            try:
                info = remotion_stage.start_or_reuse_stage(proj, proj / "remotion", port=0)
                self.assertTrue(info["ok"])
                data = build_review.build_review_data(proj, proj / "edit")
                build_review.write_review_files(proj, data)
                host = review_surface.open_review(proj, open_browser=False)

                with sync_playwright() as pw:
                    browser = pw.chromium.launch()
                    try:
                        page = browser.new_page(viewport={"width": 1440, "height": 900})
                        wav_requests = []
                        page.on("request", lambda req: wav_requests.append(req.url) if ".wav" in req.url else None)

                        page.goto(host["url"], wait_until="domcontentloaded")
                        page.wait_for_function(
                            "() => window.__vcLiveStage && window.__vcLiveStage.ready === true"
                            " && !!document.getElementById('review-audio-alt')?.getAttribute('src')"
                            " && !!document.getElementById('review-soundscape-audio')?.getAttribute('src')",
                            timeout=20000,
                        )

                        # Start live playback via real play button (user activation)
                        page.click("#btn-global-play")
                        page.wait_for_function(
                            "() => window.__vcLiveStage.currentMs > 700"
                            " && document.getElementById('review-audio-alt').readyState >= 2"
                            " && document.getElementById('review-soundscape-audio').readyState >= 2"
                            " && !document.getElementById('review-audio-alt').paused"
                            " && !document.getElementById('review-soundscape-audio').paused",
                            timeout=10000,
                        )

                        # Introduce realistic small drift (0.20s behind live clock: < 0.35s, > old 0.12s) and wait for its own seeked event
                        page.evaluate(
                            """() => new Promise((resolve) => {
                              const alt = document.getElementById("review-audio-alt");
                              const snd = document.getElementById("review-soundscape-audio");
                              const target = Math.max(0, (window.__vcLiveStage.currentMs / 1000) - 0.20);
                              let left = 2;
                              const done = () => { if (--left === 0) resolve(); };
                              alt.addEventListener("seeked", done, { once: true });
                              snd.addEventListener("seeked", done, { once: true });
                              alt.currentTime = target;
                              snd.currentTime = target;
                            })"""
                        )

                        # Start counting heartbeat-triggered seeking & WAV requests across ~900ms (4+ 200ms ticks)
                        wav_count_before = len(wav_requests)
                        page.evaluate(
                            """() => {
                              window.__hbAltSeeks = 0;
                              window.__hbSndSeeks = 0;
                              document.getElementById("review-audio-alt").addEventListener("seeking", () => { window.__hbAltSeeks += 1; });
                              document.getElementById("review-soundscape-audio").addEventListener("seeking", () => { window.__hbSndSeeks += 1; });
                            }"""
                        )
                        page.wait_for_timeout(900)
                        hb_seeks = page.evaluate("() => ({ alt: window.__hbAltSeeks, snd: window.__hbSndSeeks })")
                        self.assertEqual(hb_seeks["alt"], 0, f"small drift triggered alt re-seeks: {hb_seeks}")
                        self.assertEqual(hb_seeks["snd"], 0, f"small drift triggered soundscape re-seeks: {hb_seeks}")
                        self.assertEqual(len(wav_requests) - wav_count_before, 0, wav_requests[wav_count_before:])

                        # Explicit step click (S02 starts at 3.0s) must snap immediately
                        page.locator('.step[data-step-id="S02"]').click()
                        page.wait_for_function(
                            "() => Math.abs((document.getElementById('review-audio-alt')?.currentTime || 0) - 3.0) <= 0.35"
                            " && Math.abs((document.getElementById('review-soundscape-audio')?.currentTime || 0) - 3.0) <= 0.35",
                            timeout=3000,
                        )

                        # Explicit timeline scrubber click at 25% (1.5s) must snap immediately
                        scrubber = page.locator("#timeline-scrubber-wrap")
                        box = scrubber.bounding_box()
                        self.assertIsNotNone(box)
                        page.mouse.click(box["x"] + box["width"] * 0.25, box["y"] + box["height"] / 2)
                        page.wait_for_function(
                            "() => Math.abs((document.getElementById('review-audio-alt')?.currentTime || 0) - 1.5) <= 0.35"
                            " && Math.abs((document.getElementById('review-soundscape-audio')?.currentTime || 0) - 1.5) <= 0.35",
                            timeout=3000,
                        )

                        # Next-screen transport button calls switchToScreen(S02, true) directly and must snap audio immediately
                        page.click("#btn-next-screen")
                        page.wait_for_function(
                            "() => Math.abs((document.getElementById('review-audio-alt')?.currentTime || 0) - 3.0) <= 0.35"
                            " && Math.abs((document.getElementById('review-soundscape-audio')?.currentTime || 0) - 3.0) <= 0.35",
                            timeout=3000,
                        )
                    finally:
                        browser.close()
            finally:
                if host is not None:
                    review_surface.review_host.stop_host(host)
                remotion_stage.stop_stage(proj)


if __name__ == "__main__":
    unittest.main()
