#!/usr/bin/env python3
"""Remotion 4 engine detection, zero-render live-stage bundling, and loopback server.

Implements the `{kw: 1}` postMessage live-stage bridge over `@remotion/player` so
creators can scrub, jump chapters, toggle audio mix / soundscape, and submit
annotations in real time with zero frame rendering during review.

All Node/React/esbuild/Remotion dependencies are loaded from the External Runtime
Shell (`remotion_runtime.py`); zero `node_modules` ever enter a project directory.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import http.server
import json
import os
import re
import signal
import socket
import socketserver
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import unquote, urlparse

HELPERS_DIR = Path(__file__).resolve().parents[1]
INTERNAL_DIR = Path(__file__).resolve().parent
for _p in (str(HELPERS_DIR), str(INTERNAL_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import remotion_runtime  # noqa: E402

STAGE_REL = "edit/_engineering/remotion-stage"
ROOT_CANDIDATES = ("Root.tsx", "Root.ts", "Root.jsx", "Root.js")
ENTRY_CANDIDATES = ("index.ts", "index.tsx", "index.js", "index.jsx")
SKIP_HASH_DIRS = {"node_modules", "_render", "renders", "out", "build", ".git", ".cache"}
_SPAWNED_PROCS: dict[int, subprocess.Popen] = {}


def _read_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else None
    except (OSError, ValueError):
        return None


def find_root_file(remotion_dir: Path) -> Path | None:
    src = remotion_dir / "src"
    if not src.is_dir():
        return None
    for name in ROOT_CANDIDATES:
        cand = src / name
        if cand.is_file():
            return cand
    return None


def find_entry_file(remotion_dir: Path) -> Path | None:
    src = remotion_dir / "src"
    if not src.is_dir():
        return None
    for name in ENTRY_CANDIDATES:
        cand = src / name
        if cand.is_file():
            return cand
    return None


def detect_motion_engine(
    project: Path,
    *,
    explicit_composition: str | None = None,
    explicit_remotion: str | None = None,
) -> tuple[str | None, Path | None]:
    """Deterministic engine auto-detection.

    Priority:
      1. Explicit `remotion_dir` or `<project>/remotion/src/Root.*` -> ("remotion", dir)
      2. `storyboard.json` or `recompose.json` `remotionDir` -> ("remotion", dir)
      3. Explicit `composition` or `recompose.json` `composition` / `<project>/composition/index.html` -> ("hyperframes", dir)
      4. Otherwise -> (None, None)
    """
    root = Path(project).expanduser().resolve()
    if root.name in {"edit", "remotion", "composition"} and root.parent.is_dir():
        root = root.parent

    if explicit_remotion:
        cand = Path(explicit_remotion).expanduser()
        cand = (cand if cand.is_absolute() else (root / cand)).resolve()
        if find_root_file(cand) is not None:
            return "remotion", cand

    default_remotion = root / "remotion"
    if find_root_file(default_remotion) is not None:
        return "remotion", default_remotion.resolve()

    for rel in ("storyboard.json", "edit/storyboard.json", "recompose.json"):
        doc = _read_json(root / rel)
        if isinstance(doc, dict) and isinstance(doc.get("remotionDir"), str) and doc["remotionDir"].strip():
            cand = Path(doc["remotionDir"].strip()).expanduser()
            cand = (cand if cand.is_absolute() else (root / cand)).resolve()
            if find_root_file(cand) is not None:
                return "remotion", cand

    if explicit_composition:
        comp = Path(explicit_composition).expanduser()
        comp = (comp if comp.is_absolute() else (root / comp)).resolve()
        if (comp / "index.html").is_file():
            return "hyperframes", comp

    if (root / "composition" / "index.html").is_file():
        return "hyperframes", (root / "composition").resolve()

    rc = _read_json(root / "recompose.json")
    if isinstance(rc, dict) and isinstance(rc.get("composition"), str) and rc["composition"].strip():
        cand = Path(rc["composition"].strip()).expanduser()
        cand = (cand if cand.is_absolute() else (root / cand)).resolve()
        if (cand / "index.html").is_file():
            return "hyperframes", cand

    return None, None


def remotion_source_hash(remotion_dir: Path) -> str:
    """Compute SHA-256 over Remotion source, config, and public asset metadata."""
    h = hashlib.sha256()
    remotion_dir = remotion_dir.resolve()
    for p in sorted(remotion_dir.rglob("*")):
        if not p.is_file():
            continue
        rel_parts = p.relative_to(remotion_dir).parts
        if any(part in SKIP_HASH_DIRS for part in rel_parts):
            continue
        if p.name.endswith(".sources.json"):
            continue
        rel = p.relative_to(remotion_dir).as_posix()
        h.update(rel.encode("utf-8"))
        st = p.stat()
        h.update(f":{st.st_size}:{st.st_mtime_ns}\n".encode("ascii"))
        if rel_parts[0] == "src" or p.name in ("package.json", "tsconfig.json", "remotion.config.ts"):
            h.update(p.read_bytes())
    return h.hexdigest()


def _node_bin(runtime_home: Path) -> str:
    found = remotion_runtime.runtime_env(runtime_home).get("PATH", "")
    for d in found.split(os.pathsep):
        cand = Path(d) / ("node.exe" if os.name == "nt" else "node")
        if cand.is_file():
            return str(cand)
    import shutil
    sys_node = shutil.which("node")
    if not sys_node:
        raise RuntimeError("node >= 22 not found on PATH")
    return sys_node


_EXTRACT_META_JS = r"""
const esbuild = require(require.resolve("esbuild", { paths: [process.env.VC_NM] }));
const fs = require("fs");
const path = require("path");

