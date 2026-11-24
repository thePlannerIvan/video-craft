# 制作阶段契约（`stages.md`）

这里定义三个生产路线与共用底座的阶段顺序、完成条件和返回条件。入口 [SKILL.md](../SKILL.md) 负责模式分流；[tools.md](tools.md) 负责命令调用；CLI `--help` 解释具体参数。

## 三条路线 + 一个共用底座

```text
[1–2 接入与定方案] → [3–4 转写与逐字剪辑 (stage_cut)] → [5–6 语义字幕与时间脊柱 (srt_export / timeline_derive)]
                                                                 │
      ┌────────────────────────────┬─────────────────────────────┴───────────────────────────┐
      ▼ `pure-talking`             ▼ `footage-montage`                                        ▼ `keyframe-svg`
   [直接进入审阅/交付]         [scan_materials → montage → check_montage]              [film → composition → check_visual]
      └────────────────────────────┴─────────────────────────────┬───────────────────────────┘
                                                                 ▼
                             [8–9 工程审阅与收件返修 (review / review_inbox)]
                                                                 ▼ 作者明确出片指令
                                         [10 严格核验与交付 (deliver / montage --deliver)]
```

| 阶段 | 步骤 | 模型负责 | 核心公开入口（`helpers/`） | 完成后去哪里 |
|---|---|---|---|---|
| 接入 | 1–2 | 版本取舍、缺口、`production_mode` 选择与本轮终点 | `_internal/resolve_vault.py`、`_internal/check_script_hash.py`、`frame.py` | 原始媒体去剪辑；未录音留 `planned`；外部 SRT 去导入 |
| 剪辑 | 3–4 | 留哪句、气口取舍、错字与声音质量处理 | `stage_cut.py`、`audio_fix.py`、`audio_mix.py` | 剪点确认后去时间与字幕 |
| 时间与字幕 | 5–6 | 语义断句、视觉分组；区分时间证据等级 | `srt_export.py`、`timeline_derive.py` | 去所属路线的第 7 步（`pure-talking` 跳过第 7 步） |
| 画面 | 7 | `keyframe-svg`：原页拆解与手写 composition；`footage-montage`：素材清单与镜头表 | `film.py`、`check_visual.py`；或 `montage.py` | 去审阅 |
| 审阅与返修 | 8–9 | 解释反馈、改源、局部返修并重建快照 | `review.py`、`review_inbox.py` | 默认终点停在第 8 步工程审阅；作者出片才进第 10 步 |
| 交付与收尾 | 10 | 确认交付形态、严格文件核验与来源指纹 | `deliver.py`（或 `montage.py --deliver`） | 实际文件核验通过后交付 |

> 检查与环境诊断属于各阶段内部自检动作，不另立制作阶段。

## 时间依据与本轮终点

时间来源证据定义只在 [visual-timeline.md](visual-timeline.md)：未录音 `planned` 只能交方案或独立预演；`projected` 支撑工程审阅，不证明成片实测；`measured` 必须匹配当前 EDL 指纹；外部音频 + SRT 标 `srt-import`。

**每轮的默认终点是侧边栏审阅页可播 + 本轮待办，不是出成片。** 渲染产物严格分两级：
- `edit/_engineering/**` = **审阅素材**（工程态，可随时重渲，**不算交付**）；
- `成品/**` = **交付件**（只有「作者明确出片指令」+「人工提交覆盖当前快照（`render_gate.py` 放行）」同时成立才允许写入）。

有视觉层才进入第 7 步；`pure-talking` 模式直接完成第 3–6 步与剪辑/口播成片交付，严禁为通过检查捏造 `film` / `recompose` 或静态参考页。

## 1. 接手与版本核对

**先读**：[intake-and-frames.md](intake-and-frames.md)、[preferences.md](preferences.md)、项目 `_idea/brief.md`（旧 `_idea/current.md`）、`edit/project.md`、`production-plan.md` 与 `feedback/`。调用 `_internal/resolve_vault.py --style <style_id>` 取 [author-spec.md](author-spec.md) 与风格规则（未挂载私有库自动回退开源内置）。

