# 当前播放接缝（2026-10-14）

| 模块 | 唯一责任 | 接口与不做什么 |
|---|---|---|
| EDL / 逐字预览 | 剪辑取舍、源媒体定位 | 保留原工具；不依赖动画或预渲整片 |
| HyperFrames 官方 player/runtime | 时间、媒体、clip 显隐、缩放、倍速 | 原生 play/pause/seek/playbackRate；Craft 不另造时钟 |
| live_stage.py | 编译服务生命周期 | 项目 → **已验为本工程的**编译路由（响应体既要有注入的 GSAP shim，其引用的资源也要真在本工程 `composition/` 里；否则是机器上另一个同名 `composition` 占了同一个 project id）；不驱动画面 |
| live_preview.py | 不透明宿主的工程传输 | 编译路由 + 项目 → HTML / 素材清单 / `assetBytes`+`assetSizes`（活舞台资产体积，供下游做预算）/ hash；严格包含性与本机来源；不渲染、不编排动画 |
| references/hyperframes-review-adapter.md | 新 HyperFrames 工程的审阅控制契约 | 可选 `VideoCraftReviewAdapter`；只暴露 composition 声明的参数，不拥有播放时间 |
| build_review.py | 审阅快照 + **活舞台资产预算** | 内联官方 player，记录版本/hash，加入工程 watch；把超预算的活舞台资产换成审阅副本并写 `composition.assetBytes` 与 `liveStage.budgetMs`；`media.sizes` 让页面在下载前拦下过大通道；不修改生产源 |
| review-page-template.html | 导航、字幕、批注、编辑请求 | 连接官方 player 与 review-core；工程路径不启用旧计时器 |
| planners-review-core | 文件与反馈传输 | 原有桥和宿主不改，不理解视频 |

退役：审阅页对 GSAP 的自造 liveStage 消息控制；工程预览直接嵌 localhost 的方式；每次改动画必渲透明载体的默认流程。旧 SVG 编辑、外部透明层、已有成片和逐字剪辑仍有真实调用者，保留兼容，不以删功能换简化。旧 composition-embed-bridge 文件只为既有工程保留，工程传输阶段移除它，避免形成第二个时钟。

以下为各既有模块与上游契约的详细说明；与实时播放有关的责任以本节为准。

# 架构：模块、接口、缝

这份文件给**改它的人**读：每个 module 拥有什么、接口是什么、不做什么、动了会牵连谁。
它不是文件清单——这里写的是**「我要改 X，该动哪里、会牵连什么」**。

词用的是 `codebase-design` 那套：**module / interface / seam / adapter / depth**。
一个 Stage 文档、一个脚本、一份 Contract、一个 Reference、一组 Asset 都是 module。

## 1. 目的与全景

`video-craft` 稳定完成一件事：**把创意内容包或一批素材，做成一条经过核验的成片**——
声音与画面怎么排、时间轴怎么定、字幕与花字怎么落、交付件怎么验。它不写稿、不画静态画面。

从接包到成片走 **10 步**。权威版本是 `SKILL.md` 的「全链流程」那一节（本节不另立判据，
只标出**每一步落在哪个 module、落什么盘**）。步号与 `SKILL.md` 一一对应：

| 步 | 落在哪个 module | 落盘的产物 |
|---|---|---|
| 1 接手与版本核对 | `helpers/check_script_hash.py` / `visual/scripts/import_svg_page.py`（`snapshot_input.py` 是它调用的库） | `edit/project.md`、`composition/pages/manifest.json` |
| 2 确定制作方案 | `references/content-to-production.md`（分界 owner）＋ `references/creative-direction.md` | `production-plan.md` |
| 3 声音与剪辑 | `helpers/transcribe*.py` / `pack_transcripts.py` / `check_edl.py` / `apply_selection.py` / `audio_diag.py` / `audio_fix.py` | `edit/transcripts/`、`takes_packed.md`、`edit/edl.json` |
| 4 逐字剪辑审阅 | `helpers/edl_preview_build.py`（出页）＋ `helpers/edl_review_surface.py`（面上缝） | `edit/edl_preview.html`、`edit/selections.json` |
| 5 工程时间与字幕；确认后输出底片 | `helpers/duration_plan.py`（`projected` 工程态）＋ `helpers/render.py --preview` ＋ `helpers/srt_export.py` | `edit/segment_durations.json`、`caption*` 系列、`subtitles.srt` |
| 6 建立唯一时间脊柱 | `helpers/timeline_derive.py`（唯一生产者）＋ `visual/scripts/align-visual-plan.py`、`import_srt_timeline.py`（外部 SRT 路径） | `timeline/grouping.json`、`timeline/timeline.json` |
| 7 动效与合成 | `visual/scripts/generate-composition.py`（＋ `import_svg_page.py`、`auto_choreography.py`）、`helpers/render_layer.py` | `composition/`、透明或整屏视觉层 |
| 8 动效与合成审阅 | `helpers/live_stage.py` ＋ `helpers/build_review.py` ＋ `helpers/review_surface.py`（`live_preview.py` 是其中的工程传输） | `review/review_data.json`、`review/index.html` |
| 9 收件、返修与重建 | `helpers/review_inbox.py` ＋ `helpers/review_slices.py` | `feedback/*.jsonl`、重建后的审阅面 |
| 10 核验与交付 | `helpers/check_parity.py` / `verify_delivery.py` / `export_deliverables.py` / `state_fingerprint.py` | `成品/`、`成品/delivery.json` |

形状：**第 1–4 步不需要实测音频；第 5 步起可以先出工程态（`projected` 解析预演），
但交付证据必须是实测渲染**。没有录音时项目照走到第 4 步并出可审的样片；「等录音」停的是
第 5 步**之后的交付态**，不是整条流程。`content-to-production.md` 是这条分界的 owner。

### recompose 构建模式（opt-in，不是用户路线）

page 路线 1–10 步不变。recompose 是项目级的内部模式，默认关闭；作者仍在 PPT Hell 确认 board，
Craft 把 board 当视觉参考、以 composition 为源重排。它复用同一套事实层、审阅宿主与交付核验。

| module | 拥有什么 | 接口 | 不做什么 |
|---|---|---|---|
| `helpers/build_review.py` 的 `density` 块 | 把逐字行按 beat 分组交给页面 | `review_data.json.density` | 不新增审阅宿主或第二份提交文件 |
| `visual/assets/review-page-template.html` 的密度 dock | 逐行 0–3 / off / 自动；多选批量；与分步动效同区两个 tab | 提交 `phase: "density"` 记录 | 不放 board 参考帧；`off` 句不展示分步动效 |
| `helpers/review_inbox.py` | 识别 density 记录，落 `feedback/density.jsonl`，回写 lines | `import_submissions()` | 不改 page 路线的逐章收件 |

## 2. 模块表

一行一个 module：**它是什么／拥有什么（唯一主人）／接口是什么／不做什么**。

### 触发面、全景与迭代落点

| module | 它是什么 | 拥有什么（唯一主人） | 接口 | 不做什么 |
|---|---|---|---|---|
| `SKILL.md` | 这个 Skill 的门面 | 10 步流程的全景与每步「一眼能不能看出没做完」、按当下需要的路由、机器保证 vs 判断的分界、两个入口 | 模型入口；frontmatter 的 `description` 是触发面 | 不写完整完成标准（那住在各 module 的文档里）、不复述子文档的规则、不定义字段语义 |
| `references/architecture.md` | 本文件 | 模块边界与缝、两个真相源、动的后果、退役清单 | 改之前读 | 不重复各 module 的内容细节 |
| `GOTCHAS.md` | **候选池** | 有证据、会稳定导致错误的行为候选；每条带 `module` 与状态（候选／已复现／已升级／已失效） | 按 module 聚类读；一条一个根因 | 不装已决定的升级（那是维护记录）；末尾那节写明**不收什么**及理由 |
| `references/maintenance-history.md` | **已发生的升级** | 每次升级做了什么／为什么／影响哪些 module／删了什么；未决事项单独标出 | 升级时追加，新的一次记在上面 | 不是 CHANGELOG，不记发版 |
| `README.md` | 给仓库**外面**的人看的说明 | 这个 Skill 是什么、四件事其实是同一件事、安装与测试入口 | 人读 | 不是运行路径的一部分；流程细节不在它这里 |
| `install.md` | 安装与重连 | 解释器、依赖、`ffmpeg`、转录密钥、HyperFrames 环境（含字体缓存）、各运行时的注册方式 | 首次安装或换机器时读 | 不写日常流程（那是 `SKILL.md`） |
| `manifest.json` | 包元数据与血统 | 名字、版本、`compat`、从哪里合并而来 | 发布工具读 | 不参与运行 |
| `upstream-diff.md` | 脱钩记录 | 吸收了上游什么、故意偏离了什么 | 只在查历史时读 | 不是现行规格 |
| `package.json` | 根依赖 | 只有 `ws`（SeedASR 的 WebSocket 桥要它） | `npm install` | 不定义任何流程 |

### Reference：流程与判断

