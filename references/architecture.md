# 架构与维护规则

本文回答“该改哪个 owner、改动会让哪些产物过期、怎样证明结果可用”。制作顺序与完成标准只维护在 [stages.md](stages.md)，命令与参数只维护在 [tools.md](tools.md)。改动前先读本文；未实现的机械修复见 [implementation-brief.md](implementation-brief.md)。

## 1. 系统边界：创作判断与机械保证

```text
输入与作者决定 → 模型选择阶段并完成语义判断 → 调用当前 owner
        ↑                         ↓                  ↓
  反馈与返修 ← 解释审阅结果 ← 人审提交 ← 可播放的工程快照
                                                   ↓ 作者要求出片
                                  编码 → 文件核验 → 包装与指纹
```

- **模型与作者负责含义**：剪哪句、怎样断句、哪些 cues 组成一个视觉步骤、批准原页怎样演成动画、反馈实际要求改什么。内容意义、静态页面决定或作者批准不交给脚本猜测。
- **工具负责可重复的事实**：区间映射、时长计算、格式转换、版本/路径检查、快照构建、文件写入、播放加载与媒体核验。工具成功只证明它覆盖的检查通过，不自动证明语义、审美、作者批准或未执行的步骤。
- **生产闭环**：原始素材与上游批准内容 → EDL / 字幕与时间绑定 → composition → 工程审阅与返修 → 作者明确要求出片后编码和核验。可回到受影响阶段，不要求每种输入都从头跑完。
- **维护闭环**：本轮症状和产物 → 定位首个错误事实与 owner → 项目内验证 → 必要时集中升级 owner 文档、实现和验收 → 清除旧口径。项目个例保留在项目；历史记录解释变更，不充当当前规则。

## 2. 权威出处

| 问题 | 唯一 owner | 其他位置如何做 |
|---|---|---|
| 任务从哪里开始、本轮停在哪里 | [SKILL.md](../SKILL.md) | 入口、目标分支和读取指针 |
| 各阶段输入、动作、产物、完成/返回条件 | [stages.md](stages.md) | 不在入口或工具手册复写另一套流程 |
| 模块职责、依赖、维护与新脚本准入 | 本文 | 变更前读取 |
| 现有命令及参数 | [tools.md](tools.md)；准确语法以命令 `--help` 为准 | 不从 help 推断阶段顺序或批准语义 |
| 时间来源与证据等级 | [visual-timeline.md](visual-timeline.md) | 字幕和交付引用它，不把消费者称为来源生产者 |
| 画面、字幕和项目字段契约 | 对应专项文件，如 [film.md](film.md)、[recompose-mode.md](recompose-mode.md)、[caption-article-first.md](caption-article-first.md) | 只引用，不复制字段规则 |
| 渲染前置、交付核验和补位 | [timing-lock.md](timing-lock.md)、[delivery.md](delivery.md) | 明确区分规则要求与当前实现覆盖 |
| 视觉判断、风格与作者偏好 | [author-spec.md](author-spec.md)、[style-spec.md](style-spec.md)、[preferences.md](preferences.md) | 按阶段读取；不要把项目偏好写成通用工具逻辑 |
| 审阅业务与播放/宿主接缝 | [review-ui.md](review-ui.md)、[live-stage-contract.md](live-stage-contract.md)、[hyperframes-review-adapter.md](hyperframes-review-adapter.md) | 公共传输能力归 planners-review-core |
| 故障候选、已发生升级、待实现修复 | 根目录 `GOTCHAS.md`、[maintenance-history.md](maintenance-history.md)、[implementation-brief.md](implementation-brief.md) | 候选、历史、待实现三种状态不可混用 |

## 3. 模块 owner 与工具边界

