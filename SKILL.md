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
2. **动效与合成面**：按稳定 `unitId` 查看一屏一段，调整动效参数、元素位置、文字、框选批注并攒批提交。

念稿确认仍回 `video-idea-system`；静态画面审阅仍回 `planners-ppt-hell`。不要用 Craft 的两个面替代上游决定。

两个面的顺序是**先剪点、后画面**：逐字剪辑面定"说什么、留哪句"，确认之后才做动效与合成面。剪点一动，画面锚点、字幕、composition 全部要重出，反过来做就是白做。

## 工程预览与最终交付

默认先做可修改的工程。**剪辑选择由 EDL 表达，动画由 composition 表达；两者都不靠反复渲染 MP4 才能审阅。**

| 工作 | 时间与画面的主人 | 什么时候渲染 |
|---|---|---|
| 纯口播删词、气口、改字 | 逐字剪辑面按 EDL 映射源媒体 | 剪点确认后的正式底片 |
| SVG 动画、录屏、口播配画面 | HyperFrames 官方播放器播放 composition；播放、定位、倍速、媒体同步和 clip 显隐都交给它 | 画面确认后的最终输出 |
| 已有合成片返修 / 外部透明层 | 保留已有媒体审阅与叠层工具 | 必要的外部素材转换或最终合成 |

`live_stage.py` 启动 HyperFrames 编译服务；`build_review.py` 将编译后的工程、官方播放器和素材清单装进审阅快照。新工程只让 HyperFrames 拥有播放与动效时钟；旧 `VideoCraftAnimEngine` 仅作为旧 SVG 审阅兼容路径保留。浏览器通过 review-core 取素材，在官方播放器内部播放，**不从 DSH 的不透明 iframe 访问本机 HTTP 舞台**。改源后重新 build、刷新即可看，不渲视频。没有 HyperFrames 审阅适配器时，动画参数通过反馈交给模型修改源工程；有适配器时也只能修改 composition 明确声明的参数。快照中记录播放器版本与工程哈希；不能把旧快照说成热更新。

声音清理、VFR 转 CFR 或浏览器不支持的媒体转码属于素材准备，可以做并缓存；它们不应变成每次修改动画都重跑的前置。工程预览不冒充最终音画验收。实测时长、字幕锁、来源指纹与正式交付核验继续保留。

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
| 已剪音频 + SRT + SVG | 核版本 → 导入 SVG → 对齐时间 → 动效与合成 | SRT 只能标为 `srt-import`，不能冒充 EDL 实测 |
| 已有项目或返修反馈 | 读项目依据和收件回执 → 只重建受影响部分 | 不在旧审阅页上继续写新反馈 |

项目目录、剪辑目录和上游目录必须使用绝对路径。先确认当前采用版本，再执行下面的流程。

## 全链流程

每一步都必须把产物交给表中的下一消费者。完成标准是硬事实，不是“页面打开了”。

### 1. 接手与版本核对

**何时进入**：所有新项目、恢复项目、收到返修反馈时。

**先读**：`references/content-to-production.md`、项目 `_idea/current.md`、PPT Hell 的 `.snapshot`、已有 `edit/project.md`、`production-plan.md` 和 `feedback/`。

**调用**：

```bash
node "<idea>/scripts/check-handoff-artifacts.mjs" --project "<idea-project>"
python3 "<craft>/helpers/check_script_hash.py" "<project>" --script "<script.md>" --plan "<visual-plan.json>"
python3 "<craft>/visual/scripts/snapshot_input.py" "<project>" --audit
```

拿到 PPT Hell snapshot 后导入项目内资产：

```bash
python3 "<craft>/visual/scripts/import_svg_page.py" "<project>" --pages "<snapshot.json绝对路径>" --audit --prove --emit --json
```

**输入**：上游交接包、作者决定、脚本、visual-plan、snapshot、SVG、素材。

**输出**：`edit/project.md` 记录本轮采用版、输入路径、缺口、责任边界；必要时生成 `composition/pages/manifest.json` 和项目内 SVG / 图片副本。

