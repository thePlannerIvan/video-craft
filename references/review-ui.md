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

剪辑面独立打开：

```bash
python3 "<craft>/helpers/edl_preview_build.py" "<project>/edit"
python3 "<craft>/helpers/edl_review_surface.py" "<project>/edit" --surface-only
```

有插件时 `review_open` 接返回的 `edit/edl_review_surface.json`；没有插件去掉 `--surface-only`。视觉页的「逐字剪辑」只请求模型打开独立面，不嵌入另一份审阅桥。

## 公共接口

surface 采用 `review-surface/2.0.0`。`project_root`、`dir`、`feedback`、`draft`、`watch` 相对 surface 文件；`entry` 相对 dir。页面中所有 read/asset 路径相对 dir。视觉面 dir 是项目根，提交和草稿分别在 `review/review-submissions.json`、`review/review-draft.json`。

入口只有一个裸行 `{{REVIEW_BRIDGE}}`；宿主注入桥，页面调用 `ReviewBridge.connect()`。媒体与 SVG 图片用 `await review.asset(rel)`，文本用 `review.readText(rel)`；插件的 opaque iframe 不直接加载项目相对 URL、外链播放器或嵌套面。

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
4. 修订真实源、重新渲染受影响片段并核验。完成后标 `resolved` 并记处理结果；未完成显式保留。开始新一轮时归档已处理提交，未处理项带入新轮，草稿不作为决定。
5. 重建审阅，展示改动与对应片段；最后提供整片有声审阅。不把自检通过写成作者批准。

剪辑选择不用视觉 inbox：

```bash
python3 "<craft>/helpers/apply_selection.py" "<project>/edit"
```

它直接消费 `edit/selections.json` 并修改 EDL。随后重新渲染底片、重建字幕和时间绑定；剪辑页的整体备注由 wake 回到对话，不混进 selections 的机器区间。