async function main() {
  const rootFile = path.resolve(process.argv[2]);
  const outJs = path.resolve(process.argv[3]);
  const shimDir = path.dirname(outJs);
  const mockRemotion = path.join(shimDir, "_meta_mock_remotion.js");

  fs.writeFileSync(mockRemotion, `
    const React = require("react");
    globalThis.__VC_COMPOSITIONS__ = [];
    exports.Composition = function Composition(props) {
      globalThis.__VC_COMPOSITIONS__.push({
        id: String(props.id || "main"),
        width: Number(props.width || 1920),
        height: Number(props.height || 1080),
        fps: Number(props.fps || 30),
        durationInFrames: Number(props.durationInFrames || 0),
        defaultProps: props.defaultProps || {},
      });
      return null;
    };
    exports.Still = function Still() { return null; };
    exports.Folder = function Folder(props) { return props.children || null; };
    exports.Sequence = function Sequence(props) { return props.children || null; };
    exports.Series = Object.assign(function Series(props) { return props.children || null; }, {
      Sequence: function SeriesSequence(props) { return props.children || null; },
    });
    exports.Loop = function Loop(props) { return props.children || null; };
    exports.Freeze = function Freeze(props) { return props.children || null; };
    exports.AbsoluteFill = function AbsoluteFill(props) { return props.children || null; };
    exports.Img = function Img() { return null; };
    exports.Audio = function Audio() { return null; };
    exports.Video = function Video() { return null; };
    exports.OffthreadVideo = function OffthreadVideo() { return null; };
    exports.delayRender = function delayRender() { return 1; };
    exports.continueRender = function continueRender() {};
    exports.cancelRender = function cancelRender() {};
    exports.staticFile = function staticFile(p) { return "/public/" + String(p || "").replace(/^\\/+/, ""); };
    exports.useCurrentFrame = function useCurrentFrame() { return 0; };
    exports.useCurrentScale = function useCurrentScale() { return 1; };
    exports.useVideoConfig = function useVideoConfig() { return { width: 1920, height: 1080, fps: 30, durationInFrames: 300, id: "main" }; };
    exports.interpolate = function interpolate(v) { return v; };
    exports.interpolateColors = function interpolateColors(_v, _input, output) { return (Array.isArray(output) && output[0]) || "#000000"; };
    exports.spring = function spring() { return 1; };
    exports.measureSpring = function measureSpring() { return 30; };
    exports.Easing = new Proxy({}, { get: () => () => (t) => t });
    exports.random = function random() { return 0.5; };
    exports.registerRoot = function registerRoot() {};
    module.exports = exports;
  `, "utf8");

  const assetPlugin = {
    name: "vc-meta-ignore",
    setup(build) {
      build.onResolve({ filter: /^remotion$/ }, () => ({ path: mockRemotion }));
      build.onResolve(
        { filter: /^@remotion\/(player|cli|studio|renderer|bundler|lambda|cloudrun)(\/|$)/ },
        () => ({ path: "virtual-noop", namespace: "vc-noop" }),
      );
      build.onLoad({ filter: /.*/, namespace: "vc-noop" }, () => ({
        contents: "module.exports = new Proxy({}, { get: () => () => null });",
        loader: "js",
      }));
    },
  };

  await esbuild.build({
    entryPoints: [rootFile],
    outfile: outJs,
    bundle: true,
    platform: "node",
    format: "cjs",
    external: ["react", "react-dom", "react-dom/server", "react/jsx-runtime", "react/jsx-dev-runtime"],
    nodePaths: [process.env.VC_NM],
    plugins: [assetPlugin],
    loader: {
      ".css": "empty",
      ".scss": "empty",
      ".png": "dataurl",
      ".jpg": "dataurl",
      ".jpeg": "dataurl",
      ".webp": "dataurl",
      ".svg": "dataurl",
      ".woff": "empty",
      ".woff2": "empty",
      ".ttf": "empty",
      ".otf": "empty",
      ".mp3": "empty",
      ".wav": "empty",
      ".m4a": "empty",
      ".mp4": "empty",
    },
    logLevel: "silent",
  });

  if (typeof globalThis.window === "undefined") globalThis.window = {};
  if (typeof globalThis.document === "undefined") globalThis.document = {};
  const mod = require(outJs);
  const React = require(require.resolve("react", { paths: [process.env.VC_NM] }));
  const ReactDOMServer = require(require.resolve("react-dom/server", { paths: [process.env.VC_NM] }));
  const RootComp = mod.RemotionRoot || mod.default || Object.values(mod).find((v) => typeof v === "function");
  if (!RootComp) {
    throw new Error("Could not find exported RemotionRoot / default component in " + rootFile);
  }
  globalThis.__VC_COMPOSITIONS__ = [];
  ReactDOMServer.renderToStaticMarkup(React.createElement(RootComp));
  const comps = globalThis.__VC_COMPOSITIONS__ || [];
  if (!comps.length) {
    throw new Error("No <Composition> discovered while evaluating " + rootFile);
  }
  const primary = comps[0];
  primary.duration = primary.fps > 0 ? Number((primary.durationInFrames / primary.fps).toFixed(6)) : 0;
  process.stdout.write(JSON.stringify({ ok: true, primary, compositions: comps }));
}

