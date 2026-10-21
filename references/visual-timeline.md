# Visual timeline (EDL-derived)

> **老路线存档**：本文里凡涉及 `import_svg_page` / `generate-composition` / `check_parity`
> 或「保真页面(page)」的段落，都是 **page 十步路线的存档说明**，新项目不要照做。
> 画面的唯一入口是 `helpers/film.py`（见 [film.md](film.md)），存档总览见
> [legacy-page-route.md](legacy-page-route.md)。


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
                 visual/scripts/generate-composition.py
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

```bash
python helpers/timeline_derive.py <edit_dir> --stats
python helpers/timeline_derive.py <edit_dir> --entries-only > /tmp/entries.json
```

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

```bash
python helpers/timeline_derive.py <edit_dir> \
  --grouping timeline/grouping.json \
  --alignment timeline/content-alignment.json \
  --output-timeline timeline/timeline.json \
  --output-durations composition/public/step-durations.json
```

`timeline.json` is the project-level truth for visual steps. Per step it emits
`startMs` / `endMs` / `durationMs` / `caption` (computed from the first and last
cue), the creative fields from `grouping.json`, and the EDL binding
(`cueRange`, `segments`, `wordCount`, `sourceRange`).

## Step 4 — generate the composition skeleton

```bash
python visual/scripts/generate-composition.py <project> --theme <theme-id>
```

It writes one `clip` per step with `data-start` / `data-duration` taken straight
from `timeline.json`. **Do not edit those attributes by hand** — change the
grouping and regenerate.

## Checkpoint

Stop after `grouping.json`, `timeline.json` and `storyboard.md` exist, and review
**at the pixels** rather than in prose: build 2–3 representative steps into the
composition and open them with `live_stage.py` + `build_review.py`, and let the
user settle **the layout and the rhythm** in one pass. Only when that route has no
composition to play (hand-drawn frame-by-frame) do you render those slices.
The theme was already decided when the picture was made (`themes.md`), so it is
not re-picked here. A written storyboard asks the user to imagine the thing they
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