| module | 拥有什么 | 接口 | 不做什么 |
|---|---|---|---|
| `references/content-to-production.md` | 承接阶段的产物与顺序（四件产物）、`script_hash` 两处核对口径、没有音频也要做完、「预演时间 vs 制作时间」两态。**完成标准的家是 `SKILL.md` 的 Process 步 1–4，这一份不另立判据** | 第 1–2 步读；第 3–4 步读它的顺序与产物表 | 不写具体剪法（`visual-direction.md`）、不定义契约字段（上游契约管） |
| `references/video-story-handoff.md` | 上游内容包的接收口径：契约 5.0 的 `screens`／4.0 的 `blueprints`、Beat 对齐、`sourceBlueprintId` | 第 1、6 步读 | 不定义上游字段语义；不复述上游契约 |
| `references/creative-direction.md` | 接住意图、主动设计视听表达的主线 | 第 2 步读 | 不写画面语言细节（`visual-direction.md`） |
| `references/capability-map.md` | 视听能力导航（按表达目的选，不按工具选） | 发想期与第 2 步读；Idea 也读它 | 不承诺运行依赖已安装 |
| `references/visual-direction.md` | 画面与动画的对齐顺序、只讨论真正改变成片的分歧 | 第 2 步读；第 10 步的字闸门判断依据在它这里 | 不写实现（`composition-craft.md`） |
| `references/preferences.md` | 作者偏好的最小记录与区分（本片要求 vs 可复用偏好） | 第 1 步起读 | 不把整份会话灌进上下文 |
| `references/media-first.md` | 真实证据 / 复刻 / 示意 / 创作的身份区分 | 选素材时读 | 不允许把修辞包装成实测证明 |
| `references/visual-timeline.md` | **时间脊柱的派生**：`timeline.json` 的输入、Step 分组规则、Checkpoint 只确认版面与节奏 | 第 6 步读；`timeline_derive.py` 是它的可执行形态 | 不重新解析 SRT；不重选主题 |
| `references/composition-craft.md` | 视觉层怎么落地：`composition/index.html` 的硬规则、字体度量、**画面页来自 planners-ppt-hell 时的动画交接** | 第 7 步读 | 字段语义不在它这里（`composition-facts-contract.md`）；预埋子元素动效配方在 `svg-animation-contract.md` |
| `references/svg-animation-contract.md` | **`planners-ppt-hell` → `video-craft` 的声明式 SVG 预埋动效契约**：5 条 SVG 分组与几何硬性规则、8 种复合子元素分阶段动效原语（`data-anim` + `.anim-*` 子选择器）、GSAP/WAAPI 双模式接线规范 | 做画面预埋动效与第 7 步绑实测时间轴时共读；`visual/assets/svg-anim-engine.js` 是旧 SVG 兼容路径的可执行形态；HyperFrames 新工程读自己的 composition 配置 | 不写口播实测毫秒数（制作前不知道时长，只预埋相对 `data-step` 顺序与微时序差） |
| `references/composition-facts-contract.md` | **`composite`／`personWindow`／`captionSafe` 三个键的字段契约**（键名、取值域、默认、谁填谁读、缺了怎样） | 做画面那一步与第 7 步都按它写/读 | 只写已实现的键；不设计新字段 |
| `references/themes.md` | **风格库的契约**：谁读它、必填 token、圆角刻度、可选性格覆盖与装饰层、创作新主题的步骤 | 选/换主题时读；`check_themes.py` 是它的可执行形态 | 不写章节 CSS（那是章节自由）；不复制 token 到别处 |
| `references/review-ui.md` | 视觉审阅页的约定、反馈 schema、三条硬约定、**与另一套审阅面的交棒条件** | 第 4、8、10 步读 | 不合并两套审阅面 |
| `references/visual-rendering.md` | 渲染、透明层容器选择、渲染前预检与受限环境 | 第 7、10 步读 | 不写审阅页（`review-ui.md`） |
| `references/frame-animation-pipeline.md` | 自绘逐帧动画那条路线：slot 切分、帧数合同、性能配方、逐画面返修、多腿交付 | 走自绘渲染器时读 | 不是画风规定 |
| `references/caption-article-first.md` | 中文语义字幕的完整规格（article → line plan → lock → build → check） | 第 5 步读；`srt_export.py` 是它的可执行形态 | 不与机械计时阶段交错 |
| `references/caption-modes.md` | 字幕三模式与断句原则；模式必须在 Checkpoint 问一次 | 第 5 步前读 | 不默认内嵌 |
| `references/timing-lock.md` | 渲染前的 Timing Lock 检查清单 | 渲染前读 | 不替代 `check_overlay.py` |
| `references/storyboard-format.md` | `storyboard.md` 的结构（`timeline.json` 的人读伴侣） | 第 6 步 Checkpoint 前读 | 不定义时间值 |
| `references/maintenance-history.md` | 见上（迭代落点） | — | — |

### 判据（`helpers/` 里带 `check_*` / `verify_*` 的那些）

每个都**只声称它能证明的那一件事**；互不蕴含（`GOTCHAS.md` #6）。

| module | 拥有什么（唯一判据） | 接口 | 不做什么 |
|---|---|---|---|
| `helpers/_edl.py`（库） | **EDL 身份与时间映射的唯一实现**：`edl_digest`、`select_render_record`、`duration_record`（字幕与交付共用同一记录策略） | 被 `check_edl` / `srt_export` / `duration_plan` / `render` / `timeline_derive` import | 不写盘、不规范化；读时校验、写时原样 |
| `helpers/check_edl.py` | 切点合法性、停顿预算、SRT 与实测时间轴是否同源 | `check_edl.py <edit_dir> [--max-pause] [--json]` | 不看画面、不判断内容 |
| `helpers/check_overlay.py` | 覆盖层接口：alpha 真在、没被烘死不透明、帧率与时长对得上 | `check_overlay.py <edit_dir>`；`render.py` 合成前会再调它 | 不渲染、不判断动效内容 |
| `helpers/check_motion.py` | 声明为动效的窗口是否真的有变化 | `check_motion.py <video> [--samples] [--expect-still]` | 不判断动作方向与结束状态（要人看片） |
| `helpers/check_screen_text.py` | 会出字的地方对回上游声明的花字，工程话命中即失败 | `check_screen_text.py <path> --plan <visual-plan.json> [--caption]` | 不另立第二份声明；只拦「任何风格下都是缺陷」的 |
| `helpers/check_caption_breaks.py` | 字幕断句：量词、孤块、句中切 | `check_caption_breaks.py <path>` | 不判断语义断句好不好（那是读一遍） |
| `helpers/check_alpha.py` | 交付前透明层是否真的透明（读**抽出的 alpha 平面**） | `check_alpha.py <file>` | 不信 `ffprobe` 的 `pix_fmt`（两个方向都会骗人） |
| `helpers/verify_av.py` | 渲染文件的轨与尾（响度吃掉结尾字、多机位偏移） | `verify_av.py --tracks a.mp4 b.mp4 ／ --tails a.mp4 ／ --pair face.mp4 base.mp4 ／ --all a.mp4 b.mp4` | 不检查交付副本（那是 `verify_delivery`） |
| `helpers/verify_delivery.py` | **交付副本**：与工作区逐字节、时长对渲染记录、字幕尾 | `verify_delivery.py <edit_dir> [--video] [--deliver-dir]` | 不看源素材 |
| `helpers/check_script_hash.py` | `script.md` 与内容契约的 `script_hash` 是否相符 | `check_script_hash.py <项目目录> ／ --script --plan`；退 0／1／2 | 不改任何文件；核不了时**不报成功** |
| `helpers/check_render_env.py` | 渲染环境：字体缓存可写、Node ≥ 22、composition 在；**并发预算** —— 读总内存／可用内存／swap，`suggest_workers()` 按「总内存÷`WORKER_RAM_GB`、可用内存÷`WORKER_RAM_GB`、核数」三者取低算出这台机器带得起的 `--workers`，可用内存 < `MIN_FREE_GB` 时退非零（`--workers auto` 是按核数开满 Chrome 的那个默认值） | `check_render_env.py [composition] [--json]`（`--json` 出 `{ok, workers, memory}` 给调用方直接消费） | 不渲染；不检查 HyperFrames 的其它 `HYPERFRAMES_*`；**不替 agent 决定要不要渲** —— 它只报这台机器能不能渲、该用几个 worker |
| `helpers/probe_env.py` | **能力报告，不做决定**：ffmpeg 滤镜（libass/drawtext）、字体与资产预算、残留 `hyperframes preview`/chrome 进程、font cache 可写性 | `probe_env.py [project] --json [--require libass --strict]`；默认退 0；`render.py` 在烧字幕前消费其中 libass 一项 | 不决定降级、不阻断渲染（缺 libass 由 `render.py` 按成片合同报错） |
| `helpers/check_motion_targets.py` | **手写 GSAP 时间轴的门禁**：时间轴里每个 selector 都命中、页面静态 `transform` 没被补间覆盖 | 「手写动效真的在演、页面位移没被 GSAP 吃掉」这一判据 | `check_motion_targets.py <project>` | 不判审美；有 `choreography.json` 的项目仍用 `check_parity.py` |
| `helpers/check_parity.py` | **审阅面／合成面一致性检查**：三条断言全确定性，可进自检 | 「spec 里声明的效果在两条路径都有实现、selector 真的命中」这一判据 | `check_parity.py <project>` | 不管渲染；不替代 `hyperframes check` |
| `helpers/state_fingerprint.py` | **工程态 ↔ 交付态的来源指纹**：让「这份交付是不是过期」变成可判定 | 「交付与当前工程态是否一致」这一判据；`capture`／`verify` 两个方向 | `state_fingerprint.py capture|verify <project> [-o 成品/delivery.json]` | **不是渲染前置**：过期是「需要重新输出」的信号，只拦发送 |

