# 制作阶段契约

这里是阶段输入、工作顺序、完成条件和返回条件的权威出处。入口 [SKILL.md](../SKILL.md) 负责按任务路由；[tools.md](tools.md) 负责命令调用；CLI `--help` 只解释参数。阶段是工作职责，不要求一阶段对应一个新脚本。

## 阶段与步骤映射

| 阶段 | 步骤 | 模型负责 | 现有工具入口 | 完成后去哪里 |
|---|---|---|---|---|
| 接入 | 1–2 | 版本取舍、缺口、视听方案与本轮终点 | check_script_hash；上游交接检查 | 原始媒体去剪辑；已剪音频去时间；未录音留 planned |
| 剪辑 | 3–4 | 留哪句、气口取舍、错字确认 | stage_cut 的 prepare / review / apply；建 EDL 用既有专用工具 | 剪点确认后去时间 |
| 时间与字幕 | 5–6 | 语义断句、视觉分组；区分时间证据 | duration_plan / srt_export / timeline_derive；外部 SRT 用 import_srt_timeline | 时间绑定完成后去画面 |
| 画面 | 7 | 原页拆解、逐段动作与强调（montage：镜头表与渲染体检） | film；recompose_plan；手写 composition；montage | 去审阅 |
| 审阅与返修 | 8–9 | 解释反馈、改源、决定返工范围 | review 构建；review_inbox 收件，两者独立 | 工程审阅可交接；出片需作者指令 |
| 交付 | 10 | 确认交付形态、审听审看 | deliver；verify_delivery；export_deliverables；state_fingerprint | 实际文件核验后交付 |
| 收尾与风格提取 | 11 | 区分项目问题与可复用风格规则；或从外部参考片独立提炼新风格 | extract_style；spec_lint（确实改规范时） | 外挂风格库演进/新建，或开源基准更新 |

检查与环境诊断是各阶段的内部动作，不另立制作阶段。旧文档的“九个动作”是分类表，不是九个必须新增的 stage 脚本；原 11 步编号继续保留；旧的 SKILL 步骤引用改指本文件。

## 时间依据与任务终点

时间来源的定义在 [visual-timeline.md](visual-timeline.md)。未录音 planned 只能交方案或独立预演；EDL projected 可以支持工程审阅，不能证明成片已实测；EDL measured 必须匹配当前剪辑指纹；外部音频 + SRT 标 srt-import，并核对真实媒体，不能冒充 EDL measured。

**每轮的默认终点是侧边栏审阅页可播 + 本轮待办，不是出成片。** 渲染产物分两级，下文各步说的「输出」都按这条分级读：

- `edit/_engineering/**` = **审阅素材**（工程态）：可随时重渲、可被审阅页消费，**不算交付**；
- `成品/**` = **交付件**：只有「作者明确出片指令」+「人工提交覆盖当前快照（`render_gate.py` 放行）」同时成立才允许写入。

`montage.py render` 的默认输出同样是审阅素材；把任何渲染写成一轮工作的自然收尾都是错的。

有视觉制作才进入第 7–9 步；纯剪辑使用逐字审阅与 render.py 的对应输出能力，不为通过 film/recompose 检查捏造参考页。外部 SRT 项目跳过不适用的 EDL 步骤。成片交付的适用限制见 delivery.md；默认完成线是本轮适用的工程审阅面可用、版本与待办清楚。

## 1. 接手与版本核对

**何时进入**：所有新项目、恢复项目、收到返修反馈时。

**先读**：`content-to-production.md`、`preferences.md`（准入与归位规则）、项目 `_idea/current.md`、已有 `edit/project.md`、`production-plan.md` 和 `feedback/`。接着运行外挂风格手册解析器，获取全局判准与当前风格手册（开源环境未挂载 `~/.config/planners/video-vault` 时自动回退至内置 `author-spec.md` 与 `style-spec.md`）：

```bash
python3 "<craft>/helpers/resolve_vault.py" --style "<style_id>"
```

