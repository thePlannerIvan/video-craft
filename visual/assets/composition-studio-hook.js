/* composition-studio-hook.js — catch what the author writes in the studio.
 *
 * The problem
 * -----------
 * The studio's "Describe a change to the agent" builds a prompt and puts it on the
 * **clipboard**; if the author does not paste it into the conversation, the note is
 * gone. Nothing reaches the project.
 *
 * Why this file can solve it without touching HyperFrames
 * ------------------------------------------------------
 * The studio loads the composition in `<hyperframes-player>`'s shadow DOM iframe,
 * and that iframe is `sandbox="allow-scripts allow-same-origin"` — verified on the
 * running studio, not assumed. So the composition shares the studio's origin, and
 * `parent.navigator.clipboard` is reachable. This file wraps the parent's
 * `writeText`:
 *
 *     studio builds a prompt → clipboard.writeText(prompt)
 *        → our wrapper: POST it to the notes collector, then call the original
 *
 * The clipboard behaves exactly as before; the original is always called, and any
 * failure on our side is swallowed. The studio never learns we are here.
 *
 * Inert everywhere else
 * ---------------------
 * It does nothing unless: we are in a frame, the parent is same-origin reachable,
 * and a collector URL was configured. A render, a bare tab, or a different host all
 * take the first return. The agent-prompt format is never parsed — it belongs to
 * HyperFrames and will change; we store it verbatim.
 *
 * Config (injected by the generator) — a meta tag, not an inline script, because a
 * downstream tool anchors on "the first inline <script>" to find the skeleton
 * script and a second inline script would steal that anchor (learned the hard way):
 *   <meta name="kw-studio-notes" content="http://127.0.0.1:4319/note">
 */
(function () {
  "use strict";

  var meta = document.querySelector('meta[name="kw-studio-notes"]');
  var ENDPOINT = (meta && meta.getAttribute("content")) || window.__KW_STUDIO_NOTES__;
  if (!ENDPOINT) return;
  if (window.parent === window) return;          // 不是被嵌的，退出
  if (window.__kwStudioHook) return;             // 幂等
  window.__kwStudioHook = true;

  var sent = 0;

  /* ── 锚点：这条意见是哪一屏、哪一个动画动作 ─────────────────────────────
   * 动画层的每一个动作本来就用 `C(step, i)`（第 step 屏第 i 句台词）命名，而
   * `__SPANS__` / `__CUES__` 就在这份文档里。所以写一句时顺手盖个章，意见就落到
   * **具体那一下动画**上，而不是一句漂浮的"再压小一点"。
   * 这是只有 composition 侧才拿得到的信息 —— studio 的 prompt 里没有它。 */
  function anchor() {
    var tl = window.__timelines && window.__timelines.main;
    var t = 0;
    try { t = (tl && typeof tl.time === "function") ? tl.time() : 0; } catch (e) { t = 0; }
    var spans = window.__SPANS__ || {};
    var stepId = null;
    for (var k in spans) {
      if (!Object.prototype.hasOwnProperty.call(spans, k)) continue;
      var sp = spans[k];
      if (sp && t >= sp[0] && t < sp[1]) { stepId = k.replace(/^step-/, ""); break; }
    }
    // 落空（比如正好停在整片末尾）就取最后一屏，宁可粗一点也不要没有锚点
    if (!stepId) {
      for (var k2 in spans) {
        if (Object.prototype.hasOwnProperty.call(spans, k2)) stepId = k2.replace(/^step-/, "");
      }
    }
    var cues = ((window.__CUES__ || {})["step-" + stepId]) || [];
    var cueIndex = -1;
    for (var i = 0; i < cues.length; i++) { if (t >= cues[i]) cueIndex = i; }
    return { t: Math.round(t * 1000) / 1000, stepId: stepId,
             cueIndex: cueIndex >= 0 ? cueIndex : null,
             anchor: cueIndex >= 0 ? ("C(" + JSON.stringify(stepId) + ", " + cueIndex + ")") : null };
  }

  function post(text, kind) {
    if (!text || typeof text !== "string") return;
    var where = anchor();
    try {
      // keepalive 让这一枪在页面被关掉时也能发完；失败一律吞掉。
      fetch(ENDPOINT, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ text: text, kind: kind || "studio",
                               t: where.t, stepId: where.stepId,
                               cueIndex: where.cueIndex, anchor: where.anchor }),
        keepalive: true,
        mode: "cors"
      }).then(function () { sent += 1; }).catch(function () {});
    } catch (e) { /* 收集器没起、CORS 被挡 —— 都不该影响 studio */ }
  }

  function install() {
    var clip;
    try {
      clip = parent.navigator && parent.navigator.clipboard;
    } catch (e) {
      return false;                              // 跨源：不是我们要处理的场景
    }
    if (!clip || typeof clip.writeText !== "function") return false;
    if (clip.__kwWrapped) return true;           // 已经包过（例如重载）

    var original = clip.writeText.bind(clip);
    var wrapped = function (text) {
      // 先照原样写剪贴板，再顺手记一份。顺序无关紧要，但原函数必须被调用。
      var result = original(text);
      post(text, "agent-prompt");
      return result;
    };
    wrapped.__kwWrapped = true;
    try {
      clip.writeText = wrapped;
      clip.__kwWrapped = true;
    } catch (e) {
      return false;                              // 不可写就不硬来
    }
    return true;
  }

  // studio 可能在 composition 之后才把 player 挂起来；轮询几次再装。
  var tries = 0;
  var timer = setInterval(function () {
    tries += 1;
    if (install() || tries > 40) clearInterval(timer);
  }, 250);

  // 对面暴露一个只读状态，便于用 CDP 断言钩子真的装上了（测试与诊断都要用）。
  window.__kwStudioHookState = function () {
    return { installed: !!(parent.navigator && parent.navigator.clipboard
                           && parent.navigator.clipboard.__kwWrapped), sent: sent };
  };
})();