### 共享事实（唯一主人）

| 事实 | 唯一主人 | 其余模块的自由 |
|---|---|---|
| 源时间 → 输出时间映射 | `helpers/_edl.py`（`duration_record` / `render_record` / `select_render_record`）；**不含变速**——`speed` 由 `render_cut.py` 消费，`render.py` 拒收声明了 speed/mute 的 range | 删哪里、留哪里、是否用 `render_cut` 变速 |
| 最终可听见的混音 | `helpers/audio_mix.py`（人声/BGM/duck/响度）；`render.py` 的 loudnorm 只服务没有预混音的项目，用了 audio_mix 就 `--no-loudnorm`；`audio_fix.py --target-lufs` 只是素材预处理 | 人声处理、BGM 选择、ducking 参数、单条素材的阶段目标 |
| 页面保真或重排范围 | 具体页面/单元的制作意图（可按单元混用） | 同片部分保真、部分重排 |
| 输出来源与交付件 | 生成时记录的实际输入 + 显式交付清单（`state_fingerprint.py`；当前交付侧仍是显式清单，raw-deck 需手动登记来源） | 画幅、版本、字幕形态、输出组合 |

### 生产者（`helpers/` 里写盘的那些）

| module | 拥有什么 | 接口 | 不做什么 |
|---|---|---|---|
| `helpers/recompose_plan.py` | `recompose.json`、`recompose/lines.json` 的唯一写者；逐字行的 state/proposal | `init` / `check` / `lines`；inbox 调 `apply_record` | 不生成 composition、不导入页面、不跑 parity |
| `helpers/edl_from_keep.py` | **keep-list → edl.json 的唯一生产者**：每条保留区间按实测静音吸附边界（`_silence.measure`），可选从 transcripts 出 `cut_text.md` | `edl_from_keep.py keeps.json --edit-dir <edit> [--snap-tol/--no-snap/--transcripts]` | 不决定留哪句（那是作者的 keep list）；不渲染、不生成字幕 |
| `helpers/audio_mix.py` | **最终可听见混音的唯一生产者**：人声（+可选 BGM，sidechain duck）→ 交付响度（-14 LUFS / -1.5 dBTP） | `audio_mix.py <voice> -o <mix> [--bgm --bgm-lufs --target-lufs --tail]` | 不剪画面；不再做第二遍母带（用它的输出时 `render.py` 必须 `--no-loudnorm`） |
| `helpers/render.py` | **最终像素的唯一决定者**：逐段抽取（内容键缓存）、无损 concat、覆盖层与字幕合成、响度归一化（**成片响度标准 -14 LUFS / -1 dBTP / LRA 11，唯一主人；`audio_fix --target-lufs` 只是素材预处理**）；**`segment_durations.json` 的唯一写者**；每段读回校验与总长断言 | `render.py <edl.json> -o <out> [--preview/--draft/--no-cache/--no-subtitles/--no-loudnorm]` | 不判断内容；不决定要不要重渲 |
| `helpers/render_cut.py` | 带 `speed` / `mute` 的 EDL 渲成单个 MP4 | `render_cut.py <edl.json> -o <out>` | 不走覆盖层合成 |
| `helpers/timeline_derive.py` | **`timeline.json` 的唯一生产者**：EDL 实测 cue + `grouping.json` → 视觉步骤。**接受两种来源**：`measured`（实测段时长）与 `projected`（解析预演，工程态可审、不可交付）；**交付路径**的 measured 硬要求由 `validate_measured_bindings` 把关，不是这里 | `timeline_derive.py <edit_dir> --grouping … --output-timeline … [--alignment] [--stats]` | 不重新解析 SRT；不做创作分组 |
| `helpers/srt_export.py` | **输出时间轴 SRT 的唯一生产者**（article → line plan → lock → build → check）；`caption_words.json` 的写者 | `srt_export.py <edit_dir> --prepare／--lock／--build／--check` | 不认标称时间轴（渲染过期就拒） |
| `helpers/export_deliverables.py` | 把成片与 SRT 拷进 `成品/` | `export_deliverables.py <edit_dir> --out <dir>` | 不校验（那是 `verify_delivery`） |
| `helpers/edl_edit.py` | 脚本化改 EDL，每次删除必须带「时间区间=期望文本」 | `edl_edit.py <edit_dir> --delete …` | 不匹配就拒写；不猜词 |
| `helpers/apply_selection.py` | 把作者的词/停顿选择应用回 EDL。**只改 EDL，不渲染** —— 正式底片排在确认之后（第 5 步），不在收件时就出 | `apply_selection.py <edit_dir> …` | 不代替作者做选择 |
| `helpers/mirror_edl.py` | 从一条规范 EDL 派生另一机位的 EDL | `mirror_edl.py --offset …` | 符号定义在 `measure_offset.py` 那边 |
| `helpers/measure_offset.py` | 多机位偏移的量法（`offset = face − screen`） | `measure_offset.py <screen> <face>` | 不加偏移（加的是 `mirror_edl`） |
| `helpers/grade.py` | 调色预设与滤镜链 | 被 `render.py` 导入；也可单独调 | 不判断画面好不好 |
| `helpers/screen_detect.py` | 判定屏幕录制/UI 素材（要 stillimage 编码） | 被 `render.py` 导入 | 不改素材 |
| `helpers/audio_diag.py` | 口语质量诊断（闷/暗/刺/轻）——**下混单声道、只看说话段**，是诊断工具不是交付标准 | `audio_diag.py <inputs…> [--chart/--json]` | 不当交付判据（见 `GOTCHAS.md` #19） |
| `helpers/audio_fix.py` | 按诊断结果应用修复链并出 A/B 样本 | `audio_fix.py <input> -o <out> [--target-lufs --deess --ab]` | 不自动改交付件 |
| `helpers/transcribe.py` | 转写（Scribe / 方舟 / mlx 三后端，缓存键含音轨号） | `transcribe.py <video> [--backend]` | 不上传静音轨（峰值 < −60 dBFS 直接拒） |
| `helpers/transcribe_seedasr.py` | SeedASR 2.0 的流式转写（**正确的那条**） | `transcribe_seedasr.py <video> [<edit_dir>] [--edit-dir …]` | 不走 `doubao_asr_file.js` 的通用多模态路径 |
| `helpers/transcribe_batch.py` | 目录批量转写 | `transcribe_batch.py <videos_dir> [--workers N]` | 不合并结果 |
| `helpers/mlx_transcribe.py` | 本地 mlx-whisper 兜底 | `mlx_transcribe.py <video> [--edit-dir] [--language]` | 最后手段（会漂、丢标点） |
| `helpers/pack_transcripts.py` | 把逐字稿打包成 `takes_packed.md`（主要阅读视图） | `pack_transcripts.py --edit-dir <edit_dir>` | 不改转写内容 |
| `helpers/timeline_view.py` | 时间区间的胶片条 + 波形合成图 | `timeline_view.py <video> <start> <end> -o <png> [--n-frames]` | 不做判断 |
| `helpers/clean_edit_dir.py` | 交付后的工作区清理（首次先呈清单） | `clean_edit_dir.py <edit_dir> [--apply --approve]` | 不删重建所需的最小集 |
| `helpers/duration_plan.py` | **解析预演时间轴**：不渲一帧就把时间轴量化算出来 | `projected` 记录（工程态可审、不可交付） | `duration_plan.py <edit_dir>` | 不算交付证据；不替代实测渲染 |
| `helpers/import_srt_timeline.py` | **外部 SRT 路径的时间脊柱**：只有剪好的音频与 SRT 时用 | 「这份 SRT 与这份内容契约完成了对齐」这一证明；写 `timeline/timeline.json` | `import_srt_timeline.py <project> --srt … --alignment …` | 不证明 EDL 实测；不重新解析语义 |
| `helpers/align.py` | **卡点对齐**：把一个词／短句定位到输出时间轴的秒数 | 词 → 输出秒数的换算（`timeline` 与 `edit` 两侧共用） | 被 `timeline_derive.py` 等调用（库接口，非 CLI） | 不做创作分组；不写时间轴文件 |
| `helpers/doubao_asr_file.js` | **豆包 SeedASR 整文件转写**：`transcribe.py --backend` 可选的第二条 ASR 路径 | 输出 Scribe 兼容的 `{words:[…]}` 词表 | `node doubao_asr_file.js <input.raw|wav> <out.json> <offsetSec>` | 不做对齐、不写 EDL |

