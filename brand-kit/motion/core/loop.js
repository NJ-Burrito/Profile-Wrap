/* core/loop.js - Sections 15-16: follow-through / overlap and loop stitch. Part of core.js (split by section, pure move). */
import { TOKENS, arr, gs } from "./base.js";
import { WEIGHT, ease } from "./ease.js";

/* ================================================================== 15. FOLLOW-THROUGH / OVERLAP (Disney) */
export const overlap = {
  follow(tl, targets, { at = 0, from, to, duration = 0.6, lag = 0.07, ease: e = "back.out", overshoot = 1.2, grow = 0.35, durGrow = 0.08 } = {}) {
    arr(targets).forEach((el, i) => {
      const ez = e === "back.out" ? `back.out(${(overshoot * (1 + grow * i)).toFixed(2)})` : e;
      tl.fromTo(el, { ...from }, { ...to, duration: duration * (1 + durGrow * i), ease: ez, immediateRender: false }, at + i * lag);
    });
  },
  chain(tl, steps, { at = 0, lag = 0.08 } = {}) {
    steps.forEach((s, i) => tl.fromTo(s.el, { ...s.from }, { ...s.to, duration: s.duration ?? 0.5, ease: s.ease || "power3.out", immediateRender: false }, at + i * lag));
  },
  anticipate(tl, el, { at = 0, from, to, duration = 0.14, ease: e = "power2.out" } = {}) {
    tl.fromTo(el, { ...from }, { ...to, duration, ease: e, immediateRender: false }, at);
    return at + duration;
  },
  /* Staggered entrance with overshoot; `weights` (optional list of "light"|"mid"|"heavy") varies each item's ease and duration. */
  reveal(tl, targets, { at = 0, from = { opacity: 0, y: 30 }, to = { opacity: 1, y: 0 }, lag = 0.06, duration = 0.5, ease: e = ease.overshootSoft, weights = null, claim = null } = {}) {
    arr(targets).forEach((el, i) => {
      const W = weights ? WEIGHT[weights[i % weights.length]] : null;
      const t = claim ? claim(at + i * lag) : at + i * lag;
      tl.fromTo(el, { ...from }, { ...to, duration: W ? W.dur * (duration / 0.6) : duration, ease: W ? W.ease : e, immediateRender: false }, t);
    });
  },
};

/* ================================================================== 16. LOOP STITCH (frame N equals frame 0) */
export const loop = {
  snapshot(targets, props = ["x", "y", "scale", "rotation", "opacity"]) {
    return arr(targets).map((el) => ({ el, vals: Object.fromEntries(props.map((p) => [p, gs().getProperty(el, p)])) }));
  },
  close(tl, snap, { at = 0, duration = 0.5, ease: e = "sine.inOut" } = {}) {
    snap.forEach((s) => tl.to(s.el, { ...s.vals, duration, ease: e }, at));
  },
  verify(tl, snap, { duration = tl.duration(), tol = 0.5 } = {}) {
    const bad = [];
    tl.seek(duration);
    snap.forEach((s) => { for (const k in s.vals) { const v = gs().getProperty(s.el, k); if (typeof v === "number" ? Math.abs(v - s.vals[k]) > tol * (k === "opacity" || k === "scale" ? 0.01 : 1) : v !== s.vals[k]) bad.push({ el: s.el.id || s.el.className, prop: k, want: s.vals[k], got: v }); } });
    tl.seek(0);
    return bad;
  },
  register(id, tl, duration) {
    tl.set({}, {}, duration);
    (globalThis.__timelines = globalThis.__timelines || {})[id] = tl;
    tl.seek(0);
  },
  /* Dev audit: how many choreographed tweens START on each frame (ignores ambient tracks, sets, typewriter units,
     sparks and pulse dots). Returns the worst frames; aim for a small number everywhere. */
  startAudit(tl, { fps = TOKENS.FPS, maxDur = 2.5, top = 5, skip = /mo-u|mo-caret|mo-spark|mo-pulse|mo-mote/ } = {}) {
    const by = new Map();
    tl.getChildren(false, true, false).forEach((c) => {
      const d = c.duration();
      if (d <= 0.001 || d > maxDur) return;
      const tg = c.targets ? c.targets() : [];
      if (tg.length && tg.every((e) => e && e.getAttribute && skip.test(String(e.getAttribute("class") || "")))) return;
      const f = Math.round(c.startTime() * fps);
      by.set(f, (by.get(f) || 0) + 1);
    });
    return [...by.entries()].sort((a, b) => b[1] - a[1]).slice(0, top).map(([f, n]) => ({ frame: f, t: +(f / fps).toFixed(2), starts: n }));
  },
};
