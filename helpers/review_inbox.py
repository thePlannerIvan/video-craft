#!/usr/bin/env python3
"""收件：把审阅面提交的那**一份**文件翻译成 `feedback/<chapterId>.jsonl` 的**追加**。

## 为什么需要这一层

缝只做两件事：页面怎么送达、提交怎么落盘。而**「落盘」在缝里是覆盖写一份文件**
（`serve-review.mjs` 的 `/__review/write` 就是 `writeFileSync`），本 Skill 的存储形状却是
**每章一个文件、只追加、旧内容留 `.previous/`**。形状对不上时不改本 Skill 的形状 ——
surface 声明一份提交文件，本模块收件时翻译。这是缝的设计（`planners-review-core/SKILL.md`
「不同形状的审阅面怎么落」里那一行「追加式日志」）。

## 幂等：靠内容哈希，不靠往记录里加字段

`feedback/<chapterId>.jsonl` 里每一条必须是页面产出的那些字段，**一个不多**（agent 协议与
`review-ui.md` 的 schema 就是那个形状）。所以去重不能往记录里塞 `recordId` —— 那会把
存储形状改掉。改用记录内容的 sha256 当游标，记在 `.inbox-cursor.json` 里：

  · 同一条记录被收两次（人重复点保存、或模型跑了两遍收件）→ 第二次是空操作；
  · 人真的重写了一遍同样的话 → `createdAt` 不同 → 哈希不同 → 是一条**新**意见，照收。

## 页面那侧为什么自己合并

宿主是覆盖写，所以页面每次保存都先 `readText` 读回这份提交文件、追加自己那条、再整体
`write`。这样即使模型还没收件，作者连写三条也不会丢前两条。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from visual_review_feedback import (          # noqa: E402
    OVERALL_FILE, STORYBOARD_FILE, SURFACE_REL, normalize_record, record_filename, save_feedback,
)

CURSOR_REL = "review/.inbox-cursor.json"
MAX_RECORDS = 500
# 两个"阶段"标识 → 各自的落点。两者都**只看记录自己带的 `phase`**（见 `is_storyboard`）。
#   · storyboard：Plan 检查点（规划阶段那一遍反馈）
#   · overall   ：整片意见 —— **不针对任何一屏**，所以它没有 `chapterId`/`stepId`，
#                 也正因为如此不能塞进 `feedback/<chapterId>.jsonl`。
# 规则（模组 design-and-porting-rules R10）：页面不许把逐单位当成唯一入口。
# 收件这一侧的对偶要求：整片那条**不许给它编一个假 `stepId`/`chapterId`** —— 那正是改形状。
STORYBOARD_ID = "storyboard"
OVERALL_ID = "overall"
PHASE_FILES = ((STORYBOARD_ID, STORYBOARD_FILE), (OVERALL_ID, OVERALL_FILE))


def cursor_path(project: Path) -> Path:
    return Path(project)/CURSOR_REL


def load_cursor(project: Path) -> set:
    try:
        doc = json.loads(cursor_path(project).read_text(encoding="utf-8"))
        return set(doc.get("imported") or [])
    except (OSError, ValueError):
        return set()


def save_cursor(project: Path, imported: set) -> None:
    path = cursor_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"imported": sorted(imported)}, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def record_hash(record: dict) -> str:
    """内容哈希。`sort_keys` 让它与键序无关；页面重排字段不会被当成新记录。"""
    canonical = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def submissions_path(project: Path) -> Path:
    """提交文件由 surface 声明（`feedback` 字段，相对 surface 文件）。"""
    surface = Path(project)/SURFACE_REL
    if not surface.is_file():
        raise ValueError("还没有审阅面：" + str(surface))
    doc = json.loads(surface.read_text(encoding="utf-8"))
    rel = doc.get("feedback")
    if not rel:
        raise ValueError("这份 surface 没有声明 feedback 文件，没有东西可收：" + str(surface))
    return (surface.parent/str(rel)).resolve()


def load_submissions(project: Path) -> list:
    path = submissions_path(project)
    if not path.is_file():
        return []
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as error:
        raise ValueError("提交文件不是 JSON：" + str(path) + "（" + str(error) + "）")
    records = doc.get("records")
    if records is None:
        raise ValueError("提交文件没有 records 数组：" + str(path))
    if not isinstance(records, list):
        raise ValueError("提交文件的 records 不是数组：" + str(path))
    if len(records) > MAX_RECORDS:
        raise ValueError("提交文件里有 " + str(len(records)) + " 条记录（上限 " + str(MAX_RECORDS) + "）：" + str(path))
    return [one for one in records if isinstance(one, dict)]


def is_storyboard(record: dict) -> bool:
    """这条是不是 Plan 检查点的记录 —— 只看**记录自己带的 `phase`**。

    以前靠**路由**分辨：页面有两个 POST 端点（`/api/feedback` 与
    `/api/storyboard-feedback`），服务端在后一个上 `record.setdefault("phase", "storyboard")`。
    缝只有**一份**提交文件、一个写入口，所以这个信息只能从记录里读。
    真实数据也确实是这么长的：`PPTSkillV2/feedback/storyboard.jsonl` 的每一条都带
    `phase: "storyboard"`，而它们的 `chapterId` 是 `painpoint`/`cta` 这些**真章节**。

    故意**不**看 `chapterId == "storyboard"`：那看起来像个便宜的后备，实际会**改记录的形状**
    ——一个真名叫 `storyboard` 的章节，经 `/api/feedback` 进来时旧代码不补 `phase`，补了就多一个字段。
    而且旧代码两条路的文件名本来就都是 `storyboard.jsonl`，不看它不会走错文件。
    """
    return phase_file(record) is not None


def phase_file(record: dict):
    """这条记录声明了哪个"阶段"→ 该落哪个文件；没声明就 None（走逐单位那条路）。

    **整片意见与 Plan 检查点是同一类东西**：它们都不是"对某一个单位的意见"，
    所以都靠记录自己带的 `phase` 定位，而不是靠编一个 chapterId/stepId 去凑。
    """
    phase = str(record.get("phase") or "").strip()
    for name, filename in PHASE_FILES:
        if phase == name:
            return filename
    return None


def route_of(record: dict) -> tuple:
    """一条记录该进哪个文件。Plan 检查点单走 `storyboard.jsonl`。

    返回 `(filename, record, error)`：`filename=None` 表示这条被拒，`error` 说明理由。
    **拒绝要出声**——静默丢一条意见正是这套东西最坏的失败方式。
    """
    filename = phase_file(record)
    if filename is not None:
        routed = dict(record)
        routed.setdefault("phase", str(record.get("phase")).strip())   # 与旧服务端同一个补法（此处是空操作）
        return filename, routed, None
    chapter_id = str(record.get("chapterId") or "").strip()
    if not chapter_id:
        return None, record, "缺少 chapterId"
    if not str(record.get("text") or "").strip():
        return None, record, "反馈内容为空"
    return record_filename(chapter_id), record, None


def import_submissions(project: Path, dry_run: bool = False) -> dict:
    """收件：读提交文件 → 逐条追加进 `feedback/<chapterId>.jsonl`（幂等）。

    返回一份能直接给模型看的收据：收了几条、跳了几条（已收过）、拒了几条（及理由）、
    每条落到哪个文件、旧内容备份在哪。
    """
    project = Path(project).expanduser().resolve()
    records = load_submissions(project)
    imported = load_cursor(project)
    receipt = {"ok": True, "submissions": str(submissions_path(project)),
               "seen": len(records), "imported": [], "skipped": [], "rejected": []}
    for index, record in enumerate(records):
        digest = record_hash(record)
        if digest in imported:
            receipt["skipped"].append({"index": index, "reason": "已经收过（内容哈希相同）"})
            continue
        filename, routed, error = route_of(record)
        if filename is None:
            receipt["rejected"].append({"index": index, "reason": error,
                                        "chapterId": routed.get("chapterId"),
                                        "record": routed})
            continue
        if dry_run:
            receipt["imported"].append({"index": index, "file": f"feedback/{filename}",
                                        "dry_run": True, "hash": digest})
            continue
        info = save_feedback(project, filename, normalize_record(routed))
        imported.add(digest)
        receipt["imported"].append({"index": index, **info, "hash": digest})
    if not dry_run:
        save_cursor(project, imported)
    receipt["ok"] = not receipt["rejected"]
    if receipt["rejected"]:
        receipt["next_action_zh"] = ("有记录被拒：作者的意见没进文件。先按上面每条的 reason 处理，"
                                     "再重跑收件。")
    elif receipt["imported"]:
        receipt["next_action_zh"] = "收件完成：按 references/review-ui.md 的 agent 协议处理 feedback/*.jsonl。"
    else:
        receipt["next_action_zh"] = "没有新记录。要么作者还没提交，要么这一批已经收过了。"
    return receipt


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="收件：审阅面的提交 → feedback/<chapterId>.jsonl 追加")
    parser.add_argument("project", help="HyperFrames 项目目录（含 review/ timeline/）")
    parser.add_argument("--dry-run", action="store_true", help="只报会收哪几条，不写文件、不动游标")
    args = parser.parse_args(argv)
    try:
        receipt = import_submissions(Path(args.project), dry_run=args.dry_run)
    except ValueError as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False, indent=1))
        return 2
    print(json.dumps(receipt, ensure_ascii=False, indent=1))
    return 0 if receipt["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
