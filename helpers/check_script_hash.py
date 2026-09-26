#!/usr/bin/env python3
"""Catch a script that changed after the content contract was bound.

`visual-plan.json` records `script_hash` — the sha256 of the `script.md` the
contract was built against. Upstream computes it once, at handoff
(`validate-visual-plan.mjs --script`); after that nothing watches it, so two
places check it and each owns a different stretch of time:

- **the picture step** (`planners-ppt-hell`'s video route) checks it before
  recording, next to the contract — the handoff package IS the upstream
  `deliverable/`, which holds `script.md` beside `visual-plan.json`. Its check is
  **in time**: the author records against the picture, so a fix costs a re-render.
- **this script**, at handoff into the edit, checks it after recording. Ours is
  **after the fact**: the narration is already cut, so a fix costs a re-record.
  Hence the rule here is stricter — a mismatch stops and asks the author.

The narration not entering the picture step is about CONTENT (it does not read the
script to decide what to draw); comparing a hash is not reading it as input.

Why it matters: if the narration changed, the screens bound to the changed Beats
may be void whole, and fixing one screen means re-recording that segment. Finding
that out after the animation is built is the expensive version.

Exit codes: 0 match · 1 mismatch (or the script is gone) · 2 cannot verify
(no `script_hash` in the contract, no plan, or no script at all).

Usage:
    python3 helpers/check_script_hash.py <project>
    python3 helpers/check_script_hash.py --script <script.md> --plan <visual-plan.json>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

SCRIPT_NAMES = ("input/script.md", "deliverable/script.md", "script.md")
PLAN_NAMES = ("input/visual-plan.json", "deliverable/visual-plan.json", "visual-plan.json")


def _find(project: Path | None, names) -> Path | None:
    if project is None:
        return None
    for name in names:
        candidate = project / name
        if candidate.is_file():
            return candidate
    return None


def sha256_file(path: Path) -> str:
    """sha256 of the file's bytes — the same digest upstream binds."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(project: Path | None = None, script: Path | None = None,
          plan: Path | None = None) -> tuple[int, str]:
    plan_path = plan or _find(project, PLAN_NAMES)
    script_path = script or _find(project, SCRIPT_NAMES)

    if plan_path is None or not plan_path.is_file():
        return 2, (f"cannot verify: no visual-plan.json in {project} "
                   f"(looked for {', '.join(PLAN_NAMES)})")
    try:
        contract = json.loads(plan_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return 2, f"cannot verify: {plan_path} is not valid JSON: {exc}"

    recorded = str(contract.get("script_hash") or "").strip()
    if not recorded:
        return 2, (f"cannot verify: {plan_path} carries no script_hash, so the contract is not "
                   "bound to a script. Ask upstream to run "
                   "`validate-visual-plan.mjs visual-plan.json --script script.md`.")

    if script_path is None or not script_path.is_file():
        return 2, (f"cannot verify: no script.md in {project} "
                   f"(looked for {', '.join(SCRIPT_NAMES)}); the contract's script_hash is "
                   f"{recorded[:12]}… but there is nothing here to hash against.")

    actual = sha256_file(script_path)
    if actual != recorded:
        return 1, (f"MISMATCH  {script_path}\n"
                   f"  contract script_hash: {recorded}\n"
                   f"  script.md sha256:     {actual}\n"
                   f"  The narration changed after the contract was bound. Screens on the "
                   f"changed Beats may be void whole, and fixing one screen means "
                   f"re-recording that segment. Stop and ask the author before going on.")
    return 0, f"match  {script_path} == script_hash {recorded[:12]}…"


def main() -> int:
    ap = argparse.ArgumentParser(description="Compare script.md against the contract's script_hash")
    ap.add_argument("project", nargs="?", type=Path, default=None)
    ap.add_argument("--script", type=Path, default=None)
    ap.add_argument("--plan", type=Path, default=None)
    args = ap.parse_args()
    project = args.project.resolve() if args.project else None
    code, message = check(project, args.script, args.plan)
    print(message)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
