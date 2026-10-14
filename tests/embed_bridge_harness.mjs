/* embed_bridge_harness.mjs — exercise composition-embed-bridge.js without a browser.
 *
 * The bridge is pure protocol logic over `window`, `parent`, `postMessage` and two
 * timers, so it runs under `node:vm` with a fake window. That makes the six
 * behaviours the review page depends on assertable in a normal test run:
 *
 *   1. inert when the file is opened on its own (render path, non-embedded path)
 *   2. `hello` answers with duration + current time + paused
 *   3. `seek` seeks, pauses, stops any tick, and answers with one time message
 *   4. `play` plays and emits a time message on every tick
 *   5. a message from anyone but the parent is ignored
 *   6. a second injection does not attach a second listener
 *
 * Prints one JSON object on stdout and exits non-zero if any case fails.
 */
import { readFileSync } from "node:fs";
import { createContext, runInContext } from "node:vm";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const BRIDGE = join(HERE, "..", "visual", "assets", "composition-embed-bridge.js");
const SOURCE = readFileSync(BRIDGE, "utf8");
const TICK_MS = 200;   // 与 bridge 里的 TICK_MS 一致

function makeTimeline() {
  const state = { t: 0, paused: true };
  const calls = [];
  return {
    calls,
    state,
    seek(t) { calls.push(["seek", t]); state.t = t; },
    play() { calls.push(["play"]); state.paused = false; },
    pause() { calls.push(["pause"]); state.paused = true; },
    time() { return state.t; },
    paused() { return state.paused; },
    duration() { return 193.08; },
  };
}

function makeHarness({ embedded = true, timeline } = {}) {
  const tl = timeline || makeTimeline();
  const posted = [];
  const listeners = [];
  const intervals = new Map();
  let nextTimer = 1;

  const parent = { postMessage: (msg) => posted.push(msg) };
  const win = {
    __timelines: { main: tl },
    addEventListener: (type, fn) => listeners.push([type, fn]),
  };
  win.parent = embedded ? parent : win;

  const sandbox = {
    window: win,
    parent: win.parent,
    console,
    setInterval: (fn, ms) => { const id = nextTimer++; intervals.set(id, { fn, ms }); return id; },
    clearInterval: (id) => { intervals.delete(id); },
  };
  sandbox.globalThis = sandbox;
  createContext(sandbox);

  const fire = (data, source) => {
    for (const [type, fn] of listeners) {
      if (type === "message") fn({ data, source: source === undefined ? win.parent : source });
    }
  };
  const tick = () => { for (const { fn } of [...intervals.values()]) fn(); };
  // 只数 200ms 的那条播放心跳：100ms 的那条是启动时的 timeline 就绪轮询，
  // 它跑一次就自己 clearInterval，不该混进这里的计数。
  const liveIntervals = () => [...intervals.values()].filter((i) => i.ms === TICK_MS).length;

  runInContext(SOURCE, sandbox, { filename: BRIDGE });
  tick();            // 冲掉就绪轮询（它会自清）
  posted.length = 0; // 每个用例都从干净状态开始
  return { win, tl, posted, fire, tick, liveIntervals, listeners, sandbox };
}

const results = [];
function check(name, fn) {
  try {
    fn();
    results.push({ name, ok: true });
  } catch (error) {
    results.push({ name, ok: false, error: String(error && error.message || error) });
  }
}
function assert(cond, msg) { if (!cond) throw new Error(msg); }
const types = (posted) => posted.map((m) => m.type);

/* 1 — 单独打开这个文件（渲染路径）时必须是死的 */
check("inert when not embedded", () => {
  const h = makeHarness({ embedded: false });
  assert(h.win.__kwEmbedBridge === undefined, "bridge armed itself outside an embed");
  assert(h.listeners.length === 0, `attached ${h.listeners.length} listener(s) outside an embed`);
  assert(h.posted.length === 0, "posted before being asked");
});

/* 2 — hello 必须回一份可用的状态 */
check("hello answers ready with duration and time", () => {
  const h = makeHarness();
  h.tl.state.t = 7.25;
  h.fire({ kw: 1, type: "hello" });
  const ready = h.posted.find((m) => m.type === "ready");
  assert(ready, `no ready message (got ${JSON.stringify(h.posted)})`);
  assert(ready.duration === 193.08, `duration ${ready.duration}`);
  assert(ready.t === 7.25, `t ${ready.t}`);
  assert(ready.paused === true, "should report paused");
});

/* 3 — seek 必须同时暂停、停掉 tick，并回一条 time */
check("seek seeks, pauses, stops the tick", () => {
  const h = makeHarness();
  h.fire({ kw: 1, type: "play" });
  assert(h.liveIntervals() === 1, "play did not start a tick");
  h.fire({ kw: 1, type: "seek", t: 42.5 });
  assert(h.tl.state.t === 42.5, `timeline at ${h.tl.state.t}`);
  assert(h.tl.state.paused === true, "seek left it playing");
  assert(h.liveIntervals() === 0, "seek left the tick running");
  const last = h.posted[h.posted.length - 1];
  assert(last.type === "time" && last.t === 42.5, `last message ${JSON.stringify(last)}`);
  const before = h.posted.length;
  h.tick();
  assert(h.posted.length === before, "tick still fired after a seek");
});

/* 4 — play 之后每一拍都要报时间 */
check("play ticks time", () => {
  const h = makeHarness();
  h.fire({ kw: 1, type: "play" });
  assert(h.tl.calls.some((c) => c[0] === "play"), "timeline.play was not called");
  h.tl.state.t = 10;
  h.tick();
  h.tl.state.t = 10.2;
  h.tick();
  const times = h.posted.filter((m) => m.type === "time");
  assert(times.length >= 3, `expected >=3 time messages, got ${times.length}`);
  assert(times.some((m) => m.t === 10.2), "tick did not report the new time");
});

/* 5 — 别人发的消息一概不理 */
check("ignores messages from anyone but the parent", () => {
  const h = makeHarness();
  h.fire({ kw: 1, type: "seek", t: 99 }, { evil: true });
  assert(h.tl.calls.length === 0, `acted on a foreign message: ${JSON.stringify(h.tl.calls)}`);
  assert(h.posted.length === 0, "answered a foreign message");
  h.fire({ type: "seek", t: 5 });
  assert(h.tl.calls.length === 0, "acted on a message without the kw marker");
});

/* 6 — 重复注入不能挂两次 */
check("second injection is a no-op", () => {
  const h = makeHarness();
  const before = h.listeners.length;
  runInContext(SOURCE, h.sandbox, { filename: BRIDGE });   // 同一个 vm context，模拟重复注入
  assert(h.listeners.length === before, "second injection attached another listener");
});

const failed = results.filter((r) => !r.ok);
console.log(JSON.stringify({ bridge: BRIDGE, cases: results, failed: failed.length }, null, 2));
process.exit(failed.length === 0 ? 0 : 1);
