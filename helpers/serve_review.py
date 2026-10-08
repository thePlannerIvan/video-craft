#!/usr/bin/env python3
"""Compatibility CLI for the public review host; no private HTTP server.

Usage: python3 helpers/serve_review.py <project> [--open] [--port 0]
Use review_surface.py --surface-only when DSH provides review_open.
"""
import argparse
import json
from pathlib import Path

from build_review import build_review_data, resolve_project_paths, write_review_files
from review_surface import open_review


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project', type=Path)
    parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--open', action='store_true')
    args = parser.parse_args()
    root, edit = resolve_project_paths(args.project)
    write_review_files(root, build_review_data(root, edit))
    result = open_review(root, port=args.port, open_browser=args.open)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