读取返回的 `author_spec_path`（全局判准，全篇）与 `craft_rules_path`（当前风格规则）。当 `production_mode == "keyframe-svg"`（`graphic` 片型）时，画面以 PPT Hell 的视频快照为参考页（recompose 不导入页，见 [recompose-mode.md](recompose-mode.md)）；当 `production_mode == "footage-montage"`（`montage` 片型，如 `lifestyle-cult`）时，项目跳过 PPT Hell 直接携带 `visual-plan.json` 中的 `footage_request` 与 `kick_word` 进入本阶段。

**调用**：

```bash
python3 "<craft>/helpers/check_script_hash.py" "<project>" --script "<script.md>" --plan "<visual-plan.json>"
```

上游交接检查（`check-handoff-artifacts.mjs`）见 [tools.md](tools.md)「接上游」。

recompose 路线**不导入页**：PPT Hell 的快照只作视觉参考，用 `film.py` 抽原页拆解（见第 7 步）。
`import_svg_page.py` 属于已归档的 page 路线，只在复活旧项目时读 [legacy-page-route.md](legacy-page-route.md)。

**输入**：上游交接包、作者决定、脚本、visual-plan、（`keyframe-svg` 模式下）snapshot 与 SVG、素材。

**输出**：`edit/project.md` 记录本轮采用版、输入路径、风格 ID（`style_id`）、制作模式（`production_mode`）、缺口、责任边界；登记批准页面快照（或 `footage-montage` 素材清单）与所需项目资产。旧 page 项目的 manifest 仅作为兼容输入，不要求新建。

**下一消费者**：制作方案、转写 / EDL、视觉时间绑定。

**完成标准**：知道当前使用哪一版脚本、哪一版画面（或素材清单）、哪条声音、哪些决定不可自行改变；hash 不一致、snapshot 不完整或资产越界时停止并回上游，不静默继续。

## 2. 确定制作方案

在 `production-plan.md` 写清楚**片型**、风格 ID（`style_id`）、成片形态（口播 / 动画 / 合成）、声音来源、画幅、画面过程、强调动作、素材、时间依据、字幕形态、交付件和返修范围。

**先读**：`creative-direction.md`（自述「第一次制作方案时读取」）；`visual-direction.md`（自述「制作方案阶段读取」）；`caption-modes.md`（自述「制作方案阶段明确字幕交付形态」，字幕形态就在这里定，第 5 步不重选）；要画框时读 `frame-spec.md`（以及 `resolve_vault.py` 返回的 `frame_preset_path`）；按 `resolve_vault.py` 返回的 `craft_rules_path` 与 `patterns/` 读取当前风格的动效/剪辑规则与三联帧参考（未挂载私有库时读 `style-spec.md` 对应节）。判准与准入（`author-spec.md` / `preferences.md`）在第 1 步已读过，这里只按片型取执行点。

能力包的记录写在 `edit/project.md`（人读），**不新增 project.json**；只有被工具实际消费的字段才值得机器化。

**片型二选一（与风格 `production_mode` 一一对应），必须显式写下来**：

| 片型 | 对应 `production_mode` | 画面从哪来 | 走哪条 | 风格字段 |
|---|---|---|---|---|
| `graphic` | `keyframe-svg` | 画出来：页、图形、字卡、动效 | recompose（第 7 步按风格那一节做） | 必填 `line-art` 线稿 / `business-report` 商业报告 / `collage` 拼贴 / `concept-film` 概念电影（优先读私有库 `styles/<style>/craft.md`，回退读 [style-spec.md](style-spec.md)） |
| `montage` | `footage-montage` | 选出来：档案影像、实拍、照片（跳过 PPT Hell） | [montage-route.md](montage-route.md) 的 素材清单 → 镜头表 → 渲染体检 | 如 `lifestyle-cult`（读私有库 `styles/lifestyle-cult/craft.md`）、调色档与素材清单路径 |

**版式/画框是另一层**，两种片型都可能要：作者给了参考页或版面约束时读 [frame-spec.md](frame-spec.md)，把 token 写进方案，用 `helpers/frame.py build` 出 `material/frame/` 的三个产物（`base.png` / `overlay.png` / `spec.md`），再用 `frame.py preview` 拿一张真实素材的合成预览给作者挑方向。

