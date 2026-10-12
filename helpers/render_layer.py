#!/usr/bin/env python3
"""Render a HyperFrames composition into alpha layers — the HTML-first overlay path.

The point of this helper is which artefact is the *source*. A visual layer used to be
authored directly as an encoded video: you wrote a frame renderer, baked an alpha MOV,
and that file WAS the layer. Nothing could be looked at without rendering the film,
nothing could be tuned without re-encoding, and the review page had no carrier it could
composite.

Here the composition (HTML/CSS/GSAP) is the source and the alpha videos are exports —
two of them, deliberately:

  * `.mov` — what ffmpeg composites into the film (the delivery artefact);
  * `.webm` — VP9 + alpha, the only alpha carrier a browser can composite, so the
    review page can stack the layer over the cut and seek it without any film render.

Both come from ONE capture: the composition is rendered once to a PNG sequence and both
carriers are encoded from those frames, so preview and delivery cannot drift apart. The
MOV is PNG-in-MOV — lossless RGBA with real alpha, matching the overlays it replaces —
rather than a ProRes/YUV round trip.

Usage:
    python3 helpers/render_layer.py <composition_dir> -o <out_stem> \\
        [--variables '{"set":"bolt"}'] [--fps 30] [--formats mov,webm] \\
        [--no-check] [--json]
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "visual" / "scripts"))
from encode_transparent import encode_sequence  # noqa: E402

FORMATS = ("mov", "webm")


def _run(cmd: list[str], cwd: Path, quiet: bool) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-6:]
        raise SystemExit("✗ " + " ".join(cmd[:4]) + " 失败：\n  " + "\n  ".join(tail))
    if not quiet:
        for line in (proc.stdout or "").splitlines()[-3:]:
            if line.strip():
                print("    " + line.strip())
    return proc


def render(composition_dir: Path, out_stem: Path, *, variables: dict | None = None,
           fps: int = 30, formats: tuple[str, ...] = FORMATS, check: bool = True,
           quiet: bool = False) -> list[dict]:
    composition_dir = Path(composition_dir).resolve()
    if not (composition_dir / "index.html").is_file():
        raise SystemExit(f"✗ 不是 composition 目录（缺 index.html）：{composition_dir}")
    if shutil.which("npx") is None:
        raise SystemExit("✗ PATH 上没有 npx（HyperFrames 走 npx hyperframes）")

    base = ["npx", "--yes", "hyperframes"]
    if check:
        _run(base + ["check"], composition_dir, quiet)

    out_stem = Path(out_stem).resolve()
    out_stem.parent.mkdir(parents=True, exist_ok=True)

    results = []
    # Capture once. Rendering per format re-runs the browser for every carrier — slower,
    # and a chance for the two to drift; the PNG sequence is also the lossless source
    # both encoders want. encode_sequence() verifies the alpha plane itself.
    with tempfile.TemporaryDirectory(prefix="vc_layer_") as tmp:
        seq = Path(tmp) / "frames"
        cmd = base + ["render", ".", "--format", "png-sequence", "--fps", str(fps),
                      "-o", str(seq)]
        if variables:
            cmd += ["--variables", json.dumps(variables)]
        _run(cmd, composition_dir, quiet)
        frames = sorted(seq.glob("*.png"))
        if not frames:
            raise SystemExit(f"✗ 渲染没有产出 PNG 帧：{seq}")

        for fmt in formats:
            target = out_stem.with_suffix("." + fmt)
            record = encode_sequence(seq, target,
                                     codec="png" if fmt == "mov" else "webm",
                                     fps=fps, quiet=True)
            results.append({"format": fmt, "file": str(target),
                            "frames": record["frames"],
                            "size_mb": round(record["size_mb"], 2)})
    return results


def main() -> int:
    ap = argparse.ArgumentParser(description="把 HTML composition 渲成两种 alpha 层（MOV 交付 / WebM 预览）")
    ap.add_argument("composition_dir", type=Path)
    ap.add_argument("-o", "--output", type=Path, required=True,
                    help="输出主干名（自动补 .mov / .webm）")
    ap.add_argument("--variables", default=None, help="JSON 对象，覆盖 composition 的变量")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--formats", default=",".join(FORMATS))
    ap.add_argument("--no-check", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    variables = json.loads(args.variables) if args.variables else None
    formats = tuple(f.strip() for f in args.formats.split(",") if f.strip())
    bad = [f for f in formats if f not in FORMATS]
    if bad:
        raise SystemExit(f"✗ 不支持的格式 {bad}；只支持 {list(FORMATS)}"
                         "（这是「层」，不是成片：别的容器本身不带 alpha）")

    results = render(args.composition_dir, args.output, variables=variables,
                     fps=args.fps, formats=formats, check=not args.no_check,
                     quiet=args.quiet)
    if args.json:
        print(json.dumps(results, ensure_ascii=False))
    else:
        for r in results:
            print(f"  {r['format']:>5} {r['size_mb']:>6.1f}MB  {r['file']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
