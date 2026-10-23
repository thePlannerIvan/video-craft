# Visual timeline (EDL-derived)

> 本文涉及 page 路线的段落已归档（见 [legacy-page-route.md](legacy-page-route.md)）；现行 recompose 路线见 [film.md](film.md) 与 [recompose-mode.md](recompose-mode.md)。命令集中在 [tools.md](tools.md)。


## 时间来源与证据等级（权威定义）

| 来源/标记 | 证明什么 | 可以做什么 |
|---|---|---|
| planned | 内容估时，尚无录音事实；项目计划状态，不冒充 timeline 字段 | 制作方案与独立预演 |
| projected | 当前 EDL 的帧量化解析预演 | 工程字幕/时间轴/审阅；不证明成片实测 |
| measured | 渲染时长记录与当前 EDL 指纹一致 | EDL 路径的正式时间依据，仍须核真实交付文件 |
| measured-guessed / nominal | 无匹配指纹或历史降级依据 | 明确风险、恢复项目；不能替代正式交付证据 |
| srt-import | 外部音频与 SRT 经内容对齐 | 外部来源的制作绑定；交付另核实际媒体，绝不声称 EDL measured |

唯一时间脊柱是下游消费接口，不是所有事实的原始生产者。EDL 路径由当前 EDL + 时长记录 + 锁定字幕 cues 派生；外部路径由音频/SRT/对齐派生。SRT 在前者是导出视图，在后者是输入，不能用一句“SRT 永远是真相”或“EDL 是所有项目的唯一来源”混同。

```text
EDL + 同版时长记录 → 字幕 cues ── timeline_derive ──┐
外部音频 + SRT + alignment ── import_srt_timeline ─┤
                                                  ↓
                        project/timeline/timeline.json
                                  ↓
                        手写 composition / 工程审阅
```

字幕字级插值（caption_words）不同于真实 ASR 词级时间。精确卡词调用 align，优先 transcripts，退估算时标 estimated；不手算比例。

## Inputs

Required:
- `edit/captions.json` — the cue list, written by `srt_export.py --build`
- `edit/caption_words.json` — the word contract, `timeline_source: "measured"` 或 `"projected"`

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
- `<project>/timeline/grouping.json`（调用时显式指定；旧项目可能保存在 edit/timeline） — the per-beat visual decision (`visualModel` /
  `modelStructure` / `screenIntent` / `onScreenTextRule`) that Step 2 turns into
  `timeline.json`. This is **not** the upstream `deliverable/visual-plan.json`,
  which is the content contract (`video-story-handoff.md`).
- `edit/assets/` — images, screenshots, frames, logos, charts.

**Never edit a cue's time.** Times are derived facts with the declared evidence level above.

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

## 时间轴字段与现有实现

顶层 `timeSource` 与 `measuredTotalMs` 记录来源状态。当前字幕导出器也会读取已有 timeline 的 `timeSource` 选择口径，这是现有实现耦合，不能据此倒过来手改视觉末帧驱动字幕。另有一项未闭合的实现边界：普通时长记录查询在找不到匹配实测记录时可能回退到 `projected`；因此不能仅凭 timeline 写着 `measured` 就宣称字幕 cues 都由实测记录生成，详见 [implementation-brief.md](implementation-brief.md) B8。恢复项目先核来源、旧 timeline 和记录是否同版，再按步骤 5–6 重建。

新项目显式传 --output-timeline 写入 project/timeline/timeline.json。旧项目若还存在 edit/timeline/timeline.json，_paths 当前优先读取它；只写项目根不会消除歧义，须先核消费者并保留备份，统一采用位置再重建，见 Brief B8。当前 timeline_derive 的 --alignment 是可选参数；有 EDL cues 的项目不因没有上游内容包就只能手写 timeline。

## Step 4 — hand-write the composition

recompose 路线没有生成器：`composition/src/scenes/*.js` 由 Agent 按 `film.py` 的拆解手写，
每个 clip 的 `data-start` / `data-duration` 从 `timeline.json` 取。**不要手改这两个属性**——
改分组、重派生时间轴，再让场景从新 timeline 读数。
（page 路线的 `generate-composition.py` 已归档，见 [legacy-page-route.md](legacy-page-route.md)。）

## Checkpoint

After grouping and timeline exist, review representative work when the visual decision needs confirmation:
**at the pixels** rather than in prose: build 2–3 representative steps into the
composition and open them with `review.py`, and let the
user settle **the layout and the rhythm** in one pass. For frame-by-frame media preparation, follow frame-animation-pipeline.md and label previews as engineering assets.
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
