"""阶段脚本的公共壳：路径解析、统一退出码、JSON 输出、下一步提示。

阶段脚本不重新实现任何制作逻辑——它只把同一阶段里原本要手敲的几条命令串起来，
并把"缺什么 / 下一步做什么"说成人话。旧命令继续可用。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HELPERS = Path(__file__).resolve().parent

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_PREREQ = 2


class Prereq(Exception):
    """前置条件不满足：还没到能跑这一步的时候。"""


class Failed(Exception):
    """某条被包装的命令退非零：把它的退出码原样带出去。"""

    def __init__(self, message: str, code: int = EXIT_FAIL) -> None:
        super().__init__(message)
        self.code = code


def resolve_project(value: str) -> tuple[Path, Path]:
    """项目根 → (项目根, edit)。两个都不存在时给明确的前置错误。"""
    project = Path(value).expanduser().resolve()
    if not project.is_dir():
        raise Prereq(f"项目目录不存在：{project}")
    edit = project / "edit"
    if not edit.is_dir():
        raise Prereq(f"没有编辑目录：{edit}（先建项目或确认 --project 指对了）")
    return project, edit


class Stage:
    """一次阶段动作：跑若干条既有命令，收集结果，最后统一输出。"""

    def __init__(self, name: str) -> None:
        self.name = name
        self.steps: list[dict] = []
        self.notes: list[str] = []
        self.next: str | None = None

    def run(self, tool: str, *args: object, allow_fail: bool = False) -> int:
        cmd = [sys.executable, str(HELPERS / tool), *[str(a) for a in args]]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        ok = proc.returncode == 0
        self.steps.append({"tool": tool, "code": proc.returncode, "ok": ok})
        if proc.stdout:
            print(proc.stdout, end="")
        if proc.stderr:
            print(proc.stderr, end="", file=sys.stderr)
        if not ok and not allow_fail:
            raise Failed(f"{tool} 退出 {proc.returncode}", proc.returncode or EXIT_FAIL)
        return proc.returncode

    def note(self, text: str) -> None:
        self.notes.append(text)
        print(f"  · {text}")

    def finish(self, action: str, as_json: bool) -> int:
        payload = {
            "stage": self.name,
            "action": action,
            "ok": True,
            "steps": self.steps,
            "notes": self.notes,
            "next": self.next,
        }
        if as_json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        elif self.next:
            print(f"  → 下一步：{self.next}")
        return EXIT_OK


def report_error(stage_name: str, action: str, exc: Exception, as_json: bool,
                 code: int) -> int:
    if as_json:
        print(json.dumps({"stage": stage_name, "action": action, "ok": False,
                          "error": str(exc), "exit": code}, ensure_ascii=False, indent=2))
    else:
        print(f"✗ {stage_name} / {action}：{exc}", file=sys.stderr)
    return code
