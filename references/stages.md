# 制作阶段契约（`stages.md`）

> 能力组合矩阵见唯一入口 [SKILL.md](../SKILL.md)；命令语法见 [tools.md](tools.md)（参数细则以 `<命令> --help` 为准）。本页定义底座与各能力叠加时的阶段顺序、完成条件和返回条件。

## 固定底座 + 按能力按段分流

```text
[1–2 接入与画框] → [3–4 转写、剪辑与 Voice Polish (stage_cut / audio_mix)] → [5–6 字幕与时间脊柱 (srt_export / timeline_derive)]
                                                                                     │
         ┌───────────────────────────────────────────────────────────────────────────┴───────────────────────────────────┐
         ▼ 仅底座（无附加画面能力）                                                                                   ▼ 叠加 footage / motion / screen-demo
   [直进工程审阅/交付]                                           [7 执行分镜 storyboard.json (film / montage) → Look-Dev (按需) → sound_design 声景 → check_visual / check_montage]
         └───────────────────────────────────────────────────────────────────────────┬───────────────────────────────────┘
                                                                                     ▼
                                                [8–9 工程审阅与收件返修 (review / review_inbox，含声景与底噪开关)]
                                                                                     ▼ 作者明确出片指令
                                                [10 按段分流核验与双轨封装交付 (deliver / 纯混剪 montage --deliver)]
```

| 阶段 | 步骤 | 模型负责 | 核心公开入口（`helpers/`） | 完成后去哪里 |
|---|---|---|---|---|
| 接入 | 1–2 | 版本取舍、缺口、`capabilities` 与 `frame` 确认 | `_internal/resolve_vault.py`、`_internal/check_script_hash.py`、`frame.py` | 原始媒体去剪辑；未录音留 `planned`；外部 SRT 去导入 |
| 剪辑与人声 | 3–4 | 留哪句、气口取舍、错字与 Voice Polish | `stage_cut.py`、`audio_mix.py`（兼容：`audio_fix.py`） | 剪点确认后去时间与字幕 |
| 时间与字幕 | 5–6 | 语义断句、视觉分组；区分时间证据等级 | `srt_export.py`、`timeline_derive.py` | 无附加画面能力直进第 8 步；否则进第 7 步 |
| 分镜、画面与声景 | 7 | `storyboard.json`、Look-Dev 样镜定调、`motion` / `footage` / `screen-demo` 与 Visual Soundscape | `film.py`、`montage.py`、`sound_design.py`、`check_visual.py` | 去审阅 |
| 审阅与返修 | 8–9 | 解释反馈、改源、局部返修并重建快照 | `review.py`、`review_inbox.py` | 默认终点停在第 8 步工程审阅；作者出片才进第 10 步 |
| 交付与收尾 | 10 | 确认交付形态、按段分流拼合、声景封装与来源指纹 | `deliver.py`（或纯混剪 `montage.py --deliver`） | 实际文件核验通过后交付 |

> 检查与环境诊断属于各阶段内部自检动作，不另立制作阶段。

## 时间依据与本轮终点

时间来源证据定义只在 [visual-timeline.md](visual-timeline.md)：未录音 `planned` 只能交方案或独立预演；`projected` 支撑工程审阅，不证明成片实测；`measured` 必须匹配当前 EDL 指纹；外部音频 + SRT 标 `srt-import`。

**每轮的默认终点是侧边栏审阅页可播 + 本轮待办，不是出成片。** 渲染产物严格分两级：
- `edit/_engineering/**` = **审阅素材**（工程态，可随时重渲，**不算交付**）；
- `成品/**` = **交付件**（只有「作者明确出片指令」+「当前审阅快照已存在且有网页零漂移提交，或当轮对话明确指令导出传入 `--approve-in-chat --approval-note "<作者原话>"` 写入含实时源码指纹 `liveSourceHash` 的审计记录（`render_gate.py` 放行）」同时成立才允许写入）。

仅在开启 `footage` / `motion` / `screen-demo` 任一画面能力时进入第 7 步；仅底座剪口播项目直接完成第 3–6 步与剪辑/口播成片交付。

## 1. 接手与版本核对

