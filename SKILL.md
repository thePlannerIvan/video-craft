---
name: video-craft
description: 触发分支：剪口播、做词级粗剪与加语义字幕（从原始录音或口播视频起步）；已定稿未录音出制作方案与预演；外部音频配 SRT 建时间轴；叠加画框、实拍混剪、Remotion 4 动效或实机录屏并配双轨声景；收到审阅反馈后收件返修；作者明确指令导出成片。
---

# Video Craft

把已定内容做成可播放、可审阅、可返修的视频工程；作者明确指令出片后，再交付经严格核验的真实视频。术语见 [GLOSSARY.md](GLOSSARY.md)，缺陷防线见 [GOTCHAS.md](GOTCHAS.md)。

## 职责边界与核心顺序

- **上游与宿主边界**：`video-manager` 拥有选题、口播定稿与风格库治理（改内容主张回上游）；`planners-ppt-hell` 拥有静态参考页；`planners-review-core` 拥有审阅宿主。
- **本 Skill 职责与铁律**：负责声音、剪辑、实测时间绑定、语义字幕、画面与实机演示同轨制作、工程审阅返修与交付核验。**先剪点后定画面时间**，剪点一改即重派生时间、字幕与审阅快照。
- **每轮默认终点是审阅页，不是成片**：`edit/_engineering/**` 属于可重渲审阅素材；写 `成品/**` 须同时满足「作者明确出片指令」与「当前审阅快照已有网页零漂移提交，或当轮对话明确指令导出传入 `--approve-in-chat --approval-note "<作者原话>"`」（见 [review-and-delivery.md](references/review-and-delivery.md)「3. 按段分流交付顺序、`deliver.py` 与务实会话出片授权」）。

## 常见来料起点与重入路由

| 常见来料起点 | 直接跳到 | 首选动作与入口 | 本轮终点与可交付证据 |
|---|---|---|---|
| **已定稿，尚未录音** | 第 1–2 步 | `helpers/frame.py resolve` + `helpers/_internal/resolve_vault.py` | `edit/project.md`、`production-plan.md` 与 `planned` 预演 |
| **原始录音 / 口播视频** | 第 3–4 步 | `helpers/stage_cut.py prepare` → `review` → `apply` | 在线词级转写 + 逐字剪辑审阅页；应用选择后重建 |
| **已确认剪点或外部 SRT** | 第 5–8 步 | `helpers/srt_export.py` + `helpers/timeline_derive.py` | 语义字幕、时间轴与 `helpers/_internal/check_review_playable.py` 绿灯审阅页 |
| **返修或恢复项目** | 第 9 步 | `helpers/review_inbox.py` → 只改受影响源 → `helpers/review.py` | 收件回执 → 改源（不动未波及轨）→ 重建新快照交审 |
| **作者明确出片** | 第 10 步 | `helpers/_internal/render_gate.py` + `helpers/deliver.py --render` | 真实媒体文件、严格核验报告与交付指纹落盘 `成品/**` |

## 能力组合、正交画框与阶段总览

第 1–2 步先运行 `python3 "<craft>/helpers/_internal/resolve_vault.py" --style <style_id>` 解析 Style Card v3（读取 `style.md`、`palette`、`anchors`、`patterns`、可选 `preferred_frame` 与全局底线 `G01–G05`/`V01–V05`；未挂载时自动回退开源六套风格与底线 [author-spec.md](references/author-spec.md)、[style-spec.md](references/style-spec.md) 及 [preferences.md](references/preferences.md)）。**`style` 只定审美与风格领词（Style Leading Words），与能力组合及画框 `frame` 完全正交**。

工程采用 **固定底座 `剪口播` × 可选叠加 `footage` / `motion` / `screen-demo`（0–3 项） × 正交画框 `frame.py`**，共 13 个公开入口（[tools.md](references/tools.md)）与 10 步阶段契约（[stages.md](references/stages.md)）：

| 层次与阶段 | 核心组件与入口 | 产出与关键机制 | 进入时先读 |
|---|---|---|---|
| **固定底座 · 剪口播（第 3–6 步）** | `stage_cut.py`、`audio_mix.py`、`srt_export.py`、`timeline_derive.py` | 词级剪辑、**Voice Polish**（默认 `podcast-warm` 含 `--debreath`）、语义字幕与唯一时间脊柱 | [stages.md](references/stages.md)、[captions-and-audio.md](references/captions-and-audio.md) |
| **正交画框（第 1–2 步）** | `frame.py`（`build` / `preview` / `resolve`） | 唯一横/竖屏与人物孔位几何真源，完全独立于风格与能力组合 | [intake-and-frames.md](references/intake-and-frames.md) |
| **可选叠加 · `footage`（第 7 步）** | `scan_materials.py`、`montage.py`、`storyboard.json` | 5s 防重与素材清单 → 分镜切片；审阅挂代理、交付 FFmpeg 直切原片 | [montage-route.md](references/montage-route.md) |
| **可选叠加 · `motion`（第 7 步）** | `remotion_runtime.py`、`film.py`、`check_visual.py` | 默认 **Remotion 4** 外部运行壳；无参考页先过 **Look-Dev**；SVG 走 `import-svg` | [remotion-engine.md](references/remotion-engine.md)、[visual-grammar.md](references/visual-grammar.md) |
| **可选叠加 · `screen-demo`（第 7 步）** | `film.py proxy`、`check_visual.py`、`deliver.py` | 审阅挂轻代理，交付直切高清原录屏（开清晰文字保护）并护卫静态资产区 | [visual-checks.md](references/visual-checks.md) |
| **可选声景 · 声景双轨（第 7 步）** | `sound_design.py`（`build` / `verify`） | 消费 `storyboard.json` 生成 **Visual Soundscape** 起伏声景与闪避底噪 | [captions-and-audio.md](references/captions-and-audio.md) |
| **审阅与交付（第 8–10 步）** | `review.py`、`review_inbox.py`、`deliver.py` | 自适应 `{kw: 1}` 活舞台审阅；授权后过门禁分轨导出 `人物成片` / `画面成片` / 字幕 | [review-and-delivery.md](references/review-and-delivery.md)、[visual-timeline.md](references/visual-timeline.md) |

全部 **13 个核心公开入口**（含兼容入口 `helpers/audio_fix.py`）与 `_internal` 诊断调用见 [tools.md](references/tools.md)；模块边界与历史迁移索引见 [architecture.md](references/architecture.md) 与 [gotchas-index.md](references/gotchas-index.md)。

## 环境与转写前置

- **优先用在线转录服务**：`helpers/stage_cut.py prepare` 默认首选 **SeedASR** 2.0（`helpers/_internal/transcribe_seedasr.py`）；`helpers/_internal/transcribe.py --backend ark` 是通用多模态模型，不参与词级转写与自动回退（[GOTCHAS.md](GOTCHAS.md) #1）。缺凭据时如实停下询问，严禁伪造词级时间。
- **凭据位置**：只放在本 Skill 仓库根的 `.env`（含 `DOUBAO_APP_ID` / `DOUBAO_ACCESS_TOKEN`，可选 `ELEVENLABS_API_KEY` 交叉核对，及显式非词级 `ARK_API_KEY`），绝不写入用户素材目录或提交；首次配置与 4 键说明表见 [install.md](install.md)。
- **运行依赖**：要求 `ffmpeg`、Python 3.9+、Node 22+，并在实际运行的副本目录执行 `cd <skill> && npm install ws`；首次启用 `motion` 运行 `python3 "<craft>/helpers/remotion_runtime.py" setup` 备齐外部运行壳（项目内零 `node_modules`）。
