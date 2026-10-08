#!/usr/bin/env python3
"""The visual scene review's record contract and the one append path.

**服务部分已退役（2026-09-26）。** 这个模块以前自带一个 HTTP 服务器
（`/review/`、`/timeline/timeline.json`、`/api/*`、固定端口 8899）。审阅面现在挂在公共缝
`planners-review-core` 上：页面由那个模组的宿主 serve（有插件时是 DSH 侧栏，没有时是
`scripts/serve-review.mjs`），页面与宿主通过桥说话。这里只剩**记录契约与落盘**——
也就是「作者的意见不能丢」这条性质真正住着的地方：

  ① 页面把一条记录写进 surface 声明的**一份**提交文件（宿主做覆盖写，页面自己合并）；
  ② `review_inbox.py` 收件，把提交翻译成 `feedback/<chapterId>.jsonl` 的**追加**；
  ③ 落盘走 `save_feedback` —— 先写 `.tmp` 再 `os.replace`，旧内容留在
     `feedback/.previous/<name>.jsonl`。

**追加语义与备份行为在这里，不在宿主里。** 宿主只落一份文件，怎么变成每章一份 JSONL
是本 Skill 自己的事（`references/architecture.md` 的缝 3）。

为什么追加不是 `edl_preview_serve.py` 那种整份替换：那个服务绑在 EDL 上、`/api/save`
替换一整份 `selections.json`；这里一次提交只加一条记录，每章一个文件。两者的保存语义
正好相反，共用一套 handler 就意味着要让那条最不该漂移的契约分叉。共享的是安全习惯，
不是代码。
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

PAGE_REL = Path("review/index.html")
TIMELINE_REL = Path("timeline/timeline.json")
SURFACE_REL = Path("review/review-surface.json")
SUBMISSIONS_REL = Path("review/review-submissions.json")
FEEDBACK_DIR = "feedback"
PREVIOUS_DIR = ".previous"
# 两个"按阶段落"的文件名 —— **唯一出处**。它们是"不针对某一个单位"的那类反馈的落点：
#   · storyboard：Plan 检查点（规划阶段那一遍）
#   · overall   ：整片意见（没有 chapterId/stepId，所以塞不进 feedback/<chapterId>.jsonl）
# 其余记录按 `chapterId` 折成 `feedback/<chapterId>.jsonl`（见 record_filename）。
STORYBOARD_FILE = "storyboard.jsonl"
OVERALL_FILE = "overall.jsonl"
# 审阅页必须带的宿主注入点。**这是那个守卫在新世界里的形状**：
# 旧世界它认 `fetch("/api/feedback"`（页面能不能把意见送进文件），
# 新世界页面不再自己 POST，能送进文件的唯一方式是被宿主 serve 时注入桥 ——
# 所以判据是「有没有留注入点」。它同时挡住两种过期的副本：
#   · 剪贴板时代（只有按钮，什么都不 POST）
#   · 直存时代（POST `/api/feedback`，但那个服务已经退役，写不进去）
# 老话仍然成立：把这两种页面交给作者，等于把意见丢进虚空。
PAGE_BRIDGE_MARKER = "{{REVIEW_BRIDGE}}"
# 旧判据的字符串：只用来**认出**直存时代的副本并给出针对它的提示。
LEGACY_SAVE_MARKER = 'fetch("/api/feedback"'
# Filename-safe = ASCII word characters, dash and CJK. Everything else is
# folded to "-" (see record_filename for why CJK must survive).
UNSAFE_NAME = re.compile(r"[^0-9A-Za-z_\-\u4e00-\u9fff]+")


def now_iso() -> str:
    """The same shape the page's `new Date().toISOString()` produces."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def record_filename(chapter_id: str) -> str:
    """`<chapterId>.jsonl`, with path-dangerous characters folded to "-".

    v1 (`archive/web-video-presentation/templates/vite.config.ts`) folded every
    non-ASCII character too, which turns a Chinese chapter id such as 「开场」
    into `---.jsonl` and files two chapters into the same file — a silent
    mis-filing, i.e. lost feedback. Chapter ids come from
    `timeline/grouping.json` and nothing enforces ASCII there, so only
    path-dangerous characters are folded here, and the page shows the file that
    was actually written.
    """
    name = UNSAFE_NAME.sub("-", str(chapter_id or "")).strip("-")
    if not name or name in {".", ".."}:
        name = "unknown"
    return f"{name}.jsonl"


