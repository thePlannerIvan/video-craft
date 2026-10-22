# Recompose build mode — 默认遵循原构图，原片不适合动画时重排

这是 Video Craft 的**主制作路线**：作者在 `planners-ppt-hell` 里确认画面、录制，Craft 把
board 当视觉参考重做成片。判据只有一条：

> **画面内容不重写。默认遵循原构图，只有原片不适合作为视频动画呈现时才重排。**
> 口播稿、事实、结论归作者与上游；怎么画、怎么动归 Craft。重排要在拆解表写明理由。

`page` 十步路线已于 2026-10-21 整条归档（见 [legacy-page-route.md](legacy-page-route.md)），
不再维护。新项目一律走 recompose，作者不需要在开工前选路线；只有复活旧项目时才读那份存档。

## 三条不变量

1. **内容不归本模式重写。** 口播稿、事实、结论仍归作者与上游；本模式只安排视觉层。
2. **board 仍然是第一视觉确认。** 作者在 PPT Hell 里看到并确认画面；recompose 不跳过这一步，
   只是不把 board 当逐像素契约。
3. **成片仍然只有一个审阅面。** 逐字密度是现有动效审阅页右侧整栏反馈的一部分，不是第二个页面。

## 产物

```text
<project>/
  recompose.json            # mode: recompose + draft / composition / 人物位 / 字幕安全区
  recompose/lines.json      # 每个口播行：state + proposal + note
  review/                   # 现有动效审阅页（build_review.py 构建）
  feedback/density.jsonl    # review_inbox.py 收件后追加
```

`recompose.json` 是模式标记；没有它，Craft 走 `page`。`recompose/lines.json` 的每一行来自
字幕 / caption cue，按 `beatId` 分组；`state` 是人的决定，`proposal` 是模型的建议。

## 画布与人物区

recompose 的交付是**画面层**；人物与字幕要么在 composition 里，要么在合成阶段贴回。
无论哪种，坐标只有一个来源：`recompose.json`。

```json
{
  "canvas":     {"w": 1920, "h": 1080, "fps": 30},
  "personSlot": {"x": 0, "y": 0, "w": 620, "h": 1080},
  "captionSafe":{"x": 0, "y": 885, "w": 1920, "h": 195}
}
```

### 换算关系

`personSlot` / `captionSafe` 都是**画布像素**，原点左上，和 composition 里元素的
`left/top` 是同一套坐标——**不乘任何缩放**。播放器与审阅页按根元素的 `data-width` /
`data-height` 整体缩放，composition 内部坐标不变。

人物在左时（默认）：

| 区域 | 公式 | 用途 |
|---|---|---|
| 人物区 | `x ∈ [personSlot.x, personSlot.x + personSlot.w)`，`y` 全高 | 画面不得进入；人物视频或留黑都在这里 |
| 画面安全区 | `x ∈ [personSlot.x + personSlot.w, canvas.w)`，`y ∈ [0, captionSafe.y)` | 舞台主体、图示、花字 |
| 字幕安全区 | `y ∈ [captionSafe.y, captionSafe.y + captionSafe.h)`，`x` 全宽 | 只放字幕/角标，不放主体信息 |

人物在右时镜像：画面安全区是 `x ∈ [0, personSlot.x)`。`captionSafe` 与人物区可以重叠
（字幕压在人物下方的黑边上），但画面主体不能进任一个。

改几何时改 `recompose.json`，然后：

改几何后跑 `recompose_plan.py check`；活舞台契约用 `check_live_stage.py` 复核。两命令的参数见 [tools.md](tools.md)「recompose 主路线」与「免渲染的工程态」。

不要在场景文件里手算一套新的 `500` / `620` / `880`：数值只有一个家，场景从
`recompose.json` 读取。

```python
import json
from pathlib import Path
cfg = json.loads((Path(project) / "recompose.json").read_text(encoding="utf-8"))
stage_x = cfg["personSlot"]["x"] + cfg["personSlot"]["w"]
stage_bottom = cfg["captionSafe"]["y"]
```

### 两种合法交付形态

| 形态 | composition 里有什么 | 人物从哪来 | 交付说明必须写 |
|---|---|---|---|
| **合成层** | 人物 `<video class="clip">` + 画面层 | composition 自己播 | 人物与画面已合成；画面避开 `personSlot` |
| **仅画面层** | 只有画面，没有人物的 `<video>` | 合成阶段用 EDL / overlay 贴回 | 这是画面层，不是成片；人物与字幕的时间以另一份素材为准 |

