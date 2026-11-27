# 工程审阅、收件返修与交付核验（`review-and-delivery.md`）

> 什么时候读：构建工程审阅页、挂载 DSH/本地宿主、处理提交与 `review_inbox.py` 收件、或作者明确指令出片执行 `deliver.py` 与双轨交付核验时读本页。

> **每轮默认终点**：审阅页可播 + 本轮待办，**不是出成片**。`edit/_engineering/**` 是审阅素材；写 `成品/**` 必须同时满足「作者明确出片指令」+「当前已建审阅快照且已有网页提交，或当轮对话明确授权 `--approve-in-chat --approval-note "<作者原话>"`（`render_gate.py` 写入实时源码指纹审计记录放行）」。

## 1. 两种审阅面与横竖屏自适应构建模式

`video-craft` 保留两套独立审阅业务页面（共享 `planners-review-core` 的 `review-surface/2.0.0` 宿主协议，互不嵌套）：
1. **逐字剪辑面**（第 4 步）：`stage_cut.py review --project "<project>"`（内部调用 `edl_preview_build.py` 与 `edl_review_surface.py`，加 `--surface-only` 仅出契约供 DSH 侧栏，不加则自动拉起本地浏览器宿主；独立浏览器保存后给出清晰闭环提示）。用于播放原片/选词/删词/调气口/改字，写 `edit/selections.json`，再由 `stage_cut.py apply` 修改 EDL 并重建预览/字幕/时间轴。若源媒体 >200MB 或可用内存 <8GB，直接走本地宿主（按 Range 供片避免侧栏传全字节爆内存）。
2. **横竖屏自适应画面与双轨声景审阅面**（第 8 步）：唯一构建入口 **`helpers/review.py <project>`**（Remotion 工程前置过 [remotion-engine.md](remotion-engine.md)「5. Remotion 四道确定性质量门禁」的前两道及 `{kw: 1}` 零渲染活舞台桥，再串联 `build_review`、`review_surface` 与 Playwright `check_review_playable`）。页面通过单一全局播放头同步驱动舞台控制与倍速，并提供分章/分镜导航、字幕/倍速控制、`播客音色 vs 纯干声`（Voice Polish）A/B 切换与 `画面底噪:开/关`（Visual Soundscape）实时试听开关。

### 单模板横竖屏自适应与反馈布局

`build_review.py` 从 `helpers/frame.py resolve` 读取画框真实宽高与朝向自动注入审阅数据，同一模板按 `data-orientation` 自动布局并在顶栏提供手动切换按钮（`#btn-orientation-toggle`）：
- **横屏模式（`landscape`）**：中央主舞台自上而下排布宽屏画布、全局播放控制条与**紧贴视频下方的紧凑意见提交区**（`#center-feedback-slot`），消除视频下方留白；右侧边栏专注承载历史反馈，**当历史反馈为零条时默认折叠收起**（顶栏展示带计数徽章的展开按钮 `#btn-toggle-history`，收到记录后自动展开）。
- **竖屏模式（`portrait`）**：释放中央舞台高度限制，让 9:16 竖屏画布撑满可用视口高度；意见表单与历史反馈记录收拢在右侧操作栏（`#right-feedback-slot`），看清每一行字阶与安全边。

`build_review.py::resolve_build_mode()` 的构建模式：
- `recompose`（活舞台工程态默认，存在 `remotion/src/Root.*`、历史 `composition/` 或分镜）：自适应舞台 + 分屏导航 + Voice Polish 与 Visual Soundscape 试听切换 + 意见与历史栏；
- `final-cut`（成片态，存在独立 `edit/montage-plan.json` 或显式 `--final-cut`）：标「成片态·无工程态」，`media.layersBaked: true`，播放合成成片、按 EDL 段跳转与提交反馈；改源须重渲后重建审阅。

### 媒体解析与公共宿主接口

