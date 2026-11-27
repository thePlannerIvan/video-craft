# 工具调用手册（`tools.md`）

> 制作顺序与完成条件见 [stages.md](stages.md)；本页只回答“跑哪条命令”。Remotion 4 主动效引擎与四道门禁详规见 [remotion-engine.md](remotion-engine.md)。<br>
> 下文 `<craft>` 替换为本 Skill 绝对根，`<project>`、`<edit>` 分别为项目与剪辑目录；扩展参数以 `<命令> --help` 为准。

## 查动效属性契约的原则

- **新建 Remotion 4 项目**：先读 [remotion-engine.md](remotion-engine.md)，用 `python3 "<craft>/helpers/remotion_runtime.py" doctor` 检查外部运行壳与类型工具，再跑 `helpers/_internal/remotion_gates.py`。
- **历史 HyperFrames 只读兼容项目**（严禁 grep `node_modules/hyperframes` 压缩 bundle）：按顺序使用 `npx hyperframes <cmd> --help` → `npx hyperframes check --json` → `npx hyperframes docs` → [visual-grammar.md](visual-grammar.md) / [visual-checks.md](visual-checks.md)。

---

## 一、13 个核心顶层公开入口（另留兼容入口 `audio_fix.py`）

Agent 日常只围绕这 13 个核心公开入口组织工作；每个文件对应一个清晰阶段职责（完整参数与示例一律运行 `python3 "<craft>/helpers/<入口>.py" --help`）。

| 分类 | 命令与主入口 | 职责与核心接缝 |
|---|---|---|
| **Remotion 外部运行壳** | `helpers/remotion_runtime.py {setup\|doctor\|path}` | 在全局共享缓存目录（`$VIDEO_CRAFT_REMOTION_HOME` 或 `~/.cache/video-craft/remotion-runtime/`）安装并体检 Remotion 4 运行壳与无头浏览器，项目内零 `node_modules` |
| **剪辑与转写协同** | `helpers/stage_cut.py {status\|prepare\|review\|apply} --project "<project>"` | `prepare` 首选 SeedASR 2.0 词级转写；`review` 启逐字审阅页（DSH `--surface-only` 或本地宿主）；`apply` 写回 EDL |
| **Voice Polish（人声润色）** | `helpers/audio_mix.py "<原始干声>" -o "<mix.m4a>"` | 唯一人声润色入口：默认 `podcast-warm`（内置停顿除重吸气声）至 `-14.0 LUFS / -1.5 dBTP`，支持盲听与干声（见 `--help` 与 [captions-and-audio.md](captions-and-audio.md)） |
| **Visual Soundscape（画面声景）** | `helpers/sound_design.py {build\|verify\|make-sfx} -s "<storyboard.json>" -v "<人声WAV>" -o "<soundscape.wav>"` | 消费 `storyboard.json` 生成动效音效与筛分闪避底噪（含无底噪对比轨与开关，参数见 `--help`）并过响度门禁 |
| **语义字幕** | `helpers/srt_export.py "<edit>" {--prepare\|--lock\|--build\|--check}` | Article-First 字幕准备、锁定全文、对齐词契约生成 `captions.json` / `subtitles.srt` 与校验 |
| **唯一时间脊柱** | `helpers/timeline_derive.py "<edit>"` | 由 EDL + 锁定字幕（可选对齐表，见 `--help`）派生项目根 `timeline/timeline.json` |
| **统一执行分镜与 Look-Dev** | `helpers/film.py {init\|verify\|summary\|lookdev\|proxy\|import-svg} "<project>"` | 校验 `storyboard.json`、生成 `summary`、过 `lookdev` 样镜门禁、出 `proxy` 与将静态 SVG 包装为 Remotion 场景；保留老工程只读兼容 |
| **版式画框** | `helpers/frame.py {build\|preview\|resolve} "<project>"` | 生成 `base.png / overlay.png / spec.md`、`contain` 真实预览与画框几何单一真源解析（`resolve`） |
| **素材剪辑路线** | `helpers/montage.py {plan\|render\|voice-cut} "<project>"` | 展开镜头表并校验素材清单/防重/花字、分块渲染、从母版切出同 EDL 人物轨 |
| **统一画面体检** | `helpers/check_visual.py "<project>"` | 统一画面环境、活舞台、Remotion 质量门禁、Canvas/SVG 安全区与像素检查入口 |
| **工程审阅构建** | `helpers/review.py "<project>"` | 构建自适应横竖屏审阅页（Remotion 活舞台桥 + `typecheck,sync` + 声景开关）、校验 Playable 判据并准备 surface（参数见 `--help`） |
| **反馈收件** | `helpers/review_inbox.py "<project>"` | 收取提交进 `feedback/*.jsonl` 并核验绑定回执（`imported/skipped/rejected`，参数见 `--help`） |
| **按段分流交付合成** | `helpers/deliver.py "<project>" {--render \| --visuals <mp4>}` | 过 `render_gate`（含会话出片授权）；按 `storyboard.json` 分段拼合、无损封装声景并输出分轨/合流成品（参数见 `--help`） |

