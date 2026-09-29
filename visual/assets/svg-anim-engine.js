/**
 * VideoCraftAnimEngine v4 — Camera Rig, Focus Spotlight & Product UI Choreography Engine
 *
 * Upgrades v3 ("static poster step-by-step appear") to v4 ("Camera + Spotlight + 12 Primitives + Sub-cue Sync"):
 *   1. Virtual Camera Rig (`camera`: 'none' | 'focus-step' | 'focus-left' | 'focus-right' | 'zoom-center')
 *      Automatically wraps SVG content in `<g class="vc-camera-stage">` and smoothly pans/zooms to the
 *      active step's bounding box (clamped safely to 1920x1080).
 *   2. Focus & Dim State Machine (`focusMode`: 'spotlight' | 'accumulate')
 *      In 'spotlight' mode, previous steps (`step < targetStep`) smoothly dim to `opacity: 0.34` so the
 *      viewer's eye locks onto the active step; 'all' restores full 1.0 visibility.
 *   3. 12 Compound Choreography Primitives (8 Editorial + 4 Product UI Micro-interactions):
 *      - Editorial: `meter-halt`, `draw-stroke`, `cursor-wipe`, `slot-push`, `polaroid-slap`,
 *                   `stagger-cards`, `stamp-in`, `paper-unroll`
 *      - Product UI:
 *        * `cursor-click`: Animated pointer flies in along an arc -> hovers -> clicks (scale 0.94 + ripple ring) -> reveals target
 *        * `number-ticker`: Numeric text nodes count up from 0 to target value while bars/badges charge up
 *        * `card-expand`: Spring panel expansion from compact header (`scaleY(0.22)`) with staggered child rows
 *        * `spotlight-sweep`: Diagonal highlight sheen sweeps across the card + subtle ambient hold breathing
 *   4. Per-step Choreography Overrides (`setChoreography(svgRoot, map)`):
 *      Allows runtime/review-page tweaking of `{ anim, camera, dimPrev, subDelayMs, startSec }` with 0ms rebuild.
 *
 * Dual-mode deterministic execution:
 *   - Browser live preview (WAAPI): `VideoCraftAnimEngine.setStep(svgRoot, stepIndex, true, options)`
 *   - HyperFrames render (GSAP):    `VideoCraftAnimEngine.registerGsapTimeline(gsap, tl, svgRoot, stepConfigMap)`
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    root.VideoCraftAnimEngine = factory();
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  const EASE_OUT = 'cubic-bezier(0.22, 1, 0.36, 1)';
  const EASE_SPRING = 'cubic-bezier(0.28, 1.38, 0.54, 1)';
  const EASE_OVERSHOOT = 'cubic-bezier(0.34, 1.56, 0.64, 1)';
  const EASE_IMPACT = 'cubic-bezier(0.2, 0.9, 0.3, 1)';
  const EASE_CAMERA = 'cubic-bezier(0.25, 1, 0.35, 1)';

  let speedMultiplier = 1;
  const choreographyStore = new WeakMap(); // svgRoot -> { focusMode, steps: { [step]: { anim, camera, subDelayMs, startSec } } }
  const activeTickers = new WeakMap();     // svgRoot -> number[] (rAF ids)

  const PRIMITIVE_CATALOG = [
    { id: 'meter-halt', label: '进度冲刺撞墙 (meter-halt)', group: 'editorial' },
    { id: 'draw-stroke', label: '笔迹生长+端点弹跳 (draw-stroke)', group: 'editorial' },
    { id: 'cursor-wipe', label: '游标切入擦出 (cursor-wipe)', group: 'editorial' },
    { id: 'slot-push', label: '几何槽撑开推字 (slot-push)', group: 'editorial' },
    { id: 'polaroid-slap', label: '相纸甩落+胶带封固 (polaroid-slap)', group: 'editorial' },
    { id: 'stagger-cards', label: '错峰弹簧升卡 (stagger-cards)', group: 'editorial' },
    { id: 'stamp-in', label: '印章重砸过冲 (stamp-in)', group: 'editorial' },
    { id: 'paper-unroll', label: '卷宗展开浮现 (paper-unroll)', group: 'editorial' },
    { id: 'cursor-click', label: '🖱️ 拟真光标点击展开 (cursor-click)', group: 'product-ui' },
    { id: 'number-ticker', label: '🔢 数字滚轮攀升充能 (number-ticker)', group: 'product-ui' },
    { id: 'card-expand', label: '📐 面板丝滑撑开让位 (card-expand)', group: 'product-ui' },
    { id: 'spotlight-sweep', label: '✨ 流光扫掠+微呼吸 (spotlight-sweep)', group: 'product-ui' }
  ];

  function setSpeedMultiplier(mult) {
    speedMultiplier = Number(mult) || 1;
  }

  function getSpeedMultiplier() {
    return speedMultiplier;
  }

  function getChoreography(svgRoot) {
    if (!svgRoot) return { focusMode: 'spotlight', steps: {} };
    if (!choreographyStore.has(svgRoot)) {
      const defaultFocus = svgRoot.getAttribute('data-focus-mode') || 'spotlight';
      choreographyStore.set(svgRoot, { focusMode: defaultFocus, steps: {} });
    }
    return choreographyStore.get(svgRoot);
  }

  function setChoreography(svgRoot, patch = {}) {
    if (!svgRoot) return;
    const cur = getChoreography(svgRoot);
    if (patch.focusMode) cur.focusMode = patch.focusMode;
    if (patch.steps) {
      Object.keys(patch.steps).forEach(k => {
        cur.steps[k] = Object.assign({}, cur.steps[k] || {}, patch.steps[k]);
      });
    }
    return cur;
  }

  /**
   * Ensure a single `<g class="vc-camera-stage">` wraps all visual layers inside `<svg>`
   * so camera pan/zoom never collides with individual element transforms.
   */
  function ensureCameraStage(svgRoot) {
    if (!svgRoot) return null;
    let stage = svgRoot.querySelector(':scope > g.vc-camera-stage');
    if (stage) return stage;
    const ns = 'http://www.w3.org/2000/svg';
    stage = document.createElementNS(ns, 'g');
    stage.setAttribute('class', 'vc-camera-stage');
    stage.style.transformOrigin = '0px 0px';
    const children = Array.from(svgRoot.childNodes);
    children.forEach(node => {
      if (node.nodeType === 1) {
        const tag = node.tagName.toLowerCase();
        if (tag === 'defs' || node.getAttribute('data-role') === 'anchor') return;
      }
      stage.appendChild(node);
    });
    svgRoot.appendChild(stage);
    return stage;
  }

  function inspect(svgRoot) {
    if (!svgRoot) return [];
    const choreo = getChoreography(svgRoot);
    return Array.from(svgRoot.querySelectorAll('[data-step]')).map(el => {
      const stepNum = Number(el.getAttribute('data-step'));
      const over = (choreo.steps && choreo.steps[stepNum]) || {};
      return {
        id: el.id || `step-${stepNum}`,
        step: stepNum,
        anim: over.anim || el.getAttribute('data-anim') || 'stagger-cards',
        camera: over.camera || el.getAttribute('data-camera') || 'none',
        subDelayMs: over.subDelayMs !== undefined ? Number(over.subDelayMs) : Number(el.getAttribute('data-sub-delay') || 0),
        cue: over.cue || el.getAttribute('data-cue') || '',
        relStartSec: over.relStartSec !== undefined ? Number(over.relStartSec) : (el.getAttribute('data-rel-start') ? Number(el.getAttribute('data-rel-start')) : undefined),
        startSec: over.startSec !== undefined ? Number(over.startSec) : undefined,
        nested: Boolean(el.parentElement && el.parentElement.closest('[data-step]')),
        el
      };
    });
  }

  function clearTickers(svgRoot) {
    const list = activeTickers.get(svgRoot);
    if (list && list.length) {
      list.forEach(id => cancelAnimationFrame(id));
    }
    activeTickers.set(svgRoot, []);
  }

  function cancelAll(svgRoot) {
    if (!svgRoot) return;
    clearTickers(svgRoot);
    svgRoot.querySelectorAll('.vc-transient-overlay').forEach(node => node.remove());
    svgRoot.querySelectorAll('[data-vc-orig-text]').forEach(node => {
      node.textContent = node.getAttribute('data-vc-orig-text');
    });
    svgRoot.querySelectorAll('[data-step], [data-step] *').forEach(node => {
      if (typeof node.getAnimations === 'function') {
        node.getAnimations().forEach(a => a.cancel());
      }
      node.style.clipPath = '';
      node.style.transform = '';
      node.style.opacity = '';
      node.style.filter = '';
    });
  }

  /**
   * Compute safe camera matrix `{ scale, tx, ty }` for 1920x1080 canvas.
   * Zooms smoothly around the active step's center while gently gliding 20% toward
   * the stage focal point so cards never get clipped or collide with the speaker zone.
   */
  function computeCameraTarget(svgRoot, item, mode) {
    const W = 1920, H = 1080;
    const speakerW = Number((svgRoot && svgRoot.getAttribute('data-speaker-width')) || 0);
    // When left speaker column is present (split-stage 16:9), never shift or pan the canvas
    // so right-stage graphics never get occluded by the speaker column.
    if (speakerW > 0 || !mode || mode === 'none' || !item || !item.el) {
      return { scale: 1, tx: 0, ty: 0 };
    }
    let box = { x: 660, y: 200, width: 1120, height: 680 };
    try {
      const b = item.el.getBBox();
      if (b && b.width > 20 && b.height > 20) box = b;
    } catch (_) { /* fallback */ }

    let scale = 1.04;
    let cx = box.x + box.width / 2;
    let cy = box.y + box.height / 2;

    if (mode === 'focus-left') {
      scale = 1.05;
      cx = box.x + Math.min(box.width * 0.35, 340);
    } else if (mode === 'focus-right') {
      scale = 1.05;
      cx = box.x + Math.max(box.width * 0.65, box.width - 340);
    } else if (mode === 'zoom-center') {
      scale = 1.04;
      cx = W * 0.5;
      cy = H * 0.5;
    } else if (mode === 'focus-step') {
      scale = 1.045;
    }

    const tx = Math.round(Math.max(W * (1 - scale), Math.min(0, cx * (1 - scale))));
    const ty = Math.round(Math.max(H * (1 - scale), Math.min(0, cy * (1 - scale))));

    return {
      scale: Number(scale.toFixed(3)),
      tx,
      ty
    };
  }

  function animateCameraWAAPI(svgRoot, item, resolvedStep) {
    const stage = ensureCameraStage(svgRoot);
    if (!stage) return;
    const mode = resolvedStep === 'all' ? 'none' : (item ? item.camera : 'none');
    const { scale, tx, ty } = computeCameraTarget(svgRoot, item, mode);
    const nextTransform = scale === 1 && tx === 0 && ty === 0
      ? 'translate(0px, 0px) scale(1)'
      : `translate(${tx}px, ${ty}px) scale(${scale})`;

    const prevTransform = stage.getAttribute('data-vc-cam-transform') || 'translate(0px, 0px) scale(1)';
    stage.setAttribute('data-vc-cam-transform', nextTransform);

    if (typeof stage.animate === 'function' && prevTransform !== nextTransform) {
      stage.animate(
        [{ transform: prevTransform }, { transform: nextTransform }],
        { duration: Math.round(620 * speedMultiplier), easing: EASE_CAMERA, fill: 'both' }
      );
    } else {
      stage.style.transform = nextTransform;
    }
  }

  /**
   * Inject a temporary SVG cursor + click ripple for `cursor-click` primitive.
   */
  function spawnCursorClickOverlay(el, opts, subDelay) {
    let box = { x: 960, y: 540, width: 300, height: 120 };
    try {
      const targetNode = el.querySelector('.anim-node, .anim-badge, .anim-endpoint, .anim-card, .anim-body') || el;
      const b = targetNode.getBBox();
      if (b && b.width > 10) box = b;
    } catch (_) { /* ignore */ }

    const tx = Math.round(box.x + box.width * 0.52);
    const ty = Math.round(box.y + box.height * 0.52);
    const startX = tx + 110;
    const startY = ty + 85;

    const ns = 'http://www.w3.org/2000/svg';
    const layer = document.createElementNS(ns, 'g');
    layer.setAttribute('class', 'vc-transient-overlay');
    layer.style.pointerEvents = 'none';

    const ripple = document.createElementNS(ns, 'circle');
    ripple.setAttribute('cx', String(tx));
    ripple.setAttribute('cy', String(ty));
    ripple.setAttribute('r', '24');
    ripple.setAttribute('fill', 'none');
    ripple.setAttribute('stroke', '#E43D1E');
    ripple.setAttribute('stroke-width', '3');
    ripple.style.opacity = '0';
    ripple.style.transformOrigin = `${tx}px ${ty}px`;

    const cursor = document.createElementNS(ns, 'g');
    cursor.innerHTML = `
      <path d="M 0,0 L 0,26 L 7,20 L 12.5,31 L 17,28.5 L 11.5,17.5 L 20.5,17.5 Z"
            fill="#141413" stroke="#FAF8F5" stroke-width="2" stroke-linejoin="round"/>
    `;

    layer.appendChild(ripple);
    layer.appendChild(cursor);
    el.appendChild(layer);

    if (typeof cursor.animate === 'function') {
      cursor.animate([
        { opacity: 0, transform: `translate(${startX}px, ${startY}px) scale(1.1)` },
        { opacity: 1, transform: `translate(${tx}px, ${ty}px) scale(1)`, offset: 0.48 },
        { opacity: 1, transform: `translate(${tx}px, ${ty}px) scale(0.85)`, offset: 0.65 },
        { opacity: 1, transform: `translate(${tx}px, ${ty}px) scale(1)`, offset: 0.80 },
        { opacity: 0, transform: `translate(${tx + 18}px, ${ty + 22}px) scale(0.95)` }
      ], opts(660, EASE_OUT, subDelay));

      ripple.animate([
        { opacity: 0, transform: 'scale(0.25)' },
        { opacity: 0.9, transform: 'scale(0.6)', offset: 0.35 },
        { opacity: 0, transform: 'scale(1.8)' }
      ], opts(420, EASE_OUT, subDelay + 310));
    }
  }

  /**
   * Run numeric ticker count-up on text elements containing numbers.
   */
  function runNumberTickers(svgRoot, el, durationMs, delayMs) {
    const texts = Array.from(el.querySelectorAll('text.anim-count, [data-count-to], text'));
    const numRegex = /(-?\d+(?:\.\d+)?)/;
    const targets = texts.filter(t => t.classList.contains('anim-count') || numRegex.test(t.textContent || ''));
    if (!targets.length) return;

    const rafList = activeTickers.get(svgRoot) || [];
    targets.forEach(node => {
      const raw = node.getAttribute('data-vc-orig-text') || node.textContent || '';
      node.setAttribute('data-vc-orig-text', raw);
      const match = raw.match(numRegex);
      if (!match) return;
      const targetVal = parseFloat(match[1]);
      const isFloat = match[1].includes('.');
      const decimals = isFloat ? (match[1].split('.')[1] || '').length : 0;
      const prefix = raw.slice(0, match.index);
      const suffix = raw.slice((match.index || 0) + match[1].length);

      const startTime = performance.now() + delayMs * speedMultiplier;
      const totalDur = Math.max(240, durationMs * speedMultiplier);

      function tick(now) {
        if (now < startTime) {
          node.textContent = `${prefix}${isFloat ? (0).toFixed(decimals) : '0'}${suffix}`;
          rafList.push(requestAnimationFrame(tick));
          return;
        }
        const p = Math.min(1, (now - startTime) / totalDur);
        const eased = 1 - Math.pow(1 - p, 3);
        const cur = targetVal * eased;
        node.textContent = `${prefix}${isFloat ? cur.toFixed(decimals) : Math.round(cur)}${suffix}`;
        if (p < 1) {
          rafList.push(requestAnimationFrame(tick));
        } else {
          node.textContent = raw;
        }
      }
      rafList.push(requestAnimationFrame(tick));
    });
    activeTickers.set(svgRoot, rafList);
  }

  /**
   * Run character-by-character typewriter effect on `.anim-typewriter` text nodes.
   */
  function runTypewriters(svgRoot, el, durationMs, delayMs) {
    const nodes = Array.from(el.querySelectorAll('text.anim-typewriter, [data-typewriter]'));
    if (!nodes.length) return;
    const rafList = activeTickers.get(svgRoot) || [];
    nodes.forEach((node, idx) => {
      const raw = node.getAttribute('data-vc-orig-text') || node.textContent || '';
      node.setAttribute('data-vc-orig-text', raw);
      const startTime = performance.now() + (delayMs + idx * 120) * speedMultiplier;
      const totalDur = Math.max(220, durationMs * speedMultiplier);
      function tick(now) {
        if (now < startTime) {
          node.textContent = '';
          rafList.push(requestAnimationFrame(tick));
          return;
        }
        const p = Math.min(1, (now - startTime) / totalDur);
        const nChars = Math.max(1, Math.round(raw.length * p));
        node.textContent = p < 1 ? raw.slice(0, nChars) + '▋' : raw;
        if (p < 1) rafList.push(requestAnimationFrame(tick));
      }
      rafList.push(requestAnimationFrame(tick));
    });
    activeTickers.set(svgRoot, rafList);
  }

  /**
   * Universal internal graphic choreography: animates paths, bars, nodes, rings,
   * scanners, and typewriters inside any step with multi-beat sequential timing (1.2s - 1.8s)
   * so diagrams evolve organically along with the spoken sentence.
   */
  function runInternalGraphicChoreography(svgRoot, el, opts, sub) {
    // 1. Vector path drawing (stroke-dashoffset) — sequential circuit tracing
    el.querySelectorAll('.anim-stroke, [pathLength="1"]').forEach((p, idx) => {
      p.style.strokeDasharray = '1';
      p.animate([
        { strokeDashoffset: 1 },
        { strokeDashoffset: 0 }
      ], opts(720, EASE_OUT, sub + 120 + idx * 240));
    });

    // 2. Horizontal progress / meter bars (.anim-bar-h, .anim-fill)
    el.querySelectorAll('.anim-bar-h, .anim-fill').forEach((bar, idx) => {
      bar.style.transformBox = 'fill-box';
      bar.style.transformOrigin = '0% 50%';
      bar.animate([
        { transform: 'scaleX(0)' },
        { transform: 'scaleX(1)' }
      ], opts(1050, EASE_OUT, sub + 140 + idx * 220));
    });

    // 3. Vertical chart pillars (.anim-bar-v)
    el.querySelectorAll('.anim-bar-v').forEach((bar, idx) => {
      bar.style.transformBox = 'fill-box';
      bar.style.transformOrigin = '50% 100%';
      bar.animate([
        { opacity: 0, transform: 'scaleY(0.08)' },
        { opacity: 1, transform: 'scaleY(1)' }
      ], opts(780, EASE_SPRING, sub + 100 + idx * 220));
    });

    // 4. In-place diagram nodes & rings (.anim-node, .anim-ring, .anim-endpoint)
    el.querySelectorAll('.anim-node, .anim-ring, .anim-endpoint').forEach((node, idx) => {
      node.style.transformBox = 'fill-box';
      node.style.transformOrigin = '50% 50%';
      node.animate([
        { opacity: 0, transform: 'scale(0.82)' },
        { opacity: 1, transform: 'scale(1.03)', offset: 0.72 },
        { opacity: 1, transform: 'scale(1)' }
      ], opts(540, EASE_SPRING, sub + 80 + idx * 240));
    });

    // 5. Scanner / highlight beam (.anim-scan)
    el.querySelectorAll('.anim-scan').forEach((scan, idx) => {
      scan.animate([
        { opacity: 0, transform: 'translateX(-48px)' },
        { opacity: 1, offset: 0.25 },
        { opacity: 1, transform: 'translateX(0px)' }
      ], opts(880, EASE_OUT, sub + 120 + idx * 180));
    });

    // 6. Typewriter text (.anim-typewriter) — 1.35s character-by-character typing
    runTypewriters(svgRoot, el, 1350, sub + 80);

    // 7. Explicit counter text (.anim-count) — 1.35s numeric count-up
    if (el.querySelector('.anim-count, [data-count-to]')) {
      runNumberTickers(svgRoot, el, 1350, sub + 120);
    }
  }

  function playPrimitive(svgRoot, item) {
    const { el, anim, nested, subDelayMs = 0 } = item;
    const baseDelay = nested ? 180 : 0;
    const sub = Math.max(0, Number(subDelayMs) || 0);
    const opts = (dur, easing = EASE_OUT, extraDelay = 0) => ({
      duration: Math.round(dur * speedMultiplier),
      delay: Math.round((baseDelay + extraDelay) * speedMultiplier),
      easing,
      fill: 'both'
    });

    // Always trigger internal graphic sub-animations (strokes, bars, nodes, typewriters)
    runInternalGraphicChoreography(svgRoot, el, opts, sub);

    if (anim === 'meter-halt') {
      const bar = el.querySelector('.wipe-bar');
      if (bar) {
        bar.style.transformBox = 'fill-box';
        bar.style.transformOrigin = '50% 0%';
        bar.animate([{ transform: 'scaleY(0)', opacity: 0.2 }, { transform: 'scaleY(1)', opacity: 1 }], opts(260, EASE_OUT, 0));
      }
      const wall = el.querySelector('.anim-wall');
      if (wall) {
        wall.animate([
          { opacity: 0.3, transform: 'translateX(0px)' },
          { opacity: 1, transform: 'translateX(6px)', offset: 0.58 },
          { opacity: 1, transform: 'translateX(-2px)', offset: 0.80 },
          { opacity: 1, transform: 'translateX(0px)' }
        ], opts(380, EASE_OVERSHOOT, 240 + sub));
      }
      const badge = el.querySelector('.anim-badge');
      if (badge) {
        badge.style.transformBox = 'fill-box';
        badge.style.transformOrigin = '50% 50%';
        badge.animate([{ opacity: 0, transform: 'scale(0.82)' }, { opacity: 1, transform: 'scale(1)' }], opts(300, EASE_SPRING, 320 + sub));
      }
      runNumberTickers(svgRoot, el, 480, 60 + sub);
    } else if (anim === 'draw-stroke') {
      const body = el.querySelector('.anim-body, .anim-label');
      if (body) {
        body.animate([{ clipPath: 'inset(0 100% 0 0)' }, { clipPath: 'inset(0 0% 0 0)' }], opts(360, EASE_OUT, 0));
      }
    } else if (anim === 'cursor-wipe' || anim === 'bar-wipe') {
      const bar = el.querySelector('.wipe-bar');
      if (bar) {
        bar.style.transformBox = 'fill-box';
        bar.style.transformOrigin = '50% 0%';
        bar.animate([{ transform: 'scaleY(0)', opacity: 0 }, { transform: 'scaleY(1)', opacity: 1 }], opts(280, EASE_OUT, 0));
      }
      const body = el.querySelector('.anim-body');
      if (body) {
        body.animate([
          { clipPath: 'inset(0 100% 0 0)', opacity: 0.35 },
          { clipPath: 'inset(0 0% 0 0)', opacity: 1 }
        ], opts(420, EASE_OUT, 30));
      }
      const subEl = el.querySelector('.anim-sub');
      if (subEl) {
        subEl.animate([{ opacity: 0 }, { opacity: 1 }], opts(320, EASE_OUT, 180));
      }
      const stamp = el.querySelector('.anim-stamp');
      if (stamp) {
        stamp.style.transformBox = 'fill-box';
        stamp.style.transformOrigin = '50% 50%';
        stamp.animate([{ opacity: 0, transform: 'scale(1.25)' }, { opacity: 1, transform: 'scale(1)' }], opts(280, EASE_OVERSHOOT, 320 + sub));
      }
    } else if (anim === 'slot-push' || anim === 'slot-expand') {
      const pushPx = Number(el.getAttribute('data-push') || 90);
      const left = el.querySelector('.slot-left');
      const right = el.querySelector('.slot-right');
      const core = el.querySelector('.slot-core');
      if (left) left.animate([{ transform: `translateX(${pushPx}px)` }, { transform: 'translateX(0px)' }], opts(460, EASE_OUT, 0));
      if (right) right.animate([{ transform: `translateX(-${pushPx}px)` }, { transform: 'translateX(0px)' }], opts(460, EASE_OUT, 0));
      if (core) {
        core.style.transformBox = 'fill-box';
        core.style.transformOrigin = '50% 50%';
        core.animate([{ opacity: 0, transform: 'scaleX(0.15)' }, { opacity: 1, transform: 'scaleX(1)' }], opts(440, EASE_SPRING, 40));
      }
    } else if (anim === 'polaroid-slap' || anim === 'z-stack-drop') {
      const units = el.querySelectorAll('.polaroid-unit, .anim-card');
      (units.length > 0 ? Array.from(units) : [el]).forEach((unit, uIdx) => {
        const uDelay = sub + uIdx * 140;
        unit.style.transformBox = 'fill-box';
        unit.style.transformOrigin = '50% 50%';
        unit.animate([
          { opacity: 0, clipPath: 'inset(0 100% 0 0)' },
          { opacity: 1, clipPath: 'inset(0 0% 0 0)' }
        ], opts(400, EASE_OUT, uDelay));
      });
    } else if (anim === 'stagger-cards' || anim === 'pop-card') {
      const cards = el.querySelectorAll('.anim-card');
      (cards.length > 0 ? Array.from(cards) : [el]).forEach((c, idx) => {
        c.style.transformBox = 'fill-box';
        c.style.transformOrigin = '50% 50%';
        c.animate([
          { opacity: 0, clipPath: 'inset(0 0 100% 0)' },
          { opacity: 1, clipPath: 'inset(0 0 0% 0)' }
        ], opts(380, EASE_OUT, sub + idx * 110));
      });
    } else if (anim === 'stamp-in') {
      const stamps = el.querySelectorAll('.anim-stamp, .anim-card');
      (stamps.length > 0 ? Array.from(stamps) : [el]).forEach((st, idx) => {
        st.style.transformBox = 'fill-box';
        st.style.transformOrigin = '50% 50%';
        st.animate([
          { opacity: 0, transform: 'scale(1.14)' },
          { opacity: 1, transform: 'scale(0.98)', offset: 0.72 },
          { opacity: 1, transform: 'scale(1)' }
        ], opts(320, EASE_OVERSHOOT, sub + idx * 110));
      });
    } else if (anim === 'paper-unroll') {
      const paper = el.querySelector('.anim-paper, .anim-card') || el;
      paper.animate([
        { clipPath: 'inset(0 100% 0 0)', opacity: 0.4 },
        { clipPath: 'inset(0 0% 0 0)', opacity: 1 }
      ], opts(440, EASE_OUT, sub));
    } else if (anim === 'cursor-click') {
      const targetCards = el.querySelectorAll('.anim-card, .anim-body, .anim-endpoint, .anim-stamp');
      (targetCards.length > 0 ? Array.from(targetCards) : [el]).forEach((t, idx) => {
        t.style.transformBox = 'fill-box';
        t.style.transformOrigin = '50% 50%';
        t.animate([
          { opacity: 0.35, transform: 'scale(0.97)' },
          { opacity: 0.65, transform: 'scale(0.95)', offset: 0.52 },
          { opacity: 1, transform: 'scale(1.02)', offset: 0.80 },
          { opacity: 1, transform: 'scale(1)' }
        ], opts(600, EASE_SPRING, sub + idx * 80));
      });
      spawnCursorClickOverlay(el, opts, sub);
    } else if (anim === 'number-ticker') {
      runNumberTickers(svgRoot, el, 620, sub + 40);
    } else if (anim === 'card-expand') {
      const targets = el.querySelectorAll('.anim-card');
      (targets.length > 0 ? Array.from(targets) : [el]).forEach((t, idx) => {
        t.animate([
          { opacity: 0, clipPath: 'inset(0 0 88% 0)' },
          { opacity: 1, clipPath: 'inset(0 0 0% 0)' }
        ], opts(440, EASE_OUT, sub + idx * 90));
      });
    } else if (anim === 'spotlight-sweep') {
      el.animate([
        { opacity: 0, clipPath: 'inset(0 100% 0 0)' },
        { opacity: 1, clipPath: 'inset(0 0% 0 0)' }
      ], opts(480, EASE_OUT, sub));
    }
  }

  function setStep(svgRoot, targetStep, animateTarget = true, options = {}) {
    if (!svgRoot) return { items: [], maxStep: 0, resolved: 0 };
    if (options.focusMode || options.steps) {
      setChoreography(svgRoot, options);
    }
    cancelAll(svgRoot);
    ensureCameraStage(svgRoot);

    const choreo = getChoreography(svgRoot);
    const focusMode = options.focusMode || choreo.focusMode || 'spotlight';
    const items = inspect(svgRoot);
    const maxStep = items.reduce((m, x) => Math.max(m, x.step), 0);
    const resolved = targetStep === 'all' ? maxStep : Number(targetStep);
    let activeItem = null;

    items.forEach(item => {
      if (item.step > resolved) {
        item.el.setAttribute('data-vc-state', 'hidden');
        item.el.style.opacity = '0';
      } else if (targetStep !== 'all' && item.step < resolved && focusMode === 'spotlight') {
        // Spotlight state machine: previous steps gently recede into context!
        item.el.setAttribute('data-vc-state', 'dimmed');
        item.el.style.opacity = '0.34';
        item.el.querySelectorAll('[pathLength="1"]').forEach(p => {
          p.style.strokeDasharray = '1';
          p.style.strokeDashoffset = '0';
        });
      } else {
        item.el.setAttribute('data-vc-state', 'active');
        item.el.style.opacity = '1';
        item.el.querySelectorAll('[pathLength="1"]').forEach(p => {
          p.style.strokeDasharray = '1';
          p.style.strokeDashoffset = '0';
        });
        if (item.step === resolved) {
          activeItem = item;
          if (animateTarget && targetStep !== 'all') {
            playPrimitive(svgRoot, item);
          }
        }
      }
    });

    animateCameraWAAPI(svgRoot, activeItem, targetStep);
    return { items, maxStep, resolved, focusMode, activeItem };
  }

  /**
   * Register seek-safe GSAP tweens on `tl` (`window.__timelines["main"]`)
   * for HyperFrames deterministic rendering.
   *
   * `stepConfigMap` can be either:
   *   - legacy `{ 1: 0.4, 2: 2.8, 3: 5.1 }` (step -> startSec)
   *   - v4 rich config `{ focusMode: 'spotlight', steps: { 1: { startSec: 0.4, anim: 'meter-halt', camera: 'focus-step', subDelaySec: 0.5 } } }`
   */
  function registerGsapTimeline(gsap, tl, svgRoot, stepConfigMap = {}) {
    if (!gsap || !tl || !svgRoot) return;
    const isRich = stepConfigMap && typeof stepConfigMap === 'object' && stepConfigMap.steps;
    const focusMode = isRich ? (stepConfigMap.focusMode || 'spotlight') : (svgRoot.getAttribute('data-focus-mode') || 'spotlight');
    const stepEntries = isRich ? stepConfigMap.steps : stepConfigMap;

    if (isRich) {
      setChoreography(svgRoot, stepConfigMap);
    }

    const stage = ensureCameraStage(svgRoot);
    if (stage) {
      gsap.set(stage, { x: 0, y: 0, scale: 1, transformOrigin: '0px 0px' });
    }

    const items = inspect(svgRoot);
    items.forEach((item, itemIdx) => {
      const { el, step } = item;
      const rawCfg = stepEntries[step];
      const cfg = (rawCfg && typeof rawCfg === 'object') ? rawCfg : { startSec: Number(rawCfg ?? 0) };
      const t0 = Number(cfg.startSec ?? item.startSec ?? 0);
      const anim = cfg.anim || item.anim;
      const camera = cfg.camera || item.camera || 'none';
      const subSec = Number(cfg.subDelaySec ?? (item.subDelayMs / 1000) ?? 0);

      // Initial hidden state outside timeline (HyperFrames rule: frame 0 determinism)
      gsap.set(el, { autoAlpha: 0 });
      tl.set(el, { autoAlpha: 1 }, t0);

      // Spotlight dimming of previous steps when this step activates
      if (focusMode === 'spotlight' && itemIdx > 0) {
        const prevEls = items.slice(0, itemIdx).map(x => x.el);
        tl.to(prevEls, { autoAlpha: 0.34, duration: 0.38, ease: 'power2.out' }, t0);
      }

      // Camera Rig Pan & Zoom
      if (stage) {
        const camTarget = computeCameraTarget(svgRoot, item, camera);
        tl.to(stage, {
          x: camTarget.tx,
          y: camTarget.ty,
          scale: camTarget.scale,
          duration: 0.62,
          ease: 'power3.out'
        }, t0);
      }

      if (anim === 'draw-stroke') {
        const paths = el.querySelectorAll('.anim-stroke, [pathLength="1"]');
        const endpoints = el.querySelectorAll('.anim-endpoint, .anim-arrow');
        gsap.set(paths, { strokeDasharray: 1, strokeDashoffset: 1 });
        gsap.set(endpoints, { autoAlpha: 0, scale: 0.68, y: 6, transformOrigin: '50% 50%' });
        paths.forEach((p, idx) => {
          tl.to(p, { strokeDashoffset: 0, duration: 0.46, ease: 'power3.out' }, t0 + subSec + idx * 0.065);
        });
        endpoints.forEach((ep, idx) => {
          tl.to(ep, { autoAlpha: 1, scale: 1, y: 0, duration: 0.28, ease: 'back.out(1.8)' }, t0 + subSec + 0.32 + idx * 0.075);
        });
      } else if (anim === 'slot-push' || anim === 'slot-expand') {
        const pushPx = Number(el.getAttribute('data-push') || 165);
        const left = el.querySelector('.slot-left');
        const right = el.querySelector('.slot-right');
        const core = el.querySelector('.slot-core');
        const paths = el.querySelectorAll('.anim-stroke, [pathLength="1"]');
        const endpoints = el.querySelectorAll('.anim-endpoint');
        if (left) {
          gsap.set(left, { x: pushPx });
          tl.to(left, { x: 0, duration: 0.52, ease: 'back.out(1.4)' }, t0);
        }
        if (right) {
          gsap.set(right, { x: -pushPx });
          tl.to(right, { x: 0, duration: 0.52, ease: 'back.out(1.4)' }, t0);
        }
        if (core) {
          gsap.set(core, { autoAlpha: 0, scaleX: 0.04, transformOrigin: '50% 50%' });
          tl.to(core, { autoAlpha: 1, scaleX: 1, duration: 0.46, ease: 'power3.out' }, t0 + 0.06);
        }
        gsap.set(paths, { strokeDasharray: 1, strokeDashoffset: 1 });
        paths.forEach((p, idx) => {
          tl.to(p, { strokeDashoffset: 0, duration: 0.42, ease: 'power2.out' }, t0 + subSec + 0.16 + idx * 0.05);
        });
        gsap.set(endpoints, { autoAlpha: 0, scale: 0.5, transformOrigin: '50% 50%' });
        endpoints.forEach((ep, idx) => {
          tl.to(ep, { autoAlpha: 1, scale: 1, duration: 0.26, ease: 'back.out(2)' }, t0 + subSec + 0.34 + idx * 0.055);
        });
      } else if (anim === 'polaroid-slap' || anim === 'z-stack-drop') {
        const units = el.querySelectorAll('.polaroid-unit');
        const targets = units.length > 0 ? Array.from(units) : [el];
        targets.forEach((unit, uIdx) => {
          const uTime = t0 + subSec + uIdx * 0.16;
          const card = unit.querySelector('.anim-card') || unit;
          const shadow = unit.querySelector('.anim-shadow');
          const tape = unit.querySelector('.anim-tape');
          gsap.set(card, { autoAlpha: 0, y: -36, scale: 1.14, rotation: -2.5, transformOrigin: '50% 50%' });
          tl.to(card, { autoAlpha: 1, y: 0, scale: 1, rotation: 0, duration: 0.42, ease: 'back.out(1.6)' }, uTime);
          if (shadow) {
            gsap.set(shadow, { autoAlpha: 0.04, x: 14, y: 20, scale: 1.08, transformOrigin: '50% 50%' });
            tl.to(shadow, { autoAlpha: 0.18, x: 0, y: 0, scale: 1, duration: 0.42, ease: 'power3.out' }, uTime);
          }
          if (tape) {
            gsap.set(tape, { autoAlpha: 0, scaleX: 0, transformOrigin: '0% 50%' });
            tl.to(tape, { autoAlpha: 1, scaleX: 1, duration: 0.24, ease: 'power2.out' }, uTime + 0.26);
          }
        });
      } else if (anim === 'meter-halt' || anim === 'number-ticker') {
        const fill = el.querySelector('.anim-fill');
        const wall = el.querySelector('.anim-wall');
        const badge = el.querySelector('.anim-badge');
        if (fill) {
          gsap.set(fill, { scaleX: 0, transformOrigin: '0% 50%' });
          tl.to(fill, { scaleX: 1, duration: 0.42, ease: 'power4.out' }, t0 + subSec + 0.06);
        }
        if (wall) {
          tl.to(wall, { x: 6, duration: 0.07, yoyo: true, repeat: 3, ease: 'power1.inOut' }, t0 + subSec + 0.26);
        }
        if (badge) {
          gsap.set(badge, { autoAlpha: 0, scale: 1.38, y: -6, transformOrigin: '50% 50%' });
          tl.to(badge, { autoAlpha: 1, scale: 1, y: 0, duration: 0.28, ease: 'back.out(2)' }, t0 + subSec + 0.36);
        }
      } else if (anim === 'cursor-click' || anim === 'card-expand' || anim === 'spotlight-sweep') {
        const cards = el.querySelectorAll('.anim-card, .anim-body, .anim-endpoint, .anim-stamp');
        const targets = cards.length > 0 ? Array.from(cards) : [el];
        gsap.set(targets, { autoAlpha: 0, y: 14, scale: 0.94, transformOrigin: '50% 50%' });
        targets.forEach((c, idx) => {
          tl.to(c, { autoAlpha: 1, y: 0, scale: 1, duration: 0.44, ease: 'back.out(1.7)' }, t0 + subSec + idx * 0.09);
        });
      } else {
        const cards = el.querySelectorAll('.anim-card, .anim-stamp, .anim-body');
        const targets = cards.length > 0 ? Array.from(cards) : [el];
        gsap.set(targets, { autoAlpha: 0, y: 16, scale: 0.96, transformOrigin: '50% 50%' });
        targets.forEach((c, idx) => {
          tl.to(c, { autoAlpha: 1, y: 0, scale: 1, duration: 0.36, ease: 'back.out(1.4)' }, t0 + subSec + idx * 0.11);
        });
      }
    });
  }

  return {
    version: '4.0.0',
    PRIMITIVE_CATALOG,
    inspect,
    setStep,
    cancelAll,
    playPrimitive,
    registerGsapTimeline,
    setChoreography,
    getChoreography,
    computeCameraTarget,
    setSpeedMultiplier,
    getSpeedMultiplier
  };
});