- `review/media.json` 显式声明 `speakerVideo`、`previewVideo`、`compositeVideo`、`guideAudio`、`soundscape`（`bedOn`）/ `soundscapeSfxOnly`（`bedOff`）、`baseVideo`（未烘焙层底片 → `layersBaked=false`，页面用 WebM VP9+alpha `layers` 实时合成）、`slices`（按关键帧切割，`manifest` 记真实起点防批注偏移）。无文件回退按名猜测时会显式提示。
- **插件内宿主 vs 本地宿主**：有 DSH `review_open` 时传返回的 `review-surface.json` 绝对路径；无插件时走 `helpers/_internal/review_surface.py <project>` 由 `planners-review-core` 启动本地 HTTP 宿主（严禁 `file://` 打开）。模板强制唯一裸行 `{{REVIEW_BRIDGE}}`（[GOTCHAS.md](../GOTCHAS.md) #32）与 Core 内联 `dsh-tokens.css`（#53）。
- 草稿 `review.draft()` 落 `review/review-draft.json`；正式提交 `review.write()` 落 `review/review-submissions.json` 并附带 `sourceManifest`（含源码、正文、资产与媒体 sha256；`lookdev-manifest.json` 不纳入漂移误报）与 `snapshot`，再用 `review.wake()` 通知 Agent（保存成功与唤醒结果独立展示）。

## 2. 收件与返修闭环（`review_inbox.py`）

`review.py` 与 `review_inbox.py` 职责独立：人提交后，先收件、核查回执再改源：

```bash
python3 "<craft>/helpers/review_inbox.py" "<project>"
```

检查 `imported`、`skipped`、`rejected` 与 `legacy_adjustments`（有 `rejected` 须修复绑定或重建审阅后重收）。
1. 按时间读取 `feedback/*.jsonl`（整片意见在 `overall.jsonl`），对比当前 `timeline` 与 `snapshot`，旧版意见先重定位再改源；
2. 文本/口播定稿改动回 `video-manager`、按需静态构图改动回 `planners-ppt-hell`、局部动效/镜头/声景在 `video-craft` 修复源（`storyboard.json`、`remotion/src/**` 或 `sound_design.py` 参数）；
3. 若返修后继续走浏览器审阅，重跑 **`review.py`** 重建快照交给人看；若作者在对话中明确指示「修改某处细节后直接导出」，改完源后可按第 3 节以 `--approve-in-chat` 直接进入交付。

## 3. 按段分流交付顺序、`deliver.py` 与务实会话出片授权

只有**作者明确要求出片**且**满足 `render_gate.py` 双轨授权之一**时才进交付流程（未建审阅页 `review/review_data.json` 一律严防死守）：
- **浏览器审阅提交**：要求存在覆盖当前 `snapshot` 的提交记录且 `sourceManifest` 零漂移；
- **务实会话出片授权（`--approve-in-chat`）**：仅当作者在当前对话中明确指令导出（如「把某句动画调快然后直接导出」）时允许传入，且**必须配 `--approval-note "<作者明确导出原话>"`**（具体校验规则由 `helpers/_internal/render_gate.py --help` 强制执行）。`render_gate.py` 核验审阅快照存在且原话凭证合法后，写入含实时源码指纹（`liveSourceHash`）、`driftedFromReview` 标记、授权原话与时间戳的 `chat-approval` 审计条目并直接放行；仅提出返修意见或未获明确导出指示时，保持停留在重建后的审阅态。

### Step 0–3 严格执行顺序

