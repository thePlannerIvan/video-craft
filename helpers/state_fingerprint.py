#!/usr/bin/env python3
"""工程态 ↔ 交付态 的来源指纹 —— 让"这份交付是不是过期"变成可判定。

## 为什么有它

`references/tools.md` 只切了一条轴：`duration_plan.py` 的 `projected` 记录不是交付证据，
`verify_delivery.py` 只认真实渲染。但另外三条轴没切，于是交付**过期时系统无法察觉**
（GOTCHAS #56，本轮实证：交付出去的成片是旧页面，靠人眼抽帧看 181s 才发现）：

1. **介质**：审阅用活舞台 vs 交付用渲染成片；
2. **来源版本**：这份交付是从哪一版 composition / 哪一版 store revision 渲出来的；
3. **产物归属**：哪些文件属于工程态（可丢可重算），不得留在 `edit/` 冒充底片。

本工具把 1–3 收敛成一件事：**交付自带来源指纹**。`capture` 在任何一次交付导出后写一份
`成品/delivery.json`；`verify` 拿它与**当前**工程态逐项比对，不一致即判**交付过期**并拒绝出交付。

## 用法

    python3 helpers/state_fingerprint.py capture <project> [-o <path>]
    python3 helpers/state_fingerprint.py verify  <project> [-f <path>]

默认指纹路径 `<project>/成品/delivery.json`。`verify` 退出码非 0 = 交付过期或成品被改过。

交付前比对当前来源和成品；旧交付指纹不能阻止重新渲染或重新核验。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import re
from urllib.parse import unquote, urlparse
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "video-craft/delivery-fingerprint"
VERSION = 3
_HASH_CACHE = {}


def sha256(path: Path) -> str:
    stat = path.stat()
    key = (str(path.resolve()), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_ino)
    if key in _HASH_CACHE:
        return _HASH_CACHE[key]
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    value = h.hexdigest()
    _HASH_CACHE[key] = value
    return value


def entry(path: Path) -> dict | None:
    if not path.is_file():
        return None
    return {"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size}


def head_revisions(project: Path) -> dict[str, str]:
    head = project / "visual_screens" / "_internal" / "06_workbench" / "head.json"
    if not head.is_file():
        return {}
    try:
        doc = json.loads(head.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return {k: (v or {}).get("revision") for k, v in (doc.get("pages") or {}).items()}


def source_paths(project: Path, *, include_review: bool = True) -> dict[str, Path]:
    """Track authored files and used media, excluding render caches and unused footage."""
    paths = {}
    for rel in ('recompose.json', 'edit/edl.json', 'edit/segment_durations.json',
                'edit/subtitles.srt', 'edit/caption_words.json', 'edit/captions.json',
                'timeline/timeline.json', 'timeline/choreography.json', 'edit/timeline/timeline.json'):
        p = project / rel
        if p.is_file(): paths[rel] = p
    comp = project / 'composition'
    excluded = {'_render', 'renders', 'node_modules', '.hyperframes', '.git'}
    for p in sorted(comp.rglob('*')):
        if not p.is_file() or p.name.endswith('.sources.json') or excluded.intersection(p.relative_to(comp).parts): continue
        if p.suffix.lower() in {'.html', '.js', '.css', '.json', '.svg'}:
            paths[p.relative_to(project).as_posix()] = p
            body = p.read_text(encoding='utf-8', errors='replace')
            for raw in re.findall(r'''(?:src|href)\s*=\s*["']([^"']+)|url\(\s*["']?([^)'"\s]+)''', body):
                ref = next((x for x in raw if x), '')
                parsed = urlparse(ref)
                if not ref or ref.startswith(('#', '//')) or parsed.scheme: continue
                target = (p.parent / unquote(parsed.path)).resolve()
                if target.is_file() and target.is_relative_to(project.resolve()):
                    paths[target.relative_to(project.resolve()).as_posix()] = target
    for name in ('audio.m4a', 'audio.mp3', 'audio.wav', 'person.mp4'):
        p = comp / 'assets' / name
        if p.is_file(): paths[p.relative_to(project).as_posix()] = p
    # Existing review/import contracts cover dynamic assets not visible in markup.
    contracts = [project / 'timeline/timeline.json']
    if include_review: contracts.append(project / 'review/review_data.json')
    for path in contracts:
        try: data = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError): continue
        records = data.get('sourceManifest') or []
        records += list((data.get('sourceEvidence') or {}).values())
        for record in records:
            if not isinstance(record, dict) or not record.get('path'): continue
            p = Path(record['path'])
            p = p if p.is_absolute() else project / p
            if p.is_file() and '_render' not in p.parts:
                key = p.relative_to(project).as_posix() if p.is_relative_to(project) else str(p)
                paths[key] = p
    return paths


def source_entries(project: Path) -> dict:
    return {key: entry(path) for key, path in sorted(source_paths(project).items())}


def capture(project: Path) -> dict:
    """采集当前工程态。只读，不改任何东西。"""
    wb = project / "visual_screens" / "_internal" / "06_workbench" / "revisions"
    pages: dict[str, dict] = {}
    for page, rev in head_revisions(project).items():
        svg = wb / str(rev) / "page.svg"
        pages[page] = {"revision": rev, "svg": entry(svg)}

    sources = source_entries(project)
    out_dir = project / "成品"
    deliverables = [entry(p) for p in sorted(out_dir.rglob("*")) if p.is_file() and p.name != "delivery.json"]
    inputs = {}
    try:
        report = json.loads((out_dir / f'{project.name}_核验报告.json').read_text(encoding='utf-8'))
        for key, record in (report.get('input_identities') or {}).items():
            if isinstance(record, dict) and record.get('path'):
                inputs[key] = entry(Path(record['path']))
    except (OSError, ValueError, TypeError):
        pass
    return {
        "schema": SCHEMA,
        "version": VERSION,
        "stage": "delivery",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "sources": sources,
        "pages": pages,
        'inputs': inputs,
        "deliverables": [d for d in deliverables if d],
    }


def compare(saved: dict, now: dict) -> list[str]:
    """逐项比对，返回人类可读的差异列表（空 = 一致）。"""
    diff: list[str] = []
    if saved.get('inputs') != now.get('inputs'):
        diff.append('本次合成选用的画面/音频/人物/字幕已改变或缺失 → 交付过期')
    if saved.get("schema") != SCHEMA:
        diff.append(f"指纹文件不是本工具写的（schema={saved.get('schema')!r}）")
    elif saved.get("version") != VERSION:
        diff.append(f"指纹是旧版本（v{saved.get('version')}）采集的，嵌套交付件可能没被记录——重新 capture 后再 verify")

    for key in sorted(set(now.get('sources') or {}) | set(saved.get('sources') or {})):
        cur = (now.get('sources') or {}).get(key)
        old = (saved.get("sources") or {}).get(key)
        if old is None and cur is None:
            continue
        if cur is None:
            diff.append(f"源 {key}：当前不存在（指纹里记着 {old.get('sha256','?')[:12]}）")
        elif old is None:
            diff.append(f"源 {key}：指纹里没有记录（当前 {cur['sha256'][:12]}）")
        elif old["sha256"] != cur["sha256"]:
            diff.append(f"源 {key} 已变 → 交付过期：指纹 {old['sha256'][:12]} / 当前 {cur['sha256'][:12]}")

    for page in sorted(set(now.get('pages') or {}) | set(saved.get('pages') or {})):
        cur = (now.get('pages') or {}).get(page)
        old = (saved.get("pages") or {}).get(page)
        if cur is None:
            diff.append(f'页 {page}：当前已删除 → 交付过期')
            continue
        if old is None:
            diff.append(f"页 {page}：指纹里没有记录（当前 revision {cur.get('revision')}）")
            continue
        if old.get("revision") != cur.get("revision"):
            diff.append(f"页 {page} revision 已变：指纹 {old.get('revision')} / 当前 {cur.get('revision')} → 交付过期")
        o, c = old.get("svg") or {}, cur.get("svg") or {}
        if o.get("sha256") and c.get("sha256") and o["sha256"] != c["sha256"]:
            diff.append(f"页 {page} SVG 内容已变 → 交付过期")

    saved_files = {d["path"]: d for d in (saved.get("deliverables") or [])}
    now_files = {d["path"]: d for d in (now.get("deliverables") or [])}
    for p, cur in now_files.items():
        old = saved_files.get(p)
        if old is None:
            diff.append(f"成品 {Path(p).name}：指纹里没有（交付后新增）")
        elif old["sha256"] != cur["sha256"]:
            diff.append(f"成品 {Path(p).name} 已被改动：指纹 {old['sha256'][:12]} / 当前 {cur['sha256'][:12]}")
    for p in saved_files:
        if p not in now_files:
            diff.append(f"成品 {Path(p).name}：指纹里有、现在不见了")
    return diff


def main() -> int:
    ap = argparse.ArgumentParser(description="工程态 ↔ 交付态 来源指纹")
    ap.add_argument("action", choices=["capture", "verify"])
    ap.add_argument("project")
    ap.add_argument("-o", "--output", help="指纹写到哪里（默认 <project>/成品/delivery.json）")
    ap.add_argument("-f", "--file", help="比对用的指纹文件（默认同上）")
    args = ap.parse_args()

    project = Path(args.project).resolve()
    default = project / "成品" / "delivery.json"
    target = Path(args.output).resolve() if args.output else default

    if args.action == "capture":
        doc = capture(project)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        n_src = sum(1 for v in doc["sources"].values() if v)
        print(f"已写指纹 → {target}")
        print(f"  源 {n_src} 项 · 页面 {len(doc['pages'])} 页 · 成品 {len(doc['deliverables'])} 个")
        return 0

    src = Path(args.file).resolve() if args.file else default
    if not src.is_file():
        print(f"✗ 找不到指纹文件 {src}（先跑 capture）")
        return 2
    saved = json.loads(src.read_text(encoding="utf-8"))
    diff = compare(saved, capture(project))
    if not diff:
        print(f"✓ 交付与当前工程态一致（指纹 {src}，采集于 {saved.get('captured_at')}）")
        return 0
    print(f"✗ 交付过期 / 被改动：{len(diff)} 处")
    for d in diff:
        print(f"  · {d}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