main().catch((err) => {
  process.stderr.write(String(err && err.stack || err) + "\n");
  process.exit(1);
});
"""


def extract_compositions_metadata(
    remotion_dir: Path,
    work_dir: Path,
    runtime_home: Path | None = None,
    *,
    skip_browser: bool = False,
) -> dict:
    """Evaluate RemotionRoot in Node/esbuild to extract authoritative composition metadata."""
    home = remotion_runtime.ensure_runtime(runtime_home, auto_setup=True, skip_browser=skip_browser)
    root_file = find_root_file(remotion_dir)
    if root_file is None:
        raise RuntimeError(f"Missing src/Root.tsx under {remotion_dir}")
    work_dir.mkdir(parents=True, exist_ok=True)
    script_path = work_dir / "_extract_meta.cjs"
    out_cjs = work_dir / "_root_meta.cjs"
    script_path.write_text(_EXTRACT_META_JS, encoding="utf-8")

    env = remotion_runtime.runtime_env(home)
    env["VC_NM"] = str(home / "node_modules")
    proc = subprocess.run(
        [_node_bin(home), str(script_path), str(root_file), str(out_cjs)],
        cwd=str(remotion_dir),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"Failed to extract Remotion composition metadata: {(proc.stderr or proc.stdout)[-800:]}")
    try:
        payload = json.loads(proc.stdout)
    except ValueError as exc:
        raise RuntimeError(f"Invalid metadata JSON from Root.tsx: {exc} ({proc.stdout[:200]})") from exc
    if not payload.get("ok") or not payload.get("primary"):
        raise RuntimeError(f"Metadata extraction did not return primary composition: {payload}")
    return payload


_SHIM_REMOTION_TSX = r"""import * as RealRemotion from "__REAL_REMOTION__";
import React, { useEffect, useRef, useState } from "react";
import { Player, type PlayerRef } from "__REMOTION_PLAYER__";

export * from "__REAL_REMOTION__";

export const delayRender = (_label?: string): number => 1;
export const continueRender = (_handle: number): void => {};
export const cancelRender = (_err: unknown): void => {};

export const staticFile = (path: string): string => {
  const clean = String(path || "").replace(/^\/+/, "");
  return "/public/" + clean;
};

type CompProps = {
  id: string;
  component: React.ComponentType<any>;
  durationInFrames: number;
  fps: number;
  width: number;
  height: number;
  defaultProps?: Record<string, any>;
};

let mountedPrimary = false;

