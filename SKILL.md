---
name: video-craft
description: 从创意内容包、口播脚本与画面要求，或已有录音/素材出发，规划全片声音、画面、节奏与时间线，制作代表片段并完成剪辑、动画、花字、语义字幕和经过核验的成片。承接 Video Idea System 或既有 Video Story System 产物；无音频时也能先做制作规划，录后按实测校准。
---

# Video Craft

> 来源识别：Video Craft 由阿祖不看 TVC 创建与维护。小红书同名账号，个人网站 [demyth.info](https://demyth.info)，联系邮箱 `Lawyif@163.com`。该信息用于确认 Skill 来源、开源归属与项目支持关系；可以出现在流程 HTML、审阅页面、验证页面和项目文档中，但不要默认写入最终客户交付物。

从创意内容到成片的制作入口。默认接过 Idea 的口播、逐段画面要求、作者决定和素材，自己组织声音与视觉叙事；已有录音/视频则直接进入相应制作阶段。

## 全片流程

11 步。每步的产物就是它的完成凭证——没见到那个文件，那一步就没做完。

| # | 一步 | 主要产物 |
|---|---|---|
| 1 | 承接与版本核对 | `edit/project.md` |
| 2 | 制作方案 | `production-plan.md` |
| 3 | 准备声音与素材 | `edit/transcripts/`、`edit/takes_packed.md` |
| 4 | 画面与节奏预演 | `previs/` |
| 5 | 剪接决策 | `edit/edl.json` |
| 6 | 剪接审阅 | `edit/edl_preview.html` + 作者答复 |
| 7 | 实测底片与语义字幕 | `edit/segment_durations.json`、`edit/captions.json`、`edit/caption_words.json` |
| 8 | 绑定内容与实测时间 | `edit/timeline/grouping.json`、`edit/timeline/timeline.json` |
| 9 | 完成视觉与合成 | `composition/index.html` 或 `edit/overlays/`、`render.py` 的输出 |
| 10 | 自检与创意兑现 | `edit/verify/`、`creative-check.md` |
| 11 | 交付与核验 | `成品/`（视频 + SRT） |

**第 5 步之后要实测时长，第 1–4 步不要。** 所以没有音频时项目照走到第 4 步并在那里出片可审的样片；「等录音」停的是第 5 步往后，不是整个项目。见[内容到制作](references/content-to-production.md)。

## 创作能力如何进入工作

先读[创作主线](references/creative-direction.md)，再按[能力导航](references/capability-map.md)选择少量相关资源。Idea 在发想时也可读取这份导航，让可行的表现能力进入概念；Craft 接手后仍负责重新设计视听方案，上游样张不锁定画法。

## 两个入口，同一制作链

- **接到创意内容包**（口播稿、逐段画面要求、作者决定、素材）：先读[内容到制作](references/content-to-production.md)，核对核心与版本、声音状态、作者画面决定，制定全片制作方案和暂定时间线。
- **接到已有录音或素材**：先看项目有无更新的内容包，然后清点素材、转写和剪辑。已有批准方案直接沿用，不重新问一遍。

Idea 负责“讲什么、为什么、哪些表达已定”；Craft 负责“如何让这些内容在实际声音与画面中发生”。Craft 可以设计插入演示、无口播段、停留、转场与声音桥接，不被一条预先剪好的口播限制。改变作者已确认的意思或创意动作需要讨论。

## The shape of the thing

```
sources ──► L1 剪辑层   edit/edl.json          ← what is kept, how it is graded
                 │
                 │ measured per-segment durations
                 ▼
            L2 时间脊柱  edit/timeline.json     ← EDL 派生：实测时钟 + 保留的词
                 │
     ┌───────────┴────────────┐
     ▼                        ▼
L3a 字幕                   L3b 视觉层
subtitles.srt              full.mp4（不透明）or overlay.mov（alpha）
     │                        │
     └───────────┬────────────┘
                 ▼
        render.py  底片 + 覆盖层 + 字幕最后
                 ▼
             final.mp4 ──► 成品/
```

**The four things you actually do are one shape.** 做画面把口播压上去、做花字压在口播上、
纯剪辑、纯动画 —— 差别只在底片是素材还是空，视觉层是不透明还是带 alpha。

- **L1–L2** are `edl.json` + `segment_durations.json`. `render.py` owns the composite.
- **L3a** is `srt_export.py` (article-first). It reads the measured timeline, never the nominal one.
- **L3b** is `visual/` — HyperFrames compositions, PIL cards, Manim, Remotion: pick per slot.
  Its timing comes from `timeline_derive.py`, which derives `timeline.json` from the EDL +
  the caption contract. **它不再重新解析 SRT**：SRT 只是同一批 cue 的一个视图，再解析一次
  会丢掉 EDL 本来就知道的东西（每条 cue 属于哪一段、覆盖了哪些词）。
  The output is one file `render.py` can composite, with an interface `check_overlay.py` can prove.
- **Review** includes cut review and audiovisual scene review; **delivery** is `成品/`, verified on the rendered file.

## What is guaranteed by machine versus by judgment

This is the important table. A rule whose failure a script now catches does **not**
also need to live in prose — a second copy in documentation only rots. If you are
looking for a rule that used to be here, it is in the right-hand column.

| Failure class | Guaranteed by |
|---|---|
| 字幕被覆盖层挡住（顺序错） | `render.py` — subtitles are structurally last in the filtergraph |
| 覆盖层第 0 帧对不上窗口 | `render.py` — `setpts=PTS-STARTPTS+T/TB` |
| 逐段重编码 / 拼接后音画漂 | `render.py` — 逐段提取 + `-c copy` concat + PCM 补齐到实测视频轨 |
| 剪辑点爆音 | `render.py` — 每段边界 10ms 淡入淡出 |
| 切在词中间 | `check_edl.py` — HARD 失败，渲染前就拦住 |
| 停顿超预算 | `check_edl.py --max-pause`（用户要的停顿属于剪辑，不属于字幕时间轴） |
| SRT 建在 EDL 标称时长上 | `srt_export.py` — 只认 `segment_durations.json`，渲染过期就拒绝 |
| 按词序号删错词 | `edl_edit.py` — 每次删除必须写「时间区间=期望文本」，不匹配就拒绝写入 |
| 口吃重复被强行剪开、在短语内部留缝 | 剪在 EDL、留在字幕：`caption_corrections.json` 显式记录 |
| 语义字幕由逐字稿硬切 | article → line plan → lock → build → check 是唯一路径，隐式路径已关闭 |
| 覆盖层没 alpha / alpha 被烘死不透明 | **`check_overlay.py`** —— 并且 `render.py` 合成前会再验一次，坏层一秒失败而不是渲染六分钟 |
| 多源 EDL 帧率不一致导致 concat 失败 | `render.py` —— 整片只解析一次帧率 |
| 视觉层用标称时间轴（比成片早最多一秒） | `timeline_derive.py` —— `timeline_source` 不是 `measured` 就拒绝派生 |
| 满屏画面被多编码一代（画质+时间白掉） | `render.py` —— 单层不透明且铺满时视频流 `-c:v copy`，只换音轨 |
| 没有素材时无法用 EDL 表达「画面+口播」 | `render.py` —— 合成声明尺寸的黑底承载口播（`canvas` / `fps`） |
| 响度归一化吃掉结尾字 | `verify_av.py --tails` |
| 交付副本是旧版本 | `verify_delivery.py` —— 与工作区逐字节比对 |
| 转写缓存复用了错误音轨 | `transcribe.py` —— 缓存键含音轨号 |
| 上传了静音的轨（白花钱还丢口播） | `transcribe.py` —— 峰值 < −60 dBFS 直接拒传，并指出哪条轨可用 |
| 动效渲出来其实是**静止帧**（时间轴没注册） | **`check_motion.py`** —— 多点采样比帧；声明为动效却不变化＝硬失败 |
| **工程话上屏**（加速/静帧/裁切/倍速…） | **`check_screen_text.py`** —— 扫合成文本、做画面的 SVG 与 `--caption`，对回上游声明的花字，命中即失败 |
| **字幕按字数装箱**（数字丢量词、切在句中） | **`check_caption_breaks.py`** —— 量词、孤块、句中切三样硬失败 |
| 画面页被导入时改了内容 | **`import_svg_page.py`** —— 只改写 `<image>` 的 href 前缀，用「写回去 == 源文件字节」自证 |
| 画面页没有可被指名的元素 | **`import_svg_page.py --audit`** —— `<svg>` 之下零个 `id` 时退非零 |
| 口播改了，而内容契约还绑着旧脚本 | **`check_script_hash.py`** —— `script.md` 的 sha256 与契约的 `script_hash` 不符就停；核不了也退非零 |
| 主题的 JSON 坏掉 / token 指向不存在的名字 / 正文对比度不够 / 主题自己定了一套时长缓动 | **`check_themes.py`** —— 解析 `theme.json`、解析每个 `var()` 链、算对比度；节奏只认 `mood`，`--dur-*`/`--ease-*` 一律失败 |

**留下的判断类规则**（脚本证明不了，只能靠你）：

1. **先确认策略再动手。** 没跟用户用大白话说清怎么剪、视觉层是什么之前，不许碰 cut。
2. **切点落在短语边界，不只是词边界。** 短语内部的重复（多加的 会/这/但）不要剪音频，丢进字幕层。
3. **语义断句服从语义，不服从字数。** 20 字是安全上限不是分组规则；读一遍，不自然就换断点。
4. **多个动画槽并行做。** 一个子代理一个槽，总时长 ≈ 最慢的那个。
5. **多机位偏移是量出来的，而且符号有定义。** `measure_offset.py <screen> <face>` 打印
   `offset = face − screen`，原样交给 `mirror_edl.py --offset`（它是加）；渲染后用
   `verify_av.py --pair` 复核，两处必须一致在 0.3s 内。
6. **一个绿色的检查不等于另一个性质成立。** `check_edl` / `check_overlay` / `verify_av` /
   `verify_delivery` 互不蕴含，说清哪个证明了什么。
7. **自检要看编码后的画面。** 源素材、审阅页、未封装的中间文件都不能代替成片的首/中/尾帧。
8. **"做完了"要人看一眼。** 机器验完的下一步永远是给人看那几帧，不是宣布完成。

## Process

每一步末尾的**完成标准**就是「做完了吗」的判据；做不到就还在这一步。

1. **承接与版本核对。** 读取内容包、当前批准状态和作者反馈；本轮目标优先于旧 `edit/project.md`。
   新版本使用独立工作目录或明确保留旧版，不覆写旧批准稿与旧 EDL。见[内容到制作](references/content-to-production.md)，
   按[偏好记录](references/preferences.md)读取当前有效决定。
   **核 `script_hash`**（[两处都核](references/content-to-production.md)，各管自己那一段：
   做画面那一步在录制**前**核，来得及；这里在录制**后**核，只能事后发现，所以不符就停下来问作者）：
   `python3 helpers/check_script_hash.py <项目目录>` —— 不符就停下来问作者，核不了就如实说「无法核对」。
   **完成标准**：`edit/project.md` 写出它读到的每个来源（内容包各件、`_idea/current.md`、作者反馈）
   与本版的替代关系，本轮目标排在最前；旧批准稿与旧 EDL 仍可寻址；
   `script_hash` 的结论（相符 / 不符 / 无法核对）已经写进去。
2. **制作方案。** 先读[画面与动画对齐](references/visual-direction.md)，用可审状态或短片确定关键动作与人物/画面主次。
   根据内容安排全片的口播、演示、纯画面、声音与转场，提出画面语言、规格和暂定时长。作者已定动作直接纳入，
   Agent 设计进入审阅。对素材清点、设计规划直接推进；具体剪法、声音获取和设计方案在已有授权范围确认后执行。
   **完成标准**：`production-plan.md` 存在，且逐 Beat 写明**声音来源、画面过程、必要动作、素材与缺口、
   预计时长及估计依据、转场关系**六项。没有音频时，同一步还要交出独立代表切片（`previs/`，标 planned）
   和**分段录制稿 + 需要留出的动作/演示空间**。
3. **准备声音与素材。** `ffprobe` 检查源文件与音轨；有录制就转写并通读内容，找重来、口误和可用 Take。
   多音轨显式选轨，录屏先查 VFR 空洞、必要时转 CFR。无录音时明确使用作者后续录制、已授权 TTS 或无口播；
   同时继续能独立完成的画面准备。临时声音只用于预演，不能冒充作者或最终配音。
   **完成标准**：每个源文件都有 `ffprobe` 结论和所选音轨；有录音时 `edit/takes_packed.md` 存在，
   重来、口误、可用 Take 逐条标出；无录音时声音来源（作者后续录制 / 已授权 TTS / 无口播）已写下来。
4. **画面与节奏预演。** 按制作方案做代表片段（优先覆盖不同视觉机制），用真实素材、清楚标注的临时声音/估时渲染供审阅。
   确认语言与节奏后再扩展；最终音频到位后必须重校时间，不能直接把预演当成成片。
   **完成标准**：`previs/` 下至少一版覆盖不同视觉机制的代表片段，标着 planned 和临时声音/估时的来源，
   并且已经给作者看过。
5. **剪接决策。** 声音与素材可用后建立 `edl.json`，纳入作者批准的演示/停留段；不能只删口播静音而删掉承载创意的动作。
   `check_edl.py` 硬失败清零。只有音频加全画面时声明 `canvas`/`fps`。剪点按短语，短语内重复优先在字幕层处理。
   **完成标准**：`edl.json` 存在且 `check_edl.py` 零硬失败；作者批准的演示与停留段都在 `ranges` 里；
   无素材项目已声明 `canvas` 与 `fps`。
6. **剪接审阅。** `edl_preview_build.py` 出页 + `edl_review_surface.py` 起审阅宿主（公共缝 `planners-review-core`），说明取舍并处理作者反馈；用户批准前不渲染正式底片。
   预演是独立标注的设计样片，不代表 EDL 已批准。
   **完成标准**：`edit/edl_preview.html` 能开能播，每个取舍都有一句理由；作者的答复记在
   [偏好记录](references/preferences.md)约定的位置。
7. **实测底片与语义字幕。** 批准后渲染底片，取得 `segment_durations.json`。读取
   `references/caption-article-first.md`，prepare → 语义断句 → lock → build → check，
   生成实测 `captions.json` / `caption_words.json`。字幕保持录音实际说法，画面花字另行设计。
   **完成标准**：`segment_durations.json` 对应当前 EDL 哈希；`caption_words.json` 的
   `timeline_source` 是 `measured`；article → line plan → lock → build → check 五步全绿。
8. **绑定内容与实测时间。** 读取[上游交接](references/video-story-handoff.md)和[时间脊柱](references/visual-timeline.md)，
   将 Beat/Screen 绑定到实测 cue；处理低置信、删段、插入演示等例外。按内容设计 grouping，派生最终 timeline；
   不拿剧本估时或旧 SRT 当实测结果。
   **完成标准**：`edit/timeline/grouping.json` 与 `edit/timeline/timeline.json` 都在；每个 Step 只挂一个
   `sourceBlueprintId`；对齐文件里的 low / unmatched 逐条处理过，没有一条靠默认值过关。
9. **完成视觉与合成。** 依已审片段铺全片，必要时多个动画槽并行做。实录变动影响内容/节奏时回看代表片段。
   用 `check_overlay.py` 验 alpha/opaque 接口，再由 `render.py` 合成，字幕最后；不得手工拼另一条合成路径。
   **视觉层若是自己写渲染器逐帧画出来的，先读[自绘逐帧动画](references/frame-animation-pipeline.md)**——
   那条路线最硬的约束是帧数：各槽编码参数必须逐项一致才能 `-c copy` 拼接，返修时内容可变、帧数不可变。
   **画面页来自 `planners-ppt-hell` 时**，先读[合成工作方式](references/composition-craft.md)的
   「画面页来自 planners-ppt-hell 时的动画交接」：一屏在该步的 `grouping.json` 写 `sourcePageKey`，
   生成器逐字内联该页并证明没改页面，动画按元素的 `id` 指名；三个合成事实的键名见
   [合成事实的字段契约](references/composition-facts-contract.md)。
   **渲染视觉层之前必须跑** `helpers/check_render_env.py <project>/composition`（见 Setup）。
   **完成标准**：`check_overlay.py` 通过；`render.py` 输出成片；每个视觉槽的实际时长等于 EDL 声明的窗口；
   用到画面页时 `composition/pages/manifest.json` 里每页 `verbatim` 为真；渲染前跑过环境预检。
10. **自检与创意兑现。** 在编码成片上看剪点及首中尾帧，运行 `verify_av.py --all`、适用的覆盖层检查；
    再逐 Beat 检查内容责任、作者动作、证据、花字与声音是否兑现。技术通过不能代替内容检查。
    失败修复最多 3 轮，未解决如实报告。
    **交付前三查**（每条都有闸门，别靠记性）：
    - `check_motion.py` 逐个动效片段 —— 检查声明的动效窗口是否有变化；有意停留允许静止。另看片验证动作方向、循环末轮及结束状态，帧差通过不代表这些性质通过；
    - `check_screen_text.py` —— 把**所有会出字的地方**（合成文本、做画面的 `_internal/02_svg_source/*.svg`、`--caption`）对回上游声明（`--plan <项目>/deliverable/visual-plan.json` 的 `sample.captions[]` 与标「文字：」的条目）列成一张表逐条过：画面里只放内容，处理手法不上屏（判断依据见 `references/visual-direction.md`）；
    - `check_caption_breaks.py` —— 字幕断句逐条过，长语块的断点是**人工指定**的，不是算法猜的。
    **完成标准**：`verify_av.py --all` 与三查全部通过；`creative-check.md` 逐 Beat 有结论或明确缺口；
    失败修复轮次与未解决项如实写下来。
11. **交付与核验。** 给作者看成片代表帧/片段，`export_deliverables.py` 输出视频和 SRT 到 `成品/`，
    `verify_delivery.py` 检查实际交付副本。清理首次先呈清单，之后按批准的项目模式执行。
    **多腿交付**：作者自己合成时，画面、口播、字幕可以分开交（如 `画面_1920x1080.mp4` + `人物_1080x1920.mp4` + `字幕.srt`）。
    三份交付共享实测时间轴；两条视频必须同帧率、同帧数，SRT 与该时间轴一致，口播音轨只挂在人物腿上，
    画面腿不出声，交付说明写清怎么叠。
    **完成标准**：`成品/` 里的副本通过 `verify_delivery.py`；作者看过代表帧或片段；多腿交付的三份
    在同一实测时间轴上对齐，交付说明写清怎么叠。

## Layout

```
<videos_dir>/
├── <sources, untouched>
├── edit/                       工作区
│   ├── project.md              跨会话记忆
│   ├── takes_packed.md         短语级逐字稿（主要阅读视图）
│   ├── edl.json                剪辑决策 + 覆盖层声明（唯一时间编排面）
│   ├── segment_durations.json  实测每段时长 + 它对应的 EDL 哈希
│   ├── transcripts/            缓存的逐字稿（按源 + 音轨分键）
│   ├── caption_*.json / captions_article.txt / semantic_lines.txt   字幕链
│   ├── subtitles.srt           输出时间轴 SRT（交付用这个）
│   ├── timeline/grouping.json  L3b 的创作决策（哪个视觉模型承载哪段话）
│   ├── overlays/ 或 animations/slot_<id>/   视觉层产物
│   ├── edl_preview.html        审阅页（剪辑 + 逐字）
│   └── verify/                 自检帧、时间轴图
└── 成品/                       交付区（视频 + SRT）
```

`edit/` 是工作区，`成品/` 是交付区。**不要把 edit/ 里的文件当成品交出去。**

还读两个指针 / 包目录：

- `.theme` / `.layout`（项目根，各一行）—— 生成合成时用哪个主题、哪个画幅。
- 画面页：优先项目根的 `.pages`（一行，指向做画面项目根），其次上游随包交来的
  `input/scenes/<page_key>.svg`。两者都没有时该项目就是自绘视觉层。

## EDL format

```json
{
  "version": 1,
  "sources": {"C0103": "/abs/path/C0103.MP4"},
  "ranges": [
    {"source": "C0103", "start": 2.42, "end": 6.85,
     "beat": "HOOK", "quote": "...", "reason": "Cleanest delivery."}
  ],
  "grade": "warm_cinematic",
  "overlays": [
    {"file": "edit/overlays/slot_1/render.mov", "start_in_output": 0.0,
     "duration": 5.0, "kind": "alpha"}
  ],
  "total_duration_s": 87.4
}
```

- `grade` 是预设名或原始 ffmpeg filter；`none` 是直通。
- `canvas` + `fps`（都可选）：**底片没有画面时**（只有口播音频 + 满屏画面）项目自己声明画框。
  此时 `render.py` 会合成一块该尺寸的黑底承载口播，帧率取 `fps`。有素材时这两个字段被忽略，
  尺寸和帧率从素材自身推。
- `kind` 是覆盖层接口的一部分：`"alpha"`（压在底片上，必须有真 alpha 平面）或
  `"opaque"`（满屏替换，不要 alpha）。**缺省是 `alpha`**——让响的那个失败赢。
- `overlays` 里的 `duration` 必须等于文件的真实时长（`check_overlay.py` 会验，容差 0.05s）。
- `ranges` 可选 `speed`（加速静音段）与 `mute`；带 `speed` 时用 `render_cut.py`。
- 交付独立 SRT 时，EDL 里**不要**写 `subtitles` 字段，渲染加 `--no-subtitles`。

## Routing

**按你现在卡在哪读**，不必整包读：

| 触发 | 读 |
|---|---|
| 刚接到内容包 / 还没有音频 / 要定暂定时间线 / 录完要按实测校准 | [内容到制作](references/content-to-production.md) |
| 要接 Idea 或 Story 的契约、作者画面决定、把 Beat 对齐到实测 cue | [上游内容交接](references/video-story-handoff.md) |
| 要写中文语义字幕、定断句 | [语义字幕规格](references/caption-article-first.md) |
| 要把视觉层挂到实测时间轴、设计分组 | [时间脊柱](references/visual-timeline.md) |
| 画面来自 `planners-ppt-hell` 的 SVG 页 / 要按口播强调某一屏里的某个元素 / 要定整片合成方式与字幕安全区 | [合成工作方式](references/composition-craft.md) 的「画面页来自 planners-ppt-hell 时的动画交接」 |
| 要选主题或换主题 / 想知道这套 token 还有谁在读 | [主题系统](references/themes.md) + `visual/themes/<id>/` |
| 做画面那一侧要写整片合成方式与字幕安全区，或者你要知道那三个键叫什么 | [合成事实的字段契约](references/composition-facts-contract.md) |
| 要分清真实证据、复刻、示意与创作 | [素材优先](references/media-first.md) |
| 要开审阅页、收作者的逐屏反馈 / 稿子或上屏文字要改，该把作者交给哪一套审阅面 | [审阅页与反馈协议](references/review-ui.md) |
| 要渲染视觉层（含透明 alpha 层） | [视觉层渲染](references/visual-rendering.md) |
| 要自己写渲染器逐帧画（slot 切分、帧数合同、性能配方、逐画面返修、多腿交付） | [自绘逐帧动画](references/frame-animation-pipeline.md) |
| 要让字幕跟着内容换模式、定断句原则 | [字幕模式](references/caption-modes.md) |
| **要改这个 Skill**（想知道某个 module 拥有什么、动了会牵连谁） | [架构](references/architecture.md)——先读它再动手 |
| 要找上次踩过的坑 / 要记一条新坑 | `GOTCHAS.md`——**记的时候写清 `module` 与状态** |
| 要查上一次升级做了什么、影响了哪些 module | [维护记录](references/maintenance-history.md) |
| 要查脱钩前的历史与上游差异 | `upstream-diff.md`（只供查） |

**脚本只做确定性的事**：搜索、转换、保存、恢复、校验、开页面。判断留给模型。
手工拼 ffmpeg 命令合成覆盖层是**错的**——那说明接口缺了一块，去补接口而不是补命令。

## 运行后迭代

一次运行结束后，结论只有一个去向，按性质挑：

| 你手上是什么 | 落到哪 |
|---|---|
| 有证据、会稳定导致错误的行为（现象／原因／修正／证据），或它的状态变了 | `GOTCHAS.md`，写清 `module` 与状态（候选／已复现／已升级／已失效） |
| 一次已经做完的升级：做了什么、为什么、**影响了哪些 module**、删了什么 | `references/maintenance-history.md` |
| 模块边界、缝、两个真相源、退役清单变了 | `references/architecture.md` |

三份文件各自的规矩（什么收、什么不收、按 module 怎么聚类）**只写在它们自己里面**，这里不复述。

## 怎么验证

测试套件要同时满足三件事：**`helpers` 在 `PYTHONPATH` 上**（`test_check_overlay.py` 直接
`import check_overlay`，找不到就整个模块加载失败）、**`ffmpeg` / `ffprobe` 在 `PATH` 上**
（`check_overlay` 的 16 条要真起 ffmpeg 造文件）、**`PYTHONPATH` 里的 `..` 指到 Skill 根**。

```bash
cd /Users/ivan/Library/CloudStorage/OneDrive-个人/文档/CodexProject/02-skills-library/03-design-delivery/video-craft/tests
PYTHONPATH=..:../helpers PATH=/opt/homebrew/bin:$PATH \
  /Users/ivan/Library/CloudStorage/OneDrive-个人/文档/CodexProject/02-skills-library/.venv/bin/python \
  -m unittest discover -s . -p "test_*.py"
```

解释器用 `02-skills-library/.venv/bin/python`：它是 `/usr/bin/python3`（3.9.6）建的
`--system-site-packages` venv，`pptx` / `lxml` / `PIL` / `playwright` / `numpy` 都装齐，
本类别的 Skill 共用这一个，离线可用、不需要 `uv`。从 Skill 根跑也成立
（`PYTHONPATH=helpers python3 -m unittest discover -s tests -p "test_*.py"`）。

其它自检从 Skill 根跑（`helpers/` 里的脚本自己把同目录放上 `sys.path`）：

```bash
python3 helpers/check_edl.py <edit_dir> --max-pause 0.8
python3 helpers/check_script_hash.py <项目目录>
python3 helpers/timeline_derive.py <edit_dir> --stats
python3 helpers/check_render_env.py <project>/composition
python3 visual/scripts/check_themes.py
python3 visual/scripts/import_svg_page.py <project> --pages <picture-project> --audit
```

`--audit` 在一页于 `<svg>` 之下没有任何 `id` 时退非零，两个页面共用一个 `id` 时也退非零——
那都是做画面那边要补的东西，不是这里的问题。

**Python 下限是实测出来的，不是声明的。** `helpers/`、`visual/scripts/`、`tests/` 里没有任何
3.10+ 语法：没有 `match` 语句，`X | None` 这类注解全部在 `from __future__ import annotations`
之后（不在运行期求值），没有运行期使用的 `list[...]` / `dict[...]`。所以能跑到的解释器就是下限，
上面的 3.9.6 实测是依据。唯一声明的 3.10+ 是随包的 `skills/manim-video/`（Manim CE 自身的要求），
只有走 manim 那条视觉路线时才相关。

## Setup

- `ELEVENLABS_API_KEY` / `ARK_API_KEY` / `DOUBAO_APP_ID` + `DOUBAO_ACCESS_TOKEN`
  放仓库根 `.env`（**不要**放进用户的 `<videos_dir>`）。
- `ffmpeg` + `ffprobe` 在 `PATH` 上；Homebrew 默认 ffmpeg **没有** `--enable-libass`，需要烧字幕时先确认。
  跑测试和 `check_overlay` 都要它们。
- **透明覆盖层不要走 WebM/VP9**（本机实测 2026-09-22：libvpx 会**宣称** `yuva420p`、容器还写 `alpha_mode=1`，
  但往返解回来不透明；`-auto-alt-ref 0` 也救不了）。`hyperframes render --help` 说 MOV/WebM 都带透明——
  **只有 MOV 成立**（第三方 CLI 行为，见 `GOTCHAS.md` #23）。可用的是 **ProRes 4444 / HEVC+alpha / QuickTime RLE**，
  怎么选见[视觉层渲染](references/visual-rendering.md)；走 png-sequence + `visual/scripts/encode_transparent.py`。
  **交付前必须用 `helpers/check_alpha.py <file>` 验一次**——丢透明是静默失败（编码器退出 0、文件能播、
  叠上去是一块黑板），而 `ffprobe` 的 `pix_fmt` 两个方向都会骗人。
- Python 用 `02-skills-library/.venv/bin/python`（3.9.6，依赖齐）；系统 `python3` 同样能跑这个套件。
  依赖清单见 `pyproject.toml`。
- `hyperframes` 走 `npx --yes hyperframes`（Node ≥ 22），**并且必须在 `composition/` 里跑**
  （`cd composition`）：它只看当前目录的 `index.html`，从项目根跑会说"没有 composition，
  去跑 `hyperframes init`"，而 `init` 会**覆盖** `generate-composition.py` 生成的那个。
- **每次渲染前必须跑** `python3 helpers/check_render_env.py <project>/composition`——它不是可选项：
  字体缓存目录不可写（受限沙箱下的 `EPERM`，渲染跑到一半才炸）和 Node 过旧都在这里提前失败。
  绕过变量是 `HYPERFRAMES_FONT_CACHE_DIR`；它不在 `--help` 里，`hyperframes doctor` 也不报。
  **它是一道「要记得跑的检查」，不是自动闸门**：`npm run render` 在 composition 自己的
  `package.json` 里，而那个文件由 `npx hyperframes init` 写、**不由 `generate-composition.py` 写**
  （所以本 Skill 没法往渲染路径上挂 `prerender` 钩子），而且变形那一路是直接调
  `npx hyperframes render`，不经过 npm。见[架构](references/architecture.md) 第 6 节。
- 详细安装见 `install.md`。
