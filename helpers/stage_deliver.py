#!/usr/bin/env python3
"""阶段 6 · 交付（deliver）—— 把"闸门 → 出片 → 核验 → 包装 → 指纹"串成一段。

契约见 `references/stages.md`。本脚本不重新实现交付：它按顺序调用既有工具，
统一退出码与下一步提示；旧命令继续可用。

    python3 helpers/stage_deliver.py status  --project <项目>
    python3 helpers/stage_deliver.py run     --project <项目> [--visuals <mp4>] [--no-person] [--out <目录>]
    python3 helpers/stage_deliver.py verify  --project <项目> --video <成片> [--deliver-dir <目录>]
    python3 helpers/stage_deliver.py export  --project <项目> [--out <目录>]
    python3 helpers/stage_deliver.py fingerprint capture|verify --project <项目>

退出码：0 完成 · 1 某条命令失败（含闸门拒绝）· 2 前置条件不满足。
"""
from __future__ import annotations

import os

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _stage import (EXIT_OK, EXIT_PREREQ, Failed, Prereq, Stage,  # noqa: E402
                    report_error, resolve_project)


def _state(project: Path, edit: Path) -> dict:
    out = project / "成品"
    state = {
        "review_submissions": (project / "review" / "review-submissions.json").is_file(),
        "feedback": sorted(p.name for p in (project / "feedback").glob("*.jsonl"))
        if (project / "feedback").is_dir() else [],
        "composition": (project / "composition").is_dir(),
        "visuals": (project / "composition" / "_render" / "visuals.mp4").is_file(),
        "deliverables": sorted(p.name for p in out.glob("*")) if out.is_dir() else [],
        "fingerprint": (out / "delivery.json").is_file(),
        "subtitles": (edit / "subtitles.srt").is_file(),
    }

    from render_gate import evaluate
    from state_fingerprint import capture, compare, entry, source_entries
    state["gate"] = evaluate(project, None, False)
    state["fingerprint_current"] = False
    state["report_current"] = False
    try:
        sources = source_entries(project)
        report = json.loads((out / f"{project.name}_核验报告.json").read_text(encoding="utf-8"))
        state["report_current"] = (report.get("ok") is True and report.get("delivery_ok") is True
             and report.get("source_fingerprint") == sources
             and report.get("output_identity") == entry(Path(report["output"]))
             and isinstance(report.get('input_identities'), dict) and bool(report['input_identities'])
             and all(record and record == entry(Path(record['path'])) for record in report['input_identities'].values()))
    except (OSError, ValueError, KeyError, TypeError):
        pass
    if state["fingerprint"]:
        try:
            state["fingerprint_current"] = not compare(json.loads((out / "delivery.json").read_text(encoding="utf-8")), capture(project))
        except (OSError, ValueError, KeyError, TypeError):
            pass
    state["stage_complete"] = bool(state["gate"]["ok"] and state["report_current"] and state["fingerprint_current"])
    state["human_approval"] = "status 不推断出片批准或反馈已解决"
    return state


def _next_step(project: Path, state: dict) -> str:
    if not state["gate"]["ok"]:
        return "重建并核对当前审阅版本；render_gate 的原因见 state.gate；作者确认出片后再 run"
    if not state["deliverables"]:
        return f"作者确认后出片：stage_deliver.py run --render --project {project}"
    if not state["report_current"]:
        return "现有文件不证明交付已完成；重新输出或核验当前文件及来源，失败时不要 capture"
    if not state["fingerprint_current"]:
        return f"本版核验报告有效；包装后核验副本，再记来源：stage_deliver.py fingerprint --fingerprint-action capture --project {project}"
    return "当前机械核验与指纹一致；发送前确认作者出片指令和未决意见已处理"


def do_status(project: Path, edit: Path, as_json: bool) -> int:
    state = _state(project, edit)
    nxt = _next_step(project, state)
    if as_json:
        print(json.dumps({"stage": "deliver", "action": "status", "ok": True,
                          "project": str(project), "state": state, "next": nxt},
                         ensure_ascii=False, indent=2))
    else:
        for key, value in state.items():
            mark = "✓" if value else "·"
            print(f"  {mark} {key}: {value}")
        print(f"  → 下一步：{nxt}")
    return EXIT_OK


def do_run(args) -> int:
    if args.no_audio:
        raise Prereq("--no-audio 只支持 verify；run 仍要求声音素材，无声合成未在此入口提供")
    project, edit = resolve_project(args.project)
    out_dir = Path(args.out).expanduser().resolve() if args.out else project / "成品"
    target = out_dir / f"{project.name}_成片.mp4"
    stage = Stage("deliver")
    if args.skip_gate and os.environ.get("DSH_TEST") != "1":
        raise Failed("--skip-gate 只允许测试夹具（DSH_TEST=1）；正式流程必须过 render_gate")
    forward = ["--visuals", args.visuals] if args.visuals else []
    forward += ["--person", args.person] if args.person else []
    forward += ["--audio", args.audio] if args.audio else []
    forward += ["--srt", args.srt_run] if args.srt_run else []
    forward += ["--out", str(out_dir)]
    forward += ["--burn-subtitles"] if args.burn_subtitles else []
    forward += ["--no-person"] if args.no_person else []
    forward += ["--render"] if args.render else []
    forward += ['--visuals-confirm-current'] if args.visuals_confirm_current else []
    forward += ["--json"] if args.json else []
    forward += ["--skip-gate"] if args.skip_gate else []
    stage.run("deliver.py", project, *forward)
    stage.next = f"本次合成与严格核验通过；包装后核验副本，再记指纹：stage_deliver.py fingerprint --fingerprint-action capture --project {project}"
    return stage.finish("run", args.json)


