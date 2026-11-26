#!/usr/bin/env python3
"""Deterministic quality gates and renderer wrapper for Remotion 4 projects.

Implements three pre-delivery gates + external-runtime video rendering without
ever installing `node_modules` inside a project directory:

  - Gate 1 (`typecheck`): `tsc --noEmit` against the External Runtime Shell
  - Gate 2 (`sync`): 0-frame parity between `Root.tsx`, `storyboard.json`, and
    optional `anchors.ts` / `steps.ts` (`STEPS` / `SHOTS`)
  - Gate 3 (`stills`): mid-beat PNG still extraction + non-black/non-flat check
  - `render_remotion`: atomic H.264/yuv420p/CRF-16 render via `/tmp/`

Interface
---------
    python3 helpers/_internal/remotion_gates.py <project> [--only typecheck|sync|stills|all] [--max-stills N] [--json]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HELPERS_DIR = Path(__file__).resolve().parents[1]
INTERNAL_DIR = Path(__file__).resolve().parent
for _p in (str(HELPERS_DIR), str(INTERNAL_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import remotion_runtime  # noqa: E402
import remotion_stage  # noqa: E402

STAGE_REL = "edit/_engineering/remotion-stage"
STILLS_REL = "edit/_engineering/stills"
ANCHOR_CANDIDATES = (
    "src/data/anchors.ts",
    "src/data/anchors.tsx",
    "src/anchors.ts",
    "src/anchors.tsx",
    "src/steps.ts",
    "src/steps.tsx",
    "src/data/steps.ts",
    "src/data/steps.tsx",
)
MOTION_KINDS = {"motion", "model", "card-deck", "xhs"}


def _resolve_project_and_remotion(target: Path) -> tuple[Path, Path | None]:
    root = Path(target).expanduser().resolve()
    if root.name in {"edit", "remotion", "composition"} and root.parent.is_dir():
        root = root.parent
    eng, rem_dir = remotion_stage.detect_motion_engine(root)
    if eng == "remotion" and rem_dir is not None:
        return root, rem_dir.resolve()
    cand = root / "remotion"
    if cand.is_dir() and remotion_stage.find_root_file(cand) is not None:
        return root, cand.resolve()
    return root, None


def _stage_dir(project: Path) -> Path:
    d = (project / STAGE_REL).resolve()
    d.mkdir(parents=True, exist_ok=True)
    return d


def _find_storyboard(project: Path) -> Path | None:
    for rel in ("storyboard.json", "edit/storyboard.json"):
        cand = project / rel
        if cand.is_file():
            return cand
    return None


def _read_json(path: Path) -> dict | None:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else None
    except (OSError, ValueError):
        return None


def _write_stage_remotion_config(project: Path, runtime_home: Path) -> Path:
    """Write stage Remotion config injecting `<runtime>/node_modules` into webpack resolve."""
    stage_dir = _stage_dir(project)
    cfg_path = stage_dir / "remotion.config.stage.mjs"
    runtime_pkg = (Path(runtime_home).resolve() / "package.json").as_posix()
    runtime_nm = (Path(runtime_home).resolve() / "node_modules").as_posix()

    content = f"""import {{ createRequire }} from "node:module";

const require = createRequire({json.dumps(runtime_pkg)});
const {{ Config }} = require("@remotion/cli/config");

const RUNTIME_NM = {json.dumps(runtime_nm)};

Config.setCachingEnabled(false);

