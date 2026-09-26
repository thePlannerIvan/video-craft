"""Render a video from an EDL.

Implements the HEURISTICS render pipeline in the correct order:

  1. Per-segment extract with color grade + 10ms audio fades baked in.
     Audio is encoded as PCM per segment and padded to the MEASURED video
     track duration (apad=whole_dur) — per-segment AAC re-encoding drifts:
     AAC frames (1024 samples) don't align with the frame grid, so each
     segment's video track rounds up 0-33ms while the audio doesn't, and the
     drift accumulates ~0.8s over 47 segments. PCM + pad keeps both tracks
     ending together; the final AAC encode happens once after the concat.
  2. Lossless -c copy concat into base.mp4, guarded by an expected-duration
     check (a torn segment file makes concat silently skip it and exit 0).
  3. If overlays or subtitles: single filter graph that overlays animations
     (with PTS shift so frame 0 lands at the overlay window start)
     and applies `subtitles` filter LAST → final.mp4

Optionally builds a master SRT from the per-source transcripts + EDL
output-timeline offsets, applies the proven force_style (2-word
UPPERCASE chunks, Helvetica 18 Bold, MarginV=90 — a platform safe-zone value,
see SUB_FORCE_STYLE below).

Timeline contract: this renderer reports each segment's MEASURED duration into
`segment_durations.json` together with the sha256 of the EDL it rendered. That
file is the authoritative source for caption offsets — never assume the
rendered timeline equals the EDL's nominal total.

Usage:
    python helpers/render.py <edl.json> -o final.mp4
    python helpers/render.py <edl.json> -o preview.mp4 --preview
    python helpers/render.py <edl.json> -o final.mp4 --build-subtitles
    python helpers/render.py <edl.json> -o final.mp4 --no-subtitles
    python helpers/render.py <edl.json> -o final.mp4 --no-cache
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
import sys
from pathlib import Path

try:
    from grade import get_preset, auto_grade_for_clip  # same directory
except Exception:
    def get_preset(name: str) -> str:
        return ""

    def auto_grade_for_clip(video, start=0.0, duration=None, verbose=False):  # type: ignore
        return "eq=contrast=1.03:saturation=0.98", {}

from screen_detect import is_screen_content  # same directory
from _edl import edl_digest  # same directory


# -------- Subtitle style (bold-overlay, proven at 1920×1080 and 1080×1920) --
#
# MarginV is NOT taste — it is a platform safe-zone rule.
# TikTok / IG Reels / Shorts UI (caption, username, music, right-rail actions)
# covers roughly the bottom ~25–30% of a 1080×1920 frame. Captions placed near
# the bottom edge get clipped or obscured by the UI. libass auto-scales the
# render canvas relative to PlayResY=288, so MarginV=90 lands the caption
# baseline roughly 30% up from the bottom on any aspect — clear of the UI on
# every major vertical-video platform. Do not drop this below ~75 without a
# specific reason.
SUB_FORCE_STYLE = (
    "FontName=Helvetica,FontSize=18,Bold=1,"
    "PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BackColour=&H00000000,"
    "BorderStyle=1,Outline=2,Shadow=0,"
    "Alignment=2,MarginV=90"
)

# -------- Helpers ------------------------------------------------------------


def run(cmd: list[str], quiet: bool = False) -> None:
    if not quiet:
        print(f"  $ {' '.join(str(c) for c in cmd[:6])}{' …' if len(cmd) > 6 else ''}")
    subprocess.run(cmd, check=True)


def resolve_grade_filter(grade_field: str | None) -> str:
    """The EDL's 'grade' field can be a preset name, a raw ffmpeg filter, or 'auto'.

    Returns the filter string to embed into the per-segment -vf chain.
    For 'auto', returns the sentinel "__AUTO__" which is resolved per-segment.
    """
    if not grade_field:
        return ""
    if grade_field == "auto":
        return "__AUTO__"
    # Preset names are short identifiers, filter strings contain '=' or ','.
    if re.fullmatch(r"[a-zA-Z0-9_\-]+", grade_field):
        try:
            return get_preset(grade_field)
        except KeyError:
            print(f"warning: unknown preset '{grade_field}', using as raw filter")
            return grade_field
    return grade_field


def resolve_path(maybe_path: str, base: Path) -> Path:
    """Resolve a path that may be absolute or relative to `base`."""
    p = Path(maybe_path)
    if p.is_absolute():
        return p
    return (base / p).resolve()


# -------- HDR → SDR tone mapping (HLG / PQ sources) --------------------------
#
# iPhone defaults to HLG HDR in Rec.2020 (and many mirrorless cameras ship PQ).
# If the source is HDR and we only downconvert bit depth (yuv420p10le → yuv420p)
# without tone-mapping, the output is 8-bit but still carries HLG/PQ transfer
# metadata. Players that honor the metadata (screen recorders, most social
# upload re-encodes) interpret 8-bit values in an HDR container and the result
# looks oversaturated / blown out. QuickTime on macOS can hide this locally —
# screen recording and uploaded renders cannot.
#
# Fix: detect HDR via color_transfer and prepend a zscale+tonemap chain to the
# vf graph so the output is clean Rec.709 SDR.

HDR_TRANSFERS = {"smpte2084", "arib-std-b67"}  # PQ (HDR10) and HLG

TONEMAP_CHAIN = (
    "zscale=t=linear:npl=100,"
    "format=gbrpf32le,"
    "zscale=p=bt709,"
    "tonemap=tonemap=hable:desat=0,"
    "zscale=t=bt709:m=bt709:r=tv,"
    "format=yuv420p"
)


def is_hdr_source(video: Path) -> bool:
    """Return True if the source uses a PQ or HLG transfer function."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=color_transfer",
             "-of", "default=noprint_wrappers=1:nokey=1", str(video)],
            capture_output=True, text=True, check=True,
        )
        return out.stdout.strip() in HDR_TRANSFERS
    except subprocess.CalledProcessError:
        return False


