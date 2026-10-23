# 工具实现 Brief 与验收

状态：**B1–B8 已完成实现与本地验收**（2026-10-23）。保留下列范围、验收与回退合同，实际结果见本页末尾。未新建统一 CLI、stage 脚本或状态数据库；模块 owner 与 Debug 方法见 architecture.md。DSH 宿主未实测，不能把本地宿主结果视为双宿主通过。

## 执行范围与保护

只修改本 Skill 库源及下列工作包涉及的现有测试。用户已确认总体文档设计；本 Brief 供下一模型接手具体实现，先核当时用户分配的是哪些工作包。默认先 B1，再 B2/B3；B4/B5 独立；B6/B7 是后续，不需要为了首轮交付一起做完。

先读当前工作区 diff（含未跟踪文件），保存基线。既有 cut-map、concept-film 等改动属于已有工作，不能覆盖。测试用临时项目/真实项目复制件；不写用户正在审阅的工程，不伪造作者批准，不启动付费转写、不擅自出成片。兼容旧 CLI 与旧项目；当前外部依赖缺失如实失败，不把异常吞成成功。

不做：大规模搬目录、删 legacy shim、重写播放器、改 review-core 公共协议、合并两种审阅面、添加 craft.py/新 stage_*、重做画面风格、无限迁移所有 ffprobe 调用。

## B1 · 交付结果必须有一致的成功语义（最高优先）

**证据 / 起点**：helpers/deliver.py 末段写 delivery_verdict，却仅从 checks 汇总 report.ok；strict verifier 非零仍可能整体退出 0。stage_deliver.py do_run 随后提示 capture 指纹，没有运行独立 verify。stages 旧 M5 文档说明过“提示模式”，不能继续把它称为严格成功。

**修改 owner**：deliver.py 的结果汇总、stage_deliver.py 的下一步提示；严格判据继续由 verify_delivery.py 持有，禁止复制判据。

**目标**：对可核验的 EDL 项目，严格核验失败、核验进程异常/报告不可解析、关键核验未执行时都不得输出“可交付”的 ok=true 或进入 capture 提示。合成成功与可交付分别可见；总成功只在本次适用必检项通过时成立。错误保留 verifier 原因与下一步 owner。

**验收**：
- 合成检查全绿 + strict verifier 非零 → 总退出非零、报告不可交付、无成功捕获提示。
- verifier 退 0 且合成检查通过 → 成功；非 JSON/崩溃/缺必要字段 → 失败而非空 hard=[] 绿灯。
- 只有过期交付指纹时：仍允许重新渲染/核验，新的输出核验后再 capture；旧指纹只拦发送，不能造成重渲死锁。查 verify_delivery/state_fingerprint 的实际依赖后再接线。
- 外部 SRT 无 EDL：明确“未完成严格核验”及 B6 边界，不强造 EDL、不静默放行。B6 完成后再给该路径正式成功条件。
- 用真实复制件对比一次正常和一次刻意错字幕/时长的结果；不需要重渲整片即可验证时优先复用已批准产物。

## B2 · 默认交付入口承担既定机械前置

**起点**：SKILL 旧步骤 7/10 要求 film verify、动效检查、HyperFrames check、环境探测；deliver 当前仅自动覆盖部分。stage_deliver.run 和 deliver 都调用 render_gate。

**修改 owner**：deliver.py 为默认成片执行入口；stage_deliver 保留兼容转发与独立子动作。render_gate 继续负责版本覆盖，不吸收审美/反馈解释。

**目标**：把 timing-lock 中适用的机械检查接入现有默认入口，在启动昂贵编码前执行；显式已有 visuals 不应绕开来源/版本检查。外层 wrapper 不再重复调用同一 gate；直接调用 deliver 仍受保护。纯剪辑继续使用既有 render 路径，不强加 film/recompose。

**验收**：缺映射/错误 selector/源漂移/环境硬错误时均非零，且断言 FFmpeg/HyperFrames 编码没有启动；正常成片路径一次 gate；经 wrapper 与直接调用结果等价；默认缺/过期视觉层拒绝，显式 --render 才渲。低内存告警按现有 delivery 的预算例外处理，不意外变成全量禁渲。

**人的职责**：当前反馈是意见文本，不能可靠自动推断“已解决”。保留人工核查未决项与作者出片指令；不要把“有提交”改写为“作者批准”。若需要新增批准 schema/按钮，先单独对齐交互范围，此包不做。

## B3 · 修正交付选项的端到端接线

**证据**：stage_deliver 的 --no-audio 帮助标为 verify 选项，do_verify 未传递；do_run 却传给不接受该参数的 deliver。deliver 的 burn 分支检查 libass，但当前合成命令未见字幕滤镜。