需要改内容意义、必见对象、固定文字或素材关系时回 `$video-idea-system`；需要重做静态画面时回 `$planners-ppt-hell`；需要复用方法时调用 `$planners-method-wiki`，但 Wiki 只提供方法，不提供本项目事实。

**完成标准**：每个交付轨都明确；未录音标 planned，有 EDL 明确工程 projected 与交付 measured 的切换，外部 SRT 保留 srt-import 来源。

## 3. 声音与剪辑

原始媒体走：

```bash
python3 "<craft>/helpers/transcribe_seedasr.py" "<source-video>" --edit-dir "<edit>"
```

首选 SeedASR（豆包流式语音识别 2.0，语音技术控制台凭据）。`transcribe.py --backend auto`（Scribe→Ark→mlx）是**没有豆包语音控制台凭据时的历史回退**：它可能落到 Ark 通用模型那一路，那正是 GOTCHAS #1 禁止的「拿通用模型当 ASR」，不能当推荐顺位，也不要用它伪造词级时间。

打包与停顿预算（`pack_transcripts.py` / `check_edl.py`）见 [tools.md](tools.md)「声音与剪辑」。

用 `edl.json` 表达取舍，不手改底片来表达取舍。逐字面写入的选择由 `selections.json` 表达，之后调用：

```bash
python3 "<craft>/helpers/apply_selection.py" "<edit>"
```

有声质量问题先诊断再处理：

音质诊断与处理（`audio_diag.py` / `audio_fix.py`）见 [tools.md](tools.md)「声音与剪辑」。

**输出**：`transcripts/`、`takes_packed.md`、`edl.json`、必要时 `selections.json`。

**下一消费者**：逐字剪辑审阅面；字幕与工程态时间脊柱可先行。正式底片渲染排在剪点确认之后（第 5 步），不排在审阅之前。

**完成标准**：EDL 可检查；源文件、区间、速度、段落累计时间明确；`transcripts/<source>.json` 是词/字级（正常 token < 1s，粗粒度转写先跑 `refine_transcript.py`）；没有把预览渲染当成正式底片。

## 4. 逐字剪辑审阅

**何时进入**：EDL 已可检查，但剪点、错字或气口仍需要人确认。

**构建并挂载**：

```bash
python3 "<craft>/helpers/edl_preview_build.py" "<edit>"
```

面上缝（`edl_review_surface.py --surface-only`）见 [tools.md](tools.md)「审阅」。

DSH 有 `review_open` 时，把返回的 **surface 绝对路径**交给 `review_open`；没有插件时去掉 `--surface-only`，使用公共 review-core 本地宿主。不要自己另起一份 Craft 专用宿主。

**素材大时先选宿主**：源媒体超过约 200MB、或机器可用内存低于约 8GB 时，逐字剪辑面直接走本地宿主（不带 `--surface-only`），不交给 `review_open` —— 侧栏桥按整份字节传，几百 MB 的源片会把内存吃穿。判据与说明归 [review-ui.md](review-ui.md)「剪辑面独立打开」。

**人可以做的事**：播放、上一刀 / 下一刀、拖时间轨、点词定位、拖选删除词、选择或恢复气口、改字、提交剪辑选择、另写整片意见。

**工具与反馈边界**：播放器、时间轨、选词、改字、停顿数值属于页面工具；整片备注和“请 Agent 应用剪点”属于反馈。页面写 `selections.json`，Agent 收件后才运行 `apply_selection.py`。

**完成标准**：提交文件真实写入；没有桥时页面明确显示未连接；Agent 先读取提交再应用选择；应用后重建逐字预览；需要视觉制作时更新工程时间轴和字幕，最终输出时再做实测核验。

## 5. 工程时间与字幕；确认后输出底片

**先读**：`caption-article-first.md` —— 语义字幕的唯一 owner（全文校对 → 语义断句 → 锁定 → 生成；文字长度、词边界、纠错与 EDL 边界规则都在它，不另立自动断句）。字幕交付形态在第 2 步已由 `caption-modes.md` 定，这里不重选。

**渲染不是「能开始干活」的前提。** 想让作者先看到东西，先出工程态：

