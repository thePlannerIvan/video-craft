# Timing Lock (v2)

Timing Lock verifies the composition is a faithful render of the SRT
timeline before anything gets rendered.

## Required Checks

1. `timeline/timeline.json` exists and is SRT-derived.
2. `python3 visual/scripts/generate-composition.py <project> --verify` exits 0:
   every clip's `data-start`/`data-duration` matches its step in
   timeline.json (±50ms), step count matches, root `data-duration`
   equals `totalDurationMs`, and the `<audio>` duration spans the
   whole timeline.
3. `cd composition && npm run check` — 0 errors (lint/runtime/layout/
   motion/contrast).
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
