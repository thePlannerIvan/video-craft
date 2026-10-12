#!/usr/bin/env python3
"""The analytic projection must be usable, and must never pass as a render.

`render.py` writing `segment_durations.json` coupled "can I look at the film" to
"has the whole film been encoded": no captions, no timeline spine, no review
surface until then. The durations are computable — `round(raw * fps) / fps` is the
grid the renderer uses — so `duration_plan.py` writes them as `projected: true`.

The safety property pinned here: a projected record is NOT render evidence.
`_edl.select_render_record` ignores it by default, which is what keeps
`verify_delivery.py` honest.
"""
from __future__ import annotations

import importlib.util
import json
import math
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


duration_plan = _load("duration_plan")
_edl = _load("_edl")


class PlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.edit = Path(self._tmp.name)
        self.edl = {
            "version": 1, "sources": {"A": str(self.edit / "A.mp4")},
            "ranges": [
                {"source": "A", "start": 0.0, "end": 25.10},
                # 5.84s is NOT on the 30fps grid: 175.2 frames -> 175 -> 5.8333…
                {"source": "A", "start": 30.0, "end": 35.84},
            ],
            "grade": "none",
        }
        (self.edit / "edl.json").write_text(json.dumps(self.edl), encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_durations_are_frame_quantised(self):
        durations, fps = duration_plan.plan_durations(self.edit, fps=30.0)
        self.assertEqual(fps, 30.0)
        # 25.10s -> 753 frames (already on the grid); 5.84s -> ceil(175.2) = 176
        self.assertAlmostEqual(durations[0], 753 / 30, places=6)
        self.assertAlmostEqual(durations[1], 176 / 30, places=6)
        self.assertNotAlmostEqual(durations[1], 5.84, places=3)
        self.assertGreater(durations[1], 5.84)   # ceil, never round-down

    def test_the_grid_is_ceil_not_round(self):
        """Pinned against a real render: ceil matched 14/14 segments, round 6/14.

        These are the 图拉斯 project's own (raw, rendered) pairs. If this changes,
        the projection stops being exact and `duration_plan` must be re-derived
        before anyone trusts a projected timeline.
        """
        observed = [(11.57, 11.600000), (6.07, 6.100000), (54.21, 54.233333),
                    (37.61, 37.633333), (8.80, 8.800000), (25.85, 25.866667)]
        for raw, rendered in observed:
            frames = max(1, math.ceil(round(raw * 30.0, 6)))
            self.assertAlmostEqual(frames / 30.0, rendered, places=6,
                                   msg=f"{raw}s should land on {rendered}s")

    def test_write_plan_is_marked_projected_and_bound_to_the_edl(self):
        record = duration_plan.write_plan(self.edit, fps=30.0)
        self.assertEqual(record["action"], "written")
        blob = json.loads((self.edit / "segment_durations.json").read_text(encoding="utf-8"))
        entry = blob[duration_plan.PLAN_KEY]
        self.assertTrue(entry["projected"])
        self.assertEqual(entry["edl_sha256"], _edl.edl_digest(self.edit / "edl.json"))
        self.assertEqual(len(entry["durations"]), 2)

    def test_write_plan_is_idempotent_unless_forced(self):
        duration_plan.write_plan(self.edit, fps=30.0)
        self.assertEqual(duration_plan.write_plan(self.edit, fps=30.0)["action"], "unchanged")
        self.assertEqual(duration_plan.write_plan(self.edit, fps=30.0, force=True)["action"],
                         "written")

    def test_a_projection_is_not_render_evidence(self):
        duration_plan.write_plan(self.edit, fps=30.0)
        self.assertEqual(_edl.render_record(self.edit)[2], "none")
        tag, entry, how = _edl.render_record(self.edit, allow_projected=True)
        self.assertEqual(how, "projected")
        self.assertTrue(entry["projected"])

    def test_a_real_render_still_wins_when_both_exist(self):
        duration_plan.write_plan(self.edit, fps=30.0)
        blob = json.loads((self.edit / "segment_durations.json").read_text(encoding="utf-8"))
        blob["final"] = {"durations": list(blob["plan"]["durations"]),
                         "edl_sha256": _edl.edl_digest(self.edit / "edl.json"),
                         "fps": 30.0}
        (self.edit / "segment_durations.json").write_text(json.dumps(blob), encoding="utf-8")
        tag, entry, how = _edl.render_record(self.edit)
        self.assertEqual(how, "digest")
        self.assertFalse(entry.get("projected"))


if __name__ == "__main__":
    unittest.main()