| 模块 | 唯一责任与现有 owner | 不承担什么 |
|---|---|---|
| 接入与版本 | 上游交接文档、`check_script_hash.py`、项目 `edit/project.md` 与 `production-plan.md` | 不改写上游主张或静态页面决定 |
| 剪辑 | `stage_cut.py` 协调；`edl_from_keep.py`、`edl_edit.py`、`apply_selection.py`、`check_edl.py` 与 `edl_preview_build.py` 表达和检查剪辑事实 | 模型仍决定语义取舍；应用选择不表示下游产物已更新 |
| 时间与字幕 | `_edl.py` 选择与当前 EDL 匹配的时长记录；`duration_plan.py` 生成 projected；`srt_export.py` 持有文章/字幕生成；`timeline_derive.py` 与 `import_srt_timeline.py` 分别持有 EDL 与外部 SRT 时间轴生成 | 不从最终视频倒推剪点；字幕字级插值不等于 ASR 词级锚点 |
| 画面 | `film.py` 建立原页拆解依据，`recompose_plan.py` 管模式与逐句视觉密度；模型按批准内容写 composition | `film.py verify` 不能代替语义保真和审美判断 |
| 工程审阅 | `review.py` 是编排入口；调用活舞台检查、`live_stage.py`、`build_review.py`、surface 与运行时播放检查 | 不把旧快照说成热更新，不自动收件或修改源 |
| 反馈 | `review_inbox.py`、`visual_review_feedback.py` 持有收件、绑定、拒收/去重和密度回写 | 不把“有提交”当成作者批准或问题已解决 |
| 交付 | `deliver.py` 负责现有合成入口；`verify_delivery.py` 持有严格文件判据；`export_deliverables.py` 与 `state_fingerprint.py` 负责包装和版本状态；`stage_deliver.py` 是分动作兼容适配器 | `deliver` 或 wrapper 的一次成功不等于严格核验、包装、指纹都完成 |
| 共享机械能力 | `_paths.py`、`_timecode.py`、`_probe.py`、`_words.py`、`_silence.py`、`_cutmap.py` 复用各自的路径、时间码、媒体探测、词、静音和剪后映射实现 | 不新增第二份通用解析器或项目事实源 |
| 外部执行环境 | HyperFrames 拥有新 composition 的播放时钟、媒体同步与 clip 显隐；FFmpeg 执行编码；planners-review-core 拥有审阅桥与宿主 | Craft 不复制官方播放器时钟或公共宿主 |

`stage_cut.py` 与 `stage_deliver.py` 是现有阶段适配器，不是完整工作流引擎。`status` 的命令成功只说明查询成功；它不能单凭文件存在断言阶段已完成。当前完成线和修复证据见 Brief B1–B5；作者确认不从文件存在或提交记录自动推断。

## 4. 跨 Skill 与外部接缝

| 对接方 | 对方拥有 | Craft 接收/交回 | 返修路由 |
|---|---|---|---|
| `video-idea-system` | 内容主张、口播稿、念稿决定、`visual-plan.json` 与来源依据 | 按当前交接契约核采用版本、对齐 Beat 与媒体；不从画面或字幕推导新事实 | 要改内容、事实或必见信息，回 Idea 确认后再接入 |
| `planners-ppt-hell` | 批准的静态页面、SVG 快照及页面级视觉决定 | 视觉项目核页面版本；当前路线用 `film.py` 拆解原页，再手写 composition；Craft 不替页面重做静态设计 | 静态构图或页面事实要变，回 PPT Hell；局部动画与时间绑定由 Craft 处理 |
| `planners-review-core` | surface/bridge、草稿和提交传输、宿主、资产读取与唤醒 | Craft 提供视频审阅业务、播放验收、反馈解释及 inbox；页面草稿、正式提交、收件和源修改是不同状态 | 桥/宿主/文件传输故障查 Core；视频播放、绑定和反馈语义查 Craft |
| HyperFrames / FFmpeg | 播放器、composition 时钟与媒体运行时 / 编码器及媒体滤镜 | Craft 调用并在自己的合同边界检查输入、配置与真实结果 | 引擎行为查对应版本；Craft 包装、参数或合成语义查现有 owner |

### 两种制作审阅面

逐字剪辑面负责取词、气口、错字和 EDL 选择；动效/合成面负责播放、密度、画面反馈与批注。Idea 的念稿审阅和 PPT Hell 的静态页面审阅分别仍归上游。它们审阅对象不同，保持独立；交棒条件由 [review-ui.md](review-ui.md) 持有。

### 工程播放的接缝归属

| owner | 输入 → 输出 | 修改时必查 |
|---|---|---|
| live_stage | 项目/composition → 经资源归属核验的编译路由 | HTTP 200 或同名 project id 不是本工程证明；检查引用资产的真实归属 |
| live_preview | 编译路由与项目 → 内联工程、素材清单与 hash | 不透明宿主的资产传输、路径包含性；不增加第二个播放时钟 |
| build_review / review_copy | 工程与媒体 → 快照与预算内审阅副本 | 时长与声音保留；代理不能回写或替代生产源 |
| 官方 player + review-page-template | 快照 → 播放、定位、倍速、字幕和反馈位置 | 统一播放头；握手或静态截图不等于实际可播 |
| review-core + review_inbox | 用户提交 → 文件回执 → 视频业务反馈 | surface 路径、snapshot/unitId、草稿/提交分离、幂等和旧版意见处理 |

