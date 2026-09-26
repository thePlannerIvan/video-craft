import { useCallback, useEffect, useRef, useState } from "react";
import type { TimelineStep } from "../registry/types";

type DurationsMap = Record<string, number[]>;

interface UseAutoPlayArgs {
  chapterId: string;
  step: number;
  timelineStep: TimelineStep | undefined;
  onAdvance(): void;
  isLastStep: boolean;
}

/**
 * SRT timeline player. It auto-advances by SRT-derived durations only:
 * public/step-durations.json first, then timeline.ts durationMs as fallback.
 */
export function useAutoPlay({
  chapterId,
  step,
  timelineStep,
  onAdvance,
  isLastStep,
}: UseAutoPlayArgs) {
  const [durations, setDurations] = useState<DurationsMap | null>(null);
  const [playing, setPlaying] = useState(() => {
    if (typeof window === "undefined") return false;
    return new URLSearchParams(window.location.search).get("auto") === "1";
  });
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const playingRef = useRef(playing);
  playingRef.current = playing;

  useEffect(() => {
    fetch("/step-durations.json")
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => setDurations(data || {}))
      .catch(() => setDurations({}));
  }, []);

  useEffect(() => {
    const onFocusIn = (e: FocusEvent) => {
      if (
        e.target instanceof HTMLInputElement ||
        e.target instanceof HTMLTextAreaElement ||
        e.target instanceof HTMLSelectElement
      ) {
        setPlaying(false);
      }
    };
    document.addEventListener("focusin", onFocusIn);
    return () => document.removeEventListener("focusin", onFocusIn);
  }, []);

  useEffect(() => {
    if (isLastStep && playing) setPlaying(false);
  }, [isLastStep, playing]);

  useEffect(() => {
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, []);

  const durationFromJson = durations?.[chapterId]?.[step];
  const currentDuration = durationFromJson ?? timelineStep?.durationMs ?? 0;

  useEffect(() => {
    if (!playing || currentDuration <= 0) return;
    timerRef.current = setTimeout(() => {
      if (playingRef.current) onAdvance();
    }, currentDuration);
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [playing, currentDuration, onAdvance]);

  const toggle = useCallback(() => setPlaying((p) => !p), []);
  const pause = useCallback(() => setPlaying(false), []);

  return { playing, toggle, pause, currentDuration };
}
