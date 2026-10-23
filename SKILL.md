---
name: video-craft
description: 承接 Video Idea System 的内容包、PPT Hell 的静态 SVG 或已有音视频，完成剪辑、实测时间绑定、动画、语义字幕、视听合成、人工审阅返修与交付核验。
---

# Video Craft

把已确定的内容做成可播放、可审阅、可返修的视频工程；作者要求出片后，再交付经核验的真实视频。

## 职责与判断

- video-idea-system 拥有内容主张、口播稿、念稿决定与 visual-plan；改变内容意义回上游确认。
- planners-ppt-hell 拥有静态页及页面级视觉决定；Craft 读取批准页，负责声音、剪辑、时间绑定、字幕、动效和合成。
- planners-review-core 拥有桥、宿主、资产读取、草稿、提交和唤醒；Craft 拥有视频业务、播放验收和反馈解释。事实来源归上游内容包及其证据；Craft 不从动画或字幕反推事实。
- 模型判断取舍、语义断句、视觉分组、原页如何演出来和反馈的含义；工具执行重复机械动作，报告实际结果。工具退 0 不替代创作判断、作者确认或未覆盖的检查。

先剪点、后最终画面绑定。剪点改变时重新派生时间、字幕和画面锚点，并重建审阅；只改动效时保留不受影响的剪辑与字幕。未录音仍可做制作方案和 planned 预演，不能伪造实测字幕。

## 接手时选入口与本轮终点

所有路径使用绝对路径；先读项目 `_idea/current.md`、`edit/project.md`、`production-plan.md`、已有反馈，再核采用版本。接手细节见 [content-to-production.md](references/content-to-production.md)。

| 输入 | 从哪里开始 | 本轮能交什么 |
|---|---|---|
| 内容已定，尚未录音 | 接入与制作方案（步骤 1–2） | 标 planned 的方案/独立预演与素材缺口 |
| 原始录音或视频要取舍 | 剪辑与逐字审阅（3–4） | 可操作的逐字剪辑面；确认后进时间与字幕 |
| 已剪音频 + SRT + 参考页 | 核版本，走 srt-import（5–6） | 对齐实声的工程审阅；不声称 EDL measured |
| 已确认剪点、词级依据、参考页 | 时间 → 原页拆解 → composition（5–8） | 可播、可听、可返修的动效审阅面 |
| 返修/恢复项目 | 收件（9），按影响回到相应步骤 | 新快照与逐项处理回执 |
| 作者明确要求出片 | 交付前置与核验（10） | 实际视频、约定字幕、核验报告与有效指纹 |

有视觉制作时，新项目固定走 recompose；旧 page 项目仅按 [legacy-page-route.md](references/legacy-page-route.md) 恢复。纯剪辑不强加参考页和动画步骤。

## 主路线

阶段输入/输出、完成标准和完整操作顺序只维护在 [stages.md](references/stages.md)。开始当前阶段时读对应步骤，不能仅凭下表跳过完成标准。

| 阶段 | 步骤 | 进入时读 | 现有入口与模型工作 |
|---|---|---|---|
| 接入 | 1–2 | content-to-production；author-spec 全篇；preferences；creative-direction；visual-direction | 核版本，写 production-plan；风格确定后读 style-spec 对应节 |
| 剪辑 | 3–4 | stages 的声音/逐字审阅；tools 的声音与剪辑 | stage_cut；模型定取舍并用既有 EDL 工具表达 |
| 时间与字幕 | 5–6 | caption-article-first；caption-modes；visual-timeline | duration_plan、srt_export、timeline_derive 或 SRT 导入；模型校对与分组 |
| 画面 | 7 | film；recompose-mode；composition-craft | film 拆解；模型写 composition；需要 HyperFrames 时读 $hyperframes |
| 审阅与返修 | 8–9 | review-ui；live-stage-contract | review 构建并验播放；review_inbox 收件后改源、重建 |
| 交付 | 10 | timing-lock；delivery | 按现有交付顺序逐项执行；实际文件核验后才交付 |
| 收尾 | 11 | preferences；故障时读 architecture 的 Debug 流程 | 记录本片处理结果，候选在项目验证后集中升级 |

上述简称均指 references 下同名 Markdown。命令参数与可复制调用集中在 [tools.md](references/tools.md)，不要自行拼一套替代脚本。

## 完成判据（按本轮目标适用）

| 目标 | 必须提供的证据 |
|---|---|
| 接入/未录音预演 | 来源、已定内容、缺口、计划与 planned 标记；未完成事项明确 |
| 逐字剪辑审阅 | 按当前 EDL 定位源媒体，选择/改字能保存，正式提交有回执；应用后重建 |
| 动效工程审阅（默认终点） | 当前时间来源明确；适用时 film verify 通过；review 运行时检查通过，并确认 live 通道、时长、画面与声音；交付当前 surface 和待办 |
| 成片交付（需作者明确指令） | 当前版本人审依据、未决意见处理、timing-lock、实际文件核验与有效交付指纹。严格检查未完成或失败就不声称能发 |
| 每轮收尾 | 反馈处理与剩余问题可追溯；无新候选就记录“本轮无新判准”，不为凑数量改 Skill |

工程审阅不需要先渲整片。素材转码、声音处理、确认剪点后的工程底片属于素材准备，缓存到 edit/_engineering；成片是独立的交付动作。快照要重建才反映源的变化，不能把旧页面称为热更新。

两个制作审阅面继续保留：逐字面处理取词/气口/改字；动效面处理播放、逐句密度、调整请求和批注。念稿与静态页面审阅仍归上游。草稿保存、正式提交、模型收件、源修改是不同动作；回执成功后才说已保存/已应用。

## 维护入口

遇到故障、准备优化或新增工具，先读 [architecture.md](references/architecture.md)：它规定模块归属、依赖失效范围、Debug 流程、新脚本准入与验证分级。机械工作包及其实际验收记录只登记在 [implementation-brief.md](references/implementation-brief.md)，不能把设计目标说成现有能力。

当前机械交付入口聚合合成与严格核验，只有二者通过才输出总 ok。render_gate 只检查当前快照的提交覆盖及内容来源，不理解意见是否已解决；作者出片指令与未决项处理仍由模型核对。stage_deliver 保留分动作调用，包装后仍须核副本并记录新指纹。
