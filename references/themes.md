# 主题系统

每个演示从头到尾跑**一个主题**。我们**不**在章节间翻转明暗 —— 那会
打断视频的视觉连贯性，录屏时看起来像很硬的剪辑。如果想要"暗一点的氛围"
段落，请在**同一调色板内**降对比、收聚光，而不是翻转表面色。

主题 = 一组 CSS 设计 token + 一个 `theme.json` 元数据。

## 谁在读它

风格库的唯一来源在本 Skill（`visual/themes/`），有两个消费者：

| 消费者 | 从主题读走什么 |
| --- | --- |
| 本 Skill 的 `visual/scripts/generate-composition.py` | `tokens.css` 的 `:root` **原样内联**进 `composition/index.html`：颜色、字体家族、性格旋钮都成了 HTML 动效层里的 `var(--…)`；`theme.json` 的 `mood` / `bestFor` / `preview` 供列清单和挑主题。 |
| `planners-ppt-hell` 的视频路线 | 同一批 token **翻成 SVG 的显式属性**贴到静态画面上（颜色落到 `fill` / `stroke`，字体落到 `font-family`，圆角落到 `rx`）。它读同一份 `tokens.css`，所以主题一改两边一起改。 |

改风格只改 `visual/themes/<id>/`，两边都不会各留一份。

校验：`python3 visual/scripts/check_themes.py` —— 逐套检查 `theme.json` 能不能当 JSON 解析、
必填 token 在不在、每个 `var()` 有没有解析到值、正文对比度够不够。

**章节只拿 token，自己写 CSS。** 主题**不提供 class**：没有 `.hero-num` /
`.rule` / `.card` / `.stage-frame` 这套 primitive，也没有 `base.css`。主题给的
是 `:root` 里的一组自定义属性，章节按内容用 `var(--…)` 写自己的规则。
所以 `--r-card` / `--rule-w` / `--hero-num-*` 是 **token**，不是 class 名。

**章节对 token 的消费分两层**：

1. **必须用 token 的**（换主题不破的底线）—— 颜色 + 字体家族
2. **章节自由发挥的**（按内容设计）—— 字号 / 间距 / 动画时长 / 缓动 /
   边框宽度 / 一般圆角 / 字距等都可硬编码

主题**不只管**颜色和字体：hero 数字、分割线、卡片、舞台装饰各有对应的
token（下表），章节读哪个就用哪个。

主题管的维度：

| 维度                       | 主题怎么管                                                        |
| -------------------------- | ----------------------------------------------------------------- |
| **调色板**                 | shell / surface 阶梯、text 阶梯、accent + 透明度衍生              |
| **字型**                   | 中文 / 英文 / body / 等宽家族 + OpenType 特性集                     |
| **舞台 padding 密度**      | `--stage-pad-x/y` —— 精炼主题 140×100，密集主题 80×60              |
| **圆角性格**               | `--r-card` 指向共用的圆角刻度 —— `--r-flat` 0（sharp）/ `--r-xs` 4（refined）/ `--r-md` 16（soft）/ `--r-xl` 32（keynote） |
| **分割线性格**             | `--rule-w` + `--rule-style` —— 细/粗 × 实/虚                       |
| **hero 数字风格**          | `--hero-num-*` —— 编辑级斜体 / 终端等宽 / 粗黑 / 手写              |
| **舞台 / 卡片阴影**        | `--shadow-stage` / `--card-shadow` —— 纸浮 / 偏移实色 / 内阴影     |
| **装饰层**                 | `--surface-pattern*` / `--surface-vignette` / `--text-shadow`     |
| **动效基线**               | `theme.json` 的 `mood` —— 电影感慢 / 弹簧 / 利落 / 安静            |

> **节奏的真相是 `mood`**。主题不定时长：具体 ms / 缓动由 chapter agent 看
> `mood` 加内容自己拍板（慢主题别写 200ms 快动画，仅此而已）。本文件下面
> 主题表里括号中的 ms 只是给挑主题的人一个手感参照，不是契约。

