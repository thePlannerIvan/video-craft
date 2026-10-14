#!/usr/bin/env python3
"""Collect what the author writes in the HyperFrames studio, as a file.

Why this exists
---------------
The studio is already the best review surface we have: edit a file, it reloads,
you see it. It also has "Describe a change to the agent" — but that affordance only
builds a prompt and puts it on the **clipboard** (`navigator.clipboard.writeText`),
so the note dies unless the author pastes it back into the conversation. Nothing
ever reaches the project.

We do not modify HyperFrames. We do not need to. The studio loads the composition
in an iframe with `allow-scripts allow-same-origin` (verified), so the composition —
which *is* our file — shares the studio's origin and can wrap the parent's
`navigator.clipboard.writeText`. The wrap still writes the clipboard exactly as
before; it also POSTs the text here. See
`visual/assets/composition-studio-hook.js`.

Interface
---------
    studio_notes.py <project> [--port 4319] [--stop]     # 起收集器（默认动作）
    studio_notes.py <project> --tail 20 [--json]         # 读回收到的意见
    studio_notes.py <project> --clear

Notes land in `<project>/edit/_engineering/studio-notes.jsonl`, one JSON object per
line: `{"ts", "kind", "chars", "text"}`.

Deliberately not doing: parsing the studio's prompt format (we store it verbatim —
the format belongs to HyperFrames and will change), and deciding what a note means
(that is the agent's job, reading the file).
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DEFAULT_PORT = 4319
NOTES_REL = "edit/_engineering/studio-notes.jsonl"
PID_REL = "edit/_engineering/studio-notes.pid"
MAX_BODY = 1 << 20          # 1 MiB：一条意见不该比这更大


def notes_path(project: Path) -> Path:
    return project / NOTES_REL


def append_note(project: Path, text: str, kind: str = "studio",
                where: dict | None = None) -> dict | None:
    """Append one note. Blank text is refused here, not only at the HTTP edge —
    a file full of empty lines is worse than no file, and the next caller will
    forget the guard."""
    text = (text or "").strip()
    if not text:
        return None
    record = {"ts": round(time.time(), 3), "kind": kind,
              "chars": len(text), "text": text}
    for key in ("t", "stepId", "cueIndex", "anchor"):
        if where and where.get(key) is not None:
            record[key] = where[key]
    path = notes_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def make_handler(project: Path):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _cors(self):
            # studio 页在 http://127.0.0.1:<preview port>，与这里不同端口 —— 必须放行，
            # 否则 fetch 会被浏览器拦下，我们只在本地回环上服务，没有对外的面。
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "content-type")
            self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")

        def do_OPTIONS(self):                                   # noqa: N802
            self.send_response(204)
            self._cors()
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_POST(self):                                      # noqa: N802
            if self.path.rstrip("/") not in ("/note", ""):
                self.send_response(404)
                self._cors()
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            length = int(self.headers.get("content-length") or 0)
            if length <= 0 or length > MAX_BODY:
                self.send_response(413)
                self._cors()
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            raw = self.rfile.read(length).decode("utf-8", "replace")
            try:
                payload = json.loads(raw)
            except ValueError:
                payload = {"text": raw}
            rec = append_note(project, str(payload.get("text") or ""),
                              str(payload.get("kind") or "studio"), payload)
            if rec:
                print(f"  + 收到一条意见（{rec['chars']} 字）→ {NOTES_REL}", flush=True)
            body = b'{"ok":true}'
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):                                       # noqa: N802
            if self.path.rstrip("/") == "/health":
                body = b'{"ok":true}'
                self.send_response(200)
                self._cors()
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_response(404)
            self._cors()
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *args):                            # 静音：不要每请求一行
            pass

    return Handler


def serve(project: Path, port: int) -> int:
    pid_file = project / PID_REL
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    if pid_file.exists():
        try:
            old = int(pid_file.read_text().strip())
            os.kill(old, 0)
            print(f"收集器已在运行（PID {old}）。要重起先 --stop。")
            return 0
        except (ValueError, ProcessLookupError, PermissionError):
            pid_file.unlink(missing_ok=True)

    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(project))
    pid_file.write_text(str(os.getpid()))
    url = f"http://127.0.0.1:{port}/note"
    print(f"studio 意见收集器 → {url}")
    print(f"  落盘 {NOTES_REL}；读回：studio_notes.py <project> --tail 20")
    print(f"  停掉：studio_notes.py <project> --stop")

    def bye(*_a):
        pid_file.unlink(missing_ok=True)
        server.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGTERM, bye)
    signal.signal(signal.SIGINT, bye)
    try:
        server.serve_forever()
    finally:
        pid_file.unlink(missing_ok=True)
    return 0


def stop(project: Path) -> int:
    pid_file = project / PID_REL
    if not pid_file.exists():
        print("没有在跑的收集器")
        return 0
    pid = int(pid_file.read_text().strip())
    try:
        os.kill(pid, signal.SIGTERM)
        print(f"已停 PID {pid}")
    except ProcessLookupError:
        print(f"PID {pid} 不在了，清掉残留标记")
    pid_file.unlink(missing_ok=True)
    return 0


def tail(project: Path, n: int, as_json: bool) -> int:
    path = notes_path(project)
    if not path.is_file():
        print(f"还没有意见（{NOTES_REL} 不存在）")
        return 0
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    rows = []
    for ln in lines[-n:]:
        try:
            rows.append(json.loads(ln))
        except ValueError:
            rows.append({"ts": 0, "kind": "raw", "text": ln})
    if as_json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        for r in rows:
            stamp = time.strftime("%H:%M:%S", time.localtime(r.get("ts", 0)))
            at = r.get("anchor") or (r.get("stepId") or "未知屏")
            print(f"[{stamp}] {at} · {r.get('chars', len(r.get('text', '')))} 字"
                  + (f" · t={r['t']}s" if r.get("t") is not None else ""))
            print("  " + (r.get("text", "").replace("\n", "\n  ")))
    return 0


def project_root(arg: str) -> Path:
    p = Path(arg).resolve()
    if (p / "composition").is_dir():
        return p
    if p.name == "edit" and (p.parent / "composition").is_dir():
        return p.parent
    raise SystemExit(f"no composition/ under {p}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("project")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--stop", action="store_true")
    ap.add_argument("--tail", type=int, default=None)
    ap.add_argument("--clear", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    project = project_root(args.project)

    if args.stop:
        return stop(project)
    if args.clear:
        notes_path(project).write_text("", encoding="utf-8")
        print(f"已清空 {NOTES_REL}")
        return 0
    if args.tail is not None:
        return tail(project, args.tail, args.json)
    return serve(project, args.port)


if __name__ == "__main__":
    raise SystemExit(main())