export const Composition: React.FC<CompProps> = ({
  id,
  component,
  durationInFrames,
  fps,
  width,
  height,
  defaultProps,
}) => {
  const playerRef = useRef<PlayerRef | null>(null);
  const [playbackRate, setPlaybackRate] = useState<number>(1);
  const [isPrimary] = useState<boolean>(() => {
    if (mountedPrimary) return false;
    mountedPrimary = true;
    return true;
  });

  useEffect(() => {
    if (!isPrimary) return;
    const duration = fps > 0 ? durationInFrames / fps : 0;
    let tickTimer: ReturnType<typeof setInterval> | null = null;
    let playing = false;

    const currentSec = () => {
      const p = playerRef.current;
      if (!p || typeof p.getCurrentFrame !== "function") return 0;
      const fr = p.getCurrentFrame();
      return fps > 0 ? Math.max(0, Math.min(duration, fr / fps)) : 0;
    };

    const post = (msg: Record<string, any>) => {
      const payload = { kw: 1, duration, fps, width, height, id, hasTimeline: true, ...msg };
      if (window.parent && window.parent !== window) {
        try { window.parent.postMessage(payload, "*"); } catch {}
      }
      window.dispatchEvent(new CustomEvent("vc-remotion-stage-msg", { detail: payload }));
    };

    const stopTick = () => {
      if (tickTimer !== null) {
        clearInterval(tickTimer);
        tickTimer = null;
      }
    };

    const startTick = () => {
      stopTick();
      tickTimer = setInterval(() => {
        const p = playerRef.current;
        const isPlaying = p && typeof p.isPlaying === "function" ? p.isPlaying() : playing;
        playing = isPlaying;
        post({ type: "time", t: currentSec(), paused: !isPlaying });
        if (!isPlaying) stopTick();
      }, 200);
    };

    const seekSec = (sec: number) => {
      const p = playerRef.current;
      if (!p) return;
      stopTick();
      playing = false;
      try { p.pause(); } catch {}
      const targetFrame = Math.max(0, Math.min(durationInFrames - 1, Math.round((Number(sec) || 0) * fps)));
      try { p.seekTo(targetFrame); } catch {}
      const syncedT = fps > 0 ? targetFrame / fps : 0;
      post({ type: "time", t: syncedT, paused: true });
    };

    const hasUserActivation = () => {
      try {
        const ua = typeof navigator !== "undefined" ? (navigator as any).userActivation : null;
        return ua ? Boolean(ua.hasBeenActive) : false;
      } catch {
        return false;
      }
    };

    const playNow = () => {
      const p = playerRef.current;
      if (!p) return;
      if (!hasUserActivation() && typeof (p as any).mute === "function") {
        try { (p as any).mute(); } catch {}
      }
      playing = true;
      try { p.play(); } catch {}
      post({ type: "time", t: currentSec(), paused: false });
      post({ type: "state", paused: false });
      startTick();
    };

    const pauseNow = () => {
      const p = playerRef.current;
      if (!p) return;
      playing = false;
      try { p.pause(); } catch {}
      stopTick();
      post({ type: "time", t: currentSec(), paused: true });
      post({ type: "state", paused: true });
    };

    (window as any).__vcRemotionStage = {
      id,
      fps,
      width,
      height,
      durationInFrames,
      duration,
      getCurrentTime: currentSec,
      isPaused: () => !playing,
      seek: seekSec,
      play: playNow,
      pause: pauseNow,
    };

    const pInst = playerRef.current;
    const onPlay = () => {
      playing = true;
      post({ type: "time", t: currentSec(), paused: false });
      post({ type: "state", paused: false });
      startTick();
    };
    const onPause = () => {
      playing = false;
      stopTick();
      post({ type: "time", t: currentSec(), paused: true });
      post({ type: "state", paused: true });
    };
    const onEnded = () => {
      playing = false;
      stopTick();
      post({ type: "time", t: duration, paused: true });
      post({ type: "state", paused: true });
      post({ type: "ended", t: duration, paused: true });
    };
    if (pInst && typeof pInst.addEventListener === "function") {
      pInst.addEventListener("play", onPlay as any);
      pInst.addEventListener("pause", onPause as any);
      pInst.addEventListener("ended", onEnded as any);
    }

    const onMessage = (event: MessageEvent) => {
      if (window.parent && window.parent !== window && event.source !== window.parent) return;
      const data = event.data;
      if (!data || data.kw !== 1) return;
      switch (data.type) {
        case "hello":
          post({ type: "ready", t: currentSec(), paused: !playing });
          break;
        case "seek":
          if (typeof data.t === "number") seekSec(data.t);
          break;
        case "play":
          playNow();
          break;
        case "pause":
          pauseNow();
          break;
        case "rate":
          if (typeof data.rate === "number" && data.rate > 0) {
            setPlaybackRate(data.rate);
          }
          break;
        case "mute": {
          const p = playerRef.current;
          if (p) {
            try {
              if (data.muted) p.mute();
              else if (hasUserActivation()) p.unmute();
            } catch {}
          }
          break;
        }
        default:
          break;
      }
    };

    window.addEventListener("message", onMessage, false);
    document.documentElement.dataset.remotionStage = "ready";
    post({ type: "ready", t: currentSec(), paused: true });

    return () => {
      stopTick();
      window.removeEventListener("message", onMessage, false);
      if (pInst && typeof pInst.removeEventListener === "function") {
        pInst.removeEventListener("play", onPlay as any);
        pInst.removeEventListener("pause", onPause as any);
        pInst.removeEventListener("ended", onEnded as any);
      }
    };
  }, [durationInFrames, fps, height, id, isPrimary, width]);

  if (!isPrimary) return null;

  return (
    <div
      id="remotion-stage-root"
      data-composition-id={id}
      style={{
        width: "100vw",
        height: "100vh",
        background: "#000",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        overflow: "hidden",
      }}
    >
      <Player
        ref={playerRef}
        component={component}
        durationInFrames={durationInFrames}
        fps={fps}
        compositionWidth={width}
        compositionHeight={height}
        inputProps={defaultProps || {}}
        playbackRate={playbackRate}
        controls={false}
        loop={false}
        autoPlay={false}
        clickToPlay={false}
        initiallyMuted
        acknowledgeRemotionLicense
        style={{
          width: "100%",
          height: "100%",
          maxWidth: "100%",
          maxHeight: "100%",
        }}
      />
    </div>
  );
};
"""


_BUNDLE_STAGE_JS = r"""
const esbuild = require(require.resolve("esbuild", { paths: [process.env.VC_NM] }));
const path = require("path");