### 审阅与导出面

| module | 拥有什么 | 接口 | 不做什么 |
|---|---|---|---|
| `helpers/live_stage.py` | **活舞台的唯一主人**：为 `<project>/composition` 起 HyperFrames 预览服务，给出**可嵌入的裸 composition 路由**，并把地址写进 `edit/_engineering/live-stage.json`；路由的**双重证明**是「响应体有注入的 GSAP shim」**且**「它引用的资源真在本工程 `composition/` 里」——只验前者会认证到机器上另一个同名 `composition` 工程；`--status/--stop/--json` | `live_stage.py <project> [--port N] [--status] [--stop] [--json]`；退出码 0 起好·2 没有 composition·3 服务没起来或**不是本工程的** | 不渲任何帧；不改 composition；不管审阅页 —— 页面只消费它给出的地址 |
| `helpers/studio_notes.py` | **studio 意见的唯一落盘路径**：起只监听回环的收集器，把 composition 钩子截到的文本追加进 `edit/_engineering/studio-notes.jsonl`；`--tail/--clear/--stop` | `studio_notes.py <project> [--port 4319] [--tail N] [--json] [--clear] [--stop]` | 不解析 studio 的 prompt 格式（原样存，格式属于 HyperFrames，会变）；不判断意见是什么意思 |
| `helpers/check_review_template.py` | **审阅页模板的静态护栏**：九条不变量（S1 舞台选择函数保住参数／S2 可交互 id 都挂了事件／S3 默认舞台最不挑数据／S4 `readText` 都 optional／S5 字幕不退回整屏／S6 点一屏即播／S7 没有空壳自定义元素／S8 舞台提升不依赖初始化成败／**S9 调整项归属键只有一个出处**——写读键域分叉过一次，作者的画布改字被静默丢弃）；`--prove` 逐条把历史缺陷打回去自证不空洞 | `check_review_template.py [--template PATH] [--json] [--prove]` | **不证明页面能跑**。它钉的是这八类机械缺陷不会静默回来；新的**类**仍然要人撞到。别把绿灯读成「审阅页已验证」 |
| `helpers/build_review.py` | **一键构建统一审阅契约与控制台**：聚合剪接决策、演示动画与字幕资产，自适应匹配三大任务形态并生成 `review/review_data.json` 与 `review/index.html`；**活舞台资产预算的唯一主人** —— `fit_live_stage_assets()` 把超 `LIVE_STAGE_ASSET_MB`(4MB) 的 `liveStage.composition.assets` 换成 `review/proxies/<stem>.review.<ext>` 审阅副本（时长与原生像素不变）并登记进 `sourceManifest`，写 `composition.assetBytes` 与 `liveStage.budgetMs`；`audit_media_sizes()` 写 `media.sizes`（每通道 MB + `oversized`），页面据此在下载前拦下过大通道 | `build_review.py <project_or_edit_dir> [--mode auto/composite/speaker_only/animation_only] [--slices on/off/auto] [--no-review-copy]` | 不启动服务；不修改源素材；**不下采样审阅副本**（像素正是被审的东西）；代理不进 `edit/` 根 |
| `helpers/review_copy.py` | **审阅副本的唯一生产者**：同一条命令吃片子与**纯音频旁轨**；视频保原生像素、音频降单声道；断言「分辨率不变、时长不变、**结果确实变小了**」 | `review_copy.py <src> [--out] [--max-mb] [--crf] [--audio-kbps] [--gop N] [--force] [--json]`；`make()` 返回 `{size_mb, underBudget, kind, …}` | 不覆盖源片；不静默降采样。`--gop`**只给会被 `-c copy` 切片的副本**（`review_slices.py`）：每秒关键帧在屏幕轨上把同一个 CRF 29 从 2.6MB 抬到 10.0MB，不切片的副本传 `--gop 0` |
| `helpers/serve_review.py` | **公共审阅宿主的兼容入口**：先构建页面，再把 `review-surface.json` 交给 `planners-review-core`；Range、桥接、反馈、草稿与唤醒都由公共宿主负责 | `serve_review.py <project> [--port N] [--open]` | 不维护私有 HTTP 服务；不修改时间轴 |
| `helpers/export_video.py` | **统一成片导出深模块**：全自动化导出四大交付规格（composite, animation, speaker, split），内置 `/tmp` 云盘锁沙盒渲染、时序隐藏样式注入与单行药丸防折行保护 | `export_video.py <project> --mode {composite,animation,speaker,split} [--out-dir 成品]` | 不做粗剪决策（严格忠实于 EDL 与 timeline 实测数据） |
| `helpers/edl_preview_build.py` | 剪辑审阅页的 HTML（逐段取舍 + 逐字 + 时间轴），数据**构建时内联**（兼容保留） | `edl_preview_build.py <edit_dir>` | 不收集决定；页里的注入点由公共宿主替换 |
| `helpers/edl_review_surface.py` | 剪接预演**这一份 surface 的内容**（`dir`＝素材与剪辑目录的公共根）+ 业务前置 | `edl_review_surface.py <edit_dir> [--port N] [--no-open] [--surface-only]` | **不再自带 HTTP 服务**（宿主归公共缝）；`selections.json` 的整份覆盖语义由缝的 `write` 1:1 承担 |
| `helpers/visual_review_feedback.py` | 视觉审阅的**记录契约与唯一落盘路径**（`save_feedback`：先 `.tmp` 再 `os.replace`，旧内容进 `.previous/`）；缺件与过期审阅页副本的守卫 | `visual_review_feedback.py <project>`（只报缺件） | **不再带 HTTP 服务**（服务归公共缝）；不判断"批准算不算门" |
| `helpers/review_surface.py` | 视觉审阅面**这份 surface 的内容**（业务）：`surface_document`；建文档 → 交给公共件落盘 + 校验；`open_review` 里的缺件前置与 `--surface-only` | `review_surface.py <project> [--port] [--no-open] [--surface-only]` | **不实现宿主生命周期** —— 写/校验/起/判活/停都在 `planners-review-core/scripts/lib/review_host.py`（唯一一份）；不解释反馈形状 |
| `helpers/lib/planners_modules.py` | **找**公共模组（发布后按名字找兄弟目录）—— 只管解析路径，生命周期不在这里 | 被 `review_surface.py` 用来定位 `planners-review-core` | 不实现任何审阅或宿主逻辑 |
| `helpers/review_inbox.py` | **收件**：把 surface 声明的那一份提交文件翻译成 `feedback/<chapterId>.jsonl` 的追加（按内容哈希去重） | `review_inbox.py <project> [--dry-run]` | 不改本 Skill 的反馈形状去迁就宿主 |
| `visual/assets/review-page-template.html` | **统一视听审阅控制台模板**：HyperFrames 是新工程的唯一播放运行时；旧 SVG 才启用兼容动效引擎；页面承载播放、字幕、批注、反馈与重建提示 | 拷成 `<project>/review/index.html` | 不含项目私有数据；不在 HyperFrames 模式复制第二个时钟 |
| `visual/assets/svg-anim-engine.js` | **旧 SVG 审阅兼容驱动器**：在静态 SVG 舞台上即时预演 Step、原语、镜头与子延迟 | `VideoCraftAnimEngine.setStep(svgRoot, step, prevStep)` ／ `setChoreography(svgRoot, map)` | 不进入新 HyperFrames composition 的主时钟；不直接控制官方 player |
| `helpers/live_preview.py` | **把编译后的 composition 经 ReviewBridge 传进审阅页**（活舞台的工程传输） | 「不透明宿主下工程态怎么传」这一件事 | 被 `build_review.py`／活舞台调用（库接口） | 不做渲染；不提供 HTTP 服务（宿主归公共缝） |
| `helpers/preview_layers.py` | **给 EDL 里每个 alpha 覆盖层导出一份浏览器可合成的孪生件** | 「层能在审阅页里实时看」这一能力 | `preview_layers.py …`（已有外部透明视频层时才需要） | 不替代 `render_layer.py` 的最终产物 |
| `helpers/review_slices.py` | **把成片切成逐屏审阅片段**，让页面只加载一个窗口 | 审阅期按屏切片这条路径；`--slices` 的开关行为 | `review_slices.py …`（`build_review.py --slices` 会调） | 不改变时间轴；不生成交付件 |

### 视觉层（`visual/`）

