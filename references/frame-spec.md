# 版式 / 画框规格（frame）

> 什么时候读：作者给了**参考页**（某个品牌的视频页 / 官网 / 社媒页面），或要求"竖屏、留字幕区、
> 上面留个位置放人"这类版面约束时。片型是 graphic 还是 montage 都适用——画框是横切的一层。

画框回答四个问题：**画面放在哪、字幕留给谁、装饰用什么语言、哪些位置必须保持空**。
它和片型正交：`montage × frame` 是哈雷那一版（档案素材 + 竖屏画框），
`graphic × frame` 是带画框的动画片，`graphic × 无 frame` 就是原来的 recompose。

## 从参考页到 token（三步）

1. **读参考页的语言，不是抄它的排版。** 看它用什么做秩序：线宽、留白比例、字体族、字重、
   彩色出现的比例。Vans 官网的可复用结论是：chrome 只用**纯黑 1px 线**和近白 `#F3F3F3`，
   标题用 condensed 大写 + 宽字距，彩色只出现在照片里，序号/页码一律没有。
2. **把结论写成 token**：底色、面（素材带）色、线色/线宽、文字色、字号与字距、边距。
   token 进 `production-plan.md`，不散落在脚本里。
3. **出三层产物**（放 `<project>/material/frame/`）：`base.png`（静态底：底色/肌理/细线/文字/空位）、
   `overlay.png`（叠在素材**之上**的：分隔线、边缘渐隐、角度裁切标记）、`spec.md`（像素坐标表）。
   两层分开的理由：`base` 会被素材盖住，`overlay` 不会。

**素材落位只有一处实现：`helpers/_geometry.py` 的 `fit_in_band()`（`montage.py` 渲染与 `frame.py` 预览都调它）。上面的 606/810/1120 是 2026-11 成片里实测的数字，不是估算——改画布或改素材带高度时，先算一遍再写进文档。

先出两版方向给作者挑**，再定稿：两版各带一张 16:9 和一张 4:3 的真实素材占位帧，
1:1 像素出图。别用抽象色块预览——那时看不出素材边缘和画框线的关系。

## 竖屏 1080×1920 的实测契约

哈雷片用过的版式，可直接作为竖屏默认值；换项目时**逐条确认再改**：

| 区域 | y 范围 | 约束 |
|---|---|---|
| 顶部留白 | 0–320 | 人物位圆心 (540,170) r=128 **保持空**；圆环只用 5–10% 不透明度当肌理，不读成"空头像" |
| 素材带 | 320–1440（1120 高） | 素材等比缩放到带内、**整幅可见**（contain）：16:9 → 1080×606、居中；4:3 → 1080×810、居中；竖图（约 4:5）→ 866×1120、左右留带面。露出来的是**带面色**，不是黑 |
| 字幕安全区 | 1440–1920（25%） | 只放一行字幕；除页脚微字（y≥1800）外不放任何东西 |
| 花字位 | y≈1258 起，左边距 90 | 花字压在素材带下沿；底衬一条轻渐隐，不做圆角色块 |

装饰语言：底色 `#0B0B0C` / 带面 `#121214`（差值很小，靠亮度差读成两个面）、
素材带上下各一条 1px 纯黑线、画面顶底 28px 极轻暗角、静态颗粒 ±2 与动态颗粒叠加时减量。
**不要**：序号/页码/素材计数、彩色 accent、发光、粗描边、圆角卡片。

## 与素材的关系（容易吵起来的地方）

- 素材是 4:3 时画面更高，下沿到 y≈1285、盖住花字位（y≈1258）：底衬必须够实（alpha ≈ 180），
  否则文件类素材（白底报告）上的花字直接不可读。
- 素材自带小角标（档案台标）时，画框不要再往同一角放东西。
- 素材分辨率低（≤360p）时不要靠画框的锐利细线对比——线越细，软素材越显软；
  这时把线宽维持 1px、把颗粒加回去，观感更统一。

## 产物验收

- `base.png` / `overlay.png` 与画布同尺寸；`overlay.png` 的透明区必须真透明（97% 像素 alpha=0 量级）。
- `spec.md` 里每个元素都有像素坐标、颜色、字号、字距；两种素材落法（16:9 / 4:3）都验过。
- 拿一帧真实素材合成出来给人看，而不是只看底图——底图好看不代表压上素材还成立。

## token 文件与 `frame.py`

画框不再手写 PIL 脚本：把上面的结论写成一份 token JSON，由 `helpers/frame.py`
出 `base.png` / `overlay.png` / `spec.md`，再用真实素材帧出一张并排预览给人看。

### 两条命令

```bash
# 三件套（默认落 <project>/material/frame/）
python3 helpers/frame.py build <project> --tokens <tokens.json> [--out-dir <dir>]

# 真实素材合成预览（1:1 像素，左右并排）
python3 helpers/frame.py preview <project> --tokens <tokens.json> \
  --wide <16:9 素材帧> --tall <4:3 素材帧> [--out <jpg>]
```

- `preview` 的两种落位与 `spec.md` 的「素材落位」表同一口径，都是 **contain**：
  16:9 → 1080×606，在素材带内垂直居中；4:3 → 1080×810，水平居中、整幅可见，**不裁两侧**。
  「预览 = 成片」不是一句承诺，而是被钉住的判据：预览与渲染调同一条 `fit_in_band()`，
  `tests/test_geometry.py` 断言三组典型值并覆盖「永不裁素材」。输出宽 = 画布宽 ×2、
  高 = 画布高，默认 `preview.jpg`。
