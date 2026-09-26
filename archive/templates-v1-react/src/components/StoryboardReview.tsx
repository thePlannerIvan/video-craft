import { useEffect, useMemo, useState, useCallback } from "react";
import { CHAPTERS } from "../registry/chapters";
import type { FeedbackType, TimelineStep } from "../registry/types";
import "./StoryboardReview.css";

interface StoryboardChapter {
  id: string;
  title: string;
  steps: TimelineStep[];
}

interface StoryboardData {
  chapters: StoryboardChapter[];
}

interface FeedbackEntry {
  id: string;
  batchId?: string;
  codeVersion?: string;
  chapterId: string;
  chapterTitle: string;
  stepId: string;
  stepIndex: number;
  srtRange: [number, number];
  type: FeedbackType;
  text: string;
  timestamp: number;
}

const feedbackTypes: Array<{ value: FeedbackType; label: string }> = [
  { value: "visual", label: "画面" },
  { value: "timing", label: "切分" },
  { value: "asset", label: "素材" },
  { value: "copy", label: "字幕" },
  { value: "animation", label: "动效" },
];

const STORAGE_KEY = "storyboard-feedback";
const BATCH_KEY = "storyboard-batch-seq";

function generateBatchId(): string {
  const today = new Date().toISOString().slice(0, 10).replace(/-/g, "");
  let seq = 1;
  try { seq = parseInt(localStorage.getItem(BATCH_KEY) || "0", 10) + 1; } catch {}
  localStorage.setItem(BATCH_KEY, String(seq));
  return "review-" + today + "-" + seq;
}

function readCodeVersion(): string {
  try {
    const meta = document.querySelector('meta[name="git-commit"]');
    if (meta) return meta.getAttribute("content") || "";
  } catch {}
  return "";
}

