#!/usr/bin/env python3
"""
Parse SRT and build strict SRT-derived timeline artifacts.

Usage:
  python3 scripts/parse-srt.py input/subtitles.srt --output timeline/timecode-map.json
  python3 scripts/parse-srt.py input/subtitles.srt --stats
  # v1 legacy (React pipeline): still implemented, not used by the v2 flow
  python3 scripts/parse-srt.py input/subtitles.srt \\
    --grouping timeline/grouping.json \\
    --output-timeline timeline/timeline.json \\
    --output-durations presentation/public/step-durations.json   # v1 path
"""
import json
import re
import sys
from pathlib import Path


def read_json(path):
    return json.loads(Path(path).read_text("utf-8"))


def write_json(path, data, pretty=True):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=2 if pretty else None)
    p.write_text(text + ("\n" if pretty else ""), "utf-8")


def parse_srt(path):
    content = Path(path).read_text(encoding="utf-8-sig")
    blocks = re.split(r"\n\s*\n", content.strip())
    entries = []
    for block in blocks:
        lines = [line.strip() for line in block.strip().splitlines() if line.strip()]
        if len(lines) < 2:
            continue
        time_line = lines[1] if re.match(r"^\d+$", lines[0]) else lines[0]
        text_lines = lines[2:] if time_line == lines[1] else lines[1:]
        tc = re.match(
            r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)",
            time_line,
        )
        if not tc:
            continue
        h1, m1, s1, ms1 = (int(tc.group(i)) for i in range(1, 5))
        h2, m2, s2, ms2 = (int(tc.group(i)) for i in range(5, 9))
        start = h1 * 3600000 + m1 * 60000 + s1 * 1000 + ms1
        end = h2 * 3600000 + m2 * 60000 + s2 * 1000 + ms2
        text = " ".join(text_lines)
        entries.append(
            {
                "index": len(entries),
                "startMs": start,
                "endMs": end,
                "durationMs": end - start,
                "text": text,
            }
        )
    return entries


def make_timecode_map(entries):
    return {
        "totalEntries": len(entries),
        "totalDurationMs": entries[-1]["endMs"] - entries[0]["startMs"] if entries else 0,
        "entries": entries,
    }


def normalize_indices(indices):
    if not isinstance(indices, list) or not indices:
        raise ValueError("step.srtIndices must be a non-empty array")
    return sorted({int(i) for i in indices})


def build_timeline(entries, grouping):
    chapters = []
    duration_map = {}
    for ch_idx, chapter in enumerate(grouping.get("chapters", [])):
        chapter_id = chapter.get("id") or "chapter-{:02d}".format(ch_idx + 1)
        title = chapter.get("title") or chapter_id
        steps = []
        durations = []
        for step_idx, step in enumerate(chapter.get("steps", [])):
            indices = normalize_indices(step.get("srtIndices"))
            selected = []
            for idx in indices:
                if idx < 0 or idx >= len(entries):
                    raise ValueError("{} step {} references missing SRT index {}".format(chapter_id, step_idx, idx))
                selected.append(entries[idx])
            start = selected[0]["startMs"]
            end = selected[-1]["endMs"]
            caption = " ".join(item["text"] for item in selected).strip()
            item = {
                "id": step.get("id") or "{}-{:03d}".format(chapter_id, step_idx + 1),
                "chapterId": chapter_id,
                "chapterTitle": title,
                "step": step_idx,
                "srtIndices": indices,
                "srtRange": [indices[0], indices[-1]],
                "startMs": start,
                "endMs": end,
                "durationMs": end - start,
                "caption": step.get("caption") or caption,
                "screenIntent": step.get("screenIntent", ""),
                "visualModel": step.get("visualModel", ""),
                "modelStructure": step.get("modelStructure", ""),
                "onScreenTextRule": step.get("onScreenTextRule", ""),
                "assetNeeds": step.get("assetNeeds", []),
            }
            steps.append(item)
            durations.append(item["durationMs"])
        chapters.append({"id": chapter_id, "title": title, "steps": steps})
        duration_map[chapter_id] = durations
    return {
        "source": "srt",
        "totalChapters": len(chapters),
        "totalSteps": sum(len(ch["steps"]) for ch in chapters),
        "totalDurationMs": sum(sum(v) for v in duration_map.values()),
        "chapters": chapters,
    }, duration_map


def print_stats(entries):
    total_s = (entries[-1]["endMs"] - entries[0]["startMs"]) / 1000 if entries else 0
    print("Total entries:  {}".format(len(entries)))
    print("Total duration: {:.1f}s ({:.1f} min)".format(total_s, total_s / 60))
    print("\nFirst 5 entries:")
    for e in entries[:5]:
        print("  #{:03d}  {:5d}ms  {}".format(e["index"], e["durationMs"], e["text"][:60]))
    print("...\nLast 5 entries:")
    for e in entries[-5:]:
        print("  #{:03d}  {:5d}ms  {}".format(e["index"], e["durationMs"], e["text"][:60]))


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(1)
    srt_path = None
    output_path = None
    grouping_path = None
    timeline_path = None
    durations_path = None
    stats = False
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("-h", "--help"):
            print(__doc__)
            sys.exit(0)
        elif arg == "--output":
            output_path = args[i + 1]
            i += 2
        elif arg == "--grouping":
            grouping_path = args[i + 1]
            i += 2
        elif arg == "--output-timeline":
            timeline_path = args[i + 1]
            i += 2
        elif arg == "--output-durations":
            durations_path = args[i + 1]
            i += 2
        elif arg == "--stats":
            stats = True
            i += 1
        elif not srt_path:
            srt_path = arg
            i += 1
        else:
            print("Unknown: {}".format(arg), file=sys.stderr)
            sys.exit(1)

    if not srt_path:
        print("Error: no SRT file", file=sys.stderr)
        sys.exit(1)

    entries = parse_srt(srt_path)
    if stats:
        print_stats(entries)
    if output_path:
        write_json(output_path, make_timecode_map(entries))
        print("Wrote timecode map -> {}".format(output_path))

    if grouping_path:
        timeline, durations = build_timeline(entries, read_json(grouping_path))
        if timeline_path:
            write_json(timeline_path, timeline)
            print("Wrote visual timeline -> {}".format(timeline_path))
        if durations_path:
            write_json(durations_path, durations, pretty=False)
            print("Wrote step durations -> {}".format(durations_path))


if __name__ == "__main__":
    main()