**修改 owner**：stage_deliver.py、deliver.py 现有选项及对应测试；不新增 CLI。

**验收**：
- stage_deliver verify --no-audio 把选项传到 verify_delivery；同一无声画面轨声明后通过适用检查，不声明时拒绝。
- run 的 --no-audio 要么明确拒绝“不支持的动作组合”，要么在单独确认无声合成范围后真正支持；不要把不认识的参数传下去。
- 有 libass 时 --burn-subtitles 的输出帧确实包含一条已知字幕（字幕时段与非字幕时段对比），报告与实际一致；缺 libass 在编码前明确失败；默认外挂不改变画面。
- 有/无人物两条路径都覆盖烧录和外挂；正确转义空格/非 ASCII 路径；字幕内容和时间不被转义逻辑篡改。

## B4 · 审阅检查使用本轮工程事实

**证据**：review.py _expected_duration 在 build_review 前读取旧 review_data.json；编辑时长后可能被当成端错工程。无法比对时长分支会记录 true。live_stage 已有工程路由身份检查，时长不应代替身份。

**修改 owner**：review.py 的编排与检查结果；有需要才修改 live_stage 的身份接口及测试。不要改播放器时钟。

**验收**：旧快照 10s、当前源/时间轴 12s，重建后应按 12s 验；同长但来自另一个工程不能通过；缺必要身份/时长证据不能标 true；运行时真实 duration/seek/画面/声音检查继续执行。失败的单个前置保留可机器读取的错误与修复位置。对本地宿主和 DSH 的结果分别报告，没有 DSH 实测不要声称双宿主全过。

## B5 · 阶段提示与真实产物一致

**起点**：stage_cut prepare 在没有 edl 时只提示需要建 EDL，却无条件建议 review；apply 后直接提示下一时间阶段，未保证逐字预览重建；status 只检查文件存在。stage_deliver status 也仅按产物存在推下一步。

**修改 owner**：两个 stage 文件的现有状态/提示逻辑，必要时复用已有指纹或选择消费记录；不新增项目状态数据库。

**验收**：无 EDL 时 prepare 可以完成“转写打包”，但下一步必须是模型确定取舍并用已有工具建 EDL，不能称剪辑已完成；apply 后提示/执行重建逐字面，再进入时间阶段；存在过期文件不能证明完成；相同选择重试按现有语义验证幂等或明确需确认，不能重复破坏 EDL。status 的 ok 仅说明查询成功，结果需区分文件存在与阶段完成。

## B6 · 外部 SRT 的真实交付证据（后续独立包）

**起点**：import_srt_timeline 支持 srt-import，但 verify_delivery 主要面向 EDL；deliver 无 EDL 时跳过严格核验。文档不能弥补这个覆盖缺口。

**先做**：读取 import_srt_timeline、verify_delivery、项目 alignment/timeSource 字段，给出最小输入契约：当前媒体身份/实测时长、SRT 身份、alignment 与 timeline 绑定、真实交付文件。优先扩展 verify_delivery 的既有接口，不复制另一套 verifier。

**验收**：合法外部音频+SRT 正常通过；错版媒体、过长字幕、失配 alignment、旧交付副本均拒绝；结果仍标 srt-import，绝不伪造 measured EDL；EDL measured 与 projected 的原规则不回归。没有事实字段足以证明时先提交明确 schema 差异供确认，不无依据补数值。

## B7 · 缓存与版本证明（后续独立包）

**起点**：render_gate 的 manifest_drift 目前读 size/mtime；deliver 的缓存判断对显式 --visuals 与默认路径不同。先盘点已有 sourceHash/sourceManifest/state_fingerprint，复用现成指纹方案。

**验收**：同大小/同 mtime 但内容不同的源能被识别；缺清单或关键条目不能当完整证明；有效旧项目兼容有明确迁移提示；显式外部视觉层须能声明来源或明确人工确认，不能自动冒充当前 composition 输出。转换不得要求所有项目同时迁 schema，不用每次扫描无关 GB 素材证明局部 CSS 修改。

## B8 · 工程预演升级为实测的时间合同（首轮交付前完成）

**证据**：srt_export._measured_durations 在已有 timeline 声明 projected 时向 _edl.duration_record 传 require_projected=True；即使新实测记录存在仍选预演。声明 nominal/未标来源时直接用标称时间；声明 measured 时普通查询仍可退到 projected。_paths.timeline_file 又先找 edit/timeline 再找项目根：仅显式写项目根不会淘汰旧副本。因此“渲完后直接重跑字幕与 timeline”没有可靠的单向升级保证。