| module | 拥有什么 | 接口 | 不做什么 |
|---|---|---|---|
| `visual/scripts/generate-composition.py` | **组成品骨架的唯一生产者**：一个 step 一个 clip、主题 token 内联进 `:root`、声音元素、时间轴提示；**声明了 `mediaClips` 的屏**（录屏/实拍）改发 `<video class="clip">` 并带 `data-media-start` —— 于是 composition 就是画面轨的**唯一源**，审阅与交付是同一份；随包拷 GSAP 与嵌入桥进 `composition/assets/`；`--verify` 的时间／尺寸／**父级穿越**闸门 | `generate-composition.py <project> [--theme] [--layout] [--audio] [--media-box x,y,w,h] [--verify]` | 不实现每个 clip 的视觉（那是 agent 写进 HTML）；**不写 `package.json`**；不替项目决定录屏落在哪 —— 落位由 `--media-box` 给 |
| `visual/assets/composition-embed-bridge.js` | **composition 自己的控制面**：被 iframe 时接 postMessage（`hello/seek/play/pause` → `ready/time`），让审阅页能演活的工程态。审阅页在不透明源 iframe 里够不着子页 DOM，这是唯一通道 | 由生成器拷进 `composition/assets/`；`window.__kwEmbedBridge` 幂等标记 | 非嵌入路径**一个字节都不影响**（`window.parent === window` 时第一行返回）；渲染时没人给它发消息 |
| `visual/assets/composition-studio-hook.js` | **studio 批注的采集钩子**：在 composition 内捕获作者在 studio 里画的批注，交给 `helpers/studio_notes.py` | 被 `generate-composition.py` 拷进 `composition/assets/`；studio 内运行时生效 | 不在渲染路径上；不存业务判断 |
| `visual/scripts/import_svg_page.py` | **画面页与动画层之间的唯一适配器**：逐字内联、只改图片 href 前缀、边界解析、`--audit`（可指名性提示；无 id 不失败；跨页 id 碰撞仍拦，因为它会让元素动效错绑）、`--prove`（往返未改坏） | `import_svg_page.py <project> [--pages] [--audit/--prove/--emit]` | **不改页面标记**、不改 id、不保证 composition 能渲染（那是 `hyperframes check`） |
| `visual/scripts/check_themes.py` | 主题库的判据：`theme.json` 可解析、必填 token、`var()` 链解析得掉、对比度、圆角刻度一致、无死节奏 token | `check_themes.py [themes_dir] [--json]` | 不判断风格好不好；不改主题文件 |
| `visual/scripts/encode_transparent.py` | 透明层的编码（PNG 序列 → MOV） | `encode_transparent.py <png_dir> -o <out> [--codec] [--fps]` | 不验证透明（那是 `check_alpha.py`） |
| `visual/scripts/align-visual-plan.py` | 把 `script.md` 的 Beat 对齐到实测 cue，产出 `visual-plan-alignment.json` | `align-visual-plan.py --plan <plan> --script <md> --edit-dir <dir> --output <json>` | 不替人处理 low/unmatched |
| `visual/scripts/scaffold.sh` | 立一个视觉层项目（`input/` `timeline/` `composition/` `.theme` `.layout`） | `scaffold.sh <target> [--theme] [--list-themes]` | **运行 `npx hyperframes init`**，那是 `package.json` 的来源；不生成画面 |
| `visual/themes/<id>/tokens.css` | **风格库的唯一数据**：颜色、字型、圆角刻度、性格旋钮、装饰 | 被 `generate-composition.py` 内联；被 `planners-ppt-hell` 的视频路线翻成 SVG 属性 | 不写章节 CSS；不含时长/缓动（节奏只由 `mood` 承载） |
| `visual/themes/<id>/theme.json` | 主题元数据（`id`／`mood`／`bestFor`／`preview`） | 被 `check_themes.py` 校验、被选主题时读 | 不写时长数值 |
| `visual/scripts/render_layer.py` | **把 composition 渲成 alpha 层**（HTML-first 的覆盖层路径） | 最终要独立透明视频时才用的那条产出路径（`.mov`；兼容旧媒体叠层可同出 `.webm`） | `render_layer.py …` | 不是整片渲染（整片走 `generate-composition.py` + `hyperframes render`） |
| `visual/scripts/auto_choreography.py` | **推导确定性的逐屏动画编排** | `timeline/choreography.json`（`check_parity.py` 的 spec 输入） | `auto_choreography.py <project>` | 不写 SVG 源；不决定视觉风格 |
| `visual/scripts/snapshot_input.py` | **严格只读的 workbench snapshot 解析**（所有 SVG 消费者的唯一入口） | 「这份 snapshot 能不能用、边界在哪」这一判据 | 库，无 CLI（被 `import_svg_page.py` / `build_review.py` 调用） | 不写项目内资产（那是 `import_svg_page.py`） |

### 数据、评测与历史

| module | 拥有什么 | 接口 | 不做什么 |
|---|---|---|---|
| `tests/` | **每条判据的可执行形态**（199 条） | `python -m unittest discover -s tests -p "test_*.py"` | 不是规格来源（规格在 Stage 文档与 contract） |
| `evals/evals.json` | 干净任务与 `must_do` / `must_not_do` | 人工或 Judge 跑 | 不是自动测试 |
| `skills/manim-video/`（含 `setup.sh`） | 随包的 manim 子 Skill（自绘逐帧那条路线的一个后端） | 走 manim 时读 | 不在默认运行路径上；唯一声明 Python 3.10+ 的地方 |
| `static/` | 展示用素材（banner、timeline-view SVG） | 人读 | 不参与运行 |
| `poster.html` | 项目的宣传页 | 人读 | 不参与运行 |
| `archive/` | 两个旧体系整份封存（见第 6 节） | **只读** | 不是运行入口；不往里写 |

表里成组的行，各自成组的理由：

- **判据十条各一行**：它们每条只声称一件事，互不蕴含，合成一行正好丢掉「哪个证明了什么」——而
  `GOTCHAS.md` #6 记的就是把这几件事混为一谈。**删除测试**：删掉任一条，它的判据没有别处承接
  （复杂度被集中，不是搬家）。
- **转录五条各一行**：它们是**同一条缝上的五个后端**（`transcribe.py` 分派），质量与代价不同，
  合起来会让人以为可以随便挑。`transcribe_seedasr.py` 是正确的那个（见 `GOTCHAS.md` #1）。
- **`visual/scripts/` 里的 `scaffold.sh` 与 `generate-composition.py` 分开**：前者立项目
  （含 `hyperframes init`，**`package.json` 归它**），后者写组成品骨架。这条分工是第 6 条问题的前提。

### depth 的三处对照

- **深**：`SKILL.md` 的「全链流程」——10 步之后是整条链的判断；`check_themes.py` 的接口只有
  「跑一下、退非零」，后面是 `theme.json` 解析、`var()` 链、对比度、刻度一致、死 token 五类判据。
- **深**：`import_svg_page.py` 的 `--prove` 只有两个字，后面是「只改哪一种属性、怎么自证、边界在哪」。
- **浅（有意）**：`references/capability-map.md` 是按表达目的列的能力表，读的人要自己拼——所以
  第 2、4 步必须给指向与顺序（`creative-direction.md` 干这件事），不能只丢一个文件名。

## 3. 缝与适配器

缝 = 谁交出什么、谁消费什么。四处跨 Skill 的缝，以及本 Skill 内部的几处。

### 3.1 上游 `video-idea-system` 的内容契约缝

- **谁交出什么**：`script.md`、`visual-plan.json`（契约 5.0）、`visual-blueprint.md`、
  `production-brief.md`、`assets/`，以及录制后做画面那一步的静态 SVG（`scenes/`）一起进 `input/`。
- **谁消费什么**：`video-story-handoff.md` 定接收口径；第 8 步把 Beat 对齐到实测 cue。
- **`script_hash` 两处都核，各管自己那一段**：交接包就是上游的 `deliverable/` 目录本身，
  里面 `visual-plan.json` 与 `script.md` 放在一起，所以**做画面那一步顺着契约所在目录就找得到**
  （`planners-ppt-hell` 的 `project_state.py` 找 `plan.parent/'script.md'`，一致 `ok`、不一致 `error`、
  找不到 `unchecked` 并明说「这不是核对通过」）。**它那一次来得及**——画面在录制前做，作者对着画面录；
  **本 Skill 这一次只能事后发现**（人已经录完），所以不符要**停下来问作者**，核不了就明说「无法核对」，
  不报成功。两处各改各段，不是分工重复。
  「口播不进做画面那一步」说的是**内容**：它不拿口播去判断画面该画什么。
  核对哈希不是把口播当输入读进来，两件事不矛盾。
- **没有 adapter，靠契约**：契约字段语义归上游（`video-plan-contract.md`），本 Skill 只读。

### 3.2 与画面那一侧的动画缝（adapter：`visual/scripts/import_svg_page.py`）

- **谁交出什么**：`planners-ppt-hell` 的视频路线交出 `_internal/02_svg_source/<page_key>.svg`
  （或随包的 `input/scenes/<page_key>.svg`），画布 `viewBox="0 0 1920 1080"`。
- **adapter 翻什么**：① 图片 href 前缀（页面写的是 `../00_project/…`，HyperFrames 会以
  `invalid_parent_traversal_in_asset_path` 拒绝）→ `assets/pages/<page_key>/<file>` 并拷进 composition；
  ② 只动 `<image>` 的 `href`/`xlink:href` 值，**页面其余一字不动**，用「写回去 == 源文件字节」自证。
