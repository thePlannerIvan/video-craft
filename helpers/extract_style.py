#!/usr/bin/env python3
"""Standalone & Post-Delivery Video Style Extractor / Evolver (`video-craft`).

Supports two workflows from one entry point:
1. **Standalone Style Extraction (`--bootstrap`)**:
   Feed a reference video (`.mp4`/`.mov`) or completed video project to create a new style playbook
   (`style.json`, `idea.md`, `page.md`, `craft.md`, `style-board.jpg`, 3-frame `*-strip.jpg` for LLMs,
   and `2s` `.webm` hover previews for humans).
2. **Continuous Style Evolution (default / Step 11 hook)**:
   After finishing a video in `video-craft`, distill new rules, negative constraints, and pattern strips
   into an existing style (`line-art`, `lifestyle-cult`, `collage`, `business-report`, `concept-film`).

When the private vault (`~/.config/planners/video-vault`) is mounted, writes directly into the vault
and rebuilds `_video-vault/index.html`. When running in an open-source environment without the private
vault, writes a self-contained style pack to `--out-dir` (default: `./_extracted_styles/<style_id>`).

Usage:
    # Evolve an existing style after finishing a project (or from a new benchmark video)
    python3 helpers/extract_style.py --video <project_or_mp4> --style line-art --summary "新增双轴联动规则"

    # Extract a brand-new style from an external reference video
    python3 helpers/extract_style.py --bootstrap --video <ref.mp4> --style kinetic-typo \
        --name "高密度动能字卡风" --mode keyframe-svg \
        --summary "全屏字卡随重音节拍硬切缩放" --clip "p1-beat-slam:3.5:2.0"
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from resolve_vault import find_vault_root


def _find_video_file(target: Path) -> Path | None:
    if target.is_file() and target.suffix.lower() in (".mp4", ".mov", ".mkv", ".webm"):
        return target
    if target.is_dir():
        for sub in ("成品", "deliverable", "edit/_engineering", "edit", "."):
            d = target / sub
            if d.is_dir():
                mp4s = sorted(d.glob("*.mp4")) + sorted(d.glob("*.mov"))
                if mp4s:
                    return mp4s[0]
    return None


def _extract_local_media(video_path: Path, style_dir: Path, clips: list[str]) -> list[dict]:
    """Fallback ffmpeg extractor when private vault is not mounted."""
    board_jpg = style_dir / "style-board.jpg"
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(video_path),
            "-vf", "fps=1/3,scale=320:-1,tile=4x3",
            "-frames:v", "1", "-q:v", "4", str(board_jpg),
        ],
        capture_output=True, text=True,
    )
    patterns_dir = style_dir / "patterns"
    patterns_dir.mkdir(parents=True, exist_ok=True)
    extracted = []
    for idx, spec in enumerate(clips, 1):
        parts = spec.split(":")
        pat_id = parts[0] if parts[0] else f"p{idx}-pattern"
        start_s = float(parts[1]) if len(parts) > 1 else 2.0 * idx
        dur_s = float(parts[2]) if len(parts) > 2 else 2.0
        strip_jpg = patterns_dir / f"{pat_id}-strip.jpg"
        clip_webm = patterns_dir / f"{pat_id}.webm"
        fps = 3.0 / max(dur_s, 0.6)
        subprocess.run(
            [
                "ffmpeg", "-y", "-ss", f"{start_s:.2f}", "-t", f"{dur_s:.2f}",
                "-i", str(video_path),
                "-vf", f"fps={fps:.4f},scale=480:-1,tile=3x1",
                "-frames:v", "1", "-q:v", "4", str(strip_jpg),
            ],
            capture_output=True, text=True,
        )
        subprocess.run(
            [
                "ffmpeg", "-y", "-ss", f"{start_s:.2f}", "-t", f"{min(dur_s, 2.5):.2f}",
                "-i", str(video_path),
                "-an", "-vf", "scale=640:-2,fps=24",
                "-c:v", "libvpx-vp9", "-b:v", "600k", "-crf", "34",
                str(clip_webm),
            ],
            capture_output=True, text=True,
        )
        extracted.append({
            "id": pat_id,
            "strip": str(strip_jpg) if strip_jpg.is_file() else None,
            "webm": str(clip_webm) if clip_webm.is_file() else None,
        })
    return extracted


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract a new video style or evolve an existing style.")
    parser.add_argument("--video", "--project", dest="source", required=True,
                        help="Path to reference video (.mp4/.mov) or finished video project directory")
    parser.add_argument("--style", required=True,
                        help="Target style_id (e.g. line-art, lifestyle-cult, collage, or new slug with --bootstrap)")
    parser.add_argument("--summary", default="提炼视频风格规则与代表性动效招式",
                        help="Summary of extracted or evolved rules/patterns")
    parser.add_argument("--version", default=None, help="Optional explicit version string")
    parser.add_argument("--bootstrap", action="store_true",
                        help="Create a brand-new style playbook from this reference video/project")
    parser.add_argument("--name", default=None, help="Display name when bootstrapping a new style")
    parser.add_argument("--mode", choices=("keyframe-svg", "footage-montage"), default="keyframe-svg",
                        help="Production mode (`keyframe-svg` uses PPT Hell; `footage-montage` skips PPT Hell)")
    parser.add_argument("--clip", action="append", default=[],
                        help="Pattern clip to extract: <pattern_id>:<start_sec>:<dur_sec> (repeatable)")
    parser.add_argument("--out-dir", default=None,
                        help="Output directory when private vault is not mounted (default: ./_extracted_styles)")
    args = parser.parse_args(argv)

    source_path = Path(args.source).expanduser().resolve()
    if not source_path.exists():
        print(json.dumps({"ok": False, "error": f"输入路径不存在：{source_path}"}, ensure_ascii=False), file=sys.stderr)
        return 2

    vault_root = find_vault_root()
    if vault_root is not None and (vault_root / "scripts" / "evolve_style.py").is_file() and args.out_dir is None:
        evolve_script = vault_root / "scripts" / "evolve_style.py"
        cmd = [
            sys.executable, str(evolve_script),
            "--video", str(source_path),
            "--style", args.style,
            "--summary", args.summary,
            "--mode", args.mode,
        ]
        if args.version:
            cmd.extend(["--version", args.version])
        if args.bootstrap:
            cmd.append("--bootstrap")
        if args.name:
            cmd.extend(["--name", args.name])
        for c in args.clip:
            cmd.extend(["--clip", c])
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            print(res.stderr or res.stdout, file=sys.stderr)
            return res.returncode
        print(res.stdout.strip())
        return 0

    # Open-source / local directory extraction mode
    base_out = Path(args.out_dir).expanduser().resolve() if args.out_dir else (Path.cwd() / "_extracted_styles")
    style_dir = base_out / args.style
    style_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    source_name = source_path.stem if source_path.is_file() else source_path.name

    video_file = _find_video_file(source_path)
    extracted_clips = _extract_local_media(video_file, style_dir, args.clip) if video_file else []

    style_meta = {
        "style_id": args.style,
        "name": args.name or args.style,
        "version": args.version or f"v1.0 ({today})",
        "updated_at": today,
        "production_mode": args.mode,
        "evolved_from_projects": [source_name],
        "positioning": args.summary,
        "patterns": extracted_clips,
    }
    (style_dir / "style.json").write_text(json.dumps(style_meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for stage_file, stage_title in (("idea.md", "创意与分镜规则"), ("page.md", "静态画面规则"), ("craft.md", "动效与剪辑合成规则")):
        p = style_dir / stage_file
        if not p.is_file():
            p.write_text(f"# `{args.style}` · {stage_title}\n\n- **Rule 1**：{args.summary}\n", encoding="utf-8")

    print(json.dumps({
        "ok": True,
        "mode": "local-style-pack",
        "style_id": args.style,
        "style_dir": str(style_dir),
        "extracted_clips": extracted_clips,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
