import type { ComponentType } from "react";

export interface ChapterStepProps {
  step: number; // 0..(timeline.length - 1)
}

export type FeedbackType = "visual" | "timing" | "asset" | "copy" | "animation";

export interface TimelineStep {
  id: string;
  caption: string;
  srtRange: [number, number];
  startMs: number;
  endMs: number;
  durationMs: number;
  screenIntent?: string;
  visualModel?: string;
  modelStructure?: string;
  onScreenTextRule?: string;
  assetNeeds?: string[];
}

export interface ChapterDef {
  id: string;
  title: string;
  /**
   * Per-step SRT-derived metadata. Length === total visual steps.
   * SRT timing is the source of truth; do not estimate durations here.
   */
  timeline: TimelineStep[];
  Component: ComponentType<ChapterStepProps>;
}
