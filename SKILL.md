---
name: video-craft
description: 承接 Video Idea System 的内容包、PPT Hell 的静态 SVG 或已有音视频，完成剪辑、实测时间绑定、动画、语义字幕、视听合成、人工审阅返修、交付核验与视频风格提取/进化。
---

# Video Craft

把已确定的内容做成可播放、可审阅、可返修的视频工程；作者要求出片后，再交付经核验的真实视频。

## 职责与判断

- video-idea-system 拥有内容主张、口播稿、念稿决定与 visual-plan；改变内容意义回上游确认。本 Skill 只接已成型的内容：有 `visual-plan.json`，或作者已有成片素材与定稿口播。从材料开始、连口播都还没定的新片不在这里开工，回 `video-idea-system`。
- planners-ppt-hell 拥有静态页及页面级视觉决定；Craft 读取批准页，负责声音、剪辑、时间绑定、字幕、动效和合成。
- planners-review-core 拥有桥、宿主、资产读取、草稿、提交和唤醒；Craft 拥有视频业务、播放验收和反馈解释。事实来源归上游内容包及其证据；Craft 不从动画或字幕反推事实。
- 模型判断取舍、语义断句、视觉分组、原页如何演出来和反馈的含义；工具执行重复机械动作，报告实际结果。工具退 0 不替代创作判断、作者确认或未覆盖的检查。

先剪点、后最终画面绑定。剪点改变时重新派生时间、字幕和画面锚点，并重建审阅；只改动效时保留不受影响的剪辑与字幕。未录音仍可做制作方案和 planned 预演，不能伪造实测字幕。

## 转录：优先在线服务，环境在 Skill 仓库根

词级时间同时决定剪辑、字幕和交付，**优先用在线转录服务**：豆包流式语音识别 2.0（SeedASR SAUC，`volc.seedasr.sauc.duration`），入口 `helpers/transcribe_seedasr.py`。它给逐词毫秒时间戳；`transcribe.py --backend ark`（doubao-seed-2.0-lite）是通用多模态模型，**不是 ASR**，不能拿来出词级时间（理由见 GOTCHAS #1）。Scribe 只作第二引擎交叉校验，本地 mlx-whisper 是最后手段；`transcribe.py --backend auto` 的 Scribe→Ark→mlx 是历史顺序，不代表推荐顺位。

**环境（本机这份 Skill 的所在）**：凭据写在本 Skill 仓库根的 `.env`，即 `02-skills-library/03-design-delivery/video-craft/.env`（Codex/Claude/Antigravity 三份 runtime 副本各读自己那份 `.env`）。不写进用户的视频目录，不写进任何文档、示例或提交。

| 键 | 属于 | 用途 |
|---|---|---|
| `DOUBAO_APP_ID` / `DOUBAO_ACCESS_TOKEN` | 火山引擎**语音技术**控制台（旧式 AppID/Token 对） | 首选：SeedASR 流式识别 |
| `ELEVENLABS_API_KEY` | ElevenLabs | 可选：Scribe 交叉校验 |
| `ARK_API_KEY` | 火山方舟 | 只作历史回退；**与语音控制台不是同一个账号**，替代不了 SeedASR |

运行环境：Node 22+，且 `ws` 必须装在**实际运行的那份副本**里（`cd <skill> && npm install ws`）。缺凭据时脚本会硬失败并说明缺哪个；缺 `ws` 时报的是 Node 的模块错误（带栈），按 [install.md](install.md) 第 5 步装上即可。没有可用凭据时如实停下问用户，**不许用别的模型伪造词级时间或字幕**。

## 接手时选入口与本轮终点

所有路径使用绝对路径；先读项目 `_idea/brief.md` 或旧项目的 `_idea/current.md`（两者等价）、`edit/project.md`、`production-plan.md`、已有反馈，再核采用版本。接手细节见 [content-to-production.md](references/content-to-production.md)。

