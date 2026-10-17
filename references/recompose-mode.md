# Recompose build mode — 板子是参考，成片允许重排

这是 Video Craft 的**内部构建模式**，不是用户要选的路线。工作方式没有变：作者仍在
`planners-ppt-hell` 里确认大概画面、录制，然后交给 Craft 做成片。区别只有一条：

> **最终成片是否严格保留那版画面。**
> `page` 保留；`recompose` 只把 board 当视觉参考，允许为了动效重排。

作者不需要在开工前选。`page` 是默认和 fallback；只有当作者明确要“更大自由度”或项目类型
适合连续动画时，才在项目里开 `recompose`。作者说“这版别改”时回 `page`。

## 三条不变量

1. **内容不归本模式重写。** 口播稿、事实、结论仍归作者与上游；本模式只安排视觉层。
2. **board 仍然是第一视觉确认。** 作者在 PPT Hell 里看到并确认画面；recompose 不跳过这一步，
   只是不把 board 当逐像素契约。
3. **成片仍然只有一个审阅面。** 逐字密度是现有动效审阅页底部的一个 dock（与分步动效同区），不是第二个页面。

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

## 五步

### 1. 锁事实

- 声音：已锁的 `edit/cut.mp4` 或音轨。
- 剪辑与字幕：`edit/edl.json`、`edit/subtitles.srt`；未锁时先走 page 路线第 3–5 步。
- 时间脊柱：`timeline/timeline.json`（自动派生）。
- 词级锚点：`edit/caption_words.json`。
- board：PPT Hell 视频路线导出的页面 / 快照，作为视觉参考。
- 人物孔位、字幕安全区、画幅。

```bash
python3 "<craft>/helpers/recompose_plan.py" init "<project>" \
    --composition "<project>/composition" \
    --draft "<project>/recompose/draft.mp4" \
    --person-slot "0,0,620,1080" \
    --caption-safe "0,885,1920,195"
python3 "<craft>/helpers/recompose_plan.py" check "<project>"
```

`init` 从字幕生成逐行预算：默认 `state: auto`、`proposal: still`。模型可以在
`recompose/lines.json` 里逐行给 `proposal`（`off/still/light/full`），作为“自动”的建议值。

### 2. 建 composition

- **不要** `import_svg_page.py`、`generate-composition.py`、`auto_choreography.py`；
- 直接写 composition：共享 core（时间轴、HUD、转场）、art 图元库、每个 beat 一个 scene；
- 从 `anchors.js` 读绝对时间；clip 窗口读 `timeline/timeline.json`；
- board 只当参考：概念、顺序、每 beat 的一两个关键图元；不复制页面几何；
- 人物位按 `recompose.json` 的 `personSlot`；画面不能进这个区域。

### 3. 审阅：现有动效页 + 分段工作区

```bash
# 工程态：起 composition 的活舞台（不渲染），再用同一份 URL 建审阅
python3 "<craft>/helpers/live_stage.py" "<project>" --composition "<composition-dir>"
python3 "<craft>/helpers/build_review.py" "<project>" --mode auto
python3 "<craft>/helpers/review_surface.py" "<project>" --surface-only
```

recompose 模式下，`build_review.py` 把 `recompose/lines.json` 写进
`review/review_data.json` 的 `density` 块。页面重排为：左侧窄 beat 列表、中间大预览（默认活 composition，工程态、不渲染）、底部「分段工作区」；右栏收起。底部分四个 tab：

- **逐句调整**：按口播逐字稿的行调密度；
- **整 beat 反馈**：这个 beat 的整体意见；
- **历史反馈**：读 `feedback/*.jsonl`；
- **动效细节**：原来的分步动效，只在选中“有图”的句子时用。

- **单位是口播逐字稿的行**，不是 beat。beat 只是分组标题与批量入口。
- 每行状态：`auto`（跟模型建议）/ `off`（字幕级，不要图）/ `still`（单图）/ `light`（轻动）/ `full`（完整）。
- 默认全部 `auto`；作者只改例外。改过的行数显示在顶部。
- 左侧 beat 列表显示每个 beat 的调整数；点它切 beat 并定位。
- 播放时当前行高亮；点行定位到那句；`0/1/2/3/a` 设状态。
- 多选：单击、Shift 连选、Cmd/Ctrl 加选、按住拖过多行；批量条一次应用到所有选中句。
- beat 标题可一键“全字幕 / 全完整”；「只看非自动」过滤；「撤销」回退上一次批量。
- 「动效细节」是同一 dock 的第二个 tab，只用于选中“有图”的句子；`off` 的句子没有分步动效。
- 提交写入现有 `review/review-submissions.json` 的 `phase: "density"` 记录，走同一个
  `feedback/` 收件；不新增第二套提交格式。

**`off` 是结构指令，不是动效参数。** 它表示这一句没有视觉层；模型要删/隐藏对应段，而不是把
不透明度调到 0。连续图跨越 5 句、其中第 3 句标 `off` 时，模型负责把图拆成两段或在那一句
做可见的停顿/淡出；不要求作者画时间线。

### 4. 收件与定点返修

```bash
python3 "<craft>/helpers/review_inbox.py" "<project>"
```

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

## 与 page 路线的关系

| 共用 | 不共用 |
|---|---|
| 声音、EDL、字幕、词级锚点 | 静态 SVG 快照作为最终几何 |
| timeline 章节 / step 边界 | `import_svg_page.py` / `generate-composition.py` |
| review-core、审阅页、收件 | `check_parity.py`（single-source 时） |
| 交付核验、指纹、render env | 页面几何契约 |

`page` 仍是默认与 fallback。recompose 失败、作者要求逐像素保留、或项目需要 PPTX 时回 page；
两者可以同一项目里先双跑，比较质量 / 时间 / 返工，再决定默认。

## 不要做什么

- 不要把 recompose 做成用户要选的新路线；它是项目级 build mode。
- 不要为密度再开一个独立页面或独立收件箱；它就在现有动效页里。
- 不要在动效页放 board 参考帧：作者已经在 PPT Hell 确认过，成片页只看成片。
- 不要用 `state` 字段假装已实现：密度改了但 scene 没改，等于没改。
- 不要为了通过检查而把 `off` 实现成 `opacity: 0`；那是动效参数，不是结构。
