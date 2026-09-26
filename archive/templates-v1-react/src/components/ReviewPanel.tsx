import { useMemo, useState } from "react";
import type { FeedbackType, TimelineStep } from "../registry/types";
import "./ReviewPanel.css";

interface Props {
  chapterId: string;
  chapterTitle: string;
  currentStep: number;
  timeline: TimelineStep[];
  onJumpStep(step: number): void;
}

const feedbackTypes: Array<{ value: FeedbackType; label: string }> = [
  { value: "visual", label: "画面" },
  { value: "timing", label: "节奏" },
  { value: "asset", label: "素材" },
  { value: "copy", label: "字幕" },
  { value: "animation", label: "动效" },
];

export function ReviewPanel({
  chapterId,
  chapterTitle,
  currentStep,
  timeline,
  onJumpStep,
}: Props) {
  const [feedback, setFeedback] = useState("");
  const [type, setType] = useState<FeedbackType>("visual");
  const [saved, setSaved] = useState(false);
  const [collapsed, setCollapsed] = useState(true);

  const current = timeline[currentStep];
  const totalMs = useMemo(
    () => timeline.reduce((sum, item) => sum + item.durationMs, 0),
    [timeline],
  );

  const handleSubmit = async () => {
    if (!feedback.trim() || !current) return;
    const payload = {
      chapterId,
      stepId: current.id,
      stepIndex: currentStep,
      srtRange: current.srtRange,
      caption: current.caption,
      durationMs: current.durationMs,
      type,
      text: feedback.trim(),
      status: "open",
    };
    try {
      await fetch("/api/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      setFeedback("");
      setSaved(true);
      setTimeout(() => setSaved(false), 1600);
    } catch {
      /* keep text in the box */
    }
  };

  return (
    <div
      className={`rp-root ${collapsed ? "rp-root--collapsed" : ""}`}
      data-no-advance
    >
      <button
        className="rp-toggle"
        onClick={() => setCollapsed((c) => !c)}
        data-no-advance
      >
        <span className="rp-toggle-icon">{collapsed ? "▲" : "▼"}</span>
        <span className="rp-toggle-label">
          {collapsed ? "展开逐画面审核" : "收起审核"}
        </span>
        {current && (
          <span className="rp-toggle-now">
            [{currentStep + 1}/{timeline.length}] SRT #{current.srtRange[0]}-
            {current.srtRange[1]} · {(current.durationMs / 1000).toFixed(1)}s ·{" "}
            {current.caption}
          </span>
        )}
      </button>

      {!collapsed && (
        <div className="rp-body">
          <section className="rp-timeline">
            <header className="rp-head">
              <div>
                <div className="rp-title">{chapterTitle}</div>
                <div className="rp-sub">
                  {timeline.length} steps · {(totalMs / 1000).toFixed(1)}s
                </div>
              </div>
              <div className="rp-count">
                {currentStep + 1}/{timeline.length}
              </div>
            </header>
            <div className="rp-list">
              {timeline.map((item, i) => (
                <button
                  key={item.id}
                  className={`rp-line ${
                    i === currentStep ? "rp-line--active" : ""
                  } ${i < currentStep ? "rp-line--past" : ""}`}
                  onClick={() => onJumpStep(i)}
                  data-no-advance
                >
                  <span className="rp-line-num">{i + 1}</span>
                  <span className="rp-line-range">
                    #{item.srtRange[0]}-{item.srtRange[1]}
                  </span>
                  <span className="rp-line-text">{item.caption || "(空白)"}</span>
                  <span className="rp-line-time">
                    {(item.durationMs / 1000).toFixed(1)}s
                  </span>
                </button>
              ))}
            </div>
          </section>

          <section className="rp-feedback">
            <div className="rp-fb-meta">
              <span>{current?.id ?? "no-step"}</span>
              <span>
                {current
                  ? `SRT #${current.srtRange[0]}-${current.srtRange[1]}`
                  : ""}
              </span>
            </div>
            <div className="rp-types">
              {feedbackTypes.map((item) => (
                <button
                  key={item.value}
                  className={`rp-type ${type === item.value ? "rp-type--on" : ""}`}
                  onClick={() => setType(item.value)}
                  data-no-advance
                >
                  {item.label}
                </button>
              ))}
            </div>
            <textarea
              className="rp-fb-input"
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
              placeholder="写这一屏的问题：画面、节奏、素材、字幕或动效..."
              rows={5}
              data-no-advance
            />
            <button
              className="rp-fb-submit"
              onClick={handleSubmit}
              data-no-advance
            >
              {saved ? "已保存到反馈队列" : "保存当前画面反馈"}
            </button>
          </section>
        </div>
      )}
    </div>
  );
}