async function main() {
  const entryFile = path.resolve(process.argv[2]);
  const outJs = path.resolve(process.argv[3]);
  const rootFile = path.resolve(process.argv[4]);
  const shimFile = path.resolve(process.argv[5]);
  const remotionReal = require.resolve("remotion", { paths: [process.env.VC_NM] });
  const playerReal = require.resolve("@remotion/player", { paths: [process.env.VC_NM] });

  const shimPlugin = {
    name: "vc-remotion-stage-shim",
    setup(build) {
      build.onResolve({ filter: /^remotion$/ }, (args) => {
        if (path.resolve(args.importer) === rootFile) {
          return { path: shimFile };
        }
        return { path: remotionReal };
      });
      build.onResolve({ filter: /^@remotion\/player$/ }, () => ({ path: playerReal }));
    },
  };

  await esbuild.build({
    entryPoints: [entryFile],
    outfile: outJs,
    bundle: true,
    format: "esm",
    platform: "browser",
    target: ["es2022"],
    nodePaths: [process.env.VC_NM],
    define: {
      "process.env.NODE_ENV": "\"production\"",
      "global": "window",
    },
    plugins: [shimPlugin],
    loader: {
      ".css": "css",
      ".png": "dataurl",
      ".jpg": "dataurl",
      ".jpeg": "dataurl",
      ".webp": "dataurl",
      ".svg": "dataurl",
      ".gif": "dataurl",
      ".woff": "dataurl",
      ".woff2": "dataurl",
    },
    logLevel: "warning",
  });
}

