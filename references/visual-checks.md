# 画面体检、活舞台契约与渲染规范（`visual-checks.md`）

> 什么时候读：构建工程态审阅前（活舞台自检）、运行 `helpers/check_visual.py`、或进入 HyperFrames 交付渲染/透明叠加层编码时读本页。命令列表见 [tools.md](tools.md)。

## 1. 统一画面体检入口：`helpers/check_visual.py`

> `check_visual.py` 收拢画面层的环境、静态结构、运动变化与画面内容检查；逐项子命令帮助见 `python3 helpers/check_visual.py --help`。

日常自检与问题定位遵循「环境与静态先过，运行态与画面像素随后，局部失败修对应 owner，禁止拿一次静态绿灯代替全部核验」。具体分工：
- **静态活舞台检查**（`helpers/_internal/check_live_stage.py`）：`build_review.py` 前必跑，防 srcdoc 0 秒黑屏。
- **构建期画质与按档门禁**（`helpers/check_visual.py --only quality` / `_internal/check_visual_quality.py`）：预览与渲染前统一按 `visual-plan.json` 档位分流核查：
  - `logic-diagram` / `theory-board`：拦 1080p 下 `<32px` 字号、连续静止 `>6–8s`、侵入人物位或字幕安全区、无 `filterUnits="userSpaceOnUse"` 的横竖矢量滤镜线、未注册外部字体与跨章残留元素；
  - `talk-only`：豁免字号与静止检查；
  - `demo-footage`：豁免 `<32px` 界面小字与静止时长告警，改为强查原录屏在 `composition/assets/` 外存在、入出点未越界、无全黑帧且显示区不侵入人物位与字幕区。
- **GSAP 锚点与静态 transform 冲突**（`helpers/_internal/check_motion_targets.py`）：手写时间轴交付前必跑。
- **环境与并发预算**（`helpers/_internal/probe_env.py` + `helpers/_internal/check_render_env.py`）：任何 `hyperframes render` 前必跑。
- **渲染后一致性/静止/屏幕文字/透明通道**：`helpers/_internal/check_render_fidelity.py`（快速转场窗内自动向前后各扩展 1 帧并以全分辨率亮像素核验，消减滑入转场误报）、`check_motion.py`、`check_screen_text.py`、`check_alpha.py`、`check_overlay.py`（蒙太奇路线用 `helpers/_internal/check_montage.py`）。

## 2. 活舞台五条硬契约（工程审阅能播的前提）

`hyperframes check` 退 0 **不证明**审阅页能播：审阅页通过 `live_preview.py` 把编译结果装进官方 player 的 `srcdoc`；官方编译器会把 `index.html` 的内联 `<script>` 改写成 `type="text/hf-after-fonts"` 延迟块，在 `srcdoc` 中永远不执行，导致玩家拿到 0 秒、舞台全黑而人物正常（[GOTCHAS.md](../GOTCHAS.md) #74）。

**五条硬契约（`check_live_stage.py` 检查，退出码 0 过 / 1 error / 2 缺 composition）**：
1. **根元素**：`<div id="root" data-composition-id="main" data-start="0" data-width="1920" data-height="1080" data-duration="..." data-fps="30">`（id 唯一、像素宽高与时长齐备）。
2. **时间轴注册名全等**：唯一暂停的 `HF.tl` 挂在 `window.__timelines[<id>]`，名字全等 `data-composition-id`。
3. **执行逻辑全在外部 `src/*.js`**：`__CFG__`、`HF.build()`、`window.__timelines[...] = HF.tl` 与启动代码全部移出到 `<script src="src/...js">`；为满足 `hyperframes check` 的 `missing_timeline_registry`，`index.html` 末尾只留一行**纯容器初始化**：`<script>window.__timelines = window.__timelines || {};</script>`（右侧只能是 `{}` / `null` / 自引用兜底）。
4. **兼容嵌入桥文件在场**：源工程保留 `assets/composition-embed-bridge.js` 满足静态兼容检查（`live_preview` 传输时自动过滤，播放器时钟仍完全归 HyperFrames 官方 player）。若使用 `--composition composition-v2`，项目里仍须有带 `index.html` 的 `composition/` 目录。
5. **媒体资产预算**：`build_review.py` 自动将 `liveStage.composition.assets` 里超过 **`LIVE_STAGE_ASSET_MB = 4.0` MB** 的资产（合计上限 `12.0` MB）转为 `review/proxies/` 代理（保持时长，先降码率、再按 `0.75 / 0.5 / 0.35` 降分辨并记入 `mediaNotes`），同时对 `<video muted>` / `data-has-audio="false"` 去除重复音轨。人物母版走 `review/media.json`，不进 `composition/assets/`。

### 运行时播放判据：`check_review_playable.py`

`review.py` 在构建后自动拉起宿主并调用 Playwright 实测四件事（退 1 则阻塞交付给作者）：
1. 页面挂上播放通道（活舞台 / 合成成片 / 人物轨）并报通道；
2. 进入 iframe 实测 **`window.__timelines[<id>].duration()` > 0** 与已渲染元素数（不轻信 `data-duration`）；
3. 能 seek 到 beat 起点拿到画面（已渲染元素 / 解码像素）；
4. 两路核查有声且未静音（页面通道或 iframe 内 `<audio data-start>`/`<video data-start>`）。

