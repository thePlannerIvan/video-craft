# 接入、交接、素材定位与画框规格（`intake-and-frames.md`）

> 什么时候读：第 1–2 步接手新项目、恢复旧项目、做版式/画框（`frame`），或判断真实素材与表现载体时读本页。阶段完成标准见 [stages.md](stages.md)，命令语法见 [tools.md](tools.md)。

## 1. 接手与版本依据

读取上游 `handoff-context.md`（或 `_idea/brief.md`）、`deliverable/script.md`、`visual-brief.md`、可选静态参考页与真实素材。已有 Story 的同名交付可直接接收，不重跑 Idea。对比既有 `edit/project.md`，把本轮目标、来源与替代关系记在最前。

接手后按 [author-spec.md](author-spec.md) 运行外挂风格手册解析器：

```bash
python3 "<craft>/helpers/_internal/resolve_vault.py" --style "<style_id>"
```

按 [SKILL.md](../SKILL.md) 的能力组合矩阵确认本项目的 **`capabilities`**（底座 `剪口播` + 可自由叠加 `footage` / `motion` / `screen-demo`）与 **`frame`**（由 `helpers/frame.py resolve` 解析），写入 `edit/project.md` 与 `production-plan.md`；历史项目 `production_mode` 与 `visual-plan.json` 仅作只读兼容。

### 按需登记静态参考页（`pages/` 或 `snapshot.json`，可选）

仅当上游提供静态参考页或存在历史 `pages/` 时，在 `edit/project.md` 记录四件：类型（PPT Hell 视频路线快照 `snapshot.json` 或裸 SVG 目录）、**绝对路径**、版本证据（snapshot revision / 目录 SVG 的 sha256）、页数与 `page_key` 与章节对应关系。PNG 预览只作对照，不是源；空 `pages/` 占位目录（内部无页面文件）直接跳过，不触发拆解门禁。

工作区找静态参考页按此顺序停在首条命中（无静态参考时开启 `motion` 直接走 [visual-grammar.md](visual-grammar.md) 的 Look-Dev Gate 与思维模型动效）：
1. 项目内 `visual_screens/_internal/02_svg_source/`（兼容视图）
2. 项目内 `composition/pages/`（已有内联副本与 `manifest.json`）
3. 项目内 `scenes/`、`deliverable/scenes/`、`input/scenes/`
4. 项目根 `.pages` 或 `.snapshot` 指针（指向 `snapshot.json` 或 `_internal/02_svg_source`）
5. 作者提供的 PPT 目录 `<ppt>/_internal/02_svg_source/`

承接工作台快照时以 `visual/scripts/snapshot_input.py` 为严格校验入口（校验 `snapshot.sha256`、SVG/嵌套 SVG 字节与页面 `order`）。原 `script_hash` 不证明编辑后 SVG 与录音语义一致，保留 `content_binding` / `content_delta` 与 `script_semantics_verified: false`；静态页仅作风格、比例与构图参考，不调用旧 `page` 导入器。

### 核对 `script_hash`

`visual-plan.json` 记录了绑定的 `script.md` sha256。PPT Hell 在**录制前**核对（改屏不用重录）；`video-craft` 在**录制后**承接时再核：

```bash
python3 "<craft>/helpers/_internal/check_script_hash.py" "<project>" --script "<script.md>" --plan "<visual-plan.json>"
```

- 相符 → 继续；
- 不符 → **停下来问作者**：口播改动会让对应 Beat 画面作废，不能静默继续；
- 缺 `script.md` 或缺 `script_hash` → 按脚本退出码 2 实报无法核对，不报成功。

## 2. 上游交接、未录音预演与对齐边界

**没有音频也要完成接入**：产出 `edit/project.md`、`production-plan.md`（逐 Beat 列声音来源、画面过程、必要动作、素材与缺口、预计时长及估计依据、转场关系）、代表切片 `previs/`（标 `planned`）及录制分工空间；暂缓依赖真音频的转写/EDL/逐字审阅，不造假转写。录音到位后保留视觉设计，回第 3 步按 [visual-timeline.md](visual-timeline.md) 重绑时间。

已有剪定录音后：
- EDL 路径运行 `visual/scripts/align-visual-plan.py --plan <visual-plan.json> --script <script.md> --edit-dir <edit> --output <project>/timeline/content-alignment.json`，人工核听 `needsReview`；
- 外部音频 + SRT 用 `align-visual-plan.py --srt <SRT>`，输出候选绑定标 `srt-import`，严禁冒充 `measured`；
- 每个视觉 Step 只引用一个 `sourceBlueprintId`/`screenId`；无口播演示窗口以独立 EDL 窗口与视觉槽承载，写在 `production-plan.md` 与 `creative-check.md`，不伪造字幕 cue；
- 口播删改或漏句回内容讨论，时长冲突可通过留白、演示长度、取舍或局部重录解决，不为迁就估时强行加速原声。

## 3. 素材真实与表现能力导航

### 素材真实与表达形态