**下一消费者**：制作方案、转写 / EDL、视觉时间绑定。

**完成标准**：知道当前使用哪一版脚本、哪一版画面、哪条声音、哪些决定不可自行改变；hash 不一致、snapshot 不完整或资产越界时停止并回上游，不静默继续。

### 2. 确定制作方案

在 `production-plan.md` 写清楚：成片形态（口播 / 动画 / 合成）、声音来源、画幅、画面过程、强调动作、素材、时间依据、字幕形态、交付件和返修范围。

需要改内容意义、必见对象、固定文字或素材关系时回 `$video-idea-system`；需要重做静态画面时回 `$planners-ppt-hell`；需要复用方法时调用 `$planners-method-wiki`，但 Wiki 只提供方法，不提供本项目事实。

**完成标准**：每个交付轨都明确，且知道后续是“以 EDL 实测时间为准”还是“以外部 SRT 为准”。

### 3. 声音与剪辑

原始媒体走：

```bash
python3 "<craft>/helpers/transcribe.py" "<source-video>" --edit-dir "<edit>" --audio-track 0 --backend auto
python3 "<craft>/helpers/pack_transcripts.py" --edit-dir "<edit>"
python3 "<craft>/helpers/check_edl.py" "<edit>" --max-pause 0.8
```

用 `edl.json` 表达取舍，不手改底片来表达取舍。逐字面写入的选择由 `selections.json` 表达，之后调用：

```bash
python3 "<craft>/helpers/apply_selection.py" "<edit>"
```

有声质量问题先诊断再处理：

```bash
python3 "<craft>/helpers/audio_diag.py" "<media>" --json
python3 "<craft>/helpers/audio_fix.py" "<media>" -o "<fixed.wav>" --target-lufs -16.5
```

**输出**：`transcripts/`、`takes_packed.md`、`edl.json`、必要时 `selections.json`。

**下一消费者**：正式渲染、字幕、逐字审阅面。

**完成标准**：EDL 可检查；源文件、区间、速度、段落累计时间明确；没有把预览渲染当成正式底片。

### 4. 逐字剪辑审阅

**何时进入**：EDL 已可检查，但剪点、错字或气口仍需要人确认。

**构建并挂载**：

```bash
python3 "<craft>/helpers/edl_preview_build.py" "<edit>"
python3 "<craft>/helpers/edl_review_surface.py" "<edit>" --surface-only
```

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

剪点确认且需要正式底片时，使用会记录实测段时长的渲染路径；这不是开始制作画面的前置：

```bash
python3 "<craft>/helpers/render.py" "<edit>/edl.json" -o "<edit>/cut.mp4" --preview --no-subtitles
```

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
python3 "<craft>/visual/scripts/align-visual-plan.py" \
  --plan "<visual-plan.json>" --script "<script.md>" --srt "<audio.srt>" \
  --output "<project>/timeline/alignment.json"
python3 "<craft>/helpers/import_srt_timeline.py" "<project>" \
  --srt "<audio.srt>" --alignment "<project>/timeline/alignment.json"