```bash
python3 "<craft>/helpers/duration_plan.py" "<edit>"     # 解析预演（帧量化，projected）
# 已有外部透明视频层才需要 preview_layers.py；HyperFrames 动画直接预览工程。
```

`projected` 记录可以支撑第 6 步的时间脊柱、字幕和审阅页，但**不是交付证据**——
`_edl.render_record` 默认跳过它，`verify_delivery.py` 永远拿真实文件对真实渲染。
交付前必须取得正式输出的实测证据并重建依赖产物。已有 projected/nominal 项目通过 `srt_export --prepare --force-prepare --time-source measured` 明确升级，再 lock/build、重派生 timeline 和 check；保留已审 semantic_lines，不能只改来源标签。下面的工程底片命令不代表正式交付完成。

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

## 6. 建立唯一时间脊柱

`timeline/timeline.json` 是页面、动效、字幕和审阅绑定共同消费的时间脊柱。

已有 EDL 字幕 cues（measured 或 projected）时用 `timeline_derive.py`；只有外部剪好音频和 SRT 时：

```bash
python3 "<craft>/visual/scripts/align-visual-plan.py" --plan "<visual-plan.json>" --script "<script.md>" --srt "<audio.srt>" --output "<project>/timeline/alignment.json"
```

外部 SRT 的时间脊柱（`import_srt_timeline.py`）见 [tools.md](tools.md)「SVG 与视觉时间」。

对齐工具写绝对来源路径；`srt-import` 只证明“这份 SRT 与这份内容契约完成了对齐”，不证明 EDL 实测。

**绑定规则**：

- 页面使用 `unitId`，不使用会随排序变化的临时序号。
- 视觉页优先为 `visual:<sourcePageKey>`；口播段为 `speech:<step-id>`；overlay 为 `visual:<tag>`。
- `review/review_data.json.binding` 是当前审阅快照的绑定证明。
- 反馈至少带 `unitId`、`chapterId`、`stepId`、`snapshot`、`text`；收件器会拒绝不存在或 chapter 不匹配的 `unitId`。
- 改变时间轴、EDL、SVG 或字幕后必须重新 build review；不能拿旧页面继续提交。

## 7. 动效与合成 / 蒙太奇渲染

**片型是 montage 时，本节换成 [montage-route.md](montage-route.md) 的第 3–4 节**：镜头表交给 `montage.py plan` 展开，`render` 分块渲染，`check_montage.py` 逐镜与成片两关体检；不要为通过 film/recompose 检查去捏造参考页，也不要在 montage 项目里手写 composition。下面是 graphic 片型的路径。

**先读（按片型取）**：`graphic` → `film.md`（原页拆解）、`recompose-mode.md`、`composition-craft.md`；`montage` → `montage-route.md`。按需：`visual-rendering.md`（透明载体 / 编码 / alpha 选择）、`frame-animation-pipeline.md`（自定义逐帧）。**本轮终点仍是第 8 步的审阅页**：这里产出的是工程态（`edit/_engineering/**` 与活 composition），分级见上文「时间依据与任务终点」。

动手前必须已有 `pages/<page>.md` 原页拆解（见 [film.md](film.md)），元素清单按阅读顺序登记；
把原页当**信息源**，按拆解逐条演出来 —— 不重画模型图，不把截图当 SVG。原页元素若已有
`data-step` / `data-anim` / `id`，沿用它们；只有元素级动效才需要稳定 id。

- HyperFrames：读 `$hyperframes`。整片 composition 由 `film.py` 的拆解驱动、手写 `src/scenes/*.js`（`generate-composition.py` 已随 page 路线归档，不再运行）；单层动效也先在 composition 中预览。只有最终合成需要独立透明视频，才用 `helpers/render_layer.py` 输出 `.mov`；兼容旧媒体叠层面时可同时输出 `.webm`。预览与渲染前先 `hyperframes check`。
  **动效的源是 composition，不是那段视频**：层要能改、能预览，才谈得上「先审后渲」。
- Manim：只有严密数学或技术动画才调用 `$manim-video`。
- 自定义逐帧：读 `frame-animation-pipeline.md`。
- 合成：读 `composition-craft.md` 与 `visual-rendering.md`。

