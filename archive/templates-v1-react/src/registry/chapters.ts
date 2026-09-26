import type { ChapterDef } from "./types";
import ExampleChapter from "../chapters/01-example/Example";
import { timeline as exampleTimeline } from "../chapters/01-example/timeline";

/**
 * Order = order of presentation.
 *
 * Each chapter MUST provide a timeline array. Its length is the chapter's
 * step count, and each item carries SRT-derived timing metadata used by
 * review UI and strict auto-play.
 */
export const CHAPTERS: ChapterDef[] = [
  {
    id: "example",
    title: "示例章节",
    timeline: exampleTimeline,
    Component: ExampleChapter,
  },
];
