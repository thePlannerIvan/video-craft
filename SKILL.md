---
name: video-craft
description: 承接 Video Idea System 的内容包、PPT Hell 的静态 SVG 或已有音视频，完成剪辑、实测时间绑定、动画、语义字幕、视听合成、人工审阅返修与交付核验。
---

# Video Craft

Video Craft 把已经确定的内容做成可播放、可审阅、可返修的真实视频。

- `video-idea-system` 负责内容主张、口播稿、念稿决定和 visual-plan。
- `planners-ppt-hell` 负责静态页面、SVG、静态页面审阅和页面级视觉决定。
- `video-craft` 负责声音、剪辑、实测时间、字幕、动效、合成、两个制作审阅面和交付核验。
- `planners-review-core` 只负责审阅桥、宿主、资产读取、草稿、提交和唤醒；它不理解视频业务。
- `planners-source-index` 负责来源索引；Craft 不从画面或字幕反推新事实。

本 Skill 的审阅面有两个：

1. **逐字剪辑面**：取舍词、删除气口、恢复片段、改字，写入剪辑选择。
2. **动效与合成面**：按稳定 `unitId` 查看一屏一段，调整动效参数、元素位置、文字、框选批注并攒批提交。在 **recompose 构建模式**下，页面变成「左侧大预览 + 视频下方横向 Beat 切换 + 左侧视频下方整 beat 反馈；右侧逐句调整 / 历史反馈」。逐句调整按口播逐字稿的行调 0–3（无画面 / 仅配图 / 轻动效 / 完整动效）。

念稿确认仍回 `video-idea-system`；静态页面的页面级审阅仍回 `planners-ppt-hell`。不要用 Craft 的审阅面替代上游决定。

顺序仍是**先剪点、后画面**：逐字剪辑面定"说什么、留哪句"，确认之后才做动效 / 密度。剪点一动，画面锚点、字幕、composition 全部要重出，反过来做就是白做。

## O / KR / Tools / Playbook

**O（这个 Skill 解决什么问题）**：把**已经确定的内容**做成**能播、能审、能返修**的视频 ——
不是做设计、不是写稿、不是替作者决定说什么。判定"内容已定"的标志是：口播稿/脚本已确认、
画面源（PPT 导出的 SVG 或已批准页面）在手、声音已剪好或已录。任何一条不成立就退回上游
（`video-idea-system` 定内容、`planners-ppt-hell` 定静态页面），Craft 不越权改内容。

**KR（可观察的完成判据，缺一不可）**

| # | 判据 | 怎么观察 |
|---|---|---|
| KR1 | 剪点由 EDL 表达，字幕与画面锚点跟随同一份实测时间 | `duration_plan.py` 有记录；`segment_durations.json` 的 hash/段数对得上 |
| KR2 | 每屏画面都来自**原页拆解**，不是自由发挥 | `pages/<page>.md` 存在且 `film.py verify` 退 0 |
| KR3 | **工程态审阅页是阶段交付物**：能播、时长对、有画面、有声音、默认演 composition | `review.py` 退 0，报告写明 `channel=live`、时间轴时长与声音来源；`check_review_playable` 绿 |
| KR4 | 人审确认后才出片；**审阅阶段禁止渲染** | 默认终点是 KR3。渲染必须作者显式"出片"指令 → `render_gate.py` 退 0 → `deliver.py --render`；缺画面层时 deliver 直接拒绝 |
| KR5 | 成片逐项核验通过 | `<成品>/<片名>_核验报告.json` 的 `ok=true`（分辨率/帧率/时长/音轨/首中尾帧/字幕安全区） |
| KR6 | 本轮沉淀有回执：候选被处置、规范通过校验 | 第 11 步的处置记录写明收了哪条、放在哪、替代了谁（或明确没收）；`helpers/spec_lint.py` 退 0 |

**Tools（三条命令；每条只回答"解决什么 / 何时调 / 失败信号"）**

| 命令 | 解决什么 | 何时调 | 失败信号 |
|---|---|---|---|
| `helpers/film.py` | 把原页读透并落到 composition | 画面开工第一步，拆解没填完不许往下 | `verify` 退 1，逐条列出"哪个 beat 没映射 / 哪一列没填" |
| `helpers/review.py` | 把工程变成能给人看的页面 | 画面改动后、交人审前 | 退 1 并指出该修 composition 还是审阅装配；端口端出别人的工程会硬失败 |
| `helpers/deliver.py` | 画面层 + 人物 + 声音 + 字幕 → 成片 + 报告 | 人审通过之后 | 退 1，报告里红项指出回修哪一层 |

**Playbook（工作路线）**：接手核对版本 → 剪辑与字幕（EDL 为唯一时间来源）→ 画面（`film.py`
拆解 → composition → `review.py` 人审）→ 交付（`deliver.py` → 核验报告）。每一步的顺序不能反：
剪点一动，画面锚点、字幕、composition 全部重出。

