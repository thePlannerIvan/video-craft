# 统一执行分镜、Look-Dev 与 Remotion 场景制作（`visual-grammar.md`）

> 什么时候读：能力组合包含 `motion`（做动效）或 `screen-demo`（实机录屏），从 `storyboard.json` 分镜、Look-Dev Gate 定调到编写 `remotion/src/` 全程读本页。能力组合总表见 [SKILL.md](../SKILL.md)，阶段要求见 [stages.md](stages.md)，Remotion 引擎细则与四道门禁见 [remotion-engine.md](remotion-engine.md)，命令见 [tools.md](tools.md)。

## 1. 创作主线与方案边界

接手时分清三层：**已锁定**（核心意思、真实证据、作者明确动作与固定字句，直接继承）、**可设计**（信息分组、空间结构、镜头与动效节奏，Craft 主动设计更好方案）、**需回谈**（改动主张、丢信息、要求重录或与明确决定冲突时单独回问作者）。

每个关键场景在 `production-plan.md` 写明四件事：**起始画面 → 发生什么变化 → 结束画面与停留 → 口播触发句（精确 cue/词位）**，再派生时间。同一视觉空间或模型可跨多个 Beat 延续（相邻 clip 保持连续状态、各自保留独立 `screen_id`/`beat_id`），不在方向未定时全片精渲。

## 2. 统一执行分镜 `storyboard.json` 与 Look-Dev Gate：`film.py`

> **核心不变量**：`storyboard.json`（`version: "storyboard/3"`）是下游执行、按段分流拼合与声景卡点的**唯一机器真源**。静态参考图/关键帧仅提取配色、比例与造型风格参考，废除逐元素搬运。

```bash
python3 "<craft>/helpers/film.py" init    "<project>" [--overwrite]
python3 "<craft>/helpers/film.py" lookdev "<project>" [--verify|--approve]
python3 "<craft>/helpers/film.py" verify  "<project>" [--json]
python3 "<craft>/helpers/film.py" summary "<project>" [--out "<overview.md>"]
python3 "<craft>/helpers/film.py" proxy   "<project>" [--json]
```

- **分镜段类型与引擎分流**（同一条实测时间轴自由混排，人物继续保持独立一轨）：
  1. `talk-only`（只看人留白）：故事引入、观点铺垫、金句与过渡；保留干净人物景别。
  2. `footage` / `video`（实拍/广告切片）：`engine: "ffmpeg-cut"`；审阅挂轻代理进活舞台，交付由 `deliver.py` 直切高清母版（素材清单与 `5s` 防重规则见 [montage-route.md](montage-route.md)）。
  3. `motion` / `model`（思维模型动效）：`engine: "remotion"`（历史只读兼容老工程允许 `hyperframes`）；无现成静态参考页时，构建随口播推进持续演化的单一空间概念模型与结构关系动画，严禁退回逐页 PPT 文字框拼接（卡片边框颜色与材质由当前风格卡自定，顶部仅留极简几何装饰）。
  4. `card-deck` / `xhs`（3D 卡片组）：`engine: "remotion"`（历史只读兼容老工程允许 `hyperframes`）；同步声明 `soundCues` 驱动 [captions-and-audio.md](captions-and-audio.md) 中的 `sound_design.py` Visual Soundscape 起伏配音。
  5. `screen-demo`（实机演示录屏）：`engine: "ffmpeg-cut"`；审阅期跑 `film.py proxy` 在 `review/demo_proxies/` 生成低码率代理进活舞台（原录屏仅放在项目素材区，严禁塞入 `remotion/public/assets/` 或历史兼容 `composition/assets/`），交付期 `deliver.py` 按 `demo.source` + `inSec/outSec/speed` 直切高清原录屏。
- **轻量样镜定调（Look-Dev Gate）**：仅当开启 `motion` 且上游未提供静态参考页时触发；在全片编码前先跑 `film.py lookdev` 输出极简配比意图清单与 1 个匹配口播节奏的代表性思维模型样镜交创作者拍板（`--approve`），`--verify` 通过后才展开全片；已有静态参考页（可走 `film.py import-svg` 包装为 Remotion 运镜场景）或成熟风格时自动跳过。
- **人读概览同源派生**：跑 `film.py summary` 从 `storyboard.json` 确定性生成 `edit/storyboard-overview.md`，消除图文两张皮。
- **老工程兼容**：仅当不存在 `storyboard.json` 且存在旧 `visual-plan.json` 或非空 `pages/` 时，`film.py {outline|pages|verify}` 保持只读兼容；空占位 `pages/` 目录不再报错。

## 3. 画框几何唯一真源（`frame.py resolve`）

所有 `remotion/src/`（及历史兼容 `composition/src/scenes/*.js`）严禁手算或硬编码默认画幅像素或人物栏宽度，一律从唯一几何真源读取：

```bash
python3 "<craft>/helpers/frame.py" resolve "<project>" --json
```

`frame.py resolve` 输出当前项目的 `canvas`（`width`、`height`、`fps`）、`personSlot`、`captionSafe` 与 `stageArea`（同时兼容 16:9 横屏、9:16 竖屏与自定义画框预设）：
- **人物区**（`personSlot`）：画面主体与文本不得侵入该区域；
- **字幕安全区**（`captionSafe`）：只放字幕/微字页脚，不放主体；
- **画面安全区**（`stageArea`）：其余舞台矩形范围，供卡片、思维模型与代理视频落位；
- **两种合法形态**：① **合成层**（舞台内按 `personSlot` 预留人物孔位并由 `deliver.py` 合流，历史兼容工程允许内嵌 `<video class="clip">`）；② **仅画面层**（只绘画面，交付阶段由 `deliver.py` 按 `frame.py` 几何与 `storyboard.json` 分段拼合并贴回人物轨）。

