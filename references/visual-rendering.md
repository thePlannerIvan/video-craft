# Rendering (delivery state)

> **老路线存档**：本文里凡涉及 `import_svg_page` / `generate-composition` / `check_parity`
> 或「保真页面(page)」的段落，都是 **page 十步路线的存档说明**，新项目不要照做。
> 画面的唯一入口是 `helpers/film.py`（见 [film.md](film.md)），存档总览见
> [legacy-page-route.md](legacy-page-route.md)。


`composition/` is the **single source** of the picture track. Review runs on the
live composition — `live_stage.py` serves it, `build_review.py` packs the
snapshot, the official player plays it; no frames are rendered for a review
round. The delivery render happens **once**, after both review surfaces are
confirmed. Deterministic: the same composition always produces the same video,
so that one render is reproducible — no screen recording anywhere in the flow.

## Prerequisites

- `references/timing-lock.md` passed: `python3 visual/scripts/generate-composition.py <project> --verify` exits 0
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
npm run render -- --workers <N>   # → renders/<project>_<timestamp>.mp4
```

**命令里必须带上 `--workers`。** `npm run render` 的默认值是 `hyperframes render` 自己的默认，
也就是粗体的 `auto`（按核数开满 Chrome，见下面第 70 行的警告）。把 `check_render_env.py --json`
报的 `workers` 传进去：

```bash
W=$(python3 <craft>/helpers/check_render_env.py <project>/composition --json \
      | python3 -c 'import json,sys; print(json.load(sys.stdin)["workers"])')
npx hyperframes render --workers "$W" -o /tmp/<name>.mp4 --resolution landscape -f 30 -q delivery
```

### 首次渲染的 `compile` 是冷启动，别把它当成「渲不动」

`hyperframes render` 的账单里 `compile` 与 `capture` 是两笔，而**第一笔是一次性的**：

| | compile | capture | 合计 |
|---|---|---|---|
| 冷缓存（227 帧） | **24m 44.8s** | 18.3s | 25m 5s |
| 暖缓存（641 帧） | **0.1s** | 38.6s | **40.2s** |
| 暖缓存整片（9342 帧 / 311s） | 5m 23.1s | 8m 37.4s | 14m 11.6s |

抓帧本身只要 **0.06 秒/帧**；一次「跑了三分钟没有任何输出」的渲染，其实还卡在 compile 里，
不是渲不动。缓存落在外层（`XDG_CACHE_HOME`，或默认 `~/.cache/hyperframes`）；在沙箱里每次
重定向 cache 都会重付一次那二十多分钟。

所以：**交付渲染前先渲一个 3–5 秒的短片段把缓存焐热**，然后再渲整片。别因为一次冷启动的
长等待就判定「这台机器渲不了」而改去手工搭 ffmpeg 分叉 —— 那等于用一条不可复现的路径
换掉十几分钟的等待。

### `snapshot` 不能用来抓帧序列

`snapshot` 每帧都要重起一次浏览器，实测约 **85 秒/帧**；`render` 是 0.06 秒/帧。要抓帧序列
（做对比图、抽帧检查）用 `render`，需要逐帧文件就用 `--format png-sequence`。
`references/composition-craft.md`、`timing-lock.md` 与本文件下文推荐 `snapshot` 的地方，
指的是**抓少量关键帧做视觉核对**，不是批量抓帧。

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
- `--workers N` — parallel render (default `auto`, i.e. one worker per core)
- `--resolution portrait` — upscale capture to 1080x1920 (aspect must match)

> ⚠ **`--workers auto` is the dangerous default.** It opens one Chrome worker per
> core, and each worker carries roughly 1.5 GB of decoded frames. Measured: 9394
> frames at 1920×1080, 6 cores, 8 GB RAM → 6 Chrome processes → swap filled to
> 8.2 GB → the machine crashed. **Start at `--workers 1`.** To raise it, render a
> 3–5 second slice first, then take the lower of `floor(total GB ÷ 1.5)`,
> `floor(available GB ÷ 1.5)` and the core count (on that 8 GB machine the answer
> is ≤ 2); when the memory budget is unknown, stay at 1.
> `helpers/check_render_env.py` reports RAM, available memory and swap, and prints
> the `--workers` value this machine can carry — pass that number instead of
> deriving your own.

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
- Because it raises the memory ceiling on purpose, **never point it at the whole
  film first**: render a 3–5 second slice to prove the alpha survives, then
  widen. Keep `--workers` at the low end while doing it (see the `--workers`
  note above).
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

## Verify the render (delivery)

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

## Acceptance (engineering state)

Acceptance happens **before any render**, on the live composition:
`live_stage.py` serves the HyperFrames preview, `build_review.py` packs the
review snapshot, and the author watches the real composition in the official
player, screen by screen. Ask one question: ship it, or fix specific steps?
On "fix": edit `composition/index.html`, re-run `npm run check`, **rebuild the
review** (`build_review.py`) and show it again — no re-render.

Only after the author has confirmed **both** review surfaces (the word-level cut
surface and the motion/composition surface) does a single real render happen.
Delivery verification (`verify_delivery.py`) then checks the actual film file.

## Delivery

Render once, then log the render (duration, size, version) in `project.md`.

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
