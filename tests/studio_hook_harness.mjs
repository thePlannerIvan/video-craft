/* studio_hook_harness.mjs — exercise composition-studio-hook.js without a browser.
 *
 * The hook is the only reason the studio's "Describe a change to the agent" ever
 * reaches the project: that affordance only writes the clipboard. Five behaviours
 * decide whether it helps or harms:
 *   1. inert when not embedded (a render, a bare tab)
 *   2. inert when no collector is configured
 *   3. wraps the parent's clipboard AND still calls the original (never eat the copy)
 *   4. POSTs the captured text to the collector
 *   5. idempotent (a reload must not stack wrappers)
 *   6. stamps the note with the animation anchor (which screen, which cue)
 * Prints one JSON object; exits non-zero if any case fails.
 */
import { readFileSync } from "node:fs";
import { createContext, runInContext } from "node:vm";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const SOURCE = readFileSync(join(HERE, "..", "visual", "assets", "composition-studio-hook.js"), "utf8");
const ENDPOINT = "http://127.0.0.1:4319/note";

function harness({ embedded = true, endpoint = ENDPOINT } = {}) {
  const calls = [];        // 原函数被调用过几次
  const posts = [];        // 我们 POST 出去的内容
  const parentClip = { writeText: (t) => { calls.push(t); return Promise.resolve(); } };
  const listeners = [];
  const intervals = [];
  const parent = { navigator: { clipboard: parentClip } };
  const win = {
    __KW_STUDIO_NOTES__: endpoint || undefined,
    parent: embedded ? parent : null,
    addEventListener: (t, f) => listeners.push([t, f]),
  };
  if (!embedded) win.parent = win;
  win.document = { querySelector: () => null };
  const sandbox = { window: win, parent: win.parent, document: win.document, console,
    setTimeout, clearTimeout, setInterval: (f, ms) => { intervals.push({ f, ms }); return intervals.length; },
    clearInterval: () => {}, Promise, JSON, Object,
    fetch: (url, opts) => { posts.push({ url, body: JSON.parse(opts.body) }); return Promise.resolve(); } };
  createContext(sandbox);
  const run = () => runInContext(SOURCE, sandbox, { filename: "hook" });
  const flush = () => { for (const { f } of [...intervals]) f(); };
  return { win, parentClip, calls, posts, run, flush, intervals };
}

const results = [];
const check = (name, fn) => { try { fn(); results.push({ name, ok: true }); }
  catch (e) { results.push({ name, ok: false, error: String(e && e.message || e) }); } };
const assert = (c, m) => { if (!c) throw new Error(m); };

check("inert when not embedded", () => {
  const h = harness({ embedded: false });
  h.run(); h.flush();
  assert(!h.win.__kwStudioHook, "armed itself outside an embed");
  assert(h.parentClip.writeText.__kwWrapped === undefined, "wrapped the clipboard anyway");
});

check("inert when no collector is configured", () => {
  const h = harness({ endpoint: "" });
  h.run(); h.flush();
  assert(!h.win.__kwStudioHook, "armed without an endpoint");
});

check("wraps the parent clipboard and still copies", async () => {
  const h = harness();
  h.run(); h.flush();
  assert(h.win.__kwStudioHook === true, "hook did not arm");
  assert(h.parentClip.writeText.__kwWrapped === true, "parent clipboard not wrapped");
  h.parentClip.writeText("NOTE");
  assert(h.calls.includes("NOTE"), "the original writeText was never called — the copy was eaten");
});

check("posts the captured text to the collector", () => {
  const h = harness();
  h.run(); h.flush();
  h.parentClip.writeText("把 beat-03 的金句压小一点");
  assert(h.posts.length === 1, `expected 1 POST, got ${h.posts.length}`);
  assert(h.posts[0].url === ENDPOINT, `posted to ${h.posts[0].url}`);
  assert(h.posts[0].body.text === "把 beat-03 的金句压小一点", "payload text missing");
});

check("stamps the note with the animation anchor", () => {
  const h = harness();
  // 动画层用 C(step, cueIndex) 给每个动作命名；钩子要把它盖在意见上。
  h.win.__timelines = { main: { time: () => 45.8 } };
  h.win.__SPANS__ = { "step-beat-03": [44.033, 68.18], "step-beat-04": [68.8, 97.887] };
  h.win.__CUES__ = { "step-beat-03": [44.033, 45.54, 47.46, 51.74] };
  h.run(); h.flush();
  h.parentClip.writeText("这句再压小一点");
  const body = h.posts[0].body;
  assert(body.stepId === "beat-03", `stepId ${body.stepId}`);
  assert(body.cueIndex === 1, `cueIndex ${body.cueIndex}`);
  assert(body.anchor === 'C("beat-03", 1)', `anchor ${body.anchor}`);
  assert(body.t === 45.8, `t ${body.t}`);
});

check("second run does not stack wrappers", () => {
  const h = harness();
  h.run(); h.flush(); h.run(); h.flush();
  h.parentClip.writeText("ONCE");
  assert(h.posts.length === 1, `double-wrapped: ${h.posts.length} POSTs for one copy`);
});

const failed = results.filter((r) => !r.ok);
console.log(JSON.stringify({ cases: results, failed: failed.length }, null, 2));
process.exit(failed.length ? 1 : 0);
