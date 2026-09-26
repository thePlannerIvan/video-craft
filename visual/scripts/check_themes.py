#!/usr/bin/env python3
"""Check every theme: the JSON is real JSON, the tokens resolve, the text is legible.

Themes are a library other skills read (`references/themes.md` names the two
consumers), so a theme that does not parse is a defect in the library, not in
whoever read it. Three classes:

1. **`theme.json` is parsed, not pattern-matched.** Required fields, `id` equal
   to the directory name, and a four-colour `preview` — the fields the picking
   UI reads.
2. **Every `var()` resolves inside the theme.** A token that points at nothing
   (`--r-card: var(--r-sm)` when no `--r-*` is defined) fails silently in CSS:
   `border-radius` drops to the initial value and nobody notices. Report it.
3. **Contrast.** `--text` and `--text-2` on `--surface` must clear 4.5:1 — the
   only numeric rule `themes.md` states. `--text-mute` and `--text-faint` are
   reported with their measured ratio instead: the doc calls them a judgment
   ("13px 大写时仍然要可读"), not a number.

Also checks the radius scale is identical in all themes: it is the one piece of
the theme contract that would otherwise drift copy by copy.

Usage:
    python3 visual/scripts/check_themes.py [themes_dir] [--json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

THEMES_DIR = Path(__file__).resolve().parent.parent / "themes"

REQUIRED_META = ("id", "name", "nameZh", "description", "descriptionZh",
                 "mood", "bestFor", "preview")
PREVIEW_KEYS = ("shell", "surface", "text", "accent")

REQUIRED_TOKENS = (
    "--shell", "--surface", "--surface-2", "--surface-3",
    "--text", "--text-2", "--text-mute", "--text-faint",
    "--rule", "--accent", "--accent-soft", "--accent-glow",
    "--font-display-cn", "--font-display-en", "--font-body", "--font-mono",
)

# The radius scale the themes' `--r-card` refers to. Same values in every theme.
RADIUS_SCALE = {
    "--r-flat": "0",
    "--r-xs": "4px",
    "--r-sm": "8px",
    "--r-md": "16px",
    "--r-lg": "20px",
    "--r-xl": "32px",
}

# Text you actually read. `themes.md` gives these 4.5:1 against `--surface`, and
# a theme that misses it fails the run.
ENFORCED_CONTRAST = {"--text": 4.5, "--text-2": 4.5, "--text-mute": 4.5}
# The hint / disabled tier. `themes.md` states no number for it, so none is
# invented here: the ratio is measured and printed for judgement and never fails.
# A threshold that can never be hit belongs in neither the doc nor the table.
REPORTED_CONTRAST = ("--text-faint",)

# `themes.md` puts the whole rhythm in `theme.json`'s `mood`: the theme does not
# fix duration or easing, because a tween timed off the theme lands on the theme's
# clock instead of on the spoken word. A leftover duration/easing token is that
# second source of truth, and nothing reads it.
DEAD_RHYTHM_PREFIXES = ("--dur-", "--ease-")

ROOT_RE = re.compile(r":root\s*\{(.*?)\}", re.S)
DECL_RE = re.compile(r"(--[A-Za-z0-9-]+)\s*:\s*([^;]+);")
VAR_RE = re.compile(r"var\(\s*(--[A-Za-z0-9-]+)\s*(?:,\s*([^()]*?)\s*)?\)")
HEX_RE = re.compile(r"^#([0-9a-fA-F]{6})$")


def read_tokens(tokens_css: str) -> dict:
    root = ROOT_RE.search(tokens_css)
    if root is None:
        return {}
    return {m.group(1): m.group(2).strip() for m in DECL_RE.finditer(root.group(1))}


def unresolved_vars(tokens: dict) -> list:
    """(declaring token, missing token) for every `var()` that points at nothing."""
    missing = []
    for name, value in tokens.items():
        for var in VAR_RE.finditer(value):
            if var.group(1) not in tokens and var.group(2) is None:
                missing.append((name, var.group(1)))
    return missing


def resolve(tokens: dict, name: str, seen: tuple = ()) -> str | None:
    """Follow `var()` chains to the literal value, or None when it dead-ends."""
    if name in seen or name not in tokens:
        return None
    value = tokens[name].strip()
    match = VAR_RE.fullmatch(value)
    if match is None:
        return value
    return resolve(tokens, match.group(1), seen + (name,))


def _linear(channel: float) -> float:
    return channel / 12.92 if channel <= 0.03928 else ((channel + 0.055) / 1.055) ** 2.4


def _luminance(color: str) -> float | None:
    match = HEX_RE.match(color.strip())
    if match is None:
        return None
    digits = match.group(1)
    r, g, b = (int(digits[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * _linear(r) + 0.7152 * _linear(g) + 0.0722 * _linear(b)


def contrast_ratio(foreground: str, background: str) -> float | None:
    front, back = _luminance(foreground), _luminance(background)
    if front is None or back is None:
        return None
    high, low = max(front, back), min(front, back)
    return (high + 0.05) / (low + 0.05)


def check_theme(theme_dir: Path) -> dict:
    """One theme's verdict. `failures` break the build; `notes` are measurements."""
    failures: list = []
    notes: list = []

    meta_path = theme_dir / "theme.json"
    meta = None
    if not meta_path.is_file():
        failures.append("theme.json is missing")
    else:
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            failures.append(f"theme.json is not valid JSON: {exc}")
        else:
            if not isinstance(meta, dict):
                failures.append("theme.json must be a JSON object")
                meta = None
            else:
                for field in REQUIRED_META:
                    if field not in meta:
                        failures.append(f"theme.json is missing '{field}'")
                if meta.get("id") != theme_dir.name:
                    failures.append(
                        f"theme.json id '{meta.get('id')}' != directory '{theme_dir.name}'")
                preview = meta.get("preview")
                if not isinstance(preview, dict):
                    failures.append("theme.json 'preview' must be an object")
                else:
                    for key in PREVIEW_KEYS:
                        color = preview.get(key)
                        if not isinstance(color, str) or not HEX_RE.match(color):
                            failures.append(
                                f"preview.{key} must be a #rrggbb colour, got {color!r}")

    tokens_path = theme_dir / "tokens.css"
    tokens: dict = {}
    if not tokens_path.is_file():
        failures.append("tokens.css is missing")
    else:
        tokens = read_tokens(tokens_path.read_text(encoding="utf-8"))
        if not tokens:
            failures.append("tokens.css has no :root block")
        for token in REQUIRED_TOKENS:
            if token not in tokens:
                failures.append(f"tokens.css does not define {token}")
        for declaring, missing in unresolved_vars(tokens):
            failures.append(
                f"{declaring}: var({missing}) resolves to nothing — CSS drops the whole "
                f"declaration silently")
        surface = resolve(tokens, "--surface")
        for token, threshold in ENFORCED_CONTRAST.items():
            value = resolve(tokens, token)
            if value is None or surface is None:
                continue
            ratio = contrast_ratio(value, surface)
            if ratio is not None and ratio < threshold:
                failures.append(
                    f"{token} on --surface is {ratio:.2f}:1, below {threshold}:1")
        for token in REPORTED_CONTRAST:
            value = resolve(tokens, token)
            if value is None or surface is None:
                continue
            ratio = contrast_ratio(value, surface)
            if ratio is not None:
                notes.append(f"{token} on --surface is {ratio:.2f}:1"
                             " (no minimum — this tier is measured, not enforced)")
        for token, expected in RADIUS_SCALE.items():
            if token in tokens and tokens[token] != expected:
                failures.append(
                    f"{token} is {tokens[token]!r}, but the shared scale says {expected!r}")
        dead = sorted(name for name in tokens if name.startswith(DEAD_RHYTHM_PREFIXES))
        if dead:
            failures.append(
                f"{', '.join(dead)} would time motion off the theme; rhythm lives in "
                f"theme.json's mood and each step times its own tween to the spoken word")

    return {"theme": theme_dir.name, "failures": failures, "notes": notes, "tokens": tokens}


def check_all(themes_dir: Path) -> tuple[list, list]:
    dirs = sorted(d for d in themes_dir.iterdir() if d.is_dir())
    return [check_theme(d) for d in dirs], dirs


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate the theme library")
    ap.add_argument("themes_dir", nargs="?", type=Path, default=THEMES_DIR)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    results, dirs = check_all(args.themes_dir)
    if args.json:
        print(json.dumps({"themes": [{k: v for k, v in r.items() if k != "tokens"}
                                     for r in results]}, ensure_ascii=False, indent=2))
    else:
        for r in results:
            mark = "ok  " if not r["failures"] else "FAIL"
            print(f"{mark} {r['theme']}")
            for failure in r["failures"]:
                print(f"       x {failure}")
            for note in r["notes"]:
                print(f"       · {note}")

    missing_scale = sorted({name for r in results for name in RADIUS_SCALE
                            if name not in r["tokens"]})
    if missing_scale:
        print(f"x themes missing part of the shared radius scale: {missing_scale}")

    failed = sum(1 for r in results if r["failures"] or
                 any(name not in r["tokens"] for name in RADIUS_SCALE))
    print(f"\n{len(results)} theme(s) · {failed} failing")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