**渲染前置（缺一不渲，只在作者出片指令之后才需要满足）**：按 [timing-lock.md](timing-lock.md) 逐条过 —— `film.py verify` 退 0、`feedback/*.jsonl` 的未决项已清或显式接受、review 运行时检查通过且人工提交覆盖当前快照；任何 `hyperframes render` 之前先跑 `python3 "<craft>/helpers/probe_env.py" "<project>"` 报能力（libass / 字体预算 / 残留进程；只报告不阻断），再跑 `python3 "<craft>/helpers/check_render_env.py" "<project>/composition"` 拿 RAM、可用内存与建议的 `--workers`（默认从 1 起）。

所有 overlay 在写入 EDL 前检查：画布尺寸、alpha、起止时间、父级 `unitId` 和输出路径。尺寸不匹配必须报错，不能静默跳过。

**输出**：`composition/`、透明或整屏视觉层、工程态合成预览（活 composition，不渲帧）。合成视频分两级：审阅素材写 `edit/_engineering/**`，交付件写 `成品/**`（只有作者出片指令 + `render_gate.py` 认可人工提交覆盖当前快照时才写，见第 10 步）。本轮默认终点是第 8 步审阅页可播，不是出成片；返修可重新输出。

**下一消费者**：动效与合成审阅面、交付核验。

## 8. 动效与合成审阅

**本轮的默认终点就是这一步**：侧边栏审阅页可播 + 本轮待办。这里构建的是工程审阅页，不是在出片。

**片型是 montage、或项目只有渲好的成片时，没有活舞台可查**：`review.py` 会按 `edit/montage-plan.json`（或 `--final-cut`）判成**成片态审阅**，跳过活舞台三步、构建成片态页面；这时只核 `review/index.html` 能否构建与 `check_review_playable.py` 是否通过，不要为通过活舞台检查去捏造 composition。判据见 [review-ui.md](review-ui.md) 的「成片态审阅（final-cut）」。下面是 graphic 片型的路径。

先读 `review-ui.md` 与 `hyperframes-review-adapter.md`。**`build_review` 之前先跑活舞台契约检查**：

```bash
python3 "<craft>/helpers/check_live_stage.py" "<project>"   # 退 0 才继续
```

它静态断言这份 composition 能进审阅页的活舞台（`data-composition-id` 与时间轴注册名一致、
会执行逻辑的脚本全在外部文件、嵌入桥在、媒体在预算内）。`hyperframes check` 全绿**不能**替代它：
那条路径不经过审阅页的 `srcdoc`，内联脚本被编译器改写成 `type="text/hf-after-fonts"` 后
在 srcdoc 里永远不执行，播放器拿到 0 秒、舞台全黑。契约与根因见
[live-stage-contract.md](live-stage-contract.md)。

通常调用：

```bash
python3 "<craft>/helpers/review.py" "<project>"      # 一条命令出审阅页（含活舞台、构建、运行时判据）
```

**review.py 已包含静态前置和运行时检查，不重复跑同一链；手动分步调试 build_review 时必须补跑下列运行时检查**：

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

## 9. 收件、返修与重建

先收件，再读反馈，再改源：

```bash
python3 "<craft>/helpers/review_inbox.py" "<project>"
```

检查收据中的 `imported`、`skipped`、`rejected`。有 rejected 时先修复记录或重建快照，不能假装收件完成。

- 逐字反馈：读 `selections.json`，运行 `apply_selection.py`，重建逐字预览、工程字幕与时间轴；正式底片留到确认后输出。
- 动效 / 合成反馈：读 `feedback/<chapterId>.jsonl` 和记录中的 `adjustments`，修改 composition / SVG 源，重新 build review 并刷新；确认后再 render。
- 元素微调若要写回源 SVG，必须核对 source snapshot / version；源已改变时拒绝覆盖，交 Agent 决定如何合并。
- 改变任何时间、页面或媒体绑定后，重新运行 `build_review.py`，让旧 snapshot 失效。

## 10. 核验与交付

