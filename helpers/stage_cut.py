#!/usr/bin/env python3
"""阶段 2 · 剪口播（cut）—— 把"转写 → 取舍 → 剪点 → 逐字审阅 → 应用选择"串成一段。

契约见 `references/stages.md`。本脚本不重新实现剪法：它按顺序调用既有工具，
统一退出码与下一步提示；旧命令继续可用。

    python3 helpers/stage_cut.py status  --project <项目>
    python3 helpers/stage_cut.py prepare --project <项目> [--source <原始视频>] [--backend auto]
    python3 helpers/stage_cut.py review  --project <项目>
    python3 helpers/stage_cut.py apply   --project <项目>

退出码：0 完成 · 1 某条命令失败 · 2 前置条件不满足（还没到这一步）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _stage import (EXIT_OK, EXIT_PREREQ, Failed, Prereq, Stage,  # noqa: E402
                    report_error, resolve_project)


def _state(edit: Path) -> dict:
    transcripts = sorted((edit / "transcripts").glob("*.json")) if (edit / "transcripts").is_dir() else []
    return {
        "transcripts": [p.name for p in transcripts],
        "takes_packed": (edit / "takes_packed.md").is_file(),
        "edl": (edit / "edl.json").is_file(),
        "selections": (edit / "selections.json").is_file(),
        "preview_page": (edit / "edl_preview.html").is_file(),
        "subtitles": (edit / "subtitles.srt").is_file(),
        "timeline": ((edit / "timeline" / "timeline.json").is_file()
                     or (edit.parent / "timeline" / "timeline.json").is_file()),
    }


def _next_step(state: dict) -> str:
    if not state["transcripts"]:
        return "先转写：stage_cut.py prepare --project <项目> --source <原始视频>"
    if not state["edl"]:
        return "建 EDL：stage_cut.py prepare --project <项目>"
    if not state["preview_page"]:
        return "出逐字审阅页：stage_cut.py review --project <项目>"
    if state["selections"]:
        return "应用作者选择：stage_cut.py apply --project <项目>"
    return "去「时间与字幕」阶段（见 references/stages.md 第 3 段）"


def do_status(project: Path, edit: Path, as_json: bool) -> int:
    state = _state(edit)
    nxt = _next_step(state)
    if as_json:
        print(json.dumps({"stage": "cut", "action": "status", "ok": True,
                          "project": str(project), "edit": str(edit),
                          "state": state, "next": nxt}, ensure_ascii=False, indent=2))
    else:
        for key, value in state.items():
            mark = "✓" if value else "·"
            print(f"  {mark} {key}: {value}")
        print(f"  → 下一步：{nxt}")
    return EXIT_OK


def do_prepare(project: Path, edit: Path, source: str | None, backend: str, as_json: bool) -> int:
    stage = Stage("cut")
    state = _state(edit)
    if source:
        stage.run("transcribe.py", "--edit-dir", edit, "--audio-track", "0",
                  "--backend", backend, source)
        stage.note("转写完成，接下来打包成阅读视图并检查剪点")
    elif not state["transcripts"]:
        raise Prereq("还没有转写产物：加 --source <原始视频>，或先把 transcripts/ 放进来")
    stage.run("pack_transcripts.py", "--edit-dir", edit)
    edl_file = edit / "edl.json"
    if edl_file.is_file():
        try:
            ranges = json.loads(edl_file.read_text(encoding="utf-8")).get("ranges") or []
        except (OSError, ValueError):
            ranges = []
        if len(ranges) <= 1:
            stage.note("EDL 只有一段（成品轨）：跳过气口体检，停顿是剪辑结果不是遗漏")
        else:
            stage.run("check_edl.py", edit, "--max-pause", "0.8")
    else:
        stage.note("还没有 edl.json：先用转录结果定取舍，再回来跑一次 prepare")
    stage.next = f"出逐字审阅页：stage_cut.py review --project {project}"
    return stage.finish("prepare", as_json)


def do_review(project: Path, edit: Path, as_json: bool) -> int:
    if not (edit / "edl.json").is_file():
        raise Prereq(f"还没有 {edit / 'edl.json'}")
    stage = Stage("cut")
    stage.run("edl_preview_build.py", edit)
    stage.run("edl_review_surface.py", edit, "--surface-only")
    stage.next = f"作者确认后应用选择：stage_cut.py apply --project {project}"
    return stage.finish("review", as_json)


def do_apply(project: Path, edit: Path, as_json: bool) -> int:
    if not (edit / "selections.json").is_file():
        raise Prereq(f"还没有 {edit / 'selections.json'}：先让作者在逐字审阅页提交选择")
    stage = Stage("cut")
    stage.run("apply_selection.py", edit)
    stage.note("EDL 已按选择更新；这一步不改底片")
    stage.next = "去「时间与字幕」阶段（references/stages.md 第 3 段）"
    return stage.finish("apply", as_json)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="阶段 2 · 剪口播：转写 / 取舍 / 剪点 / 逐字审阅 / 应用选择")
    ap.add_argument("action", choices=("status", "prepare", "review", "apply"))
    ap.add_argument("--project", required=True, help="项目根目录")
    ap.add_argument("--source", default=None, help="prepare 时：原始视频/录音（还没有转写时给）")
    ap.add_argument("--backend", default="auto", choices=("auto", "scribe", "ark", "mlx"),
                    help="prepare 时：转写后端，默认 auto")
    ap.add_argument("--json", action="store_true", help="给机器读的结果")
    args = ap.parse_args(argv)

    try:
        project, edit = resolve_project(args.project)
        if args.action == "status":
            return do_status(project, edit, args.json)
        if args.action == "prepare":
            return do_prepare(project, edit, args.source, args.backend, args.json)
        if args.action == "review":
            return do_review(project, edit, args.json)
        return do_apply(project, edit, args.json)
    except Prereq as exc:
        return report_error("cut", args.action, exc, args.json, EXIT_PREREQ)
    except Failed as exc:
        return report_error("cut", args.action, exc, args.json, exc.code)


if __name__ == "__main__":
    raise SystemExit(main())
