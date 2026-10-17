#!/usr/bin/env python3
"""The one owner of the review page's live stage.

The author reviews the **engineering state**: the composition itself, playing in
the review page, with no render and no waiting. That needs a running
HyperFrames preview server and the *bare* composition route it serves — not the
studio page (which is its own UI with its own chrome).

Three facts this tool exists to encapsulate, each learned the hard way:

1. **The sandbox.** `hyperframes preview --background` writes its state under
   `~/.local/state/hyperframes`. Under DSH's `workspace-write` sandbox that mkdir
   fails with `EPERM` and the preview silently does not start. Redirecting
   `XDG_STATE_HOME` into the project fixes it without widening permissions.

2. **The route.** The studio URL is `#/project/<id>` — a hash route inside the
   studio's SPA, useless to embed. The embeddable address is
   `/api/projects/<id>/preview/comp/index.html`, which serves the composition
   itself with a `<base>` and a GSAP fallback shim injected. That path is only
   discoverable from the studio's JS bundle (`/preview/comp/`), so it is pinned
   here instead of being re-derived per run.

3. **The protocol.** The served page has no message listener of its own; the
   studio reaches into it same-origin. Our review page runs in an opaque-origin
   `sandbox="allow-scripts"` iframe and cannot, so the composition carries its own
   `postMessage` bridge (see `composition/anim.js`). This tool only supplies the
   URL; it does not speak the protocol.

Interface
---------
    live_stage.py <project> [--port N] [--status] [--stop] [--json]

Exit codes: 0 ok · 2 no composition to stage · 3 server did not come up in time.

Deliberately not doing: rendering any frame, editing the composition, or owning
the review page. Those have their own owners.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import unquote

DEFAULT_PORT = 4317
BOOT_TIMEOUT_S = 45.0
STATE_FILE = "edit/_engineering/live-stage.json"

# studio 的路由在它自己的 bundle 里；裸路由是这一条
STAGE_ROUTE = "/api/projects/{pid}/preview/comp/index.html"
ROUTE_IN_BUNDLE = re.compile(r"[/\"]/api/projects/\$\{[A-Za-z0-9_$]+\}/preview/comp/")
BUNDLE_SRC = re.compile(r'<script[^>]+src="(/assets/[^"]+\.js)"')


def project_root(arg: str) -> Path:
    p = Path(arg).resolve()
    if (p / "composition").is_dir():
        return p
    if p.name == "edit" and (p.parent / "composition").is_dir():
        return p.parent
    raise SystemExit(f"no composition/ under {p} — nothing to stage")


def hf_state_env(root: Path) -> dict:
    """Keep HyperFrames' state inside the project: outside it the sandbox denies."""
    state = root / "edit/_engineering/hf-state"
    state.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["XDG_STATE_HOME"] = str(state)
    env["XDG_CACHE_HOME"] = str(state / "cache")
    return env


def npx() -> list[str]:
    return ["npx", "--no-install", "hyperframes"]


def run(root: Path, args: list[str], timeout: float = 60.0) -> subprocess.CompletedProcess:
    return subprocess.run(npx() + args, cwd=str(root / "composition"),
                          env=hf_state_env(root), capture_output=True, text=True,
                          timeout=timeout)


def parse_status(text: str) -> dict:
    out = {}
    for line in text.splitlines():
        m = re.match(r"\s*(Project|Studio|Server|Background preview running)\s+(.*)", line)
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip()
        if key == "Studio":
            out["studioUrl"] = val
        elif key == "Server":
            out["serverUrl"] = val
        elif key == "Project":
            out["projectId"] = val
        elif key.startswith("Background"):
            m2 = re.search(r"\(PID\s+(\d+)\)", val)
            out["pid"] = m2.group(1) if m2 else val.strip("().")
    m = re.search(r"Log:\s*(\S+)", text)
    if m:
        out["log"] = m.group(1)
    return out


