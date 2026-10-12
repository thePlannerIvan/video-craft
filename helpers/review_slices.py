#!/usr/bin/env python3
"""Cut the composite into per-step review slices, so the page loads only a window.

The review host transfers whole files; it does not stream and does not do range
requests. A 4-minute composite is therefore a single all-or-nothing download even
when the reviewer is looking at one 6-second step.

Slicing is done with `-c copy` from the keyframe at or before each step, so it costs
no re-encode. A stream copy cannot start mid-GOP, so each slice's real start is the
keyframe, not the step boundary — the manifest records BOTH, and the page maps step
time to `slice file + (t - sliceStartMs)`. Recording the truth is the whole point:
a slice that claims to start at the step boundary while actually starting 0.4s
earlier silently shifts every annotation on the page.

Usage:
    python3 helpers/review_slices.py <project_root> [--composite <rel path>]
                                     [--edit <edit dir>] [--force] [--json]
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

SLICE_DIR = "slices"
MANIFEST = "slices.json"


def _probe_keyframes(media: Path) -> list[float]:
    """Presentation timestamps (seconds) of the media's key frames."""
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-skip_frame", "nokey", "-show_entries", "frame=pts_time",
         "-of", "csv=p=0", str(media)],
        capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe 读不到关键帧：{media.name}")
    out = []
    for line in proc.stdout.splitlines():
        value = line.strip().rstrip(",")
        if not value:
            continue
        try:
            out.append(float(value))
        except ValueError:
            continue
    return sorted(out)


def _probe_duration(media: Path) -> float:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(media)],
        capture_output=True, text=True)
    try:
        return float((proc.stdout or "0").strip())
    except ValueError:
        return 0.0


def _keyframe_at_or_before(keyframes: list[float], t: float) -> float:
    best = 0.0
    for kf in keyframes:
        if kf <= t + 1e-3:
            best = kf
        else:
            break
    return best


def build_slices(project_root: Path, *, composite_rel: str, steps: list[dict],
                 force: bool = False) -> dict:
    """Write per-step slices + a manifest. Returns the manifest payload."""
    project_root = Path(project_root).resolve()
    composite = (project_root / composite_rel).resolve()
    if not composite.is_file():
        raise SystemExit(f"✗ 找不到复合片：{composite}")
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        raise SystemExit("✗ PATH 上没有 ffmpeg/ffprobe")

    out_dir = project_root / "review" / SLICE_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    # On a cloud-synced workspace (OneDrive) a directory created and written to in
    # the same breath was not visible to the next process: ffmpeg died with
    # "Error opening output ... No such file or directory" (exit 254) even though
    # mkdir had just succeeded. Verify, and retry once, rather than silently
    # producing no slices.
    if not out_dir.is_dir():
        out_dir.mkdir(parents=True, exist_ok=True)
    if not out_dir.is_dir():
        raise RuntimeError(f"切片段目录建不出来：{out_dir}")
    keyframes = _probe_keyframes(composite)
    total = _probe_duration(composite)

    entries = []
    for step in steps:
        step_id = str(step.get("id") or step.get("stepId") or "step")
        start_s = max(0.0, float(step.get("startMs", 0)) / 1000.0)
        end_s = max(start_s, float(step.get("endMs", 0)) / 1000.0)
        kf = _keyframe_at_or_before(keyframes, start_s)
        target = out_dir / f"{step_id}.mp4"
        if force or not target.is_file() or target.stat().st_mtime < composite.stat().st_mtime:
            subprocess.run(
                ["ffmpeg", "-v", "error", "-y", "-ss", f"{kf:.3f}", "-i", str(composite),
                 "-t", f"{max(0.05, end_s - kf):.3f}",
                 "-c", "copy", "-avoid_negative_ts", "make_zero", str(target)],
                check=True)
        # The REAL start is what the file contains, not what we wished for.
        real_ms = int(round(kf * 1000))
        entries.append({
            "stepId": step_id,
            "file": f"review/{SLICE_DIR}/{target.name}",
            "startMs": real_ms,
            "endMs": int(round(end_s * 1000)),
            "stepStartMs": int(round(start_s * 1000)),
            "stepEndMs": int(round(end_s * 1000)),
            "keyframeLeadMs": int(round((start_s - kf) * 1000)),
            "durationS": round(_probe_duration(target), 3),
        })

    manifest = {
        "version": "review-slices/1.0.0",
        "composite": composite_rel,
        "compositeDurationS": round(total, 3),
        "sliceCount": len(entries),
        "slices": entries,
    }
    (project_root / "review" / MANIFEST).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return manifest


def load_manifest(project_root: Path) -> dict | None:
    path = Path(project_root) / "review" / MANIFEST
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description="按步切片，供审阅页只加载当前窗口")
    ap.add_argument("project_root", type=Path)
    ap.add_argument("--composite", default=None, help="相对项目根的复合片路径")
    ap.add_argument("--edit", type=Path, default=None)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    root = args.project_root.resolve()
    edit = (args.edit or (root / "edit")).resolve()
    timeline_path = root / "timeline" / "timeline.json"
    if not timeline_path.is_file():
        raise SystemExit(f"✗ 没有时间脊柱：{timeline_path}")
    timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
    steps = [s for ch in timeline.get("chapters", []) for s in ch.get("steps", [])]

    composite_rel = args.composite
    if composite_rel is None:
        media_file = root / "review" / "media.json"
        if media_file.is_file():
            declared = json.loads(media_file.read_text(encoding="utf-8"))
            composite_rel = declared.get("compositeVideo")
        composite_rel = composite_rel or f"{edit.name}/final.mp4"

    manifest = build_slices(root, composite_rel=composite_rel, steps=steps,
                            force=args.force)
    if args.json:
        print(json.dumps(manifest, ensure_ascii=False))
    else:
        lead = max((s["keyframeLeadMs"] for s in manifest["slices"]), default=0)
        print(f"切片 {manifest['sliceCount']} 个 → review/{SLICE_DIR}/"
              f"（最大关键帧提前量 {lead}ms，manifest: review/{MANIFEST}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
