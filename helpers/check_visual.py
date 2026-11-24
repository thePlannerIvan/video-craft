#!/usr/bin/env python3
"""Unified visual preflight and build quality gate for video-craft.

Aggregates composition/stage contract checks (`check_live_stage`), GSAP motion
target checks (`check_motion_targets`), on-screen text hygiene (`check_screen_text`),
and render environment checks (`check_render_env`) behind a single entrypoint.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

HELPERS = Path(__file__).resolve().parent
INTERNAL = HELPERS / "_internal"
for _p in (str(HELPERS), str(INTERNAL)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _run_tool(script: str, args: list[str]) -> tuple[int, str, str]:
    proc = subprocess.run(
        [sys.executable, str(INTERNAL / script), *args],
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def _parse_json_tail(text: str) -> dict | None:
    dec = json.JSONDecoder()
    for i in range(len(text)):
        if text[i] == "{" and (i == 0 or text[i - 1] == "\n"):
            try:
                obj, end = dec.raw_decode(text[i:])
                if isinstance(obj, dict) and not text[i + end :].strip():
                    return obj
            except ValueError:
                continue
    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="check_visual.py",
        description="Unified visual build quality gate (live-stage + motion-targets + screen-text + render-env)",
    )
    ap.add_argument("target", help="Project directory (or composition dir for --only render-env)")
    ap.add_argument("--composition", default=None, help="Optional composition subdirectory name")
    ap.add_argument(
        "--only",
        choices=("all", "live-stage", "motion-targets", "screen-text", "quality", "render-env", "fidelity"),
        default="all",
        help="Run a single check instead of the full preflight bundle",
    )
    ap.add_argument("--strict-transform", action="store_true", help="Treat static transform conflicts as errors")
    ap.add_argument("--max-static-s", type=float, default=8.0, help="Static segment error threshold (seconds)")
    ap.add_argument("--video", default=None, help="Rendered video path (used with --only fidelity)")
    ap.add_argument("--samples", type=int, default=12, help="Sample frame count for fidelity check")
    ap.add_argument("--json", action="store_true", help="Emit machine-readable JSON report")
    args = ap.parse_args(argv)

    target = Path(args.target)
    if not target.exists():
        print(f"not found: {target}", file=sys.stderr)
        return 2

    if args.only == "render-env":
        comp = target / (args.composition or "composition") if (target / (args.composition or "composition")).is_dir() else target
        cmd_args = [str(comp)] + (["--json"] if args.json else [])
        code, out, err = _run_tool("check_render_env.py", cmd_args)
        sys.stdout.write(out)
        sys.stderr.write(err)
        return code

    if args.only == "fidelity":
        if not args.video:
            print("--only fidelity requires --video <mp4>", file=sys.stderr)
            return 2
        cmd_args = [str(target), "--video", str(args.video), "--samples", str(args.samples)]
        if args.json:
            cmd_args.append("--json")
        code, out, err = _run_tool("check_render_fidelity.py", cmd_args)
        sys.stdout.write(out)
        sys.stderr.write(err)
        return code

    if args.only == "live-stage":
        cmd_args = [str(target)] + (["--composition", args.composition] if args.composition else []) + (["--json"] if args.json else [])
        code, out, err = _run_tool("check_live_stage.py", cmd_args)
        sys.stdout.write(out)
        sys.stderr.write(err)
        return code

    if args.only == "motion-targets":
        cmd_args = [str(target)] + (["--strict-transform"] if args.strict_transform else []) + (["--json"] if args.json else [])
        code, out, err = _run_tool("check_motion_targets.py", cmd_args)
        sys.stdout.write(out)
        sys.stderr.write(err)
        return code

    if args.only == "screen-text":
        cmd_args = [str(target)] + (["--json"] if args.json else [])
        code, out, err = _run_tool("check_screen_text.py", cmd_args)
        sys.stdout.write(out)
        sys.stderr.write(err)
        return code

    if args.only == "quality":
        cmd_args = (
            [str(target)]
            + (["--composition", args.composition] if args.composition else [])
            + ["--max-static-s", str(args.max_static_s)]
            + (["--json"] if args.json else [])
        )
        code, out, err = _run_tool("check_visual_quality.py", cmd_args)
        sys.stdout.write(out)
        sys.stderr.write(err)
        return code

    # Full bundle (`--only all`): run applicable static/build checks cleanly
    comp_dir = target / (args.composition or "composition")
    checks: list[dict] = []
    worst = 0

    ls_args = [str(target)] + (["--composition", args.composition] if args.composition else []) + ["--json"]
    if comp_dir.is_dir():
        code, out, err = _run_tool("check_live_stage.py", ls_args)
        checks.append({"check": "live-stage", "ok": code == 0, "code": code, "report": _parse_json_tail(out) or out.strip()})
        worst = max(worst, code)

        mt_args = [str(target)] + (["--strict-transform"] if args.strict_transform else []) + ["--json"]
        code, out, err = _run_tool("check_motion_targets.py", mt_args)
        checks.append({"check": "motion-targets", "ok": code == 0, "code": code, "report": _parse_json_tail(out) or out.strip()})
        worst = max(worst, code)

    if comp_dir.is_dir() or (target / "visual-plan.json").is_file():
        vq_args = (
            [str(target)]
            + (["--composition", args.composition] if args.composition else [])
            + ["--max-static-s", str(args.max_static_s), "--json"]
        )
        code, out, err = _run_tool("check_visual_quality.py", vq_args)
        checks.append({"check": "quality", "ok": code == 0, "code": code, "report": _parse_json_tail(out) or out.strip()})
        worst = max(worst, code)

    code, out, err = _run_tool("check_screen_text.py", [str(target), "--json"])
    checks.append({"check": "screen-text", "ok": code == 0, "code": code, "report": _parse_json_tail(out) or out.strip()})
    worst = max(worst, code)

    overall_ok = worst == 0
    if args.json:
        print(json.dumps({"ok": overall_ok, "project": str(target), "checks": checks}, ensure_ascii=False, indent=2))
    else:
        for item in checks:
            mark = "✓" if item["ok"] else "✗"
            print(f"{mark} {item['check']} (exit {item['code']})")
    return 0 if overall_ok else (2 if worst == 2 else 1)


if __name__ == "__main__":
    raise SystemExit(main())
