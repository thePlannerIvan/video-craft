# SVG 动效预埋与跨 Skill 交接契约（`svg-animation-contract.md`）

> 本文涉及 page 路线的段落已归档（见 [legacy-page-route.md](legacy-page-route.md)）；现行 recompose 路线见 [film.md](film.md) 与 [recompose-mode.md](recompose-mode.md)。命令集中在 [tools.md](tools.md)。


> **适用条件（先读）**：这是**可选**的元素级动效契约。页面没有 `data-step`、`data-anim` 或稳定 `id` 时，仍可作为整页画面导入和合成；只有明确要做元素级动效时才需要按本文加钩子。

> **核心原则**：为什么普通 AI 做的 SVG 动画看起来「只是简单的浮现」？因为它们只对最外层 `<g data-step="N">` 做了一个单层透明度/位移过渡。
> 要在不写逐页定制代码的前提下做出**电影片头级的精致感**，`planners-ppt-hell` 在写 SVG 时必须把步进组内部的子构件挂上标准语义类名（`.anim-stroke`、`.anim-endpoint`、`.anim-fill`、`.anim-wall`、`.anim-card`、`.anim-shadow`、`.anim-tape`、`.slot-left`、`.slot-core`、`.slot-right`）。下游 `video-craft` 无需重新研究每页怎么动，也无需拆改 SVG DOM，直接按外层 `data-anim` + 内部子件语义类名驱动**复合子件连锁微动效（Compound Sub-Element Choreography）**。

---

## 一、5 条强制 SVG 结构规则（`planners-ppt-hell` 写画面时必守）

1. **锚点层与步进层分离**：
   - 背景、工程网格、十字准星、顶栏眉题等「切屏即在、全程不动」的骨架，统一放在 `<g id="{page_key}-anchor" data-role="anchor">` 内（不加 `data-step`）。
   - 随口播逐句触发的元素，切成 `<g id="{page_key}-step-1" data-step="1" data-anim="..." data-cue="口播触发句">`。每个 `id` 必须带 `{page_key}-` 前缀，保证全片内联进同一个 DOM 时唯一。
2. **每个 `data-anim` 组必须包含 2–3 层内部语义子件（拒绝单层整块浮现）**：
   - 画线型原语必须区分「线条本体 `.anim-stroke` (`pathLength="1"`)」与「末端箭头/端点卡片 `.anim-arrow` / `.anim-endpoint`」——末端卡片在线条画到之前严格隐藏（`opacity: 0`），只有当笔迹触达末端的那一刻才弹簧蹦出。
   - 拍立得相纸必须区分「`.anim-shadow`（投影）」、「`.anim-card`（相纸本体）」与「`.anim-tape`（顶部胶带）」——相纸先带旋转惯性拍落、投影同步收紧，落稳后胶带才从左向右抹上封固。
3. **外层动效容器 `<g data-step>` 与内层静态旋转/位移 `<g transform>` 严格分离（防 CSS 覆盖死律）**：
   - **关键陷阱**：如果把 `data-step="N"` 或 `.anim-card` 直接写在带有静态 `transform="translate(1320, 250) rotate(2.2)"` 的 `<g>` 上，CSS/WAAPI/GSAP 的 `transform` 动画会直接覆盖掉 SVG 的静态位移和旋转角！
   - **强制写法**：外层 `<g id="..." data-step="2" data-anim="polaroid-slap">` 与内部 `.anim-card` **绝不带静态 `transform` 属性**；卡片自身的静态定位与微倾角一律写在专用的静态包裹层 `<g class="polaroid-unit" transform="translate(1320, 250) rotate(2.2)">` 上。
4. **凡是「画出来」的线，一律用开放 `<path class="anim-stroke" pathLength="1">`**：
   - 正交箭头、分支树干、手绘红圈、手绘下划线，全部写成开放 `<path pathLength="1" class="anim-stroke"/>`，绝不扩边成闭合 `<polygon>`。多条路径在同一 step 内自动按 `65–75ms` 错峰依次生长。
5. **允许并鼓励现代 SVG 特性**：
   - 视频路线不转 PPT，全面使用 `clipPath`、`mask`、`filter`、`rotate()`、`stroke-dasharray`。图片在静态 SVG 中保持项目内相对路径，导入 `composition/` 时由 `visual/scripts/import_svg_page.py` 自动改写前缀并自证字节往返一致。

---

## 二、8 个复合子件连锁微动效原语（Compound Choreography Recipes）