每个主题约 25~35 个 token。完整契约见下方。

---

## v2 集成方式（HyperFrames 组成品）

v2 管线里主题的消费方式不变，落地位置变了：

- `visual/scripts/generate-composition.py` 读取 `themes/<id>/tokens.css` 的
  `:root` 块，内联进 `composition/index.html` 的 `<style>` —— 主题
  仍是 token 的单一来源，章节视觉一律用 `var(--…)`。
- `theme.json` 元数据（mood / bestFor / preview）继续供 Checkpoint
  Plan 推荐使用，字段不变。
- **字体确定性**：HyperFrames 编译期会确定化拉取 Google Fonts 字体
  （Inter / Noto Sans SC / JetBrains Mono / Montserrat / EB Garamond
  等有映射）。`-apple-system` / `PingFang SC` 会产生一条 benign
  compiler warning 并回退到映射字体——不要依赖它们渲染。
- 切换主题 = 重跑生成器（`generate-composition.py --theme=<id>`），
  章节视觉代码一行不用动，规则同 v1。

---

## 内置主题

24 套主题，每个都有**独立的设计 DNA** —— 不是简单的换色版。挑一个
匹配你主题情绪的，或者作为你自己主题的起点。

### 深色主题

| id                | 性格                                                                                                                                                                                                            |
| ----------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `midnight-press`  | 电影感编辑级深色。暖色 espresso（不是纯黑）+ 火热橙。Instrument Serif italic 英文 vs Noto Serif SC 中文。hero 数字：斜体衬线。慢速电影感节奏。140×100 padding。只有 vignette，没有颗粒。            |
| `chalk-garden`    | 深石板黑板。Patrick Hand 全场手写，粉笔黄 accent。**2px 虚线 rule** 是签名。film grain（overlay）+ vignette。衬线带 chalk text-shadow。手绘节奏。                                                                |
| `terminal-green`  | 80 年代磷光终端。纯黑 + JetBrains Mono only + 0px 直角。**CRT 扫描线**贴在舞台上。文字带磷光 text-shadow。利落线性动效。hero 数字：等宽带发光。                                                  |
| `blueprint`       | 工程蓝图。深海军蓝 + 绘图青 + IBM Plex Mono。**2px 虚线青色 rule + 60px 制图网格**是签名。hero 数字：等宽青色。等宽配对营造技术 / 蓝图感。                                                                       |
| `dark-botanical`  | 高级感编辑暗底 —— 时尚刊物 / 博物馆图录。近黑 + 暖陶 / 玫粉 / 鎏金叠层。Cormorant italic + IBM Plex Sans。**柔光晕染（blurred light pool）作为签名**。慢速电影感节奏。140×100 padding。              |
| `neon-cyber`      | 赛博朋克未来派。深海军底 + 电光青 + 玫红双霓虹。Clash Display + Satoshi。**青色发光网格 + 双色霓虹描边（cyan + magenta text-shadow）**是签名。snappy 节奏。                                       |
| `bold-signal`     | hero pitch-deck 暗底。Archivo Black + Space Grotesk。大橙色焦点色卡 + 制表数编号。**对角线深色渐变 + 大字标语**是签名。punchy 节奏。                                                                |
| `creative-voltage`| 复古朋克创意工作室。饱和电光蓝底 + 霓虹黄强调。Syne + Space Mono。**halftone 网点 + 偏移霓黄阴影**是签名。punchy + 能量节奏。                                                                       |

### 浅色主题

