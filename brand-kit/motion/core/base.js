/* core/base.js - Shared constants and low-level helpers (rng, hash, periodic, sample, track, mk). Part of core.js (split by section, pure move). */


export const TAU = Math.PI * 2;
export const gs = () => globalThis.gsap;
export const arr = (t) => gs().utils.toArray(t);
export const NS = "http://www.w3.org/2000/svg";
export const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
export const allow = (el) => ["overlap", "occlusion", "overflow"].forEach((a) => el.setAttribute("data-layout-allow-" + a, "true"));

/* Layout constants only: NO colours here (a palette comes from color.script). */
export const TOKENS = { W: 1080, H: 1350, FPS: 25 };

/* ------------------------------------------------------------------ seeded randomness */
export function hash(s) {
  let h = 2166136261 >>> 0;
  for (const c of String(s)) { h ^= c.codePointAt(0); h = Math.imul(h, 16777619) >>> 0; }
  return h >>> 0;
}

export function rng(seed = 1) {
  let s = (typeof seed === "number" ? seed >>> 0 : hash(seed)) || 1;
  const next = () => {
    s = (s + 0x6d2b79f5) >>> 0;
    let t = s;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  const api = {
    next,
    range: (a, b) => a + (b - a) * next(),
    int: (a, b) => Math.floor(a + (b - a + 1) * next()),
    pick: (list) => list[Math.floor(next() * list.length)],
    shuffle: (list) => { const l = list.slice(); for (let i = l.length - 1; i > 0; i--) { const j = Math.floor(next() * (i + 1)); [l[i], l[j]] = [l[j], l[i]]; } return l; },
  };
  return api;
}

/* A smooth periodic function f(u), u in [0,1], with f(0) = f(1) = 0 and values in [-amp, amp].
   Built from sine terms with WHOLE cycles, so anything driven by it loops exactly. */
export function periodic(seed, { terms = 3, minCycles = 1, maxCycles = 3, amp = 1 } = {}) {
  const r = rng(seed);
  const T = [];
  let norm = 0;
  for (let i = 0; i < terms; i++) {
    const a = r.range(0.5, 1) / (i + 1);
    T.push({ c: r.int(minCycles, maxCycles), ph: r.range(0, TAU), a });
    norm += a;
  }
  return (u) => amp * T.reduce((s, t) => s + t.a * (Math.sin(TAU * t.c * u + t.ph) - Math.sin(t.ph)), 0) / norm;
}

/* multiply a periodic fn by a story envelope env(absTime); env is optional */
const withEnv = (f, env, at, duration) => (env ? (u) => f(u) * env(at + u * duration) : f);

/* Sample fns(t)-style props into keyframes: one tween per target, seek-safe. fns[k](u) for u in 0..1. */
function track(tl, targets, { at = 0, duration, fns, step = 0.1, init = {} }) {
  const n = Math.max(2, Math.round(duration / step));
  const dt = duration / n;
  arr(targets).forEach((el, idx) => {
    const f = typeof fns === "function" ? fns(idx) : fns;
    const at0 = {}; for (const k in f) at0[k] = f[k](0);
    tl.set(el, { ...init, ...at0 }, at);
    const kf = [];
    for (let i = 1; i <= n; i++) {
      const o = { duration: dt, ease: "none" };
      for (const k in f) o[k] = f[k](i / n);
      kf.push(o);
    }
    tl.to(el, { keyframes: kf }, at);
  });
}

/* Free-form sampler: fn(absTime) returns a props object. One tween per target. */
export function sample(tl, targets, { at = 0, duration, step = 0.08, fn }) {
  const n = Math.max(2, Math.round(duration / step)), dt = duration / n;
  arr(targets).forEach((el, idx) => {
    tl.set(el, fn(at, idx), at);
    const kf = [];
    for (let i = 1; i <= n; i++) kf.push({ ...fn(at + i * dt, idx), duration: dt, ease: "none" });
    tl.to(el, { keyframes: kf }, at);
  });
}

/* Linear travel with wrap-around: prop runs a -> b once per `duration`, starting at `phase` (0..1). */
function wrapTravel(tl, el, prop, a, b, { at = 0, duration, phase = 0, laps = 1 }) {
  const lapD = duration / laps;
  for (let l = 0; l < laps; l++) {
    const t0 = at + l * lapD, p = phase % 1, p0 = a + (b - a) * p;
    const d1 = lapD * (1 - p), d2 = lapD * p;
    tl.set(el, { [prop]: p0 }, t0);
    if (d1 > 1e-6) tl.to(el, { [prop]: b, duration: d1, ease: "none" }, t0);
    if (d2 > 1e-6) { tl.set(el, { [prop]: a }, t0 + d1); tl.to(el, { [prop]: p0, duration: d2, ease: "none" }, t0 + d1); }
  }
}

export function mk(tag, cls, css, parent) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (css) Object.assign(e.style, css);
  if (parent) parent.appendChild(e);
  return e;
}