**修改 owner**：_edl 的记录选择合同、srt_export 的调用、_paths 的路径解析；timeline_derive 仅在来源传递需要时调整。复用 test_time_source、test_srt_export、test_timeline_equivalence、test_measured_total、test_paths，不新增独立校验器或平行时间文件。

**目标**：工程预演与正式实测由明确模式/输入证据选择；已有派生 timeline 不能永远锁住升级。优先在现有命令扩展显式来源选择，默认兼容；由执行者提出最小参数差异并在同包更新 help/tools。不能用手写 timeSource=measured 把旧时间数值改名为实测。若读取两处 timeline，必须识别歧义，不能一个消费者读旧文件、另一个写新文件。

**验收**：
- 相同 EDL，两段 projected=[1.0,1.0]，新 measured=[1.1,1.2]；旧 timeline=projected。通过既有入口的明确升级动作后，caption_words 标 measured，第二段 offset=1.1，总长=2.3，timeline 与字幕同步；保留 semantic_lines 的已审文字。
- 只有 projected 时，工程模式成功；请求 measured 时明确失败。旧指纹/错误段数/无指纹记录不得伪装强实测；measured 字段不是证据。
- nominal/缺标记旧项目有可执行恢复步骤；两处时间轴冲突时报告各自来源并要求选择/迁移，不覆盖唯一旧文件；统一后所有消费方读取同一版。
- EDL 改动时旧实测不再可用；只改视觉 CSS 不触发字幕重建；外部 srt-import 仍走自己的来源链。
- 给出一次临时项目完整命令实跑：projected → 字幕 → timeline → 写入真实测量记录 → measured 升级 → 字幕/timeline 重建 → 检查。再用真实项目复制件核一遍，不能只测试内部函数。

## 工作包顺序与验证入口

先 B1 统一失败语义，再处理 B8 时间升级；B2/B3 在同一 deliver owner 上顺序执行，避免同时改同一文件。B4/B5 可单独领取；B6/B7 为后续包。B1 可以先正确拒绝缺证据的交付，不必等待 B6 就放行外部 SRT。每包必须留下独立可审 diff 与验证证据；不要把全部包塞成一次重构。

在 Skill 根使用已确认依赖齐全的 Python，设置 `PYTHONPATH=helpers:tests`、FFmpeg/Node 在 PATH；完整测试命令见 README。优先运行的现有模块：

| 包 | 首批测试（先加旧实现失败例） | 必须观察的结果 |
|---|---|---|
| B1 | test_deliver、test_stage_scripts、test_edit_contracts | 顶层退出码、报告与下一步提示一致 |
| B2 | test_deliver、test_render_gate、test_render_env、test_film | 适用前置失败时编码未开始；直接与 wrapper 入口一致 |
| B3 | test_deliver、test_stage_scripts | 参数端到端传递；真实输出帧存在烧录字幕 |
| B4 | test_review_playable、test_live_preview、test_recompose | 当前源时长/身份，而非旧 review_data；播放链无退化 |
| B5 | test_stage_scripts、test_edl_review | 下一步提示匹配当前事实与重建状态 |
| B6 | test_import_srt_timeline、test_edit_contracts、test_deliver | 合法外部来源通过；错版/过期来源失败 |
| B7 | test_render_gate、test_fingerprint_nested、test_deliver | 同大小同 mtime 内容变化仍可识别 |
| B8 | test_time_source、test_srt_export、test_timeline_equivalence、test_paths | projected 可明确升级；缺实测不伪装；读写落点一致 |

失配时先修归属模块，不改原始素材、用户批准记录或跨 Skill 公共协议来让用例过。测试前查当前实现与 CLI，本文的证据是 2026-10-23 检查结果，接手时可能已有其他修复；已通过行为不要重复实现。

## 每包的提交和完成规则

1. 运行当前基线并记录日志；最小失败例必须先在旧实现表现出问题，正常例作为对照。用既有 test 文件优先；测试断言用户结果，不仅断言调用了某函数。
2. 一包一份可审 diff，不夹带其它包；测试数减少时列替代覆盖与理由。参数兼容、退出码、报告语义和重建范围同包更新。
3. 相关测试通过后跑全量 unittest、review template 与 prove、spec_lint、planning lint；skip 原因逐项说明。真实项目复制件走受影响链；审阅改动至少包括构建→播放定位/倍速/声音→提交→inbox→改源→重建→旧快照拒绝。测试提交仅在复制件中，不能用于生产渲染批准。
4. 报告实际改动、原故障复现、修复后正常/失败结果、未覆盖宿主或场景、CLI 兼容、是否增加文件及必要性。
5. 仅在行为已通过验收后，修改 delivery/tools/stages 的对应补位说明，把本包标完成并链接验证证据；保持未实现包的待执行状态。
6. 按 AGENTS/PUBLISHING 发布完整 Skill：本地 dry-run → all → 三端核对；GitHub 密钥闸门与显式提交身份 → 推送验证。没有验收通过不以“已写代码”标完成。

