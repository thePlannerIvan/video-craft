#!/usr/bin/env python3
"""Read the live timeline: what is actually on screen at time t, and what type does it use?

Why this exists
---------------
Two failures in 2026-11 品牌屋 cost a review round each, and both were invisible
in a screenshot at thumbnail size:

- **`immediateRender` leak**: a later `fromTo` wrote its *from* values at frame 0,
  so the composition's opening 3D angle was silently flattened. A still frame
  looked plausible; only reading computed styles at t=0.6 showed opacity/rotation
  that no markup predicted.
- **type scale drift**: band labels had been resized one at a time (26 / 24 / 22 /
  21 / 20 px). The author noticed before any tool did. `--type-table` prints the
  whole declared scale in one screen so drift is obvious.

`hyperframes snapshot` answers "does it look right". This answers "what are the
values" and "how do the labels line up" — the questions that need numbers.

Usage
-----
    python3 helpers/probe_stage.py <composition-or-project> --type-table
    python3 helpers/probe_stage.py <composition> --at 0.6,64.6,240
    python3 helpers/probe_stage.py <composition> --at 240 --ids t-rtb-ds,shape-rtb
    python3 helpers/probe_stage.py <composition> --at 64.6 --shot-dir /tmp/probe
    python3 helpers/probe_stage.py <composition> --at 64.6 --all   # every tagged element
    python3 helpers/probe_stage.py <composition> --at 64.6 --json

Needs playwright (`pip install playwright && playwright install chromium`), which
`check_review_playable.py` already requires.
"""
from __future__ import annotations

import argparse
import functools
import http.server
import json
import re
import socket
import socketserver
import sys
import threading
from pathlib import Path

TEXT_RE = re.compile(r"<text\b([^>]*)>", re.S)
ATTR_RE = re.compile(r"([\w:-]+)\s*=\s*\"([^\"]*)\"")


def composition_of(target: Path) -> Path:
    target = target.resolve()
    if (target / "index.html").is_file():
        return target
    if (target / "composition/index.html").is_file():
        return target / "composition"
    raise SystemExit(f"找不到 composition：{target}")


def type_table(comp: Path) -> int:
    """静态统计字号/基线。继承来的字号按最近的 <g> 祖先解析，不然一大半行是空的。"""
    html = (comp / "index.html").read_text(encoding="utf-8")
    inherit = ("font-size", "font-weight", "letter-spacing", "fill")
    defaults = {"font-size": "-", "font-weight": "-", "letter-spacing": "-", "fill": "-"}
    stack: list[dict] = []
    rows = []
    token = re.compile(r"<(/?)g\b([^>]*)>|<text\b([^>]*)>", re.S)
    for m in token.finditer(html):
        if m.group(1) == "" and m.group(3) is None:        # <g ...>
            attrs = dict(ATTR_RE.findall(m.group(2)))
            stack.append({k: attrs.get(k) for k in inherit if k in attrs})
        elif m.group(0).startswith("</g"):                  # </g>
            if stack:
                stack.pop()
        else:                                               # <text ...>
            attrs = dict(ATTR_RE.findall(m.group(3)))
            body = html[m.end():].split("</text>", 1)[0]
            text = re.sub(r"<[^>]+>", "", body).strip()
            eff = dict(defaults)
            for layer in stack:
                eff.update({k: v for k, v in layer.items() if v})
            eff.update({k: v for k, v in attrs.items() if k in inherit})
            rows.append({
                "id": attrs.get("id") or "(no-id)",
                "size": eff["font-size"], "weight": eff["font-weight"],
                "ls": eff["letter-spacing"], "fill": eff["fill"],
                "anchor": attrs.get("text-anchor", "start"),
                "x": attrs.get("x", "-"), "y": attrs.get("y", "-"),
                "text": text[:18],
            })
    if not rows:
        raise SystemExit("composition 里没有 <text>")
    print(f"{'id':26s} {'size':>5s} {'weight':>6s} {'ls':>4s} {'anchor':>7s} {'x':>6s} {'y':>6s}  text")
    for r in rows:
        print(f"{r['id']:26s} {r['size']:>5s} {r['weight']:>6s} {r['ls']:>4s} "
              f"{r['anchor']:>7s} {r['x']:>6s} {r['y']:>6s}  {r['text']}")
    sizes: dict[str, list[str]] = {}
    for r in rows:
        sizes.setdefault(r["size"], []).append(r["id"])
    print("\n字级分布：")
    for size, ids in sorted(sizes.items(), key=lambda kv: -len(kv[1])):
        print(f"  {size:>5s} → {len(ids)} 个：{', '.join(ids[:8])}")
    if len(sizes) > 3:
        print("  （>3 种字号：画面要刻意分层时才有必要；多数是历史改字留下的漂移）")
    xs = sorted({r["x"] for r in rows if r["anchor"] == "middle"})
    print(f"\n居中元素共用的 x：{xs or '无'}")
    return 0


