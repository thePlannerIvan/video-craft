# Timing Lock (v2)

> 本文涉及 page 路线的段落已归档（见 [legacy-page-route.md](legacy-page-route.md)）；现行 recompose 路线见 [film.md](film.md) 与 [recompose-mode.md](recompose-mode.md)。命令集中在 [tools.md](tools.md)。


Timing Lock verifies the composition is a faithful render of the SRT
timeline **before anything gets rendered**.

## Required Checks

1. `timeline/timeline.json` exists and is SRT-derived.
2. `python3 helpers/film.py verify <project>` exits 0 — 原页拆解填满、每个 beat 都有映射。
   （旧 page 路线的 `generate-composition.py --verify` 已随路线归档，新项目不再要求。）
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
- 第 7 步手写的场景从新 timeline 取 `data-start`/`data-duration`，再跑 `helpers/check_live_stage.py`
- 重建审阅页（`helpers/review.py`），旧快照随之失效

SRT remains the time source.