| id                   | 性格                                                                                                                                                                                                            |
| -------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `paper-press`        | midnight-press 的白天孪生兄弟。暖奶油 + 纸纹（multiply blend）。火热橙。hero 数字：斜体编辑级衬线。慢速电影感节奏。140×100 padding。                                                                              |
| `warm-keynote`       | 现代 SaaS keynote。奶油 + 棕褐墨 + 青绿 + Inter。**大圆角（32px）glass slab** 配 backdrop blur。**粗黑 font-black hero 数字**。舞台上 40px 暖色网格。弹簧动效。                                                  |
| `newsroom`           | NYT 报刊。报纸奶油 + 墨黑衬线 + 旗红。Playfair Display + Noto Serif SC。**0 圆角**（报纸不会圆角）。hero 数字：超大斜体显示衬线。安静的印刷节奏。淡纸纹。                                                        |
| `bauhaus-bold`       | 现代主义宣言。米白 + 墨黑 + 原色蓝。Archivo Black + Inter。**0 圆角 + 4px 实色厚边 + 4px 黑色画框包住舞台 + 偏移实色阴影**。hero 数字：font-weight 900 巨字。利落快速动效。无装饰。                              |
| `sunset-zine`        | 独立 risograph zine。暖桃 + riso 洋红 + Fraunces。**虚线剪贴线 + 偏移桃色阴影**。hero 数字：斜体 Fraunces。粗 riso 纸纹。弹簧 overshoot 动效。                                                                  |
| `monochrome-print`   | 安静精炼的印刷杂志 —— Monocle / Wallpaper / MIT Press。米白 + 墨黑衬线 + 墨蓝 accent。Source Serif。**只有 1px 实线发丝、4px 精炼圆角**。hero 数字：斜体 tabular figures。**无装饰** —— 极简纯粹。极静节奏。 |
| `vintage-editorial`  | 俏皮编辑奶油底。Fraunces italic + Work Sans + 暖陶 accent。**细线几何叠层（圆 + 线 + 点）**是签名。有性格、会说话，像专栏作家。中速带轻微 overshoot。                                                            |
| `pastel-dream`       | 友好柔光。柔粉蓝灰底 + 奶油卡 + 鼠尾草绿。Plus Jakarta Sans。**大圆角（20px）+ 右侧多色 pill 色条**是签名。soft springy。                                                                          |
| `split-canvas`       | 双拼画布 —— 蜜桃 + 薰衣草 50/50 硬切分。Outfit + 玫红 accent。**屏幕本身就是双色底**，章节自由在哪一侧落内容。playful 中速。                                                                       |
| `electric-studio`    | 企业电光蓝。净白底 + 单一电光蓝 + Manrope。**贴底 4px 电蓝条**作为签名，B2B / 路演 / 财报场景的清晰自信。punchy 节奏。                                                                              |
| `indigo-porcelain`   | 靛蓝瓷 —— **靛蓝当墨**（不是 accent，是字色本身）+ 瓷白纸。Playfair Display italic + Noto Serif SC + IBM Plex Sans 正文。学术 / 研究气质，像一本当代思想期刊。无装饰 —— 纯粹。慢速。                       |
| `forest-ink`         | 森林墨 —— **森林绿当墨** + 象牙暖纸。Source Serif 正文 + Playfair Display。旧版《国家地理》感，沉稳、文献感。faint warm grain。慢速。                                                                  |
| `kraft-paper`        | 牛皮纸 —— **深棕当墨** + 牛皮米。Fraunces + Source Serif + 紫铜 accent。老笔记本 / 老信封感。**粗暖纸纹**是签名。慢速 tactile。                                                                       |
| `dune`               | 沙丘 —— **炭褐当墨** + 沙底 + 几乎无 accent（muted clay）。Inter display + Source Serif 正文。**无装饰 + 极宽 padding（140×100）**是签名。建筑手册 / 画廊感。最慢节奏。                                |
| `swiss-ikb`          | 瑞士国际主义。**极细 200 weight Inter / Helvetica** + 净暖白底 + IKB 克莱因蓝 + **1px 发丝网格 (64px)**。`r-card: 0` 直角。Massimo Vignelli / Helvetica Forever 能量。punchy + linear。           |
| `editorial-archive`  | 瑞士编辑档案系统。暖色生纸（`#F2EFE9`）+ 炭墨黑 + 低饱和朱砂砖红（`#C8553D`）+ 氧化黄高光。Playfair Display 斜体衬线 + Noto Serif SC + Space Grotesk + JetBrains Mono。**1px 工程发丝线 + 0px 档案直角 + 四域×独奏/群像节奏矩阵**，配套预埋子元素动效契约（[`svg-animation-contract.md`](svg-animation-contract.md)）。 |


