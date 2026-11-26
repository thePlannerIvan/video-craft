# Remotion 4 主动效引擎、外部运行壳与四道门禁（`remotion-engine.md`）

> 什么时候读：开启 `motion`（做动效）或通过 `film.py import-svg` 导入静态视觉参考页时读本页。能力组合总表见 [SKILL.md](../SKILL.md)，阶段顺序见 [stages.md](stages.md)，命令语法见 [tools.md](tools.md)。

## 1. 引擎定位与工程目录约定

v3 起 **Remotion 4** 为所有新建 `motion` 与静态视觉参考页导入项目的唯一默认主动效引擎；既有旧引擎项目（仅有 `composition/index.html`）冻结为静默只读兼容通道，由 `helpers/_internal/remotion_stage.py::detect_motion_engine()` 按工程目录特征确定性路由：

1. 存在 `<project>/remotion/src/Root.*`（或 `storyboard.json` / `recompose.json` 的 `remotionDir`）→ **Remotion 4**；
2. 否则存在 `<project>/composition/index.html` → **历史兼容只读通道**。

新建 Remotion 源码工程只存放轻量源码与少量静态引用资产，**严禁在项目目录内生成或安装 `node_modules`**：

```text
<project>/remotion/
├── src/
│   ├── index.ts          # registerRoot(RemotionRoot)
│   ├── Root.tsx          # <Composition id=... width/height/fps/durationInFrames />
│   ├── MainComposition.tsx
│   ├── scenes/           # 或 acts/，按 storyboard.json 分镜切分
│   ├── components/       # 复用卡片、光标、背景与交互组件
│   ├── utils/            # 弹簧配置、贝塞尔轨迹、音频频谱辅助
│   └── data/             # anchors / 时序常量（与 timeline.json 对齐）
├── public/assets/        # 仅放字体子集、静态参考页、必要音频/小图（大录屏禁用）
└── tsconfig.json         # 可选工程配置（编译依赖由外部运行壳注入）
```

### 静态 SVG 参考页导入

当上游提供静态关键帧 SVG 参考页时，用一键命令包装为带平滑推拉运镜与弹性入场的 Remotion 场景，不再新建旧引擎目录：

```bash
python3 "<craft>/helpers/film.py" import-svg "<project>" --source "<svg或目录>" [--seconds-per-slide 4.0] [--json]
```

底层由 `helpers/_internal/remotion_svg_scene.py` 校验 XML、改写并拷贝内联图片至 `remotion/public/assets/pages/`，并生成 `remotion/src/scenes/StaticSvgReference.tsx`。

## 2. 外部运行壳（External Runtime Shell）

前端依赖统一托管在云盘与视频项目仓之外的共享缓存目录，解析优先级：
1. `$VIDEO_CRAFT_REMOTION_HOME`（显式环境变量覆写）；
2. `$XDG_CACHE_HOME/video-craft/remotion-runtime/`（若设 `XDG_CACHE_HOME`）；
3. `~/.cache/video-craft/remotion-runtime/`（默认路径）。

```bash
python3 "<craft>/helpers/remotion_runtime.py" setup [--runtime-home <dir>] [--download-browser] [--skip-browser] [--force] [--json]
python3 "<craft>/helpers/remotion_runtime.py" doctor [--runtime-home <dir>] [--json]
python3 "<craft>/helpers/remotion_runtime.py" path [--runtime-home <dir>]
```

- `setup` 幂等锁版本安装 `remotion`、`@remotion/cli`、`@remotion/player`、`@remotion/media-utils`、`@remotion/paths`、`@remotion/noise`、`@remotion/transitions`、React 18、esbuild、TypeScript、`lucide-react`；浏览器优先自动复用本机已安装的 Chrome/Chromium 或 `$REMOTION_BROWSER_EXECUTABLE`（避免受限网络重复拉取 headless-shell），未检测到或显式传入 `--download-browser` 时按需拉取 Remotion 内置无头浏览器（`remotion browser ensure`）；首次做动效未安装时支持自动触发初始化。
- 脚本完全尊重本机已有 npm 配置，不写死地区镜像或个人机器路径；如需网络加速，可在执行前按需临时配置 `NPM_CONFIG_REGISTRY`。

## 3. 第一性原理创作心法与无状态纯帧守则