- token 缺字段时按下面的默认值补齐，并在 stderr 逐项说明补了什么，不静默。
- 字体不在 token 里：固定按 Hiragino Sans GB → STHeiti Medium → Songti 的顺序回退，
  三个都取不到就报错退出，不退到 PIL 默认字体。
- 字体缺字形不报错：`✓ ✗ ☑ ✕` 在 Hiragino Sans GB 里会落成同一个带叉方框（notdef）。
  PIL 出的卡片在出片前抽一帧看符号，或把符号 mask 与 notdef 比（GOTCHAS #4）。
- 退出码：0 成功；1 token / 素材有问题（stderr 给一句能读的原因）；2 用法错误。

### token 字段

| 字段 | 含义 | 默认值 |
|---|---|---|
| `canvas.width` / `canvas.height` / `canvas.fps` | 画布尺寸与帧率 | 1080 / 1920 / 30 |
| `band.top` / `band.bottom` | 素材带上下边界行（`bottom` 是下边界线所在行） | 320 / 1440 |
| `band.inset` | 带区两条线距左右边缘的像素 | 90 |
| `band.tick` | 带区线两端刻度长度 | 18 |
| `palette.bg` / `band` / `line` / `text` / `muted` | 色板 | `#0B0B0C` / `#121214` / `#000000` / `#F3F3F3` / `#6E6E6A` |
| `texts[]` | 文字数组，逐条见下 | 竖屏默认五处文字 |
| `texts[].id` | 位置标识，写进 `spec.md` | `""` |
| `texts[].text` | 文字内容（必填） | — |
| `texts[].size` | 字号 px | 32 |
| `texts[].tracking` | 字距 px（逐字补，不是 CSS letter-spacing） | 0 |
| `texts[].baseline` | 基线 y | 161 |
| `texts[].x` | 左起 x；`align=right` 时是右对齐基准 x | 90 |
| `texts[].align` | `left` / `right` | left |
| `texts[].color` | `#RRGGBB` 或 palette 键 | `text` |
| `texts[].uppercase` | 是否转大写 | false |
| `texts[].condense` | 字形横向压缩比（只压字形，字距不跟着压） | 1.0 |
| `personSlot.cx` / `cy` / `r` | 人物位圆心与空区半径 | 540 / 170 / 128 |
| `personSlot.ringOffset` | 圆环画在空区外多少 px（空区保持干净） | 5 |
| `personSlot.ringWidth` / `ringAlpha` | 圆环线宽 / 不透明度 | 1 / 0.10 |
| `cropMarks.inset` / `length` / `width` / `color` | 四角裁切标记 | 40 / 18 / 1 / `line` |
| `grain.amplitude` / `grain.dither` | 静态颗粒 ±级 / 防色带抖动 ±级 | 2 / 1 |
| `vignette.height` / `maxAlpha` / `color` | 画面顶底暗角高度 / 最大 alpha | 28 / 26 / `line` |

### 竖屏 1080×1920 的完整 token

```json
{
  "canvas": {"width": 1080, "height": 1920, "fps": 30},
  "band": {"top": 320, "bottom": 1440, "inset": 90, "tick": 18},
  "palette": {
    "bg": "#0B0B0C",
    "band": "#121214",
    "line": "#000000",
    "text": "#F3F3F3",
    "muted": "#6E6E6A"
  },
  "texts": [
    {"id": "title-1", "text": "WEEKEND", "size": 32, "tracking": 7.7,
     "baseline": 161, "x": 90, "align": "left", "color": "text",
     "uppercase": true, "condense": 0.8},
    {"id": "title-2", "text": "OUTLAW", "size": 32, "tracking": 7.7,
     "baseline": 201, "x": 90, "align": "left", "color": "text",
     "uppercase": true, "condense": 0.8},
    {"id": "meta-1", "text": "CASE STUDY", "size": 11, "tracking": 2.0,
     "baseline": 166, "x": 990, "align": "right", "color": "muted",
     "uppercase": true, "condense": 1.0},
    {"id": "meta-2", "text": "OUTLAW MYTHOLOGY", "size": 11, "tracking": 2.0,
     "baseline": 181, "x": 990, "align": "right", "color": "muted",
     "uppercase": true, "condense": 1.0},
    {"id": "footer", "text": "MILWAUKEE, WISCONSIN · HARLEY-DAVIDSON",
     "size": 9, "tracking": 1.8, "baseline": 1842, "x": 90, "align": "left",
     "color": "muted", "uppercase": true, "condense": 1.0}
  ],
  "personSlot": {"cx": 540, "cy": 170, "r": 128,
                 "ringOffset": 5, "ringWidth": 1, "ringAlpha": 0.10},
  "cropMarks": {"inset": 40, "length": 18, "width": 1, "color": "line"},
  "grain": {"amplitude": 2, "dither": 1},
  "vignette": {"height": 28, "maxAlpha": 26, "color": "line"}
}
```

系统字体里没有 DIN Condensed，标题的 `condense: 0.8` 是对 condensed 字形的近似；
换项目时按参考页重新定这个值，不要沿用。

token 进 `production-plan.md`，不散落在脚本里：项目里只留 token 与三个产物，
重做画框 = 改 token + 重跑 `build`。

