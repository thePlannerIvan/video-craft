#!/usr/bin/env python3
"""Resolve the external Style-Centric Video Vault (`~/.config/planners/video-vault`) using Style Card v3.

Decouples open-source `video-craft` from the author's private `_video-vault`:
1. `PLANNERS_VIDEO_VAULT` environment variable (if set; `none`/`off`/`0` forces fallback)
2. `~/.config/planners/video-vault` (symlink or directory)
3. Open-source fallback (`references/author-spec.md` + `references/style-spec.md`)

Usage:
    python3 helpers/_internal/resolve_vault.py [--style <style_id>] [--frame <frame_id>] [--vault <dir>] [--json]
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from _geometry import resolve_project_frame

SKILL_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REFS = SKILL_ROOT / "references"

STYLE_ALIASES = {
    "editorial-archive": "collage",
    "pinterest-neo-swiss-video": "line-art",
    "vans-harley": "lifestyle-cult",
    "harley-vans": "lifestyle-cult",
}


def find_vault_root(explicit: str | Path | None = None) -> Path | None:
    if explicit is not None:
        raw = str(explicit).strip()
        if not raw or raw.lower() in ("none", "off", "0"):
            return None
        p = Path(raw).expanduser()
        try:
            resolved = p.resolve()
            if (resolved / "manifest.json").is_file() and (resolved / "styles").is_dir():
                return resolved
        except OSError:
            return None
        return None

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


def _read_json_obj(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _resolve_existing_file(base: Path, rel: Any) -> Path | None:
    if not isinstance(rel, str) or not rel.strip():
        return None
    candidate = (base / rel.strip()).resolve()
    try:
        candidate.relative_to(base.resolve())
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def _resolve_anchors(style_dir: Path, raw_anchors: Any) -> list[dict[str, str]]:
    if not isinstance(raw_anchors, list):
        return []
    resolved: list[dict[str, str]] = []
    for item in raw_anchors:
        if not isinstance(item, dict):
            continue
        anchor_file = _resolve_existing_file(style_dir, item.get("path"))
        if anchor_file is None:
            continue
        entry: dict[str, str] = {"path": str(anchor_file)}
        label = item.get("label")
        if isinstance(label, str) and label.strip():
            entry["label"] = label.strip()
        resolved.append(entry)
    return resolved


def _has_declared_media(val: Any) -> bool:
    return isinstance(val, str) and bool(val.strip())


def _resolve_patterns(style_dir: Path, raw_patterns: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_patterns, list):
        return []
    resolved: list[dict[str, Any]] = []
    for item in raw_patterns:
        if isinstance(item, str):
            p = _resolve_existing_file(style_dir, item)
            if p is not None:
                resolved.append({"path": str(p)})
            continue
        if not isinstance(item, dict):
            continue
        raw_strip = item.get("strip")
        raw_webm = item.get("webm")
        raw_code = item.get("code")
        declared_any_media = any(_has_declared_media(v) for v in (raw_strip, raw_webm, raw_code))
        strip_file = _resolve_existing_file(style_dir, raw_strip)
        webm_file = _resolve_existing_file(style_dir, raw_webm)
        code_file = _resolve_existing_file(style_dir, raw_code)
        # Drop declared-media patterns whose referenced files are all missing on disk,
        # while retaining pure rule-only patterns that declare no media paths yet.
        if declared_any_media and strip_file is None and webm_file is None and code_file is None:
            continue
        entry: dict[str, Any] = {}
        for key in ("id", "title", "when_to_use", "rule"):
            val = item.get(key)
            if isinstance(val, str) and val.strip():
                entry[key] = val.strip()
        entry["strip"] = str(strip_file) if strip_file is not None else None
        entry["webm"] = str(webm_file) if webm_file is not None else None
        entry["code"] = str(code_file) if code_file is not None else None
        resolved.append(entry)
    return resolved


def resolve_vault(
    style_id: str | None = None,
    frame_id: str | None = None,
    vault_root: str | Path | None = None,
) -> dict[str, Any]:
    raw_style = (style_id or "line-art").strip()
    normalized = STYLE_ALIASES.get(raw_style, raw_style)
    requested_frame = frame_id.strip() if isinstance(frame_id, str) and frame_id.strip() else None
    resolved_vault_root = find_vault_root(vault_root)

    if resolved_vault_root is None:
        return {
            "available": False,
            "mode": "open-source-fallback",
            "standalone": True,
            "vault_root": None,
            "schema_version": "3.0.0",
            "requested_style": raw_style,
            "style_id": normalized,
            "default_capabilities": [],
            "author_spec_path": str(DEFAULT_REFS / "author-spec.md"),
            "voice_profile_path": None,
            "style_card_path": str(DEFAULT_REFS / "style-spec.md"),
            "preferences_path": str(DEFAULT_REFS / "preferences.md"),
            "palette": {},
            "anchors_dir": None,
            "anchors": [],
            "patterns_dir": None,
            "patterns": [],
            "preferred_frame": None,
            "frame_preset": requested_frame,
            "frame_preset_path": None,
            "frame_preset_paths": [],
            "frame_defaults": resolve_project_frame(None),
            "note": (
                "Private video-vault not mounted; using open-source Style Card v3 baseline "
                "references/author-spec.md and references/style-spec.md."
            ),
        }

    manifest = _read_json_obj(resolved_vault_root / "manifest.json")
    style_dir = resolved_vault_root / "styles" / normalized
    if not style_dir.is_dir():
        normalized = "line-art"
        style_dir = resolved_vault_root / "styles" / normalized

    meta = _read_json_obj(style_dir / "style.json")
    author_spec = resolved_vault_root / "global" / "author-spec.md"
    voice_profile = resolved_vault_root / "global" / "voice-profile.md"
    style_md = style_dir / "style.md"
    anchors_dir = style_dir / "anchors"
    patterns_dir = style_dir / "patterns"

    raw_palette = meta.get("palette")
    palette = (
        {str(k): str(v) for k, v in raw_palette.items() if isinstance(k, str) and isinstance(v, str)}
        if isinstance(raw_palette, dict)
        else {}
    )
    raw_caps = meta.get("default_capabilities")
    default_capabilities = (
        [str(c).strip() for c in raw_caps if isinstance(c, str) and c.strip()]
        if isinstance(raw_caps, list)
        else []
    )

    preferred_frame_raw = meta.get("preferred_frame")
    preferred_frame = (
        preferred_frame_raw.strip()
        if isinstance(preferred_frame_raw, str) and preferred_frame_raw.strip()
        else None
    )
    active_frame = requested_frame or preferred_frame
    frame_preset_path: str | None = None
    if active_frame:
        candidate_frame = resolved_vault_root / "frames" / f"{active_frame}.json"
        if candidate_frame.is_file():
            frame_preset_path = str(candidate_frame)

    return {
        "available": True,
        "mode": "private-vault",
        "standalone": False,
        "vault_root": str(resolved_vault_root),
        "schema_version": str(meta.get("schema_version") or manifest.get("schema_version") or "3.0.0"),
        "requested_style": raw_style,
        "style_id": normalized,
        "name": meta.get("name", normalized),
        "version": meta.get("version"),
        "default_capabilities": default_capabilities,
        "author_spec_path": str(author_spec if author_spec.is_file() else (DEFAULT_REFS / "author-spec.md")),
        "voice_profile_path": str(voice_profile) if voice_profile.is_file() else None,
        "style_card_path": str(style_md if style_md.is_file() else (DEFAULT_REFS / "style-spec.md")),
        "preferences_path": str(DEFAULT_REFS / "preferences.md"),
        "palette": palette,
        "anchors_dir": str(anchors_dir) if anchors_dir.is_dir() else None,
        "anchors": _resolve_anchors(style_dir, meta.get("anchors")),
        "patterns_dir": str(patterns_dir) if patterns_dir.is_dir() else None,
        "patterns": _resolve_patterns(style_dir, meta.get("patterns")),
        "preferred_frame": preferred_frame,
        "frame_preset": active_frame,
        "frame_preset_path": frame_preset_path,
        "frame_preset_paths": [frame_preset_path] if frame_preset_path else [],
        "frame_defaults": resolve_project_frame(None),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Resolve Style Card v3 rules, palette, anchors, and patterns from video-vault")
    parser.add_argument("--style", default="line-art", help="Style ID (e.g. line-art, concept-film, lifestyle-cult, studio-motion-ui)")
    parser.add_argument("--frame", default=None, help="Optional orthogonal frame preset ID")
    parser.add_argument("--vault", default=None, help="Optional explicit Style Vault path (or 'none' to force fallback)")
    parser.add_argument("--json", action="store_true", help="Output JSON (default)")
    args = parser.parse_args(argv)

    info = resolve_vault(args.style, args.frame, vault_root=args.vault)
    print(json.dumps(info, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