def http_ok(url: str, timeout: float = 3.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return 200 <= resp.status < 400
    except (urllib.error.URLError, OSError):
        return False


def fetch(url: str, timeout: float = 8.0) -> str:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


ASSET_REF = re.compile(r'(?:src|href)\s*=\s*["\']([^"\']+)["\']')
NOT_A_LOCAL_REF = ("#", "data:", "blob:", "//", "http://", "https://",
                   "mailto:", "javascript:")


def foreign_asset_refs(body: str, comp: Path) -> list:
    """Composition-relative refs in the served body that do not exist here.

    The shim check below proves the route is *a* staged composition. It does not
    prove the body is THIS project's. Two projects whose directory is named
    `composition` register under the same project id, and `hyperframes preview
    --status` then reports whichever server answers first — on 2026-10-15 a
    project was pointed at a different project's preview and the mismatch only
    surfaced much later and much less clearly, as `Missing or escaping
    composition asset: assets/pages/beat-01/…jpg` out of build_review.

    An asset reference that this composition does not contain is that mistake,
    caught at the source. A body with no relative refs proves nothing either way,
    so it passes — this narrows the failure, it does not claim to be a checksum.
    """
    comp = comp.resolve()
    missing = []
    for ref in ASSET_REF.findall(body):
        if not ref or ref.startswith(NOT_A_LOCAL_REF) or ref.startswith("/"):
            continue
        target = (comp / unquote(ref.split("?", 1)[0])).resolve()
        if target.is_relative_to(comp) and not target.is_file():
            missing.append(ref)
    return missing


def prove_stage_route(server: str, pid: str, comp: Path) -> tuple[bool, str]:
    """Ask the running server for the bare route; confirm it is OUR composition.

    Status codes alone prove nothing — this server answers 200 with the studio
    SPA for unknown paths, so `/anything` looks fine. The route is only real when
    the body is the composition: the injected GSAP fallback shim plus a `<base>`
    scoped to the route itself. And it is only OURS when the body's own asset
    references resolve inside this project's composition directory.
    """
    url = server.rstrip("/") + STAGE_ROUTE.format(pid=pid)
    try:
        body = fetch(url)
    except (urllib.error.URLError, OSError) as exc:
        return False, f"{url} unreachable: {exc}"
    if "data-hf-gsap-fallback" not in body:
        return False, (f"{url} returned something that is not a staged composition "
                       f"({len(body)} bytes, no injected fallback shim) — the studio's "
                       f"route shape may have changed; re-derive it from the bundle")
    missing = foreign_asset_refs(body, comp)
    if missing:
        sample = ", ".join(missing[:3])
        return False, (
            f"{url} 端上来的是**另一个工程**的 composition：它引用了本工程 "
            f"{comp} 里不存在的 {len(missing)} 个资源（例如 {sample}）。"
            f"\n  多半是机器上还有一个同名的 `composition` 工程占着同一个 project id，"
            f"预览服务指向了它。先 `live_stage.py <project> --stop`，"
            f"再确认没有别的预览服务占着同一端口。")
    return True, url


def discover_route_shape(root: Path, server: str) -> str | None:
    """Last resort: read the studio bundle to confirm the route prefix still exists."""
    try:
        index = fetch(server.rstrip("/") + "/")
    except (urllib.error.URLError, OSError):
        return None
    for rel in BUNDLE_SRC.findall(index):
        try:
            body = fetch(server.rstrip("/") + rel)
        except (urllib.error.URLError, OSError):
            continue
        if ROUTE_IN_BUNDLE.search(body):
            return "/api/projects/{pid}/preview/comp/"
    return None


def stop(root: Path) -> int:
    proc = run(root, ["preview", str(root / "composition"), "--stop"])
    text = (proc.stdout or "") + (proc.stderr or "")
    print(text.strip() or "stopped")
    state = root / STATE_FILE
    if state.exists():
        state.unlink()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("project")
    ap.add_argument("--composition", default="composition",
                    help="composition directory inside the project (default: composition)")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--stop", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    root = project_root(args.project)
    comp = (root / args.composition).resolve()
    if root not in comp.parents and comp != root:
        print(f"✗ --composition 必须在项目内：{comp}", file=sys.stderr)
        return 2
    if not (comp / "index.html").is_file():
        print(f"✗ no composition/index.html under {comp}", file=sys.stderr)
        return 2
    if args.stop:
        return stop(root)

    if shutil.which("npx") is None:
        print("✗ npx not on PATH — HyperFrames preview cannot start", file=sys.stderr)
        return 3

    stated = parse_status(run(root, ["preview", str(comp), "--status"]).stdout or "")
    started = False
    if not stated.get("serverUrl"):
        proc = run(root,
                   ["preview", str(comp), "--background", "--port", str(args.port), "--no-open"],
                   timeout=BOOT_TIMEOUT_S)
        text = (proc.stdout or "") + (proc.stderr or "")
        if "EPERM" in text or "operation not permitted" in text:
            print("✗ preview could not write its state directory even with "
                  "XDG_STATE_HOME redirected — the sandbox is blocking more than "
                  "state; run the review host locally instead.", file=sys.stderr)
            return 3
        started = True
        stated = parse_status(run(root, ["preview", str(comp), "--status"]).stdout or "")

    server = stated.get("serverUrl")
    pid = stated.get("projectId") or comp.name
    if not server:
        deadline = time.time() + BOOT_TIMEOUT_S
        probe = f"http://127.0.0.1:{args.port}"
        while time.time() < deadline and not http_ok(probe):
            time.sleep(0.5)
        server = probe if http_ok(probe) else None
    if not server or not http_ok(server):
        print(f"✗ preview server did not answer within {BOOT_TIMEOUT_S:.0f}s "
              f"(port {args.port}); check the log under edit/_engineering/hf-state/",
              file=sys.stderr)
        return 3

    ok, stage = prove_stage_route(server, pid, comp)
    if not ok:
        shape = discover_route_shape(root, server)
        print(f"✗ {stage}" + (f"\n  bundle still advertises {shape}<name>" if shape else ""),
              file=sys.stderr)
        return 3

    duration = None
    try:
        cfg = json.loads(fetch(server.rstrip("/") + "/api/projects"))
        duration = next((p.get("duration") for p in cfg.get("projects", [])
                         if p.get("id") == pid), None)
    except (urllib.error.URLError, OSError, ValueError):
        pass

    payload = {"ok": True, "started": started, "serverUrl": server,
               "stageUrl": stage, "projectId": pid,
               "composition": str(comp.relative_to(root)),
               "studioUrl": stated.get("studioUrl"), "pid": stated.get("pid"),
               "log": stated.get("log"), "port": args.port}
    state = root / STATE_FILE
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                     encoding="utf-8")

    if args.json or args.status:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"活舞台 {'已启动' if started else '已在运行'} · {pid}")
        print(f"  嵌入地址  {stage}")
        print(f"  studio    {stated.get('studioUrl') or server}")
        print(f"  状态文件  {state.relative_to(root)}")
        print("  停掉：live_stage.py <project> --stop")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
