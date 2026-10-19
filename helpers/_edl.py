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


def select_render_record(blob: dict, digest: str | None, *,
                         allow_projected: bool = False) -> tuple:
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
    # Records written by duration_plan.py are analytic projections, not render
    # evidence. They are skipped by default so verify_delivery can never compare a
    # real file against a projection and call it verified; `allow_projected` is for
    # callers that only want to *report* that a projection exists.
    records = [(tag, entry) for tag, entry in blob.items()
               if isinstance(entry, dict) and isinstance(entry.get("durations"), list)
               and (allow_projected or not entry.get("projected"))]
    if not records:
        return None, None, "none"
    if digest:
        matching = [(tag, entry) for tag, entry in records
                    if entry.get("edl_sha256") == digest]
        if matching:
            tag, entry = matching[-1]
            return tag, entry, "projected" if entry.get("projected") else "digest"
        hashed = [(tag, entry) for tag, entry in records if entry.get("edl_sha256")]
        if hashed:
            return hashed[-1][0], hashed[-1][1], "mismatch"
    return records[-1][0], records[-1][1], "no-digest"


def render_record(edit_dir: Path, *, allow_projected: bool = False) -> tuple:
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
    return select_render_record(blob, digest, allow_projected=allow_projected)

def duration_record(edit_dir: Path, count: int, edl_path: Path | None = None
                    ) -> tuple[list[float] | None, str | None, str | None, str | None]:
    """One answer for "which durations should captions use?".

    Returns `(durations, source, tag, problem)`; `source` is `"measured"` or
    `"projected"`. Policy: the **latest** matching record whose segment count
    matches wins — the same record the delivery gates read. A record with the
    right digest but the wrong count is skipped (reported when nothing else
    fits), so one bad record cannot refuse a project that has a good one.

    `edl_path` matters: `srt_export --edl` may point at a different file than
    `edit_dir/edl.json`; the digest must be taken from the EDL actually in use.
    """
    edit_dir = Path(edit_dir)
    edl_file = Path(edl_path) if edl_path is not None else edit_dir / "edl.json"
    digest = edl_digest(edl_file) if edl_file.exists() else None
    blob = _load_duration_blob(edit_dir)
    if blob is None:
        return None, None, None, None

    def _candidates(allow_projected: bool):
        return [(tag, entry) for tag, entry in blob.items()
                if isinstance(entry, dict) and isinstance(entry.get("durations"), list)
                and (allow_projected or not entry.get("projected"))]

    hashed = [(t, e) for t, e in _candidates(True) if e.get("edl_sha256")]
    # Same policy as select_render_record: digest match wins; if no record carries a
    # digest at all (pre-digest projects), the newest record is the best guess; if
    # records carry digests but none matches, the render is stale — do not silently
    # fall back to a no-digest record.
    use_no_digest = not hashed and bool(digest)

    def _matching(allow_projected: bool):
        records = _candidates(allow_projected)
        if digest and not use_no_digest:
            return [(t, e) for t, e in records if e.get("edl_sha256") == digest]
        if use_no_digest:
            return [(t, e) for t, e in records if not e.get("edl_sha256")]
        return records

    for allow_projected, source in ((False, "measured"), (True, "projected")):
        records = _matching(allow_projected)
        if allow_projected:
            records = [(t, e) for t, e in records if e.get("projected")]
        count_problem = None
        for tag, entry in reversed(records):
            durations = [float(x) for x in entry["durations"]]
            if len(durations) == count:
                return durations, source, tag, None
            count_problem = f"{tag}: {len(durations)} 段，EDL 有 {count} 段"
        if count_problem:
            return None, None, None, count_problem

    hashed = [tag for tag, entry in blob.items()
              if isinstance(entry, dict) and entry.get("edl_sha256")]
    if hashed:
        return None, None, None, "segment_durations.json 是另一次 EDL 的渲染结果（哈希不符）"
    return None, None, None, None


def _load_duration_blob(edit_dir: Path):
    path = Path(edit_dir) / "segment_durations.json"
    if not path.exists():
        return None
    try:
        blob = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return blob if isinstance(blob, dict) else None
