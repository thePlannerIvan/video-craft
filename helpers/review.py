#!/usr/bin/env python3
"""`审阅` —— 一条命令把工程变成**能给人看的**页面，不绿不放行。

它藏起来的是四件零件 + 两道闸门
--------------------------------
旧流程要调用者自己拼：`check_live_stage.py` → `live_stage.py` → `build_review.py` →
`review_surface.py` →（可选）`review_inbox.py`。拿到手的是一堆输出，而不是"能给人看"的结果：
2026-10-21 那份页面**能提交反馈、但看不到画面、也没有声音**，为了让人听到声音，只能另写
一个原生播放器页面绕过它。这里把那件事收进模块。

接口（只有这一个）
------------------
    python3 helpers/review.py <project> [--open] [--no-live] [--json]

它保证（否则退出非 0 并指出该修哪一层）：
1. 活舞台契约通过（`check_live_stage.py`，退 0）；
2. 页面构建完成，并给出 surface 绝对路径（有 `review_open` 插件时直接交给它，没有就起本地宿主）；
3. **运行时判据通过**（`check_review_playable.py`）：挂上哪条播放通道、时间轴真的构建了、
   时长相符、能 seek 出画面、有声音且未静音。

两个"分层失败"的设计：静态契约红 → 修 composition；运行时红 → 修审阅装配/媒体通道。
调用者不需要知道这件事由五个脚本完成。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

HELPERS = Path(__file__).resolve().parent
sys.path.insert(0, str(HELPERS))


def _run(args: list[str], expect_ok: bool = True) -> tuple[int, str]:
    proc = subprocess.run([sys.executable, *args], capture_output=True, text=True)
    out = (proc.stdout or "") + (proc.stderr or "")
    if expect_ok and proc.returncode != 0:
        return proc.returncode, out
    return proc.returncode, out


def _json_tail(text: str) -> dict:
    start = text.find("{")
    while start != -1:
        try:
            return json.loads(text[start:])
        except json.JSONDecodeError:
            start = text.find("{", start + 1)
    return {}


def review(project: Path, open_surface: bool = True, live: bool = True,
           as_json: bool = False, port: int | None = None) -> int:
    steps: list[dict] = []

    def step(name: str, ok: bool, detail: str, fix_layer: str = "") -> bool:
        steps.append({"step": name, "ok": ok, "detail": detail, "fix": fix_layer})
        if not as_json:
            print(f"{'✓' if ok else '✗'} {name}" + (f" — {detail}" if detail else ""))
        return ok

    # 1) 静态契约：这份 composition 能不能进活舞台
    if live:
        code, out = _run([str(HELPERS / "check_live_stage.py"), str(project)])
        if not step("活舞台契约（静态）", code == 0, out.strip().splitlines()[-1] if out.strip() else "",
                    "composition/src：会执行逻辑的脚本必须在外部文件；注册名 = data-composition-id"):
            print("\n".join(out.strip().splitlines()[-8:]))
            return 1
        stage_args = [str(HELPERS / "live_stage.py"), str(project), "--json"]
        if port:
            stage_args += ["--port", str(port)]
        code, out = _run(stage_args)
        info = _json_tail(out)
        if not step("编译服务", code == 0 and info.get("ok", False),
                    f"stageUrl={info.get('stageUrl', '')}", "live_stage.py 的报错原文"):
            print(out.strip().splitlines()[-6:])
            return 1

    # 2) 构建审阅页
    code, out = _run([str(HELPERS / "build_review.py"), str(project), "--mode", "auto", "--slices", "off"])
    built = (project / "review" / "index.html").is_file()
    if not step("审阅页构建", code == 0 and built, "review/index.html",
                "build_review.py（看它报的 mediaNotes / 缺的输入）"):
        print("\n".join(out.strip().splitlines()[-10:]))
        return 1

    # 3) surface：有插件交给 review_open，没有就起本地宿主
    code, out = _run([str(HELPERS / "review_surface.py"), str(project), "--surface-only"])
    surface = (project / "review" / "review-surface.json")
    if not step("surface 契约", code == 0 and surface.is_file(), str(surface),
                "review_surface.py 的校验报错"):
        print("\n".join(out.strip().splitlines()[-8:]))
        return 1

    # 4) 运行时判据：这页到底能不能给人看
    code, out = _run([str(HELPERS / "check_review_playable.py"), str(project), "--quiet"])
    playable = code == 0
    detail = ""
    verdict = _json_tail(out)
    if verdict:
        fails = verdict.get("failures") or []
        detail = f"channel={verdict.get('channel')}；" + (
            "全部通过" if playable else "；".join(f["name"] for f in fails[:3]))
    step("运行时判据（能播 / 有画面 / 有声音）", playable, detail,
         "看上一行的 layer 提示：composition 或审阅装配")
    if not playable:
        print("\n".join(l for l in out.splitlines() if l.startswith(("✗", "  ")))[:2000])
        return 1

    # 5) 交付给人
    if open_surface:
        try:
            from review_open_bridge import notify  # 可选：DSH 侧栏
            notify(surface)
            host = "DSH 侧栏（review_open）"
        except Exception:
            code, out = _run([str(HELPERS / "review_surface.py"),
                              str(project), "--no-open", "--port", "0"])
            info = _json_tail(out)
            host = info.get("url") or info.get("path") or "本地宿主"
    else:
        host = "（--open 关掉了，surface 已就绪）"

    result = {
        "ok": True,
        "surface": str(surface),
        "host": host,
        "channel": (verdict or {}).get("channel"),
        "steps": steps,
        "next": "把 surface 交给 review_open（有插件）或打开 host；作者提交后跑 review_inbox.py 收件",
    }
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("project", type=Path)
    parser.add_argument("--no-open", dest="open_surface", action="store_false",
                        help="只准备 surface，不起宿主、不交给 review_open")
    parser.add_argument("--no-live", dest="live", action="store_false",
                        help="跳过活舞台（成片/预览通道项目用）")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--port", type=int, default=None,
                        help="编译服务端口；默认用 live_stage 的默认端口。别的工程占着它时会红，换一个端口")
    args = parser.parse_args(argv)
    return review(args.project.expanduser().resolve(), args.open_surface, args.live,
                  args.json, args.port)


if __name__ == "__main__":
    raise SystemExit(main())
