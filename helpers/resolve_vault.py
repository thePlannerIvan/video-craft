#!/usr/bin/env python3
"""Resolve the external Style-Centric Video Vault (`~/.config/planners/video-vault`).

Decouples open-source `video-craft` from the author's private `_video-vault`:
1. `PLANNERS_VIDEO_VAULT` environment variable (if set; `none`/`off`/`0` forces fallback)
2. `~/.config/planners/video-vault` (symlink or directory)
3. Open-source fallback (`references/author-spec.md` + `references/style-spec.md`)

Usage:
    python3 helpers/resolve_vault.py [--style <style_id>] [--frame <frame_id>] [--json]
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from style_vault import frame_presets

SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REFS = SKILL_ROOT / "references"

STYLE_ALIASES = {
    "editorial-archive": "collage",
    "pinterest-neo-swiss-video": "line-art",
    "vans-harley": "lifestyle-cult",
    "harley-vans": "lifestyle-cult",
}

FALLBACK_PRODUCTION_MODES = {
    "line-art": "keyframe-svg",
    "collage": "keyframe-svg",
    "business-report": "keyframe-svg",
    "concept-film": "keyframe-svg",
    "lifestyle-cult": "footage-montage",
    "default-clean": "keyframe-svg",
}


def find_vault_root() -> Path | None:
    env_override = os.environ.get("PLANNERS_VIDEO_VAULT")
    if env_override is not None:
        if not env_override.strip() or env_override.strip().lower() in ("none", "off", "0"):
            return None
        p = Path(env_override).expanduser()
        try:
            resolved = p.resolve()
            if (resolved / "manifest.json").is_file() and (resolved / "styles").is_dir():
                return resolved
        except OSError:
            return None
        return None

    candidate = Path.home() / ".config" / "planners" / "video-vault"
    try:
        resolved = candidate.resolve()
        if (resolved / "manifest.json").is_file() and (resolved / "styles").is_dir():
            return resolved
    except OSError:
        return None
    return None


def resolve_vault(style_id: str | None = None, frame_id: str | None = None) -> dict[str, Any]:
    raw_style = (style_id or "line-art").strip()
    normalized = STYLE_ALIASES.get(raw_style, raw_style)
    vault_root = find_vault_root()

    if vault_root is None:
        prod_mode = FALLBACK_PRODUCTION_MODES.get(normalized, "keyframe-svg")
        return {
            "available": False,
            "mode": "open-source-fallback",
            "vault_root": None,
            "requested_style": raw_style,
            "style_id": normalized,
            "production_mode": prod_mode,
            "craft_type": "montage" if prod_mode == "footage-montage" else "graphic",
            "author_spec_path": str(DEFAULT_REFS / "author-spec.md"),
            "craft_rules_path": str(DEFAULT_REFS / "style-spec.md"),
            "page_rules_path": None,
            "patterns_dir": None,
            "patterns": [],
            "frame_preset": frame_id,
            "frame_preset_path": None,
            "frame_preset_paths": [],
            "extract_script_path": str(SKILL_ROOT / "helpers" / "extract_style.py"),
            "note": (
                "Private video-vault not mounted; using open-source baseline "
                "references/author-spec.md and references/style-spec.md."
            ),
        }

    style_dir = vault_root / "styles" / normalized
    if not style_dir.is_dir():
        normalized = "line-art"
        style_dir = vault_root / "styles" / normalized

    meta: dict[str, Any] = {}
    meta_path = style_dir / "style.json"
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            meta = {}

    prod_mode = meta.get("production_mode") or FALLBACK_PRODUCTION_MODES.get(normalized, "keyframe-svg")
    author_spec = vault_root / "global" / "author-spec.md"
    craft_md = style_dir / "craft.md"
    page_md = style_dir / "page.md"
    patterns_dir = style_dir / "patterns"
    patterns: list[str] = []
    if patterns_dir.is_dir():
        patterns = [str(p) for p in sorted(patterns_dir.iterdir()) if p.is_file() and not p.name.startswith(".")]

    declared_presets = [frame_id] if frame_id else frame_presets(meta)
    resolved_frame_paths: list[str] = []
    for preset in declared_presets:
        if not preset:
            continue
        candidate_frame = vault_root / "frames" / f"{preset}.json"
        if candidate_frame.is_file():
            resolved_frame_paths.append(str(candidate_frame))

    return {
        "available": True,
        "mode": "private-vault",
        "vault_root": str(vault_root),
        "requested_style": raw_style,
        "style_id": normalized,
        "name": meta.get("name", normalized),
        "production_mode": prod_mode,
        "craft_type": "montage" if prod_mode == "footage-montage" else "graphic",
        "author_spec_path": str(author_spec if author_spec.is_file() else (DEFAULT_REFS / "author-spec.md")),
        "craft_rules_path": str(craft_md if craft_md.is_file() else (DEFAULT_REFS / "style-spec.md")),
        "page_rules_path": str(page_md) if page_md.is_file() else None,
        "patterns_dir": str(patterns_dir) if patterns_dir.is_dir() else None,
        "patterns": patterns,
        "params": meta.get("params", {}),
        "frame_preset": declared_presets[0] if declared_presets else None,
        "frame_preset_path": resolved_frame_paths[0] if resolved_frame_paths else None,
        "frame_preset_paths": resolved_frame_paths,
        "extract_script_path": str(SKILL_ROOT / "helpers" / "extract_style.py"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Resolve active style rules and patterns from video-vault")
    parser.add_argument("--style", default="line-art", help="Style ID (e.g. line-art, lifestyle-cult, collage)")
    parser.add_argument("--frame", default=None, help="Optional frame preset ID")
    parser.add_argument("--json", action="store_true", help="Output JSON (default)")
    args = parser.parse_args(argv)

    info = resolve_vault(args.style, args.frame)
    print(json.dumps(info, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