function loadFeedback(): FeedbackEntry[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

function fallbackData(): StoryboardData {
  return {
    chapters: CHAPTERS.map((chapter) => ({
      id: chapter.id,
      title: chapter.title,
      steps: chapter.timeline,
    })),
  };
}

export function StoryboardReview() {
  const [data, setData] = useState<StoryboardData>(() => fallbackData());
  const [activeChapter, setActiveChapter] = useState(0);
  const [activeStep, setActiveStep] = useState(0);
  const [type, setType] = useState<FeedbackType>("visual");
  const [feedback, setFeedback] = useState("");
  const [saved, setSaved] = useState(false);
  const [allFeedback, setAllFeedback] = useState<FeedbackEntry[]>(() => loadFeedback());
  const [showFeedback, setShowFeedback] = useState(false);

  useEffect(() => {
    fetch("/storyboard-review-data.json")
      .then((r) => (r.ok ? r.json() : null))
      .then((json) => {
        if (!json) return;
        const chapters = Array.isArray(json.chapters)
          ? json.chapters.map((chapter: any) => ({
              id: chapter.id,
              title: chapter.title || chapter.id,
              steps: chapter.steps || [],
            }))
          : [];
        if (chapters.length > 0) setData({ chapters });
      })
      .catch(() => {});
  }, []);

  const chapter = data.chapters[activeChapter];
  const step = chapter?.steps[activeStep];
  const totalSteps = useMemo(
    () => data.chapters.reduce((sum, item) => sum + item.steps.length, 0),
    [data],
  );
  const totalMs = useMemo(
    () =>
      data.chapters.reduce(
        (sum, item) =>
          sum + item.steps.reduce((inner, stepItem) => inner + stepItem.durationMs, 0),
        0,
      ),
    [data],
  );

  const jump = (chapterIndex: number, stepIndex: number) => {
    setActiveChapter(chapterIndex);
    setActiveStep(stepIndex);
    setSaved(false);
  };

  const jumpToFeedback = useCallback((entry: FeedbackEntry) => {
    const chIdx = data.chapters.findIndex((c) => c.id === entry.chapterId);
    if (chIdx >= 0) {
      setActiveChapter(chIdx);
      setActiveStep(entry.stepIndex);
    }
  }, [data.chapters]);

  const handleSubmit = async () => {
    if (!chapter || !step || !feedback.trim()) return;
    const currentBatchId = generateBatchId();
    const currentCodeVersion = readCodeVersion();
    const payload = {
      phase: "storyboard",
      batchId: currentBatchId,
      codeVersion: currentCodeVersion,
      chapterId: chapter.id,
      chapterTitle: chapter.title,
      stepId: step.id,
      stepIndex: activeStep,
      srtRange: step.srtRange,
      caption: step.caption,
      durationMs: step.durationMs,
      screenIntent: step.screenIntent || "",
      visualModel: step.visualModel || "",
      modelStructure: step.modelStructure || "",
      onScreenTextRule: step.onScreenTextRule || "",
      type,
      text: feedback.trim(),
      status: "open",
    };

    // 1. Write to server API → feedback/*.jsonl
    try {
      await fetch("/api/storyboard-feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
    } catch {
      /* server write failed, still save locally */
    }

    // 2. Write to localStorage for frontend feedback panel
    const entry: FeedbackEntry = {
      id: `${chapter.id}-${step.id}-${Date.now()}`,
      batchId: currentBatchId,
      codeVersion: currentCodeVersion,
      chapterId: chapter.id,
      chapterTitle: chapter.title,
      stepId: step.id,
      stepIndex: activeStep,
      srtRange: step.srtRange,
      type,
      text: feedback.trim(),
      timestamp: Date.now(),
    };
    const updated = [...allFeedback, entry];
    setAllFeedback(updated);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(updated));

    setFeedback("");
    setSaved(true);
    setTimeout(() => setSaved(false), 1600);
  };

  // Load external feedback from server on mount
  useEffect(() => {
    fetch("/api/feedback?chapter=all")
      .then((r) => (r.ok ? r.text() : ""))
      .then((text) => {
        if (!text) return;
        const lines = text.trim().split("\n").filter(Boolean);
        const fileEntries: FeedbackEntry[] = lines.map((line) => {
          try {
            const p = JSON.parse(line);
            return {
              id: `${p.chapterId}-${p.stepId || "unknown"}-${Date.parse(p.createdAt) || 0}`,
              chapterId: p.chapterId || "",
              chapterTitle: p.chapterTitle || "",
              stepId: p.stepId || "",
              stepIndex: p.stepIndex ?? 0,
              srtRange: p.srtRange || [0, 0],
              type: p.type || "visual",
              text: p.text || "",
              timestamp: Date.parse(p.createdAt) || Date.now(),
            };
          } catch {
            return null;
          }
        }).filter(Boolean) as FeedbackEntry[];

        if (fileEntries.length > 0) {
          setAllFeedback((prev) => {
            const seen = new Set(prev.map((f) => f.id));
            const merged = [...prev];
            for (const entry of fileEntries) {
              if (!seen.has(entry.id)) {
                merged.push(entry);
                seen.add(entry.id);
              }
            }
            localStorage.setItem(STORAGE_KEY, JSON.stringify(merged));
            return merged;
          });
        }
      })
      .catch(() => {});
  }, []);

  const clearFeedback = () => {
    localStorage.removeItem(STORAGE_KEY);
    setAllFeedback([]);
  };

  const downloadFeedback = () => {
    const jsonl = allFeedback.map((f) => JSON.stringify(f)).join("\n");
    const blob = new Blob([jsonl], { type: "application/jsonl" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "storyboard-feedback.jsonl";
    a.click();
    URL.revokeObjectURL(url);
  };

  const feedbackCount = allFeedback.length;

  return (
    <div className="sr-root">
      <div className="sr-shell">
        <header className="sr-top">
          <div>
            <h1 className="sr-title">Storyboard Review</h1>
            <div className="sr-sub">
              开发前确认每个 visual step：SRT 字幕、模型化画面、素材需求和反馈。
            </div>
          </div>
          <div className="sr-meta">
            <span className="sr-chip">{data.chapters.length} chapters</span>
            <span className="sr-chip">{totalSteps} steps</span>
            <span className="sr-chip">{(totalMs / 1000).toFixed(1)}s</span>
          </div>
        </header>

        <div className="sr-layout">
          <aside className="sr-sidebar">
            {data.chapters.map((item, chapterIndex) => (
              <div key={item.id}>
                <div className="sr-chapter-title">
                  {String(chapterIndex + 1).padStart(2, "0")} · {item.title}
                </div>
                {item.steps.map((stepItem, stepIndex) => (
                  <button
                    key={stepItem.id}
                    className={`sr-step-btn ${
                      activeChapter === chapterIndex && activeStep === stepIndex
                        ? "sr-step-btn--active"
                        : ""
                    }`}
                    onClick={() => jump(chapterIndex, stepIndex)}
                  >
                    <span className="sr-step-num">{stepIndex + 1}</span>
                    <span className="sr-step-cap">{stepItem.caption}</span>
                  </button>
                ))}
              </div>
            ))}
          </aside>

          <main className="sr-main">
            {!chapter || !step ? (
              <div className="sr-empty">没有可审核的 storyboard 数据。</div>
            ) : (
              <>
                <section className="sr-card">
                  <div className="sr-card-head">
                    <div className="sr-card-title">
                      {chapter.title} / Step {activeStep + 1}
                    </div>
                    <div className="sr-card-kicker">
                      {step.id} · SRT #{step.srtRange[0]}-{step.srtRange[1]} ·{" "}
                      {(step.durationMs / 1000).toFixed(1)}s
                    </div>
                  </div>
                  <div className="sr-card-body">
                    <div className="sr-caption">{step.caption}</div>
                  </div>
                </section>

                <section className="sr-card">
                  <div className="sr-card-head">
                    <div className="sr-card-title">画面理解</div>
                    <div className="sr-card-kicker">
                      {step.startMs}ms - {step.endMs}ms
                    </div>
                  </div>
                  <div className="sr-card-body">
                    <div className="sr-intent">
                      {step.screenIntent || "这个 step 还没有 screenIntent。"}
                    </div>
                  </div>
                </section>

                <section className="sr-card">
                  <div className="sr-card-head">
                    <div className="sr-card-title">模型化画面</div>
                    <div className="sr-card-kicker">不是字幕弹出，而是内容结构</div>
                  </div>
                  <div className="sr-card-body sr-model">
                    <div>
                      <div className="sr-model-label">Visual model</div>
                      <div className="sr-model-value">
                        {step.visualModel || "未定义：需要先判断这段内容适合画成什么模型"}
                      </div>
                    </div>
                    <div>
                      <div className="sr-model-label">Structure</div>
                      <div className="sr-model-value">
                        {step.modelStructure || "未定义：需要写出节点、层级、箭头、坐标轴或分组关系"}
                      </div>
                    </div>
                    <div>
                      <div className="sr-model-label">On-screen text rule</div>
                      <div className="sr-model-value">
                        {step.onScreenTextRule || "默认：主画面只保留节点/标签/关系词，不逐句展示字幕"}
                      </div>
                    </div>
                  </div>
                </section>

                <section className="sr-card">
                  <div className="sr-card-head">
                    <div className="sr-card-title">素材需求</div>
                  </div>
                  <div className="sr-card-body">
                    <div className="sr-assets">
                      {(step.assetNeeds || []).length > 0 ? (
                        step.assetNeeds!.map((asset) => (
                          <span key={asset} className="sr-asset">
                            {asset}
                          </span>
                        ))
                      ) : (
                        <span className="sr-asset">暂无明确素材需求</span>
                      )}
                    </div>
                  </div>
                </section>

                <section className="sr-card">
                  <div className="sr-card-head">
                    <div className="sr-card-title">
                      反馈
                      {feedbackCount > 0 && (
                        <span className="sr-feedback-badge">{feedbackCount}</span>
                      )}
                    </div>
                    <div className="sr-card-kicker">
                      <button
                        className="sr-link-btn"
                        onClick={() => setShowFeedback(!showFeedback)}
                      >
                        {showFeedback ? "收起反馈列表" : `查看已保存的反馈 (${feedbackCount})`}
                      </button>
                    </div>
                  </div>
                  <div className="sr-card-body sr-feedback">
                    <div className="sr-type-row">
                      {feedbackTypes.map((item) => (
                        <button
                          key={item.value}
                          className={`sr-type ${type === item.value ? "sr-type--on" : ""}`}
                          onClick={() => setType(item.value)}
                        >
                          {item.label}
                        </button>
                      ))}
                    </div>
                    <textarea
                      className="sr-textarea"
                      value={feedback}
                      onChange={(event) => setFeedback(event.target.value)}
                      placeholder="这里写这一段画面方案的问题：字幕分组、模型是否准确、素材、节奏都可以..."
                    />
                    <div className="sr-submit-row">
                      <button className="sr-submit" onClick={handleSubmit}>
                        {saved ? "✅ 已保存" : "保存这一屏反馈"}
                      </button>
                      {feedbackCount > 0 && (
                        <>
                          <button className="sr-download-btn" onClick={downloadFeedback}>
                            下载反馈 JSONL
                          </button>
                          <button className="sr-clear-btn" onClick={clearFeedback}>
                            清空
                          </button>
                        </>
                      )}
                    </div>
                  </div>
                </section>

                {showFeedback && allFeedback.length > 0 && (
                  <section className="sr-card">
                    <div className="sr-card-head">
                      <div className="sr-card-title">已保存的反馈</div>
                    </div>
                    <div className="sr-card-body">
                      {allFeedback.map((entry) => (
                        <div
                          key={entry.id}
                          className="sr-feedback-item"
                          onClick={() => jumpToFeedback(entry)}
                        >
                          <div className="sr-fi-head">
                            <span className="sr-fi-chapter">{entry.chapterTitle}</span>
                            <span className="sr-fi-step">Step {entry.stepIndex + 1}</span>
                            <span className={`sr-fi-type sr-fi-type--${entry.type}`}>
                              {feedbackTypes.find((t) => t.value === entry.type)?.label || entry.type}
                            </span>
                          </div>
                          <div className="sr-fi-text">{entry.text}</div>
                          <div className="sr-fi-time">
                            {new Date(entry.timestamp).toLocaleTimeString()}
                          </div>
                        </div>
                      ))}
                    </div>
                  </section>
                )}
              </>
            )}
          </main>
        </div>
      </div>
    </div>
  );
}
