#!/usr/bin/env python3
"""The review-page template's static guardrail, wired into the default test run.

Two jobs, and the second matters more than the first:

1. `test_template_is_clean` — the regression pin. Six defects shipped at once in
   this template and the author found every one by hand while two browser tests sat
   dead. Green here means those seven shapes are gone; it does **not** mean the page
   works (see `architecture.md`).

2. `test_checks_are_not_vacuous` — GOTCHA #30 is "a criterion that can never fail".
   A regex check nobody ever sees fail is indistinguishable from a broken one, so
   every check must be provably triggered by the defect it guards. Adding a check
   without a proof, or deleting a proof, fails here.

The checks themselves live in `helpers/check_review_template.py` so they can also
run standalone (`python3 helpers/check_review_template.py`) and over another copy
(`--template PATH`).
"""
import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path

HELPERS = Path(__file__).resolve().parents[1] / "helpers"
CHECKER = HELPERS / "_internal" / "check_review_template.py"

spec = importlib.util.spec_from_file_location("check_review_template", CHECKER)
check_review_template = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_review_template)


class ReviewTemplateGuardrailTest(unittest.TestCase):
    def test_template_is_clean(self):
        report = check_review_template.check_template(check_review_template.DEFAULT_TEMPLATE)
        if report["failed"]:
            lines = []
            for r in report["checks"]:
                for f in r["findings"]:
                    lines.append(f"  [{r['code']}] {f}")
            self.fail(f"{report['failed']} 类静态缺陷留在审阅页模板里：\n" + "\n".join(lines))

    def test_checks_are_not_vacuous(self):
        """每条检查都必须能在「缺陷被打回来」的副本上响起来。"""
        proc = subprocess.run([sys.executable, str(CHECKER), "--prove"],
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0,
                         f"有检查是空洞的（永远不会失败）：\n{proc.stdout}\n{proc.stderr}")

    def test_every_check_has_a_proof(self):
        """新增检查必须同时给一份自证，否则它可能只是永远绿的一行。"""
        codes = {code for code, _t, _fn in check_review_template.CHECKS}
        proofs = set(check_review_template.PROOFS)
        self.assertEqual(codes, proofs,
                         f"没有自证的检查：{codes - proofs}；"
                         f"没有对应检查的自证：{proofs - codes}")

    def test_s10_catches_removed_controls_and_engineering_jargon(self):
        """S10 必须能抓住已下线控件和用户可见工程术语，但不误伤注释。"""
        codes = {code for code, _t, _fn in check_review_template.CHECKS}
        self.assertIn("S10", codes)
        self.assertNotIn("verbatim-iframe-wrap", check_review_template.STAGE_WRAPS)

        clean = check_review_template.DEFAULT_TEMPLATE.read_text(encoding="utf-8")
        s10 = dict((c, fn) for c, _t, fn in check_review_template.CHECKS)["S10"]

        # 注释里提到不误报
        with_comment = clean.replace(
            "</body>",
            "<!-- #view-verbatim-btn live_stage.py composition -->\n</body>",
            1,
        )
        self.assertEqual(s10(with_comment), [])

        bad_snippets = [
            '<button type="button" id="view-verbatim-btn">逐字剪辑</button>',
            '<div id="verbatim-iframe-wrap" hidden></div>',
            '<div id="density-panel" hidden></div>',
            '<div id="elem-edit-bar" hidden></div>',
            '<select id="fb-type"><option value="visual">画面与版式</option></select>',
            '<script>const msg1 = "请先跑 helpers/live_stage.py";</script>',
            '<script>const msg2 = "运行 edl_review_surface.py";</script>',
            '<script>const msg3 = "调用 review_open 打开";</script>',
            '<script>const msg4 = "没有可播的活 composition";</script>',
        ]
        for snippet in bad_snippets:
            with self.subTest(snippet=snippet):
                mutated = clean.replace("</body>", f"{snippet}\n</body>", 1)
                self.assertTrue(s10(mutated), f"S10 未拦住回归片段：{snippet}")


if __name__ == "__main__":
    unittest.main()
