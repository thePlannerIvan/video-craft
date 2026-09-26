# 章节开发指引（每章开发必读）

---

## 这是视频，不是 PPT

正在做的是**视频网页** —— 讲者点击 + 口播 + 录屏发出去给观众看。
判断每一步做对没有，标准非常朴素：

- **不像 PPT** —— 观众感觉是在看视频，不是在看翻页幻灯（页面中不得包含页眉页脚，突出主视觉元素）
- **看起来舒服** —— 配色、字体、节奏都让人放松，不得出现大量的纯文字、不得出现字体太小的文字
- **有视觉冲击** —— 画面在演事情，不只是文字堆砌，不得一次性全部罗列所有元素，关键元素随进度逐步推进展现

---

## 必须用 CSS / SVG / Canvas / JS 大胆绘制视觉演示

> **这是底线。**
>
> 每一章都至少要有 1~2 处"动起来的图 / 演示元素"。
> **整章只有纯文字 = 验收不过 = 回去重做。**

视频感最强的来源 —— 用户**看见**了被讲解的东西在屏幕上演给他看：

- 数字在递增 / 横条在生长 / 排名在交换
- 流程节点依次点亮 / 连线自绘
- 对比被一刀切开 / 聚光灯扫过 / 形状在变形
- 粒子聚拢成形 / 噪声背景流动 / 字符雨下落
- 模拟终端交互
- 模拟 AI 对话窗口
- 模拟文件目录树

**怎么组合发挥都行 —— 但每章必须用，不允许整章纯文字。**

---

## 主画面必须建模，禁止字幕复读

> **硬规则**：主画面不是字幕播放器。严禁把 SRT 拆成一句一句弹出的文字，
> 然后把这当成主要画面。

每个 visual step 开工前必须先回答：

1. 这段内容背后的结构是什么？
2. 它在讲流程、对比、层级、因果、矩阵、循环、漏斗、地图，还是决策树？
3. 哪些文字应该只留在字幕 / ReviewPanel，不需要搬到主画面？
4. 主画面应该画出什么模型，让观众一眼理解"这段在说什么"？

优先画：

- 流程图 / pipeline
- 二维矩阵 / 坐标轴 / 光谱
- 漏斗 / 分层结构
- 时间线 / roadmap
- 层级树 / 分类框架
- 对比表 / split comparison
- 因果链 / feedback loop
- 决策树
- 系统地图 / 关系网络
- 数据卡 + 关系线
- 输入 → 处理 → 输出的机器模型

只有 hook、转场、金句、结论锤点允许短句大字。解释型段落必须画模型。

---

## 逐步揭示，禁止一次全展示

整页内容由**全局 `step` 计数器**驱动 —— 点击空白处或按 → 键推进
一步。设计每一步时心里要默念：**这一步演什么，下一步演什么**。

**最重要的一条**：

> 当口播在说"第一是 X、第二是 Y、第三是 Z"这种**清单 / 列表**时，
> **严禁**一个 step 把 X / Y / Z 全部 stagger 上来。

正确做法：

- 一项 = 一个 step
- X 只在它自己的 step 里独自亮起
- 讲到 Y 时，X 灰化保留作上下文 + Y 亮起
- 讲到 Z 时，X / Y 都灰化 + Z 亮起

**判断标准**：讲者会一个一个念出来吗？会 → 必须逐个揭示。

---

## 场景合并：渐进揭示 vs 切页

> **这是 SRT-First 项目中最关键的代码模式。**
> 同一个视觉骨架下的渐进变化，**不要**拆成多个 step 各自 return 独立 JSX。

### 判断：该合并还是切页？

| 情况 | 做法 |
|---|---|
| 两步的"视觉骨架"相同（同一个图/表/漏斗/轴/对比/金字塔） | **合并**：一个 `key` + 内部 CSS transition |
| 两步在讲完全不同的概念（从漏斗切换到品牌对比） | **切页**：各自独立 `key` |
| 同一场景下元素逐个出现（3 个节点依次点亮） | **合并**：用 `step` 偏移量控制 CSS class toggle |
| SRT 行在讲同一主题但不同句子 | **合并**：用 CSS `opacity`/`transform` transition 渐进揭示文字 |

