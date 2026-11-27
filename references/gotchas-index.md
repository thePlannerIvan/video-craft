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
