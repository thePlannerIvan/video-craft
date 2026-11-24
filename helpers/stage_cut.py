#!/usr/bin/env python3
"""阶段 2 · 剪口播（cut）—— 把"转写 → 取舍 → 剪点 → 逐字审阅 → 应用选择"串成一段。

契约见 `references/stages.md`。本脚本不重新实现剪法：它按顺序调用既有工具，
统一退出码与下一步提示；旧命令继续可用。

    python3 helpers/stage_cut.py status  --project <项目>
    python3 helpers/stage_cut.py prepare --project <项目> [--source <原始视频>] [--backend auto]
    python3 helpers/stage_cut.py review  --project <项目> [--surface-only]
    python3 helpers/stage_cut.py apply   --project <项目>

退出码：0 完成 · 1 某条命令失败 · 2 前置条件不满足（还没到这一步）。
"""
from __future__ import annotations

import argparse
import io
import json
import hashlib
import os
import re
import sys
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "_internal"))
from _edl import edl_digest, edl_raw_digest  # noqa: E402
from _stage import (EXIT_OK, EXIT_PREREQ, Failed, Prereq, Stage,  # noqa: E402
                    report_error, resolve_project)

SKILL_ROOT = Path(__file__).resolve().parent.parent


def _load_credentials() -> dict[str, str]:
    """Read non-empty credential keys from <skill_root>/.env and os.environ without exposing values."""
    creds: dict[str, str] = {}
    override = os.environ.get("VIDEO_CRAFT_ENV_FILE")
    if override is None:
        env_file: Path | None = SKILL_ROOT / ".env"
    elif override.strip().lower() in ("", "none", "0", "false"):
        env_file = None
    else:
        env_file = Path(override).expanduser()

    if env_file is not None and env_file.is_file():
        try:
            for raw in env_file.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                if line.startswith("export "):
                    line = line[7:].strip()
                k, v = line.split("=", 1)
                key = k.strip()
                val = v.strip().strip('"').strip("'")
                if key and val:
                    creds[key] = val
        except OSError:
            pass

    for key, val in os.environ.items():
        cleaned = val.strip()
        if cleaned:
            creds[key] = cleaned
    return creds


