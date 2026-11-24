# 工程审阅、收件返修与交付核验（`review-and-delivery.md`）

> 什么时候读：构建工程审阅页、挂载 DSH/本地宿主、处理提交与 `review_inbox.py` 收件、或作者明确指令出片执行 `deliver.py` 与多腿交付核验时读本页。

> **每轮默认终点**：侧边栏审阅页可播 + 本轮待办，**不是出成片**。`edit/_engineering/**` 是审阅素材；写 `成品/**` 必须同时满足「作者明确出片指令」+「人工提交覆盖当前快照（`render_gate.py` 放行）」。

## 1. 两种审阅面与构建模式

`video-craft` 保留两套独立审阅业务页面（共享 `planners-review-core` 的 `review-surface/2.0.0` 宿主协议，互不嵌套）：
1. **逐字剪辑面**（第 4 步）：`edl_preview_build.py <edit>` → `edl_review_surface.py <edit> [--surface-only]`。用于播放原片/选词/删词/调气口/改字，写 `edit/selections.json`，再由 `apply_selection.py` 修改 EDL 并重建预览/字幕/时间轴。若源媒体 >200MB 或可用内存 <8GB，直接走本地宿主（不加 `--surface-only`，按 Range 供片避免侧栏传全字节爆内存）。
2. **动效 / 成片 / 密度审阅面**（第 8 步）：唯一构建入口 **`helpers/review.py <project>`**（自动串联活舞台检查、`live_stage.py`、`build_review.py`、`review_surface.py`、Playwright `check_review_playable.py`），官方 HyperFrames player 驱动播放、定位与倍速，**不复制第二个播放时钟**。

`build_review.py::resolve_build_mode()` 的三种合法模式：
- `recompose`（工程态默认，存在 `recompose.json`）：左大预览 + 横向 `B01–Bxx` Beat 切换 + 整 beat 反馈；右栏为「逐句调整」（按行设 `auto/off/still/light/full`、`0/1/2/3/a` 快捷键、拖拽/Shift/Cmd 多选、批量应用、撤销）与「历史反馈」tab，中间分隔可拖拽。
- `final-cut`（成片态，存在 `edit/montage-plan.json` 或显式 `--final-cut`）：标「成片态·无工程态」，`media.layersBaked: true`，播放合成成片、按 EDL 段跳转与提交反馈；改源须重渲后重建审阅。
- 已退休 `page` 模式默认退 2（仅测试或复活老工程时 `--allow-page`）。无活舞台却有 `composition/index.html` 时同样拒绝（`--allow-static` 仅显式降级）。

### 可选实时参数适配器（HyperFrames 兼容边界）

若需实时预览参数微调，composition 可选暴露 `window.VideoCraftReviewAdapter`（`getModel / applyOverride / serializeOverrides / resetOverrides`），**只改声明参数、不建立第二播放头**；否则一律走默认「反馈 → 改 composition 源 → `review.py` 重建」路径。静态页兼容时保留的 `visual/assets/svg-anim-engine.js` 不可写入新 composition 主时钟。

### 媒体解析与公共宿主接口

- `review/media.json` 显式声明 `speakerVideo`、`previewVideo`、`compositeVideo`、`guideAudio`、`baseVideo`（未烘焙层底片 → `layersBaked=false`，页面用 WebM VP9+alpha `layers` 实时合成）、`slices`（按关键帧切割，`manifest` 记真实起点防批注偏移）。无文件回退按名猜测时会显式提示。
- **插件内宿主 vs 本地宿主**：有 DSH `review_open` 时传返回的 `review-surface.json` 绝对路径；无插件时走 `helpers/_internal/review_surface.py <project>` 由 `planners-review-core` 启动本地 HTTP 宿主（严禁 `file://` 打开）。模板强制唯一裸行 `{{REVIEW_BRIDGE}}`（[GOTCHAS.md](../GOTCHAS.md) #32）与 Core 内联 `dsh-tokens.css`（#53）。
- 草稿 `review.draft()` 落 `review/review-draft.json`；正式提交 `review.write()` 落 `review/review-submissions.json` 并附带 `sourceManifest`（含正文、SVG 与媒体 sha256）与 `snapshot`，再用 `review.wake()` 通知 Agent（保存成功与唤醒结果独立展示）。

