---
name: web-video-presentation
description: 把已剪好的音频 + .srt 字幕 + 素材制作成帧级精确、带音轨、可重复渲染的视频；也能接收 Video Story System 的内容层视觉信息契约，在保持蓝图与 Speech Beat 一一对应的前提下，自主提出画面模型、排版、Visual Step、动画状态和精确时间设计，并通过独立的 Storyboard 与逐画面反馈完成确认。默认工作流是输入验收 → Beat/SRT 对齐 → 内容承载与视觉方案 → HyperFrames 开发 → 逐画面反馈 → Timing Lock → 确定性渲染。适用于动态知识画面、资料型视频、音频驱动动画、字幕严格对轨和 video-use 剪辑交接；无 SRT 时才使用 legacy 分支。
---

# Web Video Presentation (v2)

把 **已剪好的音频 + SRT 字幕 + 素材** 做成**可确定性渲染成片的视频**。
SRT 是唯一时间真相源。最终输出是 HyperFrames 组成品渲染的 mp4——不再
需要录屏。

核心设计：**单一视觉真相源 = `composition/index.html`（HyperFrames 组成品）**；
React 网页不再实现最终视觉，只承担逐 step 反馈（内嵌 `<hyperframes-player>`）；
音频内嵌 `<audio>`，SRT 对轨在渲染时就精确。

## 与 Video Story System 的层级

`video-story-system` 交付内容层契约：问题、画面上必须出现的对象/事实/数字、必须表达的语义事实、固定文字和证据来源。
本 Skill 交付表达层方案：如何选择视觉模型、如何组织空间、如何排版、如何拆 Visual Step、哪些状态渐进出现、怎样与口播同步，以及最终如何实现和渲染。

上游蓝图不是设计稿，也不是“左边放什么、右边放什么”的指令。本 Skill 不得把上游内容改写成新的理论；如果内容无法被当前画面准确表达，先在 Storyboard Review 暴露缺口，再决定回退上游还是重做下游模型。

## 核心产物

```
my-video/
├── input/
│   ├── audio.mp3              # 可选：用户已剪好的音频（handoff 时自动生成）
│   ├── subtitles.srt          # 必需：主时间源（handoff 时自动生成句子级 SRT）
│   ├── script.md              # 可选：内容参考，不改时间
│   ├── visual-plan.json       # 可选：Video Story System 机器契约
│   ├── visual-blueprint.md    # 可选：视觉计划人读版
│   └── assets/                # 可选：图片 / 截图 / 视频帧 / 品牌素材
├── timeline/
│   ├── timecode-map.json      # SRT 原始解析结果
│   ├── visual-plan-alignment.json # 可选：Beat/SRT 候选对齐与异常
│   ├── grouping.json          # 人/agent 确认后的 SRT 行 → visual step 分组
│   ├── timeline.json          # 项目级 step 真相源（start/end/duration/caption…）
│   └── storyboard.md          # 人读版画面计划
├── composition/               # HyperFrames 项目（唯一视觉真相源）
│   ├── index.html             # 生成器产骨架 + agent 实现视觉
│   ├── package.json           # pin 的 hyperframes CLI 版本
│   └── renders/*.mp4          # 渲染产物
├── review/index.html          # 静态反馈页（内嵌播放器，模板在 assets/）
└── feedback/*.jsonl           # 每条反馈绑定 chapter + step + srtRange
```

## 工作流

```
Phase 0  输入验收
  确认 .srt；收集已剪音频、脚本、素材。
  分支 A：普通输入 —— 用户提供 srt + 音频。
  分支 B：video-use 过渡 —— 输入是 video-use 的 <videos_dir>/edit/，
    运行 scripts/video-use-handoff.py 组装 input/（音频提取 +
    句子级 SRT + 可选抽帧）。见下方「video-use 过渡」。
  没有 SRT 才走 legacy。
  ▼
Phase 1  SRT 解析与时间线建模
  parse-srt → timecode-map.json
  ▼
Phase 1.5  Video Story 内容蓝图导入（有 visual-plan.json 时）
  Speech Beat 对齐 SRT → 每张逐段蓝图得到自己的候选范围 → 人工处理歧义
  ▼
Phase 2  视觉 step 切分与 storyboard
  SRT 行按语义合并为 visual step；生成 grouping / timeline / storyboard
  ▼
[Checkpoint Plan]  必须停
  打开 ?review=storyboard（或 review 页 storyboard 模式）；用户确认
  分组、模型化画面、素材策略、主题、开发模式
  ▼
Phase 3  组成品开发（HyperFrames）
  scaffold.sh 建 composition/（hyperframes init，pin 版本）
  generate-composition.py 生成骨架：每 step 一个 clip、时长来自
  timeline.json、theme tokens 内联、<audio> 内嵌
  agent 按 COMPOSITION-CRAFT.md 逐章实现视觉；每章后 npm run check
  ▼
[Checkpoint Review]  必须停
  review 页内嵌 <hyperframes-player> 逐帧暂停打反馈；schema 不变
  ▼
Phase 4  Timing Lock
  生成器 --verify 对账 + npm run check + 音频覆盖 + 反馈清零
  ▼
Phase 5  渲染输出
  cd composition && npm run render → ffprobe 验证 → 用户验收
  详见 RENDERING.md
```

