#!/usr/bin/env python3
"""Project the rendered timeline analytically, so nothing has to wait for a render.

Why this exists
---------------
`segment_durations.json` is written by `render.py`, and both the caption builder
and the visual timeline refuse to work without it. That coupling made a full
render a prerequisite for even *looking* at the film: no captions, no timeline
spine, no review surface until the whole thing had been encoded once.

The durations are not actually unknowable before the render. A segment's length on
the output grid is **`ceil(raw_duration * fps) / fps`** — the encoder rounds UP onto
the frame grid, and the drift that motivated the measured record was that per-segment
ceiling accumulating to a full second over 38 segments.

The formula is not a guess. Re-derived against a real render on the 图拉斯 project
(`segment_durations.json["master_final"]`), `ceil` reproduces **14 of 14** segment
durations exactly, while `round` reproduces only 6 — so the projection is exact for
this renderer, and "measured" is worth keeping mainly to catch a renderer change.

Projected vs measured
---------------------
A projected record carries `"projected": true` and is deliberately weaker:

  * it MAY build project-state artifacts — captions to review, the visual timeline,
    the review surface — so the edit can be judged before it is rendered;
  * it may NOT be presented as delivery evidence. `_edl.select_render_record`
    ignores projected records by default, so `verify_delivery.py` still compares the
    real file against a real render. A projection can never stand in for that.

Usage:
    python3 helpers/duration_plan.py <edit_dir> [--fps 30] [--force] [--json]

Writes one extra key (`plan`) into `segment_durations.json`; existing records are
left untouched.
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _edl import edl_digest, load_edl  # noqa: E402

PLAN_KEY = "plan"
DEFAULT_FPS = 30.0


def _probe_fps(media: Path) -> float | None:
    if shutil.which("ffprobe") is None or not media.exists():
        return None
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=r_frame_rate", "-of", "default=nw=1:nk=1", str(media)],
        capture_output=True, text=True)
    raw = (proc.stdout or "").strip()
    if "/" not in raw:
        return None
    num, den = raw.split("/", 1)
    try:
        value = float(num) / float(den)
    except (ValueError, ZeroDivisionError):
        return None
    return round(value, 6) if value > 0 else None


def resolve_fps(edit_dir: Path, edl: dict, fps: float | None = None) -> float:
    """FPS the render would use: explicit > an existing record > the source > 30."""
    if fps:
        return float(fps)
    record = edit_dir / "segment_durations.json"
    if record.exists():
        try:
            blob = json.loads(record.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            blob = {}
        for entry in blob.values():
            if isinstance(entry, dict) and entry.get("fps"):
                return float(entry["fps"])
    for path_str in (edl.get("sources") or {}).values():
        media = Path(path_str)
        if not media.is_absolute():
            media = (edit_dir / media).resolve()
        probed = _probe_fps(media)
        if probed:
            return probed
    return DEFAULT_FPS


def plan_durations(edit_dir: Path, fps: float | None = None) -> tuple[list[float], float]:
    """Frame-quantised per-range durations, in output order."""
    edit_dir = Path(edit_dir).resolve()
    edl = load_edl(edit_dir)
    rate = resolve_fps(edit_dir, edl, fps)
    durations = []
    for r in edl["ranges"]:
        raw = (float(r["end"]) - float(r["start"])) / float(r.get("speed", 1.0) or 1.0)
        # ceil, not round: the encoder lands ON or AFTER the requested time.
        # The inner round only removes float noise (8.8*30 = 264.00000000000006
        # must stay 264, not become 265).
        # 1e-3 frame of noise is below any real frame boundary but above
        # the error a six-decimal source duration can introduce (0.5e-6*30).
        frames = max(1, math.ceil(raw * rate - 1e-3))
        durations.append(round(frames / rate, 6))
    return durations, rate


def write_plan(edit_dir: Path, fps: float | None = None, *,
               force: bool = False) -> dict:
    """Record the projection under `segment_durations.json["plan"]`."""
    edit_dir = Path(edit_dir).resolve()
    edl_path = edit_dir / "edl.json"
    digest = edl_digest(edl_path)
    record_path = edit_dir / "segment_durations.json"
    try:
        blob = json.loads(record_path.read_text(encoding="utf-8")) if record_path.exists() else {}
    except json.JSONDecodeError:
        blob = {}
    if not isinstance(blob, dict):
        blob = {}

    existing = blob.get(PLAN_KEY)
    if (isinstance(existing, dict) and existing.get("edl_sha256") == digest
            and not force):
        return {"action": "unchanged", "key": PLAN_KEY, "durations": existing["durations"],
                "total_s": existing["total_s"], "fps": existing["fps"],
                "path": str(record_path)}

    durations, rate = plan_durations(edit_dir, fps)
    blob[PLAN_KEY] = {
        "durations": durations,
        "total_s": round(sum(durations), 6),
        "edl_sha256": digest,
        "fps": rate,
        # The whole point: consumers must be able to tell this apart from a render.
        "projected": True,
    }
    record_path.write_text(json.dumps(blob, ensure_ascii=False, indent=1) + "\n",
                           encoding="utf-8")
    return {"action": "written", "key": PLAN_KEY, "durations": durations,
            "total_s": blob[PLAN_KEY]["total_s"], "fps": rate,
            "path": str(record_path)}


def main() -> int:
    ap = argparse.ArgumentParser(description="解析计算各段时长（预演，不渲染）")
    ap.add_argument("edit_dir", type=Path)
    ap.add_argument("--fps", type=float, default=None)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    record = write_plan(args.edit_dir, args.fps, force=args.force)
    if args.json:
        print(json.dumps(record, ensure_ascii=False))
    else:
        verb = {"written": "已写入", "unchanged": "已是最新"}[record["action"]]
        print(f"{verb}解析预演：{len(record['durations'])} 段 / "
              f"{record['total_s']:.3f}s @ {record['fps']:g}fps → segment_durations.json"
              f"[{record['key']}]（projected，不能作为交付证据）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