**先读**：[intake-and-frames.md](intake-and-frames.md)、[preferences.md](preferences.md)、上游 `handoff-context.md`（或 `_idea/brief.md`）、`edit/project.md`、`production-plan.md` 与 `feedback/`。调用 `_internal/resolve_vault.py --style <style_id>` 取全局底线 [author-spec.md](author-spec.md)（G01–G05 / V01–V05）与 Style Card v3 风格卡（`style_card_path`、`palette`、`anchors`、`patterns`、可选 `preferred_frame`；未挂载私有库自动回退开源内置六套风格 [style-spec.md](style-spec.md)）。

**核 `script_hash`**：调用 `_internal/check_script_hash.py`（规则见 [intake-and-frames.md](intake-and-frames.md)）。hash 不一致、snapshot 不完整或资产越界立即停下问作者，不静默继续。

**输出与完成标准**：`edit/project.md` 明确本轮版本、输入绝对路径、`style_id`、`capabilities`、`frame` 与职责边界（存量老项目 `production_mode` 仅只读兼容）。

## 2. 确定制作方案

在 `production-plan.md` 写明：能力组合（底座 `剪口播` + `footage` / `motion` / `screen-demo`）、风格、声音来源与预设、画幅与版式（由 `helpers/frame.py resolve` 解析唯一几何真源，构建/预览见 [intake-and-frames.md](intake-and-frames.md)）、画面过程与强调（开启 `motion` / `screen-demo` 读 [visual-grammar.md](visual-grammar.md)；开启 `footage` 读 [montage-route.md](montage-route.md)）、字幕交付形态（[captions-and-audio.md](captions-and-audio.md) 的 `embed` / `srt-deliver` / `both`）与时间证据等级。

需要改内容主张或口播定稿回 `$video-manager`；仅在需要长篇静态图文时按需请 `$planners-ppt-hell` 介入；需要复用策略方法按需调用 `$planners-method-wiki`（不提供本项目事实）。

**完成标准**：`production-plan.md` 已落盘且写明 `capabilities`、风格、可由 `helpers/frame.py resolve` 解析的画幅真源、声音来源与字幕交付形态；需要改口播定稿或核心主张时停下回退 `$video-manager`，方案未拍板前不进入剪辑与分镜编码。

## 3. 声音与剪辑

1. **首选在线词级转写**：通过 `helpers/stage_cut.py prepare --project "<project>" --source "<原片>"` 自动首选豆包 SeedASR 2.0；备选与禁止自动 `ark` 规则见 [captions-and-audio.md](captions-and-audio.md)。
2. **音质诊断与 Voice Polish**：先按需 `_internal/audio_diag.py <媒体> --json`；全片人声与 `--ab` 盲听统一由 `helpers/audio_mix.py` 处理原始干声（细则见 [captions-and-audio.md](captions-and-audio.md)）。
3. **建剪辑决定（EDL）**：取舍写进 `edl.json` 保护原母版；用 `_internal/edl_from_keep.py` 吸附实测静音，用 `_internal/check_edl.py` 查边界与停顿。

**完成标准**：EDL 可检查；`transcripts/<source>.json` 为真实词/字级 token（粗粒度先跑 `_internal/refine_transcript.py`）；未将预览渲染当作正式底片。

## 4. 逐字剪辑审阅

唯一协调入口：`helpers/stage_cut.py review --project "<project>"`（内部调用 `_internal/edl_preview_build.py <edit>` 与 `_internal/edl_review_surface.py <edit>`）。DSH 有 `review_open` 时可加 `--surface-only` 只出契约路径；无插件（或源媒体 >200MB / 内存 <8GB）不加 `--surface-only` 自动拉起本地浏览器宿主并返回 URL，独立浏览器保存后给出明确闭环提示。

人审完成提交写入 `edit/selections.json` 后，模型跑 `helpers/stage_cut.py apply --project "<project>"` 并重建逐字预览。

**完成标准**：`edit/selections.json` 已由人审保存，`stage_cut.py apply` 执行通过且更新后的 `edl.json` 经 `_internal/check_edl.py` 校验绿灯、逐字预览已重建；未收到人审提交前停在审阅态，需改口播或重录则交回 `$video-manager`。

## 5. 工程时间与字幕

**先读**：[captions-and-audio.md](captions-and-audio.md)。