| 当前责任 | 合适的来源与处理 |
|---|---|
| 展示真实界面、数据、产物或操作 | 查原始素材；无法获取时忠实复刻并显式标 `replica`，不冒充 `original` 实录 |
| 解释关系、变化、系统、数量 | 基于真实数据与语义设计图形、模型或动画；有截图也可抽象解释 |
| 创造情绪、隐喻或视觉体验 | 可用创作/生成素材（`generated`），标明创作身份，不当真实事件证据 |
| 既要证据又要理解 | 原物 → 局部提取/模型（`schematic`） → 变化 → 回到原物 |

采集真实操作录屏须读取连续帧区间，确保界面小字在成片分辨率可读；按隐私规范脱敏，缺素材直接指出。素材身份统一记在 `production-plan.md`（`original` / `replica` / `schematic` / `generated`），不另造素材总账；所有资源使用项目内路径，保持原始宽高比，画面不夹带制作备注。

### 表现能力有限检索

先写清观众应经历的变化，再挑选最匹配的表现机制（通常每片只用 1–2 类核心能力，同类段落复用同一视觉语言；具体 Remotion 创作心法与组件规范见 [remotion-engine.md](remotion-engine.md)，音频素材按需检索 `media-use`）：

- **证据与实操**：实操录屏局部聚焦、前后对比、原物↔模型往返；
- **差异与规模**：同位对比、遮罩揭示、差值变化、数据驱动分布（严禁动效编造数据关系）；
- **流程与关系**：状态推进、路径追踪、同一场景Shell内渐进改变关系；
- **氛围与声音**：声音双轨规范见 [captions-and-audio.md](captions-and-audio.md)（人声润色 `audio_mix.py`、画面声景 `sound_design.py`），BGM 按需通过外部 `media-use` 补充；
- **静态阅读**：清晰排版与留白停留即可，静止可以是有意设计，复杂动效不自动更好；
- **默认主动效运行时**：采用 **Remotion 4**（外部运行壳与兼容边界见 [remotion-engine.md](remotion-engine.md)），不引入未在本环境验证/集成的外部渲染栈。

## 4. 版式 / 画框规格（`frame.py`，正交横切层）

> 适用条件：任何能力组合（`footage` / `motion` / `screen-demo`）需要横/竖屏版式或人物孔位约束时使用，与能力组合及风格完全正交。

### 从参考页到唯一几何真源

1. **读秩序不抄排版**：提取线宽、留白比例、字体族、字重与用色比例（如纯黑 1px 线 + `#0B0B0C`/`#121214`/`#F3F3F3` + 无序号/页码）。
2. **token 进 `production-plan.md`**：不散落在脚本里。
3. **`helpers/frame.py` 出三件套、预览与真源解析**：

```bash
python3 "<craft>/helpers/frame.py" build   "<project>" --tokens "<tokens.json>" [--out-dir "<dir>"]
python3 "<craft>/helpers/frame.py" preview "<project>" --tokens "<tokens.json>" --wide "<16:9帧>" --tall "<4:3帧>" [--out "<jpg>"]
python3 "<craft>/helpers/frame.py" resolve "<project>" [--tokens "<tokens.json>"] [--json]
```

- `build` 生成 `<project>/material/frame/` 下的 `base.png`（静态底）、`overlay.png`（素材之上的分隔线/渐隐/裁切角标，透明区约 97% alpha=0）与 `spec.md`（算出的像素坐标）。
- `preview` 调用 **`helpers/_internal/_geometry.py::fit_in_band()`**（与 `montage.py` 渲染共用同一落位实现），按 **contain** 1:1 像素左右并排合成两张真实素材帧给作者挑方向；`preview` 不套调色档。
- `resolve` 返回当前项目唯一画框几何（`canvas`、`personSlot`、`captionSafe`、`stageArea`），供 `composition`、录屏裁切、`check_visual.py`、`deliver.py` 与审阅页同源读取（兼容 16:9 横屏、9:16 竖屏及自定义预设）。
- 字体固定回退顺序：`Hiragino Sans GB` → `STHeiti Medium` → `Songti`（全无则报错退出）；注意 `✓ ✗ ☑ ✕` 在 `Hiragino Sans GB` 会变成 notdef 带叉方框，必须抽帧核对符号（[GOTCHAS.md](../GOTCHAS.md) #4）。

### 竖屏 `1080×1920` 实测参考示例

| 区域 | y 范围 | 约束 |
|---|---|---|
| 顶部留白 | `0–320` | `personSlot` 空区圆心 `(540, 170)`、`r=128` 保持空；装饰环 `ringAlpha` 仅 `0.05–0.10`（此装饰空区区别于执行画框的人物矩形） |
| 素材带 | `320–1440`（高 1120） | `contain` 等比居中：`16:9 → 1080×606`、`4:3 → 1080×810`、`4:5 竖图 → 866×1120`，露出部分填带面色 `#121214` |
| 字幕安全区 | `1440–1920`（25%） | 仅放一行字幕；除 `y≥1800` 页脚微字外不放装饰 |
| 花字位 | `y≈1258` 起，左边距 90 | 压素材带下沿；若 4:3 素材盖到 `y≈1285`，底衬渐隐须够实（alpha≈180）；低分（≤360p）素材保持 1px 线加回颗粒 |
