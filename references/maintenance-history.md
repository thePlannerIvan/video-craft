# 维护记录（升级，不是 CHANGELOG）

## 2026-10-08 · 审阅宿主公共化与跨 Skill 接缝收口

| 做了什么 | 为什么 | 影响了哪些 module | 删了什么 |
|---|---|---|---|
| 视觉审阅与 EDL 审阅统一改为产出 `review-surface/2.0.0`，通过 `planners-review-core` 的宿主与 DSH `review_open` 打开；`serve_review.py`、`edl_review_surface.py` 只保留业务适配 | 两种审阅面共享生命周期、桥、Range、draft、watch 与唤醒语义，避免 Skill 内再维护一套 HTTP 服务 | `helpers/review_surface.py`、`helpers/edl_review_surface.py`、`helpers/serve_review.py`、`references/review-ui.md`、`00-system/planners-review-core`、DSH review dock | 私有视觉服务器、EDL 私有服务器、页面内嵌第二审阅面 |
| 审阅页改用 DSH tokens、`review.asset()`、独立 draft 与明确保存状态；结构化动效调整进入提交收件链 | 让人在 DSH 侧栏与无插件本地宿主中都能完成可恢复的人审 | `visual/assets/review-page-template.html`、`helpers/review_inbox.py`、`references/review-ui.md` | 依赖 `localStorage` 的草稿与假成功导出 |
| 保持 PPT Hell snapshot 作为唯一画面输入，并让视觉审阅构建器复用 snapshot resolver；补齐工具调用手册与上游交接说明 | 顺序、递归资产和来源绑定不能因进入审阅页而丢失；Agent 应按 CLI 调用，不应阅读实现源码 | `helpers/build_review.py`、`visual/scripts/snapshot_input.py`、`references/tools.md`、`references/video-story-handoff.md` | 目录扫描绕过 snapshot 的隐式 fallback |

本次升级的完整行为由 `video-craft` 的 288 项测试、`planners-review-core` 回归、DSH review dock 测试与 surface 校验共同覆盖。视觉审阅与剪辑审阅仍是两个独立 surface：前者审画面/节奏，后者审词级剪辑；页面不互相嵌套，模型通过各自的收件入口继续工作。

## 2026-10-02 · 统一多形态视听审阅控制台 + 自动化导出引擎深模块化（消灭“读代码为材料”反模式）

**起因**：在真项目《Research与Wayfinder调研》（226.4s 复合双通道视频）运行中暴露了三个系统性架构缺陷：
1. **审阅页碎片化失控**：工程中先后产生 4 个审阅页面（逐字稿、SVG 预览、原始视觉页、临时双通道页），割裂了作者审阅体验，且页面与底层时间轴数据脱节；
2. **“把代码当材料阅读”反模式消耗天量 tokens**：由于 `SKILL.md` 缺少清晰的黑盒 CLI 工具界限与接口封装，Agent 在执行过程中频繁通读上千行 HTML/JS/Python 代码（寻找端点、探查 DOM、手写临时导出脚本）；
3. **导出链路脆弱与云盘锁超时**：手拼临时 FFmpeg 与录屏脚本频繁发生 OneDrive 写入锁超时（exit code -60）、动效第 0 帧未来步漏出、字幕折行遮挡。
按照 `/planning-before-create-skill` 架构原则完成系统性重构与深模块内化。

| 做了什么 | 为什么 | 影响了哪些 module | 删了什么 |
|---|---|---|---|
| **新增一键审阅构建深模块 `helpers/build_review.py`**：自动扫描项目内 `edl.json`、`timeline.json`、`subtitles.srt`、SVG 场景与音视频底片，统一编译为 `review/review_data.json` 并装配 `review/index.html` 与 `review-surface.json` | 将四处分散的切片数据合流为唯一审阅数据契约，杜绝 Agent 阅读底层解析脚本 | `helpers/build_review.py`（新） | 手工维护临时 `update_review_data.py` 的碎片流程 |
| **新增统一高性能审阅服务 `helpers/serve_review.py`**：支持 HTTP 206 Partial Content (Range: bytes=...) 秒级拖拽，内置 `/api/feedback` 本地反馈持久化与跨源兜底 | 让大视频（>200MB）在 Chrome/Safari 中秒级快进定位，脱离 DSH 也能稳定落盘 `feedback/*.jsonl` | `helpers/serve_review.py`（新） | 临时手工起静态 http.server 导致的 Range 挂起与死锁 |
| **新增统一成片导出深模块 `helpers/export_video.py`**：一键支持 `composite`（完整双通道成片）、`animation`（独立演示动画轨）、`speaker`（独立口播剪辑）、`split`（四件套多腿交付）四大规格；内置系统 `/tmp` 沙盒渲染（彻底杜绝云盘写入锁超时）、动效未来步强制隐藏样式注入与单行安全字幕防折行保护 | 将易错的音画合成、视频 overlay 滤镜与帧率锁定封装为黑盒 CLI，彻底消灭 Agent 临时手写 Python/Playwright 录屏代码 | `helpers/export_video.py`（新） | 零散的 `render_full_video.py` 与 `export_animation_track.py` 临时拼装代码 |
| **重构升级统一审阅控制台模板 `visual/assets/review-page-template.html`**：自适应三大生产形态（复合双通道、纯口播剪辑、纯演示动画）；提供实时视听播放与逐幕/逐字拆解双视图；单行安全药丸字幕防折行；100% 兼容保留 `{{REVIEW_BRIDGE}}` 审阅桥契约 | 一个统一控制台覆盖全部制作场景，杜绝针对不同形态另立新页 | `visual/assets/review-page-template.html` | 碎片化的专用临时审阅页面 |
| **更新 `SKILL.md` 渐进式披露与黑盒 CLI 速查**：明示三大任务形态，更新 Step 6 与 Step 11 产物凭证，严禁 Agent 读取内部代码，提供清晰的命令行速查表 | 严格落实渐进式披露，从根源消除 tokens 浪费 | `SKILL.md`、`references/architecture.md`、`GOTCHAS.md` | 模糊的审阅与导出描述 |