随时列出可用主题：

```bash
bash visual/scripts/scaffold.sh --list-themes
```

---

## 挑一个主题、换一个主题

生成组成品时指定主题；不指定就用 `.theme` 里的那个，再不然是 `midnight-press`。

```bash
python3 visual/scripts/generate-composition.py <project> --theme=newsroom
```

换主题 = 换一个 id 重跑这条命令，章节视觉代码一行不用动。生成器会把
`visual/themes/<id>/tokens.css` 的 `:root` 内联进 `composition/index.html`。

如果切换后某一步看起来有问题，那是那一步在某处硬编码了颜色 / 字体 /
尺寸，而不是用语义 token。去找出来 —— bug 在那一步里，不在主题里。

---

## 完整 token 契约

主题的 `tokens.css` 提供**调色板 + 字体 + 性格旋钮 + 装饰**这四类。

> **v2 没有 `base.css`。** 生成器只把这一份 `tokens.css` 的 `:root` 内联进
> composition，所以某个 token 主题没定义、又没有 `var(…, fallback)`，用到它的
> 那条 CSS 声明会被整条丢掉。必填项由 `check_themes.py` 挡住；可选装饰项
> 主题不写就是"没有这个装饰"，这是有意的。

> 字号 / 间距尺度由章节自己写。章节这一层要不要 `var(--t-h1)` 还是直接写
> `font-size: 96px` 完全自由。

### 必填（主题必须定义）

#### 表面色（4 个）

| token         | 作用                                                |
| ------------- | --------------------------------------------------- |
| `--shell`     | letterbox / 舞台外的页面背景                        |
| `--surface`   | 舞台主背景                                          |
| `--surface-2` | 凸起 —— 卡片、代码块、嵌入面板                      |
| `--surface-3` | 最里层 —— surface-2 里再嵌一层时用                  |

#### 文字（4 个，前三个按 4.5:1 校验）

| token          | 作用                                  | 对比度           |
| -------------- | ------------------------------------- | ---------------- |
| `--text`       | 主                                    | ≥ 4.5:1（判）    |
| `--text-2`     | 次（副标题、正文）                    | ≥ 4.5:1（判）    |
| `--text-mute`  | 静音 —— 标签 / 元数据                 | ≥ 4.5:1（判）    |
| `--text-faint` | 三级 —— 提示 / 禁用                   | 不限（只报实测）  |

#### 线条（1 个）

| token    | 作用              |
| -------- | ----------------- |
| `--rule` | 发丝分割线颜色    |

#### Accent（3 个）

| token           | 作用                                          |
| --------------- | --------------------------------------------- |
| `--accent`      | accent 本体（一个品牌强色）                   |
| `--accent-soft` | 低透明度叠层 —— pill 背景、悬浮光晕            |
| `--accent-glow` | 中透明度叠层 —— text shadow、圆点发光          |

#### 字型家族（4 个）

| token               | 作用                                       |
| ------------------- | ------------------------------------------ |
| `--font-display-cn` | 中文显示家族                               |
| `--font-display-en` | 拉丁显示家族（斜体强调声音）               |
| `--font-body`       | 正文 / 段落家族                            |
| `--font-mono`       | 等宽家族（终端、mono caps、badge）          |

#### 圆角刻度（6 个，24 套共用同一组值）

