#!/usr/bin/env python3
"""兼容 shim —— 页面十步路线已存档（page route archived）。

真正的代码在 `_legacy_page/check_parity.py`。这里按**原模块名**把它注册进 sys.modules，
并把原目录与本目录都放回 sys.path，好让存档模块继续解析兄弟 import（如 snapshot_input）。
`__file__` / `__name__` / 打补丁行为都与存档前一致，只为不打断旧调用方与测试。
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
