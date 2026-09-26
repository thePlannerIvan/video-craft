"""The contract says which script it was built against; this is where it is checked.

`visual-plan.json` carries `script_hash`. Upstream computes it once at handoff and
nothing watches it afterwards, so **two places check it**: the picture step, before
recording and next to the contract (`script.md` sits beside `visual-plan.json` in
the upstream `deliverable/`), and this skill, after recording. Ours is the later
one, so its rule is the stricter one.

The behaviour that matters is the middle one: a changed script is not a warning
(exit 2) and not a pass (exit 0); it is a stop (exit 1), because screens bound to
the changed Beats may be void and fixing one means re-recording that segment.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

SKILL = Path(__file__).parents[1]
HELPERS = SKILL / "helpers"


def load(name: str):
    spec = importlib.util.spec_from_file_location(f"video_craft_{name}", HELPERS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


script_hash = load("check_script_hash")

SCRIPT = "# 标题\n\n## beat-01 ｜ 开场\n\n这是口播。\n"


class ProjectFixture(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.project = Path(self._tmp.name)

    def write_package(self, script: str = SCRIPT, recorded: str | None = "auto",
                      plan: bool = True, scene: str = "input") -> None:
        if scene == "input":
            self.project.joinpath("input").mkdir(exist_ok=True)
        directory = self.project / "input" if scene == "input" else self.project / "deliverable"
        directory.mkdir(parents=True, exist_ok=True)
        if script is not None:
            (directory / "script.md").write_text(script, encoding="utf-8")
        if not plan:
            return
        if recorded == "auto":
            recorded = hashlib.sha256(script.encode("utf-8")).hexdigest()
        payload = {"contract_version": "5.0", "title": "t", "screens": []}
        if recorded is not None:
            payload["script_hash"] = recorded
        (directory / "visual-plan.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def run_check(self):
        return script_hash.check(self.project)


class ScriptHashTests(ProjectFixture):
    def test_a_matching_script_passes(self):
        self.write_package()
        code, message = self.run_check()
        self.assertEqual(code, 0, message)
        self.assertIn("match", message)

    def test_a_changed_script_is_a_stop_not_a_warning(self):
        self.write_package()
        (self.project / "input" / "script.md").write_text(
            SCRIPT + "\n## beat-02 ｜ 补录\n\n又加了一段。\n", encoding="utf-8")
        code, message = self.run_check()
        self.assertEqual(code, 1, message)
        self.assertIn("MISMATCH", message)
        self.assertIn("ask the author", message)

    def test_the_digest_is_over_the_raw_bytes(self):
        self.write_package()
        expected = hashlib.sha256((self.project / "input" / "script.md").read_bytes()).hexdigest()
        self.assertEqual(script_hash.sha256_file(self.project / "input" / "script.md"), expected)

    def test_a_contract_without_script_hash_cannot_be_verified(self):
        self.write_package(recorded=None)
        code, message = self.run_check()
        self.assertEqual(code, 2, message)
        self.assertIn("carries no script_hash", message)
        self.assertIn("validate-visual-plan.mjs", message)

    def test_a_missing_script_cannot_be_verified(self):
        self.write_package()
        (self.project / "input" / "script.md").unlink()
        code, message = self.run_check()
        self.assertEqual(code, 2, message)
        self.assertIn("nothing here to hash against", message)

    def test_a_missing_contract_cannot_be_verified(self):
        self.write_package(plan=False)
        code, message = self.run_check()
        self.assertEqual(code, 2, message)
        self.assertIn("no visual-plan.json", message)

    def test_the_deliverable_folder_is_also_searched(self):
        self.write_package(scene="deliverable")
        code, message = self.run_check()
        self.assertEqual(code, 0, message)

    def test_explicit_paths_win(self):
        self.write_package()
        other = self.project / "elsewhere.md"
        other.write_text(SCRIPT, encoding="utf-8")
        code, message = script_hash.check(
            None, other, self.project / "input" / "visual-plan.json")
        self.assertEqual(code, 0, message)


if __name__ == "__main__":
    unittest.main()