`--r-card` 指向这套刻度，所以刻度必须在主题里、并且各套一致
（`check_themes.py` 逐套比对）：

| token      | 值    | 性格     |
| ---------- | ----- | -------- |
| `--r-flat` | `0`   | sharp    |
| `--r-xs`   | `4px` | refined  |
| `--r-sm`   | `8px` | —        |
| `--r-md`   | `16px`| soft     |
| `--r-lg`   | `20px`| —        |
| `--r-xl`   | `32px`| keynote  |

### 可选的性格覆盖（主题应该定义来表达自己的性格）

主题写哪几项，章节就有哪几个性格维度可用。**"常见值"是 24 套现有的取值，
供你对照自己的意图，不是 base 默认值**——主题不写某一项，用到它的那条 CSS
声明就没有值（整条丢掉），所以想要这个维度就得给值。

| token              | 常见值              | 作用                                                  |
| ------------------ | ------------------- | ----------------------------------------------------- |
| `--font-features`  | `"tnum","ss01"`     | body 上的 OpenType 特性栈                             |
| `--r-card`         | `--r-md`            | 卡片默认圆角（sharp / refined / keynote）              |
| `--r-stage`        | `0`                 | 舞台本身的圆角                                         |
| `--rule-w`         | `1px`               | 分割线粗细（1=发丝，2=中等，4=厚重）                   |
| `--rule-style`     | `solid`             | 分割线样式（`solid` / `dashed` / `dotted`）            |
| `--hero-num-font`  | `--font-display-en` | hero 数字用什么字体（主题决定性格）                    |
| `--hero-num-style` | `italic`            | `italic` / `normal`                                   |
| `--hero-num-weight`| `400`               | 400（编辑级）/ 500（等宽）/ 900（粗黑）                |
| `--hero-num-track` | `--track-tight`     | hero 数字的字距                                       |
| `--stage-pad-x`    | `96px`              | 舞台横向内边距（密度旋钮）                            |
| `--stage-pad-y`    | `80px`              | 舞台纵向内边距                                        |
| `--card-shadow`    | none                | 卡片的 box-shadow                                     |
| `--card-glass-bg`  | `rgba(255,255,255,0.06)` | 玻璃卡片材质层的背景                            |
| `--card-glass-border` | `rgba(255,255,255,0.12)` | 玻璃卡片材质层的边框                        |
| `--shadow-stage`   | dark drop           | 舞台的 box-shadow                                     |
| `--stage-border`   | `none`              | 舞台的可选边框（Bauhaus 用 `4px solid black`）         |

### 可选的装饰层（主题可选用，给质感加签名）

装饰画**在舞台上**、不在整页上，所以会被屏幕录制器捕捉到：pattern 作舞台的
`::after`，vignette 作舞台的 `::before`，章节自己写这两条规则。主题不写就是
没有这个装饰。

| token                        | 作用                                                                                                       |
| ---------------------------- | ---------------------------------------------------------------------------------------------------------- |
| `--surface-pattern`          | 叠在舞台上的 `background-image`。SVG 噪声 / 网格 / 扫描线。                                                |
| `--surface-pattern-size`     | 配套的 `background-size`。可平铺渐变必填。                                                                  |
| `--surface-pattern-blend`    | pattern 层的 `mix-blend-mode`（`normal` / `multiply` / `overlay`）。                                       |
| `--surface-pattern-opacity`  | pattern 层的整体透明度乘子。                                                                                |
| `--surface-vignette`         | vignette 叠层的 `background`（黑板 / 电影感边角的径向渐变）。                                              |
| `--text-shadow`              | 叠在斜体强调 / 中文衬线 / 英文显示字上的阴影。如粉笔晕、磷光辉。                                            |

如果你需要的装饰找不到对应槽位，那就跨过"主题契约"边界进入"章节自定义
CSS"领域 —— 在那里解决，别扩主题契约。

