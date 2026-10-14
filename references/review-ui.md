# 审阅页：播放与反馈

## 工程预览是默认入口

`live_stage.py → build_review.py → review_surface.py`。`live_preview.py` 将 HyperFrames 编译后的 HTML、内联运行时和项目内素材清单交给审阅页。审阅页内联本机 CLI 对应版本的官方 player，素材经 review-core 取回，再交给 player 的 `srcdoc`。没有跨源 localhost iframe；也不共享父帧的 blob URL。播放、定位、倍速、clip 显隐和媒体同步都由官方 player 管。

这是可重复构建的工程快照，不是 MP4，也不是无需重建的热更新。每次改源重新 build；反馈携带 snapshot、稳定 unitId、playbackTimeMs 和 animationAnchor。sourceManifest 包含工程及素材，变更后提示旧版。播放器版本和哈希记在 media.liveStage.player。

## 界面与功能归属

DSH tokens 仍来自 review-core，生成时内联。导航显示分屏标题、时长与短口播，更多意图只在选中屏展开；舞台为主；播放速度与字幕开关集中在底部；高级调整默认折叠。右栏保留本批意见、历史及输入，窄栏重排，保存始终可达。

实时预览的控件直接调用 player：play / pause / seek / playbackRate。分屏切换和字幕读取同一时钟。输入意见、框选批注时暂停；回到预览不会同时启动旧视频或 SVG 定时器。点选文字/位置属于静态源稿的调整请求，提交后由 Agent 写回并重建，不能假装已经改动实时工程。

不得将“runtime 已握手”作为验收。至少验证不同分屏只显示目标 clip，声音与录屏 seek/倍速同步，字幕开关有效，提交实际写入并被 inbox 接收。锁屏、宿主不可达等导致的实测缺口必须明确记录。

## 兼容已有项目

以下已有媒体、叠层、提交和版本约束继续适用。它们不再是新 HyperFrames 工程预览的默认制作路径。

# 审阅接入与收件

Craft 有两个审阅面。视觉面审实际画面、声音与节奏；剪辑面选要删的词、停顿和错字。Idea 的念稿审阅、PPT Hell 的静态画面批准仍归上游，不由本面代替。

## 生成与打开

下面 `<craft>` 是 Skill 根，`<project>` 是项目绝对路径，`<core>` 是 `planners-review-core` 根。

```bash
python3 "<craft>/helpers/build_review.py" "<project>" --mode auto
python3 "<craft>/helpers/review_surface.py" "<project>" --surface-only
node "<core>/scripts/validate-surface.mjs" "<project>/review/review-surface.json" --text
```

构建器输出 `review/review_data.json`、`review/index.html` 和唯一适配器生成的 `review-surface.json`，并调用公共校验器。数据含实际 timeline 位置、媒体、SVG/图片映射与构建快照；新项目只用根 `timeline/`，旧项目显式引用已有位置，不复制出第二份时间轴。

**有 `review_open`**：参数 `surface` 填返回的 surface 绝对路径。插件挂入侧栏，不起本地服务。

**没有 `review_open`**：运行 `python3 "<craft>/helpers/review_surface.py" "<project>"`，由公共宿主开浏览器。`--no-open` 仅供测试；旧 `serve_review.py --open` 也是这个入口的薄包装，不再拥有另一套 HTTP 服务。

剪辑面默认按 EDL 直接播放源素材，即使目录里有旧 final.mp4 也不替换。明确要对照成片时才传 `edl_preview_build.py <edit_dir> --rendered-preview final.mp4`。

剪辑面独立打开：

```bash
python3 "<craft>/helpers/edl_preview_build.py" "<project>/edit"
python3 "<craft>/helpers/edl_review_surface.py" "<project>/edit" --surface-only
```

有插件时 `review_open` 接返回的 `edit/edl_review_surface.json`；没有插件去掉 `--surface-only`。视觉页的「逐字剪辑」只请求模型打开独立面，不嵌入另一份审阅桥。

## 媒体从哪来

审阅面不再按文件名猜媒体。显式声明优先：`<project>/review/media.json`

```json
{"speakerVideo": null, "previewVideo": null,
 "compositeVideo": "edit/final.mp4", "guideAudio": null}
```

缺这份文件时仍会退回按文件名猜，但**会在构建输出里明说**——`anim_preview.mp4` 这种名字
曾让一份全长 720p 副本被当成「演示动画」轨。声明了却不存在的文件也会被报出来。

`media.json` 还可以声明 `baseVideo`：**未烘焙视觉层的底片**。声明后 `compositeVideo`
就是这份底片，并置 `layersBaked: false`，页面在它上面**实时合成层**——这才是「改一层不必
重渲整片」。不给 `baseVideo` 时默认 `layersBaked: true`（成片里已经烘焙了层），页面**不会**
再叠一遍（叠了就重影），并会明说原因。

