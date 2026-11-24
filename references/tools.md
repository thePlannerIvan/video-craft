# 工具调用手册（`tools.md`）

> 制作顺序与完成条件见 [stages.md](stages.md)；本页只回答“跑哪条命令”。<br>
> 下文 `<craft>` 替换为本 Skill 绝对根，`<project>`、`<edit>` 分别为项目与剪辑目录；扩展参数以 `<命令> --help` 为准。

## 查 HyperFrames 属性契约的原则

严禁 grep `node_modules/hyperframes` 压缩 bundle。正确排查顺序：
1. `npx hyperframes <cmd> --help`
2. `npx hyperframes check --json`
3. `npx hyperframes docs`
4. 本 Skill 的 [visual-grammar.md](visual-grammar.md) 与 [visual-checks.md](visual-checks.md)
5. 最小 3 行 fixture composition 实测（`visual/assets/` 下本 Skill 脚本可直接读）

---

## 一、12 个顶层公开入口（`helpers/`）

Agent 日常只围绕这 12 个顶层入口组织工作；每个文件对应一个清晰阶段职责。

| 分类 | 命令 | 职责 |
|---|---|---|
| **剪辑与转写协同** | `python3 "<craft>/helpers/stage_cut.py" {status\|prepare\|review\|apply} --project "<project>" [--source "<原片>" --backend auto\|seedasr\|scribe\|mlx] [--surface-only]` | `prepare` 首选 SeedASR 2.0 词级转写（禁自动 `ark`）；`review` 支持 DSH `--surface-only` 或无插件自动起本地浏览器宿主 |
| **人声诊断试听** | `python3 "<craft>/helpers/audio_fix.py" "<媒体>" -o "<处理.wav>" [--preset podcast-warm\|raw] [--ab "起始,时长"]` | 单轨声学试听与短片段 A/B 盲听对比；终混请直接传原始干声给 `audio_mix.py`，勿二次压限 |
| **全片混音** | `python3 "<craft>/helpers/audio_mix.py" "<原始干声>" -o "<mix.m4a>" [--bgm ...] [--sfx ...] [--voice-preset podcast-warm\|none\|raw] [--no-sfx\|--dry]` | 唯一混音出口：默认启用 `podcast-warm` 与 `-14.0 LUFS / -1.5 dBTP`，支持稀疏 CC0 SFX 护栏与 `--dry` 纯干声 |
| **语义字幕** | `python3 "<craft>/helpers/srt_export.py" "<edit>" {--prepare\|--lock\|--build\|--check} [--force-prepare --time-source measured]` | Article-First 字幕准备、锁定全文、对齐词契约生成 `captions.json` / `subtitles.srt` 与校验 |
| **唯一时间脊柱** | `python3 "<craft>/helpers/timeline_derive.py" "<edit>" [--stats \| --entries-only \| --grouping <g> --output-timeline <t> --output-durations <d>]` | 由 EDL + 锁定字幕（+ 可选 `--alignment`）派生项目根 `timeline/timeline.json` |
| **四档分拍与演示代理** | `python3 "<craft>/helpers/film.py" {init\|proxy\|verify} "<project>" ...` | 初始化 `visual-plan.json` 四档视觉语法、生成 `demo-footage` 审阅轻代理与构建校验 |
| **版式画框** | `python3 "<craft>/helpers/frame.py" {build\|preview\|resolve} "<project>" ...` | 生成 `base.png / overlay.png / spec.md`、`contain` 真实预览与画框几何单一真源解析 |
| **蒙太奇路线** | `python3 "<craft>/helpers/montage.py" {plan\|render\|voice-cut} "<project>" ...` | 展开镜头表并校验素材清单/唯一性/花字、分块幂等渲染、从母版切出同 EDL 人物轨 |
| **统一画面体检** | `python3 "<craft>/helpers/check_visual.py" ...` | 统一画面环境、静态规范、运动与像素检查入口（子动作详 `check_visual.py --help`） |
| **工程审阅构建** | `python3 "<craft>/helpers/review.py" "<project>" [--final-cut]` | 按形态构建工程活舞台或成片态审阅页、校验 Playable 四判据并准备 surface |
| **反馈收件** | `python3 "<craft>/helpers/review_inbox.py" "<project>" [--dry-run]` | 收取提交进 `feedback/*.jsonl`、去重验绑定、回写 `recompose/lines.json` |
| **严格交付合成** | `python3 "<craft>/helpers/deliver.py" "<project>" {--render \| --visuals <mp4>} [--mode split\|composite] [--composite] [--approve-in-chat] [--no-person --burn-subtitles]` | 过 `render_gate`（支持网页提交或 `--approve-in-chat`）；有真人口播默认分轨输出人物成片+无声画面成片+空隙字幕，加 `--composite` 合流单视频 |

