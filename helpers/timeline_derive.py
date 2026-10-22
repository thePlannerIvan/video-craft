#!/usr/bin/env python3
"""Derive the visual layer's timeline from the EDL — the one spine.

The retired path derived the same timeline by *re-parsing the SRT*:

    subtitles.srt ──parse-srt.py──► timecode-map.json ──grouping.json──► timeline.json

That round trip threw away what the EDL already knew: which EDL segment each cue
belongs to, which transcript words it covers, and the fact that its times are
MEASURED rather than nominal. The SRT is a *view* of the same cues, so parsing it
back was a second, lossier derivation of one thing.

This module derives the same `entries` from the captions contract instead:

    edl.json + segment_durations.json + caption_words.json + captions.json
                                   │
                          timeline_derive.py + grouping.json
                                   ▼
                             timeline.json ──► generate-composition.py

`generate-composition.py` does not change: it reads `timeline.json`, and only the
producer of that file changes. That is what makes the replacement provable —
same grouping in, byte-identical composition skeleton out.

`grouping.json` stays a creative decision and is NOT derivable from the EDL: one
cut range can carry five visual steps, and one visual step can span a cut. What it
no longer has to do is re-number SRT lines; `cueIndices` address the caption cues
directly, and the older key `srtIndices` is still accepted as an input alias.

Usage:
    python helpers/timeline_derive.py <edit_dir> --grouping timeline/grouping.json \\
        --output-timeline timeline/timeline.json \\
        --output-durations presentation/public/step-durations.json
    python helpers/timeline_derive.py <edit_dir> --stats
    python helpers/timeline_derive.py <edit_dir> --entries-only > entries.json
"""
from __future__ import annotations

import argparse
import json
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

CAPTIONS_NAME = "captions.json"
WORDS_NAME = "caption_words.json"
EDIT_DEFAULT = "edl.json"

# The ONLY step keys this module may drop. Everything else a grouping step
# declares belongs to `generate-composition.py` and passes through untouched.
#
# Why this is an exclusion set and not a whitelist: the step dict used to list
# exactly the keys the generator was believed to read. That list drifted, and it
# dropped `mediaClips` + `mediaBox` — the whole picture track — while
# `generate-composition.py --verify` still reported success, because verify counts
# N videos when `mediaClips` exists and 1 section when it does not. A composition
# with no media at all therefore looked exactly like a composition with no media
# declared. An exclusion set cannot drift that way: forgetting to list a key
# passes it through, which is the safe direction.
OWNED_STEP_KEYS = frozenset({
    # recomputed from the cue binding
    "id", "chapterId", "chapterTitle", "step",
    "startMs", "endMs", "durationMs", "caption",
    "cueIndices", "srtIndices", "cueRange", "segments", "wordCount", "sourceRange",
})


def _fail(message: str) -> None:
    raise SystemExit(f"timeline derive error: {message}")


