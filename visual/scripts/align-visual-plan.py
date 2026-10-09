#!/usr/bin/env python3
"""Align one Video Story blueprint per Speech Beat to an edited SRT."""

from __future__ import annotations

import argparse
import json
import hashlib
import sys
import re
from difflib import SequenceMatcher
from pathlib import Path


def parse_time(value: str) -> int:
    hours, minutes, rest = value.replace('.', ',').split(':')
    seconds, millis = rest.split(',')
    return ((int(hours) * 60 + int(minutes)) * 60 + int(seconds)) * 1000 + int(millis)


def parse_srt(path: Path) -> list[dict]:
    text = path.read_text(encoding='utf-8-sig').replace('\r\n', '\n')
    entries = []
    for block in re.split(r'\n\s*\n', text.strip()):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        time_index = next((i for i, line in enumerate(lines) if '-->' in line), None)
        if time_index is None:
            continue
        start, end = [part.strip() for part in lines[time_index].split('-->', 1)]
        entries.append({'index': len(entries), 'startMs': parse_time(start), 'endMs': parse_time(end), 'text': ' '.join(lines[time_index + 1:])})
    return entries


def normalize_id(value: str, index: int) -> str:
    value = re.sub(r'[^a-z0-9_-]+', '-', value.strip().lower()).strip('-')
    return value or f'beat-{index + 1:02d}'


def parse_script(path: Path) -> list[dict]:
    text = path.read_text(encoding='utf-8')
    matches = list(re.finditer(r'^##\s+([^\n｜|]+?)(?:\s*[｜|]\s*([^\n]+))?\s*$', text, re.M))
    if not matches:
        body = re.sub(r'^#\s+.*$', '', text, count=1, flags=re.M).strip()
        return [{'id': 'beat-01', 'title': '全文', 'body': body}]
    beats = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        beats.append({'id': normalize_id(match.group(1), index), 'title': (match.group(2) or match.group(1)).strip(), 'body': text[match.end():end].strip()})
    return beats


def normalize(text: str) -> str:
    return ''.join(ch.lower() for ch in text if ch.isalnum() or '\u4e00' <= ch <= '\u9fff')


def best_match(text: str, entries: list[dict], cursor: int) -> dict | None:
    target = normalize(text)
    if not target:
        return None
    best = None
    for start in range(cursor, min(len(entries), cursor + 50)):
        combined = ''
        for end in range(start, min(len(entries), start + 20)):
            combined += normalize(entries[end]['text'])
            if not combined:
                continue
            contains = target in combined or combined in target
            score = 1.0 if target == combined else SequenceMatcher(None, target, combined).ratio()
            length_fit = min(len(target), len(combined)) / max(len(target), len(combined))
            score = score * 0.88 + length_fit * 0.12
            candidate = {'start': start, 'end': end, 'score': round(score, 4), 'contains': contains}
            if best is None or (candidate['score'], -abs(len(target) - len(combined))) > (best['score'], best.get('lengthTie', -10**9)):
                candidate['lengthTie'] = -abs(len(target) - len(combined))
                best = candidate
            if len(combined) > len(target) * 1.5:
                break
    return best


