# Idea / Story 内容包交接

> **老路线存档**：本文里凡涉及 `import_svg_page` / `generate-composition` / `check_parity`
> 或「保真页面(page)」的段落，都是 **page 十步路线的存档说明**，新项目不要照做。
> 画面的唯一入口是 `helpers/film.py`（见 [film.md](film.md)），存档总览见
> [legacy-page-route.md](legacy-page-route.md)。


默认承接 Video Idea System，也兼容既有 Story 交付。先读取 script.md、visual-plan.json、production-brief.md 和作者原始反馈；素材路径按交付声明的根解析，不假设都相对 edit/。新版 contract 5.0 使用 screens / screen_id，旧 4.0 使用 blueprints / blueprint_id，均保持每屏一个 Beat。

## 先设计，再绑定实测声音

没有录音时按 content-to-production.md 形成制作方案和预演，不能运行最终字幕对齐来伪造时钟。声音到位、剪接批准、底片渲染和语义字幕构建后：

```bash
python <skill>/visual/scripts/align-visual-plan.py --plan <project>/deliverable/visual-plan.json --script <project>/deliverable/script.md --edit-dir <edit> --output <edit>/timeline/content-alignment.json
```

对齐结果保留 sample 作为素材参考，保留 mustShow / mustExpress / exactLabels / evidence。`blueprintId`、`screenId` 都沿用原 screen_id；grouping 的 sourceBlueprintId 使用这个原 ID，不重编号。脚本检查稿件哈希，但匹配只是候选：逐段核听，处理 needsReview；演示原声、临时插入段或实录改意不能硬塞进自动匹配结果。

每个 Step 只引用一个 screen，在该 Beat 内可以有多个状态；有序 cue 必须连续。明确的无口播演示窗口以 EDL 与独立视觉槽承载，写在制作说明及创意兑现表，不伪造字幕。原稿漏段或发生语义变化时先更新并确认内容包，然后重新对齐。

```bash
python <skill>/helpers/timeline_derive.py <edit> --grouping <edit>/timeline/grouping.json --alignment <edit>/timeline/content-alignment.json --output-timeline <edit>/timeline/timeline.json
```

存在上游画面契约时必须带 `--alignment`。校验拒绝错误/过期对齐、未处理屏、跨屏引用、重复和遗漏 cue；只证明绑定覆盖，不证明画面内容真的实现。语音很短但画面需延长时，先调整制作/剪辑安排再重新测时，不手改 cue。

旧 `--srt` 入口保留给外部导入/诊断，输出标记 srt-import，不能通过最终 measured 绑定检查。SRT 是实测字幕的导出视图，不是另一条时间线。

## 作者决定与样张

作者要求的擦除、聚焦、翻页、顺序等，从 production-brief 或历史反馈逐条继承。Agent 的设计建议等待本阶段审阅；样张摆法可重做。没有 production-brief 的旧 Story 项目，先从直接反馈提取这三类并核对，不因格式迁移遗漏决定。

每 Beat 在 creative-check.md 对照内容责任、作者动作、素材身份和成片窗口。验收同时看听得到什么、看得清什么、创意变化有没有发生，不能只确认文件存在。

## 工作台 SVG 快照

承接 PPT Hell 工作台时，将 `<project>/.pages` 或 `.snapshot` 指向 `_internal/06_workbench/snapshots/<id>/snapshot.json`（也可指向该快照目录）。快照的 `order` 决定页序，`page_key` 保留稳定身份；不读取工作台当前页来补齐缺失快照。

`visual/scripts/snapshot_input.py` 是唯一严格入口；SVG 导入、合成生成、自动动效编排和统一审阅构建共用它。它校验 `snapshot.sha256`、SVG/资产及嵌套 SVG 依赖字节、页面身份、原 visual-plan 与 script 绑定。嵌套 SVG 的固定子图一起复制，父文件保持打包字节；缺依赖、越界、同 ID 快照被改写时拒绝消费。旧 `input/scenes/`、PPT 根目录和普通 SVG 目录入口仍可用。

原 `script_hash` 只证明打包的原脚本身份，不证明编辑后的 SVG 文案与录音语义一致。消费者保留 `content_binding`、逐页 `content_delta` 和 `script_semantics_verified: false`；`changed_needs_check` 交实际差异给内容/核查环节，不改上游 Hash 来消除提示。

再次交接必须产生新快照。导入清单与动效记录标记受影响的静态屏、元素/步骤绑定及待检查内容；notes-only 修订不使静态画面失效。未变化屏的 Craft 动效设置保留；更换步骤 ID 不继承旧元素的设置。程序不改 EDL、音频或实测时间线，不反写工作台或上游内容包。需要调整录音/稿件时明确进入声音与对齐流程。

页序或集合变化时，导入回执的 `timeline_needs_review` 提醒重新对齐时间线。`generate-composition.py` 比较按 startMs 排列、合并连续同页步骤后的 sourcePageKey 与 snapshot.order；不一致时报 timeline_order_changed。时间线制作方按快照顺序更新分镜与录音绑定，再生成合成；不会直接重排已有音频。增删页以 collection_delta 说明相对原 visual-plan 的变化，并保持 changed_needs_check。