## 只有一条路线

命令表见上面 Tools。剪辑、字幕、时间脊柱是它们的**事实层**，按全链流程做（第 3–6 步）。

**老路线已存档，不再维护**：page 十步路线（`import_svg_page` → `generate-composition` → `check_parity`）
整体归档在 [legacy-page-route.md](references/legacy-page-route.md)，代码在 `helpers/_legacy_page/` 与
`visual/scripts/_legacy_page/`，原路径保留兼容 shim。新项目一律走 recompose + `film.py`；
只有复活旧项目时才读那份存档。

## 工程预览与最终交付

默认先做可修改的工程。**剪辑选择由 EDL 表达，动画由 composition 表达；两者都不靠反复渲染 MP4 才能审阅。**

| 工作 | 时间与画面的主人 | 什么时候渲染 |
|---|---|---|
| 纯口播删词、气口、改字 | 逐字剪辑面按 EDL 映射源媒体 | 剪点确认后的正式底片 |
| SVG 动画、录屏、口播配画面 | HyperFrames 官方播放器播放 composition；播放、定位、倍速、媒体同步和 clip 显隐都交给它 | 画面确认后的最终输出 |
| 已有合成片返修 / 外部透明层 | 保留已有媒体审阅与叠层工具 | 必要的外部素材转换或最终合成 |

`live_stage.py` 启动 HyperFrames 编译服务；`build_review.py` 将编译后的工程、官方播放器和素材清单装进审阅快照。新工程只让 HyperFrames 拥有播放与动效时钟；旧 `VideoCraftAnimEngine` 仅作为旧 SVG 审阅兼容路径保留。浏览器通过 review-core 取素材，在官方播放器内部播放，**不从 DSH 的不透明 iframe 访问本机 HTTP 舞台**。改源后重新 build、刷新即可看，不渲视频。没有 HyperFrames 审阅适配器时，动画参数通过反馈交给模型修改源工程；有适配器时也只能修改 composition 明确声明的参数。快照中记录播放器版本与工程哈希；不能把旧快照说成热更新。

声音清理、VFR 转 CFR 或浏览器不支持的媒体转码属于素材准备，可以做并缓存；它们不应变成每次修改动画都重跑的前置。工程预览不冒充最终音画验收。实测时长、字幕锁、来源指纹与正式交付核验继续保留。

### recompose 主路线入口

```bash
python3 "<craft>/helpers/recompose_plan.py" init "<project>" \
    --composition "<project>/composition" --draft "<project>/recompose/draft.mp4" \
    --person-slot "0,0,620,1080" --caption-safe "0,885,1920,195"
python3 "<craft>/helpers/review.py" "<project>"      # 一条命令出审阅页
```

`check` / `lines` 的完整参数与产物见 [tools.md](references/tools.md)「recompose 主路线」。

densities 的提交仍走同一个审阅面，由 `review_inbox.py` 收件：`feedback/density.jsonl` + 回写 `recompose/lines.json`。
完整说明见 [recompose-mode.md](references/recompose-mode.md)。产物是 `recompose.json`、`recompose/lines.json`，不生成页面快照。

### 验收判据

- 改剪点后源媒体预览采用新 EDL；改动效后重建审阅采用新 composition，无需先渲整片。
- DSH 沙箱和公共本地宿主均能显示、定位、连续播放、调速；声音、录屏与字幕对应同一播放头。
- 分屏、动画时间、批注、草稿、正式提交和收件都能追溯到当前快照。黑屏提示、握手成功、静态截图均不等于播放验收。
- 交付仍核验真实文件；未完成的宿主实测明确列出，不能用单元测试数量替代。

## 入口判断

| 输入 | 入口 | 不要跳过 |
|---|---|---|
| 内容包，没有录音 | 接手并写制作方案；可做 `planned` 预演 | 不把估时当成实测时间，不生成假字幕 |
| 原始视频或录音，需要取舍 | 转写 → EDL → 源媒体逐字预览 → 确认后输出 | 不直接手改成片后再猜字幕时间 |
| 已剪音频 + SRT + 参考页 | 核版本 → 对齐时间（`srt-import`）→ `film.py` 拆原页 → 重做动画与合成 | SRT 只能标为 `srt-import`，不能冒充 EDL 实测；不导入 SVG 页 |
| 已有项目或返修反馈 | 读项目依据和收件回执 → 只重建受影响部分 | 不在旧审阅页上继续写新反馈 |
| 已锁音频 + 词级锚点，画面是连续动画 / 图解 | **recompose 一条路线**：`recompose_plan.py` 建密度 → `film.py` 拆原页 → composition → 逐字密度 | 不跳原页拆解（KR2）；老 page 路线只读存档，新项目不走 |

项目目录、剪辑目录和上游目录必须使用绝对路径。先确认当前采用版本，再执行下面的流程。

## 全链流程

