---
name: video-craft
description: 承接上游制片总控内容包、静态参考页或已有音视频，完成剪辑、实测时间绑定、动画与实机演示、语义字幕、视听合成、人工审阅返修与交付核验。
---

# Video Craft

把已定内容做成可播放、可审阅、可返修的视频工程；作者明确指令出片后，再交付经严格核验的真实视频。领域术语见 [GLOSSARY.md](GLOSSARY.md)，常见缺陷防线见 [GOTCHAS.md](GOTCHAS.md)。

## 职责边界与核心顺序

- 上游 `video-manager` 拥有选题、口播定稿与风格库治理；改变内容意义回上游。`planners-ppt-hell` 拥有静态参考页；`planners-review-core` 拥有审阅桥与宿主。
- 本 Skill 负责声音、剪辑、实测时间绑定、语义字幕、画面与实机演示同轨制作、工程审阅返修与交付核验。模型做取舍、断句、视觉表达与反馈解释；工具执行机械动作，**先剪点后定画面时间**，剪点一改就重派生时间、字幕与审阅快照。

## 转录与凭据（优先在线服务，环境在 Skill 仓库根）

词级时间戳同时决定剪辑、字幕和交付，**优先用在线转录服务**：豆包流式语音识别 2.0（SeedASR SAUC，`volc.seedasr.sauc.duration`），入口 `helpers/stage_cut.py prepare`（默认自动优先路由至 `helpers/_internal/transcribe_seedasr.py`）。`helpers/_internal/transcribe.py --backend ark` 是通用多模态模型，**不是 ASR**，禁用于自动回退与词级时间（见 [GOTCHAS.md](GOTCHAS.md) #1）。Scribe 仅作第二引擎交叉校验，本地 `--backend mlx` 为离线最后手段。

**环境（本机 Skill 仓库根）**：凭据只写在本 Skill 仓库根的 `.env`（即 `02-skills-library/03-design-delivery/video-craft/.env`；Codex / Claude / Antigravity 副本各读自己的 `.env`），绝不写入用户素材目录或任何提交。首次配置见 [install.md](install.md)。

| 键 | 属于 | 用途 |
|---|---|---|
| `DOUBAO_APP_ID` / `DOUBAO_ACCESS_TOKEN` | 火山引擎**语音技术**控制台 | 首选：SeedASR 词级流式识别 |
| `ELEVENLABS_API_KEY` | ElevenLabs | 可选：Scribe 交叉核对 |
| `ARK_API_KEY` | 火山方舟 | 历史回退，替代不了语音控制台 SeedASR |

运行环境要求 `ffmpeg` / Python 3.9+ / Node 22+，且在**实际运行的副本**执行 `cd <skill> && npm install ws`。缺凭据时如实停下询问，严禁伪造词级时间。

## 三条生产路线 + 一个共用底座

第 1–2 步先运行 `python3 "<craft>/helpers/_internal/resolve_vault.py" --style <style_id>` 解析外挂风格手册（未挂载时自动回退内置 [author-spec.md](references/author-spec.md) 与 [style-spec.md](references/style-spec.md)，准入见 [preferences.md](references/preferences.md)），并锁定本项目的 **`production_mode`（三选一）**：

| 模式 (`production_mode`) | 适用场景 | 画面主线 | 进入时先读 |
|---|---|---|---|
| `pure-talking` | 纯口播精剪 + 字幕 | 不捏造视觉页与动画；直走剪辑 → 字幕 → 审阅/口播成片 | [stages.md](references/stages.md)、[captions-and-audio.md](references/captions-and-audio.md) |
| `footage-montage` | 档案/实拍/照片蒙太奇 | 跳过 PPT Hell；素材清单 → 镜头表 → 分块渲染 → 两关体检 | [montage-route.md](references/montage-route.md)、[intake-and-frames.md](references/intake-and-frames.md) |
| `keyframe-svg` | 图形演进/理论拆解/实机演示 | `film.py init` 四档分拍 → 手写 composition / 演示段 → 统一画面体检 | [visual-grammar.md](references/visual-grammar.md)、[visual-checks.md](references/visual-checks.md) |

> 版式/画框（`helpers/frame.py`）是横切层，与 `footage-montage` / `keyframe-svg` 正交，规格见 [intake-and-frames.md](references/intake-and-frames.md)。

### 共用底座步骤（完整契约见 [stages.md](references/stages.md)）

| 阶段 | 步骤 | 顶层公开入口（`helpers/`） | 进入时读（`references/`） |
|---|---|---|---|
| 接入与定方案 | 1–2 | `frame.py`（需要画框时）；`helpers/_internal/check_script_hash.py` | [intake-and-frames.md](references/intake-and-frames.md)、[author-spec.md](references/author-spec.md)、[style-spec.md](references/style-spec.md)、[preferences.md](references/preferences.md) |
| 声音与逐字剪辑 | 3–4 | `stage_cut.py`、`audio_fix.py`、`audio_mix.py` | [captions-and-audio.md](references/captions-and-audio.md)、[review-and-delivery.md](references/review-and-delivery.md) |
| 语义字幕与时间脊柱 | 5–6 | `srt_export.py`、`timeline_derive.py` | [captions-and-audio.md](references/captions-and-audio.md)、[visual-timeline.md](references/visual-timeline.md) |
| 画面制作 | 7 | `film.py` + `check_visual.py`（或 `montage.py`） | [visual-grammar.md](references/visual-grammar.md) / [montage-route.md](references/montage-route.md)、[visual-checks.md](references/visual-checks.md) |
| 工程审阅与返修 | 8–9 | `review.py`、`review_inbox.py` | [review-and-delivery.md](references/review-and-delivery.md) |
| 严格核验与交付 | 10 | `deliver.py`（或 `montage.py --deliver`） | [review-and-delivery.md](references/review-and-delivery.md)、[visual-timeline.md](references/visual-timeline.md) |

全部 **12 个顶层公开入口**与底层 `_internal` 诊断调用清单集中在 [tools.md](references/tools.md)；模块边界、失效范围与历史迁移索引维护在 [architecture.md](references/architecture.md) 与 [gotchas-index.md](references/gotchas-index.md)。

## 每轮终点：审阅页，不是成片

- `edit/_engineering/**` = **审阅素材**（工程态，可重渲、不算交付）；
- `成品/**` = **交付件**（必须同时满足「作者明确出片指令」+「审阅快照零漂移且存在网页提交或对话授权 `--approve-in-chat`」；有真人口播与画面层时默认分轨导出 `人物成片 + 无声画面成片 + 空隙字幕`，单视频合流用 `--composite`）。

| 常见来料起点 | 首选动作 | 本轮可交付证据 |
|---|---|---|
| 已定稿，尚未录音 | 完成第 1–2 步 | `edit/project.md`、`production-plan.md` 与 `planned` 预演 |
| 原始录音 / 口播视频 | 跑第 3–4 步 | 在线词级转写 + 逐字剪辑审阅页；应用选择后重建 |
| 已确认剪点或外部 SRT | 跑第 5–8 步 | 语义字幕、时间轴与 `check_review_playable.py` 绿灯审阅页 |
| 返修或恢复项目 | 先跑 `review_inbox.py` | 收件回执 → 改源（不动未波及轨）→ `review.py` 重建新快照 |
| 作者明确出片 | 过渲染前置并交付（第 10 步） | 真实媒体文件（`-14 LUFS / -1.5 dBTP`）、严格核验报告与交付指纹 |