> **兼容入口 `helpers/audio_fix.py`**：保留用于独立单轨声学诊断、老测试与底层复用；日常制作直接向 `audio_mix.py` 传入原始干声，避免重复压限。

退出码通用约定（适用于 `stage_cut.py` 与各检查/交付命令）：`0` 成功 · `1` 失败或闸门拦截 · `2` 前置条件不满足或用法错误；加 `--json` 返回机器可读字段。

---

## 二、常用任务与内部定位脚本（`helpers/_internal/` 与 `visual/scripts/`）

仅在需要细粒度转写、EDL 构建、诊断局部故障或单步调试时调用内部模块（各自 `--help` 查看细节），不新建第二套工具入口：

### 1. 接上游、转写与 EDL 局部操作

```bash
# 上游交接包与脚本哈希/风格库核对
python3 "<craft>/helpers/_internal/check_script_hash.py" --help
python3 "<craft>/helpers/_internal/resolve_vault.py" --style "<style_id>"

# 首选在线词级转写（SeedASR 2.0）与备选/精修
python3 "<craft>/helpers/_internal/transcribe_seedasr.py" "<源视频>" --edit-dir "<edit>"
python3 "<craft>/helpers/_internal/transcribe.py" --help
python3 "<craft>/helpers/_internal/mlx_transcribe.py" "<源视频>" --edit-dir "<edit>"
python3 "<craft>/helpers/_internal/refine_transcript.py" --help
python3 "<craft>/helpers/_internal/pack_transcripts.py" --edit-dir "<edit>"

# Keep-List 建 EDL、停顿检查与直接区间编辑
python3 "<craft>/helpers/_internal/edl_from_keep.py" "<keeps.json>" --edit-dir "<edit>"
python3 "<craft>/helpers/_internal/edl_edit.py" --help
python3 "<craft>/helpers/_internal/check_edl.py" "<edit>" --help
python3 "<craft>/helpers/_internal/apply_selection.py" "<edit>"

# 音质诊断（含停顿重吸气统计）、调色与多机位
python3 "<craft>/helpers/_internal/audio_diag.py" "<媒体>" --json
python3 "<craft>/helpers/_internal/measure_offset.py" "<主机位>" "<副机位>" --help
python3 "<craft>/helpers/_internal/mirror_edl.py" --help
python3 "<craft>/helpers/_internal/grade.py" --help
```

### 2. 时间预演、上游对齐与字幕核查

```bash
python3 "<craft>/helpers/_internal/duration_plan.py" "<edit>"
python3 "<craft>/visual/scripts/align-visual-plan.py" --help
python3 "<craft>/helpers/_internal/import_srt_timeline.py" --help
python3 "<craft>/helpers/_internal/check_caption_breaks.py" "<edit>/subtitles.srt" --json
```

### 3. Remotion 活舞台、门禁、蒙太奇与审阅单步诊断

