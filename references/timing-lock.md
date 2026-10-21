# Timing Lock (v2)

> **老路线存档**：本文里凡涉及 `import_svg_page` / `generate-composition` / `check_parity`
> 或「保真页面(page)」的段落，都是 **page 十步路线的存档说明**，新项目不要照做。
> 画面的唯一入口是 `helpers/film.py`（见 [film.md](film.md)），存档总览见
> [legacy-page-route.md](legacy-page-route.md)。


Timing Lock verifies the composition is a faithful render of the SRT
timeline **before anything gets rendered**.

## Required Checks

1. `timeline/timeline.json` exists and is SRT-derived.
2. `python3 visual/scripts/generate-composition.py <project> --verify` exits 0:
   every clip's `data-start`/`data-duration` matches its step in
   timeline.json (±50ms), step count matches, root `data-duration`
   equals `totalDurationMs`, and the `<audio>` duration spans the
   whole timeline.
3. `cd composition && npm run check` — 0 errors (lint/runtime/layout/
   motion/contrast).
   Hand-authored GSAP timelines: `helpers/check_motion_targets.py <project>` exits 0 —
   it catches selectors that no longer resolve and page `transform`s a tween rewrites.
4. When the project has narration audio: `input/audio.mp3` exists and
   `ffprobe` duration ≥ SRT span.
5. All `feedback/*.jsonl` open items are fixed or explicitly accepted.
6. Optional but recommended: `npx hyperframes snapshot --at <midpoints>`
   and eyeball the frames (or hand them to the user).

## Timing Changes

Never edit `data-start`/`data-duration` by hand — that is the same
"stretch a screen to feel right" anti-pattern, moved into a new file.
If timing feels wrong:

- regroup SRT lines into different visual steps (timeline/grouping.json)
- rebuild `timeline/timeline.json`
- re-run the generator: `python3 visual/scripts/generate-composition.py <project>`
- re-verify with `--verify`

SRT remains the time source.