main().catch((err) => {
  process.stderr.write(String(err && err.stack || err) + "\n");
  process.exit(1);
});
"""


def bundle_stage(
    project: Path,
    remotion_dir: Path,
    out_dir: Path | None = None,
    *,
    runtime_home: Path | None = None,
) -> dict:
    """Bundle `<remotion_dir>/src/Root.tsx` into a fast browser stage under `edit/_engineering/`."""
    project = project.resolve()
    remotion_dir = remotion_dir.resolve()
    out_dir = (out_dir or (project / STAGE_REL)).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    home = remotion_runtime.ensure_runtime(runtime_home, auto_setup=True, skip_browser=True)
    root_file = find_root_file(remotion_dir)
    if root_file is None:
        raise RuntimeError(f"Missing src/Root.tsx under {remotion_dir}")

    meta = extract_compositions_metadata(remotion_dir, out_dir, home, skip_browser=True)
    primary = meta["primary"]

    nm = home / "node_modules"
    real_remotion = (nm / "remotion").resolve()
    real_player = (nm / "@remotion" / "player").resolve()

    shim_file = out_dir / "stage-remotion-shim.tsx"
    shim_src = (
        _SHIM_REMOTION_TSX
        .replace("__REAL_REMOTION__", str(real_remotion).replace("\\", "/"))
        .replace("__REMOTION_PLAYER__", str(real_player).replace("\\", "/"))
    )
    shim_file.write_text(shim_src, encoding="utf-8")

    root_import = "./" + os.path.relpath(root_file, out_dir).replace(os.sep, "/")
    for ext in (".tsx", ".ts", ".jsx", ".js"):
        if root_import.endswith(ext):
            root_import = root_import[: -len(ext)]
            break
    # Locate optional Root export name
    root_text = root_file.read_text(encoding="utf-8", errors="ignore")
    has_named_root = bool(re.search(r"\bexport\s+(?:const|function|class)\s+RemotionRoot\b", root_text))
    export_expr = "RemotionRoot" if has_named_root else "defaultRoot"
    import_stmt = (
        f'import {{ RemotionRoot }} from "{root_import}";'
        if has_named_root
        else f'import defaultRoot from "{root_import}";'
    )

    entry_file = out_dir / "stage-entry.tsx"
    entry_file.write_text(
        f"""import React from "react";
import {{ createRoot }} from "react-dom/client";
{import_stmt}