`media` 里另有两项：

- `layers`：EDL 覆盖层，带稳定 `unitId`（`visual:<tag>`）、时间窗与 `previewFile`。
  页面据此在成片上**自己合成**这些层（`previewFile` 是 WebM VP9+alpha，浏览器唯一能合成的
  带 alpha 载体；没有它就只能看成片里的烘焙结果，页面会明说）。
- `slices`：按步切片，页面只加载当前窗口。切片用 `-c copy` 从关键帧切，manifest 记的是
  **真实起点**与关键帧提前量，不是步边界——写错会让页面上的每条批注平移。

`hostAdvice: "local"` 表示复合片大到侧栏不适合承载且没有切片，应改用本地宿主。

## 公共接口

surface 采用 `review-surface/2.0.0`。`project_root`、`dir`、`feedback`、`draft`、`watch` 相对 surface 文件；`entry` 相对 dir。页面中所有 read/asset 路径相对 dir。视觉面 dir 是项目根，提交和草稿分别在 `review/review-submissions.json`、`review/review-draft.json`。

入口只有一个裸行 `{{REVIEW_BRIDGE}}`；宿主注入桥，页面调用 `ReviewBridge.connect()`。媒体与 SVG 图片用 `await review.asset(rel)`，文本用 `review.readText(rel)`；插件的 opaque iframe 不直接加载项目相对 URL；官方 player 内联，工程和素材通过桥交付。

`review.write(payload)` 原样覆盖提交文件；`review.draft(payload)` 写独立草稿，不通知、不批准；`review.wake({unit})` 使用 surface 中的收件提示。DSH 资产桥传整文件，不宣称支持大视频流式拖拽：大型素材先做有声、保留时间对应的审阅副本或选择公共本地宿主。插件 MIME 要包含实际媒体类型。

公共 DSH tokens 在生成时内联，源只有 Core 的 `assets/dsh-tokens.css`。桌面三栏，窄栏上下布局，保存状态始终可达，高级动效默认折叠。主题可选自动/浅色/深色。

## 保存与恢复

整体意见不要求选屏；逐屏意见含 chapterId/stepId、当时字幕与播放位置。界面微调写进同条记录的 `adjustments`：`choreography`、`svg_edits`、`annotations`。它们是作者请求，不由宿主直接修改制作源。

草稿持久保存文本、作用范围、选屏与微调。作品快照变化时保留文字、提示旧版，不把旧微调自动套到新版。提交成功与通知成功分开显示；失败保留输入。快照包含文本/SVG 哈希和媒体 size/mtime，不声称是视频逐字节哈希或内容验收。

watch 覆盖当前 timeline、审阅数据、页面、SVG 和媒体。文件变化或当前文件无法核对时显式提示，记录携带 `stale` 与构建 snapshot。保留旧快照用于理解作者针对什么版本提出意见。修改源后重建审阅，再打开/刷新，不能只改模板让旧 snapshot 假装更新。

## 模型收件

```bash
python3 "<craft>/helpers/review_inbox.py" "<project>" --dry-run
python3 "<craft>/helpers/review_inbox.py" "<project>"
```

检查收据 `rejected`、`imported`、`skipped` 和 `legacy_adjustments`。后者暴露旧页面放在提交顶层的微调，防止丢失。新记录的 `adjustments` 与反馈一起进入 JSONL，内容哈希使重复收件幂等，旧文件留 `feedback/.previous/`。

1. 读全部 `feedback/*.jsonl`，按时间理解反馈轮次；整片意见进 `overall.jsonl`，不虚构 stepId。
2. 对照当前时间轴与 snapshot。旧版意见先重新定位，不能只凭同名 step 应用。
3. 同时读取文字和结构化调整。改上屏内容/事实先回 Idea；改静态构图需要 PPT Hell；局部动画和同步由 Craft 修。
4. 修订真实源，重建工程审阅并核验；已确认的最终交付再渲染。完成后标 `resolved` 并记处理结果；未完成显式保留。开始新一轮时归档已处理提交，未处理项带入新轮，草稿不作为决定。
5. 重建审阅，展示改动与对应片段；最后提供整片有声审阅。不把自检通过写成作者批准。

剪辑选择不用视觉 inbox：

```bash
python3 "<craft>/helpers/apply_selection.py" "<project>/edit"
```

它直接消费 `edit/selections.json` 并修改 EDL。随后重建逐字预览、工程字幕和时间绑定；确认后渲染正式底片；剪辑页的整体备注由 wake 回到对话，不混进 selections 的机器区间。
