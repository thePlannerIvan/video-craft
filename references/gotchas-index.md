# GOTCHAS 历史迁移索引与当前不变式（`gotchas-index.md`）

本页仅保存已升级/已合并的 GOTCHAS 历史编号索引与仍在生效的跨版本不变式（现行规则见 [SKILL.md](../SKILL.md) 与 `references/` 各 owner；实时条目与 enforcement 见 [GOTCHAS.md](../GOTCHAS.md)）。


这一节收「只活在历史里、但今天仍然有效」的规则与已升级/已合并 GOTCHA 迁移索引；现行规则见 [SKILL.md](../SKILL.md) 与 `references/` 各 owner。

### 当前不变式

- **GOTCHAS 有条数上限，新增必须走迁移索引**：`GOTCHAS.md` 正文只留当前仍会造成错误的条目，每条必须有 enforcement 指针；已升级/已合并的从正文移出，只在本节迁移索引留一行。上限由 `tests/test_gotchas.py` 的 `MAX_GOTCHAS` 锁定为唯一数字源，加新条目之前先合并或迁移，不新增正文条目。
- **仍记账的现存缺陷**（2026-10-14 记下，至今未消除，别当成已修）：无口播视觉槽在这套契约里还不成立（字幕要求 EDL 每段有词、`timeline_derive` 的 step 必须由 cue 组成）；`check_edl` 对删字这类合法编辑永远亮红；`apply_selection.py` 会留下纯标点的碎片段，与 `srt_export.py` 的一段一块硬约束冲突；时间轴的步长是 cue 派生的（比媒体窗口窄一个片头静音），要不要统一基准需要一次决定。
- **timeline 落点仍在观察**：`edit/timeline/` 与项目根 `timeline/` 的历史兼容未收口；新项目显式写项目根，恢复旧项目先确认消费者与落点（现行规则见 [architecture.md](architecture.md) 的共享事实表）。
- **两个审阅面不合并**：视觉审阅与剪辑审阅是两套业务页面与两份反馈形状，共享 `review-surface/2.0.0` 宿主接缝，但不互相嵌套。

### GOTCHAS 迁移索引（2026-10-19）

这些条目已由代码/测试/公共宿主承接，正文从 `GOTCHAS.md` 移出，仅留索引。

- #8 A leftover review server serves the wrong project ｜ 已升级（剪接线那台自带服务器 `edl_preview_serve.py` 已退役，宿主归公共缝）
- #9 Register the timeline after the DOM, in the same script ｜ 已升级
- #14 Screen recordings are VFR — force CFR before compositing ｜ 已升级
- #16 The picture carries content, never method ｜ 已升级
- #17 One cue per natural clause — the ceiling is not a grouping rule ｜ 已升级
- #23 `hyperframes render --help` advertises WebM transparency; only the MOV half is true ｜ 已升级
- #25 A freshly extracted segment was never read back ｜ 已升级
- #26 Delivery gates picked the render record by position ｜ 已升级
- #27 The page importer's href boundary was the page directory ｜ 已升级
- #28 Inlining a page by hand bypasses the href rewrite ｜ 已升级
- #29 The same id in two pages makes `#name` ambiguous ｜ 已升级
- #30 A criterion that can never fail ｜ 已升级
- #31 `hyperframes doctor` does not check the font cache ｜ 已升级
- #32 注入点必须裸着独占一行，而且只许一个 ｜ 已升级
- #35 出口与内容不许取决于"恰恰会失败的那件事"（R11） ｜ 已升级
- #36 测量工具在测量自己 ｜ 已升级
- #37 想要"写沙盒"就**硬链接**，别用软链 —— 宿主会（正确地）拒绝 ｜ 已升级
- #38 浏览器用例：**一个类共用一个浏览器**，而且失败也要关 ｜ 已升级
- #39 交付审阅页必须启动 HTTP 审阅宿主，绝不能直接 open 本地 file:// 路径 ｜ 已升级（已确立为铁律，机制在 review-core 宿主那一侧）。
- #66 GSAP 握手不证明 HyperFrames 播放正常 ｜ 已升级
- #67 不透明源访问 loopback 和跨帧 blob 都可能被拦 ｜ 已升级
- #68 编译路由的 base 不是 HTML 路径的父目录 ｜ 已升级
- #74 审阅副本坏了不报错：页面照播，只是没声 ｜ 已修
- #76 「画面」这一步以前没有入口，于是实现了自己重画原页 ｜ 已升级（`helpers/film.py` 与 `tests/test_film.py`）
- #77 画面层会把内容画进字幕区，字幕一压就废 ｜ 已升级（`helpers/deliver.py` 与 `tests/test_deliver.py`）