def do_verify(args) -> int:
    project, edit = resolve_project(args.project)
    forward = ["--video", args.video] if args.video else []
    forward += ["--deliver-dir", args.deliver_dir] if args.deliver_dir else []
    forward += ["--no-audio"] if args.no_audio else []
    forward += ['--media', args.audio] if args.audio else []
    forward += ['--srt', args.srt_run] if args.srt_run else []
    forward += ["--json"] if args.json else []
    stage = Stage("deliver")
    stage.run("verify_delivery.py", edit, *forward)
    stage.next = "核验通过再发送；过期就重新出片，不要改日期"
    return stage.finish("verify", args.json)


def do_export(args) -> int:
    project, edit = resolve_project(args.project)
    forward = ["--out", args.out] if args.out else []
    forward += ["--videos", *args.videos] if args.videos else []
    forward += ["--srt", *args.srt] if args.srt else []
    stage = Stage("deliver")
    stage.run("export_deliverables.py", edit, *forward)
    stage.next = f"先 verify --deliver-dir 核验包装副本，通过后记来源：stage_deliver.py fingerprint --fingerprint-action capture --project {project}"
    return stage.finish("export", args.json)


def do_fingerprint(args) -> int:
    project, _edit = resolve_project(args.project)
    stage = Stage("deliver")
    stage.run("state_fingerprint.py", args.fingerprint_action, project)
    stage.next = ("发送前：stage_deliver.py fingerprint --fingerprint-action verify --project <项目>"
                  if args.fingerprint_action == "capture"
                  else "一致才发送；不一致说明源改过，需要重新输出")
    return stage.finish(f"fingerprint {args.fingerprint_action}", args.json)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="阶段 6 · 交付：闸门 / 出片 / 核验 / 包装 / 指纹")
    ap.add_argument("action", choices=("status", "run", "verify", "export", "fingerprint"))
    ap.add_argument("--project", required=True, help="项目根目录")
    ap.add_argument("--visuals", default=None, help="run 时：已有画面层，跳过渲染")
    ap.add_argument('--visuals-confirm-current', action='store_true', help='run 时：明确人工确认已有画面属于当前版，补记来源')
    ap.add_argument("--person", default=None, help="run 时：人物轨")
    ap.add_argument("--audio", default=None, help="run 时：声音")
    ap.add_argument("--srt", nargs="+", default=None,
                    help="run 时：外挂字幕（一条）；export 时：字幕文件对（可多条）")
    ap.add_argument("--out", default=None, help="run/export 时：输出目录（默认 成品/）")
    ap.add_argument("--burn-subtitles", action="store_true", help="run 时：把字幕烧进画面")
    ap.add_argument("--no-person", action="store_true", help="run 时：没有人物轨（纯画面 + 旁白）")
    ap.add_argument("--render", action="store_true",
                    help="run 时：显式渲染画面层（默认不渲染，缺画面层会拒绝）")
    ap.add_argument("--skip-gate", action="store_true", help="run 时：仅测试夹具可跳过闸门")
    ap.add_argument("--video", default=None, help="verify 时：要核验的成片")
    ap.add_argument("--deliver-dir", default=None, help="verify 时：交付目录")
    ap.add_argument("--no-audio", action="store_true",
                    help="verify 时：这是无声画面轨（画面成片），不要求音轨")
    ap.add_argument("--videos", nargs="+", default=None, help="export 时：成片文件对")

    ap.add_argument("--fingerprint-action", choices=("capture", "verify"), default=None,
                    help="fingerprint 时：记指纹（capture）或核对（verify）")
    ap.add_argument("--json", action="store_true", help="给机器读的结果")
    args = ap.parse_args(argv)

    # run 的 --srt 只取一条；export 的 --srt 是文件对列表
    args.srt_run = args.srt[0] if args.srt else None
    try:
        if args.action == "status":
            project, edit = resolve_project(args.project)
            return do_status(project, edit, args.json)
        if args.action == "run":
            return do_run(args)
        if args.action == "verify":
            return do_verify(args)
        if args.action == "export":
            return do_export(args)
        if not args.fingerprint_action:
            raise Prereq("fingerprint 需要子动作：--fingerprint-action capture|verify")
        return do_fingerprint(args)
    except Prereq as exc:
        return report_error("deliver", args.action, exc, args.json, EXIT_PREREQ)
    except Failed as exc:
        return report_error("deliver", args.action, exc, args.json, exc.code)


if __name__ == "__main__":
    raise SystemExit(main())