| 输入 | 从哪里开始 | 本轮能交什么 |
|---|---|---|
| 内容已定，尚未录音 | 接入与制作方案（步骤 1–2） | 标 planned 的方案/独立预演与素材缺口 |
| 原始录音或视频要取舍 | 剪辑与逐字审阅（3–4） | 可操作的逐字剪辑面；确认后进时间与字幕 |
| 已剪音频 + SRT + 参考页 | 核版本，走 srt-import（5–6） | 对齐实声的工程审阅；不声称 EDL measured |
| 已确认剪点、词级依据、参考页 | 时间 → 原页拆解 → composition（5–8） | 可播、可听、可返修的动效审阅面 |
| 已录口播、**没有参考页**、画面是现成素材（或上游 `production_mode: "footage-montage"` 直通包） | 片型选 montage（2）→ 素材清单 → 镜头表（5）→ 渲染体检（7） | 侧边栏审阅面（可播）+ 镜头表 + 两关体检；三件套要等作者出片指令 |
| 外部参考视频或已完工项目，**专门提取新风格或进化已有风格** | 风格提取与进化（直接进 11，调 `helpers/extract_style.py`） | 新增或升级后的风格手册（`idea/page/craft.md` + 三联帧 `*-strip.jpg` + `2s .webm`）与更新后的可视化看板 |
| 返修/恢复项目 | 收件（9），按影响回到相应步骤 | 新快照与逐项处理回执 |
| 作者明确要求出片 | 交付前置与核验（10） | 实际视频、约定字幕、核验报告与有效指纹 |

**第 1–2 步先解析风格手册与片型**：运行 `python3 "<craft>/helpers/resolve_vault.py" --style <style_id>` 解析外挂风格库（`~/.config/planners/video-vault`；开源环境下未挂载时自动回退至内置 `author-spec.md` 与 `style-spec.md`）。画面是**造出来的**（`production_mode: "keyframe-svg"`，含页、图形、字卡、动效）→ `graphic`（recompose）；画面是**选出来的**（`production_mode: "footage-montage"`，如 `lifestyle-cult` 街头文化与商业档案快切，跳过 PPT Hell 直接带 `footage_request` + `kick_word` 进入 Craft）→ [montage-route.md](references/montage-route.md)。版式/画框另算一层，两种片型都可能要，见 [frame-spec.md](references/frame-spec.md)；旧 page 项目仅按 [legacy-page-route.md](references/legacy-page-route.md) 恢复。纯剪辑不强加参考页和动画步骤。

## 每轮终点：审阅页，不是成片

一轮工作的完成线是**侧边栏审阅页可播 + 本轮待办**。渲染不是完成，成片也不是每轮的默认产物。产物分两级，边界是硬的：

- `edit/_engineering/**` = **审阅素材**（工程态）：可随时重渲、可被审阅页消费，不算交付；
- `成品/**` = **交付件**：只有作者明确说「出片/交付」，且人工提交覆盖当前快照（`render_gate.py` 放行）才允许写入。

两条路线同样适用：recompose 的 `deliver.py` 第一件事就是 render_gate；montage 的 `montage.py render` 默认只写 `edit/_engineering/picture.mp4`，写 `成品/` 必须显式 `--deliver` 并过闸。渲出来、拷进成品目录、然后称之为交付，是这类工作最常见的错误——工具和文档都不为它留路。

## 主路线

阶段输入/输出、完成标准和完整操作顺序只维护在 [stages.md](references/stages.md)。开始当前阶段时读对应步骤，不能仅凭下表跳过完成标准。

