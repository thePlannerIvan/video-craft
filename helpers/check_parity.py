#!/usr/bin/env python3
"""兼容 shim —— 页面十步路线已存档（page route archived）。

真正的代码在 `_legacy_page/check_parity.py`。这里按**原模块名**把它注册进 sys.modules，
并把原目录与本目录都放回 sys.path，好让存档模块继续解析兄弟 import（如 snapshot_input）。
`__file__` / `__name__` / 打补丁行为都与存档前一致，只为不打断旧调用方与测试。

命令行由 `cli()` **真转发**到存档模块的 `main()`（这里不能只 globals 转发：存档模块的
`if __name__ == "__main__":` 在 spec 加载时不会执行，命令行会静默退 0，把「没检查」
伪装成「检查通过」）。

适用范围只有**老 page 项目**（项目里真有 `timeline/choreography.json`）；recompose /
montage 项目没有 choreography.json，不要跑它。
退出码：0 一致 · 1 发现不一致 · 2 用法错误或缺 choreography.json。
"""
import importlib.util
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_LEGACY = _HERE / "_legacy_page" / "check_parity.py"

for _p in (str(_HERE), str(_HERE / "_legacy_page")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

_CURRENT = sys.modules.get("check_parity")
if _CURRENT is None or getattr(_CURRENT, "__file__", "") == __file__:
    _spec = importlib.util.spec_from_file_location("check_parity", _LEGACY)
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules["check_parity"] = _mod
    _spec.loader.exec_module(_mod)

_impl = sys.modules["check_parity"]
globals().update({k: v for k, v in vars(_impl).items() if not k.startswith("__")})


def cli(argv=None) -> int:
    """把命令行转发给存档模块的 `main()`；参数解析只覆盖这一条命令的形状。

    存档模块没有 argparse（它按 `sys.argv[1]` 取项目路径），所以这里必须自己提供
    `--help` 与退码语义，否则 `--help` 会被当成项目路径去读 choreography.json。
    """
    import argparse

    ap = argparse.ArgumentParser(
        prog="check_parity.py",
        description="审阅面 / 合成面一致性检查（page 路线已归档，只对老 page 项目有意义）",
        epilog="退出码：0 一致 · 1 有不一致 · 2 用法错误或缺 timeline/choreography.json",
    )
    ap.add_argument("project", type=Path, help="老 page 项目根（含 timeline/choreography.json）")
    args = ap.parse_args(argv)
    return _impl.main(args.project.expanduser().resolve())


if __name__ == "__main__":
    raise SystemExit(cli())