def is_portrait_source(video: Path) -> bool:
    """Return True if the video displays portrait (vertical), honoring rotation metadata."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height,rotation",
             "-show_entries", "stream_side_data=rotation",
             "-of", "json", str(video)],
            capture_output=True, text=True, check=True,
        )
        info = json.loads(out.stdout)
        st = info["streams"][0]
        w, h = st.get("width", 0), st.get("height", 0)
        rot = st.get("rotation")
        if rot is None:
            rot = st.get("side_data_list", [{}])[0].get("rotation", 0)
        if rot in (90, 270):
            return w > h  # rotated: displayed orientation swaps axes
        return h > w
    except Exception:
        return False


def detect_fps(video: Path) -> float:
    """Best-effort average frame rate of a video's first stream."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=avg_frame_rate",
             "-of", "csv=p=0", str(video)],
            capture_output=True, text=True, check=True,
        )
        num, den = map(float, out.stdout.strip().split("/"))
        return round(num / den, 3) if den else 30.0
    except Exception:
        return 30.0


# -------- Per-segment extraction (Rule 2 + Rule 3) --------------------------


def probe_stream_duration(path: Path, stream: str) -> float:
    """ffprobe a stream's duration in seconds (raises on failure)."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", stream,
         "-show_entries", "stream=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True).stdout.strip()
    return float(out)


def extract_segment(
    source: Path,
    seg_start: float,
    duration: float,
    grade_filter: str,
    out_path: Path,
    preview: bool = False,
    draft: bool = False,
    fps: float | None = None,
) -> float:
    """Extract a cut range as its own MP4 with grade + 30ms audio fades baked in.

    `-ss` before `-i` for fast accurate seeking. Scale to 1080p from 4K.
    Portrait sources (height > width) are scaled by height to preserve orientation.

    Quality ladder:
      - final (default): 1080p libx264 fast CRF 20
                         → screen/UI footage auto-detected: fast CRF 16
                           + `-tune stillimage` (keeps small text crisp)
      - preview:         1080p libx264 medium CRF 22 (evaluable for QC)
      - draft:           720p libx264 ultrafast CRF 28 (cut-point check only)

    Returns the MEASURED video track duration (vt) — audio is padded to it so
    both tracks always end together (see module docstring).
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Ask for the smallest whole-frame duration that still covers the range.
    # It must survive being written as `-t f"{tv:.3f}"`: k/30 for k ≡ 2 (mod 3)
    # rounds UP at the third decimal (176/30 = 5.8667 → "5.867" → 176.01
    # frames → the encoder emits 177 and the timeline grows by one frame per
    # such segment). Flooring to milliseconds keeps the written value inside
    # the intended frame count. Residual sub-frame differences are absorbed by
    # the measured timeline in segment_durations.json, never guessed.
    grid = float(fps or 30.0)
    tv = math.floor(math.ceil(duration * grid) / grid * 1000) / 1000

    portrait = is_portrait_source(source)
    if draft:
        scale = "scale=-2:1280" if portrait else "scale=1280:-2"
    else:
        scale = "scale=-2:1920" if portrait else "scale=1920:-2"

    vf_parts: list[str] = []
    if is_hdr_source(source):
        vf_parts.append(TONEMAP_CHAIN)
    vf_parts.append(scale)
    if grade_filter:
        vf_parts.append(grade_filter)
    vf = ",".join(vf_parts)

    # 10ms audio fades at both edges (Rule 3) — prevent pops. 10ms is the
    # user-tuned value: 30ms measurably swallowed the last word of a cut.
    fade_out_start = max(0.0, duration - 0.01)
    af = f"afade=t=in:st=0:d=0.01,afade=t=out:st={fade_out_start:.3f}:d=0.01"

    if draft:
        preset, crf, tune = "ultrafast", "28", None
    elif preview:
        preset, crf, tune = "medium", "22", None
    elif is_screen_content(source):
        # Screen recordings (fine text/UI) need stillimage tuning — generic
        # x264 rate control blurs small text even at moderate CRF.
        preset, crf, tune = "fast", "16", "stillimage"
        print(f"  screen content detected: stillimage, CRF 16 → {out_path.name}")
    else:
        preset, crf, tune = "fast", "20", None

    enc_args = ["-c:v", "libx264", "-preset", preset, "-crf", crf]
    if tune:
        enc_args += ["-tune", tune]

    fps_args = ["-r", str(fps)] if fps else []
    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{seg_start:.3f}",
        "-i", str(source),
        "-t", f"{tv:.3f}",
        "-vf", vf,
        "-af", af,
        *enc_args,
        "-pix_fmt", "yuv420p",
        *fps_args,
        # PCM per segment: AAC re-encode per segment makes audio tracks land
        # off the video frame grid and the error accumulates through the concat
        "-c:a", "pcm_s16le",
        str(out_path),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    vt = probe_stream_duration(out_path, "v:0")
    if abs(vt - tv) > 0.001:
        # Video ended on a frame boundary past tv (tv + 1/fps); pad the PCM
        # audio to exactly the measured video track so tracks end together.
        fixed = out_path.with_name(out_path.stem + "_pad.mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-i", str(out_path),
             "-c:v", "copy", "-af", f"apad=whole_dur={vt:.6f}",
             "-c:a", "pcm_s16le", str(fixed)],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        fixed.replace(out_path)
    return vt