| 阶段 | 步骤 | 进入时读 | 现有入口与模型工作 |
|---|---|---|---|
| 接入 | 1–2 | content-to-production；`resolve_vault.py` 返回的 author-spec 与 craft.md（或内置 style-spec）；preferences；recompose-mode（第 1 步）；caption-modes 与 montage-route／frame-spec（第 2 步定片型、字幕形态与画框）；creative-direction；visual-direction | 核版本，解析外挂风格手册，写 production-plan；定片型、字幕形态与画框 |
| 剪辑 | 3–4 | stages 的声音/逐字审阅；tools 的声音与剪辑；review-ui（剪辑面独立打开的宿主判据：源 >200MB 或内存 <8GB 时走本地宿主） | stage_cut；模型定取舍并用既有 EDL 工具表达 |
| 时间与字幕 | 5–6 | caption-article-first；visual-timeline（三个时间坐标） | duration_plan、srt_export、timeline_derive 或 SRT 导入；模型校对与分组 |
| 画面 | 7 | film／montage-route（按片型）；composition-craft；visual-rendering；timing-lock（缺一不渲）；frame-animation-pipeline（自定义逐帧时） | graphic：film 拆解后写 composition；montage：镜头表 + montage 渲染 + check_montage 体检 |
| 审阅与返修 | 8–9 | review-ui；live-stage-contract；hyperframes-review-adapter | review 构建并验播放；review_inbox 收件后改源、重建 |
| 交付 | 10 | timing-lock；delivery | 按现有交付顺序逐项执行；实际文件核验后才交付 |
| 收尾与风格提取 | 11 | preferences；[style-extraction.md](references/style-extraction.md)；`helpers/extract_style.py`（`packet` → `check` → `apply` / `lint`） | 按四步提取协议（工具采样 → 四问填表 → 机械校验 → 落盘并提交本地 Git）进化现有风格或从参考片新建风格 |

本目录还有两类不在主路线上的东西：`skills/manim-video/` 是数学与技术动画的独立制作管线，只在严密数学或技术动画时按 `$manim-video` 调用（见 [stages.md](references/stages.md) 的画面一节）；`archive/` 是已退役实现的存档，只供定位旧项目、读历史字幕与旧页面经验，不是制作入口，主路线不会调用它。

上述简称均指 references 下同名 Markdown。命令参数与可复制调用集中在 [tools.md](references/tools.md)，不要自行拼一套替代脚本。

## 完成判据（按本轮目标适用）

| 目标 | 必须提供的证据 |
|---|---|
| 接入/未录音预演 | 来源、已定内容、缺口、计划与 planned 标记；未完成事项明确 |
| 逐字剪辑审阅 | 按当前 EDL 定位源媒体，选择/改字能保存，正式提交有回执；应用后重建 |
| 工程审阅（默认终点） | 当前时间来源明确；适用时 film verify 通过；`check_review_playable.py` 退 0（播放通道、时长、画面与声音都对）；侧边栏 surface 已打开；本轮待办已列出 |
| 蒙太奇工程 | 素材清单每条都已登记（含「不可用」原因，`plan` 会拒未登记或没写画面一句话的行）；`montage.py plan` 退 0；`check_montage.py --shots-dir` 逐镜与 `--video` 成片两关都过；**并已打开侧边栏审阅页**（终点是审阅，渲染只是中间产物） |
| 成片交付（需作者明确指令） | 作者出片指令、当前版本人审依据、未决意见处理、timing-lock、实际文件核验与有效交付指纹；`edit/_engineering/` 里的文件不能当交付件。严格检查未完成或失败就不声称能发 |
| 每轮收尾 / 独立风格提取 | 反馈处理与剩余问题可追溯；运行 `helpers/extract_style.py` 完成已有风格演进或新风格初始化（`--bootstrap`），产出三段式规则（`idea/page/craft.md`）、三联帧与 `2s` 预览并刷新看板 |

工程审阅不需要先渲整片。素材转码、声音处理、确认剪点后的工程底片、montage 的镜头渲染都属于素材准备，缓存到 `edit/_engineering/`；快照要重建才反映源的变化，不能把旧页面称为热更新。交付件只在上面「每轮终点」的边界内产生。

两个制作审阅面继续保留：逐字面处理取词/气口/改字；动效面处理播放、逐句密度、调整请求和批注。念稿与静态页面审阅仍归上游。草稿保存、正式提交、模型收件、源修改是不同动作；回执成功后才说已保存/已应用。

## 维护入口

遇到故障、准备优化或新增工具，先读 [architecture.md](references/architecture.md)：它规定模块归属、依赖失效范围、Debug 流程、新脚本准入与验证分级。机械工作包及其实际验收记录只登记在 [implementation-brief.md](references/implementation-brief.md)，不能把设计目标说成现有能力。

当前机械交付入口聚合合成与严格核验，只有二者通过才输出总 ok。render_gate 只检查当前快照的提交覆盖及内容来源，不理解意见是否已解决；作者出片指令与未决项处理仍由模型核对。stage_deliver 保留分动作调用，包装后仍须核副本并记录新指纹。
