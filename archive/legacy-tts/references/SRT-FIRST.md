# SRT-First 工作流：字幕优先模式

当用户已经有 `.srt` 字幕文件（带精确时间码）时，走这条分支。
SRT 时间码是唯一权威的时钟源，替代 TTS 估时驱动自动播放。

---

## 何时触发

用户给了以下任一输入时走 SRT-First：

- `.srt` 字幕文件 + 口播稿/脚本
- `.srt` 字幕文件 + 原始文章
- 明确说"按照字幕时间线来做"

**没有 SRT 文件** → 走原 TTS 分支（SKILL.md Phase 1→4），
本文档不适用。

---

## Phase 0：字幕预处理（新增）

```
Phase 0.1  解析 SRT → timecode-map.json
Phase 0.2  口播稿 ↔ SRT 文本校对（错别字、断句）
Phase 0.3  节拍分组：SRT 行 → 视觉 step（关键步骤）
   ▼
进入 Phase 1（复用原流程，但 step 按节拍分组切，不按 SRT 行）
```

### 0.1 解析 SRT

```bash
python3 scripts/parse-srt.py <字幕文件.srt> --output timecode-map.json
```

产出 `timecode-map.json`（中间产物，供 agent 审阅分组用）：

```json
{
  "totalEntries": 258,
  "totalDurationMs": 481600,
  "entries": [
    {
      "index": 0,
      "startMs": 0,
      "endMs": 1467,
      "durationMs": 1467,
      "text": "前两天我发了一篇小红书"
    },
    ...
  ]
}
```

### 0.2 文本校对

对照口播稿（`script.md` 或等价文件）检查 SRT 文本：
- **改错别字**：SRT 文本与口播稿不一致的错字
- **不改口语表达**：用户的口语结构、用词习惯保留
- **不改时间码**：SRT 时间码是录制/剪辑的产出，只改文本内容

### 0.3 节拍分组（核心）

**问题**：SRT 字幕行 ≠ 视觉节拍。258 条 SRT 如果 1:1 映射为 step，
会变成"一句一跳"——碎片化、动画密度过高、观众无法聚焦。

**原则**：一个视觉 step = 一个**完整想法**（口播自然断句，约 3~10 秒）。

#### 分组规则

| 规则 | 判断依据 | 处理 |
|---|---|---|
| **衔接碎片** | 单字/双字连接词："所以""首先""但是""好""然后""那" | 并入相邻节拍，不独立成 step |
| **连续叙述** | 3~8 条 SRT 在讲同一主题（同一件事、同一个画面概念） | 合并为一个视觉场景，内部用 CSS transition 渐进揭示 |
| **主题切换** | 内容从 A 切换到 B（如"数据抓取"→"框架分析"；"Adidas"→"Nike"） | 新 step 边界 |
| **金句/结论** | 独句总结、call-to-action、反转 | 可独立成 step（给视觉重音） |
| **时长约束** | 合并后 step 时长 = 所含 SRT 时长之和 | 建议 3~10 秒/step；< 2s 太薄应合并；> 15s 应拆分 |

#### 分组示例

```
SRT 行                               →    视觉 step

#66 首先                              ┐
#67 我们来跑一个GWTB                   ├─ step 0 (4.2s) "引入 GWTB"
                                       │
#68 第一步                             ┐
#69 我们首先要确定数据的需求             │
#70 我要分析的是一个品牌的传播策略       │
#71 所以我要看的是商业笔记              ├─ step 1 (18.2s) "数据需求"
#72 所以                               │  ← "所以"不单独成步
#73 直接抓这个品牌在小红书上的点赞       │
#74 排序高互动量的笔记                  │
#75 按照近半年最多点赞                  │
#76 每个品牌抓100条                     │
#77 你就刚好能够用这样的内容             │
#78 来反推他们的传播策略                ┘
                                       │
#79 第二步抓到了整体的数据               ┐
#80 我们直接用GWTB的框架分析            ├─ step 2 (7.9s) "框架分析"
#81 就能够还原他们这两个品牌             │
#82 究竟一开始的策略是什么样的           ┘
                                       │
#83 好抓完了数据                        ┐
#84 跑完了分析                         ├─ step 3 (6.8s) "过渡：看结果"
#85 我们来看结果                        ┘
```

#### 产出：在 `timecode-map.json` 上叠加分组

agent 在 0.3 产出带分组的 `timecode-map.json`：

```json
{
  "chapters": {
    "gwtb-method": {
      "srtRange": [66, 85],
      "steps": [
        { "step": 0, "srtIndices": [66, 67], "durationMs": 4167 },
        { "step": 1, "srtIndices": [68,69,70,71,72,73,74,75,76,77,78], "durationMs": 18234 },
        { "step": 2, "srtIndices": [79, 80, 81, 82], "durationMs": 7934 },
        { "step": 3, "srtIndices": [83, 84, 85], "durationMs": 6833 }
      ]
    }
  }
}
```

用户对齐 Checkpoint Plan 时确认分组合理性。

---

## Phase 1 调整（SRT-First 模式）

### script.md

如果用户已有口播稿 → 直接落盘为 `script.md`。
如果用户只有 SRT + 原始文章 → `script.md` 用 SRT 文本拼合（去掉时间码，
按节拍分组拼成自然段落）。

