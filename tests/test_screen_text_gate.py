"""The screen-text gate: the surface it must see, and the names it must not know.

① 视频路线的画面源是 `_internal/02_svg_source/*.svg`。不扫这里，做画面接手之后
   闸门会把「一个字都没查」报成 OK —— 这正是它今天最贵的那种通过。
② 上屏文字与花字的声明归上游内容契约（`deliverable/visual-plan.json`）：花字层、
   标了「文字：」的 `must_show`、以及整条都算字的 `exact_labels`。闸门只读它，
   不另立第二份声明（旧的 `on_screen_text.json` 没有任何生产者）。
③ 过程材料按**结构**跳过，不按上游的名字：上游正在合并改名，任何硬编码的上游
   目录名或产物名都会在改名当天静默失效。
④ 判定只拦「在任何风格里都是缺陷」的东西。`样张/预览/草稿/审阅/缺口` 在别的题材
   里是正当代词，只报不拦；声明与渲染的差集同样只报不拦。禁词表归闸门自己，
   且不许误伤普通文字（`beat` 只在编号形态下是工程话，`EDL`/`HF` 只在成词时命中）。
"""
import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

HELPERS = Path(__file__).parents[1] / "helpers"


def load(name: str):
    spec = importlib.util.spec_from_file_location(f"video_craft_{name}", HELPERS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


GATE = load("check_screen_text")


def run_gate(*argv: str) -> tuple[int, str]:
    """Run the gate on `argv` and return `(exit code, stdout)`."""
    out = io.StringIO()
    old = sys.argv
    sys.argv = ["check_screen_text.py", *argv]
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = GATE.main()
    finally:
        sys.argv = old
    return code, out.getvalue()


class GateCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def write(self, rel: str, text: str) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def plan(self, screens: list[dict]) -> Path:
        return self.write("deliverable/visual-plan.json",
                          json.dumps({"contract_version": "5.0", "screens": screens},
                                     ensure_ascii=False))


class PictureSource(GateCase):
    """① 做画面产出的画面必须进扫描面。"""

    def test_picture_source_svg_is_scanned(self):
        self.write("_internal/02_svg_source/screen-beat-01.svg",
                   '<svg xmlns="http://www.w3.org/2000/svg">'
                   '<text x="10" y="20">10× 加速 · 中段停一下</text></svg>')
        code, out = run_gate(str(self.root))
        self.assertEqual(code, 1, out)
        self.assertIn("加速", out)
        self.assertIn("1 个 SVG", out)

    def test_legend_text_in_svg_is_scanned(self):
        self.write("_internal/02_svg_source/page-07.svg",
                   '<svg xmlns="http://www.w3.org/2000/svg">'
                   '<text x="0" y="0">真实评论</text>'
                   '<text x="0" y="40"><tspan>待补拍</tspan></text></svg>')
        code, out = run_gate(str(self.root))
        self.assertEqual(code, 1, out)
        self.assertIn("待补拍", out)

    def test_svg_metadata_is_not_on_screen(self):
        self.write("_internal/02_svg_source/page-01.svg",
                   '<svg xmlns="http://www.w3.org/2000/svg">'
                   '<title>样张：这一屏怎么排</title><desc>审阅用的排布草图</desc>'
                   '<text x="10" y="20">真实评论</text></svg>')
        code, out = run_gate(str(self.root))
        self.assertEqual(code, 0, out)


class Declaration(GateCase):
    """② 声明只从上游契约读，读到的字与渲染的字同一套规则。"""

    def test_declaration_is_read_from_the_plan(self):
        self.write("visual/index.html", "<html><body><div>真实评论</div></body></html>")
        plan = self.plan([{"screen_id": "screen-beat-02", "beat_id": "beat-02",
                           "sample": {"captions": ["只做种草 → 人走掉", "本片中段用 2× 加速"]}}])
        code, out = run_gate(str(self.root), "--plan", str(plan))
        self.assertEqual(code, 1, out)
        self.assertIn("visual-plan.json:screen-beat-02/花字", out)
        self.assertIn("加速", out)

    def test_must_show_needs_the_marker_and_exact_labels_does_not(self):
        plan = self.plan([{"screen_id": "screen-beat-01",
                           "must_show": ["文字：本片中段用 2× 加速",
                                         "草稿感的对比关系（这句只说画面要表达什么）"],
                           "exact_labels": ["成交位", "种草（蓄水）"]}])
        code, out = run_gate(str(self.root), "--plan", str(plan))
        self.assertEqual(code, 1, out)                       # 加速 仍然硬失败
        self.assertIn("visual-plan.json:screen-beat-01/exact_labels", out)
        self.assertIn("成交位", out)                          # 没有「文字：」也整条算字
        self.assertIn("种草（蓄水）", out)
        self.assertNotIn("草稿感的对比关系", out)              # 没标的 must_show 只说语义，不上屏
        self.assertIn("上屏文字体检：3 条", out)

    def test_missing_plan_is_not_a_silent_pass(self):
        self.write("visual/index.html", "<html><body><div>真实评论</div></body></html>")
        code, out = run_gate(str(self.root))
        self.assertEqual(code, 0, out)
        self.assertIn("未给 --plan，只查渲染侧", out)
        self.assertNotIn("声明比对", out)
        code, _ = run_gate(str(self.root), "--plan", str(self.root / "deliverable/nope.json"))
        self.assertEqual(code, 2)


class ProcessMaterial(GateCase):
    """③ 结构认过程材料：不认上游的目录名，也不认上游的产物名。"""

    def test_review_page_is_skipped_by_structure_not_by_name(self):
        self.write("visual/随便哪个目录/随便哪一页.html",
                   '<html><body><h1>念稿审阅</h1>'
                   '<script>fetch("/api/feedback",{method:"POST"})</script></body></html>')
        code, out = run_gate(str(self.root))
        self.assertEqual(code, 0, out)
        self.assertIn("跳过", out)
        self.assertIn("/api/feedback", out)

    def test_self_declared_process_page_is_skipped(self):
        self.write("visual/notes.html",
                   "<!-- process-material --><html><body>审阅草稿预览</body></html>")
        code, out = run_gate(str(self.root))
        self.assertEqual(code, 0, out)
        self.assertIn("页面自述为过程材料", out)

    def test_marker_file_marks_a_subtree(self):
        self.write("visual/draft-pages/.process-material", "")
        self.write("visual/draft-pages/page.html", "<html><body>草稿</body></html>")
        code, out = run_gate(str(self.root))
        self.assertEqual(code, 0, out)
        self.assertIn(".process-material", out)


class ReportOnly(GateCase):
    """④ 只报不拦：信息给到人，判定不跟着动。"""

    def test_advisory_words_do_not_fail_but_are_reported(self):
        self.write("visual/index.html",
                   "<html><body><div>印刷样张的历史</div><div>软件预览版</div></body></html>")
        code, out = run_gate(str(self.root))
        self.assertEqual(code, 0, out)
        self.assertIn("只报不拦", out)
        self.assertIn("样张", out)
        self.assertIn("预览", out)
        self.assertIn("RESULT: OK", out)

    def test_advisory_words_are_in_the_json_and_still_do_not_fail(self):
        self.write("visual/index.html", "<html><body><div>编辑审阅流程</div></body></html>")
        code, out = run_gate(str(self.root), "--json")
        self.assertEqual(code, 0, out)
        payload = json.loads(out)
        self.assertEqual(payload["banned_hits"], [])
        self.assertEqual([hit["word"] for hit in payload["advisory_hits"]], ["审阅"])

    def test_declared_but_not_rendered_is_reported_not_failed(self):
        self.write("visual/index.html", "<html><body><div>转化发生在后</div></body></html>")
        plan = self.plan([{"screen_id": "screen-beat-01",
                           "sample": {"captions": ["种草发生在前"]}}])
        code, out = run_gate(str(self.root), "--plan", str(plan))
        self.assertEqual(code, 0, out)
        self.assertIn("声明了但画面上找不到", out)
        self.assertIn("画面上有但声明里没有", out)
        self.assertIn("种草发生在前", out)
        self.assertIn("转化发生在后", out)

    def test_declaration_diff_is_in_the_json(self):
        self.write("visual/index.html", "<html><body><div>转化发生在后</div></body></html>")
        plan = self.plan([{"screen_id": "screen-beat-01",
                           "sample": {"captions": ["种草发生在前"]}}])
        code, out = run_gate(str(self.root), "--plan", str(plan), "--json")
        self.assertEqual(code, 0, out)
        diff = json.loads(out)["declaration_diff"]
        self.assertEqual([item["text"] for item in diff["declared_not_rendered"]],
                         ["种草发生在前"])
        self.assertEqual([item["text"] for item in diff["rendered_not_declared"]],
                         ["转化发生在后"])


class Rules(GateCase):
    """⑤ 禁词表是闸门自己的，并且不许误伤普通文字。"""

    def test_plain_beat_passes_but_beat_ids_fail(self):
        self.write("visual/index.html", "<html><body><div>beat the odds</div></body></html>")
        code, out = run_gate(str(self.root))
        self.assertEqual(code, 0, out)
        self.write("visual/index.html", "<html><body><div>beat-03 的两条路径</div></body></html>")
        code, out = run_gate(str(self.root))
        self.assertEqual(code, 1, out)
        self.assertIn("beat-03", out)

    def test_ascii_bans_respect_word_boundaries(self):
        self.write("visual/index.html", "<html><body><div>MEDLEY 与 HFR</div></body></html>")
        code, out = run_gate(str(self.root))
        self.assertEqual(code, 0, out)

    def test_allow_lets_a_legitimate_word_through(self):
        self.write("visual/index.html", "<html><body><div>加速主义的由来</div></body></html>")
        code, _ = run_gate(str(self.root))
        self.assertEqual(code, 1)
        code, out = run_gate(str(self.root), "--allow", "加速")
        self.assertEqual(code, 0, out)
        self.assertIn("放行「加速」", out)


if __name__ == "__main__":
    unittest.main()