两种都合法。**"只有画面层"不是偷工减料**：画面层可以独立审、独立改、独立重渲，
人物母版不必进 `composition/assets`（也躲开了活舞台的资产预算）。选择哪种写进
`production-plan.md`，不要两份都做一半。

### `live_stage.py` 的目录限制（已选择写进文档，不改代码）

`live_stage.py` 接受 `--composition <dir>`，并把它透传给 `hyperframes preview`；
但 `project_root()` 和 `build_review.py` 的 `has_composition` 都要求项目里存在一个
**名为 `composition` 的目录**（否则活舞台起不来）。所以：

- `composition/` 必须存在，哪怕真正要演的是 `composition-v2/`；
- 用 `--composition composition-v2` 时，`composition/` 里至少要有 `index.html`；
- `review/review_data.json` 的 `liveStage.compositionDir` 会记住实际目录，审阅页按它编译。

选择写进文档而不是改代码，是因为这条要求同时落在 `live_stage.project_root()` 与
`build_review.has_composition` 两处，只改一处会留下另一半；而且改默认目录会影响
`recompose_plan.py` 的默认路径。遇到多套 composition 并存时，先跑
`check_live_stage.py <project> --composition <dir>` 确认要演的那份，再起服务。

## 五步

### 1. 锁事实

- 声音：已锁的 `edit/cut.mp4` 或音轨。
- 剪辑与字幕：`edit/edl.json`、`edit/subtitles.srt`；未锁时先走 `SKILL.md` 第 3–5 步（共用事实层，不属于任何一条画面路线）。
- 时间脊柱：`timeline/timeline.json`（自动派生）。
- 词级锚点：`edit/caption_words.json`。
- board：PPT Hell 视频路线导出的页面 / 快照，作为视觉参考。
- 人物孔位、字幕安全区、画幅。

初始化与检查命令见 [tools.md](tools.md)「recompose 主路线」；`init` 的两个前置文件见下。

**`init` 的两个前置文件（缺一个它就退 1）**：

- `timeline/timeline.json` 必须有非空 `chapters[].steps[]`（每步 `startMs` / `endMs`）。
  EDL 项目用 `timeline_derive.py` 产；外部剪好音频 + SRT 的项目用 `import_srt_timeline.py`
  （需要 `--alignment`，来自上游 visual-plan）。**没有上游内容包的项目（自己录 / TTS 配音）
  这两条都用不了，只能手写 timeline.json** —— 手写时把顶层 `totalChapters` / `totalSteps` /
  `totalDurationMs` 一起写上：审阅页顶栏与播放器总时长读的就是这三个字段。
- `edit/subtitles.srt` 或 `edit/captions.json`，至少一条字幕行。

`init` 从字幕生成逐行预算：默认 `state: auto`、`proposal: still`。模型可以在
`recompose/lines.json` 里逐行给 `proposal`（`off/still/light/full`），作为“自动”的建议值。

### 2. 建 composition

- **不要** `import_svg_page.py`、`generate-composition.py`、`auto_choreography.py`；
- 直接写 composition：共享 core（时间轴、HUD、转场）、art 图元库、每个 beat 一个 scene；
- 从 `anchors.js` 读绝对时间；clip 窗口读 `timeline/timeline.json`；
- board 是参考，不是几何契约：**默认遵循原构图**（模型图、层级、排布），只有原片不适合作为视频动画呈现时才重排或重做，并在拆解表写明理由；每片重新拆解，不维护跨项目元素库；
- 人物位按 `recompose.json` 的 `personSlot`；画面不能进这个区域。

### 3. 审阅：左侧预览 + 右侧整栏反馈

审阅只用一条命令：`python3 "<craft>/helpers/review.py" "<project>"`（内部完成编译 → 构建 → surface → 运行时判据）；细节见 [tools.md](tools.md)「免渲染的工程态」。

审阅期间保持 `live_stage` 进程运行：它给工程态预览提供编译路由。停掉后页面会提示
「预览暂时无法启动」；要恢复就重跑 `live_stage.py ... --composition <dir>` 再刷新。