流程是**事实的产出顺序**，不是路线：每步说明"这一步要产出什么事实"，判据由上表 KR 与各步的完成标准定义。
老「能力包」体系只作历史读（[capability-packs.md](references/capability-packs.md)，已存档），不再按它选路线。

| 阶段 | 步骤 | 产出的事实 |
|---|---|---|
| 接入 | 1–2 | 来源与制作方案：可用能力、作者约束（保真/自由度、画幅、字幕内外、交付件） |
| 剪辑 | 3–6 | EDL、字幕、唯一时间脊柱（实测优先，预演只作工程态） |
| 画面 | 7–8 | 视觉层与审阅确认（按能力包的 DoD） |
| 交付 | 9–10 | 收件返修、核验与交付（指纹、外挂 SRT、交付说明）；**只有作者显式"出片"才进入** |

每一步都必须把产物交给表中的下一消费者。完成标准是硬事实，不是“页面打开了”。

### 1. 接手与版本核对

**何时进入**：所有新项目、恢复项目、收到返修反馈时。

**先读**：`references/content-to-production.md`、`references/author-spec.md`（判准，全篇）、`references/preferences.md`（准入与归位规则）、项目 `_idea/current.md`、已有 `edit/project.md`、`production-plan.md` 和 `feedback/`；画面以 PPT Hell 的视频快照为参考页（recompose 不导入页，见 [recompose-mode.md](references/recompose-mode.md)）。

**调用**：

```bash
python3 "<craft>/helpers/check_script_hash.py" "<project>" --script "<script.md>" --plan "<visual-plan.json>"
```

上游交接检查（`check-handoff-artifacts.mjs`）见 [tools.md](references/tools.md)「接上游」。

recompose 路线**不导入页**：PPT Hell 的快照只作视觉参考，用 `film.py` 抽原页拆解（见第 7 步）。
`import_svg_page.py` 属于已归档的 page 路线，只在复活旧项目时读 [legacy-page-route.md](references/legacy-page-route.md)。

**输入**：上游交接包、作者决定、脚本、visual-plan、snapshot、SVG、素材。

**输出**：`edit/project.md` 记录本轮采用版、输入路径、缺口、责任边界；必要时生成 `composition/pages/manifest.json` 和项目内 SVG / 图片副本。

**下一消费者**：制作方案、转写 / EDL、视觉时间绑定。

**完成标准**：知道当前使用哪一版脚本、哪一版画面、哪条声音、哪些决定不可自行改变；hash 不一致、snapshot 不完整或资产越界时停止并回上游，不静默继续。

### 2. 确定制作方案

在 `production-plan.md` 写清楚**风格**（`line-art` 线稿 / `business-report` 商业报告 / `collage` 拼贴，见 [style-spec.md](references/style-spec.md)）、成片形态（口播 / 动画 / 合成）、声音来源、画幅、画面过程、强调动作、素材、时间依据、字幕形态、交付件和返修范围。路线固定为 recompose，不用选；第 7 步按风格那一节做。

需要改内容意义、必见对象、固定文字或素材关系时回 `$video-idea-system`；需要重做静态画面时回 `$planners-ppt-hell`；需要复用方法时调用 `$planners-method-wiki`，但 Wiki 只提供方法，不提供本项目事实。

**完成标准**：每个交付轨都明确，且知道后续是“以 EDL 实测时间为准”还是“以外部 SRT 为准”。

### 3. 声音与剪辑

原始媒体走：

```bash
python3 "<craft>/helpers/transcribe.py" "<source-video>" --edit-dir "<edit>" --audio-track 0 --backend auto
```

打包与停顿预算（`pack_transcripts.py` / `check_edl.py`）见 [tools.md](references/tools.md)「声音与剪辑」。

用 `edl.json` 表达取舍，不手改底片来表达取舍。逐字面写入的选择由 `selections.json` 表达，之后调用：

```bash
python3 "<craft>/helpers/apply_selection.py" "<edit>"
```

有声质量问题先诊断再处理：

音质诊断与处理（`audio_diag.py` / `audio_fix.py`）见 [tools.md](references/tools.md)「声音与剪辑」。

**输出**：`transcripts/`、`takes_packed.md`、`edl.json`、必要时 `selections.json`。

**下一消费者**：逐字剪辑审阅面；字幕与工程态时间脊柱可先行。正式底片渲染排在剪点确认之后（第 5 步），不排在审阅之前。

**完成标准**：EDL 可检查；源文件、区间、速度、段落累计时间明确；`transcripts/<source>.json` 是词/字级（正常 token < 1s，粗粒度转写先跑 `refine_transcript.py`）；没有把预览渲染当成正式底片。

### 4. 逐字剪辑审阅

**何时进入**：EDL 已可检查，但剪点、错字或气口仍需要人确认。

**构建并挂载**：

```bash
python3 "<craft>/helpers/edl_preview_build.py" "<edit>"
```

