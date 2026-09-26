#!/usr/bin/env python3
"""Transcribe a video with 豆包流式语音识别 2.0 (SeedASR SAUC) — the correct
backend for word-level transcription.

Why: doubao-seed-2.0-lite (the generic LLM used by `--backend ark`) is NOT an
ASR — it garbles fast speech, drifts word timestamps ±0.5-2s, and hallucinates
words in silent spans. SeedASR 2.0 streaming (`volc.seedasr.sauc.duration`)
returns clean per-word millisecond timestamps, no garble, no hallucination.

Usage:
  uv run python helpers/transcribe_seedasr.py <video> --edit-dir <edit_dir>

Requirements:
  - Node.js 22+ and the `ws` npm package (npm install ws) in the video-use repo
    (or anywhere node can resolve it).
  - Credentials in <repo>/.env (speech console, old-style):
      DOUBAO_APP_ID=8796768107
      DOUBAO_ACCESS_TOKEN=...
    (Secret Key not needed for streaming.)

Writes <edit_dir>/transcripts/<name>.json in the Scribe-compatible word format
({text,type,start,end,speaker}), cached per source (no re-transcription unless
the source file itself changes).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    video = Path(sys.argv[1]).resolve()
    edit_dir = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else video.parent / "edit"
    # support --edit-dir flag too
    for i, a in enumerate(sys.argv):
        if a == "--edit-dir" and i + 1 < len(sys.argv):
            edit_dir = Path(sys.argv[i + 1]).resolve()

    trans_dir = edit_dir / "transcripts"
    trans_dir.mkdir(parents=True, exist_ok=True)
    out_json = trans_dir / f"{video.stem}.json"
    if out_json.exists():
        print(f"cached: {out_json}", flush=True)
        return 0

    # 1) extract 16k mono PCM
    wav = trans_dir / f"{video.stem}_16k.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(video), "-vn",
         "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", "-f", "wav", str(wav)],
        check=True,
    )

    # 2) call the Node SeedASR streaming transcriber
    node_script = Path(__file__).resolve().parent / "doubao_asr_file.js"
    repo = Path(__file__).resolve().parent.parent
    env = dict(__import__("os").environ)
    # load credentials from <repo>/.env if present
    env_file = repo / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                env.setdefault(k.strip(), v.strip())
    subprocess.run(
        ["node", str(node_script), str(wav), str(out_json), "0"],
        check=True, env=env, cwd=str(repo),
    )

    # 3) cleanup temp wav
    wav.unlink(missing_ok=True)
    print(f"saved: {out_json}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
