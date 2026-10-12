#!/usr/bin/env python3
"""Export a browser-compositable twin for every alpha overlay in the EDL.

Why: an overlay is authored/encoded as MOV (PNG-in-MOV or ProRes 4444) because
that is what ffmpeg can composite. No browser can composite those alpha channels —
Chrome cannot do it at all — so a page that wanted to show the layer itself had
nothing to play, and the only way to see an overlay was to bake it into the film.

WebM VP9 with `yuva420p` is the one alpha carrier browsers do composite, so this
writes a sibling `<name>.webm` next to each overlay. `build_review.py` then gives
the layer a `previewFile`, and the review page stacks it over the composite and
seeks it against the master clock.

The MOV stays the delivery artefact; the WebM exists only so the layer can be
looked at without rendering.

Usage:
    python3 helpers/preview_layers.py <edit_dir> [--force] [--crf 24] [--json]
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "visual" / "scripts"))
from _edl import load_edl  # noqa: E402
from encode_transparent import verify_alpha  # noqa: E402


def export_one(src: Path, *, crf: int = 24, force: bool = False) -> dict:
    out = src.with_suffix(".webm")
    if out.is_file() and not force and out.stat().st_mtime >= src.stat().st_mtime:
        return {"file": str(src), "webm": str(out), "action": "cached"}
    if shutil.which("ffmpeg") is None:
        raise SystemExit("✗ PATH 上没有 ffmpeg")
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(src),
         "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-auto-alt-ref", "0",
         "-b:v", "0", "-crf", str(crf), "-row-mt", "1",
         "-cpu-used", "5", "-deadline", "good", str(out)],
        capture_output=True)
    if proc.returncode != 0:
        tail = proc.stderr.decode("utf-8", "replace").strip().splitlines()[-3:]
        raise SystemExit(f"✗ {src.name} 转 WebM 失败：" + " / ".join(tail))
    print(f"  {src.name}")
    verify_alpha(out)      # refuses an opaque "preview" rather than shipping one
    return {"file": str(src), "webm": str(out), "action": "made",
            "size_mb": round(out.stat().st_size / 1e6, 2)}


def main() -> int:
    ap = argparse.ArgumentParser(description="为 EDL 里的每个 alpha 层出一份浏览器可合成的 WebM")
    ap.add_argument("edit_dir", type=Path)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--crf", type=int, default=24)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    edit_dir = args.edit_dir.resolve()
    edl = load_edl(edit_dir)
    overlays = edl.get("overlays") or []
    if not overlays:
        raise SystemExit(f"✗ {edit_dir}/edl.json 里没有 overlays")

    results = []
    for overlay in overlays:
        raw = str(overlay.get("file") or "")
        if not raw:
            continue
        path = Path(raw)
        if not path.is_absolute():
            path = (edit_dir / path).resolve()
        if not path.is_file():
            results.append({"file": raw, "action": "missing"})
            continue
        results.append(export_one(path, crf=args.crf, force=args.force))

    made = sum(1 for r in results if r["action"] == "made")
    cached = sum(1 for r in results if r["action"] == "cached")
    missing = [r["file"] for r in results if r["action"] == "missing"]
    if args.json:
        print(json.dumps(results, ensure_ascii=False))
    else:
        print(f"浏览器可合成层：新出 {made} / 复用 {cached}"
              + (f" / 缺文件 {len(missing)}" if missing else ""))
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
