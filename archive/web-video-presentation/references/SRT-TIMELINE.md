# SRT Timeline Workflow

SRT-first is the default workflow. The edited audio already exists; the page must play in lockstep with its SRT timecodes.

## Inputs

Required:
- `input/subtitles.srt`

Optional:
- `input/audio.mp3` for final recording sync checks
- `input/script.md` for wording reference only
- `input/visual-plan.json` for one information blueprint per visual Speech Beat
- `input/visual-blueprint.md` for human-readable visual context
- `input/assets/` for images, screenshots, video frames, logos, charts

Never change SRT timecodes. If text has obvious typos, ask before editing the SRT text.

## Phase 1: Parse SRT

```bash
python3 scripts/parse-srt.py input/subtitles.srt \
  --output timeline/timecode-map.json \
  --stats
```

`timecode-map.json` is the raw subtitle timeline:

```json
{
  "totalEntries": 258,
  "totalDurationMs": 481600,
  "entries": [
    { "index": 0, "startMs": 0, "endMs": 1467, "durationMs": 1467, "text": "..." }
  ]
}
```

## Phase 1.5: Align Video Story Information Requirements

If`input/visual-plan.json`exists, read`VIDEO-STORY-HANDOFF.md`and run`align-visual-plan.py`with the final`script.md`before semantic grouping. It aligns Speech Beats to SRT, then gives each one-beat content blueprint its own candidate range. Treat low or unmatched Beats as a human-review queue. Keep blueprint boundaries intact; design the actual visual model, layout, animation states and timing inside each Beat in Phase 2. Upstream fields are content requirements, not screen instructions.

## Phase 2: Group SRT Lines Into Visual Steps

SRT line does not equal visual step. A visual step is one complete thought shown on one screen state.

Grouping rules:

| Case | Action |
|---|---|
| Tiny connectors such as "所以 / 然后 / 好 / 首先" | Merge into neighbor |
| Several lines explain the same object/process | Merge into one visual step |
| Topic, object, or argument changes | Start a new step |
| A conclusion or punchline lands alone | Can be its own step |
| Merged duration under 2s | Usually too thin; merge |
| Merged duration over 15s | Usually too heavy; split if meaning allows |

Create `timeline/grouping.json` manually or with agent assistance:

```json
{
  "chapters": [
    {
      "id": "intro",
      "title": "开场",
      "steps": [
        {
          "srtIndices": [0, 1, 2],
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

Do not put `durationMs`, `startMs`, or `endMs` in `grouping.json`. The script computes them from SRT.

When a visual plan exists, preserve one`sourceBlueprintId`per grouped Step. One blueprint may span several Visual Steps inside its bound Beat, but a Step may not combine multiple upstream blueprints or cross into another blueprint's Beat.

## Build Timeline Artifacts

```bash
python3 scripts/parse-srt.py input/subtitles.srt \
  --grouping timeline/grouping.json \
  --output-timeline timeline/timeline.json \
  --output-durations presentation/public/step-durations.json
```

`timeline.json` is the project-level truth for visual steps. `step-durations.json` is the runtime timing file.

## Chapter timeline.ts

Each chapter copies its matching `timeline.json` steps into `src/chapters/<id>/timeline.ts`:

```ts
export const timeline = [
  {
    id: "intro-001",
    caption: "SRT lines merged into this visual step.",
    srtRange: [0, 2],
    startMs: 0,
    endMs: 6200,
    durationMs: 6200,
    screenIntent: "Use one strong opening image."
  }
];
```

`timeline.ts.length` must equal the number of `step` states implemented by the chapter component.

## Checkpoint Plan

Stop after `grouping.json`, `timeline.json`, and `storyboard.md` are ready. Use the webpage, not only chat, to confirm screen plans.

Recommended setup:

```bash
cp timeline/timeline.json presentation/public/storyboard-review-data.json
cd presentation
npm run dev
```

Open:

```text
http://localhost:5174/?review=storyboard
```

The page must show, for each visual step:

- merged SRT caption
- SRT range and exact duration
- screen intent / 画面文字描述
- visual model and model structure
- asset needs
- feedback textbox bound to that step
- source Blueprint ID when imported from Video Story System

Ask the user to confirm:

- Are visual steps too fragmented or too long?
- Does every step have a clear screen intent?
- Does every step model the content instead of replaying subtitles sentence by sentence?
- Which assets are real, missing, or placeholder?
- Are all low/unmatched Speech Beats resolved?
- Has this phase designed the actual visual model, animation states and timing instead of expecting them from upstream?
- Does the model persist across related speech instead of resetting per subtitle line?
- Does every upstream `must_show` item have a visible carrier, and does the model make every `must_express` fact legible without merely repeating the subtitle?
- Which theme should be used?
- Which development mode: chapter-by-chapter, sequential, or parallel?

Before Phase 3, read `feedback/storyboard.jsonl` and revise grouping/storyboard/timeline if needed.
