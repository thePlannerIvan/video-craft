#!/usr/bin/env python3
"""film.py：原页拆解闸门。

2026-10-21 的根因是"没读原页就先动手"，所以这道闸门必须能变红：没填口播列 / 没映射
beat / 处置不合法，任何一种都要挡住 composition。
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

HELPERS = Path(__file__).parents[1] / "helpers"
sys.path.insert(0, str(HELPERS))

import film  # noqa: E402

SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1920 1080">
  <rect x="0" y="0" width="1920" height="1080" fill="#F5F5F2"/>
  <text x="100" y="168" font-size="52" font-weight="900">BBDO 的 GWTB：用四个词逼问品牌真正的定位策略</text>
  <rect x="100" y="225" width="400" height="570" fill="#1A1A1A"/>
  <text x="140" y="300" font-size="70" fill="#E2F827">GET</text>
  <text x="140" y="556" font-size="18">拒绝泛化的人口统计标签，锁定特定生活情境的精准切片。</text>
  <text x="100" y="1010" font-size="18">IVAN · 从 4A 方法论到生产力系统</text>
  <text x="1820" y="1010" font-size="18">06 / 27</text>
</svg>
"""


def _project(tmp: Path) -> Path:
    (tmp / "recompose").mkdir(parents=True, exist_ok=True)
    (tmp / "recompose/lines.json").write_text(json.dumps(
        {"beats": [{"id": "ch01", "title": "开场"}, {"id": "ch02", "title": "GWTB"}]}),
        encoding="utf-8")
    (tmp / "composition").mkdir(exist_ok=True)
    (tmp / "page.svg").write_text(SVG, encoding="utf-8")
    return tmp


class Extract(unittest.TestCase):
    def test_reads_elements_and_prefills_disposition(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = _project(Path(td))
            elements = film.extract_elements(tmp / "page.svg")
            kinds = {e["kind"] for e in elements}
            self.assertIn("字", kinds)
            self.assertIn("框", kinds)
            # 页脚署名与页码必须预填为"删"，长句预填为"拆"，大字号关键概念"保留"
            actions = {e["text"]: e["action"] for e in elements if e["kind"] == "字"}
            self.assertEqual(actions["06 / 27"], "删")
            self.assertEqual(actions["IVAN · 从 4A 方法论到生产力系统"], "删")
            self.assertEqual(actions["GET"], "保留")
            long_line = [a for t, a in actions.items() if t.startswith("拒绝泛化")][0]
            self.assertEqual(long_line, "拆")


class Gate(unittest.TestCase):
    def test_outline_then_verify_red_then_green(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = _project(Path(td))
            self.assertEqual(film.cmd_outline(tmp, "page_04", tmp / "page.svg"), 0)
            # 没映射 → 红
            self.assertEqual(film.cmd_verify(tmp, as_json=True), 1)
            film.write_map(tmp, ["ch01=page_04", "ch02=page_04"])
            # 口播列还空着 → 仍然红
            self.assertEqual(film.cmd_verify(tmp, as_json=True), 1)
            # 填满 → 绿
            md = (tmp / "pages/page_04.md")
            lines = []
            for line in md.read_text(encoding="utf-8").splitlines():
                if line.startswith("|") and line.count("|") >= 8 and not line.startswith("| #"):
                    cells = line.rstrip("|").split("|")
                    if not cells[-1].strip():
                        cells[-1] = " 这句口播 "
                    line = "|".join(cells) + "|"
                lines.append(line)
            text = "\n".join(lines).replace(
                "（一句话。写不出来说明还没读懂原页 —— 回去再读。）",
                "用四个词逼问品牌定位。")
            md.write_text(text, encoding="utf-8")
            self.assertEqual(film.cmd_verify(tmp, as_json=True), 0)


if __name__ == "__main__":
    unittest.main()
