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