**默认停在工程审阅交接（第 8–9 步），随后做第 11 步收尾。** 审阅的交付物是**工程态审阅页**，不是成片。只有当作者明确说"出片/交付"时才进入本节；在此之前任何 `hyperframes render` 或 `deliver`（不带 `--render`）都不该发生。写 `成品/**`（交付件）只在这里发生；工程态预览与渲出的审阅素材一律落 `edit/_engineering/**`（分级见文首「时间依据与任务终点」）。

作者确认出片后，先按 [timing-lock.md](timing-lock.md) 做前置检查；再调用现有合成入口：

```bash
python3 "<craft>/helpers/deliver.py" "<project>" --render        # 渲染画面层 + 人物贴回 + 声音 + 核验报告
python3 "<craft>/helpers/deliver.py" "<project>" --visuals "<已有画面层.mp4>"   # 画面层已存在，跳过渲染
```

交付成功语义与人工完成线见 [delivery.md](delivery.md)：`deliver.py` 退出 0 表示本次合成及适用严格核验通过，包装副本与发送前指纹仍须独立核对。

它按 `recompose.json` 的 `personSlot` / `captionSafe` 贴回人物、接声音、核验分辨率/帧率/时长/音轨/
首中尾帧/字幕安全区，并写 `<成品>/<片名>_核验报告.json`；第一件事是跑 `render_gate.py`
（没人审覆盖当前快照就拒绝出片）。**没有人物轨的片子加 `--no-person`**（纯画面 + 旁白是合法形态，
不是缺素材）。缺画面层、缺来源证明或来源内容已变化时 **deliver 默认拒绝**，不会自动渲染——那会把审阅变成导出；
重渲必须显式 `--render`。
契约见 [delivery.md](delivery.md)。

**渲染前的第一步是渲染闸门，不是 render。** 它要求 `review/review-submissions.json`（或
`feedback/*.jsonl`）里至少一条人工提交覆盖**当前**审阅快照，且源在那次构建之后没有再改过：

```bash
python3 "<craft>/helpers/render_gate.py" "<project>" --out "<实际成片路径>"   # 退 0 才允许 render
```

退 1 = 这一版没人看过或源已漂移，先用 `review.py` 重建并打开审阅；退 2 = 还没有审阅数据。
工程态预览（`--preview`、落 `edit/_engineering/`）用 `--engineering --out <edit/_engineering/...>`，
它不能改个文件名当成交付成片。口头规则拦不住渲染，这条闸门才是判据。

```bash
python3 "<craft>/helpers/check_motion_targets.py" "<project>"
```
**成片在渲染后被二次剪过（例如剪停顿）不是默认可交付形态。** 剪点必须写进
`edit/cut-map.json`，剪后字幕必须由剪前字幕 + 同一份剪点逐条复算；`verify_delivery.py`
会按 cut-map 核成片时长与每一条字幕（条数/文字/起止 ±20ms），没有声明又比渲染记录短就拒绝交付。
映射是单调分段函数，**禁止边遍历边改时间**（2026-10-22 XHS v2 因此最大偏 3.2 秒）。
契约见 [delivery.md](delivery.md)「成片被二次剪过」。


其余交付核验（`verify_delivery.py` / `export_deliverables.py` / `state_fingerprint.py`）与 `check_parity.py`（仅老 page 项目）见 [tools.md](tools.md)「渲染、核验、包装」。

手写 GSAP/recompose 交付前跑 `check_motion_targets.py`：recompose 项目没有 `timeline/choreography.json`——它的唯一生产者 `auto_choreography.py` 已随 page 路线归档。这条检查断言时间轴里的每个 selector 都命中、且页面自带的静态 `transform` 没有被 x/y/scale/rotation 补间覆盖（GSAP 会把 attribute 重写掉，位移静默丢失）。

只有复活老 page 项目、且项目里真有 `choreography.json` 时才跑 `python3 "<craft>/helpers/check_parity.py" "<project>"`（断言 spec 里的每个效果 kind 在 composition 与审阅页两条路径都有实现；退 0 一致 / 1 有不一致 / 2 用法错误或缺 choreography.json）。两类失配都**不会让 `hyperframes check` 失败、也不会让页面报错**，只会让某一步静默不演 —— **这类老项目的交付前必须过**；recompose / montage 项目没有 `choreography.json`，不跑它。