def segment_cache_key(source: Path, start: float, duration: float,
                      grade_filter: str, preview: bool, draft: bool,
                      fps: float | None) -> str:
    """Content key for one cached segment.

    The cache used to be validated by duration alone, so an EDL, grade, style or
    source change could silently reuse a segment holding different content.
    Everything that changes the pixels or the samples is part of the key,
    including the source file's size and mtime (a re-recorded source keeps the
    same path).
    """
    try:
        st = source.stat()
        src_sig = f"{source.resolve()}:{st.st_size}:{int(st.st_mtime)}"
    except OSError:
        src_sig = str(source)
    payload = f"{src_sig}|{start:.3f}|{duration:.3f}|{grade_filter}|{preview}|{draft}|{fps}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def extract_all_segments(
    edl: dict,
    edit_dir: Path,
    preview: bool,
    draft: bool = False,
    fps: float | None = None,
    clips_tag: str = "base",
    use_cache: bool = True,
    edl_path: Path | None = None,
) -> tuple[list[Path], list[float]]:
    """Extract every EDL range into edit_dir/clips_<tag>/seg_NN.mp4.

    Returns (ordered segment paths, MEASURED per-segment video durations) —
    the durations drive the concat guard and, through
    segment_durations.json, the caption timeline.

    A cached segment is reused only when its CONTENT KEY matches
    (source identity + range + grade + quality mode + fps); the key lives in
    clips_<tag>/manifest.json. Duration-only reuse is what let a stale segment
    render wrong content after an EDL change, so it is no longer the check.
    """
    resolved = resolve_grade_filter(edl.get("grade"))
    is_auto = resolved == "__AUTO__"
    clips_dir = edit_dir / f"clips_{clips_tag}"
    clips_dir.mkdir(parents=True, exist_ok=True)

    ranges = edl["ranges"]
    sources = edl["sources"]

    manifest_path = clips_dir / "manifest.json"
    cache_manifest: dict[str, str] = {}
    if manifest_path.exists():
        try:
            cache_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            cache_manifest = {}

    seg_paths: list[Path] = []
    vts: list[float] = []
    print(f"extracting {len(ranges)} segment(s) → {clips_dir.name}/")
    if is_auto:
        print("  (auto-grade per segment: analyzing each range)")
    for i, r in enumerate(ranges):
        src_name = r["source"]
        src_path = resolve_path(sources[src_name], edit_dir)
        start = float(r["start"])
        end = float(r["end"])
        duration = end - start
        grid = float(fps or 30.0)
        tv = math.floor(math.ceil(duration * grid) / grid * 1000) / 1000
        out_path = clips_dir / f"seg_{i:02d}_{src_name}.mp4"

        seg_filter = ""
        if is_auto:
            seg_filter, _stats = auto_grade_for_clip(src_path, start=start, duration=duration, verbose=False)
        else:
            seg_filter = resolved
        key = segment_cache_key(src_path, start, duration, seg_filter or "", preview, draft, fps)

        if use_cache and out_path.exists() and cache_manifest.get(out_path.name) == key:
            try:
                pv = probe_stream_duration(out_path, "v:0")
                pa = probe_stream_duration(out_path, "a:0")
                if abs(pa - pv) < 0.005:
                    seg_paths.append(out_path)
                    vts.append(pv)
                    continue
            except (subprocess.CalledProcessError, ValueError):
                pass  # torn/corrupt segment — re-extract

        note = r.get("beat") or r.get("note") or ""
        print(f"  [{i:02d}] {src_name}  {start:7.2f}-{end:7.2f}  ({duration:5.2f}s)  {note}")
        if is_auto:
            print(f"        grade: {seg_filter or '(none)'}")
        vt = extract_segment(src_path, start, duration, seg_filter, out_path, preview=preview, draft=draft, fps=fps)
        cache_manifest[out_path.name] = key
        seg_paths.append(out_path)
        vts.append(vt)

    (clips_dir / "manifest.json").write_text(
        json.dumps(cache_manifest, ensure_ascii=False, indent=1), encoding="utf-8")

    # Measured per-segment durations, bound to the EDL that produced them.
    # Caption offsets must come from here — the nominal Σ(end-start) is not what
    # the encoder emitted (frame-grid rounding is only known post-hoc), and
    # building an SRT on the nominal total desynchronises it by up to a second.
    dur_file = edit_dir / "segment_durations.json"
    blob = {}
    if dur_file.exists():
        try:
            blob = json.loads(dur_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            blob = {}
    blob[clips_tag] = {
        "durations": [round(v, 6) for v in vts],
        "total_s": round(sum(vts), 6),
        "edl_sha256": edl_digest(edl_path) if edl_path else None,
        "fps": grid,
    }
    dur_file.write_text(json.dumps(blob, ensure_ascii=False, indent=1), encoding="utf-8")

    return seg_paths, vts


# -------- Lossless concat ----------------------------------------------------


def concat_segments(segment_paths: list[Path], out_path: Path, edit_dir: Path,
                    expected_duration: float) -> None:
    """Lossless concat via the concat demuxer, then a single final AAC encode.

    The expected-duration guard catches silent concat corruption: a torn
    segment file (e.g. from a concurrent render writing the same clips dir)
    makes ffmpeg skip it and exit 0 — the duration check catches the loss.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    concat_list = edit_dir / f"_concat_{out_path.stem}.txt"
    concat_list.write_text("".join(f"file '{p.resolve()}'\n" for p in segment_paths))

    raw = out_path.with_name(out_path.stem + "_raw.mp4")
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(concat_list),
        "-c", "copy",
        str(raw),
    ]
    print(f"concat → {out_path.name}")
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    got = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(raw)],
        capture_output=True, text=True, check=True).stdout.strip())
    if abs(got - expected_duration) > 0.5:
        raise SystemExit(
            f"concat duration mismatch: expected {expected_duration:.2f}s, got {got:.2f}s — "
            "a segment file was likely corrupted (concurrent renders sharing the clips dir?); "
            "delete the clips dir and re-render without concurrent runs")

    # Single AAC encode for the whole timeline (per-segment AAC would re-encode
    # and drift; the segments are PCM and already padded to the video grid)
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(raw),
         "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
         "-movflags", "+faststart", str(out_path)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    raw.unlink(missing_ok=True)
    concat_list.unlink(missing_ok=True)


# -------- Master SRT (Rule 5) ------------------------------------------------


PUNCT_BREAK = set(".,!?;:")


def _srt_timestamp(seconds: float) -> str:
    total_ms = int(round(seconds * 1000))
    h, rem = divmod(total_ms, 3600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _words_in_range(transcript: dict, t_start: float, t_end: float) -> list[dict]:
    out: list[dict] = []
    for w in transcript.get("words", []):
        if w.get("type") != "word":
            continue
        ws = w.get("start")
        we = w.get("end")
        if ws is None or we is None:
            continue
        if we <= t_start or ws >= t_end:
            continue
        out.append(w)
    return out


def build_master_srt(edl: dict, edit_dir: Path, out_path: Path) -> None:
    """Build an output-timeline SRT from per-source transcripts.

    - 2-word chunks (break on any punctuation in between)
    - UPPERCASE text
    - Output times computed as word.start - segment_start + segment_offset
    """
    transcripts_dir = edit_dir / "transcripts"
    sources = edl["sources"]

    entries: list[tuple[float, float, str]] = []
    seg_offset = 0.0

    for r in edl["ranges"]:
        src_name = r["source"]
        seg_start = float(r["start"])
        seg_end = float(r["end"])
        seg_duration = seg_end - seg_start

        tr_path = transcripts_dir / f"{src_name}.json"
        if not tr_path.exists():
            print(f"  no transcript for {src_name}, skipping captions for this segment")
            seg_offset += seg_duration
            continue

        transcript = json.loads(tr_path.read_text())
        words_in_seg = _words_in_range(transcript, seg_start, seg_end)

        # Group into 2-word chunks, break on punctuation
        chunks: list[list[dict]] = []
        current: list[dict] = []
        for w in words_in_seg:
            text = (w.get("text") or "").strip()
            if not text:
                continue
            current.append(w)
            # Break if the current text ends in punctuation or we hit 2 words
            ends_in_punct = bool(text) and text[-1] in PUNCT_BREAK
            if len(current) >= 2 or ends_in_punct:
                chunks.append(current)
                current = []
        if current:
            chunks.append(current)

        for chunk in chunks:
            local_start = max(seg_start, chunk[0].get("start", seg_start))
            local_end = min(seg_end, chunk[-1].get("end", seg_end))
            out_start = max(0.0, local_start - seg_start) + seg_offset
            out_end = max(0.0, local_end - seg_start) + seg_offset
            if out_end <= out_start:
                out_end = out_start + 0.4
            text = " ".join((w.get("text") or "").strip() for w in chunk)
            text = re.sub(r"\s+", " ", text).strip()
            # Strip trailing punctuation for cleaner uppercase look
            text = text.rstrip(",;:")
            text = text.upper()
            entries.append((out_start, out_end, text))

        seg_offset += seg_duration

    # Sort and write as SRT
    entries.sort(key=lambda e: e[0])
    lines: list[str] = []
    for i, (a, b, t) in enumerate(entries, start=1):
        lines.append(str(i))
        lines.append(f"{_srt_timestamp(a)} --> {_srt_timestamp(b)}")
        lines.append(t)
        lines.append("")
    out_path.write_text("\n".join(lines))
    print(f"master SRT → {out_path.name} ({len(entries)} cues)")


# -------- Loudness normalization (social-ready audio) -----------------------


# Social-media standard: -14 LUFS integrated, -1 dBTP peak, LRA 11 LU.
# Matches YouTube / Instagram / TikTok / X / LinkedIn normalization targets.
LOUDNORM_I = -14.0
LOUDNORM_TP = -1.0
LOUDNORM_LRA = 11.0


def measure_loudness(video_path: Path) -> dict[str, str] | None:
    """Run ffmpeg loudnorm first pass and parse the JSON measurement.

    Returns a dict with measured_i, measured_tp, measured_lra, measured_thresh,
    target_offset, or None if measurement failed.
    """
    filter_str = (
        f"loudnorm=I={LOUDNORM_I}:TP={LOUDNORM_TP}:LRA={LOUDNORM_LRA}:print_format=json"
    )
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-nostats",
        "-i", str(video_path),
        "-af", filter_str,
        "-vn", "-f", "null", "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    # loudnorm prints the JSON to stderr at the end of the run
    stderr = proc.stderr

    # Find the JSON block — loudnorm output contains a `{ ... }` block
    start = stderr.rfind("{")
    end = stderr.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        data = json.loads(stderr[start : end + 1])
    except json.JSONDecodeError:
        return None
    needed = {"input_i", "input_tp", "input_lra", "input_thresh", "target_offset"}
    if not needed.issubset(data.keys()):
        return None
    return data


def apply_loudnorm_two_pass(
    input_path: Path,
    output_path: Path,
    preview: bool = False,
) -> bool:
    """Run two-pass loudnorm on input_path, write normalized copy to output_path.

    Returns True on success, False if measurement failed (caller should fall
    back to copying the input unchanged).

    In preview mode, skips the measurement pass and uses a one-pass approximation
    for speed. Final mode always does the proper two-pass.
    """
    if preview:
        # One-pass approximation — faster, slightly less accurate.
        filter_str = f"loudnorm=I={LOUDNORM_I}:TP={LOUDNORM_TP}:LRA={LOUDNORM_LRA}"
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-nostats",
            "-i", str(input_path),
            "-c:v", "copy",
            "-af", filter_str,
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-movflags", "+faststart",
            str(output_path),
        ]
        print(f"  loudnorm (1-pass preview) → {output_path.name}")
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        return True

    # Full two-pass
    print(f"  loudnorm pass 1: measuring {input_path.name}")
    measurement = measure_loudness(input_path)
    if measurement is None:
        print("  loudnorm measurement failed — falling back to 1-pass")
        return apply_loudnorm_two_pass(input_path, output_path, preview=True)

    print(f"    measured: I={measurement['input_i']} LUFS  "
          f"TP={measurement['input_tp']}  LRA={measurement['input_lra']}")

    filter_str = (
        f"loudnorm=I={LOUDNORM_I}:TP={LOUDNORM_TP}:LRA={LOUDNORM_LRA}"
        f":measured_I={measurement['input_i']}"
        f":measured_TP={measurement['input_tp']}"
        f":measured_LRA={measurement['input_lra']}"
        f":measured_thresh={measurement['input_thresh']}"
        f":offset={measurement['target_offset']}"
        f":linear=true"
    )
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-nostats",
        "-i", str(input_path),
        "-c:v", "copy",
        "-af", filter_str,
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-movflags", "+faststart",
        str(output_path),
    ]
    print(f"  loudnorm pass 2: normalizing → {output_path.name}")
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    return True


# -------- Final compositing (Rule 1 + Rule 4) -------------------------------


def build_final_composite(
    base_path: Path,
    overlays: list[dict],
    subtitles_path: Path | None,
    out_path: Path,
    edit_dir: Path,
    subtitle_style: str = SUB_FORCE_STYLE,
) -> None:
    """Final pass: base → overlays (PTS-shifted) → subtitles LAST → out.

    If there are no overlays and no subtitles, just copy base to out.
    `subtitle_style` comes from the EDL's optional `subtitle_style` field;
    defaults to the shipped bold-overlay style.
    """
    has_overlays = bool(overlays)
    has_subs = subtitles_path is not None and subtitles_path.exists()

    if not has_overlays and not has_subs:
        # Nothing to do — just rename/copy base to final name
        run(["ffmpeg", "-y", "-i", str(base_path), "-c", "copy", str(out_path)], quiet=True)
        return

    inputs: list[str] = ["-i", str(base_path)]
    for ov in overlays:
        ov_path = resolve_path(ov["file"], edit_dir)
        inputs += ["-i", str(ov_path)]

    filter_parts: list[str] = []
    # PTS-shift every overlay so its frame 0 lands at start_in_output
    for idx, ov in enumerate(overlays, start=1):
        t = float(ov["start_in_output"])
        filter_parts.append(f"[{idx}:v]setpts=PTS-STARTPTS+{t}/TB[a{idx}]")

    # Chain overlays on top of base
    current = "[0:v]"
    for idx, ov in enumerate(overlays, start=1):
        t = float(ov["start_in_output"])
        dur = float(ov["duration"])
        end = t + dur
        next_label = f"[v{idx}]"
        filter_parts.append(
            f"{current}[a{idx}]overlay=enable='between(t,{t:.3f},{end:.3f})'{next_label}"
        )
        current = next_label

    # Subtitles LAST — Rule 1
    if has_subs:
        subs_abs = str(subtitles_path.resolve()).replace(":", r"\:").replace("'", r"\'")
        filter_parts.append(
            f"{current}subtitles='{subs_abs}':force_style='{subtitle_style}'[outv]"
        )
        out_label = "[outv]"
    else:
        # Rename the last overlay output to [outv] for consistency
        if has_overlays:
            filter_parts.append(f"{current}null[outv]")
            out_label = "[outv]"
        else:
            out_label = "[0:v]"

    filter_complex = ";".join(filter_parts)

    crf = "18"
    tune_args: list[str] = []
    if is_screen_content(base_path):
        # Base is screen footage — keep text crisp through the final re-encode
        crf = "16"
        tune_args = ["-tune", "stillimage"]
        print("  screen content detected: stillimage, CRF 16 (composite)")

    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", filter_complex,
        "-map", out_label,
        "-map", "0:a",
        "-c:v", "libx264", "-preset", "fast", "-crf", crf, *tune_args,
        "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        "-movflags", "+faststart",
        str(out_path),
    ]
    print(f"compositing → {out_path.name}")
    print(f"  overlays: {len(overlays)}, subtitles: {'yes' if has_subs else 'no'}")
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


# -------- Main ---------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser(description="Render a video from an EDL")
    ap.add_argument("edl", type=Path, help="Path to edl.json")
    ap.add_argument("-o", "--output", type=Path, required=True, help="Output video path")
    ap.add_argument(
        "--preview",
        action="store_true",
        help="Preview mode: 1080p, medium, CRF 22 — evaluable for QC, faster than final.",
    )
    ap.add_argument(
        "--draft",
        action="store_true",
        help="Draft mode: 720p, ultrafast, CRF 28 — cut-point verification only.",
    )
    ap.add_argument(
        "--build-subtitles",
        action="store_true",
        help="Build master.srt from transcripts + EDL offsets before compositing",
    )
    ap.add_argument(
        "--no-subtitles",
        action="store_true",
        help="Skip subtitles even if the EDL references one",
    )
    ap.add_argument(
        "--no-loudnorm",
        action="store_true",
        help="Skip audio loudness normalization. Default is on (-14 LUFS, -1 dBTP, LRA 11).",
    )
    ap.add_argument(
        "--fps",
        type=float,
        default=None,
        help="Output frame rate. Default: the first source's frame rate (24 was hardcoded before).",
    )
    ap.add_argument(
        "--no-cache",
        action="store_true",
        help="Ignore cached segments (re-extract everything). Use after any EDL/grade change.",
    )
    args = ap.parse_args()

    edl_path = args.edl.resolve()
    if not edl_path.exists():
        sys.exit(f"edl not found: {edl_path}")

    edl = json.loads(edl_path.read_text())
    edit_dir = edl_path.parent
    out_path = args.output.resolve()

    # Resolve output frame rate: explicit --fps wins; otherwise use the first
    # source's stream frame rate so screen/phone footage keeps its native look.
    if args.fps is None:
        first_src = edl["sources"][edl["ranges"][0]["source"]]
        args.fps = detect_fps(resolve_path(first_src, edit_dir))

    # 1. Extract per-segment (auto-grade per range if EDL grade is "auto").
    #    The clips dir is per-OUTPUT (clips_<out.stem>), so concurrent renders
    #    of different outputs never overwrite each other's segments.
    segment_paths, vts = extract_all_segments(
        edl, edit_dir, preview=args.preview, draft=args.draft, fps=args.fps,
        clips_tag=out_path.stem, use_cache=not args.no_cache, edl_path=edl_path,
    )

    # 2. Concat → base (guarded; includes the single final AAC encode)
    if args.draft:
        base_name = "base_draft.mp4"
    elif args.preview:
        base_name = "base_preview.mp4"
    else:
        base_name = "base.mp4"
    base_path = edit_dir / base_name
    concat_segments(segment_paths, base_path, edit_dir, sum(vts))

    # 3. Subtitles: build if requested, resolve final path
    subs_path: Path | None = None
    if not args.no_subtitles:
        if args.build_subtitles:
            subs_path = edit_dir / "master.srt"
            build_master_srt(edl, edit_dir, subs_path)
        elif edl.get("subtitles"):
            subs_path = resolve_path(edl["subtitles"], edit_dir)
            if not subs_path.exists():
                print(f"warning: subtitles path in EDL does not exist: {subs_path}")
                subs_path = None

    # 4. Composite (overlays + subtitles LAST) → intermediate (pre-loudnorm) path
    overlays = edl.get("overlays") or []
    subtitle_style = edl.get("subtitle_style") or SUB_FORCE_STYLE
    if args.no_loudnorm:
        # Composite directly to final output
        build_final_composite(base_path, overlays, subs_path, out_path, edit_dir, subtitle_style)
    else:
        # Composite to a temp file, then run loudnorm → final output
        tmp_composite = out_path.with_suffix(".prenorm.mp4")
        build_final_composite(base_path, overlays, subs_path, tmp_composite, edit_dir, subtitle_style)
        # NOTE: loudnorm with linear=true (the two-pass path) TRIMS the audio
        # tail by ~0.5s — measured eating the final word of a real deliverable.
        # Use --no-loudnorm when the last word matters, or verify the tail
        # afterwards with verify_av.py --tails.
        print("loudness normalization → social-ready (-14 LUFS / -1 dBTP / LRA 11)")
        print("  warning: linear two-pass loudnorm can trim ~0.5s of the tail — check with verify_av.py --tails")
        apply_loudnorm_two_pass(tmp_composite, out_path, preview=args.draft)
        tmp_composite.unlink(missing_ok=True)

    size_mb = out_path.stat().st_size / (1024 * 1024)
    print(f"\ndone: {out_path} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