def _receipt(edit: Path) -> dict:
    try:
        data = json.loads((edit / "selections.applied.json").read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _digest(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def _edl_digests(edit: Path) -> tuple[str | None, str | None]:
    edl_file = edit / "edl.json"
    if not edl_file.is_file():
        return None, None
    return edl_digest(edl_file), edl_raw_digest(edl_file)


def _state(edit: Path) -> dict:
    transcripts = sorted((edit / "transcripts").glob("*.json")) if (edit / "transcripts").is_dir() else []
    page = edit / "edl_preview.html"
    digest, raw_digest = _edl_digests(edit)
    accepted = {d for d in (digest, raw_digest) if d}
    marker = re.search(r'video-craft-edl-sha256" content="([a-f0-9]+)"', page.read_text(encoding="utf-8")) if page.is_file() else None
    receipt = _receipt(edit)
    applied = bool(digest and receipt.get("edl_sha256") in accepted
                   and receipt.get("selection_sha256") == _digest(edit / "selections.json"))
    current = bool(digest and marker and marker[1] in accepted)
    return {
        "transcripts": [p.name for p in transcripts], "takes_packed": (edit / "takes_packed.md").is_file(),
        "edl": bool(digest), "selections": (edit / "selections.json").is_file(),
        "preview_page": page.is_file(), "preview_current": current,
        "selection_applied": applied, "stage_complete": False,
        "ready_for_time": current and applied,
        "subtitles": (edit / "subtitles.srt").is_file(),
        "timeline": ((edit / "timeline/timeline.json").is_file() or (edit.parent / "timeline/timeline.json").is_file()),
        "human_confirmation": "需作者核对当前逐字页；status 不推断批准",
    }


def _next_step(state: dict) -> str:
    if not state["transcripts"]:
        return "先转写：stage_cut.py prepare --project <项目> --source <原始视频>"
    if not state["edl"]:
        return "模型先确定取舍，再用 edl_from_keep.py / edl_edit.py 建 EDL；prepare 不代做剪辑决定"
    if not state["preview_current"]:
        return "出逐字审阅页：stage_cut.py review --project <项目>"
    if state["selections"] and not state["selection_applied"]:
        return "应用作者选择：stage_cut.py apply --project <项目>"
    return "核对当前逐字审阅页；作者确认剪点后进入时间与字幕（stages 步骤 5–6）"


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


def _run_transcribe(stage: Stage, edit: Path, source: str, backend: str) -> None:
    if backend == "seedasr":
        stage.run("transcribe_seedasr.py", "--edit-dir", edit, source)
        return
    if backend == "auto":
        creds = _load_credentials()
        if creds.get("DOUBAO_APP_ID") and creds.get("DOUBAO_ACCESS_TOKEN"):
            stage.run("transcribe_seedasr.py", "--edit-dir", edit, source)
            return
        if creds.get("ELEVENLABS_API_KEY"):
            stage.note("未检测到豆包语音凭据，改用 ElevenLabs Scribe（词级时间戳以 SeedASR 2.0 为准）")
            stage.run("transcribe.py", "--edit-dir", edit, "--audio-track", "0", "--backend", "scribe", source)
            return
        raise Prereq(
            "缺少词级转写凭据：请在 Skill 仓库根 .env 配置 DOUBAO_APP_ID / DOUBAO_ACCESS_TOKEN"
            "（首选豆包 SeedASR 2.0）或 ELEVENLABS_API_KEY；离线兜底显式传 --backend mlx。"
            "禁用 --backend ark 作为自动回退（见 GOTCHAS #1）。"
        )
    if backend == "ark":
        stage.note(
            "警告：显式指定 --backend ark（通用多模态模型非词级 ASR，时间会漂移 ±0.5–2s，"
            "违反 GOTCHAS #1 词级时间可靠性要求，禁止用于自动默认模式）"
        )
    stage.run("transcribe.py", "--edit-dir", edit, "--audio-track", "0", "--backend", backend, source)


def do_prepare(project: Path, edit: Path, source: str | None, backend: str, as_json: bool) -> int:
    stage = Stage("cut")
    state = _state(edit)
    if source:
        _run_transcribe(stage, edit, source, backend)
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
        stage.note("转写已打包；还没有 edl.json，剪辑尚未完成")
    stage.next = (f"出逐字审阅页：stage_cut.py review --project {project}" if edl_file.is_file() else
                  "模型先确定取舍，再用 edl_from_keep.py / edl_edit.py 建 EDL；完成后再 review")
    return stage.finish("prepare", as_json)


def _json_tail(text: str) -> dict:
    start = text.find("{")
    while start != -1:
        try:
            data = json.loads(text[start:])
            if isinstance(data, dict):
                return data
        except ValueError:
            pass
        start = text.find("{", start + 1)
    return {}


def _run_capture(stage: Stage, tool: str, *args: object) -> str:
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            stage.run(tool, *args)
    except Failed as exc:
        out = buf.getvalue().strip()
        if out:
            raise Failed(f"{exc}：{out}", exc.code) from exc
        raise
    return buf.getvalue()


def do_review(project: Path, edit: Path, as_json: bool, surface_only: bool = False) -> int:
    if not (edit / "edl.json").is_file():
        raise Prereq(f"还没有 {edit / 'edl.json'}")
    stage = Stage("cut")
    stage.run("edl_preview_build.py", edit)
    surface = edit / "edl_review_surface.json"

    if surface_only:
        out = _run_capture(stage, "edl_review_surface.py", edit, "--surface-only")
        info = _json_tail(out)
        surface_str = info.get("surface") or str(surface)
        stage.extra["surface"] = surface_str
        stage.extra["host_started"] = False
        stage.extra["host"] = None
        stage.note(f"surface 契约已就绪（--surface-only，未起宿主）：{surface_str}")
        stage.next = (f"把 surface 交给 review_open（或去掉 --surface-only 起本地宿主）；"
                      f"作者确认后应用选择：stage_cut.py apply --project {project}")
        return stage.finish("review", as_json)

    host: str | None = None
    try:
        from review_open_bridge import notify  # 可选：DSH 侧栏
    except ImportError:
        notify = None

    if notify is not None:
        out = _run_capture(stage, "edl_review_surface.py", edit, "--surface-only")
        info = _json_tail(out)
        surface_target = Path(info.get("surface") or surface)
        try:
            notify(surface_target)
            host = "DSH 侧栏（review_open）"
            stage.extra["surface"] = str(surface_target)
            stage.extra["host_started"] = True
            stage.extra["host"] = host
            stage.note(f"逐字审阅页已交付：{host}")
            stage.next = f"作者在侧栏逐字审阅页确认后应用选择：stage_cut.py apply --project {project}"
        except Exception:
            host = None

    if host is None:
        out = _run_capture(stage, "edl_review_surface.py", edit, "--no-open", "--port", "0")
        info = _json_tail(out)
        if not info and (edit / "review_host.json").is_file():
            try:
                info = json.loads((edit / "review_host.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                info = {}
        host_url = info.get("url") or info.get("entry") or "本地宿主"
        stage.extra["surface"] = info.get("surface") or str(surface)
        stage.extra["host_started"] = True
        stage.extra["host"] = host_url
        stage.note(
            f"本地浏览器宿主已启动：{host_url}"
            "（在浏览器打开后拖选剪点并点击「保存选择」；整段意见回对话说明）"
        )
        stage.next = f"打开 {host_url} 确认并保存选择后，执行：stage_cut.py apply --project {project}"

    return stage.finish("review", as_json)


def do_apply(project: Path, edit: Path, as_json: bool) -> int:
    if not (edit / "selections.json").is_file():
        raise Prereq(f"还没有 {edit / 'selections.json'}：先让作者在逐字审阅页提交选择")
    stage = Stage("cut")
    receipt = _receipt(edit)
    selection_digest = _digest(edit / "selections.json")
    digest, raw_digest = _edl_digests(edit)
    accepted = {d for d in (digest, raw_digest) if d}
    same_selection = receipt.get("selection_sha256") == selection_digest
    if same_selection and receipt.get("edl_sha256") not in accepted:
        raise Prereq("这份选择已应用过，但 EDL 后来又改变；先重建逐字页并确认新选择，避免重复剪辑")
    if same_selection:
        stage.note("相同选择已应用，本次仅重建逐字面，不再次改 EDL")
    else:
        stage.run("apply_selection.py", edit)
        digest, _ = _edl_digests(edit)
        (edit / "selections.applied.json").write_text(json.dumps({
            "selection_sha256": selection_digest, "edl_sha256": digest,
            "selection": json.loads((edit / "selections.json").read_text(encoding="utf-8")),
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    stage.run("edl_preview_build.py", edit)
    stage.run("edl_review_surface.py", edit, "--surface-only")
    stage.note("逐字页已重建；这一步不渲染底片")
    stage.next = "核对重建后的逐字面；作者确认剪点后进入时间与字幕（stages 步骤 5–6）"
    return stage.finish("apply", as_json)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="阶段 2 · 剪口播：转写 / 取舍 / 剪点 / 逐字审阅 / 应用选择")
    ap.add_argument("action", choices=("status", "prepare", "review", "apply"))
    ap.add_argument("--project", required=True, help="项目根目录")
    ap.add_argument("--source", default=None, help="prepare 时：原始视频/录音（还没有转写时给）")
    ap.add_argument("--backend", default="auto", choices=("auto", "seedasr", "scribe", "mlx", "ark"),
                    help="prepare 时：转写后端（默认 auto：首选 SeedASR 2.0 → Scribe；离线兜底显式传 mlx）")
    ap.add_argument("--surface-only", action="store_true",
                    help="review 时：只写并校验 surface 契约，不起本地浏览器宿主")
    ap.add_argument("--json", action="store_true", help="给机器读的结果")
    args = ap.parse_args(argv)

    try:
        project, edit = resolve_project(args.project)
        if args.action == "status":
            return do_status(project, edit, args.json)
        if args.action == "prepare":
            return do_prepare(project, edit, args.source, args.backend, args.json)
        if args.action == "review":
            return do_review(project, edit, args.json, surface_only=args.surface_only)
        return do_apply(project, edit, args.json)
    except Prereq as exc:
        return report_error("cut", args.action, exc, args.json, EXIT_PREREQ)
    except Failed as exc:
        return report_error("cut", args.action, exc, args.json, exc.code)


if __name__ == "__main__":
    raise SystemExit(main())