## 阶段读取指南

| 阶段 | 必读 | 按需 |
|---|---|---|
| Phase 0-2 | `references/SRT-TIMELINE.md` + `references/MEDIA-FIRST.md` | 有`visual-plan.json`时必须读`references/VIDEO-STORY-HANDOFF.md`；按需读`references/STORYBOARD-FORMAT.md` |
| Phase 0 分支 B | `scripts/video-use-handoff.py`（运行）+ video-use 侧 `helpers/srt_export.py` | —— |
| 选主题 | `themes/*/theme.json` 动态读取 | `references/THEMES.md` |
| Phase 3 | `references/COMPOSITION-CRAFT.md` + `/hyperframes-core` + `/hyperframes-animation` | —— |
| Review | `references/REVIEW-UI.md` + `assets/review-page-template.html` | —— |
| Timing Lock / 渲染 | `references/TIMING-LOCK.md` + `references/RENDERING.md` | —— |
| 无 SRT fallback | `archive/legacy-tts/references/SCRIPT-STYLE.md` + `archive/legacy-tts/references/AUDIO.md` | `archive/legacy-tts/templates/scripts/tts-providers/README.md` |
| 旧 React pipeline | `archive/legacy-recording/`（老项目维护时） | `archive/legacy-recording/EXAMPLES/`（v1-era 结构 anchor，勿抄代码） |

## Phase 0 输入验收

默认要求 `.srt` 或 video-use 输出。已剪音频、原脚本、文章、素材都可以
作为参考，但不得改变 SRT 时间码。

若输入来自 Video Story System，把`visual-plan.json`、`visual-blueprint.md`和`assets/`一起复制到`input/`。v4 蓝图只说明必须呈现的内容；本 Skill 负责把内容转成画面与动画设计。在普通语义分组前运行：

```bash
python3 scripts/align-visual-plan.py \
  --plan input/visual-plan.json \
  --script input/script.md \
  --srt input/subtitles.srt \
  --output timeline/visual-plan-alignment.json
```

先处理 Beat 与逐段蓝图的`needsReview`，再创建`grouping.json`。一张蓝图只能落在其绑定 Beat 的时间范围内；候选范围不是动画指令，段内构图、状态和精确时序必须在本 Skill 的 Storyboard 阶段完成。详细规则见`references/VIDEO-STORY-HANDOFF.md`。

### video-use 过渡（分支 B）

用户在 video-use 里剪完素材后可直接续到本 skill：

```bash
python3 scripts/video-use-handoff.py <videos_dir> -o my-video/input --frames 8
```

契约：

- `input/audio.mp3` 从 final.mp4 提取（无 final 则 base.mp4）
- `input/subtitles.srt` 是**句子级** SRT（video-use `srt_export.py`
  从 Scribe JSON + EDL 重建，输出时间轴偏移）——**严禁**使用 video-use
  的 `master.srt`（2 词字幕块，会切碎语义分组）
- 渲染时长的基准 = 这段 SRT 的区间 = 原片 final cut 的时间轴，两者
  共享同一音频时钟，可无缝互剪
- video-use 不在默认位置 `~/Developer/video-use` 时（例如 Codex 安装的
  `~/.codex/skills/video-use`），加 `--video-use-dir <path>` 指向该副本

## Checkpoint Plan

`storyboard.md` 和 `timeline.json` 写完后必须停，并进入 Storyboard
Review。操作：

1. 启动 review 页（模板见 `assets/review-page-template.html`）。
2. 用户确认：SRT 行分组 / 每个 visual step 的模型化画面 / 素材策略
   （按 `references/MEDIA-FIRST.md` 的优先级：真实截图 > 忠实复刻 >
   手绘示意）/ 主题（读取全部 `themes/*/theme.json` 后推荐 2-3 个）/
   开发模式。
   有内容层视觉蓝图时，同时确认每张蓝图与唯一 Beat 的对齐、必见内容是否全部被承载、视觉模型是否准确表达理论、动画状态和准确时间边界。这里是用户第一次审具体画面形式的地方。
3. 反馈保存到 `feedback/storyboard.jsonl`。

**进入 Phase 3 前，agent 必须：** 读取所有 `feedback/*.jsonl`，按
`createdAt` 排序，按 `chapterId` + `stepId` 分组逐条处理，处理后置
`status: "resolved"`。

## Phase 3 组成品开发

脚手架：

```bash
bash <path-to-web-video-presentation>/scripts/scaffold.sh ./my-video --theme=<theme-id>
```

第一章仍是强制 anchor：主线程完整实现一章，`npm run check` 通过，反馈
页内嵌播放器验收后再继续。

单章硬规则：

- 每个 visual step 一个 clip（`data-start`/`data-duration` 由生成器
  从 timeline.json 写入）——**不得手改时间轴**，改时间请改上游
