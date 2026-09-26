"""Local transcription with mlx-whisper, writing Scribe-compatible word JSON.

Fallback backend for transcribe.py when Scribe quota is exhausted or
unavailable. Output schema is byte-compatible with what Scribe's
speech-to-text returns for the fields video-use consumes:

  {"text": ..., "language": ..., "words": [
      {"text": "这", "type": "word", "start": 1.2, "end": 1.5, "speaker": "S0"},
      {"text": " ",  "type": "spacing"},
      ...
  ]}

pack_transcripts.py / srt_export.py / edl_preview_build.py only read
entries with type=="word" (text/start/end); the spacing entries keep the
same alternation Scribe produces. No diarization (single speaker S0) and
no audio-event tags — the EDL workflow doesn't consume them.

Runs on Apple Silicon via the Metal MLX runtime; needs the video-use
venv (has mlx_whisper). Cached like Scribe: existing transcript is
never re-computed.

Usage:
    python helpers/mlx_transcribe.py <video> --edit-dir <dir>
    python helpers/mlx_transcribe.py <video> --edit-dir <dir> --language zh
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

MODEL = "mlx-community/whisper-large-v3-turbo"


def extract_audio(video_path: Path, dest: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(video_path),
         "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", "-bitexact", str(dest)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def to_scribe_schema(result: dict, language: str | None) -> dict:
    words: list[dict] = []
    full: list[str] = []
    for seg in result.get("segments") or []:
        for w in seg.get("words") or []:
            text = (w.get("word") or "").strip()
            if not text:
                continue
            if words:
                words.append({"text": " ", "type": "spacing"})
            words.append({
                "text": text,
                "type": "word",
                "start": float(w["start"]),
                "end": float(w["end"]),
                "speaker": "S0",
            })
            full.append(text)
    return {
        "text": "".join(full),
        "language": language or result.get("language") or "",
        "model": MODEL,
        "words": words,
    }


def transcribe_one(video: Path, edit_dir: Path, language: str | None) -> Path:
    transcripts_dir = edit_dir / "transcripts"
    transcripts_dir.mkdir(parents=True, exist_ok=True)
    out_path = transcripts_dir / f"{video.stem}.json"

    if out_path.exists():
        print(f"cached: {out_path.name}")
        return out_path

    import mlx_whisper  # heavy import — only when actually used

    print(f"  [mlx] transcribing {video.name} with {MODEL}", flush=True)
    t0 = time.time()
    with tempfile.TemporaryDirectory() as tmp:
        audio = Path(tmp) / f"{video.stem}.wav"
        extract_audio(video, audio)
        result = mlx_whisper.transcribe(
            str(audio),
            path_or_hf_repo=MODEL,
            language=language,
            word_timestamps=True,  # required: segments carry no word times by default
        )
    payload = to_scribe_schema(result, language)
    out_path.write_text(json.dumps(payload, indent=2))
    dt = time.time() - t0
    print(f"  [mlx] saved: {out_path.name} ({len(payload['words'])} word entries) in {dt:.1f}s")
    return out_path


def main() -> None:
    ap = argparse.ArgumentParser(description="Transcribe with mlx-whisper to Scribe-compatible JSON")
    ap.add_argument("video", type=Path)
    ap.add_argument("--edit-dir", type=Path, required=True)
    ap.add_argument("--language", type=str, default=None)
    args = ap.parse_args()

    video = args.video.resolve()
    if not video.exists():
        sys.exit(f"video not found: {video}")

    try:
        transcribe_one(video, args.edit_dir.resolve(), args.language)
    except ImportError:
        sys.exit(
            "mlx_whisper not installed in this Python. Run it from the video-use venv:\n"
            "  <video-use>/.venv/bin/python helpers/mlx_transcribe.py ..."
        )


if __name__ == "__main__":
    main()
