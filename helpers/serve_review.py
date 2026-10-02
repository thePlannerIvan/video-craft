#!/usr/bin/env python3
"""serve_review.py — Video Craft 统一审阅控制台高性能服务（深模块）。

特性：
  1. 完整支持 HTTP 206 Partial Content (Range: bytes=...)：大视频（>200MB）在 Chrome/Safari 中秒级快进/拖拽定位；
  2. 独立 API 兜底：处理 POST /api/feedback，自动同步至 review-submissions.json 与 feedback/*.jsonl，脱离 DSH 也能稳定提意见；
  3. 智能根目录映射：以项目根为宿主目录，精准解析 review/index.html、edit/cut.mp4 与 timeline/timeline.json；
  4. 支持 --open 自动打开系统浏览器。

用法：
    python3 helpers/serve_review.py <project_dir> [--port 8765] [--open]
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import urllib.parse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HELPERS = Path(__file__).resolve().parent
sys.path.insert(0, str(HELPERS))

BRIDGE_JS_PATH = None
try:
    from lib.planners_modules import resolve_module
    _core = resolve_module("planners-review-core")
    if (_core / "assets" / "review-bridge.js").exists():
        BRIDGE_JS_PATH = _core / "assets" / "review-bridge.js"
except Exception:
    pass

if not BRIDGE_JS_PATH or not BRIDGE_JS_PATH.exists():
    _fallback = HELPERS.parent.parent / "00-system" / "planners-review-core" / "assets" / "review-bridge.js"
    if _fallback.exists():
        BRIDGE_JS_PATH = _fallback


class VideoCraftReviewHandler(SimpleHTTPRequestHandler):
    """带 HTTP Range 与反馈持久化的专用 Handler。"""

    def end_headers(self):
        # 允许跨域与 Range 请求
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Range")
        self.send_header("Accept-Ranges", "bytes")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def do_HEAD(self):
        self._is_head = True
        try:
            self.do_GET()
        finally:
            self._is_head = False

    def do_POST(self):
        """处理反馈提交接口 /__review/write 与 /api/feedback。"""
        if self.path.startswith("/__review/wake"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(b'{"ok": true, "woke": false, "note": "serve_review standalone"}')
            return

        if self.path.startswith("/api/feedback") or self.path.startswith("/__review/write"):
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length).decode("utf-8")
                payload = json.loads(body)
                project_root = Path(self.server.project_root)
                review_dir = project_root / "review"
                review_dir.mkdir(parents=True, exist_ok=True)

                submissions_path = review_dir / "review-submissions.json"
                if isinstance(payload, dict) and "records" in payload:
                    doc = payload
                elif isinstance(payload, list):
                    doc = {"records": payload}
                else:
                    existing_records = []
                    if submissions_path.is_file():
                        try:
                            old = json.loads(submissions_path.read_text(encoding="utf-8"))
                            if isinstance(old, dict) and "records" in old:
                                existing_records = old["records"]
                            elif isinstance(old, list):
                                existing_records = old
                        except Exception:
                            pass
                    existing_records.append(payload)
                    doc = {"records": existing_records}

                submissions_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")

                # 如果有 review_inbox.py，尝试收件
                try:
                    import review_inbox
                    review_inbox.process_submissions(project_root)
                except Exception:
                    pass

                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                saved_count = len(doc.get("records", []))
                self.wfile.write(json.dumps({"ok": True, "saved": saved_count, "path": str(submissions_path)}).encode("utf-8"))
                return
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": False, "error": str(e)}).encode("utf-8"))
                return

        self.send_error(404, "Endpoint not found")

    def do_GET(self):
        """带 Range 支持的静态文件服务。"""
        # 默认根路径重定向到 review/index.html
        if self.path == "/" or self.path == "":
            self.send_response(302)
            self.send_header("Location", "/review/index.html")
            self.end_headers()
            return

        if self.path.startswith("/__review/version"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            if not getattr(self, "_is_head", False):
                self.wfile.write(b'{"token": "v1"}')
            return

        if self.path.startswith("/__review/capabilities"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            if not getattr(self, "_is_head", False):
                self.wfile.write(b'{"capabilities": []}')
            return

        if self.path.startswith("/__review/bridge.js"):
            if BRIDGE_JS_PATH and BRIDGE_JS_PATH.exists():
                bridge_bytes = BRIDGE_JS_PATH.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/javascript; charset=utf-8")
                self.send_header("Content-Length", str(len(bridge_bytes)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                if not getattr(self, "_is_head", False):
                    self.wfile.write(bridge_bytes)
                return
            self.send_error(404, "bridge.js not found")
            return

        if self.path.startswith("/__review/wake"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            if not getattr(self, "_is_head", False):
                self.wfile.write(b'{"ok": true, "woke": false, "note": "serve_review standalone"}')
            return

        # 去掉 query string 并进行 URL 解码（支持中文路径）
        clean_path = urllib.parse.unquote(self.path.split("?")[0])
        file_path = (Path(self.server.project_root) / clean_path.lstrip("/")).resolve()

        if not file_path.is_file():
            self.send_error(404, f"File not found: {clean_path}")
            return

        file_size = file_path.stat().st_size
        content_type, _ = mimetypes.guess_type(str(file_path))
        content_type = content_type or "application/octet-stream"

        # HTML 文件：原地替换 {{REVIEW_BRIDGE}}
        if content_type.startswith("text/html"):
            raw_html = file_path.read_text(encoding="utf-8")
            if "{{REVIEW_BRIDGE}}" in raw_html:
                block = '<script>window.__REVIEW_BASE__="/"</script>\n<script src="/__review/bridge.js"></script>'
                raw_html = raw_html.replace("{{REVIEW_BRIDGE}}", block)
            html_bytes = raw_html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html_bytes)))
            self.end_headers()
            if not getattr(self, "_is_head", False):
                self.wfile.write(html_bytes)
            return

        range_header = self.headers.get("Range")

        # 非 Range 请求：直接发送完整文件
        if not range_header:
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(file_size))
            self.end_headers()
            if not getattr(self, "_is_head", False):
                try:
                    with open(file_path, "rb") as f:
                        shutil.copyfileobj(f, self.wfile)
                except (BrokenPipeError, ConnectionResetError):
                    pass
            return

        # 处理 Range 请求
        range_match = re.match(r"bytes=(\d+)-(\d*)", range_header)
        if not range_match:
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(file_size))
            self.end_headers()
            if not getattr(self, "_is_head", False):
                with open(file_path, "rb") as f:
                    shutil.copyfileobj(f, self.wfile)
            return

        start = int(range_match.group(1))
        end = int(range_match.group(2)) if range_match.group(2) else file_size - 1
        if start >= file_size or end >= file_size or start > end:
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{file_size}")
            self.end_headers()
            return

        chunk_length = end - start + 1
        content_type, _ = mimetypes.guess_type(str(file_path))
        content_type = content_type or "application/octet-stream"

        self.send_response(206)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
        self.send_header("Content-Length", str(chunk_length))
        self.end_headers()

        if not getattr(self, "_is_head", False):
            with open(file_path, "rb") as f:
                f.seek(start)
                bytes_to_send = chunk_length
                buf_size = 64 * 1024
                while bytes_to_send > 0:
                    chunk = f.read(min(bytes_to_send, buf_size))
                    if not chunk:
                        break
                    try:
                        self.wfile.write(chunk)
                        bytes_to_send -= len(chunk)
                    except (BrokenPipeError, ConnectionResetError):
                        break


def find_free_port(start_port: int = 8765) -> int:
    """寻找可用端口。"""
    port = start_port
    while port < 65535:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
        port += 1
    return start_port


def main():
    parser = argparse.ArgumentParser(description="Video Craft 统一审阅控制台高性能服务")
    parser.add_argument("project", help="项目根目录")
    parser.add_argument("--port", type=int, default=8765, help="服务端口（默认 8765）")
    parser.add_argument("--open", action="store_true", help="启动后自动在浏览器中打开")
    args = parser.parse_args()

    project_root = Path(args.project).resolve()
    if project_root.name == "edit" or project_root.name == "review":
        project_root = project_root.parent

    if not project_root.exists():
        print(f"Error: 找不到项目目录 {project_root}", file=sys.stderr)
        sys.exit(1)

    review_html = project_root / "review" / "index.html"
    if not review_html.exists():
        print(f"提示: 未发现 review/index.html，正在自动构建...", file=sys.stderr)
        cmd = [sys.executable, str(HELPERS / "build_review.py"), str(project_root)]
        subprocess.run(cmd, check=True)

    port = find_free_port(args.port)
    server_address = ("127.0.0.1", port)

    class CustomServer(ThreadingHTTPServer):
        daemon_threads = True
        def __init__(self, *s_args, **kwargs):
            self.project_root = str(project_root)
            super().__init__(*s_args, **kwargs)

    httpd = CustomServer(server_address, VideoCraftReviewHandler)
    url = f"http://127.0.0.1:{port}/review/index.html"

    print(f"============================================================")
    print(f" Video Craft 统一审阅控制台已启动")
    print(f" 项目: {project_root.name}")
    print(f" 地址: {url}")
    print(f" 特性: HTTP Range 支持 / 秒级拖拽 / 反馈自动持久化")
    print(f" 按 Ctrl+C 退出服务")
    print(f"============================================================")

    if args.open:
        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", url])
            elif sys.platform == "win32":
                os.startfile(url)
            else:
                subprocess.Popen(["xdg-open", url])
        except Exception:
            pass

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n审阅服务已停止。")
        httpd.server_close()


if __name__ == "__main__":
    main()
