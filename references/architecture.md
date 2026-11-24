# 架构与维护规则（`architecture.md`）

本文回答“该改哪个 owner、改动会让哪些产物过期、怎样证明结果可用”。制作顺序与完成标准只维护在 [stages.md](stages.md)，命令与参数只维护在 [tools.md](tools.md)。待实现与已验收的机械修复及 GOTCHAS 历史迁移索引见 [implementation-brief.md](implementation-brief.md)。

## 1. 系统边界：创作判断与机械保证

```text
输入与作者决定 → 模型选择生产模式与完成语义判断 → 调用当前 owner (12 个公开入口)
        ↑                                 ↓                       ↓
  反馈与返修 ← 解释审阅结果 ← 人审提交 ← 可播放的工程快照
                                                              ↓ 作者明确出片指令
                                         编码 → 文件核验 → 包装与指纹
```

- **模型与作者负责含义**：定 `production_mode`、剪哪句、怎么断句、哪些 cues 组成一个 Beat、批准原页怎样演成动画、反馈实际要求改什么。
- **工具负责可重复事实**：区间映射、时长计算、响度混音、版本/路径检查、快照构建、播放加载与媒体核验。工具退出 0 不等于语义、审美或作者批准成立。
- **工程结构分层**：`helpers/` 顶层只保留 **12 个高内聚公共入口**；所有底层共享模块（`_edl` / `_paths` / `_geometry` 等）、诊断工具与兼容适配沉入 `helpers/_internal/`（及 `helpers/_internal/lib/`）。

## 2. 权威出处（14 份参考手册）

| 问题 | 唯一 owner |
|---|---|
| 任务入口、生产模式三分与本轮终点 | [SKILL.md](../SKILL.md)、[GLOSSARY.md](../GLOSSARY.md) |
| 各阶段输入、顺序、完成/返回条件 | [stages.md](stages.md) |
| 12 个顶层公开命令与 `_internal` 诊断调用 | [tools.md](tools.md)（参数细则看 `--help`） |
| 上游交接、未录音预演、素材定位与画框规格 | [intake-and-frames.md](intake-and-frames.md) |
| `keyframe-svg` 创作主线、原页拆解、recompose 几何与 composition 硬规 | [visual-grammar.md](visual-grammar.md) |
| `footage-montage` 顺序、镜头表、体检与素材准入判据 | [montage-route.md](montage-route.md) |
| 唯一时间脊柱、三坐标换算与渲染前置检查 | [visual-timeline.md](visual-timeline.md) |
| `check_visual.py`、活舞台契约、交付态渲染、alpha 与自绘逐帧规则 | [visual-checks.md](visual-checks.md) |
| ASR 转写、Article-First 语义字幕、字幕形态与人声响度标准 | [captions-and-audio.md](captions-and-audio.md) |
| 双审阅面、DSH/本地宿主、收件返修与严格交付多腿核验 | [review-and-delivery.md](review-and-delivery.md) |
| 跨风格全局判准、四风格动效准则与规则准入淘汰 | [author-spec.md](author-spec.md)、[style-spec.md](style-spec.md)、[preferences.md](preferences.md) |
| 模块边界、失效依赖、新脚本准入与调试闭环 | 本文（`architecture.md`） |
| B1–B10 工作包、当前不变式与 GOTCHAS 历史迁移索引 | [implementation-brief.md](implementation-brief.md)、根目录 [GOTCHAS.md](../GOTCHAS.md) |

## 3. 模块 owner 与工具边界

| 模块层 | 唯一责任与公开入口（`helpers/`） | 内部机制（`helpers/_internal/`）与不承担项 |
|---|---|---|
| 接入与版本 | 上游文档与作者决定 | `check_script_hash.py`、`resolve_vault.py`、`spec_lint.py`；不改写上游主张 |
| 声音与混音 | `audio_fix.py`（人声预处理）、`audio_mix.py`（唯一混音 `-14 LUFS / -1.5 dBTP`） | `audio_diag.py`、`transcribe_seedasr.py`、`transcribe.py`、`mlx_transcribe.py`、`refine_transcript.py`、`pack_transcripts.py` |
| 剪辑协同 | `stage_cut.py`（prepare / review / apply） | `edl_from_keep.py`、`edl_edit.py`、`apply_selection.py`、`check_edl.py`、`edl_preview_build.py`、`edl_review_surface.py`、`measure_offset.py`、`mirror_edl.py` |
| 时间与字幕 | `srt_export.py`（Article-First 字幕）、`timeline_derive.py`（EDL 时间轴） | `_edl.py`、`duration_plan.py`、`import_srt_timeline.py`、`check_caption_breaks.py` |
| 画面与画框 | `film.py`（原页拆解）、`frame.py`（画框三件套与 `contain` 预览）、`check_visual.py`（统一画面体检） | `recompose_plan.py`、`check_live_stage.py`、`check_motion_targets.py`、`check_motion.py`、`check_screen_text.py`、`check_alpha.py`、`check_overlay.py`、`check_render_env.py`、`check_render_fidelity.py`、`probe_env.py` |
| 蒙太奇路线 | `montage.py`（plan / render / voice-cut） | `scan_materials.py`、`check_montage.py`、`_geometry.py::fit_in_band()` |
| 工程审阅与反馈 | `review.py`（构建 + 播放检查）、`review_inbox.py`（收件 + 密度回写） | `live_stage.py`、`live_preview.py`、`build_review.py`、`review_surface.py`、`check_review_playable.py`、`check_review_template.py`、`review_copy.py`、`review_slices.py`、`preview_layers.py`、`studio_notes.py`、`visual_review_feedback.py` |
| 交付与核验 | `deliver.py`（前置检查 + 合成 + 严格核验） | `render_gate.py`、`render.py`、`render_cut.py`、`render_layer.py`、`verify_av.py`、`verify_delivery.py`、`export_video.py`、`export_deliverables.py`、`state_fingerprint.py`、`stage_deliver.py`、`clean_edit_dir.py` |
| 共享机械库 | — | `_paths.py`、`_timecode.py`、`_probe.py`、`_words.py`、`_silence.py`、`_cutmap.py`、`_stage.py`、`screen_detect.py`、`lib/planners_modules*.py` |
| 外部执行环境 | — | HyperFrames（composition 播放与渲染）、FFmpeg、planners-review-core（审阅桥与宿主） |