### GOTCHAS 合并索引（2026-10-19）

同根条目合并进宿主条目，正文只留宿主；症状与修正原则已并入宿主条目。

- #5 Cloud-synced video folders make ffmpeg fail intermittently ｜ 并入 #52 编码产物不要直接写进云同步目录
- #46 云同步目录里刚建的目录，下一个进程可能看不见 ｜ 并入 #52 编码产物不要直接写进云同步目录
- #60 `hyperframes preview` 在沙箱下静默不起，而且它的路由只能验内容 ｜ 并入 #63 studio 会缓存 composition —— 改了源，你要硬刷新它
- #64 studio 的 player 路由剥掉所有 `src=` 脚本，并把内联脚本拼成一个大脚本 ｜ 并入 #63 studio 会缓存 composition —— 改了源，你要硬刷新它
- #65 「第几个脚本」不能当锚点，「第一个内联 script」尤其不能 ｜ 并入 #63 studio 会缓存 composition —— 改了源，你要硬刷新它
- #69 `hyperframes render --workers auto` 按核数开满 Chrome → 小内存机器被 swap 打崩 ｜ 并入 #70 首次渲染的 compile 是冷启动（约 25 分钟），会被误判成「这台机器渲不动」
- #51 lint 会把运行期 `if` 当成「补间一定存在」 ｜ 并入 #62 静态检查的两个假阳：对正确代码报红，训练出来的只是忽略
- #54 删掉标记、却没删挂事件的代码 → 页面死在渲染数据之前 ｜ 并入 #57 审阅页的护栏是两具尸体 —— 不跑的测试等于没有测试
- #72 `segment_durations.json` 的键是输出文件名的 stem，渲到非权威名会静默留下旧记录 ｜ 并入 #61 composition 用旧时间轴打过补丁 → 过期 3 秒，无人发现
- #15 `-t` between two inputs belongs to the second input ｜ 并入 #83 `-t` 写在两个输入之间
- #20 `render.py --no-loudnorm` cannot take an `-o` that equals the internal base name ｜ 并入 #84 `--no-loudnorm` 的 `-o` 撞 base

### GOTCHAS 迁移索引（2026-11-08）

- #22 三个不同根因并成一条 ｜ 已拆分为 #82–84（2026-11-08；旧编号不复用）

### GOTCHAS 迁移索引（2026-11-27 · HyperFrames 冻结只读归档）

v3 起 Remotion 4 成为默认主动效引擎，以下仅作用于冻结 HyperFrames 旧引擎工程的条目从 `GOTCHAS.md` 正文迁出，编号不复用（历史只读兼容项目仍可按需检索）：

- #10 `onStart` callbacks do not replay under a seek-driven render ｜ 已归档/冻结兼容（HyperFrames 暂停时间轴回调在 seek 下不重放）
- #48 composition 里 CSS 初始 transform 与 GSAP 补间会互相抢 ｜ 已归档/冻结兼容（`hyperframes check` 规则与根元素属性）
- #50 composition 缺 viewport meta 会让浏览器整体缩放页面 ｜ 已归档/冻结兼容（HyperFrames 骨架 viewport meta）
- #61 composition 用旧时间轴打过补丁 → 过期 3 秒，无人发现 ｜ 已归档/冻结兼容（HyperFrames `__SPANS__` 与 `composition/` 重派生）
- #63 studio 会缓存 composition —— 改了源，你要硬刷新它 ｜ 已归档/冻结兼容（`hyperframes preview` 缓存与 `live_stage.py`）
- #70 首次渲染的 compile 是冷启动（约 25 分钟），会被误判成「这台机器渲不动」 ｜ 已归档/冻结兼容（HyperFrames 暖缓存与 `check_render_env.py` 并发预算）
- #74 `hyperframes check` 全绿 ≠ 审阅页能播：内联脚本在 srcdoc 里永不执行 ｜ 已归档/冻结兼容（`check_live_stage.py` 与外置 `src/*.js`）
- #79 渲染退出 0、check 全绿，画面却从第 78 秒起整段没画：多 worker 截图丢内容 ｜ 已归档/冻结兼容（`--workers 1` 与 `check_render_fidelity.py`）

