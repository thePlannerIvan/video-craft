#!/usr/bin/env python3
"""Report what this machine can actually do — and nothing else.

The v3 architecture review drew one boundary for this file: a probe reports
capabilities, it does not decide what should happen. So this script answers
"does ffmpeg have libass? how much font weight is baked into the composition?
is a preview server stealing the GPU?" as JSON, and exits 0 even when something
is missing. Callers (render, review build, import) choose the fallback; the
model decides whether "burned captions" can stay in scope.

Why it exists (measured, not hypothetical):
  * a composition naming a system CJK family embedded ~23MB of font, compile
    went from 2.9s to >240s;
  * `render.py` burns captions through libass, and this machine's ffmpeg has no
    `ass`/`subtitles`/`drawtext` filter at all;
  * a running `hyperframes preview` dropped capture from ~25 fps to ~0.9 fps.

Usage:
    python3 helpers/probe_env.py [project] [--json]
    python3 helpers/probe_env.py [project] --strict --require node,libass
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

SYSTEM_CJK_FAMILIES = (
    "Hiragino", "PingFang", "Heiti", "Songti", "STHeiti", "Noto Sans CJK",
    "Source Han Sans", "Microsoft YaHei", "SimHei",
)
_FILTER_ROW = re.compile(r"^\s*[TSC.]{2,3}\s+(\S+)\s+")
FONT_BUDGET_BYTES = 2 << 20  # 2MB: a subset font is ~0.5MB, a system dump is ~20MB


def _run(cmd: list[str]) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        return (r.stdout or "") + (r.stderr or "")
    except (OSError, subprocess.SubprocessError):
        return ""


def ffmpeg_capabilities() -> dict:
    if not shutil.which("ffmpeg"):
        return {"present": False, "filters": {}}
    raw = _run(["ffmpeg", "-hide_banner", "-filters"])
    # Filter rows look like " T.. ass  V->V  ..."; substring matching lies ("ass" is
    # inside "protect"/"pass" and in the subtitles filter's description).
    names = set()
    for line in raw.splitlines():
        m = _FILTER_ROW.match(line)
        if m:
            names.add(m.group(1))
    return {
        "present": True,
        "version": (_run(["ffmpeg", "-version"]).splitlines() or [""])[0],
        "filters": {
            name: (name in names)
            for name in ("ass", "subtitles", "drawtext", "overlay", "alphamerge")
        },
    }


def font_cache() -> dict:
    override = os.environ.get("HYPERFRAMES_FONT_CACHE_DIR")
    root = Path(override) if override else Path.home() / ".cache" / "hyperframes" / "fonts"
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import check_render_env as cre
        candidates = cre.font_cache_candidates()
        results = []
        for candidate in candidates:
            ok, detail = cre.probe_writable(candidate)
            results.append({"dir": str(candidate), "ok": ok, "detail": detail})
    except Exception:  # noqa: BLE001 - probe must never crash
        results = []
    return {
        "dir": next((r["dir"] for r in results if r["ok"]), str(root)),
        "candidates": results or [{"dir": str(root), "ok": False, "detail": "check_render_env unavailable"}],
        "writable": any(r["ok"] for r in results) if results else False,
        "override_env": bool(override),
    }


def stray_processes() -> dict:
    out = {}
    for pattern in ("hyperframes render", "hyperframes preview", "chrome-headless-shell"):
        text = _run(["pgrep", "-f", pattern])
        out[pattern] = len([line for line in text.splitlines() if line.strip()])
    return out


def composition_budget(project: Path) -> dict | None:
    html = project / "composition" / "index.html"
    if not html.is_file():
        return None
    text = html.read_text(encoding="utf-8", errors="ignore")
    system = [f for f in SYSTEM_CJK_FAMILIES if f in text]
    has_face = "@font-face" in text
    assets = project / "composition" / "assets"
    total = 0
    if assets.is_dir():
        total = sum(p.stat().st_size for p in assets.rglob("*") if p.is_file())
    fonts = sorted(
        [(p.name, p.stat().st_size) for p in assets.rglob("*")
         if p.is_file() and p.suffix.lower() in (".ttf", ".otf", ".woff", ".woff2")],
        key=lambda x: -x[1],
    ) if assets.is_dir() else []
    return {
        "index": str(html),
        "system_cjk_families": system,
        "has_font_face": has_face,
        "font_files": [{"name": n, "bytes": b} for n, b in fonts[:5]],
        "assets_bytes": total,
        "font_budget_bytes": FONT_BUDGET_BYTES,
        "over_font_budget": any(b > FONT_BUDGET_BYTES for _, b in fonts),
    }


def build(project: Path | None) -> dict:
    report = {
        "ok": True,
        "ffmpeg": ffmpeg_capabilities(),
        "node": {"present": bool(shutil.which("node"))},
        "npx": {"present": bool(shutil.which("npx"))},
        "hyperframes": {"present": bool(shutil.which("hyperframes")) or bool(shutil.which("npx"))},
        "font_cache": font_cache(),
        "stray_processes": stray_processes(),
        "composition": composition_budget(project) if project else None,
        "notes": [],
    }
    f = report["ffmpeg"]["filters"]
    if report["ffmpeg"]["present"] and not f.get("subtitles"):
        report["notes"].append("ffmpeg 没有 libass（ass/subtitles）——烧录字幕不可用；可改外挂 SRT，或装带 libass 的 ffmpeg")
    if report["ffmpeg"]["present"] and not f.get("drawtext"):
        report["notes"].append("ffmpeg 没有 drawtext——不能用 drawtext 叠字")
    comp = report["composition"]
    if comp:
        if comp["system_cjk_families"] and not comp["has_font_face"]:
            report["notes"].append(
                "composition 引用了系统 CJK 字族且没有 @font-face：HyperFrames 会把整包字体嵌进 HTML（实测 23MB → compile >240s）；换本地子集字体")
        if comp["over_font_budget"]:
            report["notes"].append("composition/assets 里有字体超过 2MB：确认是否已子集化")
        if comp["assets_bytes"] > 40 << 20:
            report["notes"].append("composition/assets 超过 40MB：编译与传输都会变慢，确认是否需要代理媒体")
    stray = {k: v for k, v in report["stray_processes"].items() if v}
    if stray:
        report["notes"].append(f"有渲染/预览进程在跑 {stray}：预览服务会抢 GPU（实测抓帧 25fps → 0.9fps），确认是否需要先停")
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("project", nargs="?", type=Path)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--strict", action="store_true", help="缺 --require 的能力时退 1")
    ap.add_argument("--require", default="", help="逗号分隔：node,libass,drawtext")
    a = ap.parse_args()
    report = build(a.project)
    if a.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"ffmpeg: {report['ffmpeg'].get('version', 'missing')}")
        print("filters: " + ", ".join(f"{k}={'yes' if v else 'NO'}" for k, v in report["ffmpeg"]["filters"].items()))
        print(f"font cache: {report['font_cache']['dir']} writable={report['font_cache']['writable']}")
        print("stray: " + (json.dumps(report["stray_processes"]) if any(report["stray_processes"].values()) else "none"))
        for note in report["notes"]:
            print(f"! {note}")
    missing = []
    for need in [x.strip() for x in a.require.split(",") if x.strip()]:
        if need == "libass" and not report["ffmpeg"]["filters"].get("subtitles"):
            missing.append(need)
        elif need == "drawtext" and not report["ffmpeg"]["filters"].get("drawtext"):
            missing.append(need)
        elif need == "node" and not report["node"]["present"]:
            missing.append(need)
    if missing:
        print(f"missing required capabilities: {', '.join(missing)}", file=sys.stderr)
        return 1 if a.strict else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
