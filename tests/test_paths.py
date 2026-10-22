#!/usr/bin/env python3
"""项目路径解析的唯一实现（合并地图 M3 的第一步）。"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "helpers"))

import _paths  # noqa: E402


class Resolve(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name) / "demo"
        (self.project / "edit").mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def test_project_root_passes_through(self):
        root, edit = _paths.resolve(self.project)
        self.assertEqual(root, self.project.resolve())
        self.assertEqual(edit, (self.project / "edit").resolve())

    def test_edit_dir_resolves_to_project(self):
        root, edit = _paths.resolve(self.project / "edit")
        self.assertEqual(root, self.project.resolve())
        self.assertEqual(edit, (self.project / "edit").resolve())

    def test_review_and_output_dirs_resolve_to_project(self):
        (self.project / "review").mkdir()
        (self.project / "成品").mkdir()
        for name in ("review", "成品"):
            root, _ = _paths.resolve(self.project / name)
            self.assertEqual(root, self.project.resolve(), name)

    def test_project_with_edl_at_root_is_its_own_edit_dir(self):
        flat = Path(self._tmp.name) / "flat"
        flat.mkdir()
        (flat / "edl.json").write_text("{}", encoding="utf-8")
        root, edit = _paths.resolve(flat)
        self.assertEqual(root, flat.resolve())
        self.assertEqual(edit, flat.resolve())


if __name__ == "__main__":
    unittest.main()
