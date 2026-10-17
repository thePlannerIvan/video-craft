#!/usr/bin/env python3
"""A hand-authored GSAP timeline can silently animate nothing, or animate the wrong thing.

Two failures this pins, neither visible to `hyperframes check` nor to the page
(both produce a green build and a wrong film):

* `target not found` — a selector that no longer matches (a renamed id, an element
  the page dropped) makes GSAP skip the tween and log to the console only. The
  composition still renders; that step just does not move.
* a page element that already carries a static `transform` gets tweened on
  x/y/scale/rotation — GSAP parses the attribute into its own matrix and re-emits
  it, so `translate(-40,16)` is gone the moment the tween starts. On 2026-10-17
  this moved three icons back to their unaligned position and the author reported
  "没对齐" twice.

The transform check compares the SOURCE html (where the page's own transform still
exists) against the tween targets observed at runtime — reading the live attribute
instead would report GSAP's own from-values as if they were the page's.

This is the substitute for `check_parity.py` on projects whose motion is
hand-authored JS instead of a `timeline/choreography.json` spec.

Usage
-----
    check_motion_targets.py <project> [--strict-transform] [--json]

Exit 1 on an unresolved target (HARD). Static-transform risks print as warnings
and exit 0 unless `--strict-transform` is passed. Playwright missing → prints SKIP
and exits 0, the same contract as this skill's other browser-dependent helpers.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

TRANSFORM_PROPS = ("x", "y", "scale", "scaleX", "scaleY",
                   "rotation", "xPercent", "yPercent")
TAG_RE = re.compile(r"<(?P<tag>[a-zA-Z][\w:-]*)(?P<attrs>[^<>]*?)/?>")
ATTR_RE = re.compile(r'([\w:-]+)\s*=\s*"([^"]*)"')


def _significant(transform: str) -> bool:
    """Does this static transform carry an offset/scale/rotation worth reporting?

    Tweening over an identity loses nothing; a 2px drift or a 0.95 scale is not
    what bit us (a -40px/-59.4px translate did), and reporting them buries the
    real ones.
    """
    for fn, body in re.findall(
            r"(matrix|translate|scale|rotate|skewX|skewY|skew)\s*\(([^)]*)\)", transform):
        nums = [float(v) for v in re.split(r"[\s,]+", body.strip()) if v]
        if not nums:
            continue
        tx = ty = dev = rot = 0.0
        if fn == "matrix" and len(nums) >= 6:
            tx, ty = nums[4], nums[5]
            dev = max(abs(nums[0] - 1), abs(nums[3] - 1))
            rot = abs(nums[1]) * 180.0
        elif fn == "translate":
            tx = nums[0]
            ty = nums[1] if len(nums) > 1 else 0.0
        elif fn == "scale":
            dev = abs(nums[0] - 1)
        else:  # rotate / skew
            rot = abs(nums[0])
        if (tx * tx + ty * ty) ** 0.5 > 8 or dev > 0.15 or rot > 1:
            return True
    return False


def _page_transforms(html: str) -> dict:
    """id -> static transform for every element the page HTML declares one on."""
    found = {}
    for match in TAG_RE.finditer(html):
        attrs = dict(ATTR_RE.findall(match.group("attrs")))
        transform = attrs.get("transform")
        if not transform:
            continue
        key = attrs.get("id") or attrs.get("data-workbench-id")
        if key:
            found[key] = transform
    return found


async def _probe(composition: Path, timeout_ms: int) -> dict:
    from playwright.async_api import async_playwright

    result = {"console": [], "pageerrors": [], "tweens": 0,
              "duration": None, "key": None, "targets": [], "found": False}
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1920, "height": 1080})
        page.on("console", lambda m: result["console"].append(m.text)
                if m.type in ("error", "warning") else None)
        page.on("pageerror", lambda e: result["pageerrors"].append(str(e)))
        await page.goto(composition.as_uri())
        try:
            await page.wait_for_function(
                "() => window.__timelines && Object.keys(window.__timelines).length > 0",
                timeout=timeout_ms)
        except Exception:
            await browser.close()
            return result
        result["found"] = True
        info = await page.evaluate("""() => {
          const all = window.__timelines;
          const key = all.main ? 'main' : Object.keys(all)[0];
          const tl = all[key];
          tl.pause();
          const targets = [];
          for (const child of tl.getChildren(false)) {
            const vars = child.vars || {};
            const props = ['x','y','scale','scaleX','scaleY','rotation','xPercent','yPercent']
              .filter(k => k in vars);
            if (!props.length) continue;
            const list = typeof child.targets === 'function' ? child.targets() : [];
            for (const el of list) {
              if (!el || typeof el.getAttribute !== 'function') continue;
              const id = el.id || el.getAttribute('data-workbench-id');
              if (!id) continue;
              targets.push({id, props,
                            at: Math.round(child.startTime() * 1000) / 1000});
            }
          }
          return {key, duration: tl.duration(),
                  tweens: tl.getChildren(false).length, targets};
        }""")
        result.update(info)
        # Play it through: a tween that throws mid-timeline is a silent stop.
        try:
            await page.evaluate("() => { const all = window.__timelines;"
                                " const tl = all.main || all[Object.keys(all)[0]];"
                                " tl.time(tl.duration()); }")
        except Exception as exc:  # noqa: BLE001 - reported below
            result["pageerrors"].append(str(exc))
        await page.wait_for_timeout(300)
        await browser.close()
    return result


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Assert a hand-authored GSAP timeline resolves and owns its transforms")
    ap.add_argument("project", type=Path)
    ap.add_argument("--strict-transform", action="store_true",
                    help="treat static-transform risks as a hard failure")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--timeout-ms", type=int, default=20000)
    args = ap.parse_args()

    composition = (args.project / "composition" / "index.html").resolve()
    if not composition.is_file():
        print(f"x {composition} not found (run generate-composition.py first)")
        return 1
    try:
        import playwright  # noqa: F401
    except ImportError:
        print("SKIP check_motion_targets: playwright is not installed "
              "(browser checks skipped; record the skip)")
        return 0

    import asyncio
    result = asyncio.run(_probe(composition, args.timeout_ms))
    if not result["found"]:
        print("x no window.__timelines after load: the composition script never "
              "registered a timeline (an exception in the motion file is the usual cause)")
        for err in result["pageerrors"][:3]:
            print(f"  pageerror: {err}")
        return 1

    static = _page_transforms(composition.read_text(encoding="utf-8"))
    risky = []
    seen = {}
    for target in result["targets"]:
        transform = static.get(target["id"])
        if not transform or not _significant(transform):
            continue
        entry = seen.get(target["id"])
        if entry:
            entry["props"] = sorted(set(entry["props"]) | set(target["props"]))
            entry["at"] = min(entry["at"], target["at"])
        else:
            entry = {"element": target["id"], "props": sorted(target["props"]),
                     "attr": transform, "at": target["at"]}
            seen[target["id"]] = entry
            risky.append(entry)

    # GSAP says "GSAP target #id not found." — the id sits between the two words, so
    # a substring search for "target not found" matches nothing (that was a real
    # bug in the first version of this check).
    missing = [m for m in result["console"]
               if re.search(r"target\s+\S+\s+not\s+found", m, re.I)]
    if args.json:
        print(json.dumps({"ok": not missing and not result["pageerrors"],
                          "timeline": result["key"],
                          "duration": result["duration"],
                          "tweens": result["tweens"],
                          "unresolved": missing,
                          "transformRisks": risky,
                          "console": result["console"][:20]},
                         ensure_ascii=False, indent=1))
    else:
        print(f"timeline '{result['key']}': {result['tweens']} tweens, "
              f"{result['duration']:.3f}s")
        for msg in missing[:10]:
            print(f"x unresolved target: {msg}")
        for risk in risky[:6]:
            print(f"warn: {risk['element']} declares transform=\"{risk['attr']}\" and is "
                  f"tweened on {','.join(risk['props'])} at {risk['at']}s — GSAP rewrites "
                  "the attribute; move the static transform to an outer wrapper")
        if len(risky) > 6:
            print(f"warn: … {len(risky) - 6} more (full list: --json)")

    if missing or result["pageerrors"]:
        for err in result["pageerrors"][:3]:
            print(f"x pageerror: {err}")
        return 1
    if risky and args.strict_transform:
        print(f"x {len(risky)} static-transform risk(s) under --strict-transform")
        return 1
    if not args.json:
        print("ok: every animation target resolved"
              + (f"; {len(risky)} transform warning(s)" if risky else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