当前静态检查仍要求源工程带 composition-embed-bridge，而 live_preview 传输阶段过滤旧桥；这是未完全收齐的兼容接缝，不能凭“官方 player 已接管”直接删桥。改变桥时同时验源检查、传输和旧项目；详见 live-stage-contract。review_inbox 的密度回写经 recompose_plan.apply_record，不能新增另一个 lines 写者。

### 当前路线与兼容代码

新视觉项目走 recompose：批准页面是信息与构图依据，`film.py` 拆解后由模型写 composition。旧 page 工作流已归档；缺少 `recompose.json` 时，`review.py` 不会自动把项目当作 page 路线，而会要求先初始化/恢复到受支持的项目形态。`legacy-page-route.md` 只供旧项目恢复。

部分旧导入器或生成器仍因兼容代码、旧快照读取或测试而保留；“路线已归档”不等于“所有模块已无调用者”。移除前要搜索生产调用方和测试，再迁移调用与测试；没有清零证据，不删 shim 或兼容模块。

## 5. 共享事实与时间证据

| 对象 | 生产者/权威 | 消费方式与边界 |
|---|---|---|
| `edit/edl.json` | 当前剪辑决定 | 源区间、速度与删除内容的依据；改变后重建依赖的时间/字幕/画面锚点 |
| `edit/segment_durations.json` | `render.py` 写入多个渲染记录，`duration_plan.py` 可写解析预演 | `_edl.py` 按 EDL 身份和记录类型选择；旧记录可留作历史，不能按文件位置挑一条 |
| `timeline/grouping.json` | 创作判断输入 | 存视觉分组和语义字段；不能从 EDL 自动猜成用户决定 |
| `timeline/timeline.json` | `timeline_derive.py`（EDL）或 `import_srt_timeline.py`（外部 SRT） | 下游统一的时间消费接口；EDL 与外部 SRT 有不同事实链。新项目显式写入项目根 `timeline/`，恢复旧项目先确认消费者与落点 |
| `composition/` | 当前项目视觉源；模型按拆解与已批准内容创作 | 工程审阅演当前源，交付渲染当前源；draft、代理与 `_engineering/` 缓存不成为生产源 |
| `review/review_data.json` 与提交 | 构建器生成快照；作者/页面生成提交 | 快照和提交绑定到当时版本；收件回执只表示处理状态，不自动等于出片批准 |
| 最终媒体与报告 | `deliver.py` 及交付工具链 | 真实文件的严格检查通过后才可报告交付；输出指纹只证明其绑定状态 |

时间来源含义只在 [visual-timeline.md](visual-timeline.md) 定义。工程预演、EDL 实测与外部 SRT 是不同证据链；词时间、时间轴来源与记录必须相符。B8 已支持显式来源升级与冲突路径拒绝；恢复项目按 tools 的迁移步骤操作，不手改标签。

当前版本证明使用 SHA-256：`render_gate` 拒绝缺清单、缺关键来源或内容漂移；视觉缓存与本次选用的合成素材分别记录内容身份。提交覆盖当前快照仍不代表未决意见已获作者确认；详见 Brief B7 与交付文档。

## 6. 改动的失效范围

先判断“源事实变了吗”，再只重建其下游消费者：

| 变化 | 必须重建或重新确认 | 通常可保留 |
|---|---|---|
| 内容稿、上游契约或批准页面 | 采用版本、受影响的原页拆解、Beat/视觉绑定与审阅快照 | 未受影响的素材缓存 |
| EDL 区间、变速或源媒体 | 同版时长、字幕锁与派生、timeline、画面锚点、审阅；旧交付版本失效 | 不受影响的视觉意图，之后重新绑定 |
| 字幕文字、断句或 correction | 文章/词序锁与 cues、分组绑定、字幕显示和审阅；必要时交付 | 未变的 EDL 与源媒体 |
| timeline 分组或时间来源 | 对应 timeline 及下游锚点、composition、审阅；不得手改派生产物掩盖源差异 | 不相关的字幕语义与资产 |
| composition、动效密度或绑定 | 活舞台/构建检查、审阅快照、新版人工审阅；若出片则重新交付 | 未受影响的剪辑与字幕事实 |
| review adapter、surface 或页面 | 公共 surface 校验、宿主打开、播放与提交/收件链 | 生产 composition 与 EDL |
| 合成选项、字幕形态或媒体文件 | 新合成产物、真实文件核验、包装和指纹 | 来源匹配且仍有效的画面缓存 |
| 成片二次剪 | `edit/cut-map.json`、同一映射的字幕和严格交付核验 | 剪前母版及其证据 |

