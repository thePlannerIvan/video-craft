#!/usr/bin/env python3
"""The live-stage contract: what `hyperframes check` cannot see.

2026-10-21 (XHS): the project played 6:08 in the official player, `hyperframes
check --json` exited 0 with `runtime.duration = null` and `contrast.checked = 0`,
and the review page's live stage showed 0:00 / black while the speaker played.
Root cause: `index.html`'s inline `<script>` is rewritten by the preview compiler
to `type="text/hf-after-fonts"`; the review page's srcdoc never re-runs it, so
`window.__CFG__` and `HF.build()` never executed. `src=` scripts survive that trip
because live_preview inlines them as ordinary executable scripts.

These tests pin the static verdict, including the two non-obvious allowances:
`hyperframes check`'s lint needs a `window.__timelines` initialization visible in
index.html, and that line may only be a container init — the real registration
must live in a file.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

HELPERS = Path(__file__).parents[1] / "helpers"
sys.path.insert(0, str(HELPERS))

import check_live_stage  # noqa: E402


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class LiveStageContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name)
        self.comp = self.project / "composition"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _bridge(self) -> None:
        _write(self.comp / "assets" / "composition-embed-bridge.js",
               "/* inert bridge */\n")

    def _good(self, *, marker: bool = True, register: str = "main",
             bridge: bool = True) -> None:
        marker_tag = ('<script>window.__timelines = window.__timelines || {};</script>\n'
                      if marker else "")
        bridge_tag = ('<script src="assets/composition-embed-bridge.js"></script>\n'
                      if bridge else "")
        _write(self.comp / "index.html", f"""<!doctype html><html><body>
<div id="root" data-composition-id="main"
     data-start="0" data-width="1920" data-height="1080" data-duration="12.5">
</div>
<script src="src/core.js"></script>
<script src="src/boot.js"></script>
{marker_tag}{bridge_tag}
</body></html>""")
        _write(self.comp / "src" / "boot.js",
               f'window.__timelines = window.__timelines || {{}};\n'
               f'window.__timelines["{register}"] = window.HF.tl;\n')
        _write(self.comp / "src" / "core.js", "window.HF = { tl: {} };\n")
        if bridge:
            self._bridge()

    def test_a_compliant_composition_passes(self):
        self._good()
        report = check_live_stage.inspect(self.project)
        self.assertEqual(report.errors, [], report.as_dict())

    def test_the_lint_marker_is_not_mistaken_for_logic(self):
        """The container init is required by hyperframes check's lint; it is not a registration."""
        self._good(marker=True)
        report = check_live_stage.inspect(self.project)
        self.assertTrue(report.as_dict()["ok"], report.as_dict())
        ids = {c["id"] for c in report.checks if c["ok"]}
        self.assertIn("inline-logic", ids)

    def test_a_missing_lint_marker_is_only_a_warning(self):
        self._good(marker=False)
        report = check_live_stage.inspect(self.project)
        self.assertTrue(report.as_dict()["ok"], report.as_dict())
        warned = {c["id"] for c in report.warnings}
        self.assertIn("lint-registry-marker", warned)

    def test_inline_config_and_build_are_rejected(self):
        """The exact shape that produced 0s/black in the review page."""
        self._good()
        html = (self.comp / "index.html").read_text(encoding="utf-8")
        html = html.replace("</body>", """<script>
window.__CFG__ = { total: 12.5 };
HF.build();
window.__timelines["main"] = HF.tl;
</script>
</body>""")
        (self.comp / "index.html").write_text(html, encoding="utf-8")
        report = check_live_stage.inspect(self.project)
        self.assertFalse(report.as_dict()["ok"])
        failed = {c["id"]: c["detail"] for c in report.errors}
        self.assertIn("inline-logic", failed)
        self.assertIn("HF.build()", failed["inline-logic"])
        self.assertIn("window.__CFG__", failed["inline-logic"])

    def test_a_saved_compiled_block_is_rejected(self):
        self._good()
        html = (self.comp / "index.html").read_text(encoding="utf-8")
        html = html.replace("</body>", """<script type="text/hf-after-fonts">
window.__timelines["main"] = window.HF.tl;
</script>
</body>""")
        (self.comp / "index.html").write_text(html, encoding="utf-8")
        report = check_live_stage.inspect(self.project)
        self.assertFalse(report.as_dict()["ok"])
        self.assertIn("rewritten-inline", {c["id"] for c in report.errors})

    def test_registration_name_must_equal_the_root_id(self):
        self._good(register="v3")
        report = check_live_stage.inspect(self.project)
        self.assertFalse(report.as_dict()["ok"])
        detail = {c["id"]: c["detail"] for c in report.errors}["timeline-registration"]
        self.assertIn("v3", detail)
        self.assertIn("main", detail)

    def test_a_missing_bridge_is_rejected(self):
        self._good(bridge=False)
        report = check_live_stage.inspect(self.project)
        self.assertFalse(report.as_dict()["ok"])
        self.assertIn("embed-bridge", {c["id"] for c in report.errors})

    def test_a_missing_external_script_is_rejected(self):
        self._good()
        (self.comp / "src" / "core.js").unlink()
        report = check_live_stage.inspect(self.project)
        self.assertFalse(report.as_dict()["ok"])
        self.assertIn("external-scripts", {c["id"] for c in report.errors})

    def test_a_composition_directory_inside_the_project_is_found(self):
        self._good()
        report = check_live_stage.inspect(self.comp)
        self.assertEqual(report.comp, self.comp.resolve())
        self.assertTrue(report.as_dict()["ok"], report.as_dict())

    def test_an_alternate_composition_dir_is_supported(self):
        self._good()
        alt = self.project / "composition-v2"
        (self.comp).rename(alt)
        report = check_live_stage.inspect(self.project, "composition-v2")
        self.assertEqual(report.comp, alt.resolve())
        self.assertTrue(report.as_dict()["ok"], report.as_dict())

    def test_no_composition_is_exit_code_2(self):
        self.assertEqual(check_live_stage.main([str(self.project)]), 2)

    def test_cli_exit_codes(self):
        self._good()
        self.assertEqual(check_live_stage.main([str(self.project)]), 0)
        self._good(register="other")
        self.assertEqual(check_live_stage.main([str(self.project)]), 1)


if __name__ == "__main__":
    unittest.main()
