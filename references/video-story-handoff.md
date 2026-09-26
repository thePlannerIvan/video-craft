# Idea / Story 内容包交接

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