**先出工程态**：`_internal/duration_plan.py <edit>` 生成帧量化 `projected` 记录；必要时 `_internal/render.py <edit>/edl.json -o <edit>/_engineering/cut.mp4 --preview --no-subtitles` 出工程底片（绝不写 `edit/cut.mp4` 占用正式名）。

**Article-First 语义字幕流程**：
1. `helpers/srt_export.py <edit> --prepare` → 校对 `captions_article.txt`（可选写 `caption_corrections.json`）→ 写 `semantic_lines.txt`（10–18 字，上限 20 字，不跨段）
2. `helpers/srt_export.py <edit> --lock` → `--build` → `--check`

**完成标准**：`edit/segment_durations.json` 已记录对齐当前 EDL 的帧量化 `projected` 时长，`edit/subtitles.srt` 已通过 `helpers/srt_export.py <edit> --check`（无单行超限或句间零空隙），且工程底片仅写入 `edit/_engineering/`（未占用 `edit/cut.mp4` 或 `成品/**`）。

## 6. 建立唯一时间脊柱

`timeline/timeline.json` 为页面、动效、字幕与审阅共同消费的唯一时间脊柱：
- EDL 路径：`helpers/timeline_derive.py <edit> --grouping <project>/timeline/grouping.json [--alignment …] --output-timeline <project>/timeline/timeline.json [--output-durations <project>/remotion/src/data/step-durations.json]`；
- 外部已剪音频 + SRT：`helpers/_internal/import_srt_timeline.py <project> --srt <SRT> --alignment <alignment.json> --media <audio>`（标 `srt-import`）。
- 绑定使用稳定 `unitId`（`visual:<sourcePageKey>` / `speech:<step-id>` / `visual:<tag>`），改变时间轴或 EDL 后必须重新构建 `review.py`。

**完成标准**：`<project>/timeline/timeline.json` 已写入且标明时间证据等级（`measured` / `projected` / `srt-import`），全部 `unitId` 绑定有效；无附加画面能力时直接进入第 8 步，开启 `footage` / `motion` / `screen-demo` 时进入第 7 步。

## 7. 执行分镜、画面制作与画面声景（按开启的能力组合）

所有附加画面能力共享唯一机器真源 `storyboard.json`（用 `helpers/film.py verify` 校验与 `film.py summary` 派生人读概览），坐标统一从 `helpers/frame.py resolve` 读取：
- **开启 `footage`（剪视频）**：按 [montage-route.md](montage-route.md) 完成 `_internal/scan_materials.py` 素材清单与 `5s` 入点防重校验；混入 `storyboard.json` 时审阅期挂轻代理，交付期由 `deliver.py` 直切高清母版（纯混剪独立成片可走 `helpers/montage.py plan/render` + `_internal/check_montage.py`）。
- **开启 `motion` / `screen-demo`（做动效 / 实机录屏）**：按 [remotion-engine.md](remotion-engine.md) 与 [visual-grammar.md](visual-grammar.md) 先过 `helpers/remotion_runtime.py doctor` 及 `helpers/film.py init` + `verify`（开启 `motion` 且无静态参考页时先过 `film.py lookdev --verify` **Look-Dev Gate**；静态 SVG 参考页走 `film.py import-svg`）；按 `frame.py resolve` 与 `timeline.json` 写 Remotion 场景 `remotion/src/**`（`screen-demo` 审阅挂 `film.py proxy`），再用 `helpers/check_visual.py "<project>"` 默认全量自检（历史只读 `composition/` 老工程保持兼容）。
- **Visual Soundscape（开启 `motion` 或 `footage` 时）**：调用 `helpers/sound_design.py build`（[captions-and-audio.md](captions-and-audio.md)）生成声景并过内置响度门禁 `sound_design.py verify`。

**完成标准**：`storyboard.json` 通过 `helpers/film.py verify`（开启 `motion` 且无静态参考页时通过 `film.py lookdev --verify`），对应引擎/画面自检及 `sound_design.py verify` 响度门禁均绿灯；未通过门禁时停在第 7 步修复，通过后只进入第 8 步工程审阅（不直接出片）。

## 8. 工程态动效与成片审阅（默认终点）

**唯一构建入口**：`python3 "<craft>/helpers/review.py" "<project>"`（Remotion 前置门禁与 `{kw: 1}` 活舞台桥见 [remotion-engine.md](remotion-engine.md)；横竖屏自适应布局、声景试听开关与宿主接入细则见 [review-and-delivery.md](review-and-delivery.md)）。