## 2026-09-30 · 双审阅页工作台重构 + v4 内部图形多拍动效引擎与口播词级自动编排

**起因**：原有两套审阅页交互粗糙（粗剪页单击词直接误删而非跳播定位；视觉审阅页强依赖 `localhost:5176` 服务、比例在宽屏下失真为 23:9、无法直接在页面内微调动效与文字），且 SVG 动画多为外层矩形盒子生硬飞入，分栏构图下虚拟摄像机平移还会将右侧元素推入左侧人物列造成遮挡。通过真项目《AI 能力体系与职场定位》（8 屏 29 步、176.70s 16:9 左人右画合成）端到端验证后落盘。

| 做了什么 | 为什么 | 影响了哪些 module | 删了什么 |
|---|---|---|---|
| 重构粗剪审阅页 `helpers/edl_preview_build.py`（Descript 风格双栏暗色工作台）：**单击任意保留词即 seek 并从该词播放**，**按住拖拽（`>= 6px`）才触发删词/恢复区间**；补齐 `J/K/L` 变速、`I/O` 打点与磁吸时间轴 | 解决「点选一个字想听定位、结果却把字删了」的核心交互反直觉问题，同时完整保留 `test_edl_review.py` 全部 15 项契约 | `helpers/edl_preview_build.py` | 旧粗剪页「单击即切换删除态」的冲突绑定 |
| 重构视觉与动效审阅页 `visual/assets/review-page-template.html`：零外部进程依赖的内联 SVG 分步动效舞台 + 合成成片预览双视图一键切换；修复 `.player-box` 严格 16:9 比例锁定；支持点选改字、框选批注、分步原语切换与分句卡点微调 | 告别 `localhost:5176` 挂掉即白屏、宽屏下舞台被压扁成 23:9 导致人物与 SVG 错位、底栏分句胶囊墙挤占画面的问题，同时 100% 兼容 `test_review_browser.py` | `visual/assets/review-page-template.html`、`references/review-ui.md` | — |
| 升级 `visual/assets/svg-anim-engine.js`（v4.0）与新增 `visual/scripts/auto_choreography.py`：扩充至 12 种原语（8 社论 + 4 产品 UI），内置 `1.2s–1.5s` 多拍内部图形编排（`.anim-typewriter` 逐字打字机、`.anim-stroke` 电路路径生长、`.anim-bar-h/v` 充能条、`.anim-node` 节点脉冲、`.anim-scan` 扫描光束、`.anim-count` 数字滚轮递增），并加入 `data-speaker-width` 分栏摄像机防遮挡锁 | 告别单调的「整张矩形卡片飞入」，让每句口播 1:1 驱动图形内部构件的多拍联动，并根治左人右画构图下摄像机左移遮挡人物的问题 | `visual/assets/svg-anim-engine.js`、`visual/scripts/auto_choreography.py`（新）、`references/svg-animation-contract.md` | — |

## 2026-09-29 · 新增 `editorial-archive` 瑞士编辑档案主题与声明式 SVG 预埋动效契约


**起因**：`planners-ppt-hell` 视频路线与 `video-craft` 是前后脚关系——如果静态 SVG 在生成时只画视觉表面、不按子元素动作分层与预埋属性，下游 `video-craft` 就只能对整块 `<g>` 做生硬的 `opacity + translateY` 浮现，或者被迫重画 SVG。基于 34 个 Pinterest 参考样本（含 9 个动态视频/GIF 逐帧拆解）与真实项目 `/prototype` 三轮压测，两边确立了统一的 `editorial-archive` 视觉主题与复合子元素预埋动效契约。

| 做了什么 | 为什么 | 影响了哪些 module | 删了什么 |
|---|---|---|---|
| 新增 `visual/themes/editorial-archive/`（`theme.json` + `tokens.css`），24 套主题全部通过 `check_themes.py` | 提供暖色生纸（`#F2EFE9`）+ 炭墨黑 + 低饱和朱砂砖红（`#C8553D`）+ 氧化黄高光 + 四域×独奏/群像节奏矩阵的瑞士编辑档案风格，并修正初版刺眼满屏红为深炭墨主底 + 12% 砖红印章克制点缀 | `visual/themes/editorial-archive/*`、`references/themes.md` | — |
| 新增 `references/svg-animation-contract.md` 与 `visual/assets/svg-anim-engine.js` | 把 8 种复合子元素分阶段动效（`bar-wipe` / `draw-stroke` / `pop-card` / `z-stack-drop` / `stamp-in` / `slot-expand` / `paper-unroll` / `highlight-sweep`）与 5 条 SVG 结构硬规则（`pathLength="1"`、`<g>` 坐标烘死防 `transform` 抹零、语义子选择器 `.anim-*`）固化为单一契约；`svg-anim-engine.js` 同时提供浏览器预演 WAAPI 模式与 HyperFrames 确定性 GSAP 时间轴注册 | `references/svg-animation-contract.md`（新）、`visual/assets/svg-anim-engine.js`（新）、`references/composition-craft.md`、`SKILL.md`、`references/architecture.md` | — |

