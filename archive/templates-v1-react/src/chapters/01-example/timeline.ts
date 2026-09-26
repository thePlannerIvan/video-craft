import type { TimelineStep } from "../../registry/types";

/**
 * SRT-derived visual timeline for this chapter.
 *
 * New projects should generate this from timeline/timeline.json after SRT
 * grouping is approved. Do not hand-estimate durations: start/end/duration
 * must come from the source SRT timecodes.
 */
export const timeline: TimelineStep[] = [
  {
    id: "example-001",
    caption: "这是示例章节的第一步。把这一行换成 SRT 合并后的字幕文本。",
    srtRange: [0, 1],
    startMs: 0,
    endMs: 4200,
    durationMs: 4200,
    screenIntent: "用一屏建立主题和观看期待。",
    visualModel: "问题钩子图",
    modelStructure: "一个中心问题 + 两个被拉开的答案方向",
    onScreenTextRule: "只保留中心问题，不把整段字幕搬到主画面。",
  },
  {
    id: "example-002",
    caption: "第二步。每个数组元素对应章节里 step === N 的那一屏。",
    srtRange: [2, 4],
    startMs: 4200,
    endMs: 9800,
    durationMs: 5600,
    screenIntent: "展示一条核心机制或对比关系。",
    visualModel: "机制框架图",
    modelStructure: "左侧输入 → 中间处理机制 → 右侧输出结果",
    onScreenTextRule: "只显示节点标题和关系词，字幕留给 ReviewPanel。",
  },
  {
    id: "example-003",
    caption: "第三步。网页自动播放时会严格按这里的 SRT 时长推进。",
    srtRange: [5, 6],
    startMs: 9800,
    endMs: 14500,
    durationMs: 4700,
    screenIntent: "收束为一句可记住的结论。",
    visualModel: "结论锤点",
    modelStructure: "一个结论 + 一个支撑证据",
    onScreenTextRule: "允许短句大字，但不能逐句弹字幕。",
  },
];