- 同一视觉骨架的连续 step 做场景合并与内部渐进揭示（GSAP 时间线）
- 来自视觉计划的 step 保留单一`sourceBlueprintId`，且不得跨到其他蓝图绑定的 Beat
- 每章必须有 CSS/SVG/Canvas 视觉演示，不能是纯字幕
- 主题 token 全部来自组成品 `:root`（生成器内联自 tokens.css）
- 完整契约见 `references/COMPOSITION-CRAFT.md` + `/hyperframes-core`

### 视觉模型自检

在写 HyperFrames 之前，逐个 Step 回查：

- `must_show` 的每个对象、数字和固定文字在 Storyboard 中都有承载位置；
- `must_express` 的每个事实都由模型关系表达，而不是只被字幕重复；
- 视觉模型名称、节点和箭头不改变上游理论；
- 画面不是把口播逐句放大，也不是用装饰性卡片替代模型；
- 反馈后先判断是内容契约缺失、视觉模型错误、排版问题还是动效问题，再修改对应层级。

## Checkpoint Review

详见 `references/REVIEW-UI.md`。反馈 schema 与 v1 完全一致
（chapterId / stepId / stepIndex / srtRange / caption / durationMs /
type / text / status / batchId / createdAt / codeVersion），保存到
`feedback/<chapterId>.jsonl`。处理协议：按 createdAt 排序 → 分组 →
旧反馈被新反馈覆盖则忽略 → 处理后置 resolved。

**审阅页就绪后必须自动打开给用户**（不要只给 URL 让用户自己找）：

1. `cd <project>/composition && npx hyperframes preview --port 5176 &` —— 运行时注入服务器（播放必需，见 REVIEW-UI.md）
2. `python3 -m http.server 8899 --directory <project> &` —— 审阅页静态服务
3. `open http://localhost:8899/review/` —— macOS 自动打开浏览器

播放器 src 指向 preview 服务器的预览端点（格式见 REVIEW-UI.md），**不要**
用静态文件直连组成品（无运行时：画面不切换、无声）。端口占用就换端口并
同步改 src。用户改完反馈后，agent 按 REVIEW-UI.md 的处理协议读反馈、
改组成品、重渲染。

## Phase 4 Timing Lock

详见 `references/TIMING-LOCK.md`。必须校验：

- `python3 scripts/generate-composition.py <project> --verify` 退出码 0
- `cd composition && npm run check` 0 error
- 有音频时 `input/audio.mp3` 存在且时长 ≥ SRT 区间
- 所有 open 反馈已处理或被用户明确接受
- 建议 `npx hyperframes snapshot --at <中点>` 抽查帧

## Phase 5 渲染输出

详见 `references/RENDERING.md`：

```bash
cd composition && npm run render
ffprobe -v error -show_entries format=duration renders/*.mp4   # 时长 == SRT 区间
```

渲染是确定性的（同一输入永远同一输出），改一版视觉后重渲染约 30 秒。
验收后追加 `project.md`（Strategy / Decisions / Reasoning log /
Outstanding）。

## 本次运行 Gotcha

- 上游蓝图必须是内容清单，不是画面草图。若它开始出现 `visualModel`、`modelStructure`、布局方向或动画状态，说明职责越界，应退回内容契约层清理。
- Storyboard 是独立的表达层审阅，不是上游蓝图的自动排版结果。必须先提出一个完整、可读、能表达理论的视觉模型，再进入 HyperFrames；不能边写 CSS 边猜模型。
- 用户在最终画面上的反馈通常会同时包含内容、模型、排版和动效问题。必须按层级分流：理论/事实回上游，模型/布局留在 Storyboard，时间/运动留在 Composition；不能只改用户挑出的单页而忽略同一轮反馈的共性。
- 16:9 画面有竖屏人物时，人物安全区和右侧信息区必须在布局方案中明确；右侧内容要占满可用宽度，但不能靠强行拉高模块填空。
- 反馈链路必须端到端验证：浏览器保存、服务端 JSONL、页面重载读取、旧反馈覆盖规则和导出结果都要能对账；浏览器缓存只能是备份。
- 长视频在全量渲染前必须完成代表性画面审阅和 `npm run check`；首帧、中段、结尾抽查不能替代对关键模型页面的静态审阅。

## Legacy 分支

- 无 SRT：`archive/legacy-tts/`（文章/脚本 → TTS → 网页，不严格对轨）
- 旧 React pipeline 项目（v1，如 PPTSkillV2/presentation）：继续用旧
  流程维护，说明在 `archive/legacy-recording/`。新项目一律走 v2
- 不要在 SRT-first 项目里主动询问"是否合成音频"

## 环境依赖

- Node.js ≥ 22 + ffmpeg（HyperFrames 渲染）
- `npx hyperframes init` 会在项目里 pin CLI 版本；升级检查用
  `npx hyperframes@latest upgrade --project . --check`
- `@hyperframes/player` 走 CDN（review 页内嵌，零依赖）