---

## 创作新主题

### 1. 复制一个最接近的作为起点

挑一个**最接近**你目标气质的：

| 目标情绪                                | 起点                  |
| --------------------------------------- | --------------------- |
| 阴郁、电影感、编辑级                    | `midnight-press`      |
| 编辑级 - 浅色                           | `paper-press`         |
| 现代 keynote / SaaS                     | `warm-keynote`        |
| 教室 / 解说                             | `chalk-garden`        |
| 终端 / 黑客 / 复古 CRT                  | `terminal-green`      |
| 纪录片 / 严肃 / 新闻                    | `newsroom`            |
| 工程 / 蓝图 / 技术                      | `blueprint`           |
| 现代主义 / 布鲁塔利斯特 / 宣言          | `bauhaus-bold`        |
| 独立 / 玩味 / zine                      | `sunset-zine`         |
| 精炼 / 安静 / 印刷                      | `monochrome-print`    |
| 高级感暗底 / 时尚 / 博物馆图录          | `dark-botanical`      |
| 赛博朋克 / 未来感 / AI / web3           | `neon-cyber`          |
| 俏皮编辑 / 有声音的博主 / 文化随笔      | `vintage-editorial`   |
| 柔粉 / 友好 / onboarding / 女性向       | `pastel-dream`        |
| 双色分屏 / 对照 / 辩论                  | `split-canvas`        |
| pitch deck / 大字宣言 / 焦点色卡         | `bold-signal`         |
| B2B / 企业 / 投资人路演                 | `electric-studio`     |
| 复古朋克 / 创意工作室 / 设计周          | `creative-voltage`    |
| 学术 / 研究 / 中国当代文化              | `indigo-porcelain`    |
| 自然 / 可持续 / 户外 / 纪录             | `forest-ink`          |
| 文学 / 怀旧 / 书评 / 手工艺             | `kraft-paper`         |
| 建筑 / 艺术展览 / 高端画廊              | `dune`                |
| 瑞士国际主义 / Helvetica / 信息驱动设计 | `swiss-ikb`           |
| 瑞士档案 / 深度调研 / 编辑拼贴 / 预埋 SVG 动效 | `editorial-archive` |

```bash
cd visual/themes
cp -r monochrome-print my-theme
```

### 2. 改 `my-theme/tokens.css`

按契约自上而下走一遍：调色板 → 字体 → 圆角刻度 → 性格旋钮（`--r-card` /
`--rule-*` / `--hero-num-*` / `--stage-pad-*`）→ 阴影 → 装饰。
字号 / 间距尺度由章节自己写，不进主题。

**几条不那么显而易见的规则：**

- 深色主题里 `--shell` **比 `--surface` 更深 / 更饱和**；浅色主题里
  `--shell` **比 `--surface` 略灰一点** —— 这样舞台读起来是"主体"，
  外围会退后。
- **读得见的字要有 4.5:1**：`--text` / `--text-2` / `--text-mute` 对 `--surface`
  都按 4.5:1 判，低于它就换颜色。96px+ 的标题可以放宽到 3:1，body / cue 必须 ≥ 4.5:1。
- `--text-faint` 是**提示 / 禁用**那一档（见上面「文字」表），文档不给它数字底线，
  `check_themes.py` 也只把实测比值印出来供判断，**不判合格**。它本来就不承担阅读，
  低对比是这一档的设计；哪天你想要一档更亮的，改的是颜色，不是这条规则。
- `--accent` 是**唯一的**饱和色。第二个饱和色会跟第一个打架。
- `--accent-glow` 和 `--accent-soft` 是 `--accent` **同色相的透明度
  叠层**，永远不要用别的色相。
- 挑**一个设计签名**重重发力：虚线 rule、粗黑边、扫描线、纸纹、glass
  slab。别同时叠三个。

### 3. 改 `my-theme/theme.json`

