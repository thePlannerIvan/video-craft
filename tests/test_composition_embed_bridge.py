#!/usr/bin/env python3
"""The composition's embed bridge is the only channel the review page has.

The review page runs in an opaque-origin `sandbox="allow-scripts"` iframe, so it
cannot reach into the embedded composition's DOM; `postMessage` is the whole
interface. If the bridge misbehaves the failure is silent and looks like "the
picture does not move" — the exact shape of the bug that cost three rounds of
hand-fixing. So the protocol is pinned by a real run of the real file, in a fake
window, with no browser.

The cases live in `embed_bridge_harness.mjs` (they need a JS runtime to exercise
JS); this module only checks that the harness ran, said so, and did not shrink.
A harness that quietly reports zero cases would otherwise be indistinguishable
from a passing one.

**Deliberately not doing**: proving the composition *animates*, or that the review
page wires the bridge correctly. That needs a browser and is not covered here —
see `references/architecture.md` 「明确不做什么」.
"""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
HARNESS = TESTS / "embed_bridge_harness.mjs"
BRIDGE = TESTS.parent / "visual" / "assets" / "composition-embed-bridge.js"

EXPECTED_CASES = {
    "inert when not embedded",
    "hello answers ready with duration and time",
    "seek seeks, pauses, stops the tick",
    "play ticks time",
    "ignores messages from anyone but the parent",
    "second injection is a no-op",
}


@unittest.skipUnless(shutil.which("node"), "needs node (the bridge is JavaScript)")
class CompositionEmbedBridgeTest(unittest.TestCase):
    def test_protocol_cases(self):
        self.assertTrue(BRIDGE.is_file(), f"missing {BRIDGE}")
        proc = subprocess.run(["node", str(HARNESS)], capture_output=True, text=True,
                              timeout=60)
        # Harness 自己会打 JSON；先解析，失败时把原始输出带进报错里。
        try:
            report = json.loads(proc.stdout)
        except ValueError:
            self.fail(f"harness printed no JSON\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}")

        seen = {c["name"] for c in report["cases"]}
        failed = [c for c in report["cases"] if not c["ok"]]

        self.assertEqual(report["failed"], 0,
                         "bridge cases failed:\n" + "\n".join(
                             f"  - {c['name']}: {c['error']}" for c in failed))
        self.assertEqual(proc.returncode, 0, f"harness exit {proc.returncode}\n{proc.stderr}")
        # 用例集不许缩水：名字对不上说明有人删了断言却没改这里。
        self.assertEqual(seen, EXPECTED_CASES,
                         f"harness case set changed; missing={EXPECTED_CASES - seen} "
                         f"extra={seen - EXPECTED_CASES}")

    def test_bridge_is_inert_without_a_parent(self):
        """The render path must stay clean: no listener, no messages, no bridge."""
        source = BRIDGE.read_text(encoding="utf-8")
        self.assertIn("window.parent === window", source,
                      "the bridge lost its non-embedded early return — a render would arm it")


if __name__ == "__main__":
    unittest.main()
