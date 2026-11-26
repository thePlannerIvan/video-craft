# 画面体检、活舞台契约与渲染规范（`visual-checks.md`）

> 什么时候读：构建工程态审阅前（活舞台自检）、运行 `helpers/check_visual.py`、执行 Remotion 四道门禁，或兼容处理历史 HyperFrames 工程与透明叠加层编码时读本页。Remotion 详情见 [remotion-engine.md](remotion-engine.md)，命令列表见 [tools.md](tools.md)。

## 1. 统一画面体检与 Remotion 四道门禁

> 日常自检与问题定位遵循「环境与静态先过，运行态与静帧随后，局部失败修对应 owner，禁止拿一次静态绿灯代替全部核验」。画框与人物/字幕安全区几何统一由 `helpers/frame.py resolve` 解析。

### Remotion 4 默认引擎门禁（`helpers/_internal/remotion_gates.py` + `helpers/check_visual.py`）

1. **外部运行壳与结构检查**（`helpers/remotion_runtime.py doctor` & `helpers/_internal/check_live_stage.py`）：校验 Node 22+、`ffmpeg`、外部运行壳依赖、无头浏览器及 `remotion/src/Root.tsx` / `index.ts` 就绪，同时阻断在项目内生成 `node_modules`。
2. **静态 TypeScript 编译（`typecheck`）**：通过外部运行壳 `tsc --noEmit` 零容差拦拼写与属性类型误差（`review.py` 与 `deliver.py --render` 自动前置运行）。
3. **分镜帧数与切点硬对账（`sync`）**：校验 `storyboard.json` 总帧数、总时长、fps 与各分段起始切点精确匹配 `Root.tsx` 合成定义。
4. **每镜中段静帧抽取与非黑校验（`stills`）**：交付编码前按 `storyboard.json` 每个动效分段在中点自动抽帧至工程检查区并验非全黑，供人工逐镜目视排查裁切、文字碰撞与层次遮挡。

### 通用画质、安全区与历史兼容检查（`helpers/check_visual.py`）

- **构建期画质与按档门禁**（`helpers/check_visual.py --only quality` / `_internal/check_visual_quality.py`）：按 `storyboard.json`（兼容旧 `visual-plan.json`）分段类型与 `frame.py` 几何真源核查：
  - `logic-diagram` / `theory-board` / `model`：拦短边 1080 基准下 `<32px` 字号、连续静止 `>6–8s`、侵入人物位或字幕安全区（已正确累加祖先容器定位偏移，消除圆形及局部装饰图元安全区误报）、Canvas/SVG 标签越界裁切（标 `data-role="background"` 的装饰层除外）、无 `filterUnits="userSpaceOnUse"` 的横竖矢量滤镜线、未注册外部字体与跨章残留元素；
  - `talk-only`：豁免字号与静止检查；
  - `demo-footage` / `screen-demo`：豁免 `<32px` 界面小字与静止时长告警，改为强查原录屏在资源资产目录外存在、入出点未越界、无全黑帧且显示区不侵入人物位与字幕区。
- **历史兼容检查**：针对仅含 `composition/index.html` 的冻结老工程，继续运行 `check_live_stage.py`（含 `<video>` `visibility: hidden` + `autoAlpha` 黑屏防坑）、`helpers/_internal/check_motion_targets.py`、`probe_env.py` + `check_render_env.py`。
- **渲染后一致性/静止/屏幕文字/透明通道**：`helpers/_internal/check_render_fidelity.py`、`check_motion.py`、`check_screen_text.py`、`check_alpha.py`、`check_overlay.py`（纯混剪路线用 `helpers/_internal/check_montage.py`）。

## 2. 活舞台契约（工程审阅能播的前提）

- **Remotion 4 `{kw: 1}` 活舞台桥（默认）**：`helpers/_internal/remotion_stage.py` 用外部运行壳 `esbuild` 增量打包 `remotion/src/Root.tsx`，通过独立回环端口挂载 `@remotion/player` 并对等响应 `hello/ready`、`seek`、`play`、`pause`（`200ms` 节拍回传进度），全程零渲染；`check_live_stage.py` 自动校验 `Root.tsx`、`index.ts`、项目内无 `node_modules` 与外部运行壳就绪度。
- **历史 HyperFrames 活舞台五条硬契约（仅冻结兼容老工程）**：
  1. **根元素**：`<div id="root" data-composition-id="main" data-start="0" data-width="<画框宽>" data-height="<画框高>" data-duration="..." data-fps="30">`（宽高取自 `helpers/frame.py resolve`）。
  2. **时间轴注册名全等**：唯一暂停的 `HF.tl` 挂在 `window.__timelines[<id>]`，名字全等 `data-composition-id`。
  3. **执行逻辑全在外部 `src/*.js`**：逻辑全部外移，`index.html` 末尾只留 `<script>window.__timelines = window.__timelines || {};</script>`（防 `srcdoc` 延迟块 0 秒黑屏，[GOTCHAS.md](../GOTCHAS.md) #74）。
  4. **兼容嵌入桥文件在场**：保留 `composition/assets/composition-embed-bridge.js`。
  5. **媒体资产预算**：`build_review.py` 自动将超 `4.0 MB` 资产（合计上限 `12.0 MB`）转至 `review/proxies/` 代理。

