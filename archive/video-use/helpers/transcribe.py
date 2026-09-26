"""Transcribe a video with ElevenLabs Scribe / 火山方舟 doubao / local mlx-whisper.

Extracts mono 16kHz audio via ffmpeg, uploads to Scribe with verbatim +
diarize + audio events + word-level timestamps, writes the full response
to <edit_dir>/transcripts/<video_stem>.json.

Cached: if the output file already exists, the upload is skipped.

Backend:
  --backend auto   (default) Scribe first; on quota exhaustion or a 401,
                    fall back to 火山方舟 doubao-seed-2.0 (multimodal audio
                    transcription), then to local mlx-whisper.
  --backend scribe Scribe only — fail hard when quota is insufficient.
  --backend ark    Ark only (doubao multimodal). Model via ARK_MODEL env.
  --backend mlx    Local only, never touches the network.

Usage:
    python helpers/transcribe.py <video_path>
    python helpers/transcribe.py <video_path> --edit-dir /custom/edit
    python helpers/transcribe.py <video_path> --language en
    python helpers/transcribe.py <video_path> --num-speakers 2
    python helpers/transcribe.py <video_path> --backend ark
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import requests


SCRIBE_URL = "https://api.elevenlabs.io/v1/speech-to-text"


def load_api_key() -> str:
    for candidate in [Path(__file__).resolve().parent.parent / ".env", Path(".env")]:
        if candidate.exists():
            for line in candidate.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                if k.strip() == "ELEVENLABS_API_KEY":
                    return v.strip().strip('"').strip("'")
    v = os.environ.get("ELEVENLABS_API_KEY", "")
    if not v:
        sys.exit("ELEVENLABS_API_KEY not found in .env or environment")
    return v


def extract_audio(video_path: Path, dest: Path) -> None:
    cmd = [
        "ffmpeg", "-y", "-i", str(video_path),
        "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
        str(dest),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def call_scribe(
    audio_path: Path,
    api_key: str,
    language: str | None = None,
    num_speakers: int | None = None,
) -> dict:
    data: dict[str, str] = {
        "model_id": "scribe_v1",
        "diarize": "true",
        "tag_audio_events": "true",
        "timestamps_granularity": "word",
    }
    if language:
        data["language_code"] = language
    if num_speakers:
        data["num_speakers"] = str(num_speakers)

    with open(audio_path, "rb") as f:
        resp = requests.post(
            SCRIBE_URL,
            headers={"xi-api-key": api_key},
            files={"file": (audio_path.name, f, "audio/wav")},
            data=data,
            timeout=1800,
        )

    if resp.status_code != 200:
        raise RuntimeError(f"Scribe returned {resp.status_code}: {resp.text[:500]}")

    return resp.json()


def check_quota(api_key: str, video: Path) -> tuple[float, float] | None:
    """Return (remaining, needed) credits, or None when unknowable.

    Scribe consumes roughly 1.1 credits per second of audio (measured:
    647 credits for a 582s upload). Quota exhaustion otherwise surfaces as a
    401 only AFTER the whole file is uploaded.
    """
    dur = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(video)],
        capture_output=True, text=True, check=True).stdout.strip())
    needed = dur * 1.1
    try:
        r = requests.get("https://api.elevenlabs.io/v1/user",
                         headers={"xi-api-key": api_key}, timeout=30)
        data = r.json()
        remaining = (data.get("character_count") or {}).get("remaining_character_count")
    except Exception as e:
        # Endpoint/format quirks make this pre-check unreliable — do NOT fail
        # silently; the upload must not look "pre-checked" when it wasn't.
        print(f"  [warn] Scribe quota pre-check unavailable ({e}); "
              f"quota exhaustion will surface as a 401 after upload", flush=True)
        return None
    if remaining is None:
        print("  [warn] Scribe quota pre-check returned no data; "
              "quota exhaustion will surface as a 401 after upload", flush=True)
        return None
    return float(remaining), needed


def mlx_python() -> str:
    """Return a Python that can import mlx_whisper (current, else repo venv)."""
    try:
        import mlx_whisper  # noqa: F401
        return sys.executable
    except ImportError:
        venv = Path(__file__).resolve().parent.parent / ".venv" / "bin" / "python"
        if venv.exists():
            return str(venv)
    sys.exit(
        "mlx_whisper not importable and no <video-use>/.venv found.\n"
        "Run `uv sync --extra mlx` inside the video-use repo (see install.md) "
        "to enable the local fallback.")


def transcribe_mlx(video: Path, edit_dir: Path, language: str | None, verbose: bool) -> Path:
    """Transcribe locally with mlx-whisper (helpers/mlx_transcribe.py)."""
    helper = Path(__file__).resolve().parent / "mlx_transcribe.py"
    cmd = [mlx_python(), str(helper), str(video), "--edit-dir", str(edit_dir)]
    if language:
        cmd += ["--language", language]
    if verbose:
        print(f"  [fallback] local mlx-whisper transcription", flush=True)
    subprocess.run(cmd, check=True)
    return edit_dir / "transcripts" / f"{video.stem}.json"


ARK_RESPONSES_URL = "https://ark.cn-beijing.volces.com/api/v3/responses"
ARK_MODEL_DEFAULT = "doubao-seed-2-0-lite-260428"
ARK_CHUNK_SECONDS = 60.0      # per-request audio length
ARK_CHUNK_STEP = 49.0         # step < chunk ⇒ overlap absorbs boundary artifacts
ARK_CHUNK_HEAD_TRIM = 3.5     # measured: model output degrades ~3s into each chunk head
ARK_CHUNK_TAIL_TRIM = 7.0     # ...and ~5-7s before each chunk tail (deepest degradation)
ARK_CHUNK_WORKERS = 4


def load_ark_key() -> str | None:
    for candidate in [Path(__file__).resolve().parent.parent / ".env", Path(".env")]:
        if candidate.exists():
            for line in candidate.read_text().splitlines():
                line = line.strip()
                if line.startswith("ARK_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    return os.environ.get("ARK_API_KEY", "") or None


def _parse_ark_words(content: str) -> list[dict]:
    """Extract word JSON from model output, tolerating fences and trailing notes."""
    import re
    stripped = content.strip()
    stripped = re.sub(r"^```(?:json)?\s*|\s*```$", "", stripped)
    data = None
    for candidate in (stripped,):
        try:
            data = json.loads(candidate)
            break
        except json.JSONDecodeError:
            pass
    if data is None:
        m = re.search(r"\{.*\}", stripped, re.S)
        if not m:
            raise RuntimeError(f"Ark output contained no JSON: {content[:300]}")
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Ark output JSON unparseable ({e}): {content[:300]}")
    words = []
    for w in data.get("words", []):
        words.append({
            "text": str(w["text"]),
            "type": "word",
            "start": float(w["start"]),
            "end": float(w["end"]),
            "speaker": w.get("speaker", "S0"),
        })
    if not words:
        raise RuntimeError(f"Ark output had no words: {content[:300]}")
    return words


def _ark_chunk(api_key: str, model: str, b64: str, prompt: str, chunk_offset: float,
               verbose: bool, chunk_no: int, n_chunks: int,
               attempts: int = 3) -> list[dict]:
    """One chunked Responses API call; retries transient API/parse failures."""
    last_err: Exception | None = None
    for attempt in range(attempts):
        body = {
            "model": model,
            "input": [{"role": "user", "content": [
                {"type": "input_audio", "audio_url": f"data:audio/wav;base64,{b64}"},
                {"type": "input_text", "text": prompt},
            ]}],
        }
        try:
            resp = requests.post(
                ARK_RESPONSES_URL,
                headers={"Authorization": f"Bearer {api_key}"},
                json=body,
                timeout=420,
            )
            if resp.status_code != 200:
                raise RuntimeError(f"Ark returned {resp.status_code}: {resp.text[:500]}")
            data = resp.json()
            content = ""
            for item in data.get("output", []):
                if item.get("type") == "message":
                    for c in item.get("content", []):
                        if c.get("type") == "output_text":
                            content += c.get("text", "")
            words = _parse_ark_words(content)
            for w in words:
                w["start"] += chunk_offset
                w["end"] += chunk_offset
            if verbose:
                print(f"  [ark] chunk {chunk_no}/{n_chunks}: {len(words)} words", flush=True)
            return words
        except (RuntimeError, requests.RequestException, ValueError) as e:
            last_err = e
            if verbose:
                print(f"  [ark] chunk {chunk_no}/{n_chunks} attempt {attempt + 1} failed "
                      f"({e}) — retrying", flush=True)
    raise RuntimeError(f"Ark chunk {chunk_no} failed after {attempts} attempts: {last_err}")


def transcribe_ark(
    video: Path,
    edit_dir: Path,
    language: str | None,
    num_speakers: int | None,
    verbose: bool,
) -> Path:
    """Transcribe with 火山方舟 doubao-seed-2.0-lite multimodal (Responses API).

    Audio is split into ARK_CHUNK_SECONDS chunks transcribed in parallel
    (ARK_CHUNK_WORKERS) — a single full-length request times out on longer
    videos because word-level JSON output is large. Chunk boundaries may
    mangle a word or two; the editor review pass catches them.
    """
    key = load_ark_key()
    if not key:
        sys.exit("ARK_API_KEY not found in .env or environment (see install.md)")
    model = os.environ.get("ARK_MODEL", ARK_MODEL_DEFAULT)
    prompt = (
        "请逐字转写这段中文音频并给出词级时间戳。要求：\n"
        "1. 完全按说话内容输出，不要改写、不要纠错；\n"
        "2. 保留语气词（啊/呢/吧/哎呀等）、口误、重复；\n"
        "3. 只输出严格的 JSON（不要 markdown 围栏），格式：\n"
        '{"words": [{"text": "词", "start": 秒数, "end": 秒数}]}\n'
        "start/end 为该词在本段音频中的起止秒数（float）。"
    )
    if language:
        prompt += f"\n音频语言：{language}。"
    if num_speakers:
        prompt += f"\n共 {num_speakers} 位说话人，每个词加 speaker 字段（S0/S1…）。"

    with tempfile.TemporaryDirectory() as tmp:
        audio = Path(tmp) / f"{video.stem}.wav"
        extract_audio(video, audio)
        duration = float(subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(audio)],
            capture_output=True, text=True, check=True).stdout.strip())
        import concurrent.futures as cf
        n_chunks = max(1, int(duration / ARK_CHUNK_STEP) + 1)
        if verbose:
            print(f"  [ark] {model} ({duration:.0f}s audio → {n_chunks} chunks x "
                  f"{ARK_CHUNK_WORKERS} workers, head {ARK_CHUNK_HEAD_TRIM}s / "
                  f"tail {ARK_CHUNK_TAIL_TRIM}s trim)", flush=True)
        jobs = []
        for i in range(n_chunks):
            t0 = i * ARK_CHUNK_STEP
            t1 = min(t0 + ARK_CHUNK_SECONDS, duration)
            chunk = Path(tmp) / f"{video.stem}_c{i}.wav"
            subprocess.run(
                ["ffmpeg", "-y", "-v", "error", "-ss", f"{t0:.3f}",
                 "-t", f"{t1 - t0:.3f}", "-i", str(audio), "-c:a", "pcm_s16le",
                 str(chunk)],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            b64 = base64.b64encode(chunk.read_bytes()).decode()
            jobs.append((i, b64, t0, t1))
        all_words = []
        with cf.ThreadPoolExecutor(max_workers=ARK_CHUNK_WORKERS) as ex:
            futs = [ex.submit(_ark_chunk, key, model, b64, prompt, t0,
                              verbose, i + 1, n_chunks) for i, b64, t0, t1 in jobs]
            for f in cf.as_completed(futs):
                all_words.extend(f.result())
        # overlap + edge trim: model output degrades near each chunk's edges
        # (measured ~1.5s head / ~3s tail); drop those zones and let the
        # neighboring chunk cover them (first chunk keeps its head, last its tail)
        kept = []
        for i, b64, t0, t1 in jobs:
            lo = t0 if i == 0 else t0 + ARK_CHUNK_HEAD_TRIM
            hi = t1 if i == n_chunks - 1 else t1 - ARK_CHUNK_TAIL_TRIM
            kept.extend(w for w in all_words
                        if t0 <= w["start"] < t1 and lo <= w["start"] < hi)
        kept.sort(key=lambda w: w["start"])
        deduped = []
        for w in kept:
            # overlap sliver: the same audio can be transcribed twice with
            # near-identical timings — drop the second copy
            if deduped and w["start"] < deduped[-1]["end"] - 0.05:
                continue
            deduped.append(w)
        kept = deduped

    payload = {
        "text": "".join(w["text"] for w in kept),
        "language": language or "zh",
        "model": model,
        "words": kept,
    }
    out_path = edit_dir / "transcripts" / f"{video.stem}.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    if verbose:
        print(f"  saved: {out_path.name} ({len(all_words)} words)")
    return out_path


def transcribe_one(
    video: Path,
    edit_dir: Path,
    api_key: str,
    language: str | None = None,
    num_speakers: int | None = None,
    verbose: bool = True,
    backend: str = "auto",
) -> Path:
    """Transcribe a single video. Returns path to transcript JSON.

    Cached: returns existing path immediately if the transcript already exists.
    backend: auto | scribe | ark | mlx — auto chains Scribe → Ark → local mlx,
    falling through when quota is insufficient, Scribe 401s, or Ark fails.
    """
    transcripts_dir = edit_dir / "transcripts"
    transcripts_dir.mkdir(parents=True, exist_ok=True)
    out_path = transcripts_dir / f"{video.stem}.json"

    if out_path.exists():
        if verbose:
            print(f"cached: {out_path.name}")
        return out_path

    if backend == "mlx":
        return transcribe_mlx(video, edit_dir, language, verbose)
    if backend == "ark":
        return transcribe_ark(video, edit_dir, language, num_speakers, verbose)

    def _ark_or_mlx(reason: str):
        """auto chain: Scribe failed → Ark → mlx (both may be unavailable)."""
        print(f"  {reason} — falling back to Ark (doubao-seed-2.0-lite)", flush=True)
        try:
            return transcribe_ark(video, edit_dir, language, num_speakers, verbose)
        except RuntimeError as ark_err:
            print(f"  Ark failed too ({ark_err}) — falling back to local mlx-whisper",
                  flush=True)
            return transcribe_mlx(video, edit_dir, language, verbose)

    quota = check_quota(api_key, video)
    if quota is not None:
        remaining, needed = quota
        if remaining < needed:
            if backend == "auto":
                return _ark_or_mlx(
                    f"Scribe quota insufficient ({remaining:.0f} credits left, "
                    f"~{needed:.0f} needed)")
            sys.exit(
                f"Scribe quota insufficient: {remaining:.0f} credits left, "
                f"~{needed:.0f} needed for {video.name} — use --backend ark/mlx to "
                "transcribe with another backend instead")

    if verbose:
        print(f"  extracting audio from {video.name}", flush=True)

    t0 = time.time()
    with tempfile.TemporaryDirectory() as tmp:
        audio = Path(tmp) / f"{video.stem}.wav"
        extract_audio(video, audio)
        size_mb = audio.stat().st_size / (1024 * 1024)
        if verbose:
            print(f"  uploading {video.stem}.wav ({size_mb:.1f} MB)", flush=True)
        try:
            payload = call_scribe(audio, api_key, language, num_speakers)
        except RuntimeError as e:
            if "401" in str(e) and backend == "auto":
                return _ark_or_mlx(f"Scribe rejected the upload ({e})")
            raise

    out_path.write_text(json.dumps(payload, indent=2))
    dt = time.time() - t0

    if verbose:
        kb = out_path.stat().st_size / 1024
        print(f"  saved: {out_path.name} ({kb:.1f} KB) in {dt:.1f}s")
        if isinstance(payload, dict) and "words" in payload:
            print(f"    words: {len(payload['words'])}")

    return out_path


def main() -> None:
    ap = argparse.ArgumentParser(description="Transcribe a video with ElevenLabs Scribe")
    ap.add_argument("video", type=Path, help="Path to video file")
    ap.add_argument(
        "--edit-dir",
        type=Path,
        default=None,
        help="Edit output directory (default: <video_parent>/edit)",
    )
    ap.add_argument(
        "--language",
        type=str,
        default=None,
        help="Optional ISO language code (e.g., 'en'). Omit to auto-detect.",
    )
    ap.add_argument(
        "--num-speakers",
        type=int,
        default=None,
        help="Optional number of speakers when known. Improves diarization accuracy.",
    )
    ap.add_argument(
        "--backend",
        choices=["auto", "scribe", "ark", "mlx"],
        default="auto",
        help="Transcription backend: auto (Scribe → Ark → local mlx), scribe, ark, mlx",
    )
    args = ap.parse_args()

    video = args.video.resolve()
    if not video.exists():
        sys.exit(f"video not found: {video}")

    edit_dir = (args.edit_dir or (video.parent / "edit")).resolve()
    api_key = load_api_key()

    transcribe_one(
        video=video,
        edit_dir=edit_dir,
        api_key=api_key,
        language=args.language,
        num_speakers=args.num_speakers,
        backend=args.backend,
    )


if __name__ == "__main__":
    main()
