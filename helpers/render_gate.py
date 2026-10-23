#!/usr/bin/env python3
"""渲染闸门：没有人看过这一版，就不许渲成片。

口头规则拦不住渲染。2026-10-21 的 XHS 项目里，"确认之后才渲"写在 SKILL 里，还是
渲出了一版 43 秒的成片——因为渲染命令本身不检查任何东西。这个工具把那条规则变成
一道可执行的闸门：**至少一条人工提交覆盖当前审阅快照**，才打印放行。

判据
----
1. `review/review_data.json` 存在，且带 `snapshot`（构建时算的工程指纹）；
2. `review/review-submissions.json`（surface 声明的那份）或 `feedback/*.jsonl` 里
   至少有一条记录，其 `snapshot` 等于当前快照；
3. `sourceManifest` 里的文件与快照记录一致 —— 有人看过之后源又改过、却没重建审阅，
   那条提交就不覆盖"现在这一版"。

工程态预览不拦：`--engineering --out <project>/edit/_engineering/xxx.mp4` 放行，
但输出必须真的落在 `edit/_engineering/` 里，不能拿它渲 `final.mp4`。

用法与退出码
------------
    python3 helpers/render_gate.py <project>
    python3 helpers/render_gate.py <project> --out <final.mp4>
    python3 helpers/render_gate.py <project> --engineering --out <edit/_engineering/cut.mp4>
    python3 helpers/render_gate.py <project> --json

退出 0 = 放行；1 = 拒绝；2 = 无法判断（缺审阅数据，先 build_review）。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SURFACE_REL = "review/review-surface.json"
SUBMISSIONS_REL = "review/review-submissions.json"
REVIEW_DATA_REL = "review/review_data.json"
FEEDBACK_DIR = "feedback"
ENGINEERING_REL = "edit/_engineering"


def project_root(arg: str) -> Path:
    """统一实现见 `helpers/_paths.py`（合并地图 M3）。"""
    from _paths import resolve
    return resolve(arg)[0]


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def submissions_path(project: Path) -> Path:
    """surface 声明哪份提交文件，就用哪份；没有 surface 时退回默认名。"""
    surface = project / SURFACE_REL
    doc = read_json(surface)
    if isinstance(doc, dict) and doc.get("feedback"):
        return (surface.parent / str(doc["feedback"])).resolve()
    return project / SUBMISSIONS_REL


def load_records(project: Path) -> tuple[list[dict], list[str]]:
    """(提交记录, 来源说明). 提交文件与 feedback/*.jsonl 都读。"""
    records: list[dict] = []
    sources: list[str] = []
    path = submissions_path(project)
    doc = read_json(path)
    if isinstance(doc, dict) and isinstance(doc.get("records"), list):
        records.extend(r for r in doc["records"] if isinstance(r, dict))
        sources.append(str(path.relative_to(project)) if path.is_relative_to(project) else str(path))
    for extra in sorted((project / FEEDBACK_DIR).glob("*.jsonl")):
        try:
            lines = extra.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        before = len(records)
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except ValueError:
                continue
            if isinstance(item, dict):
                records.append(item)
        if len(records) > before:
            sources.append(str(extra.relative_to(project)))
    return records, sources


def manifest_drift(project: Path, manifest) -> list[str]:
    """sourceManifest 与磁盘不一致的条目（文件被改 / 被删 / 被换）。"""
    drift = []
    if not isinstance(manifest, list) or not manifest:
        return ['缺 sourceManifest；旧审阅请重新 build_review.py 并核对新版本']
    from state_fingerprint import sha256, source_paths
    known = {str(x.get('path')) for x in manifest if isinstance(x, dict)}
    critical = [key for key in source_paths(project, include_review=False) if key.startswith('composition/')]
    critical += [key for key in ('edit/edl.json', 'edit/subtitles.srt', 'timeline/timeline.json',
                                  'edit/timeline/timeline.json') if (project / key).is_file()]
    for key in critical:
        if key not in known: drift.append(f'{key}（缺关键来源记录；重新 build_review.py）')
    for item in manifest:
        if not isinstance(item, dict):
            drift.append('sourceManifest 条目无效；重新 build_review.py')
            continue
        rel = str(item.get("path") or "")
        if not rel:
            drift.append('sourceManifest 缺 path；重新 build_review.py')
            continue
        path = project / rel
        if not path.is_file():
            drift.append(f"{rel}（不在了）")
            continue
        digest = item.get('sha256')
        if not isinstance(digest, str) or len(digest) != 64:
            drift.append(f'{rel}（缺内容哈希；旧清单需重新 build_review.py）')
        elif item.get('size') != path.stat().st_size or digest != sha256(path):
            drift.append(f'{rel}（内容已变）')
    return drift


def _latest(records: list[dict]) -> str:
    stamps = [str(r.get("createdAt") or "") for r in records]
    stamps = [s for s in stamps if s]
    return max(stamps) if stamps else "时间未记录"


def evaluate(project: Path, out: Path | None, engineering: bool) -> dict:
    report: dict = {
        "ok": False, "evaluable": True, "project": str(project),
        "out": str(out) if out else None, "engineering": engineering,
        "reasons": [], "notes": [], "snapshot": None,
        "submissions": 0, "covering": 0, "sources": [],
    }

    if engineering:
        tip = project / ENGINEERING_REL
        if out is None:
            report["reasons"].append(
                "--engineering 必须同时给 --out，并落在 "
                f"{ENGINEERING_REL}/ 下：工程态预览也要有地方落，"
                "而且这个开关不能用来渲成片")
            return report
        try:
            out.resolve().relative_to(tip.resolve())
        except ValueError:
            report["reasons"].append(
                f"--engineering 的 --out 必须落在 {ENGINEERING_REL}/ 里，"
                f"收到 {out}。成片不走这条路")
            return report
        report.update(ok=True, engineeringBypass=True)
        report["notes"].append(
            "工程态预览：只允许落在 edit/_engineering/；它不是交付成片，"
            "不能改个文件名当成品")
        return report

    data_path = project / REVIEW_DATA_REL
    data = read_json(data_path)
    if not isinstance(data, dict):
        report["evaluable"] = False
        report["reasons"].append(
            f"读不到 {REVIEW_DATA_REL}：还没有审阅快照。"
            "先跑 build_review.py 并交给人审")
        return report
    snapshot = str(data.get("snapshot") or "").strip()
    if not snapshot:
        report["evaluable"] = False
        report["reasons"].append(
            f"{REVIEW_DATA_REL} 没有 snapshot 字段：这份审阅数据不是当前构建器写的，"
            "无法判断人看的是哪一版。重新 build_review")
        return report
    report["snapshot"] = snapshot

    drift = manifest_drift(project, data.get("sourceManifest"))
    if drift:
        report["reasons"].append(
            "审阅快照之后源又改过，这一版还没重建："
            + "、".join(drift[:6]) + ("…" if len(drift) > 6 else ""))
        report["notes"].append(
            "重新 build_review.py，让人看过新一版再渲；旧提交不覆盖新源码")

    records, sources = load_records(project)
    report["submissions"] = len(records)
    report["sources"] = sources
    covering = [r for r in records if str(r.get("snapshot") or "") == snapshot]
    report["covering"] = len(covering)
    if not records:
        report["reasons"].append(
            "没有任何人工提交：先把这一版交给人审（review_open），"
            "人提交后再渲染")
    elif not covering:
        seen = sorted({str(r.get("snapshot") or "（未记录）") for r in records})
        report["reasons"].append(
            "有提交，但没有一条覆盖当前快照 "
            f"{snapshot}。已有提交对应的快照：{'、'.join(seen[:5])}"
            + ("…" if len(seen) > 5 else ""))
        report["notes"].append(
            "提交只证明人看过它自己那一版；改过源之后必须重建审阅并重新提交")
    else:
        report["notes"].append(
            f"{len(covering)} 条人工提交覆盖当前快照（最近 {_latest(covering)}）")

    report["ok"] = not report["reasons"]
    return report


def print_report(report: dict) -> None:
    print(f"渲染闸门 · {report['project']}")
    if report.get("engineeringBypass"):
        print("  ✓ 工程态预览（edit/_engineering/）—— 不要求人工提交")
        for note in report["notes"]:
            print(f"    {note}")
        print("放行：这只是工程态，不是成片。")
        return
    print(f"  当前审阅快照  {report.get('snapshot') or '（没有）'}")
    print(f"  人工提交      {report.get('submissions', 0)} 条，"
          f"覆盖当前快照 {report.get('covering', 0)} 条")
    if report.get("sources"):
        print(f"  提交来源      {'、'.join(report['sources'])}")
    for note in report["notes"]:
        print(f"  · {note}")
    print()
    if report["ok"]:
        print("放行：这一版有人看过，可以渲染"
              + (f" → {report['out']}" if report.get("out") else ""))
        return
    print("拒绝渲染：")
    for reason in report["reasons"]:
        print(f"  × {reason}")
    print()
    print("先 build_review 交给人审：")
    print(f'  python3 "<craft>/helpers/build_review.py" "{report["project"]}" --mode auto')
    print(f'  python3 "<craft>/helpers/review_surface.py" "{report["project"]}" --surface-only')
    print("人提交之后再重跑本闸门。工程态预览用 --engineering --out edit/_engineering/...")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="渲染前闸门：至少一条人工提交覆盖当前审阅快照才放行",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="退出码：0 放行；1 拒绝；2 无法判断（缺审阅数据）。")
    ap.add_argument("project", help="项目根（也可以是 edit/）")
    ap.add_argument("--out", type=Path, default=None,
                    help="即将渲染的输出路径（工程态必须落在 edit/_engineering/）")
    ap.add_argument("--engineering", action="store_true",
                    help="工程态预览放行开关；必须配 --out 且落在 edit/_engineering/")
    ap.add_argument("--json", action="store_true", help="输出机器可读结果")
    args = ap.parse_args(argv)

    project = project_root(args.project)
    if not project.is_dir():
        print(f"✗ 项目不存在：{project}", file=sys.stderr)
        return 2
    out = args.out.expanduser() if args.out else None
    if out is not None and not out.is_absolute():
        out = (project / out).resolve()
    report = evaluate(project, out, args.engineering)
    report["checkedAt"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_report(report)
    if report["ok"]:
        return 0
    return 1 if report.get("evaluable", True) else 2


if __name__ == "__main__":
    sys.exit(main())