### 正确模式

```tsx
// ✅ 一个 React key + 内部 CSS transition 渐进揭示
if (step >= 6 && step <= 10) {
  const s = step - 6;  // 局部偏移量
  return (
    <div className="scene" key="funnel">
      <div className={`node ${s >= 1 ? 'node--glow' : ''}`}>第一步</div>
      <div className={`node ${s >= 3 ? 'node--glow' : ''}`}>第二步</div>
      <div className={`node ${s >= 5 ? 'node--glow' : ''}`}>第三步</div>
    </div>
  );
}
```

关键词是 `key="funnel"` —— React 不卸载 DOM，CSS transition 驱动渐进。

```css
.node {
  opacity: 0.3;
  transition: opacity 400ms var(--dur-base), border-color 400ms var(--dur-base);
}
.node--glow {
  opacity: 1;
  border-color: var(--accent);
  background: var(--accent-soft);
}
```

### 错误模式

```tsx
// ❌ 同一个漏斗拆成 3 个独立 return → React 每次卸载重建 DOM
// → 闪烁、性能差、动画碎片化
if (step === 6) return <div className="scene" key="funnel-1"><div>第一步</div></div>;
if (step === 7) return <div className="scene" key="funnel-2"><div>第一步</div><div>第二步</div></div>;
if (step === 8) return <div className="scene" key="funnel-3"><div>第一步</div><div>第二步</div><div>第三步</div></div>;
```

### 局部偏移量约定

用 `const s = step - startStep` 做局部偏移，而不是硬编码绝对 step 值：

```tsx
const s = step - 6;     // s = 0, 1, 2, 3, ...
const showRight = s >= 2;
const allGlow = s >= 4;
```

这样调整步数时只需改一处 `startStep`，不用每个条件都改。

### 何时仍需要切页

以下情况切页是正确的：

- 视觉概念彻底切换（漏斗 → 时间线 → 品牌对比）
- 需要不同的 CSS 布局（居中 → 左对齐 → 全屏背景）
- 用户明确说"这里要翻一页"

---

## 内容取舍：抓重点，不要原文搬运

视频是**既定声音 + 画面解释**：

- **SRT** 决定顺序、字幕文本和每个 visual step 的可用时间
- **画面**负责把这一段字幕里最重要的关系、数字、动作或反差放大

每个 step 屏幕上只挂这个节拍**最值得放大的 1~3 个东西**：一个 hero 标语 /
一个数字 / 一组对比 / 一个流程节点 / 必要的视觉演示。

不要把 SRT 字幕整段搬上屏幕。底部 ReviewPanel 已经显示字幕；主画面应该
服务理解，不是重复字幕。

---

## 单源时间线：节奏跟 SRT，细节回素材

> **顺序 / 字幕 / 时长** 跟 `timeline.ts`，而 `timeline.ts` 必须来自
> `timeline/timeline.json`，后者由 SRT timecode 自动计算。
> **画面细节 / 数据 / 引用 / 截图 / 产品状态** 回 `input/assets/`、原脚本
> 或用户资料抽。

实现章节时必须看当前 step 的：

- `caption`
- `srtRange`
- `durationMs`
- `screenIntent`
- `assetNeeds`
- `visualModel`
- `modelStructure`
- `onScreenTextRule`

如果一个 step 只有 3 秒，画面必须足够单纯；如果一个 step 有 12 秒，应该
用同一视觉骨架做渐进揭示，而不是塞成一屏静态大字。

---

## 字体 / 配色 / 动画 / 留白 —— 视频演示基本审美

视频观众离屏幕远、注意力浮动，所以：

- **字号要大** —— hero 文字至少 80px 起，远观也能看清
- **留白要多** —— 舞台四边都要让出大留白，画面不要塞满
- **配色要舒服** —— **颜色和字体家族必须用主题 token**（保证换主题不破）；
  字号 / 间距 / 时长这些章节按内容自由发挥（详见下方「代码层最小约束」）