Config.overrideWebpackConfig((currentConfiguration) => {{
  const resolve = currentConfiguration.resolve || {{}};
  const resolveLoader = currentConfiguration.resolveLoader || {{}};
  const modules = Array.isArray(resolve.modules) ? [...resolve.modules] : ["node_modules"];
  if (!modules.includes(RUNTIME_NM)) {{
    modules.push(RUNTIME_NM);
  }}
  const loaderModules = Array.isArray(resolveLoader.modules) ? [...resolveLoader.modules] : ["node_modules"];
  if (!loaderModules.includes(RUNTIME_NM)) {{
    loaderModules.push(RUNTIME_NM);
  }}
  return {{
    ...currentConfiguration,
    cache: false,
    resolve: {{
      ...resolve,
      modules,
    }},
    resolveLoader: {{
      ...resolveLoader,
      modules: loaderModules,
    }},
  }};
}});
"""
    cfg_path.write_text(content, encoding="utf-8")
    return cfg_path


def _load_tsconfig_compiler_options(remotion_dir: Path) -> dict:
    ts_path = remotion_dir / "tsconfig.json"
    if not ts_path.is_file():
        return {}
    raw = ts_path.read_text(encoding="utf-8", errors="ignore")
    # Strip /* ... */ and // comments outside strings best-effort
    cleaned = re.sub(r"/\*.*?\*/", "", raw, flags=re.S)
    cleaned = re.sub(r"(?m)^\s*//.*$", "", cleaned)
    try:
        doc = json.loads(cleaned)
    except ValueError:
        return {}
    opts = doc.get("compilerOptions")
    return dict(opts) if isinstance(opts, dict) else {}


def check_typecheck(
    project: Path,
    remotion_dir: Path | None = None,
    *,
    runtime_home: Path | None = None,
) -> dict:
    """Gate 1: run `tsc --noEmit` using External Runtime Shell dependencies."""
    project, detected = _resolve_project_and_remotion(project)
    rem_dir = (remotion_dir or detected)
    if rem_dir is None:
        return {
            "gate": "typecheck",
            "ok": False,
            "errors": [f"找不到 Remotion 工程（缺少 remotion/src/Root.tsx）：{project}"],
        }

    home = remotion_runtime.ensure_runtime(runtime_home, auto_setup=True, skip_browser=True)
    tsc_bin = remotion_runtime.bin_path("tsc", home)
    if not tsc_bin.exists():
        return {
            "gate": "typecheck",
            "ok": False,
            "errors": [f"External Runtime Shell 缺少 tsc：{tsc_bin}"],
        }

    nm = (home / "node_modules").resolve()
    types_dir = (nm / "@types").resolve()
    stage_dir = _stage_dir(project)
    tsconfig_check = stage_dir / "tsconfig.check.json"

    base_opts = _load_tsconfig_compiler_options(rem_dir)
    raw_base = base_opts.get("baseUrl")
    resolved_base = (rem_dir / raw_base).resolve() if isinstance(raw_base, str) and raw_base.strip() else rem_dir.resolve()

    merged_paths: dict[str, list[str]] = {}
    raw_paths = base_opts.get("paths")
    if isinstance(raw_paths, dict):
        for alias, targets in raw_paths.items():
            if not isinstance(targets, list):
                continue
            resolved_targets: list[str] = []
            for t in targets:
                if not isinstance(t, str) or not t.strip():
                    continue
                resolved_targets.append(t if os.path.isabs(t) else os.path.normpath(os.path.join(str(resolved_base), t)))
            if resolved_targets:
                merged_paths[str(alias)] = resolved_targets
    runtime_fallbacks = [f"{types_dir}/*", f"{nm}/*"]
    star_targets = list(merged_paths.get("*", []))
    for fb in runtime_fallbacks:
        if fb not in star_targets:
            star_targets.append(fb)
    merged_paths["*"] = star_targets

    merged_type_roots: list[str] = []
    raw_type_roots = base_opts.get("typeRoots")
    if isinstance(raw_type_roots, list):
        for tr in raw_type_roots:
            if isinstance(tr, str) and tr.strip():
                merged_type_roots.append(tr if os.path.isabs(tr) else os.path.normpath(os.path.join(str(rem_dir.resolve()), tr)))
    if str(types_dir) not in merged_type_roots:
        merged_type_roots.append(str(types_dir))

    merged_opts = {
        "target": base_opts.get("target", "ES2022"),
        "module": base_opts.get("module", "ES2022"),
        **base_opts,
        "baseUrl": str(resolved_base),
        "noEmit": True,
        "skipLibCheck": True,
        "jsx": "react-jsx",
        "moduleResolution": "bundler",
        "typeRoots": merged_type_roots,
        "paths": merged_paths,
    }
    check_doc = {
        "compilerOptions": merged_opts,
        "include": [
            f"{rem_dir.resolve()}/src/**/*.ts",
            f"{rem_dir.resolve()}/src/**/*.tsx",
        ],
    }
    tsconfig_check.write_text(json.dumps(check_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    proc = subprocess.run(
        [str(tsc_bin), "--noEmit", "-p", str(tsconfig_check)],
        cwd=str(rem_dir),
        env=remotion_runtime.runtime_env(home),
        capture_output=True,
        text=True,
    )
    out = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
    errors: list[str] = []
    if proc.returncode != 0:
        lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
        errors = lines[:12] if lines else [f"tsc --noEmit exited with {proc.returncode}"]
    return {
        "gate": "typecheck",
        "ok": proc.returncode == 0,
        "tsconfig": str(tsconfig_check),
        "errors": errors,
        "output": out[-2000:] if out else "",
    }


_INSPECT_ANCHORS_JS = r"""
const esbuild = require(require.resolve("esbuild", { paths: [process.env.VC_NM] }));
const path = require("path");