def normalize_record(record: dict) -> dict:
    """Fill the two fields the agent protocol relies on, change nothing else.

    `status` defaults to "open" (v1 did the same); `createdAt` is filled with
    the server clock only when the page did not send one — the agent sorts
    rounds by it, so the field must exist. Every other field is written through
    verbatim, so a record that carries more than the page produces (e.g. a
    future `srtRange`/`codeVersion`) survives untouched.
    """
    out = dict(record)
    if not str(out.get("status") or "").strip():
        out["status"] = "open"
    if not str(out.get("createdAt") or "").strip():
        out["createdAt"] = now_iso()
    return out


def append_atomic(target: Path, record: dict, backup_dir: Path | None = None) -> dict:
    """Append one JSONL record by rewriting the file through a temp + rename.

    An append is not the dangerous part; a half-written line is. Composing the
    new content and `os.replace`-ing it means the file the agent reads is never
    partial, whatever happens mid-write. The previous version is copied into
    `backup_dir` first — a rolling single file, because a per-write timestamped
    copy would bury `feedback/` in backups during one review. The backup must
    NOT be named `*.jsonl` next to the original: the agent reads
    `feedback/*.jsonl`, and a backup sibling would come back as author feedback.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    previous = target.read_text(encoding="utf-8") if target.is_file() else ""
    backup = None
    if previous.strip() and backup_dir is not None:
        backup_dir.mkdir(parents=True, exist_ok=True)
        saved = backup_dir / target.name
        saved.write_text(previous, encoding="utf-8")
        backup = saved
    line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(previous + line, encoding="utf-8")
    os.replace(tmp, target)
    content = previous + line
    records = sum(1 for one in content.splitlines() if one.strip())
    return {
        "line": line,
        "records": records,
        "backup_path": str(backup) if backup else None,
        # 调用方（收件）要能逐条断言，而不是只看总行数。
        "appended": records - sum(1 for one in previous.splitlines() if one.strip()),
    }


def save_feedback(project: Path, filename: str, record: dict) -> dict:
    """The one save path the inbox and the tests use."""
    feedback_dir = project / FEEDBACK_DIR
    info = append_atomic(feedback_dir / filename, record, feedback_dir / PREVIOUS_DIR)
    return {
        "file": f"{FEEDBACK_DIR}/{filename}",
        "records": info["records"],
        "bytes": len(info["line"].encode("utf-8")),
        "previous": (
            f"{FEEDBACK_DIR}/{PREVIOUS_DIR}/{filename}" if info["backup_path"] else None
        ),
        "savedAt": now_iso(),
    }


def existing_feedback(project: Path) -> list[str]:
    feedback_dir = project / FEEDBACK_DIR
    if not feedback_dir.is_dir():
        return []
    return sorted(one.name for one in feedback_dir.glob("*.jsonl"))


def check_project(project: Path) -> list[str]:
    """Everything that must be true before promising the human a review page."""
    problems: list[str] = []
    page = project / PAGE_REL
    if not page.is_file():
        problems.append(
            f"缺少审阅页 {page}——先把 visual/assets/review-page-template.html "
            "复制到 <project>/review/index.html（见 references/review-ui.md）"
        )
    elif PAGE_BRIDGE_MARKER not in page.read_text(encoding="utf-8", errors="replace"):
        # 一份过期副本没有注入点：宿主 serve 时替换不到东西，桥永远不加载，
        # 页面看起来好好的、按保存什么都没有。整页拒绝，并说清是哪一种过期。
        if LEGACY_SAVE_MARKER in page.read_text(encoding="utf-8", errors="replace"):
            problems.append(
                f"{page} 是直存时代的审阅页（自己 POST 到已退役的 /api/feedback）——"
                "重新复制 visual/assets/review-page-template.html 覆盖它"
            )
        else:
            problems.append(
                f"{page} 是剪贴板时代的审阅页（只写剪贴板，连不上审阅宿主）——"
                "重新复制 visual/assets/review-page-template.html 覆盖它"
            )
    data_path = project / 'review/review_data.json'
    if not (project / TIMELINE_REL).is_file() and not data_path.is_file():
        problems.append(
            f"缺少 {project / TIMELINE_REL}——先按 references/visual-timeline.md 派生时间轴"
        )
    return problems


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="视觉审阅的记录契约（服务已退役，见模块 docstring）")
    parser.add_argument("project", help="HyperFrames 项目目录（含 review/ timeline/）")
    args = parser.parse_args()
    found = check_project(Path(args.project).expanduser().resolve())
    print(json.dumps({"ok": not found, "problems": found,
                      "feedback_files": existing_feedback(Path(args.project).expanduser().resolve())},
                     ensure_ascii=False, indent=1))
    raise SystemExit(2 if found else 0)