### GOTCHAS 迁移索引（2026-11-27 · 40→10 清淤：已淘汰旧路线与旧引擎，6 条）

以下 6 条仅作用于已淘汰的旧对比/旧 SVG 动效/浏览器录屏/WebM 透明预览或跨栈坐标移植，从 `GOTCHAS.md` 正文迁出，编号不复用：

- #24 Re-rendering a project rendered before 2026-09-25 changes its bytes ｜ 已淘汰历史记录（`-bitexact` 与旧字节哈希对比；交付身份改以规范 EDL 与图像核验为准）
- #40 SVG 空间布局平移 (Layout Transform) 与 WAAPI 动效平移冲突覆盖 ｜ 已淘汰旧路线（旧 SVG+WAAPI 动效模板坑；现行主动效走 Remotion `useCurrentFrame()`）
- #41 Headless Browser Screencast 在 `<video>` 元素上的 IPC 缓冲区死锁 ｜ 已淘汰旧路线（`export_video.py` 浏览器录屏方案已停用，实拍与动效走 Remotion 截帧 + FFmpeg 拼合）
- #44 审阅页要能合成层，就必须有一份浏览器可合成的载体 ｜ 已淘汰旧载体路线（MOV+WebM 双透明层路径，现行默认按段分流或 Remotion 活舞台直渲）
- #45 VP9 的 alpha 是带外的：不点明解码器就抽不出来 ｜ 已淘汰旧载体解码（随 #44 透明 WebM 叠层路线迁出；工具能力保留于 `encode_transparent.py`）
- #49 PIL 的 rotate 是逆时针为正，CSS 的 rotate 是顺时针为正 ｜ 已淘汰旧迁移坑（逐帧 PIL 脚本改写 HTML/CSS 的历史坐标系差异）

### GOTCHAS 迁移索引（2026-11-27 · 40→10 清淤：旧审阅页模板一次性修复，9 条）

以下 9 条审阅页模板与测试护栏缺陷已由代码修复与静态门禁（`check_review_template.py` / `review_surface.py`）一次性锁死，从 `GOTCHAS.md` 正文迁出：

- #33 一屏画不出来，把整张清单带走了（而页头还写着"23 步"） ｜ 已固化修复（`review-page-template.html` `cueRangeOf()` 与单屏 `try/catch` 隔离）
- #34 `os.kill(pid, 0)` 对僵尸进程也返回成功 ｜ 已固化修复（`review_surface.py` `Popen.poll()` 回收 + 超时升级 `SIGKILL`，`tests/test_visual_review_feedback.py` 回归）
- #47 页面实时叠层，不能叠在已经烘焙了层的成片上 ｜ 已固化修复（`review/media.json` `baseVideo` 与 `layersBaked` 互斥声明）
- #53 审阅页在不透明源 iframe 里：宿主 token 不会继承，硬编码会静默胜出 ｜ 已固化修复（Core 内联 `/*__DSH_TOKENS__*/` 与清理 `!important` 组件硬编码色）
- #55 「当前屏」只在扬声器轨可见时才被记下 → 上一屏/下一屏看着像坏的 ｜ 已固化修复（选中即无条件赋值 `state.currentScreenObj` 与同步唯一播放器）
- #57 审阅页的护栏是两具尸体 —— 不跑的测试等于没有测试 ｜ 已固化修复（已删死测试 `test_interactive_ui.py` 与修复跨 Skill `sys.path`，#54 同根并入本条）
- #58 舞台选择函数改写了自己的参数 → 页面永远开在错的舞台上 ｜ 已由门禁锁死（`check_review_template.py` S1/S2/S3 不变量）
- #59 字幕退回「整屏字幕」+ 圆角药丸 = 一个圆盖住画面 ｜ 已由门禁锁死（`check_review_template.py` S5/S6 不变量）
- #62 静态检查的两个假阳：对正确代码报红，训练出来的只是忽略 ｜ 已由门禁锁死（`check_review_template.py --prove` 缺陷注入自证，#51 同根并入本条）