> `pure-talking` / `footage-montage` / `keyframe-svg` 三条模式共用第 1–6、8–10 步共享底座。v1 旧 `page` 十步路线、独立主题库及归档历史包已清理退役；`visual/scripts/` 下保留的兼容脚本仅服务老项目迁移或现有测试。

## 4. 跨 Skill 与外部接缝

| 对接方 | 对方拥有 | Craft 接收/交回 |
|---|---|---|
| `video-idea-system` | 口播稿、内容主张、`visual-plan.json`、`production_mode` 建议与上游依据 | 核 `script_hash` 与采用版、对齐 Beat；改事实或文案回上游 |
| `planners-ppt-hell` | 静态页面、SVG 快照及页面视觉风格 | `film.py` 拆解参考页、不篡改静态原构图决定；改构图回上游 |
| `planners-review-core` | surface 契约、桥、本地宿主与 DSH 唤醒 | Craft 持有审阅 UI、播放验收与 `review_inbox.py` 业务解释 |
| HyperFrames / FFmpeg | composition 运行时时钟与视频编码 | Craft 负责活舞台契约、`check_visual` 与交付严格核验 |

两种审阅面（逐字剪辑面与动效/成片面）保持业务独立，共享 `review-surface/2.0.0` 宿主协议。

## 5. 共享事实与失效范围

| 权威产物 | 生产者 | 修改后必须重建的下游 |
|---|---|---|
| `edit/edl.json` | 剪辑决定 / `stage_cut.py` | `duration_plan`、字幕锁/cues、`timeline.json`、画面锚点、审阅快照（旧交付失效） |
| `edit/captions_article.txt` / `semantic_lines.txt` | 作者校对 + `srt_export.py` | `caption_words.json`、`subtitles.srt`、`timeline.json`、审阅 |
| `timeline/grouping.json` → `timeline/timeline.json` | 模型分组 → `timeline_derive.py` / `import_srt_timeline.py` | `composition` 时序、审阅快照 |
| `composition/`、`recompose/lines.json` | 模型手写 / `review_inbox.py` | `check_live_stage`、`review.py` 新快照 |
| `material-inventory.json` / 镜头表 / `material/frame/*` | `scan_materials.py` / `frame.py` | `montage.py plan`、受影响镜头、`check_montage`、`review.py` |
| `review/review-submissions.json` | 审阅页面写入 | `review_inbox.py`；仅覆盖当前快照才可通过 `render_gate.py` |
| `成品/*` 与交付指纹 | `deliver.py` / `montage.py --deliver` / `state_fingerprint.py` | 发送前必须 `state_fingerprint.py verify` |

## 6. Debug 闭环与新脚本准入

1. **先定位首个坏事实**：按 `源/版本 → EDL → 字幕/时间 → composition/素材 → 审阅 → 成片` 排查，保留失败产物与项目版本记录。
2. **只修当前 owner**：扩展 12 个顶层公开入口或 `helpers/_internal/` 对应模块，禁止复制第二个解析器/检查器/总调度脚本；兼容 shim 须先迁完调用方与测试才清理。
3. **验证与发布门禁**：改动必须现场跑全量 `python3 -m unittest discover -s tests -p 'test_*.py'`、`python3 helpers/_internal/spec_lint.py`、`python3 helpers/_internal/check_review_template.py`、`python3 evals/run_evals.py`；多 runtime 同步与 GitHub 镜像推送遵循根目录 `AGENTS.md` 与 `02-skills-library/PUBLISHING.md`。