```json
{
  "id": "my-theme",
  "name": "My Theme",
  "nameZh": "我的主题",
  "description": "一句英文描述它的气质。",
  "descriptionZh": "一句中文描述它的气质。",
  "mood": ["dark", "moody", "futuristic"],
  "bestFor": ["<匹配场景 1>", "<匹配场景 2>"],
  "preview": {
    "shell": "#080808",
    "surface": "#101010",
    "text": "#f0f0f0",
    "accent": "#ffd54a"
  }
}
```

`id` 必须等于目录名。

### 主题元数据字段说明

| 字段 | 必填 | 取值 | 决定什么 |
|---|---|---|---|
| `id` / `name` / `nameZh` | ✓ | 字符串 | 主题标识 |
| `description` / `descriptionZh` | ✓ | 一句话 | Checkpoint Plan 列清单时的简介 |
| `mood` | ✓ | 标签数组 | 模糊匹配用 |
| `bestFor` | ✓ | 场景数组 | Checkpoint Plan 智能推荐时的命中点 |
| `preview` | ✓ | 4 色对象 | Checkpoint Plan 列清单时的视觉预览 |

> **主题不再约束动画选型 / 时长 / 字号 / emoji**。视觉风格由 `tokens.css`
> 的颜色 / 字体 / 字号 token 决定，动画 / 节奏 / 视觉演示完全交给 chapter
> agent 在每章实现时按内容自由发挥，避免主题字段过早限制创造力。
>
> 风格审美约束（不要紫粉渐变、不要 emoji 装饰、不要假数据等）由
> [`composition-craft.md`](composition-craft.md) 统一规定，与具体主题无关。

### 4. 先过校验，再拿真项目看一眼

```bash
python3 visual/scripts/check_themes.py
```

它逐套检查 `theme.json` 能不能解析、必填 token 在不在、每个 `var()` 有没有解析到值、
圆角刻度是否与其他主题一致、正文对比度够不够。再用一个真项目重跑生成器，
在渲染出来的画面上核对：

- 标题在画面里很清晰，斜体强调有可读的背景。
- accent 用在唯一该用的地方，发光不爆。
- hero 数字感觉**和整体字型同源**，不像贴上去的。
- 卡片的圆角与主题性格一致（直角还是软角）。
- 装饰**被注意到一次然后被忘掉** —— 永远不打扰。

哪里不对就改 `tokens.css`，重跑生成器即可。

### 5. 加到文档里

在本文件顶部"内置主题"表里追加一行。

> **如果是从一整块参考画板（如 Pinterest 画板 / 视频参考集）逆向提取完整的视频视觉风格与预埋动效模板**（不止配一套颜色 token，还要提炼四域构图矩阵、独奏/群像呼吸阀、预埋 SVG 子元素动效并用 `/prototype` 实测），完整流程与避坑指南见 `planners-ppt-hell/references/workflow/08_video_style_extraction_sop.md`。

---

## 反模式

- **章节 CSS 硬编码 hex 颜色 / 字体名** —— 缺哪个色彩 / 字体语义就在
  契约里补一个，给所有主题加上（注意：**字号 / 间距 / 时长**硬编码不算
  反模式，章节按内容自由设计）
- **演示中途切换主题** —— 选一个，一以贯之
- **第二个 accent 色** —— 只能有一个。用尺度 + 字重做层级
- **在组件层 override 主题 token**（颜色 / 字体 / 性格签名）—— 只在
  `:root` 里覆盖。一次性的颜色需求 = 提一个派生 token，让所有主题都
  提供自己的值
- **依赖主题的 TSX 条件分支** —— 章节必须主题无关。布局依赖明 vs 暗
  = 布局脆弱，修布局
- **一个主题叠三个设计签名** —— 选 ONE 个（虚线 rule / 扫描线 /
  glass slab / 纸纹 / 粗边），三个会自己打架
