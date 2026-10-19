#!/usr/bin/env python3
"""Delivery fingerprint must see nested deliverables (成品/subtitles/*.srt).

v3 audit: changing 成品/subtitles/final.srt left the fingerprint unchanged because
capture() listed only the first level of 成品/. Deliverable shape is the author's
choice, so the walk must be recursive.
"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

HELPERS = Path(__file__).parents[1] / "helpers"
sys.path.insert(0, str(HELPERS))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"craft_{name}", HELPERS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


fingerprint = _load("state_fingerprint")


class NestedDeliverables(unittest.TestCase):
    def test_nested_subtitle_is_tracked_and_changes_are_seen(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            out = project / "成品" / "subtitles"
            out.mkdir(parents=True)
            (project / "成品" / "final.mp4").write_bytes(b"video")
            srt = out / "final.srt"
            srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nold\n", encoding="utf-8")
            saved = fingerprint.capture(project)
            paths = {d["path"] for d in saved["deliverables"]}
            self.assertTrue(any(p.endswith("subtitles/final.srt") for p in paths), paths)

            srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nnew\n", encoding="utf-8")
            now = fingerprint.capture(project)
            diff = fingerprint.compare(saved, now)
            self.assertTrue(any("final.srt" in line for line in diff), diff)


if __name__ == "__main__":
    unittest.main()