## 3. 合成事实契约（兼容历史 `page` 与上游 `design_direction`）

当老项目或上游 `planners-ppt-hell` 随包写入 `design_direction.md` JSON 块 / `grouping.json` 单屏覆盖时，跨 Skill 共用三个字段名（优先级：`单屏 grouping.json > 整片 design_direction.md > 默认`）：

| 键 | 取值 | 默认 | 含义与落点 |
|---|---|---|---|
| `composite` | `"replace"` / `"over-person"` | `"replace"` | `replace` 走满屏不透明（`opaque`）；`over-person` 走透明叠加（`alpha`） |
| `personWindow` | `{"x":int,"y":int,"w":int,"h":int}` | 无 | 页面坐标下的人物避让矩形 |
| `captionSafe` | `{"x":int,"y":int,"w":int,"h":int}` | 无 | 页面坐标下的字幕安全区 |

## 4. 交付态渲染规范（HyperFrames）

只有在**作者明确出片 + 过 `render_gate.py`** 后才执行交付编码：
- **先测环境、严禁 `--workers auto`**：跑 `helpers/_internal/probe_env.py`（汇报能力、字体缓存、残留 `stray` 预览进程）与 `helpers/_internal/check_render_env.py <composition> --json`，取推荐 `workers`（画面层交付一律建议 **`--workers 1`**，防多 worker 截图通道后半段静默丢帧；停掉 `hyperframes preview` 再渲）。
- **冷启动 `compile` 预热**：首次冷缓存 `compile` 可能耗约 25 分钟（暖缓存 `0.1s`），渲染整片前先渲 3–5s 短片段热缓存；沙盒下设 `HYPERFRAMES_FONT_CACHE_DIR="$PWD/.hf-fontcache"`；输出路径必须**不含空格**（先落 `/tmp` 再移入目标目录，防云同步盘故障与路径压缩丢件，[GOTCHAS.md](../GOTCHAS.md) #52 / #70）。
- **禁用 `snapshot` 批抽帧**：`snapshot` 约 85 秒/帧，只用于少量关键帧核对；批量抽帧走 `render --format png-sequence`。
- **音频与根目录相对路径**：旁白放入 `composition/assets/audio.m4a`，HTML 写 `assets/audio.m4a`（禁 `../` 否则 `hyperframes check` 报错），进 composition 前预先用 `audio_mix.py` / `audio_fix.py` 归一（HyperFrames 不会自动做响度）。
- **交付后必跑 `check_render_fidelity.py`**：按抽样时间点对比成片帧与 `composition` 快照（结构相关 ≥0.93 且墨量不坍塌）。

### 透明叠加层载体选择（Alpha Overlays）

绝不用 H.264 `.mp4`（无 alpha），也不可轻信 `ffprobe pix_fmt`：

| 消费方 | 推荐封装 | 关键注意点 |
|---|---|---|
| 剪辑软件（FCP / PR / DaVinci / 剪映） | **ProRes 4444 `.mov`**（`encode_transparent.py --codec prores`） | 真保透明 |
| Apple 生态小体积 | **HEVC+alpha `.mov`**（`-c:v hevc_videotoolbox`） | `ffprobe` 误报 `yuv420p` 但实际保透明 |
| 网页/审阅页浏览器实时叠加 | **WebM VP9+alpha**（`preview_layers.py` / `libvpx-vp9`） | 本机普通编码或 Safari 可能丢透明；审阅可用、交付成片前须合成为不透明 |

- 渲染透明层 PNG 序列时**必须加 `--no-low-memory-mode`** 并传 `--workers` 低并发（先试 3–5s 切片）；交接前必跑 `helpers/_internal/check_alpha.py` 与 `check_overlay.py` 解出真 alpha 平面核查 span。

## 5. 自绘逐帧视觉腿规范（代码直出帧管线）

不走 HTML/HyperFrames、改用代码逐帧绘图输出独立无声视觉腿（多腿同步）时：
1. **帧数是硬合同**：每 `slot` 帧数 = `实测时长 × fps` 取整，求和精确等于参考腿总帧数；内容可改、帧数与槽内切点不可变。
2. **一致参数 + `-c copy`**：所有 slot 锁定完全一致的 codec / profile / 分辨率 / `pix_fmt` / `fps` / `time_base` / 无音轨 / `+faststart`，最后按 concat demuxer `-c copy` 合并。
3. **性能配方（百帧/秒级）**：低逻辑分辨率绘图 → 直接管道 `rawvideo rgb24` 喂给 ffmpeg `-vf scale=W:H:flags=neighbor`（禁写盘逐帧 PNG）；静态背景每镜缓存一次；每镜 ≤3–5 个活动元素；参数化复用角色/调色盘；重跑资产校对哈希。
4. **安全区与返修**：事先程序化扫描字幕带的有色相像素占比；按**时间重叠最多**（非 cue 起点）往每屏绑定字幕防 `0.03s` 舍入边界错位；支持 `--qc t1,t2` 抽帧验证；返修复用原 slot 子代理，最后人眼核查首中尾关键帧。