## 2026-09-26 · 剪接预演面接缝（第四条形状：在板子上挑），自带服务器退役

**起因**：接缝已经接了三家（ppt-hell 逐单位+版本 / video-craft 视觉面追加式 / bypage 逐页+事实例外），
但剪接线一直是**本 Skill 自己的服务器**（`edl_preview_serve.py`：固定端口 8737、严格包含的静态根、
`/api/save` 整份替换 `selections.json`）。第四家的形状与前三家都不同，所以结论不能照抄。

**这一面逼出来的缝修正（唯一一处）**：宿主静态分支**认 `Range`**。前三家都不放**大媒体**，
所以这条潜伏缺口在它们身上看不见 —— 而这一面要在 SOURCE 时间轴上拖 `<video>`，真项目素材
**0.5–2.04 GB**（四个真项目量过），且宿主发 `no-store`（素材是原地改写的，缓存会骗人）。
没有 Range 就只有两个坏选择：每次把整个素材拉完，或者让页面硬写另一个 origin（违反 R4）。
一并补了 MIME 的 `.mov`/`.m4v`（原来会给 `application/octet-stream`，`<video>` 放不出来）。
边界情况都钉了测试：无 Range 的 `200` **仍带** `Accept-Ranges`、不可满足 `416` + `bytes */<total>`、
单区间 `Content-Length` ＝**实发**字节数、**多区间故意不支持**（回整份；写错 multipart 会静默截断）。

**判断（两件，都不是照抄）**：
- **`dir` ＝ 素材与剪辑目录的公共根**，不是剪辑目录。页面里那些 `/<素材>.mp4` 从写出来那天起
  就假定 serve root 是公共根 —— 取公共根，页面与 `selections.json` 里的 `dir` **一个字符都不用改**
  （真项目历史值就是 `/edit`，四个全一致）。"宿主严格单目录"不是缺口，是**配置**。
- **该声明 `feedback`（＝`selections.json`），`wake` 只当门铃**。工件不许穿过人类语言通道：
  几十上百条浮点区间塞进一句 prompt 再变回 JSON 就是丢信息。**整体意见另走一条**：只 `wake`、
  **不写文件**（写进去会被 `apply_selection.py` 静默忽略 → 死字段）。这一条改了公共规则里
  "第 4 类形状"的写法（拆成"结果就是那句话"与"结果是下一步要执行的工件"两半）——**第四家第一次
  改到规则本身**。

**改了**：`edl_preview_build.py`（裸注入点、桥接线**排在整页渲染之后**、保存走 `review.write`、
R11 永久刷新出口、R10 整体入口、保存后敲一下门铃）；新增 `helpers/edl_review_surface.py`；
删 `helpers/edl_preview_serve.py`；模组 `serve-review.mjs` 加 Range 与 MIME。

**没改**：`selections.json` 的形状（含照旧写回去的 `dir`）、`apply_selection.py`、页面的交互
（拖选/双击改字/时间轴/播放器）、页面位置。

**基线是"无覆盖"**：接缝之前这一条线**没有任何测试**（`apply_selection` 只在注释里出现过一次）。
新增 `tests/test_edl_review.py` 15 条 —— 接缝顺带给它第一张回归网，含真项目端到端（挑四个真项目里
素材最大的那个，硬链接成副本跑，真项目只读）。

**已知代价**：旧 `/api/save` 每次保存留一份 `selections.backup-<时间戳>.json`，缝的 `write` 是
纯覆盖 → **这份时间戳备份没有了**。影响面：丢一次挑选（EDL 自己那层有 `edl.previous.json`，
不受影响），人可以从页面重挑。已报备，未擅自加缝能力。

**同轮修掉的**：`Cmd-S` 绕过 `disabled` → 并发保存 → 读-改-写**真的丢了一条**（加 `saving` 守卫，
GOTCHAS #34）；陈旧提示**只给人看**（`stale`/`stale_timeline` 进记录，R5b）。

这里装**已决定的升级**：做了什么、为什么、**影响了哪些 module**、删了什么。
候选与状态在 `GOTCHAS.md`；模块边界与缝在 `references/architecture.md`。
新的一次记在最上面。发版记录不在这里。

## 2026-09-26 · 宿主生命周期搬进公共模组（只留一份）

来源：`planners-review-core` 侧的整合（上一轮接入时发现：缝集中了**宿主**，没集中**宿主的生命周期**，
两个家各一份 `review_surface.py`，已经漂移过——僵尸判据、SIGKILL 升级）。测试基线 **238 → 238 全绿**
（一条没丢、一条没多；改的是调用点，不是断言）。

| 做了什么 | 为什么 | 影响了哪些 module | 删了什么 |
|---|---|---|---|
| 生命周期（写/校验 surface、`host_state`、`host_alive`、`start_host`、`stop_host`、`_pid_alive`、`_startup_report`、`_port_of`、`open_review`）搬进 `planners-review-core/scripts/lib/review_host.py` | 两份副本会各自长 bug：僵尸判据、SIGKILL 升级、身份比对都只在一家修过 | `helpers/review_surface.py`（只剩 `surface_document` 与薄壳）、`helpers/lib/planners_modules.py`（只剩"找模组"）、`tests/test_visual_review_feedback.py`（生命周期调用改指模组、传 surface 路径） | 本 Skill 里那 7 个函数的实现；适配器里的 `node_binary()`（node 的查找也归模组，覆盖变量统一成 `REVIEW_CORE_NODE`） |