```

对齐工具写绝对来源路径；`srt-import` 只证明“这份 SRT 与这份内容契约完成了对齐”，不证明 EDL 实测。

**绑定规则**：

- 页面使用 `unitId`，不使用会随排序变化的临时序号。
- 视觉页优先为 `visual:<sourcePageKey>`；口播段为 `speech:<step-id>`；overlay 为 `visual:<tag>`。
- `review/review_data.json.binding` 是当前审阅快照的绑定证明。
- 反馈至少带 `unitId`、`chapterId`、`stepId`、`snapshot`、`text`；收件器会拒绝不存在或 chapter 不匹配的 `unitId`。
- 改变时间轴、EDL、SVG 或字幕后必须重新 build review；不能拿旧页面继续提交。

### 7. 动效与合成

静态 SVG 必须来自第 1 步导入的项目内副本。沿用 `data-step`、`data-anim`、元素 `id` 和画面原有尺寸；不要把页面截图当成可编辑 SVG。

- HyperFrames：读 `$hyperframes`。整片走 `visual/scripts/generate-composition.py`；单层动效也先在 composition 中预览。只有最终合成需要独立透明视频，才用 `helpers/render_layer.py` 输出 `.mov`；兼容旧媒体叠层面时可同时输出 `.webm`。预览与渲染前先 `hyperframes check`。
  **动效的源是 composition，不是那段视频**：层要能改、能预览，才谈得上「先审后渲」。
- Manim：只有严密数学或技术动画才调用 `$manim-video`。
- 自定义逐帧：读 `references/frame-animation-pipeline.md`。
- 合成：读 `references/composition-craft.md` 与 `references/visual-rendering.md`。

所有 overlay 在写入 EDL 前检查：画布尺寸、alpha、起止时间、父级 `unitId` 和输出路径。尺寸不匹配必须报错，不能静默跳过。

**输出**：`composition/`、透明或整屏视觉层、合成预览和最终合成视频。

**下一消费者**：动效与合成审阅面、交付核验。

### 8. 动效与合成审阅

先读 `references/review-ui.md` 与 `references/hyperframes-review-adapter.md`。通常调用：

```bash
python3 "<craft>/helpers/live_stage.py" "<project>" --json
python3 "<craft>/helpers/build_review.py" "<project>" --mode auto --slices off
python3 "<craft>/helpers/review_surface.py" "<project>" --surface-only
```

DSH 有 `review_open` 时传返回的 surface 绝对路径；没有时去掉 `--surface-only`，由 review-core 启动本地宿主。两种宿主使用同一份审阅页。

官方播放器承担播放、暂停、拖动、倍速、单屏播放和屏末定位。字幕与反馈位置读取它的播放头；不要同时启动旧 SVG 定时器或隐藏视频。逐动画反馈以分屏、播放时间及对应分句锚点记录；框选批注先暂停。点选调整切换到静态源稿编辑，调整作为请求随反馈提交，返回预览后看当前真实工程，不能把未应用的草稿说成已生效。

`review/media.json` 显式声明已有成片、底片或透明视频层；这些兼容入口继续保留。工程含图片、声音或录屏时必须来自项目内资产；`live_preview.py` 拒绝外部资源和越界路径。桥传素材字节，播放器层使用可跨不透明源的媒体载体；不要把父帧的 `blob:null` URL 直接给子帧。大型源媒体先准备可播放的审阅代理，不要把数百 MB 原片反复传进侧栏。

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

```bash
python3 "<craft>/helpers/check_parity.py" "<project>"
python3 "<craft>/helpers/verify_delivery.py" "<edit>" --video "<final-video>"
python3 "<craft>/helpers/export_deliverables.py" "<project>"
python3 "<craft>/helpers/state_fingerprint.py" capture "<project>"   # 交付自带来源指纹
```

`check_parity.py` 先跑：它断言 spec（`choreography.json`）里的每个效果 kind 在 composition 与审阅页两条路径都有实现、每个 selector 在目标页面上真的命中元素。这两类失配**不会让 `hyperframes check` 失败、也不会让页面报错**，只会让某一步静默不演 —— 交付前必须过。

**已有交付先用 `state_fingerprint.py verify` 判断是否过期；改源后过期正是需要重新输出的信号，不拦住新渲染。** 重新输出并核验后 `capture` 新指纹，发送前再 `verify`，不一致就不能发送。工程态的渲染与预览一律落 `edit/_engineering/`，**不进 `edit/` 根**，免得被当成当前底片（GOTCHAS #56）。

核验实际成片，不核验预览假象：声音、首 / 中 / 尾画面、字幕、关键动效、alpha、画幅、帧率、时长和交付文件名。交付中明确：有声 / 无声、透明 / 不透明、字幕烧录 / 外挂，以及仍未完成的事项。

## 故障表

| 现象 | 处理 |
|---|---|
| segment duration 累积或 hash 不匹配 | 不手改字幕；重新渲染当前 EDL，再 `--build --check` |
| `--prepare` 会覆盖人工正文 | 先确认版本；只有确认 EDL / 转写已变时用 `--force-prepare`，之后重新放回人工正文 |
| overlay 尺寸与画布不符 | 修正源尺寸或显式适配；禁止静默跳过 |
| 审阅页媒体读不到 | 检查 `review.asset` 的相对 `dir` 路径和项目内资产副本，不改成猜相对路径 |
| surface 加载但 bridge 不可用 | 用 DSH `review_open` 或公共 review-core 宿主；不显示假成功 |
| 草稿显示已保存但提交文件没变 | 这是 `draft()`，不是 `write()`；点击正式提交并检查回执 |
| `unitId` 被收件器拒绝 | 重新 build review；检查当前 `review_data.json.binding` 与反馈的 chapter / snapshot |
| SRT 对齐路径不稳定 | 从任意工作目录调用时使用绝对 `--plan`、`--script`、`--srt`、`--output` |
| 音频需要 EQ 但工具没有该能力 | 先用 `audio_diag.py` 诊断；没有明确处理器就报告能力边界，不伪造完成 |
| 导出结果纯色、无声或无字幕 | 回到正式 render；`export_video.py` 只包装已有结果，不替代渲染 |

## 文件与参考入口

- 可执行命令与产物目录：`references/tools.md`
- 上游交接与责任边界：`references/content-to-production.md`
- 视觉时间绑定：`references/visual-timeline.md`
- **卡点对齐（词在第几秒）：`helpers/align.py`** —— 优先真实词级时间戳（`edit/transcripts/*.json`），命中不到才退回比例估算并标注 `estimated`。**卡点不要手算比例**：`edit/caption_words.json` 的字时间是段内插值，是假的
- 字幕契约：`references/caption-article-first.md`
- SVG 动效契约：`references/svg-animation-contract.md`
- 合成与渲染：`references/composition-craft.md`、`references/visual-rendering.md`
- **审阅页硬约定（改审阅页前必读）**：`references/review-ui.md`、`references/hyperframes-review-adapter.md`；桥、宿主与收件：`$planners-review-core`
- 维护与已知陷阱：`GOTCHAS.md`、`references/architecture.md`

## 自检

从 Skill 根运行：

```bash
PYTHONPATH=helpers python3 -m unittest discover -s tests -p 'test_*.py'   # 必须 0 error
python3 helpers/check_review_template.py                                  # 审阅页七条静态不变量
python3 helpers/check_review_template.py --prove                          # 证明那七条不是空洞判据
node "<review-core>/evals/run.mjs"
python3 -m unittest discover -s "<review-core>/evals" -p 'test_*.py'
```

第一条必须**全绿**，不是"大部分通过"。这个仓库的自检曾经常年带着两个 ERROR 在跑 —— `test_interactive_ui.py` 连 import 都失败（模块被删掉了）、`test_snapshot_input.py` 找不到隔壁 Skill 的模块而被静默跳过 —— 于是没人看结果，同一个审阅页文件连着返工三轮（GOTCHA #57）。有 skip 是允许的（浏览器用例需要 `VIDEO_CRAFT_BROWSER_TESTS=1` 与 playwright，见下），但 skip 必须写在案上，不能当成通过。

`check_review_template.py` 是**静态**的：它钉住七类机械缺陷不会静默回来，**不证明页面能跑** —— 新的类仍然要人撞到。别把绿灯读成"审阅页已验证"。同样的道理，浏览器用例（`VIDEO_CRAFT_BROWSER_TESTS=1`）默认不跑，所以舞台的**握手**目前只由 `tests/test_composition_embed_bridge.py` 的协议测试间接保证。

真实项目至少走一遍：`build_review → surface-only → 页面加载 → 提交带 unitId 的反馈 → review_inbox → 修改源 → 重新 build review`。只有这条链通过，才报告审阅接缝可用。审阅时画面走**工程态**（活 composition，见「两个态」）：先 `live_stage.py` 起服务，再 `build_review.py`。

浏览器验收入口与覆盖边界见 `references/review-ui.md`；新增传输回归在 `tests/test_live_preview.py`。