| `data-anim` 值 | 适用场景与参考样本 | 内部子件语义类名 | 复合连锁微动效时间轴（为什么精致？） |
| :--- | :--- | :--- | :--- |
| **`cursor-wipe`** | 反白大字、章节核心词、重点金句擦出（`pin-33`） | `.wipe-bar`（左端橘红游标条）<br>`.anim-body`（黑底块或主字）<br>`.anim-sub`（副标说明）<br>`.anim-stamp`（可选印章） | **① `0–160ms`**：`.wipe-bar` 先以 `scaleY(0.25 → 1)` 竖向切入亮出锋利游标；<br>**② `40–420ms`**：`.anim-body` 从左向右 `clipPath: inset(0 100% 0 0 → 0 0% 0 0)` 丝滑擦出；<br>**③ `180–520ms`**：`.anim-sub` 从下方 `translateY(12px)` 轻盈跟进；若有 `.anim-stamp`，在 `380ms` 砸下并触发微震。 |
| **`meter-halt`** | 进度冲刺撞墙、指标卡壳、阈值截断 | `.wipe-bar` / `.anim-body`（左侧大字）<br>`.anim-fill`（进度填充条）<br>`.anim-wall`（红色截断墙）<br>`.anim-badge`（末端数值胶囊） | **① `0–340ms`**：左侧文字切入，同时 `.anim-fill` 从 `scaleX(0 → 1.07 → 1)` 高速冲刺；<br>**② `250–440ms`**：冲刺撞上 `.anim-wall` 的瞬间，阻断墙触发 **水平撞击震颤（`0 → +6px → -2px → 0`）**；<br>**③ `360–650ms`**：撞停后 `.anim-badge`（如 `22% 浅层即停`）带弹簧过冲蹦出。 |
| **`draw-stroke`** | 分叉轨迹、正交树、回环线、手绘红圈（`pin-28, 32`） | `.anim-origin`（起点圆点）<br>`.anim-stroke`（带 `pathLength="1"` 的路径）<br>`.anim-arrow` / `.anim-endpoint`（末端箭头与卡片） | **① `0–180ms`**：`.anim-origin` 脉冲放大；<br>**② `0–460ms`**：每条 `.anim-stroke` 按 `65ms` 错峰顺着笔迹生长（`stroke-dashoffset: 1 → 0`）；<br>**③ `320ms + i*75ms`**：**等线条画到末端的那一刻**，对应的 `.anim-arrow` 和 `.anim-endpoint` 才以弹簧微弹（`scale(0.68 → 1.05 → 1)`）接力蹦出！ |
| **`slot-push`** | 单核文字强调屏（`text-focus · solo`，源自 `pin-26`）：中间几何槽撑开并把左右文字物理推开 | `.slot-left`（左词）<br>`.slot-core`（中间几何槽）<br>`.slot-right`（右词）<br>`data-push="165"`（推开像素） | **① 初态 `t=0ms`**：`.slot-left` 向右偏 `+165px`、`.slot-right` 向左偏 `-165px`，两词原本紧贴在中心，`.slot-core` 为 `scaleX(0.04)`；<br>**② `0–520ms`**：`.slot-core` 强力撑开到 `scaleX(1)`，**把 `.slot-left` 和 `.slot-right` 物理推向两侧**；<br>**③ `160–600ms`**：槽内 `.anim-stroke` 轨迹自绘并点亮末端 `.anim-endpoint`。 |
| **`polaroid-slap`** | 单张特写相纸或 3–4 张档案相纸甩上桌面（`pin-25, 28`） | `.polaroid-unit`（静态旋转位移外框）<br>`.anim-shadow`（独立投影）<br>`.anim-card`（相纸本体）<br>`.anim-tape`（顶部胶带） | 若组内有多个 `.polaroid-unit`，按 `160ms` 错峰依次执行：<br>**① `0–420ms`**：`.anim-card` 从空中 `translateY(-36px) scale(1.14) rotate(-2.5deg)` 拍落桌面，同时 `.anim-shadow` 从远距偏移 `translate(14px, 20px) opacity(0.04)` **同步收紧贴合桌面**；<br>**② `260–500ms`**：相纸拍稳后，顶部黄色胶带 `.anim-tape` 从左向右 `scaleX(0 → 1)` 抹上封固！ |
| **`stagger-cards`** | 模型节点卡、社论分栏条、多模块递进（`pin-03, 16`） | `.anim-card`（卡片本体）<br>`.anim-badge`（编号角标）<br>`.anim-stroke`（前置连线） | **① `0–320ms`**：若有前置 `.anim-stroke` 连线先画出；<br>**② `0–480ms`**：组内多个 `.anim-card` 按 `110ms` 错峰从 `translateY(18px) scale(0.96)` 弹簧升起，`.anim-badge` 同步点亮。 |
| **`stamp-in`** | 核验印章、`? 待核验` 警示签、核心锁定章（`pin-25, 32`） | `.anim-stamp`（印章本体） | 从高处 `scale(1.65) translateY(-14px)` 狠狠砸向纸面（`280ms` 弹簧过冲），多枚印章按 `140ms` 错峰盖下。 |
| **`paper-unroll`** | 底部打孔 PDF 卷宗条、SHA-256 核验纸条展开（`pin-32`） | `.anim-paper`（纸条底板）<br>`.anim-item`（纸条内文字/徽章） | **① `0–460ms`**：`.anim-paper` 从左向右 `clipPath: inset(0 100% 0 0 → 0 0% 0 0)` 卷轴展开；<br>**② `180–540ms`**：纸条内的 `.anim-item` 徽章与元数据按 `95ms` 错峰依次浮现。 |
| **`cursor-click`** | 产品 UI 演示：拟真鼠标光标滑入、点击按压、波纹扩散并触发目标展开 | `.anim-target`（被点按钮）<br>`.anim-expand`（点击后展开面板） | **① `0–380ms`**：引擎自动注入 SVG 矢量光标沿贝塞尔弧线滑至目标中心；<br>**② `380–520ms`**：光标与 `.anim-target` 同步下压 `scale(0.92)` 并迸发双层扩散波纹；<br>**③ `480–920ms`**：`.anim-expand` 面板从折叠态丝滑撑开。 |
| **`number-ticker`** | 统计看板、规模跃增、百分比对比：数字从 `0` 实时滚轮攀升至目标值 | `.anim-count` / `.anim-number`（含数字的 `<text>`）<br>`.anim-bar-h` / `.anim-bar-v`（伴随进度条） | **① `0–360ms`**：承载卡轻盈显形；<br>**② `100–1200ms`**：组内所有含数值的 `<text>` 按三次缓出实时跳动递增至目标数字（保留原前后缀与小数位），伴随 `.anim-bar-h` / `.anim-bar-v` 同步充能。 |
| **`card-expand`** | 抽屉式拆解、详情展开、多维结构显露 | `.anim-header`（常驻头）<br>`.anim-drawer` / `.anim-card`（展开抽屉） | **① `0–280ms`**：`.anim-header` 先锁定；<br>**② `180–760ms`**：`.anim-drawer` 从顶部折叠态伴随弹性阻尼向下撑开，内部子项依次点亮。 |
| **`spotlight-sweep`** | 核心结论卡、架构总览、金句高光扫掠 | `.anim-card`（主卡）<br>`.anim-badge`（高光徽章） | 主卡浮现后，一道斜向高光束从左至右扫过卡片表面，同时徽章脉冲点亮。 |