async function main() {
  const anchorFile = path.resolve(process.argv[2]);
  const outJs = path.resolve(process.argv[3]);
  await esbuild.build({
    entryPoints: [anchorFile],
    outfile: outJs,
    bundle: true,
    platform: "node",
    format: "cjs",
    nodePaths: [process.env.VC_NM],
    logLevel: "silent",
  });
  const mod = require(outJs);
  process.stdout.write(JSON.stringify({
    ok: true,
    hasSteps: mod.STEPS !== undefined,
    hasShots: mod.SHOTS !== undefined,
    STEPS: mod.STEPS !== undefined ? mod.STEPS : null,
    SHOTS: mod.SHOTS !== undefined ? mod.SHOTS : null,
    FPS: typeof mod.FPS === "number" ? mod.FPS : null,
    TOTAL_FRAMES: typeof mod.TOTAL_FRAMES === "number" ? mod.TOTAL_FRAMES : null,
  }));
}

main().catch((err) => {
  process.stderr.write(String(err && err.stack || err) + "\n");
  process.exit(1);
});
"""


def _inspect_anchors_module(remotion_dir: Path, work_dir: Path, home: Path) -> tuple[Path | None, dict | None, str | None]:
    anchor_path: Path | None = None
    for rel in ANCHOR_CANDIDATES:
        cand = remotion_dir / rel
        if cand.is_file():
            anchor_path = cand
            break
    if anchor_path is None:
        return None, None, None

    text = anchor_path.read_text(encoding="utf-8", errors="ignore")
    if not re.search(r"\bexport\b.*\b(STEPS|SHOTS)\b", text):
        return anchor_path, None, None

    script_path = work_dir / "_inspect_anchors.cjs"
    out_cjs = work_dir / "_anchors_bundle.cjs"
    script_path.write_text(_INSPECT_ANCHORS_JS, encoding="utf-8")

    env = remotion_runtime.runtime_env(home)
    env["VC_NM"] = str((home / "node_modules").resolve())
    node_bin = shutil.which("node", path=env.get("PATH")) or "node"
    proc = subprocess.run(
        [node_bin, str(script_path), str(anchor_path), str(out_cjs)],
        cwd=str(remotion_dir),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode != 0:
        return anchor_path, None, f"打包/读取 {anchor_path.name} 失败：{(proc.stderr or proc.stdout)[-400:]}"
    try:
        payload = json.loads(proc.stdout)
    except ValueError as exc:
        return anchor_path, None, f"解析 {anchor_path.name} 输出失败：{exc}"
    return anchor_path, payload, None


def _item_frame_span(item: dict, fps: float) -> tuple[int, int] | None:
    if not isinstance(item, dict):
        return None
    if item.get("startFrame") is not None and item.get("endFrame") is not None:
        return int(item["startFrame"]), int(item["endFrame"])
    if item.get("from") is not None and item.get("durationInFrames") is not None:
        f0 = int(item["from"])
        return f0, f0 + int(item["durationInFrames"])
    if item.get("startSec") is not None and item.get("endSec") is not None:
        return int(round(float(item["startSec"]) * fps)), int(round(float(item["endSec"]) * fps))
    if item.get("start") is not None and item.get("end") is not None:
        return int(round(float(item["start"]) * fps)), int(round(float(item["end"]) * fps))
    return None


def _normalize_anchor_shots(raw_val, fps: float) -> dict[str, tuple[int, int]]:
    out: dict[str, tuple[int, int]] = {}
    if isinstance(raw_val, dict):
        for sid, item in raw_val.items():
            span = _item_frame_span(item, fps)
            if span is not None:
                out[str(sid)] = span
    elif isinstance(raw_val, list):
        for idx, item in enumerate(raw_val):
            if not isinstance(item, dict):
                continue
            sid = str(item.get("id") or f"idx:{idx}")
            span = _item_frame_span(item, fps)
            if span is not None:
                out[sid] = span
    return out


def check_storyboard_sync(
    project: Path,
    remotion_dir: Path | None = None,
    *,
    runtime_home: Path | None = None,
) -> dict:
    """Gate 2: verify 0-frame parity across Root.tsx, storyboard.json, and anchors STEPS/SHOTS."""
    project, detected = _resolve_project_and_remotion(project)
    rem_dir = remotion_dir or detected
    if rem_dir is None:
        return {
            "gate": "sync",
            "ok": False,
            "errors": [f"找不到 Remotion 工程（缺少 remotion/src/Root.tsx）：{project}"],
        }

    stage_dir = _stage_dir(project)
    try:
        home = remotion_runtime.ensure_runtime(runtime_home, auto_setup=True, skip_browser=True)
        meta = remotion_stage.extract_compositions_metadata(rem_dir, stage_dir, home, skip_browser=True)
    except RuntimeError as exc:
        return {"gate": "sync", "ok": False, "errors": [str(exc)]}

    primary = meta["primary"]
    comp_fps = float(primary.get("fps") or 0)
    comp_w = int(primary.get("width") or 0)
    comp_h = int(primary.get("height") or 0)
    comp_frames = int(primary.get("durationInFrames") or 0)

    sb_path = _find_storyboard(project)
    if sb_path is None:
        return {
            "gate": "sync",
            "ok": True,
            "composition": primary,
            "storyboard": None,
            "errors": [],
            "note": "未找到 storyboard.json，仅校验了 Remotion 合成元数据",
        }

    sb_doc = _read_json(sb_path)
    if sb_doc is None:
        return {
            "gate": "sync",
            "ok": False,
            "composition": primary,
            "storyboard": str(sb_path),
            "errors": [f"无法解析分镜文件：{sb_path}"],
        }

    errors: list[str] = []
    canvas = sb_doc.get("canvas") if isinstance(sb_doc.get("canvas"), dict) else {}
    if canvas.get("fps") is not None:
        sb_fps = float(canvas["fps"])
        if abs(sb_fps - comp_fps) > 1e-6:
            errors.append(f"FPS 不一致：Root.tsx={comp_fps:g} vs storyboard.json={sb_fps:g}")
    sb_w = canvas.get("width") if canvas.get("width") is not None else canvas.get("w")
    sb_h = canvas.get("height") if canvas.get("height") is not None else canvas.get("h")
    if sb_w is not None and int(sb_w) != comp_w:
        errors.append(f"画宽不一致：Root.tsx={comp_w} vs storyboard.json={int(sb_w)}")
    if sb_h is not None and int(sb_h) != comp_h:
        errors.append(f"画高不一致：Root.tsx={comp_h} vs storyboard.json={int(sb_h)}")

    shots = [s for s in (sb_doc.get("shots") or []) if isinstance(s, dict)]
    sb_spans: dict[str, tuple[int, int]] = {}
    sb_order: list[str] = []
    max_end_frame = 0
    for idx, s in enumerate(shots):
        sid = str(s.get("id") or f"idx:{idx}")
        span = _item_frame_span(s, comp_fps)
        if span is None:
            continue
        sb_spans[sid] = span
        sb_order.append(sid)
        if span[1] > max_end_frame:
            max_end_frame = span[1]

    expected_frames: int | None = None
    expected_source = ""
    if sb_doc.get("totalFrames") is not None:
        expected_frames = int(sb_doc["totalFrames"])
        expected_source = "totalFrames"
    elif sb_doc.get("totalSec") is not None and comp_fps > 0:
        expected_frames = int(round(float(sb_doc["totalSec"]) * comp_fps))
        expected_source = "totalSec"
    elif sb_spans:
        expected_frames = max_end_frame
        expected_source = "max(endFrame)"

    if expected_frames is not None and comp_frames != expected_frames:
        errors.append(
            f"总帧数不一致（零容差）：Root.tsx durationInFrames={comp_frames} vs "
            f"storyboard {expected_source}={expected_frames}（差 {comp_frames - expected_frames:+d} 帧）"
        )

    anchor_path, anchor_doc, anchor_err = _inspect_anchors_module(rem_dir, stage_dir, home)
    if anchor_err:
        errors.append(anchor_err)
    elif anchor_doc is not None:
        if anchor_doc.get("FPS") is not None and abs(float(anchor_doc["FPS"]) - comp_fps) > 1e-6:
            errors.append(f"{anchor_path.name} FPS={anchor_doc['FPS']} 与 Root.tsx fps={comp_fps:g} 不一致")
        if anchor_doc.get("TOTAL_FRAMES") is not None and int(anchor_doc["TOTAL_FRAMES"]) != comp_frames:
            errors.append(
                f"{anchor_path.name} TOTAL_FRAMES={anchor_doc['TOTAL_FRAMES']} "
                f"与 Root.tsx durationInFrames={comp_frames} 不一致"
            )

        raw_collection = anchor_doc.get("STEPS") if anchor_doc.get("hasSteps") else anchor_doc.get("SHOTS")
        anchor_spans = _normalize_anchor_shots(raw_collection, comp_fps)
        if not anchor_spans:
            errors.append(f"{anchor_path.name} 导出了 STEPS/SHOTS，但未解析出有效帧区间")
        else:
            all_motion_or_rem = all(
                s.get("engine") == "remotion" or s.get("kind") in MOTION_KINDS
                for s in shots
            )
            remotion_shot_ids = {
                str(s.get("id")) for s in shots
                if s.get("id") and (
                    s.get("engine") == "remotion"
                    or (not s.get("engine") and s.get("kind") in MOTION_KINDS)
                    or all_motion_or_rem
                )
            }
            for sid in sorted(remotion_shot_ids):
                if sid not in anchor_spans:
                    errors.append(f"{anchor_path.name} 缺少分镜镜头 {sid}")
            for sid, (af0, af1) in anchor_spans.items():
                if sid not in sb_spans:
                    errors.append(f"{anchor_path.name} 多出未在 storyboard.json 登记的镜头 {sid}")
                    continue
                sf0, sf1 = sb_spans[sid]
                if af0 != sf0 or af1 != sf1:
                    errors.append(
                        f"镜头 {sid} 切点帧数不一致（零容差）：{anchor_path.name}=[{af0}, {af1}] "
                        f"vs storyboard=[{sf0}, {sf1}]"
                    )

    return {
        "gate": "sync",
        "ok": not errors,
        "composition": primary,
        "storyboard": str(sb_path),
        "expectedFrames": expected_frames,
        "anchorsFile": str(anchor_path) if anchor_path else None,
        "errors": errors,
    }


def _evaluate_luma_samples(path: Path, data: list[int], size: int, extra: dict | None = None) -> tuple[bool, dict, str | None]:
    mean_luma = sum(data) / len(data)
    lo, hi = int(min(data)), int(max(data))
    stats = {
        "bytes": size,
        **(extra or {}),
        "meanLuma": round(mean_luma, 2),
        "minLuma": lo,
        "maxLuma": hi,
    }
    if hi < 12 and mean_luma < 6.0:
        return False, stats, f"{path.name} 疑似全黑帧 (mean={mean_luma:.1f}, max={hi})"
    if (hi - lo) < 2:
        return False, stats, f"{path.name} 画面单色平坦无内容 (min={lo}, max={hi})"
    return True, stats, None


def _inspect_still_png(path: Path) -> tuple[bool, dict, str | None]:
    if not path.is_file():
        return False, {}, f"静帧文件不存在：{path}"
    size = path.stat().st_size
    if size <= 0:
        return False, {"bytes": 0}, f"静帧为空文件：{path.name}"

    try:
        from PIL import Image
        with Image.open(path) as im:
            im.load()
            w, h = im.size
            grey = im.convert("L")
            if w * h > 320 * 180:
                grey = grey.resize((160, max(1, int(round(160 * h / max(1, w))))))
            data = list(grey.getdata())
        return _evaluate_luma_samples(path, data, size, {"width": w, "height": h})
    except ImportError:
        pass
    except Exception as exc:
        return False, {"bytes": size}, f"{path.name} PNG 读取损坏：{exc}"

    # Fallback via ffprobe + ffmpeg gray stats
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", str(path)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        return False, {"bytes": size}, f"{path.name} ffprobe 读取失败"
    fproc = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-vf", "scale=160:90,format=gray", "-f", "rawvideo", "-"],
        capture_output=True,
    )
    if fproc.returncode != 0 or not fproc.stdout:
        return False, {"bytes": size}, f"{path.name} 解码像素失败"
    return _evaluate_luma_samples(path, list(fproc.stdout), size)


def _select_still_targets(project: Path, comp_frames: int, fps: float, max_stills: int | None) -> list[tuple[str, int]]:
    sb_path = _find_storyboard(project)
    targets: list[tuple[str, int]] = []
    if sb_path is not None:
        sb_doc = _read_json(sb_path) or {}
        for idx, shot in enumerate(sb_doc.get("shots") or []):
            if not isinstance(shot, dict):
                continue
            eng = shot.get("engine")
            kind = shot.get("kind")
            is_rem = eng == "remotion" or (not eng and kind in MOTION_KINDS)
            if not is_rem:
                continue
            span = _item_frame_span(shot, fps)
            if span is None:
                continue
            f0, f1 = span
            mid = max(0, min(max(0, comp_frames - 1), (f0 + f1) // 2))
            sid = re.sub(r"[^A-Za-z0-9._-]+", "_", str(shot.get("id") or f"S{idx + 1:02d}")).strip("_") or f"S{idx + 1:02d}"
            targets.append((sid, mid))

    if not targets:
        max_idx = max(0, comp_frames - 1)
        for idx, frac in enumerate((0.15, 0.50, 0.85), start=1):
            fr = max(0, min(max_idx, int(round(frac * max_idx))))
            targets.append((f"sample_{idx:02d}", fr))

    if max_stills is not None and max_stills > 0 and len(targets) > max_stills:
        if max_stills == 1:
            targets = [targets[len(targets) // 2]]
        else:
            step_idxs = sorted({
                int(round(i * (len(targets) - 1) / (max_stills - 1)))
                for i in range(max_stills)
            })
            targets = [targets[i] for i in step_idxs]
    return targets


def extract_shot_stills(
    project: Path,
    remotion_dir: Path | None = None,
    *,
    max_stills: int | None = None,
    runtime_home: Path | None = None,
) -> dict:
    """Gate 3: render mid-beat PNG stills for Remotion shots and verify non-black/non-flat."""
    project, detected = _resolve_project_and_remotion(project)
    rem_dir = remotion_dir or detected
    if rem_dir is None:
        return {
            "gate": "stills",
            "ok": False,
            "errors": [f"找不到 Remotion 工程（缺少 remotion/src/Root.tsx）：{project}"],
        }

    entry_file = remotion_stage.find_entry_file(rem_dir)
    if entry_file is None:
        return {
            "gate": "stills",
            "ok": False,
            "errors": [f"找不到 Remotion 入口文件（remotion/src/index.ts）：{rem_dir}"],
        }

    home = remotion_runtime.ensure_runtime(
        runtime_home,
        auto_setup=True,
        skip_browser=False,
    )
    browser_bin, browser_source = remotion_runtime.resolve_browser_executable(home)
    remotion_bin = remotion_runtime.bin_path("remotion", home)
    if not remotion_bin.exists():
        return {
            "gate": "stills",
            "ok": False,
            "errors": [f"External Runtime Shell 缺少 remotion CLI：{remotion_bin}"],
        }

    stage_dir = _stage_dir(project)
    meta = remotion_stage.extract_compositions_metadata(rem_dir, stage_dir, home, skip_browser=True)
    primary = meta["primary"]
    comp_id = str(primary["id"])
    fps = float(primary.get("fps") or 30)
    comp_frames = int(primary.get("durationInFrames") or 1)

    stage_config = _write_stage_remotion_config(project, home)
    public_dir = rem_dir / "public"
    stills_dir = (project / STILLS_REL).resolve()
    stills_dir.mkdir(parents=True, exist_ok=True)

    targets = _select_still_targets(project, comp_frames, fps, max_stills)
    env = remotion_runtime.runtime_env(home)

    records: list[dict] = []
    errors: list[str] = []
    for sid, frame in targets:
        out_png = stills_dir / f"{sid}_f{frame}.png"
        cmd = [
            str(remotion_bin), "still",
            str(entry_file), comp_id, str(out_png),
            "--frame", str(frame),
            "--image-format", "png",
            "--config", str(stage_config),
            "--overwrite",
        ]
        if public_dir.is_dir():
            cmd.extend(["--public-dir", str(public_dir)])
        if browser_bin is not None and browser_source != "remotion-managed":
            cmd.extend(["--browser-executable", str(browser_bin)])

        proc = subprocess.run(cmd, cwd=str(rem_dir), env=env, capture_output=True, text=True)
        if proc.returncode != 0:
            err_msg = f"{sid} @ frame {frame} remotion still 失败：{((proc.stderr or proc.stdout)[-400:]).strip()}"
            errors.append(err_msg)
            records.append({
                "shotId": sid,
                "frame": frame,
                "sec": round(frame / fps, 3) if fps > 0 else 0.0,
                "path": os.path.relpath(out_png, project).replace(os.sep, "/"),
                "ok": False,
                "error": err_msg,
            })
            continue

        img_ok, stats, luma_err = _inspect_still_png(out_png)
        if not img_ok and luma_err:
            errors.append(luma_err)
        records.append({
            "shotId": sid,
            "frame": frame,
            "sec": round(frame / fps, 3) if fps > 0 else 0.0,
            "path": os.path.relpath(out_png, project).replace(os.sep, "/"),
            "ok": img_ok,
            **stats,
            **({"error": luma_err} if luma_err else {}),
        })

    manifest = {
        "schema": "video-craft/remotion-stills/1",
        "compositionId": comp_id,
        "fps": fps,
        "width": int(primary.get("width") or 0),
        "height": int(primary.get("height") or 0),
        "durationInFrames": comp_frames,
        "stills": records,
        "ok": not errors and bool(records),
    }
    manifest_path = stills_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return {
        "gate": "stills",
        "ok": not errors and bool(records),
        "manifest": str(manifest_path),
        "count": len(records),
        "stills": records,
        "errors": errors,
    }


def render_remotion(
    project: Path,
    remotion_dir: Path,
    out_path: Path,
    comp_id: str | None = None,
    *,
    runtime_home: Path | None = None,
) -> Path:
    """Render Remotion composition to `/tmp/` via External Runtime Shell then atomically move."""
    project = Path(project).expanduser().resolve()
    rem_dir = Path(remotion_dir).expanduser().resolve()
    out_path = Path(out_path).expanduser().resolve()

    entry_file = remotion_stage.find_entry_file(rem_dir)
    if entry_file is None:
        raise RuntimeError(f"找不到 Remotion 入口文件（remotion/src/index.ts）：{rem_dir}")

    home = remotion_runtime.ensure_runtime(
        runtime_home,
        auto_setup=True,
        skip_browser=False,
    )
    browser_bin, browser_source = remotion_runtime.resolve_browser_executable(home)
    remotion_bin = remotion_runtime.bin_path("remotion", home)
    if not remotion_bin.exists():
        raise RuntimeError(f"External Runtime Shell 缺少 remotion CLI：{remotion_bin}")

    stage_dir = _stage_dir(project)
    if not comp_id:
        meta = remotion_stage.extract_compositions_metadata(rem_dir, stage_dir, home, skip_browser=True)
        comp_id = str(meta["primary"]["id"])

    stage_config = _write_stage_remotion_config(project, home)
    public_dir = rem_dir / "public"
    env = remotion_runtime.runtime_env(home)

    with tempfile.TemporaryDirectory(prefix="vc-remotion-render-", dir="/tmp") as td:
        tmp_mp4 = Path(td) / "visuals.mp4"
        cmd = [
            str(remotion_bin), "render",
            str(entry_file), str(comp_id), str(tmp_mp4),
            "--config", str(stage_config),
            "--codec", "h264",
            "--crf", "16",
            "--pixel-format", "yuv420p",
            "--overwrite",
        ]
        if public_dir.is_dir():
            cmd.extend(["--public-dir", str(public_dir)])
        if browser_bin is not None and browser_source != "remotion-managed":
            cmd.extend(["--browser-executable", str(browser_bin)])

        proc = subprocess.run(cmd, cwd=str(rem_dir), env=env, capture_output=True, text=True)
        if proc.returncode != 0 or not tmp_mp4.is_file() or tmp_mp4.stat().st_size == 0:
            raise RuntimeError(
                f"Remotion 渲染失败 (exit={proc.returncode}): "
                f"{((proc.stderr or proc.stdout)[-800:]).strip()}"
            )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(tmp_mp4), str(out_path))

    return out_path


def _parse_only_arg(raw: str) -> list[str]:
    valid = ("typecheck", "sync", "stills", "all")
    parts = [p.strip() for p in str(raw or "all").split(",") if p.strip()]
    if not parts:
        return ["typecheck", "sync", "stills"]
    for p in parts:
        if p not in valid:
            raise argparse.ArgumentTypeError(f"invalid --only choice {p!r}; expected typecheck|sync|stills|all")
    if "all" in parts:
        return ["typecheck", "sync", "stills"]
    dedup: list[str] = []
    for p in parts:
        if p not in dedup:
            dedup.append(p)
    return dedup


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="remotion_gates.py",
        description="Remotion deterministic quality gates (typecheck, storyboard sync, mid-beat stills)",
    )
    ap.add_argument("project", help="Project root (or remotion/ / edit/)")
    ap.add_argument(
        "--only",
        default="all",
        help="Comma-separated or single gate: typecheck|sync|stills|all (default: all)",
    )
    ap.add_argument("--max-stills", type=int, default=None, help="Cap number of still frames extracted")
    ap.add_argument("--runtime-home", type=Path, default=None, help="Override External Runtime Shell path")
    ap.add_argument("--json", action="store_true", help="Emit machine-readable JSON output")
    args = ap.parse_args(argv)

    try:
        selected = _parse_only_arg(args.only)
    except argparse.ArgumentTypeError as exc:
        ap.error(str(exc))
        return 2

    target = Path(args.project).expanduser()
    if not target.exists():
        print(f"✗ 项目不存在：{target}", file=sys.stderr)
        return 2

    project, rem_dir = _resolve_project_and_remotion(target)
    if rem_dir is None:
        payload = {
            "ok": False,
            "project": str(project),
            "errors": [f"找不到 Remotion 工程（缺少 remotion/src/Root.tsx）：{project}"],
            "gates": {},
        }
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"✗ {payload['errors'][0]}", file=sys.stderr)
        return 2

    gates_out: dict[str, dict] = {}
    all_errors: list[str] = []

    if "typecheck" in selected:
        res = check_typecheck(project, rem_dir, runtime_home=args.runtime_home)
        gates_out["typecheck"] = res
        all_errors.extend(res.get("errors") or [])

    if "sync" in selected:
        res = check_storyboard_sync(project, rem_dir, runtime_home=args.runtime_home)
        gates_out["sync"] = res
        all_errors.extend(res.get("errors") or [])

    if "stills" in selected:
        res = extract_shot_stills(
            project, rem_dir, max_stills=args.max_stills, runtime_home=args.runtime_home
        )
        gates_out["stills"] = res
        all_errors.extend(res.get("errors") or [])

    ok = all(g.get("ok") for g in gates_out.values()) and not all_errors
    report = {
        "ok": ok,
        "project": str(project),
        "remotionDir": str(rem_dir),
        "selected": selected,
        "gates": gates_out,
        "errors": all_errors,
    }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for name, g in gates_out.items():
            mark = "✓" if g.get("ok") else "✗"
            print(f"{mark} remotion_gates[{name}]")
            for err in g.get("errors") or []:
                print(f"  × {err}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