- **谁读它**：`generate-composition.py`（内联进 clip）、以及独立跑 `--audit` 时的人。
- **两条可选约定（只在做元素级动效时成立）**：按 `id` 指名元素（DOM 序号在重渲后会静默错绑）；id 全片唯一
  （各屏内联进同一个 DOM，重复的 `#caption-1` 只命中第一屏——`audit_pages()` 报这个）。
  没有 id 的页面照样导入，作为整页画面使用；`--audit` 只报能力，不拦。
- **`--prove` 证明什么、不证明什么**：只证明**页面往返没被改坏**，不证明 composition 渲染得出来。
  后者归 `cd composition && npx hyperframes check`；`generate-composition.py --verify` 另外拦父级穿越。
- **为什么这是一个真 adapter 而不是多余的中间层**：翻译有两处以上消费者——`generate-composition.py`
  的内联路径、独立 `--audit`/`--prove` 路径、以及「页面原样留给它自己的 PPT 出口」这条要求。
  只有一处做翻译时该怀疑中间层，这里是三处。

### 3.3 风格库的两个消费者

- **来源唯一**：`visual/themes/<id>/tokens.css`。
- **消费者一**：本 Skill 的 `generate-composition.py` —— 把 `:root` **原样内联**进
  `composition/index.html`，成为 HTML 动效层的 `var(--…)`。
- **消费者二**：`planners-ppt-hell` 的视频路线 —— 把同一批 token **翻成 SVG 的显式属性**
  （颜色落 `fill`/`stroke`，字体落 `font-family`，圆角落 `rx`）贴到静态画面上。
- **谁都不复制第二份**：ppt-hell 侧只通过它自己的 `theme_tokens.py` 读。改主题只改这里，两边一起改。
- **判据在** `visual/scripts/check_themes.py`（见第 5 节）。

### 3.4 两个审阅面（**故意不互操作**）

- **本 Skill 的视觉审阅**：约定 `<project>/review/index.html` + `<project>/timeline/timeline.json`，
  由**公共缝的宿主**服务（有插件 → DSH 侧栏；没有 → `serve-review.mjs`），审阅面是
  `review/review-surface.json`；页面先写 surface 声明的提交文件，`review_inbox.py` 收件时
  翻译成 `feedback/<chapterId>.jsonl` 追加。Range、资产桥、草稿与唤醒不在本 Skill 再实现。
- **另一套在** `<项目>/_idea/reviews/script/`，属于 `video-idea-system`（念稿审阅：左口播、右样张、下双反馈）。
- **为什么分开**：审的是两件事——这一套审**剪辑与画面**，那一套审**稿子与内容契约**。作者已裁定不合并。
- **什么时候交棒**：稿子或逐屏上屏文字要改 → 回 `video-idea-system`；剪点取舍与画面节奏要改 → 本页；
  两边都要改 → 先回上游定稿与契约，再回本页。表在 `review-ui.md` 开头。
- **接缝行为**：把本页的服务指向只装了 idea 审阅页的项目会**报错退出**（要那两个文件，退出码 2）——
  正确行为，不端出旧项目。

### 3.5 本 Skill 内部的缝

- **EDL → 实测时长 → 字幕/时间轴**：`render.py` 写 `segment_durations.json`（含 EDL 哈希），
  `srt_export.py` 与 `timeline_derive.py` 读它。标称时间轴上的 cue 最多早一秒，所以派生器只认
  `measured` 与 `projected` 两种来源；`projected`（解析预演）足以支撑工程态审阅与字幕，
  **但不算交付证据**——`_edl.render_record` 默认跳过它，交付前必须按实测重渲并重建字幕。
  把 `projected` 挡在门外的是**交付路径**（`validate_measured_bindings`），不是派生器本身。
- **稿件 → 契约 → 画面**：上游的缝（3.1）。
- **产出者 → 判据**：`render.py` 产像素，`verify_av.py` 判轨与尾，`verify_delivery.py` 判交付副本。
  **写的人不当法官**是故意的。
- **人 → 机器**：审阅页把作者的意见绑到当时的版本（反馈 JSONL + 旧版本留底）。

### 3.6 审阅页 ↔ 活 composition（跨源，只能 postMessage）

审阅页跑在 `sandbox="allow-scripts"` 的**不透明源** iframe 里（GOTCHA #53），拿不到被嵌入 composition 的 DOM，`contentWindow` 一碰就跨源。所以这条缝只有 postMessage，而且协议必须**随 composition 走**：它是那份文件自己的控制面，也只有它在场才知道自己的时间轴。真缝 —— 消费者是两个（审阅页、将来的任何驱动方）。

地址不自己拼：`live_stage.py` 探出来（studio 的 hash 路由不可嵌；裸路由只出现在 studio 自己的 bundle 里）。证明分两层：**「响应体里有没有注入的 GSAP shim」证明它是 composition**（这台服务器对未知路径一律回 200 + SPA，看状态码什么都证明不了）；**「它引用的资源是否真在本工程 `composition/` 里」证明它是本工程的** —— 机器上两个同名 `composition` 会注册成同一个 project id，`--status` 报的是先应答的那一台，只验第一层就会把别人的工程认证成自己的（2026-10-15 撞上过一次：错误晚到 `build_review` 才以 `Missing or escaping composition asset: assets/pages/beat-01/….jpg` 冒出来）。

### 3.7 studio 的意见回传（同源钩子 → 本地收集器）

studio 的「Describe a change to the agent」只调 `navigator.clipboard.writeText`，不写任何文件。
我们不改 HyperFrames：studio 把 composition 装在 `<hyperframes-player>` 的 shadow iframe 里，
而那个 iframe 带 `allow-same-origin`（**在跑着的 studio 上实测过**），所以 composition ——
**它是我们的文件** —— 与 studio 同源，能包住父页的 `writeText`：剪贴板照旧写，同时 POST 给
`studio_notes.py`。钩子必须在**内联脚本**里（player 路由会剥掉所有 `src=` 脚本），并且并进
动画那一块（runtime 把内联脚本拼成一个大脚本执行，单独那段排在动画之后，前面一抛错就轮不到它）。

## 4. 与相邻 Skill 的关系

| 相邻方 | 它给本 Skill 什么 | 本 Skill 给它什么 | 什么不归本 Skill |
|---|---|---|---|
| `video-idea-system`（上游） | `script.md`、`visual-plan.json`、`assets/`、制作说明、念稿审阅记录 | 内容契约落地时发现的技术缺口；不符 `script_hash` 时的**停手与追问作者**（结论停在作者那里，不飞回上游）。注意它下游做画面那一步**也核** `script_hash`——那一次在录制前，来得及 | 不写稿、不改上屏文字、不做发散与主张 |
| `planners-ppt-hell`（视频路线，上游的画面） | 静态 SVG 页（`_internal/02_svg_source/` 或 `input/scenes/`） | 三个合成事实的字段契约、导入器、可选 id 指引、`--audit` 的能力/碰撞报告 | 不画画面、不改页面、不决定风格怎么落；无 id 页面按整页使用 |
| `hyperframes` | 组成品的运行时与校验器（`check` / `render` / `preview`） | `composition/index.html` 的骨架与内联页面 | 不是本 Skill 的一部分；它的 CLI 行为变化属于外部工具那一类 gotcha |
| `02-skills-library/.venv` | 共用解释器（3.9.6，依赖齐） | — | 不由本 Skill 维护 |
| 作者（人） | 目标、决定、录音、逐屏反馈 | 可审的样片、剪接审阅页、视觉审阅页、成片与 SRT | 不替作者确认策略、不替作者念稿、不替作者批准 |

## 5. 同一件事的两个真相源要单独标出

分开是故意的；每条都说清谁读谁、谁不读谁。

### 5.1 `segment_durations.json` 的键（累积 vs 当前）

- **它是什么**：`render.py` 按**输出名**把每次渲染记进去，键会累积（`poc` / `draft` / `mix-base` / `final`）。
- **唯一写者**：`helpers/render.py`。每个键里带 `durations`、`total_s`、`edl_sha256`、`fps`。
- **谁读**：`srt_export.py`（字幕时间轴）、`verify_av.py`、`check_edl.py`、`verify_delivery.py`。
- **按什么选**：`helpers/_edl.py` 的 `select_render_record()` —— **按当前 EDL 的 `edl_sha256` 选**，
  历史键保留给人和回溯，**不参与判定**。`digest`／`mismatch`／`no-digest`／`none` 四种结果各有措辞。
- **为什么不删历史键**：它们是「这一版渲过什么」的记录；删掉会让回溯失效。而按位置选第一条正是
  P-28 那个假 FAIL 的根因（读到 `poc` 的 12 秒去判一条 84 秒的成片）。
- **改键策略要动**：`_edl.select_render_record` 一处；读者不用改（都经它选）。见第 6 节。

### 5.2 `themes.md` 的契约 ↔ `check_themes.py` 的判据

- `references/themes.md` 写**语义**（谁读它、必填项、圆角刻度、可选性格覆盖、创作步骤）；
  `visual/scripts/check_themes.py` 执行它。
