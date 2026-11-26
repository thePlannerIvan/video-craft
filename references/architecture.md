# 架构与维护规则（`architecture.md`）

本文回答“该改哪个 owner、改动会让哪些产物过期、怎样证明结果可用”。制作顺序与完成标准只维护在 [stages.md](stages.md)，命令与参数只维护在 [tools.md](tools.md)。待实现与已验收的机械修复及 GOTCHAS 历史迁移索引见 [gotchas-index.md](gotchas-index.md)。

## 1. 系统边界：创作判断与机械保证

```text
输入与作者决定 → 模型确认能力组合与完成语义判断 → 调用当前 owner (13 个核心公开入口)
        ↑                                   ↓                         ↓
  反馈与返修 ← 解释审阅结果 ← 人审提交 ← 可播放的工程快照（含声景与底噪切换）
                                                                 ↓ 作者明确出片指令 / --approve-in-chat
                                            按段分流拼合 + 声景封装 → 文件核验 → 指纹
```

- **模型与作者负责含义**：定能力组合（底座 `剪口播` + `footage` / `motion` / `screen-demo`）与 `frame`、剪哪句、怎么断句、哪些 cues 组成一个 Beat、批准 Look-Dev 样镜与镜头表、反馈实际要求改什么。
- **工具负责可重复事实**：区间映射、时长计算、Voice Polish 除吸气与响度混音、Visual Soundscape 筛分闪避与响度门禁、版本/路径检查、快照构建、按段拼合与媒体核验。工具退出 0 不等于语义、审美或作者批准成立。
- **工程结构分层**：`helpers/` 顶层保留 **13 个高内聚核心公开入口**（含 `remotion_runtime.py`，另保留兼容入口 `audio_fix.py` 供单轨诊断与底层复用）；所有底层共享模块（`_edl` / `_debreath` / `_paths` / `_geometry` / `remotion_*` 等）、诊断工具与兼容适配沉入 `helpers/_internal/`（及 `helpers/_internal/lib/`）。

## 2. 权威出处（15 份参考手册）

| 问题 | 唯一 owner |
|---|---|
| 任务入口、能力组合矩阵与本轮终点 | [SKILL.md](../SKILL.md)、[GLOSSARY.md](../GLOSSARY.md) |
| 各阶段输入、顺序、完成/返回条件 | [stages.md](stages.md) |
| 13 个核心公开命令（含兼容入口 `audio_fix.py`）与 `_internal` 诊断调用 | [tools.md](tools.md)（参数细则看 `--help`） |
| Remotion 4 主动效引擎、外部运行壳、纯帧守则与四道门禁 | [remotion-engine.md](remotion-engine.md) |
| 上游交接、未录音预演、素材定位与画框规格 | [intake-and-frames.md](intake-and-frames.md) |
| `motion` / `screen-demo` 创作主线、`storyboard.json`、Look-Dev Gate 与场景硬规 | [visual-grammar.md](visual-grammar.md) |
| `footage` 素材清单、镜头表、防重与准入判据 | [montage-route.md](montage-route.md) |
| 唯一时间脊柱、三坐标换算与渲染前置检查 | [visual-timeline.md](visual-timeline.md) |
| `check_visual.py`、活舞台契约、交付态渲染、alpha 与自绘逐帧规则 | [visual-checks.md](visual-checks.md) |
| ASR 转写、Article-First 语义字幕、Voice Polish 与 Visual Soundscape 声音标准 | [captions-and-audio.md](captions-and-audio.md) |
| 双审阅面、DSH/本地宿主、收件返修与按段分流双轨交付核验 | [review-and-delivery.md](review-and-delivery.md) |
| 跨风格全局判准、四风格动效准则与规则准入淘汰 | [author-spec.md](author-spec.md)、[style-spec.md](style-spec.md)、[preferences.md](preferences.md) |
| 模块边界、失效依赖、新脚本准入与调试闭环 | 本文（`architecture.md`） |
| 当前不变式与 GOTCHAS 历史迁移索引 | [gotchas-index.md](gotchas-index.md)、根目录 [GOTCHAS.md](../GOTCHAS.md) |