1. **无状态纯帧函数（Pure Frame Function）**：一切位移、缩放、透明度、路径生长与噪声扰动必须由 `useCurrentFrame()` 与 `useVideoConfig()`/`FPS` 纯函数推导——使用 `spring()`、`interpolate(..., { extrapolateLeft: "clamp", extrapolateRight: "clamp" })`、`Easing`、`@remotion/paths`（`evolvePath` / `getPointAtLength`）与 `@remotion/noise`（`noise2D`）。严禁依赖 `setInterval`、CSS `transition` / `@keyframes` 隐式时间状态或挂载后未绑帧的副作用。
2. **一镜一视觉主角与物理弹簧分级**：每镜只承载一个主要关系演化；通过分级弹簧阻尼（如快弹入场 `SPRING_SNAPPY`、稳重落位 `SPRING_SMOOTH`、点击回弹 `SPRING_BOUNCE`）与贝塞尔弧线光标建立可信触感；字体加载使用 `delayRender` + `document.fonts.ready` + `continueRender` 保证首帧即稳。
3. **真音频频谱驱动**：通过 `@remotion/media-utils` 的 `useAudioData(staticFile(...))` + `visualizeAudio()` 读取真实人声频谱能量，驱动波形柱、微光晕或语音激活控件；无音频数据或边界帧须做钳制兜底。
4. **唯一画框几何与双轨声音隔离**：画布尺寸、人物孔位（`personSlot`）、主舞台（`stageArea`）与字幕安全区（`captionSafe`）必须来自 `python3 "<craft>/helpers/frame.py" resolve "<project>" --json`；声音分层遵守「人声润色仅归 `人物成片.mp4`，画面声景归 `画面成片.mp4` 与 `画面音效轨.wav`」。

## 4. 零渲染 `{kw: 1}` 活舞台桥（Live Stage Bridge）

`helpers/_internal/remotion_stage.py` 为 Remotion 工程提供秒级增量打包与独立回环端口服务，审阅期**全程不触发视频帧渲染**：

- 通过外部运行壳 `esbuild` 将 `remotion/src/Root.tsx` 包装为 `@remotion/player` 实时播放容器并注入 `{kw: 1}` 跨窗口消息桥：
  - `hello` → 回传 `ready`（含 `duration`、`fps`、`width`、`height`、`id`、`paused`）；
  - `seek` → 换算目标帧 `targetFrame` 并 `seekTo` 后回传最新 `time`；
  - `play` → 连续播放并以 `200ms` 节拍持续回传 `time`；
  - `pause` → 立即停帧并同步 `paused: true`（同时支持 `rate` 与 `mute` 指令）。
- 审阅台外壳继续无缝承接分镜导航、`播客音色 vs 纯干声` A/B 切换、`画面底噪:开/关` 试听以及横竖屏自适应布局（详见 [review-and-delivery.md](review-and-delivery.md)）。

## 5. Remotion 四道确定性质量门禁

由 `helpers/_internal/remotion_gates.py` 与 `helpers/deliver.py` 串联执行的四道门禁（`review.py` 前置运行前两道，`deliver.py --render` 串联完整门禁）：

| 门禁 | 检查内容 | 触发时机 | 失败处理 |
|---|---|---|---|
| **1. 静态 TypeScript 编译（`typecheck`）** | 借外部运行壳 `tsc --noEmit` 零容差检查 `remotion/src/**` | `review.py`、`deliver.py --render` | 立刻阻断并输出具体 TS 文件与行号 |
| **2. 分镜帧数与切点硬对账（`sync`）** | 核对 `storyboard.json` 总时长、总帧数、fps 与各分段起止切点完全对齐 `Root.tsx` 合成元数据 | `review.py`、`deliver.py --render` | 差 1 帧即拦截，消除音画漂移 |
| **3. 每镜中段静帧抽取与非黑核验（`stills`）** | 按 `storyboard.json` 每个动效分段自动在分段中点抽取 PNG 静帧汇总至工程检查区，检验非全黑并供目视排查裁切/文字碰撞 | `deliver.py --render`（编全片前）及按需自检 | 全黑或抽帧失败即拦截；人工目视确认后再出全片 |
| **4. 交付成片严格核验** | 按段分流拼合 + `verify_delivery.py` 检查流对齐、响度规范、声景双轨合法性、全黑帧与字幕安全区空带，并固化 `state_fingerprint.py` | `deliver.py` 交付收尾 | 任一红项退出非 0，拒绝写入合格交付结论 |
