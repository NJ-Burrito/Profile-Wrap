/* core/hand.js - Section 7: hand-animated feel. Part of core.js (split by section, pure move). */
import { TOKENS, gs, rng } from "./base.js";
import { WEIGHT, ease } from "./ease.js";

/* ================================================================== 7. HAND-ANIMATED FEEL
   anticipation, overshoot and settle, squash and stretch, arcs, offset timing, weight. */
export const hand = {
  /* Unique-frame scheduler: claim(t) returns t snapped to a frame that no earlier claim used, so nothing starts on the same frame. */
  claimer(fps = TOKENS.FPS) {
    const taken = new Set();
    const f = (t) => { let k = Math.round(t * fps); while (taken.has(k)) k++; taken.add(k); return k / fps; };
    f.taken = taken;
    return f;
  },
  /* n distinct start times spread over `spread` seconds from `at` (seeded jitter, frame-unique). */
  fan(n, { at = 0, spread = 0.4, seed = "fan", fps = TOKENS.FPS, claim = null } = {}) {
    const r = rng(seed), c = claim || hand.claimer(fps), out = [];
    for (let i = 0; i < n; i++) out.push(c(at + (n > 1 ? (i / (n - 1)) * spread : 0) + r.range(-0.4, 0.4) / fps));
    return out;
  },

  /* A hand-animated move: wind-up (anticipation), main move with a weight-based ease that overshoots, and settle.
     from/to are numeric GSAP props ({x,y,scale,rotation,opacity,...}). Returns { start, land, end }. */
  move(tl, el, { at = 0, from, to, weight = "mid", duration = null, anticipate = null, antiDur = null, ease: e = null, antiEase = "power2.out" } = {}) {
    const W = typeof weight === "string" ? WEIGHT[weight] : weight;
    const A = new Set(["x", "y", "z", "scale", "scaleX", "scaleY", "rotation", "rotationX", "rotationY", "xPercent", "yPercent"]);
    const keys = Object.keys(to), fa = anticipate ?? W.anti, dur = duration ?? W.dur, ad = antiDur ?? W.antiDur;
    let t = at;
    if (fa > 0 && keys.some((k) => A.has(k))) {
      const pre = {};
      keys.forEach((k) => { pre[k] = A.has(k) ? from[k] - (to[k] - from[k]) * fa : from[k]; });
      tl.fromTo(el, { ...from }, { ...pre, duration: ad, ease: antiEase, immediateRender: false }, t);
      t += ad;
      tl.fromTo(el, pre, { ...to, duration: dur, ease: e || W.ease, immediateRender: false }, t);
    } else tl.fromTo(el, { ...from }, { ...to, duration: dur, ease: e || W.ease, immediateRender: false }, t);
    return { start: at, land: t + dur * 0.4, end: t + dur };
  },

  /* Squash and stretch on an impact. The element must not have other scaleX/scaleY tweens. origin = transform origin
     (e.g. "50% 100%" to squash against the floor). Returns the time of the impact frame. */
  hit(tl, el, { at = 0, squash = 0.12, stretch = 0.07, origin = "50% 50%", base = { x: 1, y: 1 }, windup = 0.1, press = 0.07, rebound = 0.13, settle = 0.45 } = {}) {
    gs().set(el, { transformOrigin: origin });
    let t = at;
    const S = (sx, sy) => ({ scaleX: base.x * sx, scaleY: base.y * sy });
    tl.fromTo(el, S(1, 1), { ...S(1 - squash * 0.25, 1 + squash * 0.3), duration: windup, ease: "power2.out", immediateRender: false }, t); t += windup;
    tl.fromTo(el, S(1 - squash * 0.25, 1 + squash * 0.3), { ...S(1 + squash, 1 - squash), duration: press, ease: "power3.in", immediateRender: false }, t);
    const impact = t + press; t = impact;
    tl.fromTo(el, S(1 + squash, 1 - squash), { ...S(1 - stretch * 0.55, 1 + stretch), duration: rebound, ease: "power3.out", immediateRender: false }, t); t += rebound;
    tl.fromTo(el, S(1 - stretch * 0.55, 1 + stretch), { ...S(1, 1), duration: settle, ease: ease.spring, immediateRender: false }, t);
    return impact;
  },

  /* Travel on an arc (quadratic curve). from/to = [x, y]. lift = how far the path bows (fraction of distance), side = +1/-1.
     Eased progress along the curve, optional wind-up, and bank (lean in degrees, peaks mid-flight). Returns { start, end }. */
  arc(tl, el, { at = 0, duration = 0.7, from, to, lift = 0.22, side = 1, ease: e = ease.heavy, steps = 26, anticipate = 0.06, antiDur = 0.14, bank = 0, relative = false } = {}) {
    const [ax, ay] = from, [bx, by] = to, dx = bx - ax, dy = by - ay, len = Math.hypot(dx, dy) || 1;
    const cx = (ax + bx) / 2 + (-dy / len) * len * lift * side, cy = (ay + by) / 2 + (dx / len) * len * lift * side;
    const f = typeof e === "string" ? gs().parseEase(e) : e;
    let t = at;
    let sx = ax, sy = ay;
    if (anticipate > 0) {
      sx = ax - dx * anticipate; sy = ay - dy * anticipate;
      tl.fromTo(el, { x: ax, y: ay, rotation: 0 }, { x: sx, y: sy, duration: antiDur, ease: "power2.out", immediateRender: false }, t);
      t += antiDur;
    }
    const kf = [];
    for (let i = 1; i <= steps; i++) {
      const u = i / steps, s = f(u), m = 1 - s;
      kf.push({ x: m * m * ax + 2 * m * s * cx + s * s * bx, y: m * m * ay + 2 * m * s * cy + s * s * by, rotation: bank * Math.sin(Math.PI * u) * side, duration: duration / steps, ease: "none" });
    }
    tl.set(el, { x: sx, y: sy }, t);
    tl.to(el, { keyframes: kf }, t);
    return { start: at, end: t + duration };
  },

  /* A double-thump heartbeat on a property (tension). prop 'scale' multiplies, 'opacity'/other add. Ends exactly at base. */
  heartbeat(tl, el, { at = 0, duration = 1.2, bpm = 54, amp = 0.03, prop = "scale", base = 1, sub = 0.6 } = {}) {
    const T = 60 / bpm, n = Math.max(1, Math.floor(duration / T)), v = (a) => (prop === "scale" ? base * (1 + a) : base + a);
    for (let b = 0; b < n; b++) {
      const t0 = at + b * T;
      tl.fromTo(el, { [prop]: v(0) }, { [prop]: v(amp), duration: 0.09, ease: "power2.out", immediateRender: false }, t0);
      tl.fromTo(el, { [prop]: v(amp) }, { [prop]: v(0), duration: 0.13, ease: "power2.in", immediateRender: false }, t0 + 0.09);
      tl.fromTo(el, { [prop]: v(0) }, { [prop]: v(amp * sub), duration: 0.08, ease: "power2.out", immediateRender: false }, t0 + 0.26);
      tl.fromTo(el, { [prop]: v(amp * sub) }, { [prop]: v(0), duration: 0.2, ease: "sine.inOut", immediateRender: false }, t0 + 0.34);
    }
    return n * T;
  },

  /* Seeded tremble: tiny x/y/rotation jitter at ~12 fps with a decay, returning to 0. Put it on a wrapper. */
  tremble(tl, el, { at = 0, duration = 1, amp = 1.2, rot = 0.4, seed = "tr", fps = 12, decay = 0 } = {}) {
    const r = rng(seed), n = Math.max(2, Math.round(duration * fps));
    for (let i = 0; i < n; i++) {
      const k = 1 - decay * (i / n), last = i === n - 1;
      tl.to(el, { x: last ? 0 : r.range(-amp, amp) * k, y: last ? 0 : r.range(-amp, amp) * k, rotation: last ? 0 : r.range(-rot, rot) * k, duration: 1 / fps, ease: "none" }, at + i / fps);
    }
  },
};