改动剪辑、字幕或画面后，旧审阅快照不能证明新版本已被审。只改动效时不要求无关剪辑和字幕重做；只改字幕文本时也不重跑无关素材转码。

## 7. 每次使用后的 Debug 闭环

1. **保留现场**：在项目已有 `edit/project.md` 或反馈处理表记录症状、输入/版本、命令与退出码、预期/实际、日志路径；保留失败产物，不覆盖唯一母版。
2. **找首个坏事实**：沿源/版本 → EDL → 字幕/时间 → composition → 审阅 → 成片顺序检查。下游黑屏先区分编译、素材传输、播放器时钟和媒体轨，不先归咎场景。
3. **定位 owner**：语义误判改阶段判据/项目决定；漏步骤改 `stages.md`；命令参数或退出语义错改既有工具 owner；格式/身份错配查生产者、契约与消费者；真实编码/映射错改现有实现。
4. **做最小复现**：保留正常例、失败例与不适用边界。测试验证用户可观察结果，不能只验证某个函数被调用。一次性项目救急可写在项目目录，不自动变成 Skill 脚本。
5. **只修当前 owner**：先扩展现有入口/判据；查直接调用者、调用方文档、旧说明与相关用例。用数据依赖表声明哪些产物失效，不顺手扩大修改范围。
6. **复测并收尾**：同一输入跑前后；记录通过、失败、跳过与未覆盖宿主。项目完成验证后，再按授权集中更新 Skill，并清理被替代规则/调用/验收。

最小复盘记录：`症状 → 首个坏事实 → owner → 最小修复 → 正常/失败验收 → 重建范围 → 项目修复或通用候选`。已有项目记录可承载，不为此建立一套永久工单或状态数据库。

## 8. 新脚本准入与减法

默认扩展/修复现有 owner，不把“脚本少”当唯一目标。新增脚本前必须在 Brief 中回答：

- 现有 owner 为什么不能承担这条行为；
- 新入口有哪些真实调用方、固定输入/输出与失败信号；
- 它替代哪个旧调用或重复维护点；
- 怎样验证结果没有把机械工作转嫁给模型；
- 哪些兼容入口、文档、测试和发布物需要同步。

只有出现独立的变化原因/生命周期，或多个真实消费者需要共享同一实现，才建立新模块。单纯转发参数、复制 parser、再做一份相同检查的 wrapper 不准入。新判据优先加入负责模块和现有测试文件；迁移时一次替换一个消费者，兼容语义未迁完前保留旧 CLI。迁完搜索调用者，再删被替代实现。不要新增 `craft.py` 总 CLI、播放器、宿主、通用状态数据库或自动工作流框架。

## 9. 验证与发布

本次验证必须现场执行；以前绿灯不能代替当前结果。基线已有失败时先判断它是否属于本次改动，不能通过删除/跳过来隐藏。

| 改动 | 本轮验证 | 不可据此声称 |
|---|---|---|
| 文档/路由 | Skill lint、有效链接检查、命令参数核对、代表场景走读、实现文件哈希无变化 | 文档补写等于代码已具备能力 |
| 单模块工具 | 先在旧实现复现；正常/失败/边界回归；实际入口；受影响项目副本对照 | 只因测试数量增加就证明行为可靠 |
| 时间、审阅、交付接缝 | 相关和全量测试、真实项目副本前后对照；适用时播放/定位/倍速/声音/提交/收件/改源/重建/旧快照拒绝 | 静态 lint 等于浏览器播放或真实交付通过 |

文档升级至少检查：

```bash
python3 <planning-before-create-skill>/scripts/lint_skill.py <craft>
python3 helpers/spec_lint.py
python3 helpers/check_review_template.py
python3 helpers/check_review_template.py --prove
python3 -m json.tool evals/evals.json >/dev/null
```

工具实现按 Brief 的包级验收；浏览器测试默认运行，skip 原因要逐项说明。真实项目只用副本或明确授权的项目；维护测试不渲成片、不制造人工批准。报告实际改动、结果和未覆盖面，不引用历史数字代替本次结果。

Skill 发布只从 `02-skills-library` 源目录进行：按根目录 `AGENTS.md` / 库根 `PUBLISHING.md` 先 dry-run，再通过项目唯一发布器同步 runtime；校验三端。独立 GitHub 镜像发布前读 PUBLISHING、检查密钥闸门与完整目录。已有未提交改动要保留，并在结果中区分其来源，不能把它们说成此次实现。