## 2. 收件与返修闭环（`review_inbox.py`）

`review.py` 与 `review_inbox.py` 职责独立：人提交后，先收件、核查回执再改源：

```bash
python3 "<craft>/helpers/review_inbox.py" "<project>"
```

检查 `imported`、`skipped`、`rejected` 与 `legacy_adjustments`（有 `rejected` 须修复绑定或重建审阅后重收）。
1. 按时间读取 `feedback/*.jsonl`（整片意见在 `overall.jsonl`），对比当前 `timeline` 与 `snapshot`，旧版意见先重定位再改源；
2. `phase: "density"` 提交自动校验写入 `feedback/density.jsonl` 并由 `recompose_plan.apply_record` 更新 `recompose/lines.json`，模型只修改受影响的 `src/scenes/*.js`（从高到低收束）；
3. 文本改动回 Idea、静态构图改动回 PPT Hell、局部动效/同步在 Craft 修复；
4. 每轮返修必重新跑 `review.py` 让旧 `snapshot` 失效并交回最新工程审阅；**切忌未重建直接提交或假装热更新**。

## 3. 交付顺序、`deliver.py` 与多腿核验

只有**作者明确要求出片**且**审阅页有覆盖当前快照的提交**（口头批准须先请作者在审阅页提交一次）才进交付流程：

### Step 0–4 严格执行顺序

0. 停掉预览服务（`pkill -f "hyperframes preview"` 释放 GPU），单并发 `--workers 1` 渲画面层（如分开导出需脱去音轨），写 `/tmp` 再移目标位置，立刻跑 `check_render_fidelity.py <project> --video <画面文件>` 验逐帧相关与墨量；
1. **`helpers/deliver.py <project> --render`**（或 `--visuals <已有画面>` 加来源证据/`--visuals-confirm-current`）：内部先过 `render_gate.py`、环境探测、适用 `film verify`、`hyperframes check`、`check_motion_targets.py`，按 `recompose.json` 的 `personSlot`（等比 cover 居中裁切，无人物加 `--no-person`）与音频（`-14 LUFS / -1.5 dBTP`）合成，`--burn-subtitles` 在编码前强制查 `libass`；
2. `verify_delivery.py` 输出严格判据与 `<成品>/<片名>_核验报告.json`（核分辨率/帧率/时长 ±0.5s/音轨/首中尾帧/字幕安全区/画面一致性/严格 `delivery_verdict`；严禁顶层退出码 0 而 `delivery_verdict.ok=false`）；
3. 若需包装发布目录，跑 `export_deliverables.py`（自动按交付空隙规整副本 SRT），并复查真实副本；
4. **`state_fingerprint.py capture <project>`** 写 v3 来源指纹；发送前再跑 `verify` 确认不过期。

### 两种多腿命名与核验区分（切勿混淆）

- **Recompose 两腿**（`deliver.py` / 分轨交付）：`成片`（全合）· `人物成片`（口播人物轨含声）· `画面成片`（**纯画面无声轨**，核 fidelity + 无音轨）。
- **Montage 三件套**（`montage.py`，[montage-route.md](montage-route.md)）：`成品/<片名>_画面成片.mp4`（**带口播音轨**，无字幕，标明是否含档案角标）· `成品/<片名>_口播成片.mp4`（`montage.py voice-cut --master <母版> --audio <口播音>`，核时长与音轨）· `成品/<片名>_字幕.srt`（外挂）。`montage` 不跑 `deliver.py` 与 `check_render_fidelity.py`（无 composition），由 `check_montage.py --video` 把关；若额外把画面成片与人物合成一条全片，仍须走 `deliver.py` 严格核验。

### 成片二次剪：`edit/cut-map.json`（例外路径）

默认不建议渲染后二次剪成片；若确需从成片剪停顿（静音窗复用 `_silence.py` 判据），必须声明 `edit/cut-map.json`（`version`、`masterDuration`、`cuts`、`srt`），由 `helpers/_internal/_cutmap.py::remap_cue()` 按单调分段函数 `t' = t - 已剪时长(t)` 整体重算（严禁边遍历边修改导致 3.2s 累加偏移，#78）；`verify_delivery.py` 会按 ±20ms 逐条对齐核验，缺声明而时长短 >0.5s 直接拒收。