退出码通用约定（适用于 `stage_cut.py` 与各检查/交付命令）：`0` 成功 · `1` 失败或闸门拦截 · `2` 前置条件不满足或用法错误；加 `--json` 返回机器可读字段。

---

## 二、常用任务与内部定位脚本（`helpers/_internal/` 与 `visual/scripts/`）

仅在需要细粒度转写、EDL 构建、诊断局部故障或单步调试时调用内部模块，不新建第二套工具入口：

### 1. 接上游、转写与 EDL 局部操作

```bash
# 上游交接与脚本哈希核对
node "<idea>/scripts/check-handoff-artifacts.mjs" --project "<上游项目>"
python3 "<craft>/helpers/_internal/check_script_hash.py" "<project>" --script "<script.md>" --plan "<visual-plan.json>"
python3 "<craft>/helpers/_internal/resolve_vault.py" --style "<style_id>"

# 首选在线词级转写（SeedASR 2.0，需 .env + node ws）与历史回退
python3 "<craft>/helpers/_internal/transcribe_seedasr.py" "<源视频>" --edit-dir "<edit>"
python3 "<craft>/helpers/_internal/transcribe.py" "<源视频>" --edit-dir "<edit>" --audio-track 0 --backend auto
python3 "<craft>/helpers/_internal/mlx_transcribe.py" "<源视频>" --edit-dir "<edit>"
python3 "<craft>/helpers/_internal/refine_transcript.py" "<edit>" --source <source> --asr <词级ASR.json>
python3 "<craft>/helpers/_internal/pack_transcripts.py" --edit-dir "<edit>"

# Keep-List 建 EDL、停顿检查与直接区间编辑
python3 "<craft>/helpers/_internal/edl_from_keep.py" "<keeps.json>" --edit-dir "<edit>" --snap-tol 0.35
python3 "<craft>/helpers/_internal/edl_edit.py" "<edit>" --delete "<起,止>=<原话>|<原因>"
python3 "<craft>/helpers/_internal/edl_edit.py" "<edit>" --restore "<起,止>=<原话>"
python3 "<craft>/helpers/_internal/check_edl.py" "<edit>" --max-pause 0.8
python3 "<craft>/helpers/_internal/apply_selection.py" "<edit>"

# 音质诊断、调色与多机位
python3 "<craft>/helpers/_internal/audio_diag.py" "<媒体>" --json
python3 "<craft>/helpers/_internal/measure_offset.py" "<主机位>" "<副机位>" --anchors 10 40
python3 "<craft>/helpers/_internal/mirror_edl.py" "<edl>" -o "<副EDL>" --source CAM2 --path "<副机位>" --offset "<秒>"
python3 "<craft>/helpers/_internal/grade.py" --help
```

### 2. 时间预演、上游对齐与字幕核查

```bash
python3 "<craft>/helpers/_internal/duration_plan.py" "<edit>"
python3 "<craft>/visual/scripts/align-visual-plan.py" --plan "<visual-plan.json>" --script "<script.md>" [--edit-dir "<edit>" | --srt "<SRT>"] --output "<alignment.json>"
python3 "<craft>/helpers/_internal/import_srt_timeline.py" "<project>" --srt "<SRT>" --alignment "<alignment.json>" --media "<音频>"
python3 "<craft>/helpers/_internal/check_caption_breaks.py" "<edit>/subtitles.srt" --json
```

### 3. Recompose 密度、蒙太奇素材、活舞台与审阅单步诊断