**完成标准**：`helpers/review.py` 构建成功且已交付给人审（`review/review_data.json` 含最新 `snapshot` 与 `sourceManifest`，侧边栏或本地宿主审阅页可播可听声景）；**默认在此停止等待人审**，在收到网页提交或作者当轮明确出片授权原话前严禁进入第 10 步写 `成品/**`。

## 9. 收件、返修与重建

先跑 `python3 "<craft>/helpers/review_inbox.py" "<project>"` 核查回执（`imported/skipped/rejected`，有拒绝先修绑定）。
- 逐字意见 → 更新 `selections.json` → `stage_cut.py apply` → 重建预览与字幕时间轴；
- 画面、素材或声景反馈 → 读 `feedback/*.jsonl` → 只改受影响的 `storyboard.json`、`remotion/src/**`（或旧工程 `src/scenes/*.js`）、镜头表或 `sound_design.py`（参数见 `--help`）→ 重跑 **`review.py`** 使旧快照失效并重交审阅；仅当作者在对话中明确指示微调后直接导出时，按 [review-and-delivery.md](review-and-delivery.md)「3. 按段分流交付顺序、`deliver.py` 与务实会话出片授权」走 `--approve-in-chat --approval-note` 进入第 10 步。

**完成标准**：`review_inbox.py` 无未解决 `rejected` 回执，全部受影响的逐字/分镜/源码/声景已按反馈改完并重跑 `review.py` 重建新快照交审；若仅收到修改意见而无明确出片授权，必须停留在重建后的审阅态（不可跳入第 10 步）。

### 审阅与交付分界：算明确出片授权 vs 仅属返修意见

| 判定类别 | 作者对话典型原话 | 下一步强制动作 |
|---|---|---|
| **算明确出片授权** | “第3镜改快点，改完直接导出成片” / “字幕调高 20px 后直接出最终三件套，不用再发我审阅” | 仅当 `review/review_data.json` 已存在时，改完后按 [review-and-delivery.md](review-and-delivery.md) 走 `--approve-in-chat --approval-note` 交付 |
| **仅属返修意见** | “第3镜节奏太慢，改快点” / “这段 B-roll 换掉再加转场音效” / “改完发我看一下” | 严禁走会话出片授权；改完源码后重跑 `review.py` 重建审阅态等待人审 |

## 10. 核验与严格交付

仅当**作者明确要求出片**且**满足 [review-and-delivery.md](review-and-delivery.md) 双轨出片授权之一（网页零漂移提交，或当轮对话明确指令导出传入 `--approve-in-chat --approval-note "<原话>"`）**时执行：
- 渲染前置按 [visual-timeline.md](visual-timeline.md)「渲染前置」与 [remotion-engine.md](remotion-engine.md)「5. Remotion 四道确定性质量门禁」执行（先过 `_internal/render_gate.py`；历史兼容工程按 [visual-checks.md](visual-checks.md) 执行）；
- **按段分流与双轨交付**：`python3 "<craft>/helpers/deliver.py" "<project>" --render [--approve-in-chat --approval-note "<原话>"]`（完整分轨输出、`--composite` 与核验流程见 [review-and-delivery.md](review-and-delivery.md)）；
- **纯混剪独立三件套**（无 `storyboard.json` 分段拼合时）：`montage.py render --concat --out <成品/...> --deliver` + `montage.py voice-cut` + `srt_export.py --build --check` + `check_montage.py --video`（细节见 [montage-route.md](montage-route.md) 与 [review-and-delivery.md](review-and-delivery.md)）；
- **发送前指纹**：`state_fingerprint.py capture` → 发送前 `verify`；核验真实文件首中尾帧、响度（标准见 [captions-and-audio.md](captions-and-audio.md)）、音轨、字幕与交付说明。

**完成标准**：`render_gate.py` 放行，`deliver.py`（或纯混剪 `montage.py --deliver`）全部核验绿灯且 `成品/**` 实际文件、`核验报告.json`、`delivery.json` 已落盘，并完成 `state_fingerprint.py capture` 与发送前 `verify`；任一核验或指纹失败则禁止发送并回退对应制作阶段修复。
