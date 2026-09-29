/**
 * VideoCraftAnimEngine v3 — Compound Sub-Element Choreography Interpreter
 *
 * Drives pre-wired SVG screens produced by `planners-ppt-hell` (video route)
 * following `references/svg-animation-contract.md`.
 *
 * Supports two execution modes:
 *   1. Interactive / Preview WAAPI mode:
 *      VideoCraftAnimEngine.setStep(svgRoot, stepIndex, true);
 *   2. HyperFrames deterministic GSAP timeline mode (seek-safe for rendering):
 *      VideoCraftAnimEngine.registerGsapTimeline(gsap, tl, svgRoot, { 1: 0.4, 2: 2.8, 3: 5.1 });
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    root.VideoCraftAnimEngine = factory();
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  const EASE_OUT = 'cubic-bezier(0.22, 1, 0.36, 1)';
  const EASE_OVERSHOOT = 'cubic-bezier(0.34, 1.56, 0.64, 1)';
  const EASE_IMPACT = 'cubic-bezier(0.2, 0.9, 0.3, 1)';
  let speedMultiplier = 1; // 1 = 1x normal speed, 2 = 0.5x slow-motion

  function setSpeedMultiplier(mult) {
    speedMultiplier = Number(mult) || 1;
  }

  function getSpeedMultiplier() {
    return speedMultiplier;
  }

  function inspect(svgRoot) {
    if (!svgRoot) return [];
    return Array.from(svgRoot.querySelectorAll('[data-step]')).map(el => ({
      id: el.id || '(anonymous)',
      step: Number(el.getAttribute('data-step')),
      anim: el.getAttribute('data-anim') || 'stagger-cards',
      cue: el.getAttribute('data-cue') || '',
      nested: Boolean(el.parentElement && el.parentElement.closest('[data-step]')),
      el
    }));
  }

  function cancelAll(svgRoot) {
    if (!svgRoot) return;
    svgRoot.querySelectorAll('[data-step], [data-step] *').forEach(node => {
      if (typeof node.getAnimations === 'function') {
        node.getAnimations().forEach(a => a.cancel());
      }
      node.style.clipPath = '';
      node.style.transform = '';
      node.style.opacity = '';
    });
  }

  function playPrimitive(item) {
    const { el, anim, nested } = item;
    const baseDelay = nested ? 220 : 0;
    const opts = (dur, easing = EASE_OUT, extraDelay = 0) => ({
      duration: Math.round(dur * speedMultiplier),
      delay: Math.round((baseDelay + extraDelay) * speedMultiplier),
      easing,
      fill: 'both'
    });

    if (anim === 'meter-halt') {
      const bar = el.querySelector('.wipe-bar');
      if (bar) {
        bar.animate([
          { transform: 'scaleY(0.15)', opacity: 0.2 },
          { transform: 'scaleY(1)', opacity: 1 }
        ], opts(260, EASE_OUT, 0));
      }
      const body = el.querySelector('.anim-body, .anim-label');
      if (body) {
        body.animate([
          { opacity: 0, transform: 'translateX(-16px)' },
          { opacity: 1, transform: 'translateX(0px)' }
        ], opts(340, EASE_OUT, 20));
      }
      const fill = el.querySelector('.anim-fill');
      if (fill) {
        fill.animate([
          { transform: 'scaleX(0)' },
          { transform: 'scaleX(1.07)', offset: 0.72 },
          { transform: 'scaleX(1)' }
        ], opts(440, EASE_IMPACT, 70));
      }
      const wall = el.querySelector('.anim-wall');
      if (wall) {
        wall.animate([
          { opacity: 0.35, transform: 'translateX(0px)' },
          { opacity: 1, transform: 'translateX(6px)', offset: 0.6 },
          { opacity: 1, transform: 'translateX(-2px)', offset: 0.82 },
          { opacity: 1, transform: 'translateX(0px)' }
        ], opts(380, EASE_OVERSHOOT, 250));
      }
      const badge = el.querySelector('.anim-badge');
      if (badge) {
        badge.animate([
          { opacity: 0, transform: 'scale(1.38) translateY(-6px)' },
          { opacity: 1, transform: 'scale(1) translateY(0px)' }
        ], opts(290, EASE_OVERSHOOT, 360));
      }
    } else if (anim === 'draw-stroke') {
      const paths = el.querySelectorAll('.anim-stroke, [pathLength="1"]');
      paths.forEach((p, idx) => {
        p.style.strokeDasharray = '1';
        p.animate([
          { strokeDashoffset: 1 },
          { strokeDashoffset: 0 }
        ], opts(460, EASE_OUT, idx * 65));
      });
      const endpoints = el.querySelectorAll('.anim-endpoint, .anim-arrow');
      endpoints.forEach((ep, idx) => {
        ep.animate([
          { opacity: 0, transform: 'scale(0.68) translateY(6px)' },
          { opacity: 1, transform: 'scale(1) translateY(0px)' }
        ], opts(280, EASE_OVERSHOOT, 320 + idx * 75));
      });
    } else if (anim === 'cursor-wipe' || anim === 'bar-wipe') {
      const bar = el.querySelector('.wipe-bar');
      if (bar) {
        bar.animate([
          { transform: 'translateX(-32px) scaleY(0.25)', opacity: 0 },
          { transform: 'translateX(0px) scaleY(1)', opacity: 1 }
        ], opts(320, EASE_OUT, 0));
      }
      const body = el.querySelector('.anim-body');
      if (body) {
        body.animate([
          { clipPath: 'inset(0 100% 0 0)', opacity: 0.2 },
          { clipPath: 'inset(0 0% 0 0)', opacity: 1 }
        ], opts(380, EASE_OUT, 40));
      }
      const sub = el.querySelector('.anim-sub');
      if (sub) {
        sub.animate([
          { opacity: 0, transform: 'translateY(12px)' },
          { opacity: 1, transform: 'translateY(0px)' }
        ], opts(340, EASE_OUT, 180));
      }
      el.querySelectorAll('.anim-stroke, [pathLength="1"]').forEach((p, idx) => {
        p.style.strokeDasharray = '1';
        p.animate([
          { strokeDashoffset: 1 },
          { strokeDashoffset: 0 }
        ], opts(420, EASE_OUT, 260 + idx * 60));
      });
      const stamp = el.querySelector('.anim-stamp');
      if (stamp) {
        stamp.animate([
          { opacity: 0, transform: 'scale(1.65) translateY(-18px)' },
          { opacity: 1, transform: 'scale(1) translateY(0px)' }
        ], opts(260, EASE_OVERSHOOT, 380));
      }
    } else if (anim === 'slot-push' || anim === 'slot-expand') {
      const pushPx = Number(el.getAttribute('data-push') || 165);
      const left = el.querySelector('.slot-left');
      const right = el.querySelector('.slot-right');
      const core = el.querySelector('.slot-core');
      if (left) {
        left.animate([
          { transform: `translateX(${pushPx}px)` },
          { transform: 'translateX(0px)' }
        ], opts(520, EASE_OVERSHOOT, 0));
      }
      if (right) {
        right.animate([
          { transform: `translateX(-${pushPx}px)` },
          { transform: 'translateX(0px)' }
        ], opts(520, EASE_OVERSHOOT, 0));
      }
      if (core) {
        core.animate([
          { opacity: 0, transform: 'scaleX(0.04)' },
          { opacity: 1, transform: 'scaleX(1)' }
        ], opts(460, EASE_OUT, 60));
      }
      el.querySelectorAll('.anim-stroke, [pathLength="1"]').forEach((p, idx) => {
        p.style.strokeDasharray = '1';
        p.animate([
          { strokeDashoffset: 1 },
          { strokeDashoffset: 0 }
        ], opts(420, EASE_OUT, 160 + idx * 50));
      });
      el.querySelectorAll('.anim-endpoint').forEach((ep, idx) => {
        ep.animate([
          { opacity: 0, transform: 'scale(0.5)' },
          { opacity: 1, transform: 'scale(1)' }
        ], opts(260, EASE_OVERSHOOT, 340 + idx * 55));
      });
      const sub = el.querySelector('.anim-sub');
      if (sub) {
        sub.animate([
          { opacity: 0, transform: 'translateY(12px)' },
          { opacity: 1, transform: 'translateY(0px)' }
        ], opts(340, EASE_OUT, 320));
      }
    } else if (anim === 'polaroid-slap' || anim === 'z-stack-drop') {
      const units = el.querySelectorAll('.polaroid-unit');
      const targets = units.length > 0 ? Array.from(units) : [el];
      targets.forEach((unit, uIdx) => {
        const uDelay = uIdx * 160;
        const card = unit.querySelector('.anim-card') || unit;
        const shadow = unit.querySelector('.anim-shadow');
        const tape = unit.querySelector('.anim-tape');
        card.animate([
          { opacity: 0, transform: 'translateY(-36px) scale(1.14) rotate(-2.5deg)' },
          { opacity: 1, transform: 'translateY(0px) scale(1) rotate(0deg)' }
        ], opts(420, EASE_OVERSHOOT, uDelay));
        if (shadow) {
          shadow.animate([
            { opacity: 0.04, transform: 'translate(14px, 20px) scale(1.08)' },
            { opacity: 0.18, transform: 'translate(0px, 0px) scale(1)' }
          ], opts(420, EASE_OUT, uDelay));
        }
        if (tape) {
          tape.animate([
            { opacity: 0, transform: 'scaleX(0)' },
            { opacity: 1, transform: 'scaleX(1)' }
          ], opts(240, EASE_OUT, uDelay + 260));
        }
      });
    } else if (anim === 'stagger-cards' || anim === 'pop-card') {
      const cards = el.querySelectorAll('.anim-card');
      if (cards.length > 0) {
        cards.forEach((c, idx) => {
          c.animate([
            { opacity: 0, transform: 'translateY(18px) scale(0.96)' },
            { opacity: 1, transform: 'translateY(0px) scale(1)' }
          ], opts(360, EASE_OUT, idx * 110));
        });
      } else {
        el.animate([
          { opacity: 0, transform: 'translateY(18px) scale(0.96)' },
          { opacity: 1, transform: 'translateY(0px) scale(1)' }
        ], opts(360, EASE_OUT, 0));
      }
      el.querySelectorAll('.anim-stroke, [pathLength="1"]').forEach(p => {
        p.style.strokeDasharray = '1';
        p.animate([
          { strokeDashoffset: 1 },
          { strokeDashoffset: 0 }
        ], opts(320, EASE_OUT, 140));
      });
    } else if (anim === 'stamp-in') {
      const stamps = el.querySelectorAll('.anim-stamp');
      const targets = stamps.length > 0 ? Array.from(stamps) : [el];
      targets.forEach((st, idx) => {
        st.animate([
          { opacity: 0, transform: 'scale(1.65) translateY(-14px)' },
          { opacity: 1, transform: 'scale(1) translateY(0px)' }
        ], opts(280, EASE_OVERSHOOT, idx * 140));
      });
    } else if (anim === 'paper-unroll') {
      const paper = el.querySelector('.anim-paper') || el;
      paper.animate([
        { clipPath: 'inset(0 100% 0 0)', opacity: 0.35 },
        { clipPath: 'inset(0 0% 0 0)', opacity: 1 }
      ], opts(460, EASE_OUT, 0));
      el.querySelectorAll('.anim-item').forEach((it, idx) => {
        it.animate([
          { opacity: 0, transform: 'translateY(10px)' },
          { opacity: 1, transform: 'translateY(0px)' }
        ], opts(280, EASE_OUT, 180 + idx * 95));
      });
    }
  }

  function setStep(svgRoot, targetStep, animateTarget = true) {
    cancelAll(svgRoot);
    const items = inspect(svgRoot);
    const maxStep = items.reduce((m, x) => Math.max(m, x.step), 0);
    const resolved = targetStep === 'all' ? maxStep : Number(targetStep);

    items.forEach(item => {
      if (item.step > resolved) {
        item.el.setAttribute('data-vc-state', 'hidden');
        item.el.style.opacity = '0';
      } else {
        item.el.setAttribute('data-vc-state', 'active');
        item.el.style.opacity = '1';
        item.el.querySelectorAll('[pathLength="1"]').forEach(p => {
          p.style.strokeDasharray = '1';
          p.style.strokeDashoffset = '0';
        });
        if (animateTarget && item.step === resolved && targetStep !== 'all') {
          playPrimitive(item);
        }
      }
    });
    return { items, maxStep, resolved };
  }

  /**
   * Register seek-safe GSAP tweens on `tl` (`window.__timelines["main"]`)
   * for HyperFrames rendering.
   * @param {object} gsap - GSAP instance
   * @param {object} tl - Paused main GSAP timeline
   * @param {Element} svgRoot - Imported <svg> element inside the clip
   * @param {Record<number, number>} stepStartTimesSec - Map of { [stepNumber]: absoluteStartSecInComposition }
   */
  function registerGsapTimeline(gsap, tl, svgRoot, stepStartTimesSec = {}) {
    const items = inspect(svgRoot);
    items.forEach(item => {
      const { el, step, anim } = item;
      const t0 = stepStartTimesSec[step] ?? 0;

      // Initial hidden state outside timeline (HyperFrames rule: frame 0 determinism)
      gsap.set(el, { autoAlpha: 0 });
      tl.set(el, { autoAlpha: 1 }, t0);

      if (anim === 'draw-stroke') {
        const paths = el.querySelectorAll('.anim-stroke, [pathLength="1"]');
        const endpoints = el.querySelectorAll('.anim-endpoint, .anim-arrow');
        gsap.set(paths, { strokeDasharray: 1, strokeDashoffset: 1 });
        gsap.set(endpoints, { autoAlpha: 0, scale: 0.68, y: 6, transformOrigin: '50% 50%' });
        paths.forEach((p, idx) => {
          tl.to(p, { strokeDashoffset: 0, duration: 0.46, ease: 'power3.out' }, t0 + idx * 0.065);
        });
        endpoints.forEach((ep, idx) => {
          tl.to(ep, { autoAlpha: 1, scale: 1, y: 0, duration: 0.28, ease: 'back.out(1.8)' }, t0 + 0.32 + idx * 0.075);
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
          tl.to(p, { strokeDashoffset: 0, duration: 0.42, ease: 'power2.out' }, t0 + 0.16 + idx * 0.05);
        });
        gsap.set(endpoints, { autoAlpha: 0, scale: 0.5, transformOrigin: '50% 50%' });
        endpoints.forEach((ep, idx) => {
          tl.to(ep, { autoAlpha: 1, scale: 1, duration: 0.26, ease: 'back.out(2)' }, t0 + 0.34 + idx * 0.055);
        });
      } else if (anim === 'polaroid-slap' || anim === 'z-stack-drop') {
        const units = el.querySelectorAll('.polaroid-unit');
        const targets = units.length > 0 ? Array.from(units) : [el];
        targets.forEach((unit, uIdx) => {
          const uTime = t0 + uIdx * 0.16;
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
      } else if (anim === 'meter-halt') {
        const fill = el.querySelector('.anim-fill');
        const wall = el.querySelector('.anim-wall');
        const badge = el.querySelector('.anim-badge');
        if (fill) {
          gsap.set(fill, { scaleX: 0, transformOrigin: '0% 50%' });
          tl.to(fill, { scaleX: 1, duration: 0.36, ease: 'power4.out' }, t0 + 0.06);
        }
        if (wall) {
          tl.to(wall, { x: 6, duration: 0.07, yoyo: true, repeat: 3, ease: 'power1.inOut' }, t0 + 0.26);
        }
        if (badge) {
          gsap.set(badge, { autoAlpha: 0, scale: 1.38, y: -6, transformOrigin: '50% 50%' });
          tl.to(badge, { autoAlpha: 1, scale: 1, y: 0, duration: 0.28, ease: 'back.out(2)' }, t0 + 0.36);
        }
      } else {
        const cards = el.querySelectorAll('.anim-card, .anim-stamp, .anim-body');
        const targets = cards.length > 0 ? Array.from(cards) : [el];
        gsap.set(targets, { autoAlpha: 0, y: 16, scale: 0.96, transformOrigin: '50% 50%' });
        targets.forEach((c, idx) => {
          tl.to(c, { autoAlpha: 1, y: 0, scale: 1, duration: 0.36, ease: 'back.out(1.4)' }, t0 + idx * 0.11);
        });
      }
    });
  }

  return {
    inspect,
    setStep,
    cancelAll,
    playPrimitive,
    registerGsapTimeline,
    setSpeedMultiplier,
    getSpeedMultiplier
  };
});