面上缝（`edl_review_surface.py --surface-only`）见 [tools.md](references/tools.md)「审阅」。

DSH 有 `review_open` 时，把返回的 **surface 绝对路径**交给 `review_open`；没有插件时去掉 `--surface-only`，使用公共 review-core 本地宿主。不要自己另起一份 Craft 专用宿主。

**人可以做的事**：播放、上一刀 / 下一刀、拖时间轨、点词定位、拖选删除词、选择或恢复气口、改字、提交剪辑选择、另写整片意见。

**工具与反馈边界**：播放器、时间轨、选词、改字、停顿数值属于页面工具；整片备注和“请 Agent 应用剪点”属于反馈。页面写 `selections.json`，Agent 收件后才运行 `apply_selection.py`。

**完成标准**：提交文件真实写入；没有桥时页面明确显示未连接；Agent 先读取提交再应用选择；应用后重建逐字预览；需要视觉制作时更新工程时间轴和字幕，最终输出时再做实测核验。

### 5. 工程时间与字幕；确认后输出底片

**渲染不是「能开始干活」的前提。** 想让作者先看到东西，先出工程态：

```bash
python3 "<craft>/helpers/duration_plan.py" "<edit>"     # 解析预演（帧量化，projected）
# 已有外部透明视频层才需要 preview_layers.py；HyperFrames 动画直接预览工程。
```

`projected` 记录可以支撑第 6 步的时间脊柱、字幕和审阅页，但**不是交付证据**——
`_edl.render_record` 默认跳过它，`verify_delivery.py` 永远拿真实文件对真实渲染。
交付前仍必须走下面这条渲染路径并重建字幕。

剪点确认后，用会记录实测段时长的渲染路径先出工程态底片（`--preview`）；这既不是开始制作画面的前置，也不是交付底片：

```bash
python3 "<craft>/helpers/render.py" "<edit>/edl.json" -o "<edit>/_engineering/cut.mp4" --preview --no-subtitles
```

`--preview` 产物属于工程态，一律落 `edit/_engineering/`；`edit/cut.mp4` 这个正式底片名只留给确认后的交付态渲染。

字幕采用“全文校对 → 语义断句 → 锁定 → 生成”的顺序：

```text
先改 caption_corrections.json
→ --prepare --force-prepare（只有确认 EDL / 转写改变时）
→ 把人工校对后的 captions_article.txt 放回
→ 写 semantic_lines.txt
→ --lock
→ --build
→ --check
```

具体入口均在 `helpers/srt_export.py --help`。`segment_durations.json` 必须与当前 EDL hash 和段数匹配；旧记录不匹配时工具会继续找其他历史记录，找不到才拒绝严格构建。

**输出**：`segment_durations.json`、`captions_article.txt`、`semantic_lines.txt`、`caption_lock.json`、`caption_words.json`、`captions.json`、`subtitles.srt`。

**下一消费者**：唯一时间脊柱、静态视觉对齐、合成与字幕交付。

### 6. 建立唯一时间脊柱

`timeline/timeline.json` 是页面、动效、字幕和审阅绑定共同消费的时间脊柱。

已有实测字幕时用 `timeline_derive.py`；只有外部剪好音频和 SRT 时：

```bash
python3 "<craft>/visual/scripts/align-visual-plan.py" --plan "<visual-plan.json>" --script "<script.md>" --srt "<audio.srt>" --output "<project>/timeline/alignment.json"
```

外部 SRT 的时间脊柱（`import_srt_timeline.py`）见 [tools.md](references/tools.md)「SVG 与视觉时间」。

对齐工具写绝对来源路径；`srt-import` 只证明“这份 SRT 与这份内容契约完成了对齐”，不证明 EDL 实测。

**绑定规则**：

- 页面使用 `unitId`，不使用会随排序变化的临时序号。
- 视觉页优先为 `visual:<sourcePageKey>`；口播段为 `speech:<step-id>`；overlay 为 `visual:<tag>`。
- `review/review_data.json.binding` 是当前审阅快照的绑定证明。
- 反馈至少带 `unitId`、`chapterId`、`stepId`、`snapshot`、`text`；收件器会拒绝不存在或 chapter 不匹配的 `unitId`。
- 改变时间轴、EDL、SVG 或字幕后必须重新 build review；不能拿旧页面继续提交。

### 7. 动效与合成

动手前必须已有 `pages/<page>.md` 原页拆解（见 [film.md](references/film.md)，KR2），元素清单按阅读顺序登记；
把原页当**信息源**，按拆解逐条演出来 —— 不重画模型图，不把截图当 SVG。原页元素若已有
`data-step` / `data-anim` / `id`，沿用它们；只有元素级动效才需要稳定 id。