- **动画要舒服 + 炫酷** —— 出现得干净利落，停下来不抢戏；炫酷靠
  **设计巧思**（内容驱动的演示动画），不靠**速度暴力**或**密集闪烁**

---

## 避免 AI 味

AI 生成的网页有几种共有的"视觉指纹"，**全部不要**：

- 紫粉 / 蓝紫对角渐变背景
- 圆角卡片 + 彩色左边框装饰
- 渐变按钮 + 大圆角药丸
- emoji 当图标用
- 假数据 / 假 logo / 假"X 万用户"
- 整章 N 步用同一种入场动画（全场 fade / 全场 blur）
- 每步都挂 ken burns / 光晕呼吸 / 持续闪烁
- 每屏右下角都挂 mono 角标 / 序号

缺的东西**承认缺** —— 用 placeholder 占位卡（一张写着"image · 16:9
描述"的卡片，按真实比例留位）。**不要**用 emoji 凑、不要找无关图凑、
不要编数字。**没有就承认没有**，比 fake 强一百倍。

---

## 框架已经搭好的部分（理解就好，不需重写）

- **16:9 固定舞台**：内容设计在 1920×1080 上，外层 transform scale
  缩到任何视口，外围 letterbox 留黑 —— **没有响应式断点**
- **舞台居中 + 大留白**：上下左右四边都让出至少 80px 的安全区
- **隐形进度条**：屏幕底部默认完全透明，鼠标悬到底部边缘才出现，
  支持点击跳转章节（录屏时摄像头看不到任何 chrome 控件）
- **全局 step 驱动**：点击舞台空白处 / 键盘 ←/→ 推进；章节是 `step`
  的纯函数，没有定时器、没有命令式状态

---

## 代码层最小约束

不能踩的红线，其它怎么写都行：

### 必须用 token（换主题不破的底线）

- **颜色**：`--shell` / `--surface` / `--surface-2` / `--surface-3` /
  `--text` / `--text-2` / `--text-mute` / `--text-faint` / `--rule` /
  `--accent` / `--accent-soft` / `--accent-glow` ——
  **禁硬编码 hex / rgb / 颜色名**
- **字体家族**：`--font-display-cn` / `--font-display-en` / `--font-body`
  / `--font-mono` —— **禁硬编码字体名**
- **主题性格签名**通过 primitive class 自动接入，**不要在章节 CSS 里
  重定义它们**：
  - `.hero-num`（hero 数字风格 —— 主题决定衬线 / 等宽 / 粗黑）
  - `.rule`（分割线 —— 主题决定 1px 实线 / 4px 实线 / 2px 虚线）
  - `.card`（卡片 —— 主题决定圆角 + 阴影性格）
  - `.stage-frame`（舞台底色 / 圆角 / 阴影 / 装饰图案 / vignette
    全自动，章节什么都不用做）

### 可硬编码 / 可 token，按内容自由（解锁章节自由设计）

- **字号**：想要 80px 就写 80px，想用 `var(--t-h1)` 也行
- **间距 / padding / margin**：按画面节奏写具体值
- **动画时长 / 缓动 / keyframe**：按动画意图写具体值
  （**节奏气质**参考 `theme.json` 的 `mood` —— 慢主题别写 200ms 的快动画）
- **边框宽度 / 非性格圆角 / 字距**：随手写
- **gap / grid 布局尺寸**：按画面构图写

### 其它工程红线

- 不用 `setTimeout` / `setInterval` 驱动动画 —— 用 CSS keyframes
- 章节内的可交互元素（按钮 / 自定义控件）加 `data-no-advance`，
  否则点了会被舞台误推进 step
- 章节代码物理隔离：每章独立文件夹、独立 CSS 类前缀，不跨章 import
- **每章必须有 `timeline.ts`**（与 `<Chapter>.tsx` 同目录）：
  - 数组长度 **=** 章节代码里可展示的 step 数
  - 每个元素必须有 `id` / `caption` / `srtRange` / `startMs` / `endMs` / `durationMs`
  - `durationMs` 必须来自 SRT，不手填估算
  - 这是 ReviewPanel、ProgressBar、Auto 播放和 Timing Lock 的唯一运行时来源