def _read_json(path: Path):
    if not path.exists():
        _fail(f"{path.name} not found at {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        _fail(f"{path.name} is not valid JSON: {exc}")


def load_contract(edit_dir: Path, *, edl_path: Path | None = None) -> tuple[list[dict], dict]:
    """Read the cue list and the word contract, refusing a nominal timeline.

    `caption_words.json` records which timeline it was built on. Cues derived from
    the EDL's nominal Σ(end−start) are off by up to a second from what the encoder
    emitted, so a timeline built on them would place every visual step slightly
    early. Refuse rather than warn: this is the same failure the caption chain
    already guards against.
    """
    words = _read_json(edit_dir / WORDS_NAME)
    cues = _read_json(edit_dir / CAPTIONS_NAME)
    if not isinstance(cues, list) or not cues:
        _fail(f"{CAPTIONS_NAME} must be a non-empty list of cues")

    source = words.get("timeline_source")
    if source not in ("measured", "projected"):
        _fail(
            f"{WORDS_NAME} was built on the '{source or 'unknown'}' timeline. "
            "Either run `duration_plan.py <edit_dir>` for a frame-quantised "
            "projection, or render and run "
            "`srt_export.py <edit_dir> --prepare --lock --build` so the cues carry "
            "MEASURED segment durations, then derive again.")
    if source == "projected":
        print("  · 时间脊柱取自解析预演（帧量化，无渲染校验）——"
              "可据此审阅；交付前必须真实渲染并复核")

    edl_file = (edl_path or (edit_dir / EDIT_DEFAULT)).resolve()
    if edl_file.exists():
        from _edl import edl_digest  # same directory
        digest = edl_digest(edl_file)
        if words.get("edl_sha256") and words["edl_sha256"] != digest:
            _fail(
                f"{WORDS_NAME} was built from a different EDL "
                f"({words['edl_sha256'][:12]}… vs {digest[:12]}…). "
                "Re-run --prepare/--lock/--build against the current cut first.")

    segments = {int(s["index"]): s for s in words.get("segments", [])}
    for cue in cues:
        if "start" not in cue or "end" not in cue or "line" not in cue:
            _fail(f"cue is missing start/end/line: {cue!r}")
        if int(cue.get("segment", -1)) not in segments:
            _fail(f"cue references missing EDL segment {cue.get('segment')!r}")
    return cues, words


def derive_entries(edit_dir: Path, *, edl_path: Path | None = None) -> list[dict]:
    """The cue list as parse-srt.py's `entries`, plus what the SRT could not carry.

    Times are rounded to whole milliseconds with the SAME rounding the SRT writer
    uses, so a cue addressed here and the same cue read back from `subtitles.srt`
    agree exactly — that is the equivalence the retirement of parse-srt.py rests on.
    """
    cues, words = load_contract(edit_dir, edl_path=edl_path)
    per_segment: dict[int, list[dict]] = {}
    for word in words.get("words", []):
        per_segment.setdefault(int(word["segment"]), []).append(word)
    for group in per_segment.values():
        group.sort(key=lambda w: w.get("out_start", 0.0))

    entries: list[dict] = []
    for index, cue in enumerate(cues):
        start_ms = int(round(float(cue["start"]) * 1000))
        end_ms = int(round(float(cue["end"]) * 1000))
        segment = int(cue.get("segment", 0))
        # Which kept words this cue covers: everything inside its output window.
        covered = [w for w in per_segment.get(segment, [])
                   if w["out_start"] >= float(cue["start"]) - 1e-6
                   and w["out_end"] <= float(cue["end"]) + 1e-6]
        entries.append({
            # --- the parse-srt.py contract, byte-compatible ---
            "index": index,
            "startMs": start_ms,
            "endMs": end_ms,
            "durationMs": end_ms - start_ms,
            "text": str(cue["line"]),
            # --- what only the EDL side knows ---
            "segment": segment,
            "sourceRange": [float(cue["source_start"]), float(cue["source_end"])],
            "wordIndices": [int(w["segment_word"]) for w in covered],
            "transcriptIndices": [int(w["transcript_index"]) for w in covered],
            "source": words["segments"][segment]["source"] if segment < len(words["segments"]) else None,
        })
    return entries


def make_timecode_map(entries: list[dict]) -> dict:
    """Same shape parse-srt.py wrote, so timecode-map consumers keep working."""
    return {
        "totalEntries": len(entries),
        "totalDurationMs": (entries[-1]["endMs"] - entries[0]["startMs"]) if entries else 0,
        "entries": entries,
    }


def _normalize_indices(indices, *, step_label: str) -> list[int]:
    if not isinstance(indices, list) or not indices:
        raise ValueError(f"{step_label}: cueIndices must be a non-empty array")
    return sorted({int(i) for i in indices})


def _stretch_to_measured(chapters: list[dict], measured_total_ms: int) -> None:
    """Pin the spine to the measured cut and close the cue gaps between steps.

    Two defects share this fix, and both are invisible until something renders:

    * the first cue starts at ~0.3s and the last cue ends before the audio does
      (the cut has head/tail pads), so a cue-span total is SHORT by ~0.35s and
      every clip after the first sits early;
    * consecutive steps have a cue gap between them, so each clip ends before the
      next begins — the film flashes black at the seam (2026-10-17: 7 segments,
      3.40s, caught only after a full render by verify_delivery's black budget).

    Steps stay a partition of the film: first step starts at 0, each step ends
    where the next one starts, the last ends at the measured total.
    """
    steps = [st for ch in chapters for st in ch["steps"]]
    if not steps:
        return
    steps[0]["startMs"] = 0
    for cur, nxt in zip(steps, steps[1:]):
        cur["endMs"] = nxt["startMs"]
    steps[-1]["endMs"] = max(steps[-1]["endMs"], measured_total_ms)
    for st in steps:
        st["durationMs"] = st["endMs"] - st["startMs"]


def _measured_total_ms(edit_dir: Path, edl_path: Path | None = None
                       ) -> tuple[int | None, str, str | None]:
    """Delegate to `_edl.measured_total_ms`: identity by digest, not by file name."""
    from _edl import measured_total_ms
    return measured_total_ms(edit_dir, edl_path)


def build_timeline(entries: list[dict], grouping: dict,
                   *, measured_total_ms: int | None = None) -> tuple[dict, dict]:
    """Same output as parse-srt.py's build_timeline, plus the EDL-side facts.

    Every numeric field and `caption` is computed identically, so a composition
    generated from this file is byte-identical to one generated from the SRT path.
    The additions (`cueIndices`/`cueRange`, `segments`, `sourceRange`) are extra
    keys the generator ignores and a human or a later stage can use.
    """
    chapters: list[dict] = []
    duration_map: dict[str, list[int]] = {}
    for ch_idx, chapter in enumerate(grouping.get("chapters", [])):
        chapter_id = chapter.get("id") or "chapter-{:02d}".format(ch_idx + 1)
        title = chapter.get("title") or chapter_id
        steps: list[dict] = []
        durations: list[int] = []
        for step_idx, step in enumerate(chapter.get("steps", [])):
            label = f"{chapter_id} step {step_idx}"
            raw = step.get("cueIndices", step.get("srtIndices"))
            indices = _normalize_indices(raw, step_label=label)
            selected = []
            for idx in indices:
                if idx < 0 or idx >= len(entries):
                    raise ValueError(f"{label} references missing cue index {idx}")
                selected.append(entries[idx])
            start = selected[0]["startMs"]
            end = selected[-1]["endMs"]
            caption = " ".join(item["text"] for item in selected).strip()
            segments = sorted({item["segment"] for item in selected})
            words = [w for item in selected for w in item["wordIndices"]]
            item = {
                # --- unchanged: what generate-composition.py reads ---
                "id": step.get("id") or "{}-{:03d}".format(chapter_id, step_idx + 1),
                "chapterId": chapter_id,
                "chapterTitle": title,
                "step": step_idx,
                "startMs": start,
                "endMs": end,
                "durationMs": end - start,
                "caption": step.get("caption") or caption,
                "screenIntent": step.get("screenIntent", ""),
                "visualModel": step.get("visualModel", ""),
                "modelStructure": step.get("modelStructure", ""),
                "onScreenTextRule": step.get("onScreenTextRule", ""),
                "assetNeeds": step.get("assetNeeds", []),
                # --- new: the cue/EDL binding the SRT could not express ---
                "cueIndices": indices,
                "cueRange": [indices[0], indices[-1]],
                "segments": segments,
                "wordCount": len(words),
                "sourceRange": [selected[0]["sourceRange"][0], selected[-1]["sourceRange"][1]],
                "sourceBlueprintId": step.get("sourceBlueprintId"),
                # --- new: the picture page this step shows, and how it composites
                # into the film. `composite` / `personWindow` / `captionSafe` are
                # per-screen exceptions; the film default lives in the ppt-hell
                # project's design_direction.md and is merged by the generator.
                "sourcePageKey": step.get("sourcePageKey"),
                "composite": step.get("composite"),
                "personWindow": step.get("personWindow"),
                "captionSafe": step.get("captionSafe"),
            }
            # Everything else the grouping declared passes through to the
            # generator. Deliberately after the literal above, so keys that are
            # already present keep their position and old timelines stay
            # byte-identical; only genuinely new keys (`mediaClips`, `mediaBox`,
            # whatever the next generator version reads) are appended.
            for author_key, author_value in step.items():
                if author_key not in OWNED_STEP_KEYS and author_key not in item:
                    item[author_key] = author_value
            steps.append(item)
            durations.append(item["durationMs"])
        chapters.append({"id": chapter_id, "title": title, "steps": steps})
        duration_map[chapter_id] = durations
    if measured_total_ms:
        _stretch_to_measured(chapters, int(measured_total_ms))
        duration_map = {ch["id"]: [st["durationMs"] for st in ch["steps"]]
                        for ch in chapters}
    first_start = chapters[0]["steps"][0]["startMs"] if chapters and chapters[0]["steps"] else 0
    last_end = chapters[-1]["steps"][-1]["endMs"] if chapters and chapters[-1]["steps"] else 0
    return {
        "source": "edl",
        "totalChapters": len(chapters),
        "totalSteps": sum(len(ch["steps"]) for ch in chapters),
        # The axis length is the END of the last step, not the sum of step
        # durations and not a span: cues have real gaps between them, and the
        # film may start before the first cue (lead-in silence). Subtracting
        # `first_start` made a 190.34s film report 190.08s and every consumer
        # (review clock, playback check) lost the head.
        "totalDurationMs": last_end,
        "chapters": chapters,
    }, duration_map


def check_alignment(entries: list[dict], grouping: dict, alignment: dict) -> None:
    """Prevent stale, missing or cross-screen bindings in a measured timeline."""
    if alignment.get('errors') or alignment.get('timelineSource') != 'measured':
        raise ValueError('Alignment must be error-free and measured')
    digest = hashlib.sha256(json.dumps(entries, sort_keys=True).encode()).hexdigest()
    if alignment.get('entriesHash') != digest:
        raise ValueError('Alignment is stale: rebuild against current measured cues')
    screens = {x['blueprintId']: x for x in alignment.get('blueprintAlignments', [])}
    covered = {key: set() for key in screens}
    for screen in screens.values():
        if screen.get('needsReview') or 'candidateCueRange' not in screen:
            raise ValueError('Unresolved screen alignment: ' + screen['blueprintId'])
    for chapter in grouping.get('chapters', []):
        for step in chapter.get('steps', []):
            key = step.get('sourceBlueprintId')
            indices = _normalize_indices(step.get('cueIndices', step.get('srtIndices')), step_label='step')
            intersected = [k for k, s in screens.items() if any(s['candidateCueRange'][0] <= n <= s['candidateCueRange'][1] for n in indices)]
            if key is None and not intersected:
                continue  # speech-only region, no upstream visual obligation
            if key not in screens:
                raise ValueError('Unknown or missing sourceBlueprintId')
            start, end = screens[key]['candidateCueRange']
            if indices != list(range(indices[0], indices[-1] + 1)) or not all(start <= n <= end for n in indices):
                raise ValueError('Step crosses screen boundary or skips internal cues: ' + key)
            if set(indices) & covered[key]:
                raise ValueError('Duplicate cue coverage: ' + key)
            covered[key].update(indices)
    for key, screen in screens.items():
        start, end = screen['candidateCueRange']
        if covered[key] != set(range(start, end + 1)):
            raise ValueError('Incomplete screen coverage: ' + key)


def print_stats(entries: list[dict]) -> None:
    if not entries:
        print("no cues")
        return
    total_s = (entries[-1]["endMs"] - entries[0]["startMs"]) / 1000.0
    segments = sorted({e["segment"] for e in entries})
    print(f"Cues:            {len(entries)}")
    print(f"EDL segments:    {len(segments)}  ({segments[0]}..{segments[-1]})")
    print(f"Total duration:  {total_s:.1f}s ({total_s / 60:.1f} min)")
    words = sum(len(e["wordIndices"]) for e in entries)
    print(f"Kept words covered by a cue: {words}")
    print("\nFirst 3 cues:")
    for e in entries[:3]:
        print("  #{:03d}  {:6d}ms  seg {:<3}  {}".format(
            e["index"], e["durationMs"], e["segment"], e["text"][:52]))
    print("Last 3 cues:")
    for e in entries[-3:]:
        print("  #{:03d}  {:6d}ms  seg {:<3}  {}".format(
            e["index"], e["durationMs"], e["segment"], e["text"][:52]))


def main() -> int:
    ap = argparse.ArgumentParser(description="Derive timeline.json from the EDL, not from the SRT")
    ap.add_argument("edit_dir", type=Path)
    ap.add_argument("--edl", type=Path, default=None)
    ap.add_argument("--alignment", type=Path, default=None)
    ap.add_argument("--grouping", type=Path, default=None)
    ap.add_argument("--output-timeline", type=Path, default=None)
    ap.add_argument("--output-durations", type=Path, default=None)
    ap.add_argument("--output-timecode-map", type=Path, default=None)
    ap.add_argument("--entries-only", action="store_true",
                    help="print the derived cue entries as JSON and exit")
    ap.add_argument("--stats", action="store_true")
    args = ap.parse_args()

    edit_dir = args.edit_dir.resolve()
    entries = derive_entries(edit_dir, edl_path=args.edl)
    words_source = (_read_json(edit_dir / WORDS_NAME).get("timeline_source")
                    if (edit_dir / WORDS_NAME).exists() else None)

    if args.entries_only:
        print(json.dumps(entries, ensure_ascii=False, indent=2))
        return 0
    if args.stats:
        print_stats(entries)
    if args.output_timecode_map:
        args.output_timecode_map.parent.mkdir(parents=True, exist_ok=True)
        args.output_timecode_map.write_text(
            json.dumps(make_timecode_map(entries), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        print(f"Wrote timecode map -> {args.output_timecode_map}")
    if args.grouping:
        grouping = _read_json(args.grouping)
        if args.alignment:
            check_alignment(entries, grouping, _read_json(args.alignment))
        measured_total = None
        if words_source == "measured":
            measured_total, how, tag = _measured_total_ms(edit_dir, args.edl)
            if measured_total and how == "digest":
                print(f"  · 时间脊柱按实测总长对齐：{measured_total / 1000:.3f}s，"
                      f"记录 {tag}（与当前剪辑指纹一致），步骤首尾相接")
            elif measured_total and how == "no-digest":
                print(f"  ! 时间脊柱用的是推定记录 {tag}（无剪辑指纹）："
                      f"{measured_total / 1000:.3f}s，请确认它渲的是当前版本")
            elif how == "mismatch":
                print("  ! 记录都来自旧版剪辑：时间轴按名义时长，画面时间点可能偏移")
            else:
                print("  ! 还没有与当前剪辑对应的渲染记录：时间轴按名义时长（先渲底片再派生可消除）")
        if measured_total and how == "digest":
            time_source = "measured"
        elif measured_total and how == "no-digest":
            time_source = "measured-guessed"
        elif words_source == "projected":
            time_source = "projected"
        else:
            time_source = "nominal"
        timeline, durations = build_timeline(entries, grouping,
                                             measured_total_ms=measured_total)
        timeline["timeSource"] = time_source
        timeline["measuredTotalMs"] = int(measured_total) if measured_total else None
        if args.output_timeline:
            args.output_timeline.parent.mkdir(parents=True, exist_ok=True)
            args.output_timeline.write_text(
                json.dumps(timeline, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"Wrote visual timeline -> {args.output_timeline}")
        if args.output_durations:
            args.output_durations.parent.mkdir(parents=True, exist_ok=True)
            args.output_durations.write_text(
                json.dumps(durations, ensure_ascii=False), encoding="utf-8")
            print(f"Wrote step durations -> {args.output_durations}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