**边界**：模组**不认识任何业务**（不解释审的是什么、也不需要在替谁干活），入参是一个 surface 路径；
`surface_document(root)` 留在本 Skill（文档内容是业务）。`write_surface`/`validate_surface`/`open_review`
在本 Skill 里只剩 1–4 行薄壳（建文档 → 交给模组 / 传路径 / 缺件前置）。

## 2026-09-26 · 视觉审阅面挂到公共缝（planners-review-core）

来源：B8 分解的「第二家」接入（第一家是 ppt-hell）。测试基线 **199 → 238 全绿**
（新增 39，删除 0；被删的是本 Skill 自己那台 HTTP 服务器的专有测试，行为断言全部迁移到新入口）。
另有一条 env-gated 的真浏览器冒烟（`VIDEO_CRAFT_BROWSER_TESTS=1`，默认 skip）。

**只动视觉审阅面。** EDL 剪接预演那条线（`edl_preview_build/serve`、`selections.json`）一个字没动。

| 做了什么 | 为什么 | 影响了哪些 module | 删了什么 |
|---|---|---|---|
| 审阅页改用**审阅桥**：`{{REVIEW_BRIDGE}}` 注入点、`review.readText` 读时间轴与 surface、`review.write` 提交、`review.wake` 唤醒；不再 `fetch("/api/feedback")` | 同一份页面要能在两种宿主下跑（有插件 → DSH 侧栏 iframe；没有 → 公共件起的本地宿主）。服务归缝，本 Skill 不再自己写 | `visual/assets/review-page-template.html` | 页面里对 `/api/health`、`/api/feedback` 的两处 fetch；剪贴板那条早已不在 |
| 新增 `review-surface.py`：写/校验 `review/review-surface.json`、起 `serve-review.mjs`（`--port 0`）、判断宿主死活与**身份** | surface 是缝唯一认识的接口；宿主生命周期不再由本 Skill 自己实现 | `helpers/review_surface.py`（新）、`helpers/lib/planners_modules.py`（新，找公共模组的适配器） | 本 Skill 自己的 HTTP 服务器（`visual_review_serve.py` 的 `create_server` / `make_handler` / `self_check` / `main`） |
| 新增收件层：surface 声明的**一份**提交文件 → `feedback/<chapterId>.jsonl` **追加**（按记录内容哈希去重） | 缝的落盘是**覆盖写一份文件**，本 Skill 的形状是**每章一份、只追加**。形状对不上时在收件处翻译，**不为了适配缝去改自己的反馈形状** | `helpers/review_inbox.py`（新） | — |
| 「不端出旧项目」的判据从**端口**换成**内容**：pid + 注入过的页面 + `watch` 文件逐字节等于磁盘 | 新宿主 `--port 0`，端口不再有判断力；而页面是几个 Skill 共用的模板，本来也分不出项目 —— 项目专属的 `timeline/timeline.json` 才分得出 | `helpers/review_surface.py`（`host_alive` / `_serves_this_project`）、`tests/test_visual_review_feedback.py`（`HostIdentityCase`） | 「把注入点还原成宿主会注入的字符串再逐字节比页面」这条判据 —— 它把宿主的注入格式写死在自己这边，宿主改一次格式它就**静默**永远为假（实测踩到） |
| 过期审阅页的守卫换成**注入点**判据，并分开报出两种过期副本 | 旧判据认 `fetch("/api/feedback"`；页面不再自己 POST 之后它就失效了 | `helpers/visual_review_feedback.py`（`PAGE_BRIDGE_MARKER` / `check_project`） | `PAGE_SAVE_MARKER` 那条判据 |
| 新增真浏览器冒烟（`VIDEO_CRAFT_BROWSER_TESTS=1`）：页面加载 → 桥注入 → 时间轴渲染成 step 清单 → 一次提交落文件 + wake 被调用 → 收件成 JSONL 追加 → 重复收件是空操作 | 这一段是「意见不能丢」的端到端；只用单元测试证明不了桥真的把时间轴送到了页面 | `tests/test_review_browser.py`（新） | — |
| 上屏文字闸门认得出新的审阅页 | 判据原来是「页面会不会把反馈回传服务器」，新页面通过桥说话 | `helpers/check_screen_text.py`（`FEEDBACK_ENDPOINTS` 增加 `{{REVIEW_BRIDGE}}` 与 `/__review/`） | — |

| 单屏渲染各自 try/catch；`cueRange`/`srtRange` 两种字段名都认 | 拿真项目（`05-VideoProject/PPTSkillV2`，7 月的时间轴）跑时，页头写"6 章 · 23 步"、**下面一屏都没有**且无报错：渲染循环里 `st.cueRange[0]` 抛在 `for` 里，一个字段名的年代差带走了整张清单 | `visual/assets/review-page-template.html`（`cueRangeOf` + 逐屏失败出声） | 循环里裸取 `cueRange[0]` |
| `stop_host` 认句柄并升级 SIGKILL | `os.kill(pid, 0)` 对**僵尸**也返回成功（子进程退出但父进程没 `wait()`），于是宿主明明关了却报"没停掉"；SIGTERM 也可能因 keep-alive 连接一直不返回 | `helpers/review_surface.py`（`_HOST_HANDLES` / `_pid_alive` / `stop_host`） | 只用 `kill(pid, 0)` 判死活、只发 SIGTERM |