- HyperFrames：读 `$hyperframes`。整片 composition 由 `film.py` 的拆解驱动、手写 `src/scenes/*.js`（不再用已存档的 `generate-composition.py`）；单层动效也先在 composition 中预览。只有最终合成需要独立透明视频，才用 `helpers/render_layer.py` 输出 `.mov`；兼容旧媒体叠层面时可同时输出 `.webm`。预览与渲染前先 `hyperframes check`。**任何 `hyperframes render` 之前先跑 `python3 "<craft>/helpers/probe_env.py" "<project>"` 报告能力（libass/字体预算/残留进程；只报告不阻断），再跑 `python3 "<craft>/helpers/check_render_env.py" "<project>/composition"`** —— 它报 RAM、可用内存与建议的 `--workers` 值（默认从 1 起）；并先过 `references/timing-lock.md`：`film.py verify` 退 0，且 `feedback/*.jsonl` 的未决项已清或显式接受。缺一不渲。
  **动效的源是 composition，不是那段视频**：层要能改、能预览，才谈得上「先审后渲」。
- Manim：只有严密数学或技术动画才调用 `$manim-video`。
- 自定义逐帧：读 `references/frame-animation-pipeline.md`。
- 合成：读 `references/composition-craft.md` 与 `references/visual-rendering.md`。

所有 overlay 在写入 EDL 前检查：画布尺寸、alpha、起止时间、父级 `unitId` 和输出路径。尺寸不匹配必须报错，不能静默跳过。

**输出**：`composition/`、透明或整屏视觉层、工程态合成预览（活 composition，不渲帧）。最终合成视频属于**交付态**，只在第 10 步经两个审阅面确认后产出一次。

**下一消费者**：动效与合成审阅面、交付核验。

### 8. 动效与合成审阅

先读 `references/review-ui.md` 与 `references/hyperframes-review-adapter.md`。**`build_review` 之前先跑活舞台契约检查**：

```bash
python3 "<craft>/helpers/check_live_stage.py" "<project>"   # 退 0 才继续
```

它静态断言这份 composition 能进审阅页的活舞台（`data-composition-id` 与时间轴注册名一致、
会执行逻辑的脚本全在外部文件、嵌入桥在、媒体在预算内）。`hyperframes check` 全绿**不能**替代它：
那条路径不经过审阅页的 `srcdoc`，内联脚本被编译器改写成 `type="text/hf-after-fonts"` 后
在 srcdoc 里永远不执行，播放器拿到 0 秒、舞台全黑。契约与根因见
[live-stage-contract.md](references/live-stage-contract.md)。

通常调用：

```bash
python3 "<craft>/helpers/review.py" "<project>"      # 一条命令出审阅页（含活舞台、构建、运行时判据）
```

**建完之后必须跑运行时检查，它才是"这页能给人看"的判据**：

```bash
python3 "<craft>/helpers/check_review_playable.py" "<project>"   # 退 0 才能交给作者
```

它自己起宿主、用 Playwright 打开页面，断言：挂上哪条播放通道、**活舞台的时间轴真的构建了**
（直接读 iframe 里的 `window.__timelines.main.duration()`，不信根元素的 `data-duration`）、
能 seek 出画面、有声音且未被静音。任一条红就退 1 并指出该修哪一层——不要把一个
"能提交反馈、但看不到也听不到"的页面交给作者（2026-10-21 就是在这里烧掉了一整轮）。

DSH 有 `review_open` 时传返回的 surface 绝对路径；没有时去掉 `--surface-only`，由 review-core 启动本地宿主。两种宿主使用同一份审阅页。

官方播放器承担播放、暂停、拖动、倍速、单屏播放和屏末定位。字幕与反馈位置读取它的播放头；不要同时启动旧 SVG 定时器或隐藏视频。逐动画反馈以分屏、播放时间及对应分句锚点记录；框选批注先暂停。点选调整切换到静态源稿编辑，调整作为请求随反馈提交，返回预览后看当前真实工程，不能把未应用的草稿说成已生效。

`review/media.json` 显式声明已有成片、底片或透明视频层；这些兼容入口继续保留。工程含图片、声音或录屏时必须来自项目内资产；`live_preview.py` 拒绝外部资源和越界路径。桥传素材字节，播放器层使用可跨不透明源的媒体载体；不要把父帧的 `blob:null` URL 直接给子帧。**活舞台的资产预算由 `build_review.py` 自动做**：`liveStage.composition.assets` 里超过 `LIVE_STAGE_ASSET_MB`（4MB）的会被换成 `review/proxies/` 下的审阅副本：时长不变，**先保原生像素只降码率，仍压不进才按 0.75/0.5/0.35 降分辨率**，降了会在 `mediaNotes` 里写明「原生 W×H → w×h」；同时把 `composition.assetBytes` 与 `liveStage.budgetMs` 写进快照 —— 页面按后者而不是写死的 8 秒算等待预算。`media.sizes` 逐通道标出 MB 与 `oversized`，页面对超大通道（例如 1.19GB 的口播母版）**拒绝下载**并说明原因，而不是把整份搬进侧栏。所以 agent 不需要手搓代理；看到「预览暂时无法连接」先查 `mediaNotes` 里有没有超预算记录，而不是先去查服务。

