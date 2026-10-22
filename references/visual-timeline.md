# Visual timeline (EDL-derived)

> 本文涉及 page 路线的段落已归档（见 [legacy-page-route.md](legacy-page-route.md)）；现行 recompose 路线见 [film.md](film.md) 与 [recompose-mode.md](recompose-mode.md)。命令集中在 [tools.md](tools.md)。


The visual layer's timing comes from **the EDL's measured timeline**, not from a
re-parse of the subtitles. SRT is a *view* of the same cues; deriving from it a
second time threw away what the EDL already knew and re-computed the same numbers
from a lossier source.

```
edl.json + segment_durations.json + caption_words.json + captions.json
                              │
                 helpers/timeline_derive.py + timeline/grouping.json
                              ▼
                    timeline/timeline.json
                              │
                 （已归档）generate-composition.py
                              ▼
                  composition/index.html
```

## Inputs

Required:
- `edit/captions.json` — the cue list, written by `srt_export.py --build`
- `edit/caption_words.json` — the word contract, `timeline_source: "measured"`

The deriver accepts `measured` or `projected` and **refuses a nominal timeline**.
`projected` comes from `duration_plan.py`: the frame-quantised `ceil(raw × fps) / fps`
grid, which reproduced all 14 segment durations of a real render exactly. It exists so
the spine, the captions and the review surface can be built *before* the film is
encoded; it prints that it is unverified, and delivery still requires a real render
(`_edl.render_record` ignores projected records by default). `caption_words.json` records which
timeline it was built on; cues off the EDL's nominal Σ(end−start) are up to a
second early, so a visual step placed on them lands before its own narration. If
the guard fires, run `duration_plan.py` first to get the projected record, then
re-run `srt_export.py --prepare --lock --build`; only delivery verification needs
a real render.

Optional:
- `edit/timeline/grouping.json` — the per-beat visual decision (`visualModel` /
  `modelStructure` / `screenIntent` / `onScreenTextRule`) that Step 2 turns into
  `timeline.json`. This is **not** the upstream `deliverable/visual-plan.json`,
  which is the content contract (`video-story-handoff.md`).
- `edit/assets/` — images, screenshots, frames, logos, charts.

**Never edit a cue's time.** Times are measured facts about the render.

## Step 1 — derive the cue entries

派生与统计命令见 [tools.md](tools.md)「SVG 与视觉时间」；`--stats` / `--entries-only` 用于核听。

Each entry carries the SRT-compatible contract (`index`, `startMs`, `endMs`,
`durationMs`, `text`) **plus** what only the EDL side knows: `segment`,
`sourceRange`, `wordIndices`, `transcriptIndices`, `source`.

Times are rounded to whole milliseconds with the same rounding the SRT writer
uses, so a cue addressed here and the same cue read back from `subtitles.srt`
agree exactly.

## Step 2 — group cues into visual steps

A cue is not a visual step. A visual step is one complete thought on one screen
state. **This is a creative decision and is not derivable from the EDL**: one cut
range can carry five steps, one step can span a cut.

| Case | Action |
|---|---|
| Tiny connectors such as "所以 / 然后 / 好 / 首先" | Merge into the neighbour |
| Several cues explain one object or process | Merge into one visual step |
| Topic, object, or argument changes | Start a new step |
| A conclusion or punchline lands alone | Can be its own step |
| Merged duration under 2s | Usually too thin; merge |
| Merged duration over 15s | Usually too heavy; split if meaning allows |

`timeline/grouping.json` — referencing cue indices, never times:

```json
{
  "chapters": [
    {
      "id": "intro",
      "title": "开场",
      "steps": [
        {
          "cueIndices": [0, 1, 2],
          "screenIntent": "用一个问题建立开场钩子",
          "visualModel": "问题钩子图",
          "modelStructure": "中心问题 + 两个方向被拉开",
          "onScreenTextRule": "主画面只保留中心问题，完整字幕不搬上屏幕",
          "assetNeeds": ["产品截图或主题图"],
          "sourceBlueprintId": "blueprint-beat-03"
        }
      ]
    }
  ]
}
```

Do **not** put `startMs`, `endMs` or `durationMs` in `grouping.json` — the deriver
computes them. `srtIndices` is still accepted as an input alias from older files;
the output always uses `cueIndices`.

When a visual plan exists, first run the measured alignment in `video-story-handoff.md` and pass `--alignment` when deriving. Keep one `sourceBlueprintId` per step. One blueprint may
span several steps inside its beat, but a step may not combine two blueprints or
cross into another blueprint's beat.

## Step 3 — build the timeline

完整派生命令（`--grouping` / `--alignment` / `--output-timeline` / `--output-durations`）见 [tools.md](tools.md)「SVG 与视觉时间」。

`timeline.json` is the project-level truth for visual steps. Per step it emits
`startMs` / `endMs` / `durationMs` / `caption` (computed from the first and last
cue), the creative fields from `grouping.json`, and the EDL binding
(`cueRange`, `segments`, `wordCount`, `sourceRange`).

## 时间轴自报时间来源

`timeline.json` 顶层带 `timeSource`（`measured` / `measured-guessed` / `projected` / `nominal` / `srt-import`）
与 `measuredTotalMs`。字幕、交付核验都按它取时间基准：只有 `measured` 才用渲染记录的分段时长，
其余用标称时长。**画面与字幕共用这一条时间轴，不存在第二条。**

## Step 4 — hand-write the composition

recompose 路线没有生成器：`composition/src/scenes/*.js` 由 Agent 按 `film.py` 的拆解手写，
每个 clip 的 `data-start` / `data-duration` 从 `timeline.json` 取。**不要手改这两个属性**——
改分组、重派生时间轴，再让场景从新 timeline 读数。
（page 路线的 `generate-composition.py` 已归档，见 [legacy-page-route.md](legacy-page-route.md)。）

## Checkpoint

Stop after `grouping.json`, `timeline.json` and `storyboard.md` exist, and review
**at the pixels** rather than in prose: build 2–3 representative steps into the
composition and open them with `live_stage.py` + `build_review.py`, and let the
user settle **the layout and the rhythm** in one pass. Only when that route has no
composition to play (hand-drawn frame-by-frame) do you render those slices.
画面风格在画面侧（`planners-ppt-hell`）已经定了，这里不重新选风格。 A written storyboard asks the user to imagine the thing they
are being asked to approve.

Before building the rest, confirm:

- Are the steps too fragmented, or too heavy?
- Does every step model the content rather than replaying subtitle lines?
- Does one visual model persist across related speech instead of resetting per cue?
- Which assets are real, which are placeholders?
- Does every upstream `must_show` item have a visible carrier, and does the model
  make every `must_express` fact legible without repeating the caption?

## Provenance

Retired on 2026-09-15: `visual/scripts/parse-srt.py` (now `archive/parse-srt.py`)
and its `timecode-map.json` step. The replacement was accepted on a byte-identical
composition skeleton — same grouping in, `cmp`-identical
`composition/index.html` out (31384 bytes on the 野人先生 project; 510 of 510 shared
scalars equal, the only differences being the deliberate `source: srt → edl`
rename and the added EDL-side fields).