0. 若存在旧预览服务先停止释放资源；Remotion 工程按 [remotion-engine.md](remotion-engine.md)「5. Remotion 四道确定性质量门禁」先过前置门禁并写入 `/tmp` 临时成片后再原子移入目标位置；
1. **`helpers/deliver.py <project> --render [--visual-audio <soundscape.wav>] [--approve-in-chat --approval-note "<原话>"]`**（或 `--visuals <已有画面>` 加来源证据/`--visuals-confirm-current`）：
   - 先过 `render_gate.py`、`film.py verify`（含 `lookdev --verify`；空占位 `pages/` 目录自动跳过）；Remotion 工程经外部运行壳渲染动效段并过四道门禁，历史旧工程走只读兼容；
   - 由 `helpers/frame.py resolve` 读取权威画框尺寸与人物孔位，按 `storyboard.json` 分流拼接：纯 `footage` 与 `screen-demo` 由 FFmpeg 直接从高清母版裁切（`screen-demo` 保留清晰文字保护），与动效渲染段毫秒级拼合；
   - 有真人口播与画面层时默认 **`--mode split` 分轨交付**（声音双轨归属与响度标准见 [captions-and-audio.md](captions-and-audio.md)）：
     1. `<片名>_人物成片.mp4`：优先无损流式复用高码率 `edit/cut.mp4` + **Voice Polish** 纯净人声；
     2. `<片名>_画面成片.mp4`：存在 **Visual Soundscape**（`edit/_engineering/soundscape.wav` 或 `--visual-audio`）时通过 `-c:v copy` 无损封装进成片并同目录输出独立无损 `<片名>_画面音效轨.wav`；无声景需求时合法保持 0 音轨；
     3. `<片名>_字幕.srt`：自动调用 `export_deliverables.fix_srt_gaps` 修正导入空隙 `≥30ms`；
   - 需要单视频合流预览时加 **`--composite`**（按 `frame.py resolve` 的 `personSlot` 等比 cover 居中裁切合成）；纯画面 + 旁白加 `--no-person`；仅底座剪口播按单轨人物成片 + 字幕交付；`--burn-subtitles` 在编码前强制查 `libass`；
2. `verify_delivery.py`（按路径无关的规范 EDL 指纹匹配 `segment_durations.json`，向后兼容旧字节哈希）输出严格判据与 `<成品>/<片名>_核验报告.json`（含 `delivery_mode` 与 `deliverables` 分轨清单；严禁顶层退出码 0 而 `delivery_verdict.ok=false`）；
3. **`state_fingerprint.py capture <project>`** 在交付档案固化本轮实际使用的最新源码指纹；发送前再跑 `verify` 确认不过期。

### 两种分轨命名与核验区分（切勿混淆）

- **`deliver.py` 分轨交付**（默认 `--mode split`）：`<片名>_人物成片.mp4`（仅 Voice Polish 人声）· `<片名>_画面成片.mp4`（存在声景时含无损封装声景并同出 `<片名>_画面音效轨.wav`，无声景需求时 0 音轨）· `<片名>_字幕.srt`（导入空隙已修正）；显式加 `--composite` 才出单轨 `<片名>_成片.mp4`。
- **纯混剪三件套**（仅走 `montage.py` 且无 `storyboard.json` 分段拼合时，[montage-route.md](montage-route.md)）：`成品/<片名>_画面成片.mp4`（带口播音轨，无字幕，标明是否含档案角标）· `成品/<片名>_口播成片.mp4`（`montage.py voice-cut --master <母版> --audio <口播音>`，核时长与音轨）· `成品/<片名>_字幕.srt`（外挂）。`montage` 独立路线由 `check_montage.py --video` 把关；若额外把画面成片与人物合成一条全片，仍须走 `deliver.py` 严格核验。

### 成片二次剪：`edit/cut-map.json`（例外路径）

默认不建议渲染后二次剪成片；若确需从成片剪停顿（静音窗复用 `_silence.py` 判据），必须声明 `edit/cut-map.json`（`version`、`masterDuration`、`cuts`、`srt`），由 `helpers/_internal/_cutmap.py::remap_cue()` 按单调分段函数 `t' = t - 已剪时长(t)` 整体重算（严禁边遍历边修改导致 3.2s 累加偏移，#78）；`verify_delivery.py` 会按 ±20ms 逐条对齐核验，缺声明而时长短 >0.5s 直接拒收。