**指纹不是渲染前置，是交付过期信号**：已有交付先跑 `state_fingerprint.py verify` 判断是否过期；改源后过期正是**需要重新输出**的信号，不拦住新渲染，只拦住**发送**。 重新输出并核验后 `capture` 新指纹，发送前再 `verify`，不一致就不能发送。工程态的媒体输出与预览一律落 `edit/_engineering/`，**不进 `edit/` 根**，免得被当成当前底片（GOTCHAS #56）。

核验实际成片，不核验预览假象：声音、首 / 中 / 尾画面、字幕、关键动效、alpha、画幅、帧率、时长和交付文件名。交付中明确：有声 / 无声、透明 / 不透明、字幕烧录 / 外挂，以及仍未完成的事项。

## 11. 收尾与风格提取/进化

本步既是**常规项目完成后的收尾入口**，也是**直接喂入外部参考视频或已完工项目提炼新风格的独立入口**。

**先读**：`preferences.md`（准入与归位规则）与 [style-extraction.md](style-extraction.md)（与模型无关的四步提取协议：谁消费切哪层、行为与数值分离、四字段禁引文、工具管准入与上限淘汰）。

**统一按四步协议执行（不直接手改风格库 Markdown）**：

1. **工具采样生成证据包（`packet`）**：
   ```bash
   python3 "<craft>/helpers/extract_style.py" packet \
     --video "<project_dir_or_ref.mp4>" \
     --style "<style_id>" \
     --out "<project_or_tmp>/packet.json"
   ```
   自动汇总本片 `feedback/*.jsonl`、`edit/preferences.md`、画面契约或视频帧采样，并附上目标风格当前的 `idea/page/craft.md`、参数表、候选池 `candidates.json` 与剩余容量。

2. **模型按四问填表写出提案（`proposal.json`）**：
   对照 `packet.json` 的 `extraction_rubric` 填写结构化提案：
   - 按消费者分进 `idea`（`I01..I05`）、`page`（`P01..P05`）、`craft`（`C01..C05`）；
   - `标题` 与 `做法` 只写可观察的行为关系，**禁写数字、色号与原话引号**；具体数值写进 `params_patch` 并用 `参数` 字段引用键名；
   - 满 5 条时显式声明 `relation: "替代"` 或 `"合并"` 及 `target_id`。

3. **机械校验提案（`check`）**：
   ```bash
   python3 "<craft>/helpers/extract_style.py" check --proposal "<project_or_tmp>/proposal.json"
   ```
   退 `0` 才可进入第 4 步；退 `1` 按报错逐条修正。

4. **落盘、切片并写入本地版本库（`apply`）**：
   ```bash
   python3 "<craft>/helpers/extract_style.py" apply \
     --proposal "<project_or_tmp>/proposal.json" \
     --video "<project_dir_or_ref.mp4>" \
     [--confirm]
   ```
   工具自动完成准入分流（`feedback-negative` 一次入正册；单次倾向型先进 `candidates.json`，满 2 个独立项目自动晋升入正册，连续 3 个项目未复现自动淘汰）、切出三联帧 `*-strip.jpg` 与 `2s` `.webm`、跑 `lint` 校验零错误、刷新 `_video-vault/index.html`，并在 `_video-vault` 本地 Git 仓库自动提交一条版本记录。
   （若从外部参考片初始化全新风格，可先跑 `extract_style.py bootstrap --video <ref.mp4> --style <new_slug> --name "<名称>" --mode <keyframe-svg|footage-montage>`。）

**实际更改规范后校验**：

```bash
python3 "<craft>/helpers/extract_style.py" lint   # 外挂风格库全量结构、行数、参数与媒体存在性检查
python3 "<craft>/helpers/spec_lint.py"            # 开源基准 author-spec / style-spec 检查
```

**完成标准**：候选处理结果可追溯（进正册、进 `candidates.json`、替代了谁或未收）；`extract_style.py lint`（及改了开源规范时的 `spec_lint.py`）退 0；没有悬空执行点或不存在的媒体路径。