## 3. 模块 owner 与工具边界

| 模块层 | 唯一责任与公开入口（`helpers/`） | 内部机制（`helpers/_internal/`）与不承担项 |
|---|---|---|
| 接入与版本 | 上游文档与作者决定 | `check_script_hash.py`、`resolve_vault.py`、`spec_lint.py`；不改写上游主张 |
| 声音（Voice Polish + Visual Soundscape） | `audio_mix.py`（Voice Polish 唯一混音/试听入口，`-14 LUFS / -1.5 dBTP`）、`sound_design.py`（Visual Soundscape 筛分闪避 + 动效声景与合播门禁）；兼容包装 `audio_fix.py` | `_debreath.py`、`audio_diag.py`、`transcribe_seedasr.py`、`transcribe.py`、`mlx_transcribe.py`、`refine_transcript.py`、`pack_transcripts.py` |
| 剪辑协同 | `stage_cut.py`（prepare / review / apply） | `edl_from_keep.py`、`edl_edit.py`、`apply_selection.py`、`check_edl.py`、`edl_preview_build.py`、`edl_review_surface.py`、`measure_offset.py`、`mirror_edl.py` |
| 时间与字幕 | `srt_export.py`（Article-First 字幕）、`timeline_derive.py`（EDL 时间轴） | `_edl.py`、`duration_plan.py`、`import_srt_timeline.py`、`check_caption_breaks.py` |
| 分镜、画面与画框 | `film.py`（`storyboard.json` 校验、`summary`、`lookdev` 样镜门禁、`proxy`、`import-svg`）、`frame.py`（画框三件套、预览与 `resolve` 几何真源）、`remotion_runtime.py`（外部运行壳管理）、`check_visual.py`（统一画面体检） | `remotion_gates.py`、`remotion_svg_scene.py`、`check_live_stage.py`、`check_visual_quality.py`、`check_motion_targets.py`、`check_motion.py`、`check_screen_text.py`、`check_alpha.py`、`check_overlay.py`、`check_render_env.py`、`check_render_fidelity.py`、`probe_env.py`、兼容 `recompose_plan.py` |
| 素材剪辑路线 | `montage.py`（plan / render / voice-cut） | `scan_materials.py`、`check_montage.py`、`_geometry.py::fit_in_band()` |
| 工程审阅与反馈 | `review.py`（构建 + 自适应横竖屏 + 声景/底噪预览 + 播放检查）、`review_inbox.py`（收件 + 绑定校验） | `remotion_stage.py`、`live_stage.py`、`live_preview.py`、`build_review.py`、`review_surface.py`、`check_review_playable.py`、`check_review_template.py`、`review_copy.py`、`review_slices.py`、`preview_layers.py`、`studio_notes.py`、`visual_review_feedback.py` |
| 交付与核验 | `deliver.py`（前置检查 + 按段分流拼合 + 声景无损封装 + 严格核验） | `render_gate.py`、`render.py`、`render_cut.py`、`render_layer.py`、`verify_av.py`、`verify_delivery.py`、`export_video.py`、`export_deliverables.py`、`state_fingerprint.py`、`stage_deliver.py`、`clean_edit_dir.py` |
| 共享机械库 | — | `_paths.py`、`_timecode.py`、`_probe.py`、`_words.py`、`_silence.py`、`_cutmap.py`、`_stage.py`、`screen_detect.py`、`lib/planners_modules*.py` |
| 外部执行环境 | — | Remotion 4 外部运行壳（`@remotion/player` 活舞台与动效段渲染；历史 `composition/` 仅作只读兼容）、FFmpeg、planners-review-core（审阅桥与宿主） |

> 所有能力组合共用第 1–6、8–10 步共享底座与统一 `storyboard.json` 契约；v1 旧 `page` 十步路线、独立主题库及归档历史包已退役，`visual/scripts/` 与 `pages/` / `visual-plan.json`、`composition/` 兼容分支仅服务历史项目只读迁移与现有测试（空 `pages/` 目录不再阻塞交付）。