def _serve(comp: Path) -> tuple[socketserver.TCPServer, int]:
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(comp))
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, httpd.server_address[1]


def probe(comp: Path, times: list[float], ids: list[str], shot_dir: Path | None,
          want_all: bool, as_json: bool) -> int:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as error:  # pragma: no cover
        raise SystemExit(f"没有 playwright：{error}")

    html = (comp / "index.html").read_text(encoding="utf-8")
    m = re.search(r'data-composition-id\s*=\s*"([^"]+)"', html)
    root_id = m.group(1) if m else "main"

    httpd, port = _serve(comp)
    out: dict[str, dict] = {}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1920, "height": 1080})
            page.goto(f"http://127.0.0.1:{port}/index.html")
            for _ in range(60):
                page.wait_for_timeout(250)
                if page.evaluate(f"!!(window.__timelines && window.__timelines[{json.dumps(root_id)}])"):
                    break
            else:
                raise SystemExit("时间轴没建起来：先跑 check_live_stage.py")
            shot_dir = shot_dir or None
            for t in times:
                info = page.evaluate(
                    """(args) => {
                        const [t, root, ids, all] = args;
                        const tl = window.__timelines[root];
                        tl.pause(t); tl.time(t, false);
                        const pick = all
                          ? Array.from(document.querySelectorAll('[id]'))
                          : ids.map((id) => document.getElementById(id)).filter(Boolean);
                        const rows = [];
                        for (const el of pick) {
                            const cs = getComputedStyle(el);
                            const r = el.getBoundingClientRect();
                            if (!all && r.width + r.height === 0) continue;
                            rows.push({id: el.id, opacity: +(+cs.opacity).toFixed(3),
                                       x: Math.round(r.x), y: Math.round(r.y),
                                       w: Math.round(r.width), h: Math.round(r.height),
                                       size: cs.fontSize, fill: cs.fill});
                        }
                        return {t, count: rows.length, rows};
                    }""",
                    [t, root_id, ids, want_all],
                )
                out[str(t)] = info
                if shot_dir is not None:
                    shot_dir.mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=str(shot_dir / f"probe-{t}.png"))
            browser.close()
    finally:
        httpd.shutdown()

    if as_json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0
    for t, info in out.items():
        print(f"=== t={t}s（{info['count']} 个元素）")
        for r in info["rows"]:
            if not want_all and r["opacity"] < 0.02:
                continue
            print(f"   {r['id']:22s} op={r['opacity']:.2f} "
                  f"cx={r['x'] + r['w'] // 2:5d} cy={r['y'] + r['h'] // 2:5d} "
                  f"w={r['w']:4d} {r['size']:>6s} {r['fill']}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", type=Path)
    ap.add_argument("--at", default="", help="逗号分隔的时刻（秒）")
    ap.add_argument("--ids", default="", help="逗号分隔的元素 id；省略=不筛")
    ap.add_argument("--all", action="store_true", help="列出页面里所有带 id 的元素")
    ap.add_argument("--type-table", action="store_true", help="只静态统计字号/基线，不开浏览器")
    ap.add_argument("--shot-dir", type=Path, default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    comp = composition_of(args.target)
    if args.type_table:
        return type_table(comp)
    times = [float(x) for x in args.at.split(",") if x.strip()]
    if not times:
        raise SystemExit("给 --at（或 --type-table）")
    ids = [x.strip() for x in args.ids.split(",") if x.strip()]
    return probe(comp, times, ids, args.shot_dir, args.all, args.json)


if __name__ == "__main__":
    sys.exit(main())