- **两者对不上的地方就是 bug**。改任一处要同时看另一处，尤其：
  - **必填 token 名单**（`check_themes.py:REQUIRED_TOKENS` ↔ `themes.md` 的「必填」几节）；
  - **圆角刻度六个值**（`RADIUS_SCALE` ↔ `themes.md` 的「圆角刻度」表）；
  - **对比度**：`ENFORCED_CONTRAST`（`--text`/`--text-2`/`--text-mute` 判 4.5）与
    `REPORTED_CONTRAST`（`--text-faint` **不设阈值**，只报实测）↔ `themes.md` 的「文字」表与那几条规则。
- **一条已经踩过的坑**：文档写着 `--text-faint`「仍然要可读」，判据把它测出来却永不失败——
  「一个都没过」被显示成「0 failing」。现在两边说同一件事：提示/禁用档**没有数字底线**。

### 5.3 `SKILL.md` 的「全链流程」↔ 各 reference

- `SKILL.md` 的「全链流程」是**模块表的摘要**，写到「一眼能不能看出这一步没做完」为止：
  这一步做什么、主要产物是什么、怎么一眼看出没做完。
- **完整的完成标准只住在那个 module 自己的文档里**（第 1–4 步在 `content-to-production.md`，
  时间脊柱在 `visual-timeline.md`，画面在 `composition-craft.md`，字幕在 `caption-article-first.md`）。
- 两处都写全，就又造了一个真相源。改完成标准时**改 reference**，`SKILL.md` 只在「一眼判据」变了时才动。

### 5.4 `timeline/grouping.json` ↔ `timeline/timeline.json`

- **`grouping.json` 是创作决定**（人写）：Step 分组、`screenIntent` / `visualModel` /
  `modelStructure` / `onScreenTextRule` / `assetNeeds` / `sourceBlueprintId`，以及 `sourcePageKey`
  与三个合成事实的单屏例外。**不能从 EDL 推出来**。
- **`timeline.json` 是派生结果**（机写）：`timeline_derive.py` 把 EDL 的实测 cue 与 grouping 合起来，
  算出每个 Step 的 `startMs`／`endMs`／`durationMs`／`caption`，并保留 EDL 绑定
  （`cueIndices` / `segments` / `sourceRange`）。
- **谁读谁**：`generate-composition.py` 只读 `timeline.json`（`data-start`/`data-duration` 从它来）；
  人只读 `grouping.json` 与 `storyboard.md`。**改时间要改 grouping 再重派生**，不许手改 clip 属性。
- **为什么不合成一个文件**：一个是创作输入（会被反复改），一个是派生结果（必须与实测一致）。
  合成会让「改设计」和「改实测」共用一条路径，而后者是不许手改的。

### 5.5 画面轨的唯一源：`composition/`

- **唯一源**：`composition/`（含录屏 `<video>`）。审阅页演的是它的**活播放**，交付是它的**一次渲染** —— 同一份东西，不是两份。
- **谁不构成源**：任何 draft 渲染、审阅副本、`_engineering/` 里的中间视频。它们可以存在，但**不得**被声明成页面或交付的输入（`review/media.json` 声明 `compositeVideo` 指向渲染物时，活舞台掉线就会给出一个过期的画面）。
- **改一处要动**：`timeline/timeline.json`（步与 `mediaClips`）→ `generate-composition.py` → `build_review.py`。落位（比如左侧留白给人物轨的 `620,0,1300,1080`）由 `--media-box` 给，不写死在生成器里。
- **旁白算不算 composition 的一部分**：算 —— 审阅时**必须能听见**，否则没法判音画同步。但交付的**画面轨是无声的**（声音归人物轨），所以渲染画面轨时要显式去掉音轨（`-an`）。生成器的 `--audio` 就是给这个用的；没有它 studio 与活舞台都是哑的（那条 `warn: no <audio> element` 一直在提醒）。
- **已踩过**：composition 用旧的 shifted 时间轴打过补丁，而时间轴已改成对齐版 —— composition 过期 3 秒，**没有任何检查发现**。这是第 56 条 GOTCHA 的第二条轴（来源版本），目前仍靠人。

## 6. 动了 X 会牵连什么

### 6.1 改主题 token 的必填集

| 要动 | 为什么 |
|---|---|
| `visual/scripts/check_themes.py` 的 `REQUIRED_TOKENS` / `RADIUS_SCALE` / `ENFORCED_CONTRAST` | 判据的唯一处 |
| `references/themes.md` 的「必填」几节与「文字」表 | 语义的唯一处；与判据必须一致 |
| 23 套 `visual/themes/*/tokens.css` | 新增必填项会让**全部主题**立刻失败——要么 23 套都补，要么先放宽判据 |
| `tests/test_themes.py` 的真实库用例 | 它按 `ENFORCED_CONTRAST` / `RADIUS_SCALE` 逐套跑，会跟着红 |
| `planners-ppt-hell` 的 `scripts/style/theme_tokens.py` | **跨 Skill**：它按 token 名读，认不出的会报出来。新增必填项要同时改它那边的 `references/architecture.md`（模块表里 `theme_tokens.py` 那一行）与 `references/workflow/03_video_route.md`（视频路线怎么用风格库） |

**不要**为了通过旧主题而把判据改回 `notes`：那正是 `--text-mute` 那一档原本的毛病（永远不可能不合格）。

### 6.2 改 `segment_durations.json` 的键策略

| 要动 | 为什么 |
|---|---|
| `helpers/render.py` 的写入处（`blob[clips_tag] = {...}`） | 新键要带 `edl_sha256`，否则选择器只能退到 `no-digest` |
| `helpers/_edl.py` 的 `select_render_record()` | **唯一的选择口**；四个读者都经它，所以这里改一处就够 |
| 四个读者的措辞：`srt_export.py` / `verify_av.py` / `check_edl.py` / `verify_delivery.py` | `mismatch` 与 `no-digest` 要各自说人话，不能都说「可能被截断」 |
| `tests/test_render_record.py` + `tests/test_edit_contracts.py` 的 `write_measured()` | 它们构造这个文件 |

**牵连面**：字幕时间轴也读它。键策略一改，**已交付项目的字幕对齐**仍按旧键活着（历史键不删），
但新渲染的字幕会走新规则——所以改它要当作一次迁移，不是一次改名。

### 6.3 改导入器的 href 改写规则

| 要动 | 为什么 |
|---|---|
| `visual/scripts/import_svg_page.py` 的 `_inline_image_hrefs()`（只动 `<image>` 的值） | 逐字保真的边界就在这里；一放宽就可能在别处改到页面 |
| `plan_href_targets()` / `href_boundary()` | 决定资源拷到哪、边界在哪 |
| `generate-composition.py` 的父级穿越闸门（`verify()`） | 它断言「只出现根相对路径」，规则一变要么跟着改要么失效 |
| `tests/test_svg_page_import.py` 的逐字保真 / 只动 image href / 三种边界用例 | 这些是这条规则的回归 |
| `references/composition-craft.md` 的交接节 + `import_svg_page.py` 的 docstring | 两侧的措辞（含 `--prove` 证明范围的说明） |

**牵连面**：`planners-ppt-hell` 的视频路线依赖「页面保留自己的相对 href」这一条（它的 PPT 出口要那条路径）。
落点在它那边的 `references/workflow/03_video_route.md` 的「交出什么：给动画层的交接」那两条
（图片 href 保持页面的相对形式；导入时的前缀改写归导入器），以及 `references/architecture.md` 的缝 2。
改改写规则**不能**要求页面改 href——那是违约。

### 6.4 改 `review/` 目录约定

| 要动 | 为什么 |
|---|---|
| `helpers/review_surface.py` 的 surface 声明与宿主身份判据 | `dir` 取项目根（页面在 `review/`，时间轴在 `timeline/`）；身份靠 `watch` 文件逐字节比对 |
| `visual/assets/review-page-template.html` | 页面里的 `rel` 相对 `dir`（项目根），`base: '../'` 补页面与 `dir` 差的那一级；注入点是**裸着独占一行**的双花括号标记（不能放进 `src=""`，也不能塞进 `<script>` 里） |
| `references/review-ui.md`（约定、反馈 schema、交棒表） | 语义的唯一处 |
| `SKILL.md` 的「文件与参考入口」与第 6/10 步 | 让人找得到这两个目录 |

**牵连面**：`video-idea-system` 的念稿审阅页在 `<项目>/_idea/reviews/script/`，**两套不合并**。
落点在它那边的 `references/architecture.md` 的「两个审阅面（故意不互操作）」一节、
`stages/05-read-aloud-review-and-handoff.md`，以及生成那一页的
`scripts/start-read-aloud-review.mjs` 与 `assets/read-aloud-review.html`。
改本页的约定要让交棒表跟着改，否则下一轮会有人试图让一个服务打开另一方的页面。

### 6.5 改渲染前的预检（以及为什么没有 `prerender` 钩子）

