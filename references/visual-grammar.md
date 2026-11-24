# 画面语法、原页拆解与 Composition 制作（`visual-grammar.md`）

> 什么时候读：`production_mode == "keyframe-svg"`（图形动画与实机演示同轨模式），从四档视觉分拍表构思、风格参考到编写 `composition/` 全程读本页。阶段要求见 [stages.md](stages.md)，工具见 [tools.md](tools.md)。

## 1. 创作主线与方案边界

接手时分清三层：**已锁定**（核心意思、真实证据、作者明确动作与固定字句，直接继承）、**可设计**（信息分组、空间结构、镜头与动效节奏，Craft 主动设计更好方案）、**需回谈**（改动主张、丢信息、要求重录或与明确决定冲突时单独回问作者）。

每个关键场景在 `production-plan.md` 写明四件事：**起始画面 → 发生什么变化 → 结束画面与停留 → 口播触发句（精确 cue/词位）**，再派生时间。同一视觉空间或模型可跨多个 Beat 延续（相邻 clip 保持连续状态、各自保留独立 `screen_id`/`beat_id`），不在方向未定时全片精渲。仅关键分歧时给 ≤2 个不同表达机制的代表片段合在一次带声工程审阅里比较。

## 2. 四档视觉语法分拍表：`film.py` 与 `visual-plan.json`

> **核心不变量**：内容不重写，**废除强制逐元素搬运静态参考页的旧闸门**。静态参考图/关键帧仅提取配色、比例与造型风格参考；没有 `visual-plan.json`（或兼容老工程的 `pages/`）不许进入交付。

```bash
python3 "<craft>/helpers/film.py" init   "<project>" [--overwrite]
python3 "<craft>/helpers/film.py" proxy  "<project>" [--max-width 960 --crf 28]
python3 "<craft>/helpers/film.py" verify "<project>" [--json]
```

`<project>/visual-plan.json` 为每个口播语义段声明四档视觉语法之一（同一条实测时间轴允许自由混排，**人物继续保持独立一轨**）：

1. **`talk-only`（只看人留白档）**：故事引入、观点铺垫、金句与过渡；保留干净人物景别，不硬叠图形卡片。
2. **`logic-diagram`（逻辑演进档，默认主力）**：集合、洞察、定位、因果与对比；每屏严格 1–2 个主视觉图形 `hero` + 1–6 个极简核心大字锚点 `anchors`，禁整句上屏或机械打字。
3. **`theory-board`（理论拆解档）**：多维框架或步骤清单；`focusMode` 保持焦点聚光灯，当前讲到哪一项该项高亮放大、其余条目自动压暗退后。
4. **`demo-footage`（实机演示录屏档）**：技能分享与软件操作录屏与动效在同一份画面成片内交替混排；
   - **审阅阶段**：严禁把百兆高清原录屏塞进 `composition/assets/`；跑 `film.py proxy` 在 `review/demo_proxies/` 生成低码率静音预览代理。
   - **交付阶段**：`deliver.py` 按 `demo.source` + `inSec/outSec/speed` 直接从高清原录屏裁切，开启清晰文字保护编码（Lanczos + `crf=16` + `deblock=-1,-1` + `aq-mode=2`），与动效段无损拼合进 `<name>_画面成片.mp4`，并独立产出 `<name>_人物轨.mp4`。

- **老工程兼容**：仅当不存在 `visual-plan.json` 且存在旧 `pages/` 目录时，`film.py {outline|pages|verify}` 继续按原表校验。

## 3. Recompose 路线契约与几何（唯一坐标源）

`recompose` 是 `keyframe-svg` 的唯一现行路线（旧 `page` 十步路线与 `storyboard.md` 均已退役；仅复活老 `page` 项目需兼顾历史 `storyboard.md` 格式与兼容代码）。

产物结构：
- `<project>/recompose.json`：`canvas`、`personSlot`、`captionSafe`、`composition` 路径；
- `<project>/recompose/lines.json`：按字幕口播行为单位的视觉密度状态（`auto` / `off` / `still` / `light` / `full`）与模型 `proposal`；
- `<project>/feedback/density.jsonl`：`review_inbox.py` 收件后追加。

```bash
python3 "<craft>/helpers/recompose_plan.py" init  "<project>" --composition "<project>/composition" --person-slot "0,0,620,1080" --caption-safe "0,885,1920,195"
python3 "<craft>/helpers/recompose_plan.py" check "<project>"
python3 "<craft>/helpers/recompose_plan.py" lines "<project>"
```

**几何规则**：场景文件（`src/scenes/*.js`）严禁手算或硬编码 `500/620/880` 等像素数，一律从 `recompose.json` 读取：
- **人物区**：`x ∈ [personSlot.x, personSlot.x + personSlot.w)` 全高（默认 `0..620`），画面不得进入；人物在右时镜像；
- **字幕安全区**：`y ∈ [captionSafe.y, captionSafe.y + captionSafe.h)`（默认 `y=885..1080`），只放字幕/角标，不放主体；
- **画面安全区**：其余矩形范围；
- **两种合法形态**：① **合成层**（composition 内嵌人物 `<video class="clip">` + 画面，避开人物区）；② **仅画面层**（黑底只绘画面，交付阶段由 `deliver.py` 按 `recompose.json` 贴回人物与声音，可躲开活舞台母版体积预算）。