### outline.md

按**视觉 step**（非 SRT 行）写每步屏幕内容。新增字段：

```markdown
## 4. gwtb-method — GWTB 数据分析过程（4 steps · ~37s）

> SRT 范围：#67–86（20 行 → 合并为 4 个视觉 step）
> 详见 timecode-map.json

**信息池**：...
```

每步标注覆盖的 SRT 行范围（方便回查字幕时间线）：

```markdown
- step 1 (~4s) — GWTB 方法标题卡。覆盖 SRT #66–67
- step 2 (~18s) — 数据需求流程图（确定需求 → 商业笔记 → 点赞排序 → 100条/品牌）。覆盖 SRT #68–78
```

---

## Phase 2 调整（SRT-First 模式）

### step-durations.json

章节实现完成后，从 `timecode-map.json` 生成 `step-durations.json`：

```bash
python3 scripts/parse-srt.py <字幕.srt> \
  --timecode-map timecode-map.json \
  --output-durations presentation/public/step-durations.json
```

格式（按章节分组的毫秒数组）：

```json
{
  "gwtb-method": [4167, 18234, 7934, 6833],
  ...
}
```

`useAutoPlay` hook 读取此文件驱动自动播放。每个数字 = 该 step 的展示时长。

### narrations.ts

**仍按视觉 step 编写**，不是按 SRT 行。每个元素 = 该 step 所有 SRT 行的拼接文本：

```ts
// gwtb-method/narrations.ts
export const narrations: Narration[] = [
  "首先，我们来跑一个GWTB",                                      // step 0 (SRT #66-67)
  "第一步，我们首先要确定数据的需求。我要分析的是一个品牌的传播策略，所以我要看的是商业笔记。所以，直接抓这个品牌在小红书上的点赞、排序高互动量的笔记，按照近半年最多点赞，每个品牌抓100条。你就刚好能够用这样的内容来反推他们的传播策略。",  // step 1 (SRT #68-78)
  "第二步抓到了整体的数据，我们直接用GWTB的框架分析，就能够还原他们这两个品牌究竟一开始的策略是什么样的。",  // step 2 (SRT #79-82)
  "好抓完了数据，跑完了分析，我们来看结果。",                       // step 3 (SRT #83-85)
];
```

> **注意**：narrations 文本拼接时自然断句即可，不必保留 SRT 的碎片化分行。

---

## 场景合并模式（Scene Merging）

SRT-First 下节拍分组 = 多个 SRT 行合并为一个视觉 step，对应代码模式：

```tsx
// ✅ 正确：一个 React key + 内部 CSS transition 渐进揭示
if (step >= 6 && step <= 10) {
  const s = step - 6;
  return (
    <div className="scene" key="funnel">
      <div className={`node ${s >= 1 ? 'node--glow' : ''}`}>确定数据需求</div>
      <div className={`node ${s >= 3 ? 'node--glow' : ''}`}>GWTB 框架分析</div>
      <div className={`node ${s >= 5 ? 'node--glow' : ''}`}>看结果</div>
    </div>
  );
}

// ❌ 错误：同一个漏斗拆成 3 个独立 return，React 每次卸载重建 DOM
if (step === 6) return <div className="scene" key="funnel-1">...</div>;
if (step === 7) return <div className="scene" key="funnel-2">...</div>;
if (step === 8) return <div className="scene" key="funnel-3">...</div>;
```

判断标准：如果两步的"视觉骨架"相同（同一个图/表/漏斗/轴/对比），就应该合并。
详见 [`../../../references/COMPOSITION-CRAFT.md`](../../../references/COMPOSITION-CRAFT.md) Part 2.5「渐进揭示 vs 切页」。

---

## SRT-First 模式下的 Checkpoint 流程

```
Phase 0  字幕预处理
   ▼
Phase 1  内容编写（按视觉 step 切分）
   ▼
[Checkpoint Plan]  ← 原 5 件事 + 确认 timecode-map 分组
   ▼
Phase 2  网页开发（每章按视觉 step 实现）
   ▼
[Checkpoint Review]  ← ★ 新增：审核模式（字幕面板对照 SRT + 反馈 + 自动播放）
   ▼
[Checkpoint Audio]  ← SRT-First 下可跳过（无 TTS 合成）
   ▼
Phase 4  录屏 + 后期
```

---

## 与 TTS 分支的关系

| 维度 | TTS 分支（原） | SRT-First 分支（新） |
|---|---|---|
| 时钟源 | TTS 音频文件时长 | SRT 字幕时间码 |
| step 切分 | 口播稿自然断句 | SRT 行 → 节拍分组 |
| 自动播放 | 音频播完 → 自动 next | step-durations.json 定时器 |
| audio-segments.json | 必需（TTS 合成输入） | 不需要 |
| Phase 3 音频合成 | 运行 | 跳过 |
| Checkpoint Audio | 必停 | 标记为"已跳过（SRT-First）" |
| narrations.ts | 每 step 口播文本（供 TTS） | 每 step 口播文本（供字幕面板显示） |

两个分支共享：outline.md 格式、../../../references/COMPOSITION-CRAFT.md 开发指引、主题系统、
完工自检、场景合并模式。
