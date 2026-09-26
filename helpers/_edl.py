#!/usr/bin/env python3
"""Canonical EDL identity — one definition shared by every contract.

`edl_digest()` is sha256 over the EDL file's bytes. The render pipeline writes
it next to the measured segment durations, and both the caption builder and the
EDL health check compare against it. A single definition means "is this render
stale?" has one answer; before, the render wrote durations nobody consumed and
the caption timeline silently assumed the render matched the EDL.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def edl_digest(edl_path: Path) -> str:
    return hashlib.sha256(Path(edl_path).read_bytes()).hexdigest()


def load_edl(edit_dir: Path) -> dict:
    path = Path(edit_dir) / "edl.json"
    if not path.exists():
        raise SystemExit(f"no edl.json in {edit_dir}")
    return json.loads(path.read_text(encoding="utf-8"))


def select_render_record(blob: dict, digest: str | None) -> tuple:
    """Pick the render record that belongs to THIS EDL.

    `segment_durations.json` accumulates one key per output name — `poc`,
    `draft`, `draft2`, `mix-base`, `final`. Picking a key by iteration order made
    both delivery gates read the `poc` run's 12 seconds and call a correct
    84-second film "possibly truncated or replaced". The EDL's digest identifies
    the record; earlier keys stay for humans and do not vote.

    Returns `(tag, entry, how)`:

    - `"digest"`  — the record whose `edl_sha256` is this EDL's digest
    - `"mismatch"`— records carry digests and none matches: the render is stale
    - `"no-digest"` — older records without a digest; the newest is the best guess
    - `"none"`    — nothing usable in the file
    """
    records = [(tag, entry) for tag, entry in blob.items()
               if isinstance(entry, dict) and isinstance(entry.get("durations"), list)]
    if not records:
        return None, None, "none"
    if digest:
        matching = [(tag, entry) for tag, entry in records
                    if entry.get("edl_sha256") == digest]
        if matching:
            return matching[-1][0], matching[-1][1], "digest"
        hashed = [(tag, entry) for tag, entry in records if entry.get("edl_sha256")]
        if hashed:
            return hashed[-1][0], hashed[-1][1], "mismatch"
    return records[-1][0], records[-1][1], "no-digest"


def render_record(edit_dir: Path) -> tuple:
    """`select_render_record` over `<edit_dir>/segment_durations.json`."""
    path = Path(edit_dir) / "segment_durations.json"
    if not path.exists():
        return None, None, "none"
    try:
        blob = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None, None, "unparsable"
    if not isinstance(blob, dict):
        return None, None, "none"
    edl_path = Path(edit_dir) / "edl.json"
    digest = edl_digest(edl_path) if edl_path.exists() else None
    return select_render_record(blob, digest)
