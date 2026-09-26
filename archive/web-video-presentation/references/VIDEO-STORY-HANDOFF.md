# Video Story System Handoff

`input/visual-plan.json`按“一段口播一张蓝图”规定每个 Speech Beat 的内容承载要求。Web Video Presentation 必须保持这组一一对应关系，再自主决定每段画面怎么画、如何排版、如何拆 Visual Step、在该段时间内做什么动画。

## 输入与对齐

- `input/subtitles.srt`：唯一精确时间真相源；
- `input/script.md`：Speech Beat 与最终口播；
- `input/visual-plan.json`：各 Beat 对应的内容层信息责任（v4：question / must_show / must_express / exact_labels / evidence）；
- `input/visual-blueprint.md`：人读参考；
- `input/assets/`：已有真实素材。

```bash
python3 scripts/align-visual-plan.py \
  --plan input/visual-plan.json \
  --script input/script.md \
  --srt input/subtitles.srt \
  --output timeline/visual-plan-alignment.json
```

脚本先把 Speech Beat 顺序匹配到 SRT，再把每张蓝图的唯一`beat_id`转换成候选时间范围。候选范围只是该段下游设计的边界，不是动画指令；低置信或缺失 Beat 必须人工处理。

## Web Video 的设计责任

对每张逐段蓝图的`must_show`、`must_express`、`exact_labels`和`evidence`，下游自行判断：

- 哪些信息适合真实素材、图表、模型、对比、空间关系或其他形式；
- 这一张蓝图在其口播段内拆成几个 Visual Step；
- 哪些元素同时存在，哪些渐进揭示；
- 画面何时进入、保持、变化和退出；
- 信息密度需要多长阅读时间；
- 口播与画面是同步还是先画面后解释；不得跨到另一张蓝图绑定的口播段。

不要向上游索要构图、State 或动画时间。已有蓝图没有这些字段是正确状态。

## Phase 2 规则

1. 先处理`beatAlignments`与`blueprintAlignments`中的`needsReview`。
2. 以内容字段和证据来源设计画面，不把它改写成字幕卡。
3. 在`grouping.json`中保留单一`sourceBlueprintId`。一张蓝图可在自己的 Beat 内拆成多个 Step，但一个 Step 不得服务多个上游蓝图。
4. 画法、视觉模型、排版、状态和精确时间全部在 Storyboard 阶段提出，并进入 Checkpoint Plan。Storyboard 的提案必须直接回查上游内容字段，不得把上游字段默认为画法。
5. 录制内容改变原意或视觉信息需求时，返回 Video Story System 更新蓝图。

## Checkpoint Plan 必查

- Beat 与 SRT 对齐无未处理异常；
- 每张蓝图只使用其对应 Beat 的 SRT 范围，并且必须呈现的信息都有明确承载方式；
- 证据和语义限制没有丢失；
- 实际模型、动画状态、排版和时间安排由本阶段提出并获得用户批准；用户在这里审“画面是否好看且匹配观点”。