recompose 模式下，`build_review.py` 把 `recompose/lines.json` 写进
`review/review_data.json` 的 `density` 块。页面重排为：**左侧大预览 + 视频下方横向 Beat 编号切换 + 视频下方整 beat 反馈；右侧逐句调整 / 历史反馈**。历史反馈是低频 tab；左侧和右侧中间的分界可以拖动。

- **整 beat 反馈**：视频下方，占满左栏剩余高度；
- **逐句调整**：右侧主 tab，按口播逐字稿的行调密度，批量条在句子列表上方；
- **历史反馈**：右侧低频 tab，读 `feedback/*.jsonl`。

- **单位是口播逐字稿的行**，不是 beat。beat 只是分组标题与批量入口。
- 每行状态：`auto`（跟模型建议）/ `off`（无画面，只留字幕）/ `still`（仅配图，一张静态图）/ `light`（轻动效）/ `full`（完整动效）。
- 默认全部 `auto`；作者只改例外。改过的行数显示在顶部。
- 视频下方是横向 B01–B08 切换器，只显示编号；点它切 beat 并定位。
- 右侧逐句列表整栏高度；播放时当前行高亮；点行定位到那句；`0/1/2/3/a` 设状态。
- 多选：单击、Shift 连选、Cmd/Ctrl 加选、按住拖过多行；批量条一次应用到所有选中句。
- beat 标题可一键“全无画面 / 全完整动效”；「只看非自动」过滤；「撤销」回退上一次批量。
- 不再显示原来的分步动效 tab；需要动效细节时由 agent 在 composition 里处理，作者只按句调密度。
- 提交写入现有 `review/review-submissions.json` 的 `phase: "density"` 记录，走同一个
  `feedback/` 收件；不新增第二套提交格式。

**`off` 是结构指令，不是动效参数。** 它表示这一句没有视觉层；模型要删/隐藏对应段，而不是把
不透明度调到 0。连续图跨越 5 句、其中第 3 句标 `off` 时，模型负责把图拆成两段或在那一句
做可见的停顿/淡出；不要求作者画时间线。

### 4. 收件与定点返修

收件：`review_inbox.py <project>`；参数、收据字段与 rejected 处理见 [tools.md](tools.md)「审阅」。

`review_inbox.py` 识别 `phase: "density"` 记录，校验 line id / state，追加
`feedback/density.jsonl`，把 `state` / `note` 回写 `recompose/lines.json`，输出收据。被拒的
记录要修或重建页面后重收，不能假装成功。

模型按更新后的 `recompose/lines.json` **只改受影响的视觉段**：

- `off`：该句不画图；人物与字幕承担。成片仍保留这条时间，不静默缩短。
- `still`：一张稳定概念图，入场与极轻环境动。
- `light`：1–2 个部件随词变化（指针、液柱、游标、粒子半径）。
- `full`：多部件、多阶段，按词级锚点推进。
- 从高到低先收束再删，不从低到高叠层；没被要求改的句子不动。

### 5. 渲染与核验

与 page 路线共用交付门槛；详见 `SKILL.md` 第 10 步与 `references/tools.md`。
recompose **不跑** `check_parity.py`（只有一条实现时没有对象），用 `check_motion_targets.py`
与真实成片核验。

## 与已归档 page 路线的差异

| 继续共用 | 不再使用 |
|---|---|
| 声音、EDL、字幕、词级锚点 | 静态 SVG 快照作为最终几何 |
| timeline 章节 / step 边界 | `import_svg_page.py` / `generate-composition.py` |
| review-core、审阅页、收件 | `check_parity.py`（single-source 时没有对象） |
| 交付核验、指纹、render env | 页面几何契约 |

老路线的说明只在 [legacy-page-route.md](legacy-page-route.md) 里，标明为存档。
recompose 是默认且唯一维护的路线；不存在"日常回 page"这个选择。

## 不要做什么

- 不要把 recompose 做成用户要选的新路线；它是项目级 build mode。
- 不要为密度再开一个独立页面或独立收件箱；它就在现有动效页里。
- 不要在动效页放 board 参考帧：作者已经在 PPT Hell 确认过，成片页只看成片。
- 不要用 `state` 字段假装已实现：密度改了但 scene 没改，等于没改。
- 不要为了通过检查而把 `off` 实现成 `opacity: 0`；那是动效参数，不是结构。