**真项目实跑（`05-VideoProject/PPTSkillV2`）**：旧页（剪贴板时代，7 月 31 日，6558 B）
sha256 `796ff3f2…` → 按文档那一步用新模板重生成（`15418868…` → 修 `cueRangeOf` 后 `74a8e939…`
→ 标记改裸写、撤掉 `base` 后定稿 `192c5f9a…`，21397 B）。
无插件宿主下真浏览器跑通：注入点被换掉、时间轴经桥渲染 23 屏、一次提交落
`review/review-submissions.json` 且 wake 被调用、收件追加进 `feedback/cta.jsonl`（3 → 4 行，纯追加）。
**6 章历史反馈逐字节未变**（收件只追加一行，随后用收件自己留的 `.previous/` 备份还原）。
证据留在 `.scratch/planner-skill-decomposition/b8.5-pptskillv2-evidence/`。

**页面不再自带 `base`**：标记改成裸写之后，宿主注入的 `window.__REVIEW_BASE__` 真的到得了页面
（以前它落在前一个脚本结束标签之前，被当成脚本文本吃掉），所以 `connect({base:'../'})` 那个
补洞用的参数撤掉了 —— 实测撤掉后浏览器冒烟仍然通过。

**接入时逼出来的三条缝的修正（已由缝自己改完）**：`watch` 的基准统一成**相对 surface 文件**；
无插件宿主注入 `window.__REVIEW_BASE__`；宿主按 `watch` 只盯声明的那几个文件。
注入点的唯一写法也定死了：**裸着独占一行、只出现一次**（校验器 `bridge_placeholder_not_bare` /
`bridge_placeholder_multiple`）。详见 `GOTCHAS.md` #32 与接入报告。

## 2026-09-26 · 报告 P-24…P-30 与 §11.4 的七条修复

来源：`05-VideoProject/06-测试-Vans-20260926/_测试报告.md`（作者实跑剪辑 + 动画整条链后的复跑）。
测试基线 162 → **199 全绿**（新增 37，删除 0）。

| 做了什么 | 为什么 | 影响了哪些 module | 删了什么 |
|---|---|---|---|
| 抽段**无条件读回**（可读 / 音视频互差 ≤ 1 帧 / 与请求差 ≤ 1 帧）；坏段重抽一次；仍坏则硬失败并点名段号与路径；`CalledProcessError` 一并接住 | 真跑出现过 48 字节的坏段：`render` 退 0、成片少 10 秒、`segment_durations.json` 把 80.0 记成实测，而 `check_edl` / `verify_av` 全绿 | `helpers/render.py`（新增 `SegmentError` / `check_segment`）、`tests/test_segment_integrity.py`（新） | 缓存命中之外那条「不校验」的路径 |
| `segment_durations.json` **落盘前**断言 `\|总长 − 标称\| ≤ 1 帧 × 段数` | 记录与标称差 4 秒却没有任何断言 | `helpers/render.py`（新增 `check_total_duration`） | — |
| 交付闸门**按 `edl_sha256` 选渲染记录**；历史键保留但不参与判定 | 键按输出名累积（`poc`/`draft`/`mix-base`/`final`），两个闸门读到 `poc` 的 12 秒，把 84 秒的正确成片判成「可能被截断或替换过」——最后一道关给假 FAIL | `helpers/_edl.py`（新增 `select_render_record` / `render_record`）、`helpers/check_edl.py`、`helpers/verify_delivery.py`、`tests/test_render_record.py`（新） | 「按迭代顺序取第一条记录」这条隐式规则 |
| 画面页的 **href 边界**改为页目录的父目录（父目录叫 `_internal` 时再上一层）；项目根 / 页目录 / 包根 / `input/` / `input/scenes/` 都解析到同一对路径；越界报错改成指向正确调用，不再建议违约改法 | docstring 里那个字符串（`--pages <项目>/_internal/02_svg_source`）必然失败，而报错的两条建议分别违反逐字保真与上游契约 | `visual/scripts/import_svg_page.py`（新增 `href_boundary`，重写 `resolve_pages` 与报错） | 两条违约建议；「显式给了页目录就用它当边界」这条规则 |
| 组成品 `--verify` 增加**父级穿越闸门**：任何 `href`/`src="../…"` 即失败 | 手写内联的页面没经过导入器的改写，`hyperframes check` 以 `invalid_parent_traversal_in_asset_path` 拦下；而 `--prove` 对同一批页面报 8/8 byte-identical | `visual/scripts/generate-composition.py`、`tests/test_svg_page_import.py`（`CompositionGuardTests`） | 「验证只看时间与尺寸」这条边界 |
| `--audit` 增加**跨页 id 碰撞**报告（退非零，修法指向画面侧）；**id 一个字不改** | 各屏内联进同一个 DOM，四个 clip 各有一个 `#caption-1`，`hyperframes check` 的对比度警告对不上时刻；「按 id 指名」在这种情况下会静默错绑 | `visual/scripts/import_svg_page.py`（新增 `audit_pages`）、`composition/pages/manifest.json` 的 `ids` 字段 | — |
| 对比度判据：`--text`/`--text-2`/`--text-mute` 进 `failures`（4.5:1）；`--text-faint` **去掉阈值**、只报实测 | `--text-faint` 的阈值写在判据表里却永远不可能命中：23/23 判 ok，而 18 套的 faint 在 1.86–2.98:1。文档说它「要可读」——「一个都没过」被显示成「0 failing」 | `visual/scripts/check_themes.py`、`visual/themes/*/tokens.css`（6 套 `--text-mute` 改色）、`references/themes.md`、`tests/test_themes.py` | `NOTE_CONTRAST` 这个常量；`themes.md` 里「`--text-faint` 仍然要可读」那句 |
| 渲染前预检 `helpers/check_render_env.py`：**真的往字体缓存目录写一个探针文件**，不可写就退非零并给出 `HYPERFRAMES_FONT_CACHE_DIR`；Node < 22 与缺 composition 各一条 | 受限沙箱下 `hyperframes render` 中途 `EPERM`，报错只给 `--docker`（本机无 docker），而 `doctor` 的九项不含这一项 | `helpers/check_render_env.py`（新）、`tests/test_render_env.py`（新）、`install.md`、`references/visual-rendering.md`、`SKILL.md` | 「`hyperframes doctor` 覆盖环境自检」这个假设 |
| `hyperframes` 的调用前提写明：**必须在 `composition/` 里跑**，`init` 会覆盖生成物、不是解法 | 从项目根跑会报「没有 composition，去跑 `hyperframes init`」——照做就覆盖掉 `generate-composition.py` 的产出 | `SKILL.md`、`references/visual-rendering.md`、`install.md` | `visual-rendering.md` 里 `src="../input/audio.mp3"` 那个自相矛盾的例子（它本身就是会被 `check` 拒的父级穿越） |
| 出版**合成事实的字段契约**（`composite`/`personWindow`/`captionSafe`） | 这三个键只有本 Skill 实现，`planners-ppt-hell` 只能转述、不能引用一份清单；作者裁定由此处出版 | `references/composition-facts-contract.md`（新）、`references/composition-craft.md`（改为指向它） | composition-craft 里那张重复列出字段语义的表 |
| 写 `references/architecture.md`；`GOTCHAS.md` 每条加 `module` + 状态并补「不收什么」；本文件对齐规范 | 作者要求把架构讨论落到 Skill 里，让下一个改它的人知道每个 module 的作用与牵连 | `references/architecture.md`（新）、`GOTCHAS.md`、本文件、`SKILL.md`（迭代落点） | — |

