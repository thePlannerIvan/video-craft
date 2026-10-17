# Composition Craft (Phase 3)

The visual source of truth is `composition/index.html`, a HyperFrames
composition. React pages no longer implement final visuals.

## Workflow per chapter

1. `visual/scripts/generate-composition.py <project> --theme=<id>` produced the
   skeleton: one clip per visual step, timing locked to timeline.json.
2. Read `composition/index.html` first. Implement each step's visual
   INSIDE its clip (`<section class="clip scene" id="step-...">`).
3. After each chapter: `cd composition && npm run check` — must be 0 errors.

## Hard rules

- **Never change generated timing**: `data-start` / `data-duration` /
  `data-track-index` / root `data-duration` / the `<audio>` element.
  Timing changes happen upstream (regroup measured cues → rebuild timeline.json →
  re-run the generator). If you need different timing, regenerate.
- **HyperFrames composition contract** — read `/hyperframes-core` before
  writing any HTML. Non-negotiables that silently break:
  - one paused `gsap.timeline` at `window.__timelines["main"]`
  - root must have `data-start="0"` and explicit 1920×1080 sizing
  - initial hidden states via `gsap.set(...)` outside the timeline
    (a `tl.set` at position 0 does NOT render at frame 0)
  - never pair a CSS initial `transform` with a GSAP tween on the same
    property (lint rejects)
  - full-frame fills go on an `inset:0` child, never the root
    (the root's own background can render black)
  - no `<br>` in body text; transformed elements must be block-level + sized
- **Progressive reveals**: consecutive steps of the same visual skeleton
  should merge into one scene and reveal progressively via the GSAP
  timeline (the generator leaves per-chapter boundary hints). This is the
  v2 equivalent of the old "场景合并 + 内部渐进揭示" rule.
- **Fonts**: use families HyperFrames resolves deterministically
  (Inter, Noto Sans SC, JetBrains Mono, Montserrat, EB Garamond, ...).
  `-apple-system` / `PingFang SC` produce a benign compiler warning and
  fall back to the mapped font — fine, but don't rely on them.
- **Contrast**: `npm run check` enforces WCAG AA on text. Fix by
  adjusting the theme token in the composition `:root`, not by
  hard-coding colors per step.

## Font metrics — why lines wrap (measured, 2026-08)

`npm run check` will NOT catch a line that wraps and overflows its
box. Measure text against real glyph widths before shipping:

| glyph | width (Noto Sans SC) | width (Inter 900) |
|---|---|---|
| CJK char (汉字) | 1.0 em | — |
| ASCII space | ≈ 0.5 em | ≈ 0.5 em |
| `·` (middle dot) | ≈ 1.0 em | ≈ 0.62 em |
| ASCII digit | ≈ 1.0 em | ≈ 0.5 em |
| `%` | ≈ 1.0 em | ≈ 0.62 em |

So `30000+ 篇笔记` at 40px is NOT 9 chars × 40px — digits run ~0.5em
each and the `+` is narrow, and a CJK string full of `·` can wrap
mysteriously early. Rule of thumb for CJK + Latin mixed labels:
count CJK chars at 1em, Latin chars at ~0.55em, then pick font-size so
the sum fits the box with ≥ 8% margin.

**Wrap self-review ritual (mandatory after each chapter):**
1. `cd composition && npm run check` — 0 errors first
2. `npx hyperframes snapshot --at <chapter midpoint> --zoom 2` →
   render the frame (the snapshot is a screenshot the model can read)
3. eyeball every element whose text contains `·` / digits / spaces —
   these are the ones that wrap in practice (seen: CTA copy, stat
   pills, "打口感·打质量" card, "30000+ 篇笔记" chips)
4. if a label wrapped: shrink font-size OR widen the box, re-check,
   re-snapshot — verify the fix in pixels, not in reasoning

## After `npm run check` — the data-hf-id gotcha

`npm run check` (and `npm run render`) rewrites `composition/index.html`
and injects `data-hf-id` attributes into elements. Consequences:

- an `Edit` old_string that matched before `check` will fail after it
  (the elements now carry injected attributes)
- if a subsequent edit "fails unexpectedly", grep the element first:
  `grep -o 'data-hf-id="[^"]*"' composition/index.html | head` — then
  match on surrounding text that excludes the injected attribute
- never run `check` mid-chapter expecting the file to stay byte-identical;
  the linter is also a formatter

## Animation

Read `/hyperframes-animation` for atomic motion rules and scene
blueprints (GSAP is the default adapter). Time tweens against the
step's data-start so payoffs land on the spoken word.

## 画面页来自 planners-ppt-hell 时的动画交接

视频静态画面的出口是 SVG 页，保留 SVG 的理由就是后面还要按口播强调元素。所以接手一屏画面，
接的是一份**能被按元素指名的活结构**，不是一堆文件。实测过 44 张真实页面：`<text>` 仍是文字
（1356 个 `<text>` 对 2 个 `<path>`，逐字动画可行）、没有 `clipPath` / `mask` / `transform`
被提前拍平、画布统一 `viewBox="0 0 1920 1080"`，**所以页面坐标就是视频像素，挂时间轴不用换算**。
缺的是元素身份：那些页面在 `<svg>` 之下一个 `id` 都没有。

### 页面从哪来

两种包都认，按这个顺序找：

1. 项目根的 `.pages` 指针（一行路径）指向做画面项目根 → 用它的
   `_internal/02_svg_source/<page_key>.svg`；
2. 上游随包交来的 `input/scenes/<page_key>.svg`（一屏一个文件）。

### 导入：`visual/scripts/import_svg_page.py`

它把页面**逐字内联**进 composition，只改写 `<image>` 的 `href` / `xlink:href` 前缀
（页面里写的是 `../00_project/...`，HyperFrames 会以 `invalid_parent_traversal_in_asset_path` 拒绝），
并把被引用的图片拷进 `composition/assets/pages/<page_key>/`。页面其余部分——标签、`id`、坐标、
文字节点——一字不动。导入器用「把 href 写回去 == 源文件字节」自证这一点，
每个页面的源哈希、内联哈希与替换清单记在 `composition/pages/manifest.json`。

一屏来自哪一页：在该步的 `grouping.json` 里写 `sourcePageKey`；生成器据此内联，并把下面那张表的三个事实
写成该屏 clip 的属性。

```bash
python3 visual/scripts/import_svg_page.py <project> --pages <picture-project> --audit
python3 visual/scripts/import_svg_page.py <project> --page beat-01 --prove
```

`--audit` 逐页报出可被指名的元素数量，并在一页于 `<svg>` 之下没有任何 `id` 时退非零——
那种页面只能整页动，需要做画面那边补 `id` 再重渲。

### 按 id 指名元素，不用 DOM 序号

`gsap.to("#peak-2026", …)`，而不是 `svg.children[8]`。做画面重渲时只要多一个 `<text>`，
序号就会**静默**绑到别的元素上：该强调的地方强调到别的东西，而且不报错。要新钩子时改的是页面
（补一个稳定 `id`），动画层只读。

### 动效加在外层

`clipPath` / `stroke-dasharray` / `transform` 用在包住 `<svg>` 的包裹层上，页面本身保持原样。

**页面自带的 `transform` 与 GSAP 互斥**：GSAP 第一次碰一个元素时把它的 `transform` 解析进自己的矩阵，之后每次补间都按自己的值重新写回 `transform` 属性 —— 页面上的 `translate(-40,16.5)` 在第一次 y/x/scale/rotation 补间时就没了，而且不报错。要么把静态位移/旋转挪到外层包裹层，要么这条元素只做不碰 transform 的补间（透明度、描边）。`check_motion_targets.py` 会把「页面声明了 transform 又被补间」的元素列出来。

**量静态几何要在静态页面上量**：不要在被 GSAP 跑过的 composition 里量元素位置 —— 那时量到的是动画态（transform 已被改写、补间 from 值已生效），据此改页会把位移修反。量页面用 PPT Hell 的页面 PNG 或源 SVG 的 `getCTM`（未动画）。
`planners-ppt-hell` 的 `svg_rules.md` 管的是**页面**，动画层在它之外，所以这条交接不需要放松页面规则。

### 每屏的合成事实从哪读

三个事实——`composite` / `personWindow` / `captionSafe`——的**键名、取值域、默认、谁填谁读**
写在[合成事实的字段契约](composition-facts-contract.md)里，那里是唯一来源（`planners-ppt-hell`
点名要求这三个键，不自己造名字）。这里只说它们怎么流进 composition：

```text
design_direction.md 的 json 代码块（整片默认）  ┐
                                              ├─► generate-composition.py ─► clip 的 data-* 属性
该步 grouping.json（单屏例外，经 timeline.json）┘                          └─► pages/manifest.json
```

生成器把三个事实落到该屏 clip 的 `data-composite` / `data-person-window` / `data-caption-safe`，
同时记进 `composition/pages/manifest.json` 的 `perScreen`。它们不改 clip 的时序。

`replace` 的屏是满屏不透明层（EDL 里 `kind: "opaque"`）；`over-person` 的屏是 alpha 层
（`kind: "alpha"`），底片保留人物。两个值由 EDL 的覆盖层声明落实。

### 画面留在 SVG 里做动效

栅格化成 PNG 会丢掉逐字文字和元素身份，而页面本来就是活的。
`id` 由做画面那边输出（可能被强调的元素都带一个），这里只读。

### 做画面那边要交的

1. 每个**可能被强调**的元素带稳定 `id`。这条对 PPT 那条路免费：实测给整页加 79 个 `id`，
   转换器输出逐字节相同（两边 md5 一致）。
2. 图片 href 保持 `../00_project/...` 原样——那条路径是页面给自己 PPT 出口用的，改前缀的是导入器。
3. 整片的合成方式、人物窗口、字幕安全区写进 `_internal/01_content/design_direction.md` 的 json 代码块。
4. **若使用预埋子元素动效契约**（如 `editorial-archive` 四域风格，在 `<g>` 上预埋了 `data-step`、`data-anim`、`pathLength="1"` 与语义子选择器 `.anim-bar` / `.anim-mask` / `.anim-bg` / `.anim-title` / `.anim-photo` 等）：直接按 [`svg-animation-contract.md`](svg-animation-contract.md) 保留语义结构，再由 HyperFrames composition 自己实现 seek-safe 的时间线；新工程不把 `VideoCraftAnimEngine` 接入 HyperFrames 主时钟。旧 SVG 审阅若要即时预演，才使用 `visual/assets/svg-anim-engine.js`。

## Assets

Media lives in `<project>/input/assets/`. Reference from the
composition as `../input/assets/...`. Never copy large media into
`composition/`.

## Style

- Colors / fonts / corner rules come from theme tokens in the
  composition `:root` (inlined by the generator from `tokens.css`).
  Hard-coding a hex color or font family in a step is a bug.
- One design signature per theme; don't stack three.
- No emoji decoration, no fake data — the same editorial rules that
  governed v1 chapters.

## Where the timing comes from

The composition's clip times come from `timeline/timeline.json`, which
`helpers/timeline_derive.py` derives from the EDL plus the caption contract — see
`visual-timeline.md`. The rendered video and the cut footage therefore share one
audio clock and can be intercut without realignment.

The old `video-use-handoff.py` bridge (it assembled an `input/` folder by
importing video-use's internals) is retired to `archive/`: it imported a function
that no longer exists, and its job is now a single derivation step.

## 画面决定的适用范围

设计前读 [visual-direction.md](visual-direction.md)，并按 [preferences.md](preferences.md) 区分本片要求和可复用偏好。某个项目的全屏网格、角落人物、不用推拉，不构成所有视频的固定样式。素材保持正确比例，观众画面不夹带制作备注；明确授权的创作性变形除外。