const mountEl = document.getElementById("root")!;
createRoot(mountEl).render(React.createElement({export_expr}));
""",
        encoding="utf-8",
    )

    bundler_script = out_dir / "_bundle_stage.cjs"
    bundler_script.write_text(_BUNDLE_STAGE_JS, encoding="utf-8")
    out_js = out_dir / "stage.js"
    out_css = out_dir / "stage.css"
    out_css.unlink(missing_ok=True)

    env = remotion_runtime.runtime_env(home)
    env["VC_NM"] = str(nm)
    proc = subprocess.run(
        [
            _node_bin(home),
            str(bundler_script),
            str(entry_file),
            str(out_js),
            str(root_file),
            str(shim_file),
        ],
        cwd=str(remotion_dir),
        env=env,
        capture_output=True,
        text=True,
        timeout=45,
    )
    if proc.returncode != 0 or not out_js.is_file():
        raise RuntimeError(f"Remotion live-stage esbuild bundle failed:\n{(proc.stderr or proc.stdout)[-1200:]}")

    public_dir = remotion_dir / "public"
    static_files = []
    if public_dir.is_dir():
        for pf in sorted(public_dir.rglob("*")):
            if pf.is_file() and not pf.name.startswith("."):
                rel_p = pf.relative_to(public_dir).as_posix()
                static_files.append({"name": rel_p, "src": f"/public/{rel_p}"})
    static_files_json = json.dumps(static_files, ensure_ascii=False)

    css_link = '  <link rel="stylesheet" href="/stage.css" />\n' if out_css.is_file() else ""
    stage_html = (
        "<!doctype html>\n"
        "<html lang=\"en\">\n"
        "<head>\n"
        "  <meta charset=\"UTF-8\" />\n"
        "  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />\n"
        f"  <title>{html.escape(str(primary.get('id') or 'Remotion Stage'))}</title>\n"
        "  <style>html, body, #root { margin: 0; padding: 0; width: 100%; height: 100%; background: #000; overflow: hidden; }</style>\n"
        f"{css_link}"
        "</head>\n"
        "<body>\n"
        "  <div id=\"root\"></div>\n"
        f"  <script>window.remotion_staticBase = '/public'; window.remotion_staticFiles = {static_files_json};</script>\n"
        "  <script type=\"module\" src=\"/stage.js\"></script>\n"
        "</body>\n"
        "</html>\n"
    )
    (out_dir / "stage.html").write_text(stage_html, encoding="utf-8")

    src_hash = remotion_source_hash(remotion_dir)
    stage_meta = {
        "ok": True,
        "engine": "remotion",
        "projectRoot": str(project),
        "remotionRoot": str(remotion_dir),
        "id": primary["id"],
        "fps": primary["fps"],
        "width": primary["width"],
        "height": primary["height"],
        "durationInFrames": primary["durationInFrames"],
        "duration": primary["duration"],
        "sourceHash": src_hash,
        "bundleBytes": out_js.stat().st_size,
    }
    (out_dir / "stage-meta.json").write_text(
        json.dumps(stage_meta, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return stage_meta


class _StageTCPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def _make_handler(stage_dir: Path, remotion_dir: Path):
    public_dir = (remotion_dir / "public").resolve()
    stage_root = stage_dir.resolve()
    meta_file = stage_root / "stage-meta.json"

    class Handler(http.server.SimpleHTTPRequestHandler):
        def end_headers(self) -> None:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def log_message(self, format: str, *args) -> None:
            pass

        def do_GET(self) -> None:
            req_path = unquote(urlparse(self.path).path)
            if req_path == "/api/stage-meta":
                if not meta_file.is_file():
                    self.send_error(404, "stage-meta.json not found")
                    return
                raw = meta_file.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
                return

            if req_path.startswith("/public/"):
                rel = req_path[len("/public/"):].lstrip("/")
                target = (public_dir / rel).resolve()
                if not target.is_relative_to(public_dir) or not target.is_file():
                    self.send_error(404, f"Public asset not found: {rel}")
                    return
                self._serve_file_with_range(target)
                return

            if req_path in ("/", "/index.html"):
                rel = "stage.html"
            else:
                rel = req_path.lstrip("/")
            target = (stage_root / rel).resolve()
            if not target.is_relative_to(stage_root) or not target.is_file():
                pub_target = (public_dir / rel).resolve()
                if public_dir.is_dir() and pub_target.is_relative_to(public_dir) and pub_target.is_file():
                    self._serve_file_with_range(pub_target)
                    return
                self.send_error(404, f"Not found: {req_path}")
                return
            self._serve_file_with_range(target)

        def _serve_file_with_range(self, target: Path) -> None:
            ctype = self.guess_type(str(target))
            if target.suffix == ".js":
                ctype = "application/javascript; charset=utf-8"
            elif target.suffix == ".css":
                ctype = "text/css; charset=utf-8"
            elif target.suffix == ".svg":
                ctype = "image/svg+xml"
            data_size = target.stat().st_size
            range_hdr = self.headers.get("Range")
            if range_hdr and range_hdr.startswith("bytes="):
                spec = range_hdr[6:].split(",", 1)[0].strip()
                if "-" not in spec:
                    self.send_error(416, "Invalid Range header")
                    return
                s0, s1 = spec.split("-", 1)
                try:
                    start = int(s0) if s0 else 0
                    end = int(s1) if s1 else data_size - 1
                except ValueError:
                    self.send_error(416, "Invalid Range header")
                    return
                end = min(end, data_size - 1)
                if 0 <= start <= end < data_size:
                    length = end - start + 1
                    self.send_response(206)
                    self.send_header("Content-Type", ctype)
                    self.send_header("Accept-Ranges", "bytes")
                    self.send_header("Content-Range", f"bytes {start}-{end}/{data_size}")
                    self.send_header("Content-Length", str(length))
                    self.end_headers()
                    with target.open("rb") as fh:
                        fh.seek(start)
                        self.wfile.write(fh.read(length))
                    return
                self.send_error(416, "Requested Range Not Satisfiable")
                return
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(data_size))
            self.end_headers()
            with target.open("rb") as fh:
                while True:
                    chunk = fh.read(65536)
                    if not chunk:
                        break
                    self.wfile.write(chunk)

    return Handler


def _serve_loop(stage_dir: Path, remotion_dir: Path, port: int) -> int:
    server = _StageTCPServer(("127.0.0.1", port), _make_handler(stage_dir, remotion_dir))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _stop_pid(pid: int) -> None:
    if not _pid_alive(pid):
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return
    for _ in range(20):
        if not _pid_alive(pid):
            return
        time.sleep(0.1)
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass


def _pick_free_port(preferred: int) -> int:
    if preferred > 0:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", preferred))
                return preferred
            except OSError:
                pass
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def fetch_stage_meta(server_url: str, timeout: float = 2.0) -> dict | None:
    try:
        with urllib.request.urlopen(server_url.rstrip("/") + "/api/stage-meta", timeout=timeout) as resp:
            if 200 <= resp.status < 400:
                return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None
    return None


def start_or_reuse_stage(
    project: Path,
    remotion_dir: Path,
    *,
    port: int = 0,
    runtime_home: Path | None = None,
) -> dict:
    """Bundle stage and ensure loopback server is serving this exact project."""
    project = project.resolve()
    remotion_dir = remotion_dir.resolve()
    stage_dir = (project / STAGE_REL).resolve()
    meta = bundle_stage(project, remotion_dir, stage_dir, runtime_home=runtime_home)

    pid_file = stage_dir / "server.pid"
    state_file = project / "edit/_engineering/live-stage.json"
    if state_file.is_file():
        old = _read_json(state_file)
        if old and old.get("engine") == "remotion" and old.get("serverUrl"):
            live_meta = fetch_stage_meta(old["serverUrl"])
            if (
                live_meta
                and Path(str(live_meta.get("projectRoot") or "")).resolve() == project
                and Path(str(live_meta.get("remotionRoot") or "")).resolve() == remotion_dir
                and live_meta.get("sourceHash") == meta["sourceHash"]
            ):
                old["started"] = False
                old["ok"] = True
                return old
            if old.get("pid"):
                try:
                    _stop_pid(int(old["pid"]))
                except (TypeError, ValueError):
                    pass

    if pid_file.is_file():
        try:
            _stop_pid(int(pid_file.read_text(encoding="utf-8").strip()))
        except (OSError, ValueError):
            pass

    use_port = _pick_free_port(port)
    log_path = stage_dir / "server.log"
    with log_path.open("ab") as log_fh:
        proc = subprocess.Popen(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "serve",
                "--stage-dir",
                str(stage_dir),
                "--remotion-dir",
                str(remotion_dir),
                "--port",
                str(use_port),
            ],
            stdin=subprocess.DEVNULL,
            stdout=log_fh,
            stderr=log_fh,
            start_new_session=True,
        )
    _SPAWNED_PROCS[proc.pid] = proc
    pid_file.write_text(f"{proc.pid}\n", encoding="utf-8")

    server_url = f"http://127.0.0.1:{use_port}"
    deadline = time.time() + 15.0
    served_meta = None
    while time.time() < deadline:
        served_meta = fetch_stage_meta(server_url, timeout=1.0)
        if served_meta and served_meta.get("ok"):
            break
        time.sleep(0.15)
    if not served_meta or not served_meta.get("ok"):
        _stop_pid(proc.pid)
        _SPAWNED_PROCS.pop(proc.pid, None)
        try:
            proc.wait(timeout=2)
        except subprocess.SubprocessError:
            pass
        pid_file.unlink(missing_ok=True)
        raise RuntimeError(f"Remotion live-stage server failed to respond on {server_url} (check {log_path})")

    rel_comp = os.path.relpath(remotion_dir, project).replace(os.sep, "/")
    payload = {
        "ok": True,
        "started": True,
        "engine": "remotion",
        "serverUrl": server_url,
        "stageUrl": f"{server_url}/stage.html",
        "projectId": meta["id"],
        "compositionId": meta["id"],
        "composition": rel_comp,
        "remotionDir": rel_comp,
        "duration": meta["duration"],
        "durationInFrames": meta["durationInFrames"],
        "fps": meta["fps"],
        "width": meta["width"],
        "height": meta["height"],
        "sourceHash": meta["sourceHash"],
        "identity": {
            "verified": True,
            "projectRoot": str(project),
            "remotionRoot": str(remotion_dir),
            "compositionRoot": str(remotion_dir),
            "proof": "remotion_stage_meta",
        },
        "pid": str(proc.pid),
        "log": str(log_path.relative_to(project)),
        "port": use_port,
    }
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def stop_stage(project: Path) -> int:
    project = project.resolve()
    stage_dir = project / STAGE_REL
    pid_file = stage_dir / "server.pid"
    state_file = project / "edit/_engineering/live-stage.json"
    stopped = False
    reaped_pids: list[int] = []
    if state_file.is_file():
        doc = _read_json(state_file)
        if doc and doc.get("pid"):
            try:
                pid = int(doc["pid"])
                _stop_pid(pid)
                reaped_pids.append(pid)
                stopped = True
            except (TypeError, ValueError):
                pass
        state_file.unlink(missing_ok=True)
    if pid_file.is_file():
        try:
            pid = int(pid_file.read_text(encoding="utf-8").strip())
            _stop_pid(pid)
            reaped_pids.append(pid)
            stopped = True
        except (OSError, ValueError):
            pass
        pid_file.unlink(missing_ok=True)
    for pid in reaped_pids:
        proc = _SPAWNED_PROCS.pop(pid, None)
        if proc is not None:
            try:
                proc.wait(timeout=2)
            except subprocess.SubprocessError:
                pass
    return 0 if stopped else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Remotion live-stage server & bundler helper")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_serve = sub.add_parser("serve", help="Run loopback HTTP server for bundled stage")
    p_serve.add_argument("--stage-dir", type=Path, required=True)
    p_serve.add_argument("--remotion-dir", type=Path, required=True)
    p_serve.add_argument("--port", type=int, required=True)
    args = ap.parse_args(argv)
    if args.cmd == "serve":
        return _serve_loop(args.stage_dir.resolve(), args.remotion_dir.resolve(), args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
