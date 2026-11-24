#!/usr/bin/env python3
"""Derive an alternate camera EDL from one canonical EDL.

Same ranges, same speed/mute, source time shifted by a fixed sync offset.
This is the only supported way to keep multi-camera cuts in sync.

Usage:
    python helpers/mirror_edl.py canonical.json -o selfie.json \
        --source VID_001 --path /abs/VID_001.MP4 --offset 2.04
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("edl", type=Path)
    ap.add_argument("-o", "--output", type=Path, required=True)
    ap.add_argument("--source", required=True, help="source key in the derived EDL")
    ap.add_argument("--path", required=True, help="absolute path to the alternate camera file")
    ap.add_argument("--offset", type=float, default=0.0, help="seconds to shift source start/end")
    args = ap.parse_args()

    edl = json.loads(args.edl.read_text(encoding="utf-8"))
    out = dict(edl)
    out["sources"] = {args.source: args.path}
    out["ranges"] = [
        dict(
            r,
            source=args.source,
            start=round(r["start"] + args.offset, 3),
            end=round(r["end"] + args.offset, 3),
        )
        for r in edl["ranges"]
    ]
    out["total_duration_s"] = round(
        sum((r["end"] - r["start"]) / r.get("speed", 1.0) for r in out["ranges"]), 2
    )
    args.output.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"mirrored EDL → {args.output} ({len(out['ranges'])} ranges, {out['total_duration_s']}s)")


if __name__ == "__main__":
    main()