`review.draft()` 保存草稿；`review.write()` 正式落提交文件；有待处理意见时再 `review.wake()`。真实回执成功后才报告已写入，通知结果与保存结果分别显示。页面不保存时不唤醒模型。改 composition、剪点、字幕或画面后重新 build review。

Studio 是可选的完整编辑入口，`studio_notes.py` 与 studio hook 保留其意见收集能力；DSH 内的结构化反馈直接走 review-core，不依赖剪贴板。

### 9. 收件、返修与重建

先收件，再读反馈，再改源：

```bash
python3 "<craft>/helpers/review_inbox.py" "<project>"
```

检查收据中的 `imported`、`skipped`、`rejected`。有 rejected 时先修复记录或重建快照，不能假装收件完成。

- 逐字反馈：读 `selections.json`，运行 `apply_selection.py`，重建逐字预览、工程字幕与时间轴；正式底片留到确认后输出。
- 动效 / 合成反馈：读 `feedback/<chapterId>.jsonl` 和记录中的 `adjustments`，修改 composition / SVG 源，重新 build review 并刷新；确认后再 render。
- 元素微调若要写回源 SVG，必须核对 source snapshot / version；源已改变时拒绝覆盖，交 Agent 决定如何合并。
- 改变任何时间、页面或媒体绑定后，重新运行 `build_review.py`，让旧 snapshot 失效。

### 10. 核验与交付

**默认停在第 9 步。** 审阅的交付物是**工程态审阅页**（KR3），不是成片。只有当作者明确说"出片/交付"时才进入本节；在此之前任何 `hyperframes render` 或 `deliver`（不带 `--render`）都不该发生。

作者确认后，出片是一条命令（**显式** `--render`，别手写 ffmpeg）：

```bash
python3 "<craft>/helpers/deliver.py" "<project>" --render        # 渲染画面层 + 人物贴回 + 声音 + 核验报告
python3 "<craft>/helpers/deliver.py" "<project>" --visuals "<已有画面层.mp4>"   # 画面层已存在，跳过渲染
```

它按 `recompose.json` 的 `personSlot` / `captionSafe` 贴回人物、接声音、核验分辨率/帧率/时长/音轨/
首中尾帧/字幕安全区，并写 `<成品>/<片名>_核验报告.json`；第一件事是跑 `render_gate.py`
（没人审覆盖当前快照就拒绝出片）。**没有人物轨的片子加 `--no-person`**（纯画面 + 旁白是合法形态，
不是缺素材）。缺画面层或画面层比 composition 旧时 **deliver 默认拒绝**，不会自动渲染——那会把审阅变成导出；
重渲必须显式 `--render`。
契约见 [delivery.md](references/delivery.md)。

**渲染前的第一步是渲染闸门，不是 render。** 它要求 `review/review-submissions.json`（或
`feedback/*.jsonl`）里至少一条人工提交覆盖**当前**审阅快照，且源在那次构建之后没有再改过：

```bash
python3 "<craft>/helpers/render_gate.py" "<project>" --out "<实际成片路径>"   # 退 0 才允许 render
```

退 1 = 这一版没人看过或源已漂移，先 `build_review` + `review_open`；退 2 = 还没有审阅数据。
工程态预览（`--preview`、落 `edit/_engineering/`）用 `--engineering --out <edit/_engineering/...>`，
它不能改个文件名当成交付成片。口头规则拦不住渲染，这条闸门才是判据。

```bash
python3 "<craft>/helpers/check_motion_targets.py" "<project>"
```

其余交付核验（`verify_delivery.py` / `export_deliverables.py` / `state_fingerprint.py`）与 `check_parity.py`（仅老 page 项目）见 [tools.md](references/tools.md)「渲染、核验、包装」。

交付前一律跑 `check_motion_targets.py`：recompose 项目没有 `timeline/choreography.json`——它的唯一生产者 `auto_choreography.py` 已随 page 路线归档。这条检查断言时间轴里的每个 selector 都命中、且页面自带的静态 `transform` 没有被 x/y/scale/rotation 补间覆盖（GSAP 会把 attribute 重写掉，位移静默丢失）。

只有复活老 page 项目、且项目里真有 `choreography.json` 时才跑 `check_parity.py`（断言 spec 里的每个效果 kind 在 composition 与审阅页两条路径都有实现）。两类失配都**不会让 `hyperframes check` 失败、也不会让页面报错**，只会让某一步静默不演 —— 交付前必须过。

**指纹不是渲染前置，是交付过期信号**：已有交付先跑 `state_fingerprint.py verify` 判断是否过期；改源后过期正是**需要重新输出**的信号，不拦住新渲染，只拦住**发送**。 重新输出并核验后 `capture` 新指纹，发送前再 `verify`，不一致就不能发送。工程态的渲染与预览一律落 `edit/_engineering/`，**不进 `edit/` 根**，免得被当成当前底片（GOTCHAS #56）。

