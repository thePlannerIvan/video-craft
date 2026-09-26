# Rendering (Phase 5)

The deliverable is a rendered MP4 from the HyperFrames composition —
no screen recording. Deterministic: the same composition always
produces the same video, and a re-render after a visual fix takes
~30 seconds instead of a full screen-recording pass.

## Prerequisites

- Phase 4 Timing Lock passed: `python3 visual/scripts/generate-composition.py <project> --verify` exits 0
- All `feedback/*.jsonl` open items resolved or explicitly accepted

## Render

**`hyperframes` only works inside `composition/`.** It looks for `index.html` in
the current directory; from the project root it reports "No composition found …
Run npx hyperframes init to create a new composition" — and running `init` there
**replaces the skeleton `generate-composition.py` produced**. `init` is not the
fix for anything in this flow.

**Every render is preceded by the environment check — this is a required step, not
an option:**

```bash
python3 helpers/check_render_env.py <project>/composition
```

It fails early on the two things that otherwise surface mid-render: a font cache
HyperFrames cannot write, and a Node older than 22. It cannot be wired into the
render as an npm `prerender` hook: `package.json` belongs to `npx hyperframes init`
(`scaffold.sh` runs it) and `generate-composition.py` never writes it — and the
transparent-overlay variant below calls `npx hyperframes render` directly, without
npm. So the check is a step you run, and this line is where it is required.

```bash
cd <project>/composition
npm run check        # 0 errors required before rendering
npm run render       # → renders/<project>_<timestamp>.mp4
```

### Font cache in a restricted environment

HyperFrames downloads fonts into a cache under the home directory. Where the home
directory is read-only or the process is sandboxed, `render` stops after it has
started with:

```
EPERM: operation not permitted, mkdir '/Users/<you>/.cache/hyperframes/fonts/noto-serif-sc'
Try --docker for containerized rendering
```

`--docker` needs Docker. The actual way out is the font cache directory:

```bash
export HYPERFRAMES_FONT_CACHE_DIR="$PWD/.hyperframes-cache"
```

That variable is not in `--help`, and **`hyperframes doctor` does not check it** —
the nine things `doctor` reports are version / node / memory / disk / frames cache
/ ffmpeg / whisper / TTS / BGM.

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
standalone video), pick the container by who consumes it — and never render
H.264/mp4, which has no alpha by design:

| 给谁用 | 用什么 | 实测（2026-09-22，往返解回来验像素） |
|---|---|---|
| 剪辑软件（FCP / Premiere / DaVinci / 剪映专业版） | **ProRes 4444 `.mov`** | 保透明 ✓ |
| Apple 生态（macOS / Safari / iOS），要小体积 | **HEVC+alpha `.mov`**（`-c:v hevc_videotoolbox -alpha_quality 1`） | 保透明 ✓ |
| 兼容优先、体积无所谓 | **QuickTime RLE `.mov`**（`-c:v qtrle`） | 保透明 ✓ |
| 网页 `<video>` | WebM/VP9 或 HEVC+alpha | ⚠️ **本机 WebM/VP9 往返丢透明**；HEVC+alpha 只有 Safari 认，Chrome/Firefox 不认 |
| 平台交付（小红书/抖音/B站） | —— | ❌ 只吃 H.264/H.265，**透明必丢**。透明层只是中间产物：叠好背景后再导出不透明成片 |

```bash
cd <project>/composition
npx hyperframes render --no-low-memory-mode --format png-sequence -o /tmp/alpha-frames
python3 <path-to-skill>/visual/scripts/encode_transparent.py /tmp/alpha-frames \
  -o renders/overlay.mov                      # PNG-in-MOV, small
python3 <path-to-skill>/visual/scripts/encode_transparent.py /tmp/alpha-frames \
  -o renders/overlay_4444.mov --codec prores  # ProRes 4444 for pro pipelines
```

- `--no-low-memory-mode` is REQUIRED — the low-memory screenshot-capture
  path drops alpha even for alpha-needing compositions (drawElement
  capture preserves it)
- Match `--fps` with the render's fps; overlays must also match the
  base footage's frame rate when composited
- **Hand every alpha layer to `helpers/check_alpha.py` before it leaves your
  hands.** A dropped alpha channel is a silent failure: the encoder exits 0,
  the file plays fine, and the "transparent" layer is a black box over the
  footage. The verdict must come from the **extracted alpha plane**, because
  `ffprobe`'s `pix_fmt` is wrong in both directions — HEVC+alpha reports
  `yuv420p` (a good file that looks bad), while a VP9 encode advertises
  `yuva420p` and records `alpha_mode=1` yet round-trips opaque (a bad file
  that looks good).

```bash
python3 <path-to-skill>/helpers/check_alpha.py renders/overlay.mov   # exit 0 = 透明真的在
```

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

The generator copies the narration into the composition and points the element at
it with a **root-relative** path (`assets/audio.mp3`); the framework owns playback,
so the render ships with a synced track — no external alignment step, unlike the
old screen-recording flow. Keep it root-relative: a `../` path is rejected by
`hyperframes check` (`invalid_parent_traversal_in_asset_path`), and
`generate-composition.py --verify` now fails on one too.

If the audio sounds too quiet/loud versus expectations, normalize the
source once with ffmpeg loudnorm and re-render; do not touch the
composition timing.
