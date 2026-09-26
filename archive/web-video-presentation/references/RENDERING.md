# Rendering (Phase 5)

The deliverable is a rendered MP4 from the HyperFrames composition —
no screen recording. Deterministic: the same composition always
produces the same video, and a re-render after a visual fix takes
~30 seconds instead of a full screen-recording pass.

## Prerequisites

- Phase 4 Timing Lock passed: `python3 scripts/generate-composition.py <project> --verify` exits 0
- All `feedback/*.jsonl` open items resolved or explicitly accepted

## Render

```bash
cd <project>/composition
npm run check        # 0 errors required before rendering
npm run render       # → renders/<project>_<timestamp>.mp4
```

Useful variants (see `npx hyperframes render --help`):

- `--fps 24|30|60` — match the source audio's native rate if needed
- `--workers N` — parallel render (default auto)
- `--resolution portrait` — upscale capture to 1080x1920 (aspect must match)

> ⚠ Output paths must be SPACE-FREE. Rendering to a path containing
> spaces (e.g. `renders/04-XHS 笔记.mp4`) fails — hyperframes compresses
> the path to a temp artifact and the output never lands. Render to a
> space-free path (or `/tmp`) and `mv` into place after.

## Transparent overlay variant (花字层/叠加层)

For an alpha layer that gets composited onto footage later (NOT a
standalone video), DO NOT render webm — this machine's ffmpeg libvpx is
built without alpha, so WebM silently drops transparency (yuv420p).

```bash
cd <project>/composition
npx hyperframes render --no-low-memory-mode --format png-sequence -o /tmp/alpha-frames
python3 <path-to-skill>/scripts/encode_transparent.py /tmp/alpha-frames \
  -o renders/overlay.mov                      # PNG-in-MOV, small
python3 <path-to-skill>/scripts/encode_transparent.py /tmp/alpha-frames \
  -o renders/overlay_4444.mov --codec prores  # ProRes 4444 for pro pipelines
```

- `--no-low-memory-mode` is REQUIRED — the low-memory screenshot-capture
  path drops alpha even for alpha-needing compositions (drawElement
  capture preserves it)
- `encode_transparent.py` verifies alpha twice (pix_fmt + alpha plane
  range) and prints size/duration; the resulting MOV's frame 0 is fully
  transparent when the composition's first frame is transparent
- Match `--fps` with the render's fps; overlays must also match the
  base footage's frame rate when composited

## Verify before showing the user

```bash
ffprobe -v error -show_entries format=duration \
  -show_entries stream=codec_name,width,height,avg_frame_rate \
  -of default=noprint_wrappers=1 renders/*.mp4
```

Assert:

- duration ≈ `timeline.json.totalDurationMs / 1000` (±100ms)
- width×height matches the composition (`data-width`×`data-height`)
- an audio stream exists when the project has narration audio
  (embedded `<audio>`); duration equals the SRT span

Also eyeball 2-3 midpoints via `npx hyperframes snapshot --at <t1,t2>`
and hand the frames to the user — the agent may be text-only, the
user always sees the pixels.

## Acceptance

Show the user the rendered MP4. Ask one question: ship it, or fix
specific steps? On "fix": edit `composition/index.html`, re-run
`npm run check`, re-render (~30s), re-verify, show again.

Log the render (duration, size, version) in `project.md`.

## Audio

Audio is embedded in the composition (`<audio data-start="0"
data-duration="<total>" src="../input/audio.mp3">`) and the framework
owns playback, so the render ships with a synced track — no external
alignment step, unlike the old screen-recording flow.

If the audio sounds too quiet/loud versus expectations, normalize the
source once with ffmpeg loudnorm and re-render; do not touch the
composition timing.