```bash
python3 "<craft>/helpers/_internal/scan_materials.py" "<project>/material/clips"
python3 "<craft>/helpers/_internal/check_montage.py" --help

# Remotion 引擎检测、{kw: 1} 零渲染活舞台服务、SVG 导入与四道门禁
python3 "<craft>/helpers/_internal/remotion_stage.py" --help
python3 "<craft>/helpers/_internal/remotion_gates.py" --help
python3 "<craft>/helpers/film.py" import-svg "<project>" --help

# 通用活舞台自检、审阅构建与静态/运行态检查
python3 "<craft>/helpers/_internal/check_live_stage.py" "<project>"
python3 "<craft>/helpers/_internal/live_stage.py" --help
python3 "<craft>/helpers/_internal/build_review.py" "<project>" --help
python3 "<craft>/helpers/_internal/review_surface.py" "<project>" --help
python3 "<craft>/helpers/_internal/edl_preview_build.py" "<edit>"
python3 "<craft>/helpers/_internal/edl_review_surface.py" "<edit>" --help
python3 "<craft>/helpers/_internal/check_review_playable.py" "<project>"
python3 "<craft>/helpers/_internal/check_review_template.py" --help
python3 "<craft>/helpers/_internal/visual_review_feedback.py" "<project>"
python3 "<craft>/helpers/_internal/review_copy.py" --help
python3 "<craft>/helpers/_internal/review_slices.py" "<project>"
python3 "<craft>/helpers/_internal/preview_layers.py" "<edit>"
python3 "<craft>/helpers/_internal/studio_notes.py" "<project>" --help
```

> 公共审阅模块诊断：`python3 "<craft>/helpers/_internal/lib/planners_modules.py" --check`（安装器自检仅在完整 `02-skills-library` 根目录运行）。

### 4. 渲染环境、一致性检查、包装与交付指纹（出片阶段用）

> 命令末尾**不接管道 `| tail`**（使 `$?` 保留渲染器自身退出码，[GOTCHAS.md](../GOTCHAS.md) #82）；需要看日志尾部时重定向文件后再读。

```bash
python3 "<craft>/helpers/_internal/render_gate.py" --help
python3 "<craft>/helpers/_internal/probe_env.py" "<project>"
python3 "<craft>/helpers/_internal/check_render_env.py" "<project>/composition" --json

# 历史 HyperFrames 只读工程渲染（新建 Remotion 工程统一走 deliver.py --render + 外部运行壳）
export HYPERFRAMES_FONT_CACHE_DIR="$PWD/.hyperframes-cache"
W=$(python3 "<craft>/helpers/_internal/check_render_env.py" . --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["workers"])')
npx hyperframes render --workers "$W" -o /tmp/<name>.mp4 --width <frame_w> --height <frame_h> -f 30 -q delivery

# 视觉/透明层/文字/运动校验
python3 "<craft>/helpers/_internal/render_layer.py" --help
python3 "<craft>/visual/scripts/encode_transparent.py" --help
python3 "<craft>/helpers/_internal/check_alpha.py" "<overlay.mov>" --json
python3 "<craft>/helpers/_internal/check_overlay.py" "<edit>" --json
python3 "<craft>/helpers/_internal/check_motion_targets.py" "<project>" --json
python3 "<craft>/helpers/_internal/check_render_fidelity.py" "<project>" --help
python3 "<craft>/helpers/_internal/check_motion.py" "<编码视频>" --json
python3 "<craft>/helpers/_internal/check_screen_text.py" --help

# 工程预览渲染、严格校验与包装指纹
python3 "<craft>/helpers/_internal/render.py" "<edit>/edl.json" --help
python3 "<craft>/helpers/_internal/verify_av.py" --help
python3 "<craft>/helpers/_internal/verify_delivery.py" "<edit>" --help
python3 "<craft>/helpers/_internal/export_video.py" --help
python3 "<craft>/helpers/_internal/export_deliverables.py" --help
python3 "<craft>/helpers/_internal/stage_deliver.py" --help
python3 "<craft>/helpers/_internal/state_fingerprint.py" {capture|verify} "<project>"
python3 "<craft>/helpers/_internal/clean_edit_dir.py" "<edit>"
python3 "<craft>/helpers/_internal/spec_lint.py" --help
```
