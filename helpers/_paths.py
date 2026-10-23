"""项目路径的统一解析（合并地图 M3）。

现状：`render_gate` / `live_stage` / `studio_notes` / `export_video` / `build_review`
各自推断"项目根与剪辑目录"，规则略有出入——传错目录时不报错，只是识别成另一个目录。
这里先建立唯一的解析，再逐个替换调用方（一次一处）。

规则（现有五处规则的并集）：

- 传入 `edit/`、`review/`、`成品/` 这类子目录 → 项目根是它的父目录；
- 传入项目根 → 项目根就是它；
- 剪辑目录优先 `<root>/edit`；不存在但 root 自己有 `edl.json` → root 就是剪辑目录。

不做判断：目录不存在时由调用方决定是报错还是继续。
"""
from __future__ import annotations

from pathlib import Path

PROJECT_SUBDIRS = ("edit", "review", "成品")


def timeline_file(edit_dir: str | Path) -> Path | None:
    """找这份工程的画面时间轴：`<edit>/timeline/` 或 `<project>/timeline/`。"""
    edit = Path(edit_dir).expanduser().resolve()
    import json
    candidates = [p for p in (edit / "timeline/timeline.json",
                             edit.parent / "timeline/timeline.json") if p.is_file()]
    if len(candidates) < 2:
        return candidates[0] if candidates else None
    try:
        docs = [json.loads(p.read_text(encoding="utf-8")) for p in candidates]
    except (OSError, ValueError) as exc:
        raise ValueError(f"两处时间轴无法确认一致：{candidates}；先备份并统一采用位置") from exc
    if docs[0] != docs[1]:
        detail = "；".join(f"{p} ({d.get('timeSource') or d.get('source') or 'unmarked'})"
                           for p, d in zip(candidates, docs))
        raise ValueError(f"时间轴冲突：{detail}；先备份两份，明确采用版并迁移到唯一位置，不自动覆盖")
    return candidates[-1]


def timeline_span_ms(path: str | Path) -> int | None:
    """时间轴末段结束时间（毫秒）；读不到返回 None。"""
    import json
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    chapters = data.get("chapters") or []
    steps = [s for ch in chapters for s in (ch.get("steps") or [])]
    if not steps:
        return None
    end = steps[-1].get("endMs")
    return int(end) if isinstance(end, (int, float)) else None


def check_timeline_output(edit_dir: str | Path, output: str | Path) -> None:
    """A writer must not leave a second timeline for other consumers to select."""
    edit, target = Path(edit_dir).resolve(), Path(output).resolve()
    timeline_file(edit)  # report conflicting versions with their declared sources
    others = [p for p in (edit / "timeline/timeline.json", edit.parent / "timeline/timeline.json")
              if p.is_file() and p.resolve() != target]
    if others:
        raise ValueError(f"写入 {target} 会留下另一处时间轴 {others}；先备份并迁移到唯一采用位置")


def timeline_source(path: str | Path) -> str | None:
    """时间轴自己声明的时间来源：measured / measured-guessed / projected / nominal。"""
    import json
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    value = data.get("timeSource")
    return value if isinstance(value, str) and value else None


def resolve(target: str | Path) -> tuple[Path, Path]:
    """→ `(project_root, edit_dir)`；两者都是绝对路径。"""
    path = Path(target).expanduser().resolve()
    root = path.parent if path.name in PROJECT_SUBDIRS else path
    edit = root / "edit"
    if not edit.is_dir() and (root / "edl.json").is_file():
        edit = root
    return root, edit