**已升级的条目**（`GOTCHAS.md` #25–#31）：#25 抽完的段没读回 · #26 交付闸门按位置选记录 ·
#27 页面的 href 边界 · #28 手写内联绕过改写 · #29 跨页 id 重复 · #30 一个永远不可能不合格的判据 ·
#31 `doctor` 不查字体缓存。其中 **#28 与 `--prove` 那件事并入 #6**（一个绿灯不等于另一个性质成立），
**「坏段静默」与「未捕获崩溃」合成一条 #25**（同一根因：抽完没读回）。

## 2026-09-26 · 流程与验证写清（报告 §7.3 / §7.5 那一轮的 Skill 侧残值）

| 做了什么 | 为什么 | 影响了哪些 module | 删了什么 |
|---|---|---|---|
| `SKILL.md` 开门给 11 步全景表 + 每步可判断的**完成标准**；Routing 收成单表、触发词前置 | §7.3 逐条对账：11 步里该做而没做的有 5 条（环境自检、`edit/project.md`、`production-plan.md`、无声音时的代表切片、`previs/`）——流程看不出长什么样，也没有「做完了吗」的判据 | `SKILL.md` | 路由里重复的同义分支；「全局方法与流程｜本文件」那一行 |
| 「怎么验证」一节：解释器、`PYTHONPATH`、`ffmpeg` 在 `PATH`；下限改成**实测 3.9.6** | P-16/P-17：按文档默认读法会红；而 3.10 那条下限没有代码依据（核过：无 `match`、联合注解全在 `from __future__` 之后、无运行期 `list[...]`） | `SKILL.md`、`README.md`、`pyproject.toml`、`references/review-ui.md` | `uv sync`、`<repo>/.venv`、`uv run` 这三套跑不了的口径 |
| 画面页导入器（`import_svg_page.py`）与内联；组成品生成器接 `sourcePageKey` | 票 19 的判决：页面 `viewBox` 就是视频像素、文字没转路径、节点是活的——缺的是元素身份；`../` href 会被 HyperFrames 拒 | `visual/scripts/import_svg_page.py`（新）、`visual/scripts/generate-composition.py`、`helpers/timeline_derive.py`、`references/composition-craft.md` | 手工内联那套做法 |
| 主题库校验 `check_themes.py`：**`theme.json` 真的当 JSON 解析**、`var()` 链解析、对比度、圆角刻度一致 | `theme.json` 从来没被解析过；23 套的 `--r-card: var(--r-xs)` 指向一个只存在于归档 v1 `base.css` 的刻度（CSS 静默丢声明，卡片全变直角）；`--dur-*` 零消费者 | `visual/scripts/check_themes.py`（新）、23 套 `tokens.css`、`references/themes.md` | 全部 `--dur-*` / `--ease-*` token；themes.md 里「有 base 默认值」那个虚构前提 |
| `check_script_hash.py` + 承接那一节 | `visual-plan.json` 声明了 `script_hash`，但只有上游交接那一刻算过一次；**做画面那一步核的是同一件事但时机不同**（录制前，来得及），本 Skill 在录制后核（只能事后发现，所以要停下来问作者） | `helpers/check_script_hash.py`（新）、`references/content-to-production.md`、`references/architecture.md`、`tests/test_script_hash.py`（新） | — |
| `review-ui.md` 写明另一套审阅页的目录与交棒条件；`evals.json` 清掉 `information_to_show` | 两套审阅面不互操作是接力的必然接缝（作者裁定不合并）；`information_to_show` 是 v5 起被禁的旧框架字段，任何代码里都不存在 | `references/review-ui.md`、`evals/evals.json` | `information_to_show` 两处引用 |