### 通用内部图形多拍微动效类名（可与任意 `data-anim` 叠加，告别单调「整盒飞入」）

在任意 `<g data-step="N">` 内部，只要给具体图形构件挂上下列语义类名，`svg-anim-engine.js` 就会在 `1.2s–1.5s` 窗口内自动执行多拍联动编排：
- **`.anim-typewriter`（或 `data-typewriter="1"`）**：`<text>` 逐字打字机敲出并附带闪烁光标 `▋`，适合咒语输入、痛点提问、代码指令；
- **`.anim-stroke`（配 `pathLength="1"`）**：流程图连接线、电路轨迹、手绘圈线按 `180ms` 错峰顺着路径实时画出；
- **`.anim-bar-h` / `.anim-bar-v`**：水平进度条（`scaleX(0 → 1)`）与垂直柱状图（`scaleY(0 → 1)`）动态生长充能；
- **`.anim-node`**：流程图节点或圆环带弹簧过冲（`scale(0.3 → 1.15 → 1)`）点亮；
- **`.anim-scan`**：水平扫描光束从左向右扫过当前工序框；
- **`.anim-count`**：任意含数字的 `<text>` 自动从 `0` 滚轮跳动递增到目标值。

### 左人右画分栏的虚拟摄像机安全锁（`data-speaker-width`）

当画面采用「左侧竖屏人物 + 右侧 SVG 舞台」合成（如 `x: 0..608` 为人物列，`x: 608..1920` 为视觉区）时，在根 `<svg>` 上声明 `data-speaker-width="608"`：
- `svg-anim-engine.js` 会自动锁定全局全景镜头（`camera: "none", scale: 1, tx: 0, ty: 0`），**严禁把右侧元素平移进左侧人物列造成遮挡**。（`auto_choreography.py` 曾做同一件事，已随 page 路线归档；recompose 手写时间轴时要自己守住这条。）

> **引擎另支持 4 个别名值**（`visual/assets/svg-anim-engine.js` 里与上表原语**同分支**处理，写哪个都能跑）：`bar-wipe` = `cursor-wipe`、`slot-expand` = `slot-push`、`z-stack-drop` = `polaroid-slap`、`pop-card` = `stagger-cards`。**新页面一律写上表的正名**，别名只为兼容既有页面。

---

## 三、在 `video-craft` 中的适用边界

这份契约服务于旧 SVG 审阅兼容路径，以及仍然需要静态 SVG 预演的项目。`visual/assets/svg-anim-engine.js` 可以在页面里即时切换 Step、原语、镜头和子延迟；这些调整会进入反馈记录，不能被当成已经修改了源工程。

新 HyperFrames composition 不再调用 `VideoCraftAnimEngine.registerGsapTimeline()` 作为主时间轴驱动器。HyperFrames 自己拥有 composition 的时间、媒体和 clip 显隐。需要让新工程支持点选式动效调整时，应实现 [`hyperframes-review-adapter.md`](hyperframes-review-adapter.md) 中的可选审阅适配器；没有适配器就走反馈 → 修改 composition / `choreography.json` → 重建审阅。

`data-step`、`data-anim` 和语义子选择器仍可作为画面结构契约，帮助生成 composition 或旧 SVG 兼容层，但不能据此推断审阅页可以直接操作 HyperFrames 的子 iframe DOM。
