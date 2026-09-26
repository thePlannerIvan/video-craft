import "./RecordingPlaceholder.css";

interface Props {
  label: string;
}

/**
 * Minimal placeholder for chapters that have pre-recorded screen footage.
 * Shows a subtle indicator on a dark surface — the recording fills this time slot.
 */
export function RecordingPlaceholder({ label }: Props) {
  return (
    <div className="rp-scene">
      <div className="rp-card">
        <span className="rp-icon">📹</span>
        <span className="rp-label">{label}</span>
        <span className="rp-hint">录屏素材 · 后期合成</span>
      </div>
    </div>
  );
}