## 2026-09-15 · P3 一条时间脊柱、P4 渲染者合一、P5 减法审计

- ✅ **P3 一条时间脊柱** —— `helpers/timeline_derive.py` 从 EDL 派生 `timeline.json`，
  `visual/scripts/parse-srt.py` 退役进 `archive/`。验收是在真实项目上**逐字节相同**的
  组成品骨架（同 grouping in，`cmp` 无输出的 `composition/index.html` out）。
  影响：`helpers/timeline_derive.py`、`visual/scripts/generate-composition.py`、`archive/`。
- ✅ **P4 渲染者合一** —— `render.py` 成为唯一决定最终像素的地方：底片没有画面时它合成
  `canvas` 尺寸的黑底承载口播（帧率取 EDL 的 `fps` 声明），满屏不透明覆盖层走 `-c:v copy`
  （比特级证明：视频流 MD5 与源相同），其余情况才真的合成。补上的是「画面 + 口播」原本
  走不通、只能整条走 wvp 自带渲染器的缺口。影响：`helpers/render.py`、`edit/edl.json` 的形状。
- ✅ **P5 减法审计** —— `video-use-handoff.py`、`parse-srt.py`、v1 React `templates/`
  退役进 `archive/`；`master.srt` 的生成路径（`--build-subtitles` + `build_master_srt`
  + 三个读取它的候选清单）整套删除；三套 EDL 备份收敛为 `edl.previous.json`；
  `clean_edit_dir.py` 的沉积清单同步更新。影响：`helpers/srt_export.py`、`helpers/clean_edit_dir.py`、
  `archive/`。

## 当前边界

视觉审阅和剪辑审阅仍然是两个业务页面与两份反馈形状，这是有意保留的产品边界：视觉面承载画面/节奏/动效反馈，剪辑面承载词级取舍与 `selections.json`。它们共享 `review-surface/2.0.0` 的宿主接缝，但不互相嵌套，也不把两种反馈强行翻译成同一份记录。

仍需在后续真实项目中持续观察的事项是时间轴文件落点（`edit/timeline/` 与项目根 `timeline/` 的历史兼容）以及复杂页面的人工审阅深度；它们不是本次公共宿主收口的阻塞项。

## 2026-10-14 · 工程态成为默认，审阅页有了执行中的护栏

**为什么改**：真实项目上连撞三件事。① 作者明确要「审阅时都是工程状态，快和灵活；确认之后才完整渲染」，而 Skill 里这条只写在第五步的一句话里，读起来像是渲染之前的建议，不是整个运行的模式。② 审阅台连着三轮坏在同一个文件上，六类缺陷一起出货，而 `tests/` 里两个浏览器测试**一个都没在跑**。③ 画面轨的源在 composition 与「事后用 ffmpeg 拼」之间摇摆，于是有了两份真相源。

**做了什么**

- **两个态提成贯穿态**：`SKILL.md` 新增「两个态：工程态与交付态」一节（活 composition 直接演 / 才渲染），并把两个审阅面的顺序（先剪点后画面）写进入口。`references/tools.md` 的「免渲染的工程态」补上活舞台的入口。
- **活舞台落地**：新增 `helpers/live_stage.py`（唯一主人：起预览服务、绕开沙盒、pin 住裸路由并验内容）与 `visual/assets/composition-embed-bridge.js`（composition 自己的 postMessage 控制面，非嵌入时零影响）。`build_review.py` 写 `media.liveStage`（并验服务此刻还活着）；审阅页模板新增 `#live-stage-wrap` 与客户端，舞台按「活 composition → 合成成片 → 静态页」选择。
- **护栏落地**：新增 `helpers/check_review_template.py`（七条静态不变量，每条配 `--prove` 自证不空洞）与 `tests/` 里对应的 unittest；新增 `tests/test_composition_embed_bridge.py`（6 例纯逻辑协议测试，不需要浏览器）。六个缺陷先 R̶E̶D̶ 后 GREEN 地修掉。
- **画面轨唯一源**：`generate-composition.py` 支持时间轴的 `mediaClips` —— 录屏段改发 `<video class="clip">` 带 `data-media-start`，取代「渲染完再用 ffmpeg 拼一遍」；GSAP 与嵌入桥随包拷进 `composition/assets/`（去掉 CDN）。
- **自检转绿**：删死测试、修跨 Skill 依赖，`unittest discover` 从 326（2 ERROR / 5 skip）到 344 全 OK。