## 2026-10-23 实际验收

基线在允许本地宿主/浏览器的隔离副本运行：503 项通过（131.740s）。最终全量：**537 项通过，99.063s，无 skip**。新增 34 项，没有减少既有覆盖；无指纹旧记录的断言改为 measured-guessed，保留可读性但不充当强实测。早期受限沙箱 EPERM 与错误复制布局不计为通过。

| 包 | 实际结果与证据 |
|---|---|
| B1 | strict 非零、崩溃、坏 JSON、缺字段、矛盾报告均阻断总成功；正常合成与严格核验分别报告。手冲咖啡成片复制件正常通过，刻意追加超长字幕失败；旧交付指纹不妨碍重新核验。`test_deliver` |
| B2 | 默认入口在编码前核环境、适用 film、HyperFrames、selector/transform 与来源；显式已有画面也不能绕过。wrapper 不重复 gate；失败用例断言生产编码未启动。`test_deliver`、`test_render_env`、`test_render_gate`、`test_film` |
| B3 | verify --no-audio 端到端传递，真实无声轨不声明失败、声明后通过；run 明确拒绝。FFmpeg7/libass 真实输出帧证明人物/无人物两种烧录，默认外挂不改画面；缺滤镜提前失败，中文/空格/引号/冒号路径通过。`test_deliver`、`test_import_srt_timeline`、`test_stage_scripts` |
| B4 | 当前源 12s 不再读取旧 10s 快照；本机项目 API 的实际服务目录证明身份，同长异工程拒绝；缺证据不放行。手冲咖啡隔离副本通过真实编译、定位、2x 播放、旁白时钟、字幕切换、提交、inbox、改源重建和旧快照拒绝。副本中仅将原有内联执行代码移至外部文件以满足现行契约；母版未改。检查器另修复注册名写死 main，采用 composition 根的实际注册名。DSH 未实测。`test_review_playable`、`browser_review_smoke.py` |
| B5 | 无 EDL 的 prepare 指向模型取舍；apply 写一次消费回执、重建逐字面，相同选择重试不重剪；EDL 后续变化要求重新确认。status 区分文件存在、当前性、机械完成及人工确认。`test_stage_scripts`、`test_edl_review` |
| B6 | 用户确认 --media 合同，旧外部项目补选现有音频即可；真实小媒体从旧导入失败 → 补选音频通过。换音频、SRT/alignment/来源/绑定失配、字幕超长、旧交付副本失败；结果保持 srt-import。未引入 EDL 假证据。`test_import_srt_timeline`、`test_edit_contracts` |
| B7 | 同大小/同 mtime 换内容、来源删除、清单/关键条目/哈希缺失、显式未证实画面均拒绝；有效 proof 可复用，人工确认可补记旧缓存/外部画面。v3 指纹覆盖嵌套交付和实际选用素材，按引用/现有来源清单哈希使用素材，不扫描无关原片。`test_render_gate`、`test_fingerprint_nested`、`test_deliver` |
| B8 | 真实 FFmpeg 小夹具 projected [1,1] → measured [1.1,1.2]，词 offset=1.1、总长=2.3、字幕与 timeline 同步，已审文字不变；keywords-video 元数据复制件通过同一升级链。缺/旧指纹、坏段数、假 measured 标签失败；双路径冲突要求保留备份后统一。`test_time_source`、`test_paths`、`test_timeline_equivalence` |

模板静态检查与 9 个缺陷自证、spec_lint、planning lint、链接/JSON/diff 检查均通过。planning lint 的 4 处提示已核为工程资产、公共 tokens 及两个既有示例。未执行付费转写、生产成片渲染或伪造生产批准；未做新的独立创作质量模型评测。

原始红/绿日志、完整差异和真实副本证据保存在 `/private/tmp/video-craft-implementation-20261023`（临时目录可能被清理）；B1 原始单包 diff 为 B1.patch，后续按 owner 和工作包整理审阅差异。永久回归在本 Skill tests/；未来更改必须重跑，不能继承本次绿灯。

兼容与迁移：旧 CLI 保留；新增可选 --time-source、--media、--visuals-confirm-current。旧项目可读取，正式 measured/外部来源/缓存使用需补足对应证据；旧 v2 delivery 指纹在实际文件核验后重新 capture v3。新增持久文件仅为 `selections.applied.json`（避免重复应用同一选择）和 `<visuals>.sources.json`（绑定缓存内容与来源），没有新增平行验证器或中心状态库。