核验实际成片，不核验预览假象：声音、首 / 中 / 尾画面、字幕、关键动效、alpha、画幅、帧率、时长和交付文件名。交付中明确：有声 / 无声、透明 / 不透明、字幕烧录 / 外挂，以及仍未完成的事项。

### 11. 收尾与沉淀

交付核验通过后做这一轮。**默认不打扰作者**：没有重复出现的要求，就只报一句「本轮无新判准」。

**读三处证据**：本片 `feedback/*.jsonl` 的返修理由、项目 `edit/preferences.md` 的处理表、核验报告里的红项。重复出现的要求最强的是返修理由——作者已经在同一件事上纠正过一次。

**只挑重复的**：同一要求在 ≥2 个独立项目、或两次独立返修里出现，才算候选；一次性的留在项目里，不进 Skill。

**给 ≤3 条候选**：每条一句话 + 出处（项目 + 屏号）+ 建议动作（收进 `author-spec.md` / 收进某种风格的 `style-spec.md` / 升进正式文档 / 丢弃）。按 [preferences.md](references/preferences.md) 的两套准入与归位规则处理：否定型硬约束一次即可进正式文档；倾向型判准要复现。有原话证据的自动收，模型推断的要问作者。

**写完校验**：

```bash
python3 "<craft>/helpers/spec_lint.py"          # 条数、篇幅、字段、执行点、类型枚举；退 0 才算收尾完成
```

**完成标准**：候选处理结果可追溯（收了哪条、放在哪、替代了谁，或明确没收）；`spec_lint.py` 退 0；没有留下悬空执行点。

## 故障表

| 现象 | 处理 |
|---|---|
| segment duration 累积或 hash 不匹配 | 不手改字幕；先 `duration_plan.py "<edit>"` 拿 projected 记录继续做字幕与时间脊柱；只有交付核验（`verify_delivery.py`）必须真渲染 |
| `--prepare` 会覆盖人工正文 | 先确认版本；只有确认 EDL / 转写已变时用 `--force-prepare`，之后重新放回人工正文 |
| overlay 尺寸与画布不符 | 修正源尺寸或显式适配；禁止静默跳过 |
| 审阅页媒体读不到 | 检查 `review.asset` 的相对 `dir` 路径和项目内资产副本，不改成猜相对路径 |
| surface 加载但 bridge 不可用 | 用 DSH `review_open` 或公共 review-core 宿主；不显示假成功 |
| 草稿显示已保存但提交文件没变 | 这是 `draft()`，不是 `write()`；点击正式提交并检查回执 |
| `unitId` 被收件器拒绝 | 重新 build review；检查当前 `review_data.json.binding` 与反馈的 chapter / snapshot |
| SRT 对齐路径不稳定 | 从任意工作目录调用时使用绝对 `--plan`、`--script`、`--srt`、`--output` |
| 审阅页舞台 0:00 / 全黑，右侧人物正常 | 先跑 `check_live_stage.py`；查内联逻辑脚本与注册名，见 [live-stage-contract.md](references/live-stage-contract.md) |
| `render_gate.py` 拒绝渲染 | 这一版没有覆盖当前快照的人工提交，或源已漂移；先 `build_review` + `review_open`，不要绕过 |
| 音频需要 EQ 但工具没有该能力 | 先用 `audio_diag.py` 诊断；没有明确处理器就报告能力边界，不伪造完成 |
| 导出结果纯色、无声或无字幕 | 回到正式 render；`export_video.py` 只包装已有结果，不替代渲染 |

## 文件与参考入口