**删掉了什么**：`tests/test_interactive_ui.py`（不是 unittest、引用已删按钮、导入即崩）；模板里的空壳 `<hyperframes-player>`；CDN GSAP。逐条见 `architecture.md` §7 退役。项目侧的 `tools/patch_review_page.py` 与 `make_review_carrier.py` 也随之删除 —— 它们的存在本身就是缺陷的症状。

**仍然记账**（下一轮）：无口播视觉槽在这套契约里还不成立（字幕要求 EDL 每段有词、`timeline_derive` 的 step 必须由 cue 组成）；`check_edl` 对「删字」这类合法编辑永远亮红；`apply_selection.py` 会留下纯标点的碎片段，与 `srt_export.py` 的「一段一块」硬约束冲突；时间轴的步长是 cue 派生的（比媒体窗口窄一个片头静音），要不要统一基准需要一次决定。


## 2026-10-14：先工程预览，再最终输出

保留 EDL、语义字幕、实测时长、交付核验和既有媒体兼容路径。新工程预览由官方 HyperFrames player/runtime 接管，review-core 传工程快照与资产，消除跨不透明源 localhost 加载和自造 GSAP 播放控制。播放速度、单屏定位、字幕和反馈时间使用同一时钟；页面降低导航密度、集中播放工具。删除旧 liveStage 消息客户端，未删除仍有调用者的 SVG 编辑与外部视频层功能。


逐字预览不再按文件名自动选旧成片；默认按 EDL 读取源素材，只有显式 `--rendered-preview` 才对照渲染结果。回归测试覆盖旧 final.mp4 存在时的源时间与速度映射。

本轮隔离项目验收：358 项 unittest（5 项环境限定测试跳过），另跑 sandbox/local 两套真实浏览器检查，各 9 项；906 词口播源预览的播放、2 倍速、下一刀通过；改 composition 后构建快照确实变化；公共 core 的 59 项 JS 与 11 项 Python 检查通过。浏览器使用空音频输出设备验证解码和时钟，未代替人工听音。Mac 锁屏，DSH 原生窗口未直接验收，sandbox 测试只证明其桥与 opaque iframe 契约。通用 Skill lint 的 17 个路径报告与基线相同，均因截取嵌套路径/跨 Skill 引用而误报；未为消除报告而移动有效模块。

## 2026-10-15 · 审阅页反馈卡与工程动效抽屉边界

移除反馈卡和状态提示左侧的装饰色条，改用 token 边界、轻阴影和更宽内边距，降低侧栏的视觉噪声。分步动效抽屉保留旧 SVG 的参数微调能力；HyperFrames 工程预览下改为明确说明播放器已接管分步显示，并隐藏会产生第二套时钟的静态参数行。新工程仍通过本屏连播、最终态、定位和倍速控制审阅；原语、镜头和子延迟回到 composition 的 `choreography.json` 修改后重建。


## 2026-10-15 · HyperFrames 成为新工程唯一运行时

旧记录中提到的 `VideoCraftAnimEngine.registerGsapTimeline()` 属于历史兼容实现，不再是新 HyperFrames composition 的主时间轴方案。新工程由官方 player/runtime 拥有时间、媒体和 clip 显隐；`VideoCraftAnimEngine` 只在旧 SVG 审阅路径中保留。需要即时参数控件时，composition 必须实现 `references/hyperframes-review-adapter.md` 的可选适配器；否则统一走反馈、改源、重建审阅。

## 2026-10-15 · 页序与页面集合的快照交接

| 做了什么 | 为什么 | 影响了哪些 module | 删了什么 |
|---|---|---|---|
| 快照 binding 增加 `order`；invalidation 增加 `order_changed` / `timeline_needs_review`，合成前校验时间线页序 | PPT 拖动顺序必须真正传递到视频生产；已有录音时间绑定不能被静默重排 | `visual/scripts/snapshot_input.py`、`visual/scripts/generate-composition.py`、`SKILL.md` | 把实时 PPT 项目目录当作视频输入的模糊示例 |
| 原 visual-plan 与工作台集合不一致时要求显式 `collection_delta` 与内容复核 | 新增/删除页需要显式承接，避免下游误把旧脚本当成完整页面集合 | `snapshot_input.py` | 集合变化的隐式接受 |

## GOTCHAS 迁移索引（2026-10-19）：已升级/已修条目

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

## GOTCHAS 迁移索引（2026-10-19）

以下条目的后果已由代码/测试/公共宿主承接，正文移出 `GOTCHAS.md`，只留索引；「看到这个症状该怎么判断」如需追溯读历史版本。

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

## GOTCHAS 合并索引（2026-10-19）

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
- #15 `-t` between two inputs belongs to the second input ｜ 并入 #22 Never end a render command with a pipe
- #20 `render.py --no-loudnorm` cannot take an `-o` that equals the internal base name ｜ 并入 #22 Never end a render command with a pipe


## GOTCHAS 迁移索引（2026-10-21）：三条命令化带来的两条

以下两条的机制已由 `helpers/film.py` 与 `helpers/deliver.py` 承接，正文不进 `GOTCHAS.md`
（该文件有条数上限，新增必须走迁移索引）。

- #76 「画面」这一步以前没有入口，于是实现了自己重画原页 ｜ 已升级（`helpers/film.py` 的原页拆解闸门；`tests/test_film.py` 红→绿）
- #77 画面层会把内容画进字幕区，字幕一压就废 ｜ 已升级（`helpers/deliver.py` 的 `captionSafe` 判据；`tests/test_deliver.py` 侵入即红）
