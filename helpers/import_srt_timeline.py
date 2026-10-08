#!/usr/bin/env python3
"""Build the shared visual timeline from externally edited audio/SRT.

python3 helpers/import_srt_timeline.py <project> --srt <srt> --alignment <json>
This preserves srt-import provenance; it never manufactures measured EDL proof.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

ALIGNER = Path(__file__).parents[1] / 'visual/scripts/align-visual-plan.py'
spec = importlib.util.spec_from_file_location('craft_aligner', ALIGNER)
aligner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(aligner)


def resolve_alignment_path(value: str, *, alignment_dir: Path, project_root: Path) -> Path:
    """Resolve paths emitted by align-visual-plan.py from any working directory."""
    candidate = Path(value)
    if candidate.is_absolute():
        return candidate.resolve()
    for base in (alignment_dir, project_root, Path.cwd()):
        resolved = (base / candidate).resolve()
        if resolved.is_file():
            return resolved
    # Return the most useful deterministic location so the caller's normal
    # FileNotFoundError names the path an agent should inspect.
    return (project_root / candidate).resolve()


def build_timeline(srt: Path, alignment: dict, *, alignment_dir: Path | None = None,
                   project_root: Path | None = None) -> dict:
    entries = aligner.parse_srt(srt)
    if not entries:
        raise ValueError('SRT 没有有效 cue')
    for i, entry in enumerate(entries):
        if entry['endMs'] <= entry['startMs'] or entry['startMs'] < 0:
            raise ValueError(f'cue {i} 时间区间无效')
        if i and entry['startMs'] < entries[i - 1]['endMs']:
            raise ValueError(f'cue {i} 与前一条重叠')
    digest = hashlib.sha256(json.dumps(entries, sort_keys=True).encode()).hexdigest()
    if alignment.get('timelineSource') != 'srt-import' or alignment.get('entriesHash') != digest:
        raise ValueError('对齐不是这份 SRT 的 srt-import 版本；重新运行 align-visual-plan.py --srt')
    if alignment.get('errors'):
        raise ValueError(f"对齐含错误：{alignment['errors']}")
    alignment_dir = Path(alignment_dir or Path.cwd()).resolve()
    project_root = Path(project_root or alignment_dir).resolve()
    plan = resolve_alignment_path(alignment['sourcePlan'], alignment_dir=alignment_dir,
                                  project_root=project_root)
    script = resolve_alignment_path(alignment['sourceScript'], alignment_dir=alignment_dir,
                                    project_root=project_root)
    plan_doc = json.loads(plan.read_text(encoding='utf-8'))
    if plan_doc.get('script_hash') != hashlib.sha256(script.read_bytes()).hexdigest():
        raise ValueError('脚本版本已改变；回上游确认当前契约')
    screens = {one['beatId']: one for one in alignment.get('blueprintAlignments', [])}
    chapters, covered = [], set()
    for beat in alignment.get('beatAlignments', []):
        if beat.get('needsReview') or 'srtRange' not in beat:
            raise ValueError(f"{beat['beatId']} 未核对齐；核听后修正 cue 范围再运行")
        lo, hi = beat['srtRange']
        if not isinstance(lo, int) or not isinstance(hi, int) or not 0 <= lo <= hi < len(entries):
            raise ValueError(f"{beat['beatId']} cue 范围无效")
        cue_ids = set(range(lo, hi + 1))
        if covered & cue_ids:
            raise ValueError('两个 Beat 使用了同一条 cue')
        covered.update(cue_ids)
        screen = screens.get(beat['beatId'])
        if screen and screen.get('needsReview'):
            raise ValueError(f"{screen['screenId']} 未核对齐")
        key = screen['screenId'] if screen else beat['beatId']
        start, end = entries[lo]['startMs'], entries[hi]['endMs']
        step = {'id': key, 'step': 1, 'cueRange': [lo, hi + 1],
                'startMs': start, 'endMs': end, 'durationMs': end - start,
                'caption': ' '.join(e['text'] for e in entries[lo:hi + 1]),
                'sourcePageKey': key if screen else None,
                'sourceBlueprintId': key if screen else None}
        if screen:
            for field in ('mustShow', 'mustExpress', 'exactLabels', 'evidence'):
                step[field] = screen.get(field, [])
        chapters.append({'id': beat['beatId'], 'title': beat.get('title', key), 'steps': [step]})
    if covered != set(range(len(entries))):
        raise ValueError('SRT 存在未绑定 cue；先核对遗漏/插入段，不静默丢弃')
    return {'source': 'srt-import', 'sourceSrt': str(srt.resolve()), 'entriesHash': digest,
            'totalChapters': len(chapters), 'totalSteps': len(chapters),
            'totalDurationMs': entries[-1]['endMs'], 'chapters': chapters}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project', type=Path)
    parser.add_argument('--srt', type=Path, required=True)
    parser.add_argument('--alignment', type=Path, required=True)
    args = parser.parse_args()
    try:
        srt = args.srt.resolve()
        alignment = args.alignment.resolve()
        data = build_timeline(
            srt,
            json.loads(alignment.read_text(encoding='utf-8')),
            alignment_dir=alignment.parent,
            project_root=args.project.resolve(),
        )
        path = args.project.resolve() / 'timeline/timeline.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    except (ValueError, OSError, KeyError) as error:
        parser.error(str(error))
    print(json.dumps({'ok': True, 'timeline': str(path), 'source': 'srt-import'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