**核 `script_hash`**：调用 `_internal/check_script_hash.py`（规则见 [intake-and-frames.md](intake-and-frames.md)）。hash 不一致、snapshot 不完整或资产越界立即停下问作者，不静默继续。

**输出与完成标准**：`edit/project.md` 明确本轮版本、输入绝对路径、`style_id`、`production_mode`（`pure-talking` / `footage-montage` / `keyframe-svg`）与职责边界。

## 2. 确定制作方案

在 `production-plan.md` 写明：制作模式（`production_mode`）、风格、声音来源与预设、画幅与版式（需要画框时读 [intake-and-frames.md](intake-and-frames.md) 并用 `helpers/frame.py build/preview`）、画面过程与强调（`keyframe-svg` 读 [visual-grammar.md](visual-grammar.md)；`footage-montage` 读 [montage-route.md](montage-route.md)）、字幕交付形态（[captions-and-audio.md](captions-and-audio.md) 的 `embed` / `srt-deliver` / `both`）与时间证据等级。

需要改内容主张或文字先回 `$video-idea-system`；需要重做静态参考页回 `$planners-ppt-hell`；需要复用策略方法按需调用 `$planners-method-wiki`（不提供本项目事实）。

## 3. 声音与剪辑

1. **首选在线词级转写**：`_internal/transcribe_seedasr.py <source-video> --edit-dir <edit>`（需 `.env` 豆包语音凭据与 `node ws`）。历史回退 `_internal/transcribe.py --backend auto` 只在无语音凭据时使用，严禁用 Ark 通用模型当 ASR（[captions-and-audio.md](captions-and-audio.md)）。
2. **音质诊断与处理**：先 `_internal/audio_diag.py <媒体> --json`，再由 `helpers/audio_fix.py` 输出增强副本；最终成片混音由 `helpers/audio_mix.py` 统一产出 `-14.0 LUFS / -1.5 dBTP`。
3. **建剪辑决定（EDL）**：取舍写进 `edl.json`，禁止直接修改原母版；用 `_internal/edl_from_keep.py` 吸附实测静音，用 `_internal/check_edl.py` 查边界与停顿。

**完成标准**：EDL 可检查；`transcripts/<source>.json` 为真实词/字级 token（粗粒度先跑 `_internal/refine_transcript.py`）；未将预览渲染当作正式底片。

## 4. 逐字剪辑审阅

由 `stage_cut.py` 协调或单跑 `_internal/edl_preview_build.py <edit>` 与 `_internal/edl_review_surface.py <edit> --surface-only`。DSH 有 `review_open` 时交返回 surface 绝对路径；无插件（或源媒体 >200MB / 内存 <8GB）直接运行本地宿主（去 `--surface-only`）。

人审完成提交写入 `edit/selections.json` 后，模型跑 `_internal/apply_selection.py <edit>`（或 `stage_cut.py apply`）并重建逐字预览。

## 5. 工程时间与字幕

**先读**：[captions-and-audio.md](captions-and-audio.md)。

**先出工程态**：`_internal/duration_plan.py <edit>` 生成帧量化 `projected` 记录；必要时 `_internal/render.py <edit>/edl.json -o <edit>/_engineering/cut.mp4 --preview --no-subtitles` 出工程底片（绝不写 `edit/cut.mp4` 占用正式名）。

**Article-First 语义字幕流程**：
1. `helpers/srt_export.py <edit> --prepare` → 校对 `captions_article.txt`（可选写 `caption_corrections.json`）→ 写 `semantic_lines.txt`（10–18 字，上限 20 字，不跨段）
2. `helpers/srt_export.py <edit> --lock` → `--build` → `--check`

## 6. 建立唯一时间脊柱

