#!/usr/bin/env python3
"""兼容 shim —— page 十步路线的 composition 生成（已存档）。

真正的代码在 `_legacy_page/generate-composition.py`。这里把它当作**模块**加载
（所以 `verify()` 等函数仍可被 import 与单测调用），同时保留 CLI 入口；
新项目不要再用它 —— 画面走 `helpers/film.py`，见 `references/legacy-page-route.md`。
"""
import importlib.util
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_LEGACY = _HERE / "_legacy_page" / "generate-composition.py"

for _p in (str(_HERE), str(_HERE / "_legacy_page")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

_SPEC = importlib.util.spec_from_file_location("_vc_legacy_generate_composition", _LEGACY)
_MOD = importlib.util.module_from_spec(_SPEC)
# 让存档模块按"还在原路径"自我定位：它的 SKILL_DIR / THEMES_DIR 都是
# 从 __file__ 推的，指到 _legacy_page 就会找不到 visual/themes（主题库已于 2026-10-22 退役，旧项目自备 .theme）。
_MOD.__file__ = str(_HERE / "generate-composition.py")
sys.modules["_vc_legacy_generate_composition"] = _MOD
_SPEC.loader.exec_module(_MOD)          # __name__ != "__main__"，所以不会自己跑 CLI

globals().update({k: v for k, v in vars(_MOD).items() if not k.startswith("__")})

if __name__ == "__main__":
    sys.stderr.write(
        "generate-composition.py 属于已归档的 page 十步路线，不能再用。\n"
        "  画面：helpers/film.py 拆原页 + 手写 composition（references/film.md）。\n"
        "  复活旧项目：references/legacy-page-route.md。\n")
    raise SystemExit(2)