### 运行时播放判据：`check_review_playable.py`

`review.py` 在构建后自动拉起宿主并调用 Playwright 实测四件事（退 1 则阻塞交付给作者）：
1. 页面挂上播放通道（Remotion 活舞台 / 历史活舞台 / 合成成片 / 人物轨）并报通道；
2. 实测时间轴真实时长 `> 0` 与已渲染元素（不轻信静态声明）；
3. 能 seek 到 beat 起点拿到非空渲染画面；
4. 两路核查有声且未静音（页面通道或舞台内音轨）。

## 3. 合成事实契约（兼容历史与上游 `design_direction`）

当老项目或上游 `planners-ppt-hell` 随包写入 `design_direction.md` JSON 块 / `grouping.json` 单屏覆盖时，跨 Skill 共用三个字段名（优先级：`单屏 grouping.json > 整片 design_direction.md > 默认`）：

| 键 | 取值 | 默认 | 含义与落点 |
|---|---|---|---|
| `composite` | `"replace"` / `"over-person"` | `"replace"` | `replace` 走满屏不透明（`opaque`）；`over-person` 走透明叠加（`alpha`） |
| `personWindow` | `{"x":int,"y":int,"w":int,"h":int}` | 无 | 页面坐标下的人物避让矩形 |
| `captionSafe` | `{"x":int,"y":int,"w":int,"h":int}` | 无 | 页面坐标下的字幕安全区 |

## 4. 交付态渲染规范与透明叠加层

只有在**作者明确出片 + 过 `render_gate.py`** 后才执行交付编码：
- **Remotion 4 默认渲染**：由 `deliver.py --render` 调用外部运行壳与 `remotion_gates.py` 串联校验并输出高码率分段视频（先写本地 `/tmp` 再移入目标目录，规避云盘同步盘故障与路径空格坑，[GOTCHAS.md](../GOTCHAS.md) #52 / #70）。
- **历史 HyperFrames 兼容渲染**（仅存量老工程）：停掉 `hyperframes preview`、设 `HYPERFRAMES_FONT_CACHE_DIR="$PWD/.hf-fontcache"`、取 `check_render_env.py` 推荐低并发 `--workers 1`，交付后必跑 `check_render_fidelity.py`（结构相关 ≥0.93 且墨量不坍塌）；禁用 `snapshot` 批抽帧。

### 透明叠加层载体选择（Alpha Overlays）

绝不用 H.264 `.mp4`（无 alpha），也不可轻信 `ffprobe pix_fmt`：

| 消费方 | 推荐封装 | 关键注意点 |
|---|---|---|
| 剪辑软件（FCP / PR / DaVinci / 剪映） | **ProRes 4444 `.mov`**（`encode_transparent.py --codec prores`） | 真保透明 |
| Apple 生态小体积 | **HEVC+alpha `.mov`**（`-c:v hevc_videotoolbox`） | `ffprobe` 误报 `yuv420p` 但实际保透明 |
| 网页/审阅页浏览器实时叠加 | **WebM VP9+alpha**（`preview_layers.py` / `libvpx-vp9`） | 本机普通编码或 Safari 可能丢透明；审阅可用、交付成片前须合成为不透明 |

- 渲染透明层 PNG 序列时交接前必跑 `helpers/_internal/check_alpha.py` 与 `check_overlay.py` 解出真 alpha 平面核查 span。

## 5. 自绘逐帧视觉腿规范（代码直出帧管线）

不走 Remotion / 网页渲染、改用代码逐帧绘图输出独立无声视觉腿（多腿同步）时：
1. **帧数是硬合同**：每 `slot` 帧数 = `实测时长 × fps` 取整，求和精确等于参考腿总帧数；内容可改、帧数与槽内切点不可变。
2. **一致参数 + `-c copy`**：所有 slot 锁定完全一致的 codec / profile / 分辨率 / `pix_fmt` / `fps` / `time_base` / 无音轨 / `+faststart`，最后按 concat demuxer `-c copy` 合并。
3. **性能配方（百帧/秒级）**：低逻辑分辨率绘图 → 直接管道 `rawvideo rgb24` 喂给 ffmpeg `-vf scale=W:H:flags=neighbor`（禁写盘逐帧 PNG）；静态背景每镜缓存一次；每镜 ≤3–5 个活动元素；参数化复用角色/调色盘；重跑资产校对哈希。
4. **安全区与返修**：事先程序化扫描字幕带的有色相像素占比；按**时间重叠最多**（非 cue 起点）往每屏绑定字幕防 `0.03s` 舍入边界错位；支持 `--qc t1,t2` 抽帧验证；返修复用原 slot 子代理，最后人眼核查首中尾关键帧。