- **动画必须适配该 step 的 SRT 时长**。Auto 模式严格按 `durationMs` 推进，
  不会等动画跑完。动画太长 → 三选一：**简化动画 / 调整分组 / 拆 step**。

### ⚠️ CSS animation 简写语法红线

在 1920×1080 舞台开发中，以下 CSS 问题已被多次验证为高频 BUG，**必须规避**：

**1. `animation` 简写中 `var(--dur-base)` 不能放在 timing-function 位置**

```css
/* ❌ 错误：var(--dur-base) 是 <time> 类型（如 400ms），不是合法的 timing-function */
animation: hkSlideUp 900ms var(--dur-base) 0.5s forwards;

/* ✅ 正确：使用具体的缓动函数名，如 ease / ease-in-out / linear */
animation: hkSlideUp 900ms ease 0.5s forwards;
```

根因：`animation` 简写的参数顺序是 `name | duration | timing-function | delay | ...`。
第二个 `<time>` 值是 delay，所以 `var(--dur-base)` 被错误地解析为 timing-function。
`400ms` 不是合法的 timing-function，整条规则被浏览器忽略。

**安全写法：只用 explicit timing-function（`ease` / `linear` / `ease-in-out` / `cubic-bezier(...)`）**

**2. `→` 字符不能出现在 SVG `<text>` 元素内**

Vite 的 oxc parser 会将 SVG `<text>` 内的 `→`（U+2192）解析为非法字符。

```jsx
{/* ❌ 错误 */}
<text x="100" y="50">→ 抽象为</text>

{/* ✅ 正确：用 » 替代，或用 CSS 伪元素、或缩写为 -> */}
<text x="100" y="50">抽象为</text>
```

**3. SVG 尺寸控制**

SVG 元素的 `width` / `height` 是展示属性，CSS 的 `width` / `height` 可覆盖。
但如果 viewBox 与 CSS 尺寸不匹配，内容会被拉伸。

```tsx
{/* viewBox 决定内容坐标系，CSS 决定显示尺寸 */}
<svg viewBox="0 0 100 100" />
{/* ✅ CSS 控制展示大小 */}
.l2-svg { width: 200px; height: 200px; }
```

---

## Stage 适配规范（1920 × 1080）

舞台是固定的 1920×1080 画布。内容是直接在这个坐标系里设计的。

### 字号基准

| 层级 | 用途 | 最小字号 | 示例 |
|------|------|---------|------|
| Hero | 核心金句、结论、品牌标语 | **120px** | "工作经验的工程化沉淀" |
| Sub | 章节标题、重要观点 | **48px** | "上下文管理是一门艺术" |
| Body | 描述文字、段落 | **28px** | 说明性文字 |
| Label | 标签、标注、注释 | **18px** | 流程步骤名、数据标签 |
| Mini | 极次要的装饰文字 | **14px** | SVG 图表内的小标注 |

**严禁**出现 10px / 11px 字号。所有字号按此基准上浮。

### 内容填满舞台

- 内容区域至少占据舞台宽度的 70% 和高度 60%
- Hero 文字应占屏幕主体，不要缩在卡片内
- 避免用 `max-width` 约束主要内容的宽度（除非明确需要留白）
- 用 `flex: 1` + `height: 100%` 撑满舞台空间

### 内容居中

- 使用 flexbox 的 `align-items: center; justify-content: center` 居中
- 避免绝对定位写死 `top/left` 值导致偏离中心
- 需要绝对定位时，坐标值应基于 1920×1080 坐标系计算

### 底部留出字幕空间

舞台底部有 ReviewPanel（最小化时 30px，展开时 260px），章节内容底部应空出至少 60px。

---

## 完工自检（写完每章**强制**执行，不可跳过）

