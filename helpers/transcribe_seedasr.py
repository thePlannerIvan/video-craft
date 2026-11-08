#!/usr/bin/env python3
"""Transcribe a video with 豆包流式语音识别 2.0 (SeedASR SAUC) — the correct
backend for word-level transcription, and the **primary** transcription entry.

Why: doubao-seed-2.0-lite (the generic LLM used by `--backend ark`, and the Ark
leg of `transcribe.py --backend auto`) is NOT an ASR — it garbles fast speech,
drifts word timestamps ±0.5-2s, and hallucinates words in silent spans.
SeedASR 2.0 streaming (`volc.seedasr.sauc.duration`) returns clean per-word
millisecond timestamps, no garble, no hallucination. `transcribe.py --backend
auto` (Scribe→Ark→mlx) is the historical fallback for when no 豆包 speech-console
credentials exist; the Ark leg it can reach is exactly the path GOTCHAS #1 bans.

Usage:
  python3 helpers/transcribe_seedasr.py <video> --edit-dir <edit_dir>
  python3 helpers/transcribe_seedasr.py <video> <edit_dir>    # 位置参数（旧调用）

Requirements:
  - Node.js 22+ and the `ws` npm package (npm install ws) in the video-use repo
    (or anywhere node can resolve it).
  - Credentials of your own in <repo>/.env (speech console, old-style):
      DOUBAO_APP_ID=<your speech-console AppID>
      DOUBAO_ACCESS_TOKEN=<your speech-console access token>
    Secret Key is not needed for streaming. This repository ships no
    credentials — see install.md step 5.

Writes <edit_dir>/transcripts/<name>.json in the Scribe-compatible word format
({text,type,start,end,speaker}), cached per source (no re-transcription unless
the source file itself changes).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="transcribe_seedasr.py",
        description="豆包流式语音识别 2.0（SeedASR SAUC）词级转写 —— 首选转写入口。",
        epilog="无豆包凭据时才用 transcribe.py --backend auto 历史回退（会走 Ark，见 GOTCHAS #1）。",
    )
    ap.add_argument("video", type=Path, help="源视频/音频（ffmpeg 可读）")
    ap.add_argument("edit_dir", nargs="?", type=Path, default=None,
                    help="剪辑目录，默认 <video 所在目录>/edit")
    ap.add_argument("--edit-dir", dest="edit_dir_flag", type=Path, default=None,
                    help="同位置参数；显式给时优先（保持旧调用方式兼容）")
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    video = Path(args.video).expanduser().resolve()
    chosen = args.edit_dir_flag if args.edit_dir_flag is not None else args.edit_dir
    edit_dir = (Path(chosen).expanduser().resolve() if chosen is not None
                else video.parent / "edit")

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
         "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", "-f", "wav", "-bitexact", str(wav)],
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
