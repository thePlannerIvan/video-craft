#!/usr/bin/env python3
"""The studio feedback path: the hook, and the collector it posts into.

The studio's "Describe a change to the agent" only writes the clipboard, so without
this path the author's notes never reach the project. Two moving parts, both tested
here without a browser:

* `visual/assets/composition-studio-hook.js` — runs inside the composition, wraps
  the studio's `navigator.clipboard.writeText` (same-origin shadow iframe, verified
  on the running studio), posts what it captures. Cases live in
  `studio_hook_harness.mjs`; this module checks the harness ran, passed, and did not
  shrink — a harness that quietly reports nothing must not look like success.
* `helpers/studio_notes.py` — the collector. Tested end to end over real HTTP
  against an ephemeral port, because "it appends to a file" is exactly the kind of
  claim that silently stops being true.

**Deliberately not doing**: proving the studio actually calls the wrapped function
when the author clicks the affordance. That needs the studio in a browser; the
live check is `node tests/studio_hook_harness.mjs` plus the CDP recipe in
`references/review-ui.md`.
"""
import json
import shutil
import subprocess
import sys
import threading
import unittest
import urllib.request
from pathlib import Path

TESTS = Path(__file__).resolve().parent
SKILL = TESTS.parent
HARNESS = TESTS / "studio_hook_harness.mjs"
sys.path.insert(0, str(SKILL / "helpers"))

import studio_notes  # noqa: E402

EXPECTED_CASES = {
    "inert when not embedded",
    "inert when no collector is configured",
    "wraps the parent clipboard and still copies",
    "posts the captured text to the collector",
    "second run does not stack wrappers",
    "stamps the note with the animation anchor",
}


class StudioHookTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "needs node (the hook is JavaScript)")
    def test_hook_cases(self):
        proc = subprocess.run(["node", str(HARNESS)], capture_output=True, text=True, timeout=60)
        try:
            report = json.loads(proc.stdout)
        except ValueError:
            self.fail(f"harness printed no JSON\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}")
        failed = [c for c in report["cases"] if not c["ok"]]
        self.assertEqual(report["failed"], 0,
                         "hook cases failed:\n" + "\n".join(
                             f"  - {c['name']}: {c['error']}" for c in failed))
        seen = {c["name"] for c in report["cases"]}
        self.assertEqual(seen, EXPECTED_CASES,
                         f"harness case set changed; missing={EXPECTED_CASES - seen} "
                         f"extra={seen - EXPECTED_CASES}")


class StudioNotesCollectorTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = Path(self.tmp.name)
        (self.project / "composition").mkdir()
        (self.project / "edit/_engineering").mkdir(parents=True)

    def test_append_and_tail_round_trip(self):
        studio_notes.append_note(self.project, "把 beat-03 的金句压小一点", "agent-prompt")
        rows = [json.loads(ln) for ln in
                studio_notes.notes_path(self.project).read_text(encoding="utf-8").splitlines() if ln.strip()]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["text"], "把 beat-03 的金句压小一点")
        self.assertEqual(rows[0]["kind"], "agent-prompt")
        self.assertGreater(rows[0]["chars"], 0)

    def test_collector_over_real_http(self):
        """起真的收集器，POST 一条，断言它落进了文件。"""
        server = studio_notes.ThreadingHTTPServer(("127.0.0.1", 0),
                                                  studio_notes.make_handler(self.project))
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        try:
            body = json.dumps({"text": "这一屏的印章落得太早", "kind": "agent-prompt"}).encode()
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/note", data=body,
                headers={"content-type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=5) as resp:
                self.assertEqual(resp.status, 200)
                self.assertTrue(json.loads(resp.read())["ok"])
        finally:
            server.shutdown()

        path = studio_notes.notes_path(self.project)
        self.assertTrue(path.is_file(), "收集器没有落盘")
        rows = [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        self.assertEqual([r["text"] for r in rows], ["这一屏的印章落得太早"])

    def test_note_carries_the_animation_anchor(self):
        """锚点是这条链的意义所在：意见要落到**具体那一下动画**，不是一句漂浮的话。"""
        studio_notes.append_note(self.project, "这句再压小一点", "agent-prompt",
                                 {"t": 45.8, "stepId": "beat-03", "cueIndex": 1,
                                  "anchor": 'C("beat-03", 1)'})
        row = json.loads(studio_notes.notes_path(self.project).read_text(encoding="utf-8").strip())
        self.assertEqual(row["stepId"], "beat-03")
        self.assertEqual(row["anchor"], 'C("beat-03", 1)')
        self.assertEqual(row["t"], 45.8)

    def test_empty_payload_is_not_recorded(self):
        studio_notes.append_note(self.project, "   ")
        path = studio_notes.notes_path(self.project)
        if path.is_file():
            self.assertEqual([ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()],
                             [])


if __name__ == "__main__":
    unittest.main()
