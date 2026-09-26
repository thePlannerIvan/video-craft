import { useCallback, useEffect, useMemo, useState } from "react";
import type { ChapterDef } from "../registry/types";

/**
 * Bump this when chapter order or timeline lengths change so old persisted
 * cursors do not land on removed steps.
 */
const STORAGE_KEY = "presentation-timeline-cursor-v1";

export type Cursor = { chapter: number; step: number };

export interface StepperState {
  cursor: Cursor;
  totalChapters: number;
  chapterTotalSteps: number;
  globalIndex: number;
  totalGlobal: number;
  next(): void;
  prev(): void;
  jumpToChapter(idx: number, step?: number): void;
  jumpToGlobal(globalIdx: number): void;
}

const clamp = (n: number, lo: number, hi: number) =>
  Math.max(lo, Math.min(hi, n));

function stepCount(chapter: ChapterDef): number {
  return chapter.timeline.length;
}

function sanitize(cursor: Cursor, chapters: ChapterDef[]): Cursor {
  if (chapters.length === 0) return { chapter: 0, step: 0 };
  const chapter = clamp(cursor.chapter | 0, 0, chapters.length - 1);
  const count = stepCount(chapters[chapter]!);
  const step = clamp(cursor.step | 0, 0, Math.max(0, count - 1));
  return { chapter, step };
}

export function useStepper(chapters: ChapterDef[]): StepperState {
  const [cursor, setCursor] = useState<Cursor>(() => {
    const fallback = { chapter: 0, step: 0 };
    if (typeof window === "undefined") return fallback;
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      if (raw) return sanitize(JSON.parse(raw), chapters);
    } catch {
      /* ignore */
    }
    return fallback;
  });

  useEffect(() => {
    setCursor((cur) => {
      const next = sanitize(cur, chapters);
      return next.chapter === cur.chapter && next.step === cur.step ? cur : next;
    });
  }, [chapters]);

  useEffect(() => {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(cursor));
    } catch {
      /* ignore */
    }
  }, [cursor]);

  const offsets = useMemo(() => {
    const arr: number[] = [];
    let acc = 0;
    for (const c of chapters) {
      arr.push(acc);
      acc += stepCount(c);
    }
    return arr;
  }, [chapters]);

  const totalGlobal = useMemo(
    () => chapters.reduce((sum, c) => sum + stepCount(c), 0),
    [chapters],
  );

  const globalIndex = (offsets[cursor.chapter] ?? 0) + cursor.step;

  const next = useCallback(() => {
    setCursor((cur) => {
      const c = chapters[cur.chapter]!;
      if (cur.step < stepCount(c) - 1) return { ...cur, step: cur.step + 1 };
      if (cur.chapter < chapters.length - 1) {
        return { chapter: cur.chapter + 1, step: 0 };
      }
      return cur;
    });
  }, [chapters]);

  const prev = useCallback(() => {
    setCursor((cur) => {
      if (cur.step > 0) return { ...cur, step: cur.step - 1 };
      if (cur.chapter > 0) {
        const previous = chapters[cur.chapter - 1]!;
        return { chapter: cur.chapter - 1, step: stepCount(previous) - 1 };
      }
      return cur;
    });
  }, [chapters]);

  const jumpToChapter = useCallback(
    (idx: number, step = 0) => {
      const ch = clamp(idx, 0, chapters.length - 1);
      const c = chapters[ch]!;
      setCursor({ chapter: ch, step: clamp(step, 0, stepCount(c) - 1) });
    },
    [chapters],
  );

  const jumpToGlobal = useCallback(
    (globalIdx: number) => {
      const target = clamp(globalIdx, 0, totalGlobal - 1);
      let acc = 0;
      for (let i = 0; i < chapters.length; i += 1) {
        const count = stepCount(chapters[i]!);
        if (target < acc + count) {
          setCursor({ chapter: i, step: target - acc });
          return;
        }
        acc += count;
      }
    },
    [chapters, totalGlobal],
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (
        e.target instanceof HTMLInputElement ||
        e.target instanceof HTMLTextAreaElement ||
        e.target instanceof HTMLSelectElement
      ) {
        return;
      }
      if (e.key === "ArrowRight" || e.key === " ") {
        e.preventDefault();
        next();
      } else if (e.key === "ArrowLeft" || e.key === "Backspace") {
        e.preventDefault();
        prev();
      } else if (e.key === "Home") {
        jumpToChapter(0, 0);
      } else if (e.key === "End") {
        const last = chapters.length - 1;
        jumpToChapter(last, stepCount(chapters[last]!) - 1);
      } else if (e.key >= "1" && e.key <= "9") {
        const n = Number(e.key) - 1;
        if (n < chapters.length) jumpToChapter(n, 0);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [next, prev, jumpToChapter, chapters]);

  const ch = chapters[cursor.chapter]!;
  return {
    cursor,
    totalChapters: chapters.length,
    chapterTotalSteps: stepCount(ch),
    globalIndex,
    totalGlobal,
    next,
    prev,
    jumpToChapter,
    jumpToGlobal,
  };
}
