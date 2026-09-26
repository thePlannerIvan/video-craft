#!/usr/bin/env python3
"""Copy final videos + SRT out of edit/ into a delivery folder."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("edit_dir", type=Path)
    ap.add_argument("--out", type=Path, default=None,
                    help="delivery dir; default is <videos_dir>/成品")
    ap.add_argument("--videos", nargs="+", default=[], help="filenames inside edit_dir")
    ap.add_argument("--srt", nargs="+", default=[], help="SRT filenames inside edit_dir")
    args = ap.parse_args()

    edit = args.edit_dir.resolve()
    out = args.out.resolve() if args.out else edit.parent / "成品"
    out.mkdir(parents=True, exist_ok=True)

    for name in list(args.videos) + list(args.srt):
        src = edit / name
        if not src.exists():
            raise SystemExit(f"missing deliverable: {src}")
        shutil.copy2(src, out / name)
        print(f"  → {out / name}")
    print(f"deliverables in {out}")


if __name__ == "__main__":
    main()
