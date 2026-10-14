/* composition-embed-bridge.js — let a review page drive this composition live.
 *
 * Why this exists
 * ---------------
 * The author reviews the engineering state: the composition itself, playing,
 * with no render. To do that the review page embeds the composition and steers
 * its timeline. It cannot reach into the frame: the review page itself runs in an
 * opaque-origin `sandbox="allow-scripts"` iframe, so `contentWindow` access is
 * cross-origin and throws. `postMessage` is the only channel both ways, and it
 * works precisely because it does not need same-origin access.
 *
 * The HyperFrames preview server serves this composition at
 * `/api/projects/<id>/preview/comp/index.html` with no listener of its own (the
 * studio reaches in same-origin instead). So the bridge has to travel with the
 * composition, which is exactly right: one file owns its own control surface.
 *
 * It is inert during rendering. A render never sends messages, `window.parent`
 * is the window itself, and the first line returns.
 *
 * Protocol (postMessage, `{kw:1, ...}`)
 * ------------------------------------
 *   in   {kw:1, type:"hello"}          → out {kw:1, type:"ready", duration, t, paused}
 *   in   {kw:1, type:"seek", t}        → seek + pause, out {type:"time", t, paused}
 *   in   {kw:1, type:"play"}           → out {type:"time", ...}, then a 200ms tick
 *   in   {kw:1, type:"pause"}          → out {type:"time", ...}
 *   out  {kw:1, type:"time", t, paused, duration}   (on tick while playing)
 *
 * Anything unrecognised is ignored. No message is ever sent unprompted except the
 * play tick, so a render's console stays clean.
 */
(function () {
  "use strict";

  if (window.parent === window) return;          // 渲染路径与非嵌入路径：直接退出
  if (window.__kwEmbedBridge) return;            // 幂等：重新注入不会挂两次
  window.__kwEmbedBridge = true;

  var TICK_MS = 200;
  var timer = null;

  function timeline() {
    var t = window.__timelines && window.__timelines.main;
    // 契约：composition 只有一个暂停的 timeline 挂在 window.__timelines.main
    return t && typeof t.seek === "function" ? t : null;
  }

  function duration() {
    var t = timeline();
    if (!t) return 0;
    try { return typeof t.duration === "function" ? t.duration() : 0; } catch (e) { return 0; }
  }

  function now() {
    var t = timeline();
    if (!t) return 0;
    try { return typeof t.time === "function" ? t.time() : 0; } catch (e) { return 0; }
  }

  function isPaused() {
    var t = timeline();
    if (!t) return true;
    try { return typeof t.paused === "function" ? t.paused() : true; } catch (e) { return true; }
  }

  function send(msg) {
    var payload = { kw: 1, duration: duration() };
    for (var k in msg) { if (Object.prototype.hasOwnProperty.call(msg, k)) payload[k] = msg[k]; }
    try { parent.postMessage(payload, "*"); } catch (e) { /* 宿主不在或不接受：静默 */ }
  }

  function stopTick() {
    if (timer !== null) { clearInterval(timer); timer = null; }
  }

  function startTick() {
    stopTick();
    timer = setInterval(function () {
      if (isPaused()) { stopTick(); }
      send({ type: "time", t: now(), paused: isPaused() });
    }, TICK_MS);
  }

  function onMessage(event) {
    // 只认父窗口发来的消息；来源不可校验（宿主是不透明源），所以用 source 认亲。
    if (event.source !== parent) return;
    var data = event.data;
    if (!data || data.kw !== 1) return;
    var tl = timeline();

    switch (data.type) {
      case "hello":
        send({ type: "ready", t: now(), paused: isPaused(), hasTimeline: !!tl });
        break;
      case "seek": {
        if (!tl || typeof data.t !== "number") return;
        stopTick();
        try { tl.seek(data.t); } catch (e) { return; }
        try { tl.pause(); } catch (e) { /* 已经暂停 */ }
        send({ type: "time", t: now(), paused: true });
        break;
      }
      case "play":
        if (!tl) return;
        try { tl.play(); } catch (e) { return; }
        send({ type: "time", t: now(), paused: false });
        startTick();
        break;
      case "pause":
        if (!tl) return;
        try { tl.pause(); } catch (e) { return; }
        stopTick();
        send({ type: "time", t: now(), paused: true });
        break;
      default:
        break;
    }
  }

  window.addEventListener("message", onMessage, false);

  // 时间轴可能在 bridge 之后才建好（生成器的脚本在页面末尾）。轮询几次再自报。
  var readyTries = 0;
  var readyTimer = setInterval(function () {
    readyTries += 1;
    if (timeline() || readyTries > 50) {
      clearInterval(readyTimer);
      send({ type: "ready", t: now(), paused: isPaused() });
    }
  }, 100);
})();