> ⚠️ **硬性流程**：章节实现完成后**必须**走完下面的自检 → 修复 → 汇报
> 三步。**禁止**"实现完成 → 直接汇报给用户"。
>
> **执行方式**（按能力降级）：
>
> 1. **优先 Agent Teams**：开一个独立的 reviewer agent，传入本章代码路径
>    + 本文件 Part「完工自检」清单，让它**逐项核查 + 出结论**（哪几条
>    pass / 哪几条 fail + 证据）。
> 2. **其次 subAgent**：当前 agent 没有 Teams 能力但能开 subagent，用 subagent
>    走同样的流程。
> 3. **都没有**：当前 agent 自己**严格逐项**核查，不允许目测一遍就放行。
>
> **拿到自检结论后**：先按 fail 项**改完代码**，然后再向用户汇报"做完
> 了 + 自检结论 + 改了什么"。**直接拿原始结论汇报但不修复 = 违规**。

写完一章 + 在浏览器点完一遍后逐项过：

- [ ] **每章至少 1~2 处 CSS / SVG / Canvas / JS 视觉演示** —— 没有 = 回去补。
      如本章在 storyboard.md 中标记了 `[REC]`（录屏素材章节），此项标记 N/A，
      使用 `RecordingPlaceholder` 占位即可
- [ ] **不同 step 的主导动作不一样** —— 全章一种动画 = 回去重做
- [ ] 字号符合 Stage 适配规范（hero ≥120px, sub ≥48px, body ≥28px, label ≥18px, mini ≥14px）
- [ ] 内容填满舞台（至少 70% 宽度 × 60% 高度），不是缩在中间的小卡片
- [ ] 内容居中（flexbox 居中或正确的绝对定位坐标）
- [ ] 底部留出至少 60px 字幕区域
- [ ] 清单 / 列表逐个揭示，**1 项 = 1 step**
- [ ] 主画面不是字幕复读，而是放大该 SRT step 的关键关系 / 数字 / 动作
- [ ] 每个解释型 step 都使用了 `visualModel` 对应的模型化画面（流程 / 矩阵 / 因果 / 漏斗 / 时间线 / 决策树等）
- [ ] **CSS 动画检查**：
      - 所有 `animation` 简写中没有 `var(--dur-base)` 或类似 `<time>` 值出现在 timing-function 位置
      - 所有动画使用 `forwards` fill-mode（确保元素保留动画结束状态）
      - 没有在 SVG `<text>` 内使用 `→` `←` `•` 等特殊 Unicode 字符
- [ ] SVG 尺寸由 CSS 控制，不在 SVG 元素上硬编码 `width`/`height` 属性
- [ ] 没有连续多屏使用"一句字幕弹出 → 下一句字幕弹出"作为主要表现
- [ ] 没有紫粉渐变 / 圆角彩色边框 / emoji / 假数据 / 假 logo
- [ ] 缺的素材用 placeholder，不是 fake
- [ ] **颜色和字体家族全部走 token**（无硬编码 hex / 字体名）；hero 数字
      / 卡片 / 分割线 / 舞台用 primitive class 接入主题性格 —— 这两条不
      达标 = 换主题就破
- [ ] 章节交付时**主动告诉用户**："本章还缺这些素材"
- [ ] 禁止出现小号字体，大量纯文字（出现后必须回去改）
- [ ] 禁止出现任何形式的页眉页脚，仅展示关键内容（出现后必须回去改）
- [ ] **`npx tsc --noEmit` 通过** —— 不通过禁止汇报"做完了"
- [ ] 章节代码物理隔离：独立 CSS 类前缀（`.l1-` / `.l2-` / ...），
      未跨章 import，未修改 `chapters.ts` 之外的共享文件
- [ ] **`timeline.ts` 存在**且 `timeline.length` === 章节代码可展示 step 数
- [ ] 每条 timeline step 的 `durationMs === endMs - startMs`
- [ ] `timeline.ts` 的 caption / srtRange 与项目级 `timeline.json` 对应章节一致
- [ ] 每个 step 的视觉动画能在该 step 的 SRT `durationMs` 内读完 / 看完

任一未过 → 回去改。**不要**"先放着以后修"。