> **密度 `off` 是结构指令**：标 `off` 的句必须删除/隐藏该段视觉层（拆段或停顿淡出），严禁靠 `opacity: 0` 敷衍；`lines.json` 的修改必须同步落回 `composition/src/scenes/*.js`。

### 四类画面语法与强调体系

在同一个画面内先选定表达语法，不混用多套逻辑：
1. **镜头语法**（讲结构关系）：单机位在一块整板上推拉摇移；**板宽 ≤ 舞台宽 / 1.15**（防止 1.1x 推镜切边）。
2. **抽卡语法**（讲逐条展开）：局部卡抽至正中放大、背景压暗后躺（`rotateX`）、答案按口播擦出后缩回原位；缩回前必须把原板上对应层的文本同步写到终态。
3. **固定槽位 + 单套字级**：「说一点出一点」直接在最终坐标显形，不靠动态居中造成文字跳移；全板除刻意分层外共用一套字号/字重/字距，改动前后跑 `helpers/_internal/check_motion_targets.py` 与文字排版检查。
4. **口播/演示窗口**：无口播纯画面/录屏演示窗口在 `production-plan.md` 与 EDL 单独留窗，不硬凑伪字幕。

## 4. Composition 写作硬规（HyperFrames）

核心引擎是 **HyperFrames**（写作前应先读 `/hyperframes-core` 与 `/hyperframes-animation`）。视觉唯一真相是 `<project>/composition/`：

- **禁止篡改生成时序**：`data-start`、`data-duration`、`data-track-index`、根 `data-duration` 与 `<audio>` 只能来自 `timeline/timeline.json`（改时间必须重改分组→重派生 `timeline_derive.py`），禁止手工微调覆盖源不一致。
- **单个暂停时间轴**：`window.__timelines = window.__timelines || {}; window.__timelines[<id>] = HF.tl`（名称全等 `#root[data-composition-id]`）；所有执行逻辑必须写在外部 `src/*.js` 中（见 [visual-checks.md](visual-checks.md) 活舞台五条硬契约）。
- **初始态与 Seek 安全（[GOTCHAS.md](../GOTCHAS.md) #10 / #48）**：
  - 首帧隐藏状态用 `gsap.set(...)` 写在时间轴**外**（位置 0 的 `tl.set` 第 0 帧不生效）；
  - 全局设定 `gsap.defaults({ immediateRender: false })`，否则后段 `fromTo` 会把初始态拉平；
  - 渲染是逐帧 seek 而不是线性 play：**`onStart` 回调在渲染时不重放**，状态切换一律预建元素改 `opacity`/`zIndex`；
  - **绝不把 CSS 静态 `transform`（或 SVG `transform="translate(...)"`）与 GSAP 补间挂在同一元素上**，静态位移/旋转放在外层静态包裹层 `<g class="unit" transform="...">`，动画挂在内部/外部专属层；
  - 满屏底色画在 `inset: 0` 子元素，不直接涂在 `#root`；正文不用 `<br>`；资产路径用 `../input/assets/...`（或 `<audio>` 根相对 `assets/audio.m4a`）并按真实目录 `glob()` 枚举（不用拼模板路径）。
- **字体实测宽度防折行**：`hyperframes check` 不会拦截文字折行溢出。混排按汉字 `1.0em`、英文/数字/空格约 `0.5–0.55em`、中点 `·` 与 `%` 约 `0.62–1.0em` 留 ≥8% 余量；每写完一章跑 `cd composition && npm run check` 后再用 `npx hyperframes snapshot --at <中点> --zoom 2` 实看折行与对比度。注意 `hyperframes check`/`render` 会注入 `data-hf-id` 并重写 HTML，回改前先重读上下文。

## 5. SVG 预埋子件微动效契约（可选）

当原 SVG 或分镜包显式使用 `data-step`、`data-anim`、语义子类名（`.anim-stroke`、`pathLength="1"`、`.anim-endpoint`、`.anim-card`、`.anim-shadow`、`.anim-tape`、`.wipe-bar`、`.anim-fill`、`.anim-wall`、`.slot-left/.slot-core/.slot-right`、`.anim-badge`、`.anim-stamp`、`.anim-paper`、`.anim-target/.anim-expand`、`.anim-count` 等）时：

- **锚点层与步进层分离**：`<g id="{page_key}-anchor" data-role="anchor">` 放全程静止骨架；`<g id="{page_key}-step-N" data-step="N" data-anim="...">` 放分步子件；全片内联 id 带 `{page_key}-` 前缀防冲突。
- **复合子件连锁**：每组含 2–3 层子件（如 `draw-stroke` 先画开放 `<path class="anim-stroke" pathLength="1">` 再弹簧弹出末端卡片；`polaroid-slap` 先落相纸同步收阴影最后抹胶带；`cursor-wipe` / `meter-halt` / `slot-push` / `stagger-cards` / `stamp-in` / `paper-unroll` / `cursor-click` / `number-ticker` / `card-expand` / `spotlight-sweep`）。
- **时钟所有权 boundary**：在 HyperFrames 新工程中保留这些语义类名与外层结构，由 composition 自己的 seek-safe GSAP 时间轴驱动，**严禁**把兼容层的 `VideoCraftAnimEngine.registerGsapTimeline()` 接入新工程主时钟；左人右画场景在根 `<svg>` 声明 `data-speaker-width="608"` 防元素平进人物区。
