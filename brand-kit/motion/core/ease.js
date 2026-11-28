/* core/ease.js - Section 2: named eases, bezier, spring, weights. Part of core.js (split by section, pure move). */
import { TAU, gs } from "./base.js";

/* ================================================================== 2. EASES (named presets, hand-made feel)
   Plain functions of progress (GSAP accepts a function as an ease). Also registered as "mo.<name>" strings. */
export function bezier(x1, y1, x2, y2) {
  const cx = 3 * x1, bx = 3 * (x2 - x1) - cx, ax = 1 - cx - bx;
  const cy = 3 * y1, by = 3 * (y2 - y1) - cy, ay = 1 - cy - by;
  const X = (t) => ((ax * t + bx) * t + cx) * t, Y = (t) => ((ay * t + by) * t + cy) * t, dX = (t) => (3 * ax * t + 2 * bx) * t + cx;
  return (x) => {
    if (x <= 0) return 0;
    if (x >= 1) return 1;
    let t = x;
    for (let i = 0; i < 8; i++) { const e = X(t) - x; if (Math.abs(e) < 1e-6) return Y(t); const d = dX(t); if (Math.abs(d) < 1e-6) break; t -= e / d; }
    let lo = 0, hi = 1; t = x;
    for (let i = 0; i < 30; i++) { const e = X(t) - x; if (Math.abs(e) < 1e-6) break; if (e > 0) hi = t; else lo = t; t = (lo + hi) / 2; }
    return Y(t);
  };
}
/* Damped spring that ends exactly at 1. freq = oscillations in the move, damp = decay (higher settles sooner). */
export function spring(freq = 2.6, damp = 5.5) {
  const y = (t) => 1 - Math.exp(-damp * t) * Math.cos(TAU * freq * t);
  const e1 = 1 - y(1);
  return (t) => (t <= 0 ? 0 : t >= 1 ? 1 : y(t) + e1 * t * t * t);
}
export const ease = {
  bezier, spring,
  snap: bezier(0.16, 1, 0.3, 1),             // light things: fast out, quick settle (UI chips, sparks)
  pop: bezier(0.2, 1.5, 0.4, 1),             // light thing that lands with a small bounce
  overshoot: bezier(0.34, 1.56, 0.64, 1),    // ~12 % past the target then back
  overshootSoft: bezier(0.3, 1.22, 0.5, 1),  // ~5 % past
  heavy: bezier(0.62, 0.02, 0.18, 1),        // slow start, long gentle settle (cards, camera dolly)
  heavyDrop: bezier(0.55, 0, 0.2, 1.1),      // heavy with a tiny settle
  anticipate: bezier(0.55, -0.55, 0.35, 1),  // dips backwards first (the wind-up inside one tween)
  spring: spring(2.4, 5.5),                  // bouncy settle, 2 visible wobbles
  settle: spring(1.5, 6.5),                  // one small wobble
  creep: bezier(0.25, 0.45, 0.4, 1),         // tension: moves, but reluctantly
  inSlow: bezier(0.8, 0, 0.9, 0.6),          // accelerates late (a thing finally letting go)
  inOut: bezier(0.65, 0, 0.35, 1),
  soft: bezier(0.37, 0, 0.63, 1),
};
/* Weight table: heavy things ease slowly and wind up longer; light things snap. weight in {light, mid, heavy}. */
export const WEIGHT = {
  light: { ease: ease.pop, dur: 0.38, anti: 0.07, antiDur: 0.09 },
  mid: { ease: ease.overshoot, dur: 0.6, anti: 0.09, antiDur: 0.14 },
  heavy: { ease: ease.heavyDrop, dur: 0.95, anti: 0.12, antiDur: 0.24 },
};
export function registerEases() {
  if (!gs() || !gs().registerEase) return;
  Object.entries(ease).forEach(([k, f]) => { if (typeof f === "function" && f.length === 1) { try { gs().registerEase("mo." + k, f); } catch (e) { /* already registered */ } } });
}

/* Legacy GSAP-string eases (colour-free), kept for convenience */
export const EASE = {
  out: "power3.out", in: "power2.in", inOut: "power2.inOut", soft: "sine.inOut",
  snap: ease.snap, pop: ease.pop, settle: ease.settle, overshoot: ease.overshoot, heavy: ease.heavy, linear: "none",
};
