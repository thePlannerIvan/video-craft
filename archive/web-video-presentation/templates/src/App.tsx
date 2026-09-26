import "./styles/fonts.css";
import "./styles/tokens.css";
import "./styles/base.css";
import "./styles/animations.css";

import { useCallback } from "react";
import { PlayButton } from "./components/PlayButton";
import { ProgressBar } from "./components/ProgressBar";
import { ReviewPanel } from "./components/ReviewPanel";
import { Stage } from "./components/Stage";
import { StoryboardReview } from "./components/StoryboardReview";
import { useAutoPlay } from "./hooks/useAutoPlay";
import { useStepper } from "./hooks/useStepper";
import { CHAPTERS } from "./registry/chapters";

export default function App() {
  const reviewMode =
    typeof window !== "undefined"
      ? new URLSearchParams(window.location.search).get("review")
      : null;

  if (reviewMode === "storyboard") {
    return <StoryboardReview />;
  }

  const stepper = useStepper(CHAPTERS);
  const ch = CHAPTERS[stepper.cursor.chapter]!;
  const Cmp = ch.Component;
  const currentTimelineStep = ch.timeline[stepper.cursor.step];
  const isLastStep = stepper.globalIndex >= stepper.totalGlobal - 1;

  const onAutoAdvance = useCallback(() => stepper.next(), [stepper]);
  const auto = useAutoPlay({
    chapterId: ch.id,
    step: stepper.cursor.step,
    timelineStep: currentTimelineStep,
    onAdvance: onAutoAdvance,
    isLastStep,
  });

  const manualAdvance = useCallback(() => {
    auto.pause();
    stepper.next();
  }, [auto, stepper]);

  return (
    <>
      <Stage onAdvance={manualAdvance}>
        <div key={ch.id} className="scene">
          <Cmp step={stepper.cursor.step} />
        </div>
      </Stage>
      <ProgressBar
        chapters={CHAPTERS}
        cursor={stepper.cursor}
        onJumpChapter={(idx) => {
          auto.pause();
          stepper.jumpToChapter(idx);
        }}
      />
      <PlayButton
        playing={auto.playing}
        onToggle={auto.toggle}
        durationMs={auto.currentDuration}
      />
      <ReviewPanel
        chapterId={ch.id}
        chapterTitle={ch.title}
        currentStep={stepper.cursor.step}
        timeline={ch.timeline}
        onJumpStep={(step) => {
          auto.pause();
          stepper.jumpToChapter(stepper.cursor.chapter, step);
        }}
      />
    </>
  );
}
