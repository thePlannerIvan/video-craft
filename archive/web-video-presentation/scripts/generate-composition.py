"""Generate a HyperFrames composition skeleton from timeline.json + theme.

The composition is the single visual source of truth in web-video-
presentation v2. This script owns everything deterministic:

  - one clip per visual step (data-start/data-duration straight from
    timeline.json, track = chapter index)
  - theme tokens.css -> :root CSS variables
  - one <audio> element spanning the whole timeline (SRT-aligned)
  - a paused GSAP timeline with per-chapter boundary hints for the
    agent's progressive-reveal implementation

The agent implements visuals inside each clip; it must NOT change the
generated timing (--verify re-derives the timeline from the HTML and
compares it field-by-field against timeline.json).

Usage:
    python scripts/generate-composition.py <project> [--theme <id>] [--audio <path>]
    python scripts/generate-composition.py <project> --verify
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
THEMES_DIR = SKILL_DIR / "themes"
DEFAULT_THEME = "midnight-press"

# .layout file values: landscape 1920x1080, portrait / overlay 1080x1920.
# overlay additionally renders with a transparent canvas (花字层 compositing).
LAYOUTS = {
    "landscape": (1920, 1080),
    "portrait": (1080, 1920),
    "overlay": (1080, 1920),
}
DEFAULT_LAYOUT = "landscape"

BASE_CSS = """
      .clip { position: absolute; inset: 0; }
      .scene { position: absolute; inset: 0; }
      .fill { position: absolute; inset: 0; background: var(--fill-bg, var(--surface, #fafaf8)); }
      .scene-body {
        position: absolute; inset: 0;
        display: flex; align-items: center; justify-content: center;
        overflow: hidden;
      }
"""


def load_layout(project: Path) -> str:
    layout_file = project / ".layout"
    if not layout_file.exists():
        return DEFAULT_LAYOUT
    layout = layout_file.read_text(encoding="utf-8").strip()
    return layout if layout in LAYOUTS else DEFAULT_LAYOUT


def load_theme_tokens(theme_id: str) -> str:
    tokens_css = THEMES_DIR / theme_id / "tokens.css"
    if not tokens_css.exists():
        sys.exit(f"theme not found: {theme_id} (themes live in {THEMES_DIR})")
    css = tokens_css.read_text(encoding="utf-8")
    m = re.search(r":root\s*\{(.*?)\}", css, re.S)
    if not m:
        sys.exit(f"no :root block in {tokens_css}")
    return m.group(1).strip()


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def generate(project: Path, theme_id: str, audio: Path | None,
             layout: str | None = None) -> Path:
    timeline = json.loads((project / "timeline" / "timeline.json").read_text(encoding="utf-8"))
    total_ms = timeline["totalDurationMs"]
    total_s = total_ms / 1000.0
    tokens = load_theme_tokens(theme_id)

    layout = layout or load_layout(project)
    width, height = LAYOUTS[layout]
    transparent = layout == "overlay"
    if transparent:
        # overlay canvas: no opaque body/root background, .fill defaults to
        # transparent unless the agent sets --fill-bg per scene
        tokens += "\n        --canvas-bg: transparent;\n        --fill-bg: transparent;"

    audio_attr = ""
    if audio is not None and audio.exists():
        # HyperFrames requires media inside the composition project (no ../ paths)
        assets_dir = project / "composition" / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(audio, assets_dir / "audio.mp3")
        audio_attr = (
            f'\n    <audio id="narration" data-start="0" data-duration="{total_s:.3f}" '
            f'src="assets/audio.mp3"></audio>'
        )

    clips: list[str] = []
    tl_hints: list[str] = []
    for ci, ch in enumerate(timeline["chapters"]):
        tl_hints.append(
            f"      // {ch['id']}: boundaries " + ", ".join(f"{st['startMs'] / 1000.0:.2f}s" for st in ch["steps"][1:]) + " — progressive reveals go here"
        )
        for st in ch["steps"]:
            start_s = st["startMs"] / 1000.0
            dur_s = st["durationMs"] / 1000.0
            comment = (
                f"    <!-- step {st['id']} {dur_s:.2f}s | caption: {esc(st['caption'])}"
                f" | intent: {esc(st.get('screenIntent') or '')}"
                f" | model: {esc(st.get('visualModel') or '')}"
                f" | {esc(st.get('modelStructure') or '')}"
                f" | text rule: {esc(st.get('onScreenTextRule') or '')}"
                f" | TODO: implement visual inside this clip; do not change data-start/data-duration -->"
            )
            clips.append(
                f"{comment}\n"
                f'    <section class="clip scene" id="step-{esc(st["id"])}" '
                f'data-start="{start_s:.3f}" data-duration="{dur_s:.3f}" data-track-index="{ci}">\n'
                f'      <div class="fill"></div>\n'
                f'      <div class="scene-body">\n'
                f'        <div class="placeholder" style="color: var(--text-mute, #737373); font-size: 28px; text-align: center; padding: 40px;">'
                f"{esc(st['id'])}</div>\n"
                f"      </div>\n"
                f"    </section>"
            )

    html = f"""<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width={width}, height={height}" />
    <script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
    <style>
      * {{ margin: 0; padding: 0; box-sizing: border-box; }}
      html, body {{ margin: 0; width: {width}px; height: {height}px; overflow: hidden; background: var(--canvas-bg, #000); }}
      #root {{ position: relative; width: {width}px; height: {height}px; background: var(--canvas-bg, #000); }}
      :root {{
{tokens}
      }}
{BASE_CSS}
    </style>
  </head>
  <body>
    <div
      id="root"
      data-composition-id="main"
      data-start="0"
      data-duration="{total_s:.3f}"
      data-width="{width}"
      data-height="{height}"
    >
{audio_attr}
{chr(10).join(clips)}
    </div>

    <script>
      window.__timelines = window.__timelines || {{}};
      const tl = gsap.timeline({{ paused: true }});
{chr(10).join(tl_hints)}
      // Scene entrances: gsap.set/fromTo on .scene-body or inner elements.
      // Boundary initial states must be set OUTSIDE the timeline (gsap.set) for frame 0.
      window.__timelines["main"] = tl;
    </script>
  </body>
</html>
"""
    out = project / "composition" / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    n_steps = sum(len(c["steps"]) for c in timeline["chapters"])
    print(f"composition skeleton -> {out}")
    print(f"  {len(timeline['chapters'])} chapters / {n_steps} steps / {total_s:.2f}s total")
    if audio_attr:
        print("  audio embedded")
    return out


STEP_RE = re.compile(r'id="step-([^"]+)" data-start="([\d.]+)" data-duration="([\d.]+)"')
AUDIO_RE = re.compile(r'<audio id="narration" data-start="([\d.]+)" data-duration="([\d.]+)"')


def verify(project: Path) -> int:
    timeline = json.loads((project / "timeline" / "timeline.json").read_text(encoding="utf-8"))
    html_path = project / "composition" / "index.html"
    if not html_path.exists():
        print(f"x composition not found: {html_path}")
        return 1
    html = html_path.read_text(encoding="utf-8")

    expected = []
    for ch in timeline["chapters"]:
        for st in ch["steps"]:
            expected.append((st["id"], st["startMs"] / 1000.0, st["durationMs"] / 1000.0))

    found = {i: (s, d) for i, s, d in STEP_RE.findall(html)}
    errors = 0

    if len(found) != len(expected):
        print(f"x step count mismatch: html {len(found)} vs timeline.json {len(expected)}")
        errors += 1

    for sid, estart, edur in expected:
        if sid not in found:
            print(f"x missing clip: {sid}")
            errors += 1
            continue
        fstart, fdur = (float(found[sid][0]), float(found[sid][1]))
        if abs(fstart - estart) > 0.05 or abs(fdur - edur) > 0.05:
            print(f"x {sid}: html {fstart:.3f}+{fdur:.3f} vs json {estart:.3f}+{edur:.3f}")
            errors += 1

    total_s = timeline["totalDurationMs"] / 1000.0
    width, height = LAYOUTS[load_layout(project)]
    root_size = re.search(r'data-width="(\d+)" data-height="(\d+)"', html)
    if root_size and (int(root_size.group(1)), int(root_size.group(2))) != (width, height):
        print(f"x root size {root_size.group(1)}x{root_size.group(2)} vs .layout {width}x{height}")
        errors += 1

    audio = AUDIO_RE.search(html)
    if audio is None:
        print("warn: no <audio> element (expected when the project has narration audio)")
    elif abs(float(audio.group(2)) - total_s) > 0.1:
        print(f"x audio duration {audio.group(2)}s vs total {total_s:.3f}s")
        errors += 1

    root_dur = re.search(r'data-duration="([\d.]+)"', html)
    if root_dur and abs(float(root_dur.group(1)) - total_s) > 0.1:
        print(f"x root duration {root_dur.group(1)}s vs total {total_s:.3f}s")
        errors += 1

    if errors == 0:
        print(f"ok: verify passed, {len(expected)} steps match timeline.json, total {total_s:.2f}s")
    return 1 if errors else 0


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate/verify HyperFrames composition skeleton")
    ap.add_argument("project", type=Path)
    ap.add_argument("--theme", type=str, default=None, help=f"theme id (default: .theme file or {DEFAULT_THEME})")
    ap.add_argument("--audio", type=Path, default=None, help="narration audio file (default: <project>/input/audio.mp3)")
    ap.add_argument("--layout", type=str, default=None,
                    help=f"layout: landscape|portrait|overlay (default: .layout file or {DEFAULT_LAYOUT})")
    ap.add_argument("--verify", action="store_true", help="verify composition timing against timeline.json and exit")
    args = ap.parse_args()

    project = args.project.resolve()
    if not (project / "timeline" / "timeline.json").exists():
        sys.exit(f"no timeline/timeline.json at {project}")

    if args.verify:
        sys.exit(verify(project))

    theme = args.theme
    if theme is None:
        theme_file = project / ".theme"
        theme = theme_file.read_text().strip() if theme_file.exists() else DEFAULT_THEME
    audio = args.audio or (project / "input" / "audio.mp3")
    layout = args.layout or load_layout(project)
    generate(project, theme, audio, layout)
    sys.exit(verify(project))


if __name__ == "__main__":
    main()