`timeline/timeline.json` 为页面、动效、字幕与审阅共同消费的唯一时间脊柱：
- EDL 路径：`helpers/timeline_derive.py <edit> --grouping <project>/timeline/grouping.json [--alignment …] --output-timeline <project>/timeline/timeline.json --output-durations <project>/composition/public/step-durations.json`；
- 外部已剪音频 + SRT：`helpers/_internal/import_srt_timeline.py <project> --srt <SRT> --alignment <alignment.json> --media <audio>`（标 `srt-import`）。
- 绑定使用稳定 `unitId`（`visual:<sourcePageKey>` / `speech:<step-id>` / `visual:<tag>`），改变时间轴或 EDL 后必须重新构建 `review.py`。

## 7. 画面制作（按 `production_mode` 分支）

- **`pure-talking`**：跳过本步，直接进入第 8 步工程审阅（或直接确认口播成片/外挂 SRT）。
- **`footage-montage`**：严格按 [montage-route.md](montage-route.md) 三步——`_internal/scan_materials.py`（补齐 `summary` / `usable` / 出处与水印等级）→ `helpers/montage.py plan/render` → `_internal/check_montage.py`（逐镜 + 成片黑帧两关）。默认输出进 `edit/_engineering/`。
- **`keyframe-svg`**：严格按 [visual-grammar.md](visual-grammar.md) 先过 `helpers/film.py init` + `verify` 四档视觉分拍网关（`talk-only` / `logic-diagram` / `theory-board` / `demo-footage`；静态参考图仅作配色、比例与造型风格参考，旧 `pages/` 仅历史兼容），从统一画框 `helpers/frame.py resolve` 与 `timeline.json` 读几何与时序手写 Seek 安全 `composition/src/scenes/*.js`（`demo-footage` 审阅挂 `film.py proxy`，严禁大录屏进 `composition/assets/`），再用 `helpers/check_visual.py --only quality` 与 `_internal/check_live_stage.py` 自检。

## 8. 工程态动效与成片审阅（默认终点）

**唯一构建入口**：`python3 "<craft>/helpers/review.py" "<project>"`（`keyframe-svg` 走活舞台检查 + `live_stage` + `build_review` + `check_review_playable`；`footage-montage` 或 `--final-cut` 走成片态审阅；详规见 [review-and-delivery.md](review-and-delivery.md)）。

通过 DSH `review_open`（传 `review-surface.json`）或 `_internal/review_surface.py <project>` 本地宿主交给人审。官方 HyperFrames player 拥有唯一播放头；超大资产由 `build_review.py` 自动在 `review/proxies/` 生成审阅副本并记录 `mediaNotes`。

## 9. 收件、返修与重建

先跑 `python3 "<craft>/helpers/review_inbox.py" "<project>"` 核查回执（`imported/skipped/rejected`，有拒绝先修绑定）。
- 逐字意见 → 更新 `selections.json` → `stage_cut.py apply` → 重建预览与字幕时间轴；
- `density` / 画面反馈 → 读 `feedback/*.jsonl` 与 `recompose/lines.json` → 只改受影响的 `src/scenes/*.js` 或镜头表 → 重跑 **`review.py`** 使旧快照失效并重交审阅。

## 10. 核验与严格交付

仅当**作者明确要求出片**且**当前审阅快照已有提交**时执行：
- 渲染前置按 [visual-timeline.md](visual-timeline.md)「渲染前置」与 [visual-checks.md](visual-checks.md) 执行（先过 `_internal/render_gate.py`；先 `probe_env.py` + `check_render_env.py`；停预览服务；`--workers 1`）；
- **`keyframe-svg` / 合成交付**：`python3 "<craft>/helpers/deliver.py" "<project>" --render`（或 `--visuals <已渲染画面>`；无人物加 `--no-person`；渲染后必过 `check_render_fidelity.py` + `verify_delivery.py`）；
- **`footage-montage` 三件套**：`montage.py render --concat --out <成品/...> --deliver` + `montage.py voice-cut --master <母版> --audio <口播音>` + `srt_export.py --build --check` + `check_montage.py --video`（细节与包装指纹见 [review-and-delivery.md](review-and-delivery.md)）；
- **发送前指纹**：`state_fingerprint.py capture` → 发送前 `verify`；核验真实文件首中尾帧、响度（`-14.0 LUFS / -1.5 dBTP`）、音轨、字幕与交付说明。