| 要动 | 为什么 |
|---|---|
| `helpers/check_render_env.py` | 环境判据的唯一处（字体缓存真的写一个探针文件、Node ≥ 22、composition 在、**RAM / 可用内存 / swap 与建议的 `--workers`**）。`--workers auto` 按核数开满 Chrome，是本 Skill 里唯一一个「失败会带走整台机器而不是一次渲染」的默认值，所以这台机器的判据在这里，不在文档里 |
| `SKILL.md` 第 7 步的 HyperFrames 说明 | 它是**流程里的一步**，所以要在流程里可见 |
| `references/visual-rendering.md` 的 Render 节 | 渲染的人读那里 |
| `references/tools.md` 的渲染节 | 渲染的人从那里照着跑 |
| `install.md` 的冷启动提醒 | 装机器的人读那里 |
| `tests/test_render_env.py` | 它的回归 |

**为什么它是「必须跑的检查」而不是自动闸门——查过了**：`generate-composition.py` **不写也不更新**
`composition/package.json`（它只写 `index.html`、拷 `assets/`、写 `pages/manifest.json`，全文没有一处引用它）。
那个文件由 `npx hyperframes init` 写（`scaffold.sh` 调它），里面是 `dev`/`check`/`render`/`publish`
四个脚本（**`package.json` 归 `scaffold.sh` / `hyperframes init`，不归生成器**）。要挂 `prerender`
钩子就得让生成器去改一个它不拥有的文件，而且：

1. 钩子里要写死本 Skill 的绝对路径——Skill 一搬家，`npm run render` 会因为找不到 python 而**整个失败**，
   报的还是一个跟渲染无关的错；
2. 它只覆盖 `npm run render` 一条路。**变形那一路是直接调 `npx hyperframes render`**
   （`visual-rendering.md` 的 alpha 变体），不经过 npm——闸门会给人「已经保住了」的错觉，
   而那正是本 Skill 反复在治的那种「一个绿灯不等于另一个性质成立」；
3. 再跑一次 `hyperframes init`（或 `hyperframes upgrade`）会把它悄悄冲掉。

所以：**写成必须跑的一步**，在 `SKILL.md` 第 7 步、`references/visual-rendering.md`、`references/tools.md` 的渲染节与 `install.md` 四处点名。
哪天真要把 `package.json` 收进本 Skill（由 `scaffold.sh` 在 init 之后补钩子，并让 alpha 变体也走 npm），
那是一次**边界变更**，要先在这里登记。

## 7. 退役

| 已退役的东西 | 现在的状态 | 为什么这样处理 |
|---|---|---|
| `archive/web-video-presentation/` | 整份封存在 `archive/`，**只读** | 它是 v1 的视觉层创作面（React 章节、`base.css`、模板库、审阅环），v2 的组成品与主题都从这里长出来。**不删**：`upstream-diff.md` 的每一条「故意偏离了什么」都要能回指到它；主题的圆角刻度、装饰层写法也是从它的 `base.css` 抄回来的。删掉等于把「为什么是现在这样」的证据删掉 |
| `archive/video-use/` | 整份封存在 `archive/`，**只读** | 它是时间脊柱、合成器、字幕链、交付校验的来源。**不删**：`GOTCHAS.md` 里若干条的现场在它里面；`upstream-diff.md` 记着吸收到哪个 commit。**唯一一处例外**：`helpers/doubao_asr_file.js` 里内联的豆包凭据字面量已脱敏为环境变量（2026-09-26 安全修复，理由见 `upstream-diff.md`）；除此之外逐字节冻结 |
| `tests/test_interactive_ui.py` | 已删除 | 它不是 unittest（没有 `TestCase`），硬编码 `127.0.0.1:8776`，引用的 `#view-player-btn`／`#view-svg-btn` 在模板里已 0 次，且 `playwright` 没装 —— 整个模块导入即失败，把 `unittest discover` 直接拖成 ERROR。它测的元素已经不存在，装上 playwright 也会崩 |
| 模板里的 `<hyperframes-player id="player">` | 已删除 | 声明了却没有任何地方 `customElements.define` 或使用它（空壳）。它让人以为「活舞台已经有了」，真实情况是位置留着、里面是空的。活舞台现在是真的：`#live-stage-wrap` + `composition-embed-bridge.js` |
| CDN 的 GSAP（`cdn.jsdelivr.net/.../gsap.min.js`） | 改为随包 `visual/assets/vendor/gsap-3.14.2.min.js`，生成器拷进 `composition/assets/` | 渲染不该依赖网络；审阅页跑在信任围栏里，外链会被打回。版本写进文件名以便追溯 |
| `tests/test_snapshot_input.py` 里按路径加载隔壁 Skill 模块 | 补上它自己的 `scripts/` 到 `sys.path` | 不补就 `No module named 'canvas_frame'`，整个模块被跳过而无人发现 —— 自检于是常年带着一个 ERROR |
| `archive/parse-srt.py` 与 `timecode-map.json` 那条路 | 被 `timeline_derive.py` 取代 | 重新解析 SRT 会丢掉 EDL 本来就知道的东西；退役是在**逐字节相同的组成品骨架**上验收的 |
| `archive/web-video-presentation` 的 `evals/` 与其他 v1 副本 | 随旧体系一起封存 | 运行路径上不再有消费者 |
| 旧解释器口径：`uv sync`、`<skill>/.venv`、`uv run` | **已从 `SKILL.md` / `README.md` / `install.md` / `review-ui.md` / `themes.md` 清掉** | 本机没有 `uv`，那个 venv 是空的；统一用 `02-skills-library/.venv/bin/python`（3.9.6）。旧句子的残留会让人照着一个跑不了的命令做 |
| Python ≥ 3.10 的声明 | 改成**实测下限 3.9.6**（`pyproject.toml` 同步） | 核实过运行路径里没有 3.10+ 语法；唯一保留的 3.10+ 是随包的 `skills/manim-video/`（Manim 自身的要求） |
| 画面页的「用 DOM 序号指名元素」 | 改成**按 `id`**，且 id 全片唯一 | 重渲时多一个元素就会静默错绑 |
| `--dur-*` / `--ease-*` token | 从 23 套主题删除，`check_themes.py` 拒绝 | 零消费者，且会把 tween 引向按主题计时而不是按口播计时；节奏只由 `theme.json` 的 `mood` 承载 |
| HyperFrames 的 `doctor` 当环境自检 | 补上 `check_render_env.py` | `doctor` 的九项**不含**字体缓存可写性，而那是受限沙箱下 `render` 中途 `EPERM` 的原因 |

## 8. 读这份之后应该能回答

```text
□ 一个没参与设计的人，只看 SKILL.md，能不能说出整条流程有哪几步、每步产出什么、什么算做完？
□ 每个 module 的作用、接口和「不做什么」，能不能在 Skill 里读到？
□ 跨 module／跨 Skill 的缝，能不能读到「谁交出什么、谁消费什么」？
□ 一条新 gotcha 该记在哪、一次优化该动哪个 module，能不能读到？
```

答不上来时缺的是 writing，不是功能。gotcha 的候选与升级分在两个地方：`GOTCHAS.md`（Skill 根）与
`references/maintenance-history.md`。

### 已知没量过的地方（登记在此）

- **`edit/timeline/` 与 `<视觉层项目根>/timeline/` 的落点没有统一口径**：`SKILL.md` 的「文件与参考入口」把
  `grouping.json` 画在 `edit/timeline/` 下，而 `scaffold.sh` 把 `timeline/` 建在组成品项目根
  （`<target>/timeline/`）。两处同名、位置不同——`generate-composition.py` 只认后者（`<project>/timeline/timeline.json`）。
  真实项目里出现过两个目录分开的情况。**没有做删除测试**，也没统一，登记在这里等一次重构时量。
- **审阅那一块的 depth 没做过删除测试**：两个审阅面已裁定不合并，短期没有做测试的空间。

## 9. 相邻 Skill 的架构文档

这份只写本 Skill 内部的 module。接缝的另一端在别处——**改缝之前先读对面那一份**：

| 相邻 | 它的架构文档 | 与本 Skill 的缝 |
|---|---|---|
| `video-idea-system` | `02-content-assembly/video-idea-system/references/architecture.md` | 它交出 `script.md` + `visual-plan.json`（契约 5.0）+ `assets/` + 制作说明，录制后把做画面那一步的静态 SVG 一并放进 `input/`；本 Skill 消费这些，把 Beat 对到实测 cue。**`script_hash` 两处都核**：它下游那一步在录制前顺着契约所在目录核（**来得及**），本 Skill 在录制后核（**只能事后发现**） |
| `planners-ppt-hell` | `03-design-delivery/planners-ppt-hell/references/architecture.md` | 它的视频路线交出 `_internal/02_svg_source/<page_key>.svg`（或随包的 `input/scenes/`），页面保留自己的相对 href、可能被强调的元素带**全片唯一**的 `id`；本 Skill 的导入器逐字内联、只改图片 href 前缀、按 `id` 指名，并把三个合成事实的**键名**出版给它写 |
| `video-craft` | （本 Skill） | — |

**不是相邻 Skill 的那个**：`hyperframes` 是外部工具，不是这三份架构文档里的邻居。它的 CLI 行为
（`--help` 的话不算证据、`doctor` 不查字体缓存）在本 Skill 这边表现为缝上的假设，记在 `GOTCHAS.md`
的 #23 与 #31。