- 制作路线（唯一一条）：`references/recompose-mode.md`
- **九个制作阶段的契约与脚本合并地图**：`references/stages.md`（每段做什么/何时用/输入/产出/坏了怎么认）
- **开工必读（作者判准与本片偏好）**：`references/author-spec.md`（全局判准，全篇）、`references/preferences.md`（准入与归位规则）、`references/creative-direction.md`（接住意图）、`references/visual-direction.md`（画面与动画的对齐顺序）
- **第 2 步定完风格再读**：`references/style-spec.md`（`line-art` 线稿 / `business-report` 商业报告 / `collage` 拼贴）
- 画面入口：`references/film.md`；交付入口：`references/delivery.md`
- 历史（存档，不要照做）：`references/capability-packs.md`、`references/legacy-page-route.md`
- 可执行命令与产物目录：`references/tools.md`
- 上游交接与责任边界：`references/content-to-production.md`；素材身份区分：`references/media-first.md`
- 视觉时间绑定：`references/visual-timeline.md`
- **卡点对齐（词在第几秒）：`helpers/align.py`** —— 优先真实词级时间戳（`edit/transcripts/*.json`），命中不到才退回比例估算并标注 `estimated`。**卡点不要手算比例**：`edit/caption_words.json` 的字时间是段内插值，是假的
- 字幕契约：`references/caption-article-first.md`；字幕三模式与断句原则：`references/caption-modes.md`（第 5 步前读）
- SVG 动效契约：`references/svg-animation-contract.md`
- 合成与渲染：`references/composition-craft.md`、`references/visual-rendering.md`；三个合成事实的字段契约：`references/composition-facts-contract.md`
- **渲染前闸门**：`references/timing-lock.md` —— `film.py verify` 退 0 且 `feedback/*.jsonl` 未决项已清或显式接受，才谈得上渲染；`helpers/check_render_env.py` 是环境判据
- **审阅页硬约定（改审阅页前必读）**：`references/review-ui.md`、`references/hyperframes-review-adapter.md`；桥、宿主与收件：`$planners-review-core`
- **活舞台契约（build_review 前必过）**：`references/live-stage-contract.md` —— 根 `data-composition-id` + 同名 `window.__timelines[...]`、逻辑脚本全在 `src/*.js`、`assets/composition-embed-bridge.js`、媒体预算；自检 `helpers/check_live_stage.py`
- **渲染闸门（render 前第一步）**：`helpers/render_gate.py` —— 人工提交必须覆盖当前审阅快照；工程态 `--engineering` 只能落 `edit/_engineering/`
- 维护与已知陷阱：`GOTCHAS.md`、`references/architecture.md`

## 升级守则（每次改本 Skill 必读）

判据只有一句：**改完以后所有的"绿"，都必须是这一次亲手跑出来的绿，不是上一次的绿。**

改动前先跑一遍基线并记下结果；改动后逐条重跑，任何一条不如基线就不许发布。

1. `PYTHONPATH=helpers python3 -m unittest discover -s tests -p 'test_*.py' | tail -3`
   → 末行必须是 `OK`，并记下 `Ran N tests`。**N 只许增不许减**，除非是合并用例并写明理由。
2. `python3 helpers/check_review_template.py`（0 项不通过）与 `--prove`（全响）。
3. `python3 <planning-before-create-skill>/scripts/lint_skill.py .` → 无确定错误。
4. **接真实项目跑一遍三条命令**：`review.py <project>`（退 0，且运行时判据「能播 / 有画面 / 有声音」全绿）、
   `deliver.py <project> --render`（成片真有音轨、核验报告 `ok=true`）。**单测绿 ≠ 真实项目绿，这条不可省。**
5. 发布前确认工作区干净、本地与 GitHub 一致；发布后再用同一现场重跑第 4 条。

不许做：把上一次的绿灯当成本次状态；把没跑过的写成"已验证"；红了先发布再修。

## 自检

从 Skill 根运行：

```bash
PYTHONPATH=helpers python3 -m unittest discover -s tests -p 'test_*.py'   # 必须 0 error
python3 helpers/check_review_template.py                                  # 审阅页九条静态不变量
python3 helpers/check_review_template.py --prove                          # 证明那九条不是空洞判据
# 静态质检用 planning-before-create-skill 的 scripts/lint_skill.py（全库唯一一份），要 0 error
python3 -m json.tool evals/evals.json >/dev/null && echo "evals 合法"     # 本 Skill 的语义验收用例（见 evals/）
node "<review-core>/evals/run.mjs"
python3 -m unittest discover -s "<review-core>/evals" -p 'test_*.py'
```

第一条必须**全绿**，不是"大部分通过"。这个仓库的自检曾经常年带着两个 ERROR 在跑 —— `test_interactive_ui.py` 连 import 都失败（模块被删掉了）、`test_snapshot_input.py` 找不到隔壁 Skill 的模块而被静默跳过 —— 于是没人看结果，同一个审阅页文件连着返工三轮（GOTCHA #57）。有 skip 是允许的（缺 ffmpeg / node / playwright 时相关用例会自己跳过），但 skip 必须写在案上，不能当成通过。

`check_review_template.py` 是**静态**的：它钉住九类机械缺陷不会静默回来，**不证明页面能跑** —— 新的类仍然要人撞到。别把绿灯读成"审阅页已验证"。浏览器用例现在**默认跑**（要跳过就设 `VIDEO_CRAFT_BROWSER_TESTS=0`）——它们曾经是 opt-in，于是长期被跳过、断言悄悄腐烂（作者丢过一次画布改字就撞在那条没人执行的路径上）。舞台的**握手**另有 `tests/test_composition_embed_bridge.py`的协议测试兜底。

真实项目至少走一遍：`build_review → surface-only → 页面加载 → 提交带 unitId 的反馈 → review_inbox → 修改源 → 重新 build review`。只有这条链通过，才报告审阅接缝可用。审阅时画面走**工程态**（活 composition，见「两个态」）：先 `live_stage.py` 起服务，再 `build_review.py`。

浏览器验收入口与覆盖边界见 `references/review-ui.md`；新增传输回归在 `tests/test_live_preview.py`。