### 四类画面语法与强调体系

在同一个画面内先选定表达语法，不混用多套逻辑：
1. **镜头语法**（讲结构关系）：单机位在一块整板上推拉摇移；**板宽 ≤ 舞台宽 / 1.15**（防止 1.1x 推镜切边）。
2. **抽卡语法**（讲逐条展开）：局部卡抽至正中放大、背景压暗后躺（`rotateX`）、答案按口播擦出后缩回原位；缩回前必须把原板上对应层的文本同步写到终态。
3. **固定槽位 + 单套字级**：「说一点出一点」直接在最终坐标显形，不靠动态居中造成文字跳移；全板除刻意分层外共用一套字号/字重/字距，改动前后跑 `helpers/_internal/check_motion_targets.py` 与文字排版检查。
4. **口播/演示窗口**：无口播纯画面/录屏演示窗口在 `production-plan.md` 与 EDL 单独留窗，不硬凑伪字幕。

## 4. Remotion 4 场景写作硬规（含历史 HyperFrames 只读兼容边界）

新建动效项目默认引擎是 **Remotion 4**，完整工程目录、外部运行壳、纯帧守则与四道门禁由 [remotion-engine.md](remotion-engine.md) 唯一定义。视觉唯一真相是 `<project>/remotion/`：

- **Remotion 4 新工程硬规（默认）**：
  - **纯帧无状态函数**：所有位移、缩放、透明度、弹簧物理（`spring`）、路径生长与频谱驱动全部由 `useCurrentFrame()` 与 `fps` 纯函数确定性推导，保持渲染帧与活舞台零状态漂移。
  - **同源对齐唯一时间脊柱**：`Root.tsx` `<Composition>` 的 `width`/`height`/`fps`/`durationInFrames` 与分段切点直接读取 `frame.py resolve`、`timeline/timeline.json` 与 `storyboard.json`。
  - **零项目内依赖与前置四道门禁**：前端依赖统一走外部运行壳（[remotion-engine.md](remotion-engine.md)），交付与审阅按要求通过 `helpers/_internal/remotion_gates.py` / `check_visual.py`。
  - **字体与文字防折行**：字体加载统一走 `delayRender` + `document.fonts.ready` + `continueRender`；混排按汉字 `1.0em`、英文/数字/空格约 `0.5–0.55em`、中点 `·` 与 `%` 约 `0.62–1.0em` 留 ≥8% 余量，再结合 `stills` 中段抽帧目视核对折行与对比度。

### 历史 HyperFrames 工程只读兼容边界

仅当接手存量 `composition/index.html` 老工程时适用（新建工程一律使用 Remotion 4）：
- `data-start`、`data-duration`、`data-track-index` 与 `<audio>` 只来自 `timeline/timeline.json`；单个暂停时间轴 `window.__timelines[<id>] = HF.tl`，执行逻辑全在外部 `src/*.js`（[visual-checks.md](visual-checks.md)）；
- 首帧隐藏用时间轴外 `gsap.set(...)`、设 `gsap.defaults({ immediateRender: false })`、不用 `onStart` 状态回调、不把静态 CSS/SVG `transform` 与 GSAP 补间挂在同一元素上；满屏底色画在 `inset: 0` 子元素；出片前过 `hyperframes check` 与 `check_motion_targets.py`。

## 5. SVG 预埋子件微动效契约（可选）

当原 SVG 或分镜包显式使用 `data-step`、`data-anim`、语义子类名（`.anim-stroke`、`pathLength="1"`、`.anim-endpoint`、`.anim-card`、`.anim-shadow`、`.anim-tape`、`.wipe-bar`、`.anim-fill`、`.anim-wall`、`.slot-left/.slot-core/.slot-right`、`.anim-badge`、`.anim-stamp`、`.anim-paper`、`.anim-target/.anim-expand`、`.anim-count` 等）时：

- **锚点层与步进层分离**：`<g id="{page_key}-anchor" data-role="anchor">` 放全程静止骨架；`<g id="{page_key}-step-N" data-step="N" data-anim="...">` 放分步子件；全片内联 id 带 `{page_key}-` 前缀防冲突。
- **复合子件连锁**：每组含 2–3 层子件（如 `draw-stroke` 先画开放 `<path class="anim-stroke" pathLength="1">` 再弹簧弹出末端卡片；`polaroid-slap` 先落相纸同步收阴影最后抹胶带；`cursor-wipe` / `meter-halt` / `slot-push` / `stagger-cards` / `stamp-in` / `paper-unroll` / `cursor-click` / `number-ticker` / `card-expand` / `spotlight-sweep`）。
- **时钟所有权边界**：在新建 Remotion 场景中按 `useCurrentFrame()` / `evolvePath()` / `spring()` 映射分步子件（静态 SVG 参考页由 `film.py import-svg` 包装入场）；历史兼容工程保留外层结构与 seek-safe GSAP 时间轴，禁止将兼容层的 `VideoCraftAnimEngine.registerGsapTimeline()` 接入新工程主时钟；有侧栏人物孔位时从 `frame.py resolve` 读取人物区宽度边界，防止元素平进人物区。