```bash
python3 "<craft>/helpers/_internal/recompose_plan.py" {init|check|lines} "<project>" ...
python3 "<craft>/helpers/_internal/scan_materials.py" "<project>/material/clips"
python3 "<craft>/helpers/_internal/check_montage.py" "<project>" [--shots-dir <work> --base <base.png> | --video <成片>]

python3 "<craft>/helpers/_internal/check_live_stage.py" "<project>"
python3 "<craft>/helpers/_internal/live_stage.py" "<project>" [--stop]
python3 "<craft>/helpers/_internal/build_review.py" "<project>" [--final-cut]
python3 "<craft>/helpers/_internal/review_surface.py" "<project>" [--surface-only]
python3 "<craft>/helpers/_internal/edl_preview_build.py" "<edit>"
python3 "<craft>/helpers/_internal/edl_review_surface.py" "<edit>" [--surface-only]
python3 "<craft>/helpers/_internal/check_review_playable.py" "<project>"
python3 "<craft>/helpers/_internal/check_review_template.py" [--prove]
python3 "<craft>/helpers/_internal/visual_review_feedback.py" "<project>"
python3 "<craft>/helpers/_internal/review_copy.py" "<成片>" [--no-downscale --no-audio --gop 0]
python3 "<craft>/helpers/_internal/review_slices.py" "<project>"
python3 "<craft>/helpers/_internal/preview_layers.py" "<edit>"
python3 "<craft>/helpers/_internal/studio_notes.py" "<project>" [--tail 20]
```

> 公共审阅模块诊断：`python3 "<craft>/helpers/_internal/lib/planners_modules.py" --check`（安装器自检仅在完整 `02-skills-library` 根目录运行）。

### 4. 渲染环境、一致性检查、包装与交付指纹（出片阶段用）

> 命令末尾**严禁**接管道 `| tail`（否则 `$?` 变成 `tail` 退出码，[GOTCHAS.md](../GOTCHAS.md) #82）；需要看日志尾部请重定向文件后再读。

```bash
python3 "<craft>/helpers/_internal/render_gate.py" "<project>" --out "<实际成片路径>"
python3 "<craft>/helpers/_internal/probe_env.py" "<project>"
python3 "<craft>/helpers/_internal/check_render_env.py" "<project>/composition" --json

# 在 <project>/composition 内执行渲染前设缓存与推荐 workers
export HYPERFRAMES_FONT_CACHE_DIR="$PWD/.hyperframes-cache"
W=$(python3 "<craft>/helpers/_internal/check_render_env.py" . --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["workers"])')
npx hyperframes render --workers "$W" -o /tmp/<name>.mp4 --resolution landscape -f 30 -q delivery

# 视觉/透明层/文字/运动校验
python3 "<craft>/helpers/_internal/render_layer.py" "<composition>" -o "<层主干名>"
python3 "<craft>/visual/scripts/encode_transparent.py" "<PNG目录>" -o "<overlay.mov>" --codec prores --fps 30
python3 "<craft>/helpers/_internal/check_alpha.py" "<overlay.mov>" --json
python3 "<craft>/helpers/_internal/check_overlay.py" "<edit>" --json
python3 "<craft>/helpers/_internal/check_motion_targets.py" "<project>" --json
python3 "<craft>/helpers/_internal/check_render_fidelity.py" "<project>" --video "<画面文件>"
python3 "<craft>/helpers/_internal/check_motion.py" "<编码视频>" [--expect-still] --json
python3 "<craft>/helpers/_internal/check_screen_text.py" "<project>" --help

# 工程预览渲染、严格校验与包装指纹
python3 "<craft>/helpers/_internal/render.py" "<edit>/edl.json" -o "<edit>/_engineering/cut.mp4" --preview --no-subtitles
python3 "<craft>/helpers/_internal/verify_av.py" "<edit>" --help
python3 "<craft>/helpers/_internal/verify_delivery.py" "<edit>" --video "<成片>" [--no-audio] --json
python3 "<craft>/helpers/_internal/export_video.py" "<project>" --mode {speaker|animation|composite|split} ...
python3 "<craft>/helpers/_internal/export_deliverables.py" "<edit>" --videos final.mp4 --srt subtitles.srt --out "<交付目录>"
python3 "<craft>/helpers/_internal/stage_deliver.py" {status|run|verify|export|fingerprint} --project "<project>" ...
python3 "<craft>/helpers/_internal/state_fingerprint.py" {capture|verify} "<project>"
python3 "<craft>/helpers/_internal/clean_edit_dir.py" "<edit>"
python3 "<craft>/helpers/_internal/spec_lint.py" [--json]
```
