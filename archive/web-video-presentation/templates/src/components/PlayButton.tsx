import "./PlayButton.css";

interface Props {
  playing: boolean;
  onToggle: () => void;
  durationMs: number;
}

/**
 * Minimal Swiss IKB play/pause button.
 * Shows a ▶ play icon or ⏸ pause icon with current step duration.
 */
export function PlayButton({ playing, onToggle, durationMs }: Props) {
  return (
    <button
      className="play-btn"
      onClick={onToggle}
      data-no-advance
      title={playing ? "暂停" : "自动播放"}
    >
      <span className="play-btn-icon">
        {playing ? (
          /* Pause — two vertical bars */
          <svg width="16" height="16" viewBox="0 0 16 16">
            <rect x="2" y="2" width="4" height="12" fill="currentColor" />
            <rect x="10" y="2" width="4" height="12" fill="currentColor" />
          </svg>
        ) : (
          /* Play — triangle */
          <svg width="16" height="16" viewBox="0 0 16 16">
            <polygon points="4,2 14,8 4,14" fill="currentColor" />
          </svg>
        )}
      </span>
      <span className="play-btn-label">
        {playing ? "暂停" : "播放"}
      </span>
      {playing && durationMs > 0 && (
        <span className="play-btn-time">
          {(durationMs / 1000).toFixed(1)}s
        </span>
      )}
    </button>
  );
}