### GOTCHAS 迁移索引（2026-11-27 · 40→10 清淤：已由现行脚手架与门禁接管，11 条）

以下 11 条约束已 100% 下沉为确定性脚本或门禁报错，从 `GOTCHAS.md` 正文迁出：

- #7 A tail pad longer than the delivery tolerance reads as a caption bug ｜ 已由门禁接管（`helpers/_internal/check_edl.py` 尾部留白容差校验）
- #13 Probe the display matrix before choosing a canvas ｜ 已由门禁接管（`helpers/_internal/render.py` 读取 `rotation` 矩阵与 `tests/test_render_orientation.py`）
- #21 A silent visual leg makes `verify_delivery.py` fail, by design ｜ 已由门禁接管（`helpers/_internal/verify_delivery.py --no-audio` 显式无声轨声明）
- #42 剪点必须按实测音频判，不能按转写词框判 ｜ 已由门禁接管（`helpers/_internal/check_edl.py` 10ms RMS 静音剪点门禁与 `tests/test_edl_silence_gate.py` / `tests/test_edl_word_granularity.py`；其中「ASR 对称打码防误剪」人工判断并入 #1）
- #43 渲染器的帧格是 ceil，不是 round ｜ 已由门禁接管（`helpers/_internal/duration_plan.py` `ceil` 帧格公式与 `tests/test_duration_plan.py`）
- #56 工程态与交付态的切分只做了一条轴 → 交付过期无人发现 ｜ 已由门禁接管（`helpers/_internal/state_fingerprint.py` 来源指纹与 `verify_delivery.py` 校验）
- #73 交付副本与流水线产物是两份判据相反的东西（字幕空隙） ｜ 已由门禁接管（`helpers/srt_export.py` 与 `helpers/_internal/export_deliverables.py` 导入空隙转换）
- #75 「确认前不要渲染」写在文档里，渲染命令什么都不检查 ｜ 已由门禁接管（`helpers/_internal/render_gate.py` 双轨授权与 `tests/test_render_gate.py`）
- #78 成片后剪停顿，字幕按剪点顺移：坐标空间混用 → 最多偏 3.2 秒 ｜ 已由门禁接管（`helpers/_internal/_cutmap.py` 与 `verify_delivery.py` `cut-map.json` 校验）
- #80 「素材入点」与「EDL 源时间」是两个坐标，混用一个就渲染出空镜 ｜ 已由门禁接管（`helpers/montage.py plan` 入点越界拦截与 `tests/test_montage.py`）
- #81 退出 0 + 文件大小正常，68% 的镜头却是空画面：显示检查必须看像素 ｜ 已由门禁接管（`helpers/_internal/check_montage.py` 逐镜像素与底图差异校验）

### GOTCHAS 合并索引（2026-11-27 · 40→10 清淤：同根合并，4 条）

同根条目合并进正文宿主条目，编号不复用：

- #2 Two engines disagreeing is a signal, not noise ｜ 并入 #1 Word-level timing must come from SeedASR 2.0
- #3 Signed-in-but-unusable accounts ｜ 并入 #1 Word-level timing must come from SeedASR 2.0
- #83 `-t` 写在两个输入之间，属于第二个输入 ｜ 并入 #82 命令末尾接管道，退出码就不是渲染器的了（含 ffmpeg 参数次序与 `-o` 命名防错）
- #84 `--no-loudnorm` 时 `-o` 撞上内部 base 名，读和写就是同一个文件 ｜ 并入 #82 命令末尾接管道，退出码就不是渲染器的了（含 ffmpeg 参数次序与 `-o` 命名防错）