## 4. 跨 Skill 与外部接缝

| 对接方 | 对方拥有 | Craft 接收/交回 |
|---|---|---|
| `video-manager` | 选题、口播定稿（`script.md`）、`visual-brief.md`、`handoff-context.md` 与 `style` 审美参考/禁忌 | 核 `script_hash` 与采用版；Craft 独立持有 `storyboard.json`、Look-Dev、声景与交付；改内容主张或文案回上游 |
| `planners-ppt-hell` | 按需产出的长篇/复杂静态参考页与 SVG 快照 | `film.py import-svg` 包装为 Remotion 场景参考（不篡改静态构图决定）；改静态排版回上游 |
| `planners-review-core` | surface 契约、桥、本地宿主与 DSH 唤醒 | Craft 持有审阅 UI、播放验收与 `review_inbox.py` 业务解释 |
| Remotion 4 外部运行壳 / FFmpeg | `@remotion/player` 活舞台与动效段渲染、FFmpeg 媒体编码（兼容历史 HyperFrames 只读工程） | Craft 负责 `{kw: 1}` 活舞台桥、`remotion_gates.py`、`check_visual`、按段分流拼合与交付严格核验 |

两种审阅面（逐字剪辑面与动效/成片面）保持业务独立，共享 `review-surface/2.0.0` 宿主协议。

## 5. 共享事实与失效范围

| 权威产物 | 生产者 | 修改后必须重建的下游 |
|---|---|---|
| `edit/edl.json` | 剪辑决定 / `stage_cut.py` | `duration_plan`、字幕锁/cues、`timeline.json`、画面锚点、声景母带、审阅快照（旧交付失效） |
| `edit/captions_article.txt` / `semantic_lines.txt` | 作者校对 + `srt_export.py` | `caption_words.json`、`subtitles.srt`、`timeline.json`、审阅 |
| `timeline/grouping.json` → `timeline/timeline.json` | 模型分组 → `timeline_derive.py` / `import_srt_timeline.py` | `storyboard.json` / `composition` 时序、`soundscape.wav`、审阅快照 |
| `storyboard.json` / `composition/` | `film.py` / 模型手写 | `film.py summary`、`sound_design.py`、`check_live_stage`、`review.py` 新快照 |
| `material-inventory.json` / 镜头表 / `material/frame/*` | `scan_materials.py` / `frame.py` | `storyboard.json` / `montage.py plan`、受影响镜头、`check_montage`、`review.py` |
| `edit/_engineering/soundscape.wav` | `sound_design.py` | `review.py` 声景预览、`deliver.py`（`画面成片.mp4` + `画面音效轨.wav`） |
| `review/review-submissions.json` | 审阅页面写入 | `review_inbox.py`；仅覆盖当前快照才可通过 `render_gate.py` |
| `成品/*` 与交付指纹 | `deliver.py` / `montage.py --deliver` / `state_fingerprint.py` | 发送前必须 `state_fingerprint.py verify` |

## 6. Debug 闭环与新脚本准入

1. **先定位首个坏事实**：按 `源/版本 → EDL → 字幕/时间 → storyboard/composition/素材 → 声景 → 审阅 → 成片` 排查，保留失败产物与项目版本记录。
2. **只修当前 owner**：扩展 13 个核心公开入口或 `helpers/_internal/` 对应模块，禁止复制第二个解析器/检查器/总调度脚本；兼容 shim 须先迁完调用方与测试才清理。
3. **验证与发布门禁**：改动必须现场跑全量 `python3 -m unittest discover -s tests -p 'test_*.py'`、`python3 helpers/_internal/spec_lint.py`、`python3 helpers/_internal/check_review_template.py`、`python3 evals/run_evals.py`；多 runtime 同步与 GitHub 镜像推送遵循根目录 `AGENTS.md` 与 `02-skills-library/PUBLISHING.md`。
