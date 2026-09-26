#!/usr/bin/env python3
"""Local server for the EDL timeline preview.

Serves the common root of <edit_dir> and its source files (computed from
edl.json) statically, with HTTP Range support so the video player can
seek. Default page is the relative path to edl_preview.html. The handler
only ever serves files that live inside that root (strict containment),
so the page can reach raw footage stored next to the edit dir.

Usage: edl_preview_serve.py <edit_dir> [port]
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime
from urllib.parse import quote, unquote
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

if any(a in ("-h", "--help") for a in sys.argv[1:]):
    print(__doc__)
    print("Usage: edl_preview_serve.py <edit_dir> [port]")
    sys.exit(0)

EDIT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd().resolve()
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8737

edl = json.load(open(EDIT / "edl.json", encoding="utf-8"))
src_paths = [((EDIT / v) if not Path(v).is_absolute() else Path(v)).resolve()
             for v in edl["sources"].values()]
ROOT = Path(os.path.commonpath([EDIT, *src_paths]))
PAGE_REL = (EDIT.relative_to(ROOT) / "edl_preview.html").as_posix()

CTYPES = {".html": "text/html", ".json": "application/json", ".js": "text/javascript",
          ".css": "text/css", ".png": "image/png", ".mp4": "video/mp4",
          ".mov": "video/quicktime"}


def in_root(candidate: Path) -> bool:
    try:
        candidate.relative_to(ROOT)
        return True
    except ValueError:
        return False


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = unquote(self.path.split("?")[0])
        if path == "/":
            path = "/" + PAGE_REL
        f = (ROOT / path.lstrip("/")).resolve()
        if not f.is_file() or not in_root(f):
            self.send_response(404)
            self.end_headers()
            return
        size = f.stat().st_size
        ctype = CTYPES.get(f.suffix, "application/octet-stream")

        rng = self.headers.get("Range")
        if rng:
            m = re.match(r"bytes=(\d*)-(\d*)", rng)
            if not m:
                self.send_response(416)
                self.end_headers()
                return
            start = int(m.group(1)) if m.group(1) else 0
            end = int(m.group(2)) if m.group(2) else size - 1
            end = min(end, size - 1)
            if start >= size or start > end:
                self.send_response(416)
                self.end_headers()
                return
            length = end - start + 1
            self.send_response(206)
            self.send_header("Content-Type", ctype + "; charset=utf-8")
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", length)
            self.end_headers()
            with open(f, "rb") as fh:
                fh.seek(start)
                remaining = length
                while remaining:
                    chunk = fh.read(min(65536, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
            return

        self.send_response(200)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", size)
        self.end_headers()
        with open(f, "rb") as fh:
            while True:
                chunk = fh.read(65536)
                if not chunk:
                    break
                self.wfile.write(chunk)

    def do_POST(self):
        if self.path != "/api/save":
            self.send_response(404)
            self.end_headers()
            return
        n = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(n))
        except json.JSONDecodeError:
            self.send_response(400)
            self.end_headers()
            return
        target = self._resolve_save_dir(body)
        if target is None:
            self.send_response(404)
            self.end_headers()
            return
        if (target / "selections.json").exists():
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup = target / f"selections.backup-{stamp}.json"
            backup.write_text((target / "selections.json").read_text(encoding="utf-8"), encoding="utf-8")
        (target / "selections.json").write_text(
            json.dumps(body, ensure_ascii=False, indent=1), encoding="utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok": true}')

    def _resolve_save_dir(self, body: dict) -> Path | None:
        """The page posts its own project dir so one shared-root server can
        serve several edit dirs without saves landing in the startup dir.
        Browser location.pathname keeps non-ASCII paths percent-encoded, so
        the posted dir must be unquoted before touching the filesystem."""
        req_dir = unquote(body.get("dir") or "")
        if not req_dir:
            return EDIT
        cand = (ROOT / req_dir.lstrip("/")).resolve()
        if in_root(cand) and (cand / "edl.json").is_file():
            return cand
        return None

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    url = f"http://localhost:{PORT}/{quote(PAGE_REL)}"
    print(f"EDL preview server on {url}")
    # User preference: auto-open the review page in the default browser.
    # Pass --no-open to skip (headless/CI or when a stale page would confuse).
    if "--no-open" not in sys.argv:
        import threading
        import webbrowser

        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
