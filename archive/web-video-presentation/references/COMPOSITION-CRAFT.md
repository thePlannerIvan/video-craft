# Composition Craft (Phase 3)

The visual source of truth is `composition/index.html`, a HyperFrames
composition. React pages no longer implement final visuals.

## Workflow per chapter

1. `scripts/generate-composition.py <project> --theme=<id>` produced the
   skeleton: one clip per visual step, timing locked to timeline.json.
2. Read `composition/index.html` first. Implement each step's visual
   INSIDE its clip (`<section class="clip scene" id="step-...">`).
3. After each chapter: `cd composition && npm run check` — must be 0 errors.

## Hard rules

- **Never change generated timing**: `data-start` / `data-duration` /
  `data-track-index` / root `data-duration` / the `<audio>` element.
  Timing changes happen upstream (regroup SRT → rebuild timeline.json →
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

## The video-use handoff contract

When the project's input came from video-use (see SKILL.md Phase 0):

- `input/audio.mp3` + `input/subtitles.srt` are produced by
  `scripts/video-use-handoff.py` (sentence-level SRT via
  video-use's `srt_export.py`).
- The SRT timing equals the video-use final cut's output timeline;
  the composition's clip times come from that SRT — the rendered
  video can be intercut with the original footage because both share
  the same audio clock.
- Never swap in video-use's `master.srt` (2-word caption chunks) —
  it will fragment semantic grouping in Phase 2.