def level(match: dict | None) -> str:
    if not match:
        return 'unmatched'
    if match['score'] >= 0.82:
        return 'high'
    if match['score'] >= 0.60:
        return 'medium'
    return 'low'


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--plan', required=True, type=Path)
    parser.add_argument('--script', required=True, type=Path)
    timing = parser.add_mutually_exclusive_group(required=True)
    timing.add_argument('--edit-dir', type=Path, help='Preferred: measured caption contract')
    timing.add_argument('--srt', type=Path, help='Legacy/import timing; not measured EDL proof')
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    args.plan = args.plan.resolve()
    args.script = args.script.resolve()
    args.output = args.output.resolve()
    if args.srt:
        args.srt = args.srt.resolve()
    if args.edit_dir:
        args.edit_dir = args.edit_dir.resolve()
    plan = json.loads(args.plan.read_text(encoding='utf-8'))
    beats = parse_script(args.script)
    if args.edit_dir:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'helpers'))
        from timeline_derive import derive_entries
        entries = derive_entries(args.edit_dir)
    else:
        entries = parse_srt(args.srt)
    errors = []
    version = plan.get('contract_version')
    if version not in ('4.0', '5.0'):
        errors.append('unsupported contract_version; expected 4.0 or 5.0')
    raw = plan.get('screens' if version == '5.0' else 'blueprints')
    if not isinstance(raw, list) or not raw:
        errors.append('screens/blueprints must be a non-empty array')
        raw = []
    blueprints = [dict(x, blueprint_id=x.get('screen_id') if version == '5.0' else x.get('blueprint_id')) for x in raw]
    digest = hashlib.sha256(args.script.read_bytes()).hexdigest()
    if (version == '5.0' or plan.get('script_hash')) and plan.get('script_hash') != digest:
        errors.append('script_hash does not match current script')
    if 'visuals' in plan:
        errors.append('visuals is obsolete')

    cursor = 0
    beat_alignments = []
    beat_map = {}
    for beat in beats:
        match = best_match(beat['body'], entries, cursor)
        confidence = level(match)
        record = {'beatId': beat['id'], 'title': beat['title'], 'confidence': confidence, 'needsReview': confidence in {'low', 'unmatched'}}
        if match and confidence != 'low':
            record.update({'srtRange': [match['start'], match['end']], 'startMs': entries[match['start']]['startMs'], 'endMs': entries[match['end']]['endMs'], 'score': match['score'], 'matchedText': ' '.join(e['text'] for e in entries[match['start']:match['end'] + 1])})
            cursor = match['end'] + 1
        elif match:
            record.update({'candidateSrtRange': [match['start'], match['end']], 'score': match['score']})
        beat_alignments.append(record)
        beat_map[beat['id']] = record

    blueprint_alignments = []
    blueprint_ids = set()
    blueprint_beat_ids = set()
    for blueprint in blueprints:
        blueprint_id = blueprint.get('blueprint_id')
        beat_id = blueprint.get('beat_id')
        if not blueprint_id or blueprint_id in blueprint_ids:
            errors.append(f'invalid or duplicate blueprint_id: {blueprint_id}')
            continue
        blueprint_ids.add(blueprint_id)
        if not beat_id or beat_id in blueprint_beat_ids:
            errors.append(f'each beat_id may have only one blueprint: {beat_id}')
            continue
        blueprint_beat_ids.add(beat_id)
        if 'related_beat_ids' in blueprint:
            errors.append(f'{blueprint_id} uses obsolete related_beat_ids; expected one beat_id')
        beat_alignment = beat_map.get(beat_id)
        missing = beat_alignment is None
        needs_review = missing or beat_alignment.get('needsReview', True) or 'srtRange' not in beat_alignment
        record = {
            'blueprintId': blueprint_id,
            'screenId': blueprint_id,
            'sample': blueprint.get('sample'),
            'beatId': beat_id,
            'needsReview': needs_review,
            'missingBeatId': beat_id if missing else None,
            'question': blueprint.get('question', ''),
            'mustShow': blueprint.get('must_show', []),
            'mustExpress': blueprint.get('must_express', []),
            'exactLabels': blueprint.get('exact_labels', []),
            'evidence': blueprint.get('evidence', []),
        }
        if beat_alignment and 'srtRange' in beat_alignment:
            record.update({'candidateSrtRange': beat_alignment['srtRange'], 'candidateStartMs': beat_alignment['startMs'], 'candidateEndMs': beat_alignment['endMs']})
        blueprint_alignments.append(record)

    if args.edit_dir:
        for item in beat_alignments:
            if 'srtRange' in item: item['cueRange'] = item['srtRange']
        for item in blueprint_alignments:
            if 'candidateSrtRange' in item: item['candidateCueRange'] = item['candidateSrtRange']
    summary = {'beats': len(beat_alignments), 'blueprints': len(blueprint_alignments), 'beatNeedsReview': sum(x['needsReview'] for x in beat_alignments), 'blueprintNeedsReview': sum(x['needsReview'] for x in blueprint_alignments)}
    output = {'version': version, 'timelineSource': 'measured' if args.edit_dir else 'srt-import', 'entriesHash': hashlib.sha256(json.dumps(entries, sort_keys=True).encode()).hexdigest(), 'sourcePlan': str(args.plan), 'sourceScript': str(args.script), 'sourceSrt': str(args.srt) if args.srt else None, 'sourceEditDir': str(args.edit_dir) if args.edit_dir else None, 'summary': summary, 'errors': errors, 'beatAlignments': beat_alignments, 'blueprintAlignments': blueprint_alignments}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if not errors else 3


if __name__ == '__main__':
    raise SystemExit(main())
