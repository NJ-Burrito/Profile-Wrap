/* core.js - Profile-Wrap motion library, Standard v4 (HyperFrames + GSAP). MIT.
   One ES module. Every helper adds tweens to a GIVEN paused timeline: helper(tl, targets, opts).
   Rules baked in (see docs/MOTION.md): deterministic (seeded rng, no Math.random / Date / performance.now),
   seek-safe (explicit fromTo states, no onUpdate side effects, no tween-time DOM measuring),
   loop-exact (periodic motion uses whole cycles; one-shots return to their rest state).
   NO DEFAULT PALETTE: every post defines its own colour script (color.script) and the library reads it.
   Needs the global `gsap` (load it with a classic <script> before importing this module).
   The identity card lives in identity.js; camera, depth and ambient (deprecated for posts) live in motion.legacy.js.

   Sections: 1 colour script . 2 eases . 6 light . 7 hand-animated feel . 8 story arc . 9 micro-onsets . 10 connector pulse .
             11 typewriter . 12 focus pull . 13 state colour . 14 counter . 15 follow-through . 16 loop stitch . 17 objects .
             19 v4: grid . type . cut . split . poster ; story.presets ; counter (whole values, never scrambled digits) */
import { SVG as OBJ_SVG } from "./objects.data.js";

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

function mk(tag, cls, css, parent) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (css) Object.assign(e.style, css);
  if (parent) parent.appendChild(e);
  return e;
}

/* ================================================================== 1. COLOUR SCRIPT
   No brand palette. A post defines roles: base, ambient, hero, accent, payoff (+ any extra named roles).
   color.script() derives readable ink/muted (WCAG), writes --c-<role> CSS variables, and checks contrast.
   Per-beat colour shifts (grade at tension, burst at payoff) are tweens on overlay elements, so they are cheap. */
export function hex2rgb(h) {
  h = String(h).replace("#", "");
  if (h.length === 3) h = [...h].map((c) => c + c).join("");
  const n = parseInt(h, 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}
export const rgb2hex = (r, g, b) => "#" + [r, g, b].map((v) => clamp(Math.round(v), 0, 255).toString(16).padStart(2, "0")).join("");
export function relLum(hex) {
  const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
  const [r, g, b] = hex2rgb(hex);
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
}
export function contrast(a, b) {
  const la = relLum(a), lb = relLum(b);
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}
export function mix(a, b, t) {
  const A = hex2rgb(a), B = hex2rgb(b);
  return rgb2hex(A[0] + (B[0] - A[0]) * t, A[1] + (B[1] - A[1]) * t, A[2] + (B[2] - A[2]) * t);
}
/* Nudge fg toward white (dark bg) or black (light bg) until it reaches `min` contrast on bg. */
export function ensure(fg, bg, min = 4.5) {
  if (contrast(fg, bg) >= min) return fg;
  const target = relLum(bg) < 0.4 ? "#ffffff" : "#000000";
  for (let t = 0.04; t <= 1.0001; t += 0.04) { const c = mix(fg, target, t); if (contrast(c, bg) >= min) return c; }
  return target;
}
/* Best of ink / near-black / white for text laid on a coloured surface. */
export function onColor(bg) {
  return ["#0a0a0c", "#ffffff"].map((x) => [x, contrast(x, bg)]).sort((p, q) => q[1] - p[1])[0][0];
}

const NEUTRAL = { base: "#101010", ambient: "#505050", hero: "#ffffff", accent: "#c8c8c8", payoff: "#ffffff", ink: "#f2f2f2", muted: "#b4b4b4" };
let CURRENT = null;

export const color = {
  hex2rgb, rgb2hex, relLum, contrast, mix, ensure, onColor,

  /* roles: { base, ambient, hero, accent, payoff, ...extras }. Returns the palette object P:
     P.<role> hex, P.rgb(role, alpha), P.apply(el) sets --c-<role>, P.report (contrast table), P.failures. */
  script(roles, { minText = 4.5, minGraphic = 3 } = {}) {
    for (const k of ["base", "ambient", "hero", "accent", "payoff"]) if (!roles[k]) throw new Error(`colour script needs the role "${k}"`);
    const dark = relLum(roles.base) < 0.4;
    const ink = ensure(roles.ink || (dark ? "#f4f4f0" : "#16130f"), roles.base, 7);
    const muted = ensure(roles.muted || mix(ink, roles.base, 0.38), roles.base, minText);
    const P = { ...roles, ink, muted, dark };
    const R = Object.keys(P).filter((k) => typeof P[k] === "string" && P[k][0] === "#");
    const report = [];
    const add = (name, a, b, min) => { const r = contrast(a, b); report.push({ pair: name, ratio: +r.toFixed(2), min, ok: r >= min }); };
    add("ink on base", ink, roles.base, 7);
    add("muted on base", muted, roles.base, minText);
    add("hero on base (graphics)", roles.hero, roles.base, minGraphic);
    add("accent on base (graphics)", roles.accent, roles.base, minGraphic);
    (roles.pairs || []).forEach(([name, fg, bg, min]) => add(name, P[fg] || fg, P[bg] || bg, min ?? minText));
    P.report = report;
    P.failures = report.filter((r) => !r.ok);
    P.roles = R;
    P.rgb = (role, a = 1) => { const [r, g, b] = hex2rgb(P[role] || role); return `rgba(${r},${g},${b},${a})`; };
    P.apply = (el) => { R.forEach((k) => el.style.setProperty("--c-" + k, P[k])); };
    return P;
  },
  use(P) { CURRENT = P; return P; },
  current() { return CURRENT || NEUTRAL; },
  rgb(role, a = 1) {
    const c = CURRENT ? CURRENT[role] || role : NEUTRAL[role] || role;
    const [r, g, b] = hex2rgb(c); return `rgba(${r},${g},${b},${a})`;
  },
  pick(role) { return (CURRENT || NEUTRAL)[role] || role; },

  /* glow strings share one structure so box-shadow tweens interpolate */
  glowOff(role) { return `0 0 0 0px ${color.rgb(role, 0)}, 0 0 0px ${color.rgb(role, 0)}`; },
  glowOn(role, a = 0.45, ring = 3, blur = 28) { return `0 0 0 ${ring}px ${color.rgb(role, a * 0.6)}, 0 0 ${blur}px ${color.rgb(role, a)}`; },

  /* idle / active / done / error from palette roles; every state still needs a second cue (badge, icon, text) */
  states(P = CURRENT || NEUTRAL, { idle = "muted", active = "hero", done = "payoff", error = "accent" } = {}) {
    const S = (role, glow) => ({ borderColor: color.rgb(role, role === idle ? 0.4 : 1), color: P[role] || role, boxShadow: glow });
    const old = CURRENT; CURRENT = P;
    const out = {
      idle: S(idle, color.glowOff(active)),
      active: S(active, color.glowOn(active, 0.5)),
      done: S(done, color.glowOn(done, 0.45)),
      error: S(error, color.glowOn(error, 0.45)),
    };
    CURRENT = old;
    return out;
  },

  /* Grade layers: a base-colour plate behind the world, a tint and a vignette over it. Returns a controller.
       const G = color.grade(stage, P);   G.to(tl, { at, duration, base, tint, tintAlpha, vignette });
     Tension: cool/darken the base, close the vignette. Payoff: G.to back to rest (or brighter). Release: G.rest(). */
  grade(stage, P = CURRENT || NEUTRAL, { vignetteColor = null } = {}) {
    stage = arr(stage)[0];
    const plate = mk("div", "mo-plate", { background: P.base }, null);
    stage.insertBefore(plate, stage.firstChild);
    const tint = mk("div", "mo-tint", { background: P.base, opacity: "0" }, stage);
    const vig = mk("div", "mo-vig", { background: `radial-gradient(ellipse at 50% 46%, rgba(0,0,0,0) 38%, ${color.rgb(vignetteColor || P.base, 0.8)} 100%)`, opacity: "0" }, stage);
    [plate, tint, vig].forEach(allow);
    const rest = { base: P.base, tint: P.base, tintAlpha: 0, vignette: 0 };
    let cur = { ...rest };
    const rgbS = (h) => { const [r, g, b] = hex2rgb(h); return `rgb(${r},${g},${b})`; };
    gs().set(plate, { backgroundColor: rgbS(P.base) });
    gs().set(tint, { backgroundColor: rgbS(P.base), opacity: 0 });
    gs().set(vig, { opacity: 0 });
    const G = {
      plate, tint, vig,
      to(tl, { at = 0, duration = 0.6, base = cur.base, tint: tc = cur.tint, tintAlpha = cur.tintAlpha, vignette = cur.vignette, ease = "sine.inOut" } = {}) {
        tl.fromTo(plate, { backgroundColor: rgbS(cur.base) }, { backgroundColor: rgbS(base), duration, ease, immediateRender: false }, at);
        tl.fromTo(tint, { backgroundColor: rgbS(cur.tint), opacity: cur.tintAlpha }, { backgroundColor: rgbS(tc), opacity: tintAlpha, duration, ease, immediateRender: false }, at);
        tl.fromTo(vig, { opacity: cur.vignette }, { opacity: vignette, duration, ease, immediateRender: false }, at);
        cur = { base, tint: tc, tintAlpha, vignette };
      },
      rest(tl, o = {}) { G.to(tl, { ...rest, ...o }); },
      get state() { return { ...cur }; },
    };
    return G;
  },

  /* Radial colour burst for a payoff accent hit. Creates its own element in `container`. */
  burst(tl, container, { at = 0, x = 540, y = 675, r = 520, role = "payoff", peak = 0.5, dur = 0.55, z = 0, spread = 1.25 } = {}) {
    container = arr(container)[0];
    const c = mk("div", "mo-burst", { left: x - r + "px", top: y - r + "px", width: 2 * r + "px", height: 2 * r + "px",
      background: `radial-gradient(closest-side, ${color.rgb(role, 1)}, ${color.rgb(role, 0.35)} 45%, ${color.rgb(role, 0)} 100%)` }, container);
    allow(c);
    gs().set(c, { opacity: 0, scale: 0.15, z });
    tl.fromTo(c, { opacity: 0, scale: 0.15 }, { opacity: peak, scale: spread * 0.5, duration: dur * 0.2, ease: "power2.out", immediateRender: false }, at);
    tl.fromTo(c, { opacity: peak, scale: spread * 0.5 }, { opacity: 0, scale: spread, duration: dur * 0.8, ease: "power2.out", immediateRender: false }, at + dur * 0.2);
    return c;
  },
};

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
function registerEases() {
  if (!gs() || !gs().registerEase) return;
  Object.entries(ease).forEach(([k, f]) => { if (typeof f === "function" && f.length === 1) { try { gs().registerEase("mo." + k, f); } catch (e) { /* already registered */ } } });
}

/* Legacy GSAP-string eases (colour-free), kept for convenience */
export const EASE = {
  out: "power3.out", in: "power2.in", inOut: "power2.inOut", soft: "sine.inOut",
  snap: ease.snap, pop: ease.pop, settle: ease.settle, overshoot: ease.overshoot, heavy: ease.heavy, linear: "none",
};

/* ================================================================== 6. LIGHT (a source the scene responds to)
   One light path drives: cast shadows (layered, move opposite the light), rim glow on an edge, specular sheen across a surface. */
export const light = {
  /* keys = [{ t, x, y, i }] with x,y in -1..1 (light direction, +x = from the right) and i = intensity 0..1.4.
     Cosine-interpolated; make first and last key equal for a loop. Returns f(absTime) -> {x,y,i}. */
  path(keys) {
    const K = keys.slice().sort((a, b) => a.t - b.t);
    return (t) => {
      if (t <= K[0].t) return { x: K[0].x, y: K[0].y, i: K[0].i ?? 1 };
      for (let j = 1; j < K.length; j++) {
        if (t <= K[j].t) {
          const a = K[j - 1], b = K[j], u = (t - a.t) / (b.t - a.t || 1), w = (1 - Math.cos(Math.PI * clamp(u, 0, 1))) / 2;
          return { x: a.x + (b.x - a.x) * w, y: a.y + (b.y - a.y) * w, i: (a.i ?? 1) + ((b.i ?? 1) - (a.i ?? 1)) * w };
        }
      }
      const L = K[K.length - 1]; return { x: L.x, y: L.y, i: L.i ?? 1 };
    };
  },

  /* Layered cast shadows. shadows = [{ el, depth (0..1, how high the object floats), reach (px), alpha }].
     Each shadow element is a pre-blurred shape (box-shadow or gradient); we only move it with transforms. */
  cast(tl, shadows, { path, at = 0, duration, step = 0.08, baseY = 18 } = {}) {
    shadows.forEach((S) => {
      sample(tl, S.el, {
        at, duration, step,
        fn: (t) => {
          const L = path(t), d = S.depth ?? 1, reach = S.reach ?? 36;
          return { x: -L.x * reach * d, y: baseY * d - L.y * reach * d * 0.6, opacity: (S.alpha ?? 0.5) * (0.55 + 0.45 * Math.min(1.2, L.i)) * (0.85 + 0.15 * d), scale: 1 + 0.04 * d };
        },
      });
    });
  },

  /* Rim glow: a gradient stroke around a rounded rect whose bright spot follows the light.
     rect = { x, y, w, h, r }, mounted in `container` (absolute, stage coords). Returns the svg. */
  rim(tl, container, { path, rect, role = "hero", width = 3, at = 0, duration, step = 0.08, spread = 0.5, strength = 0.9, z = 4 } = {}) {
    container = arr(container)[0];
    const id = "mo-rim-" + hash(JSON.stringify(rect) + role);
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("class", "mo-rim");
    svg.setAttribute("viewBox", `0 0 ${TOKENS.W} ${TOKENS.H}`);
    svg.style.cssText = `position:absolute;left:0;top:0;width:${TOKENS.W}px;height:${TOKENS.H}px;overflow:visible;pointer-events:none`;
    svg.innerHTML = `<defs><linearGradient id="${id}" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" style="stop-color:var(--c-${role}, #fff)" stop-opacity="0"/><stop offset=".5" style="stop-color:var(--c-${role}, #fff)" stop-opacity="1"/><stop offset="1" style="stop-color:var(--c-${role}, #fff)" stop-opacity="0"/></linearGradient></defs>
      <rect x="${rect.x}" y="${rect.y}" width="${rect.w}" height="${rect.h}" rx="${rect.r || 0}" fill="none" stroke="url(#${id})" stroke-width="${width}"/>`;
    container.appendChild(svg); allow(svg);
    const g = svg.querySelector("linearGradient");
    gs().set(svg, { z });
    const at0 = (t) => {
      const L = path(t), cx = rect.x + (L.x * 0.5 + 0.5) * rect.w, cy = rect.y + (L.y * 0.5 + 0.5) * rect.h, s = spread * Math.max(rect.w, rect.h);
      return { x1: cx - s, y1: cy - s * 0.6, x2: cx + s, y2: cy + s * 0.6, i: L.i };
    };
    const n = Math.max(2, Math.round(duration / step)), dt = duration / n;
    const p0 = at0(at);
    gs().set(g, { attr: { x1: p0.x1, y1: p0.y1, x2: p0.x2, y2: p0.y2 } });
    gs().set(svg, { opacity: strength * Math.min(1, p0.i) });
    for (let i = 1; i <= n; i++) {
      const a = at0(at + (i - 1) * dt), b = at0(at + i * dt);
      tl.fromTo(g, { attr: { x1: a.x1, y1: a.y1, x2: a.x2, y2: a.y2 } }, { attr: { x1: b.x1, y1: b.y1, x2: b.x2, y2: b.y2 }, duration: dt, ease: "none", immediateRender: false }, at + (i - 1) * dt);
      tl.fromTo(svg, { opacity: strength * Math.min(1, a.i) }, { opacity: strength * Math.min(1, b.i), duration: dt, ease: "none", immediateRender: false }, at + (i - 1) * dt);
    }
    return svg;
  },

  /* Specular sheen: a soft diagonal band that crosses a surface at given moments. Clipped to the surface, so it
     stays a leaf. passes = [{ at, duration, opacity, ease }]. host: element with the surface's size/radius. */
  sheen(tl, host, { passes = [], radius = 24, skew = -16, band = 0.34, width = 960, role = "payoff", z = 0 } = {}) {
    host = arr(host)[0];
    const wrap = mk("div", "mo-sheenwrap", { borderRadius: radius + "px" }, host);
    allow(wrap);
    const bar = mk("div", "mo-sheen", { width: width * band + "px", background: `linear-gradient(90deg, transparent, var(--c-${role}, #fff), transparent)` }, wrap);
    gs().set(bar, { x: -width * band * 1.5, skewX: skew, opacity: 0 });
    if (z) gs().set(wrap, { z });
    passes.forEach((p) => {
      tl.fromTo(bar, { x: -width * band * 1.5, opacity: 0 }, { x: width * 1.15, duration: p.duration ?? 0.9, ease: p.ease || ease.soft, immediateRender: false }, p.at);
      tl.fromTo(bar, { opacity: 0 }, { opacity: p.opacity ?? 0.22, duration: (p.duration ?? 0.9) * 0.3, ease: "power1.out", immediateRender: false }, p.at);
      tl.fromTo(bar, { opacity: p.opacity ?? 0.22 }, { opacity: 0, duration: (p.duration ?? 0.9) * 0.3, ease: "power1.in", immediateRender: false }, p.at + (p.duration ?? 0.9) * 0.7);
    });
    return bar;
  },
};

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

/* ================================================================== 8. STORY ARC (hook, build, tension, payoff, release)
   A plan fixes the phase times and gives the helpers a rhythm: fast build, slow tension, fast payoff, slow release.
   plan.calm(t) lowers secondary activity during tension ON PURPOSE; plan.pace(t) is the onset interval per phase. */
export const story = {
  /* v4: mode "stop" makes the tension a DEAD STOP (nothing moves for buildEnd..tensionEnd, at most 0.8 s) instead of a dim:
     calm() stays 1, the stop is a logged hold (plan.holds -> shot-plan.json) and the tension-length check becomes the hold check. */
  plan({ duration = 8, fps = TOKENS.FPS, hookEnd = 0.8, buildEnd = 3.6, tensionEnd = 5.0, hit = 5.2, payoffEnd = 5.9,
    floor = 0.1, ramp = 0.4, pace = {}, mode = "dim" } = {}) {
    const P = { hook: [0, hookEnd], build: [hookEnd, buildEnd], tension: [buildEnd, tensionEnd], payoff: [tensionEnd, payoffEnd], release: [payoffEnd, duration] };
    const paces = { hook: 0.2, build: 0.26, tension: Infinity, payoff: 0.17, release: 0.5, ...pace };
    const phaseAt = (t) => Object.keys(P).find((k) => t >= P[k][0] && t < P[k][1]) || "release";
    const stop = mode === "stop";
    const calm = (t) => {
      if (stop) return 1;
      const a = buildEnd - ramp, b = buildEnd, c = hit - 0.05, d = hit + 0.2;
      let w = 0;
      if (t >= a && t < b) w = (t - a) / (b - a);
      else if (t >= b && t < c) w = 1;
      else if (t >= c && t < d) w = 1 - (t - c) / (d - c);
      const s = w * w * (3 - 2 * w);
      return 1 - (1 - floor) * s;
    };
    const plan = {
      duration, fps, hit, phases: P, paces, floor, mode,
      phaseAt, calm,
      pace: (t) => paces[phaseAt(t)],
      quiet: [[buildEnd, stop ? tensionEnd : hit - 0.05]],
      /* logged holds for shot-plan.json: [{ at, end, why }]; the still-frame gate allows these and nothing else */
      holds: stop ? [{ at: buildEnd, end: tensionEnd, why: "dead stop before the hit" }] : [],
      label(tl) { Object.keys(P).forEach((k) => tl.addLabel(k, P[k][0])); tl.addLabel("hit", hit); },
      /* events per second per phase, from the paces */
      tempo() { const o = {}; Object.keys(P).forEach((k) => { o[k] = isFinite(paces[k]) ? +(1 / paces[k]).toFixed(2) : 0; }); return o; },
      /* sanity checks the arc grammar. Returns a list of problems (empty = ok). */
      check() {
        const bad = [], T = plan.tempo();
        if (P.hook[1] - P.hook[0] > 1.2) bad.push("hook longer than 1.2 s");
        const tlen = P.tension[1] - P.tension[0];
        if (stop) {
          if (tlen < 0.3 || tlen > 0.8) bad.push("dead stop must be 0.3-0.8 s (is " + tlen.toFixed(2) + " s)");
          if (hit - P.tension[1] > 0.6) bad.push("hit more than 0.6 s after the dead stop: the silence will not lead into it");
        } else if (tlen < 0.8) bad.push("tension shorter than 0.8 s: the held breath will not read");
        if (!(T.tension < T.build * 0.5)) bad.push("tension must be less than half as busy as the build");
        if (!(T.payoff >= T.build * 0.9)) bad.push("payoff should be at least as fast as the build");
        if (hit < P.payoff[0] || hit > P.payoff[1]) bad.push("hit is outside the payoff phase");
        if (duration - payoffEnd < 0.9) bad.push("release shorter than 0.9 s: the loop will not breathe");
        if (hit > duration - 0.5) bad.push("payoff within 0.5 s of the seam");
        return bad;
      },
    };
    return plan;
  },
};

/* ARC PRESETS (Standard v4). A post picks ONE; two neighbours in the queue never share a preset. Times are for a 10 s loop and
   scale with `duration`. identity.where (see identity.js) says where the card beat and the signature go: "hook" (rides the first big word),
   "release" (after the payoff), "signoff" (the last thing before the seam). Override any field: M.story.preset("no-dim", { hit: 4.08 }). */
story.presets = {
  "early-hit": { hookEnd: 0.8, buildEnd: 2.6, tensionEnd: 3.5, hit: 3.9, payoffEnd: 5.0, mode: "dim", identity: "hook",
    note: "hit at about 3.9 s; dim tension 0.9 s; the rest of the loop is payoff and a long release" },
  "mid-hit": { hookEnd: 0.8, buildEnd: 3.6, tensionEnd: 5.0, hit: 5.2, payoffEnd: 6.2, mode: "dim", identity: "release",
    note: "the v3 shape: hit at about 5.2 s after a 1.4 s dim" },
  "late-hit": { hookEnd: 1.0, buildEnd: 4.8, tensionEnd: 6.4, hit: 6.6, payoffEnd: 7.4, mode: "dim", identity: "signoff",
    note: "a long build, the hit at about 6.6 s, a short release" },
  "no-dim": { hookEnd: 1.2, buildEnd: 3.4, tensionEnd: 3.9, hit: 4.1, payoffEnd: 5.4, mode: "stop", identity: "signoff",
    note: "no grade shift, no vignette: the tension is a logged DEAD STOP (0.3-0.8 s), then the hit at about 4 s" },
};
story.preset = function preset(name, over = {}) {
  const base = story.presets[name];
  if (!base) throw new Error("story.preset: unknown preset '" + name + "' (" + Object.keys(story.presets).join(", ") + ")");
  const o = { duration: 10, ...base, ...over };
  const k = o.duration / 10, sc = (v) => (over[v] != null ? over[v] : +(base[v] * k).toFixed(3));
  const plan = story.plan({ duration: o.duration, fps: o.fps, hookEnd: sc("hookEnd"), buildEnd: sc("buildEnd"), tensionEnd: sc("tensionEnd"), hit: sc("hit"), payoffEnd: sc("payoffEnd"), mode: o.mode });
  const where = over.identity || base.identity, D = o.duration;
  const at = where === "hook" ? +(plan.phases.hook[1] * 0.6).toFixed(2) : where === "release" ? +(plan.phases.release[0] + 0.55).toFixed(2) : +(D - 2.35).toFixed(2);
  plan.preset = name; plan.note = base.note;
  plan.identity = { where, at };   /* M.identity(tl, { plan, where: plan.identity.where, at: U(plan.identity.at), ... }) */
  return plan;
};

/* ================================================================== 9. MICRO-ONSETS (a new small event at least every N ms) */
export function flash(tl, el, { at = 0, scale = 1.3, dur = 0.38, base = 1 } = {}) {
  tl.fromTo(el, { scale: base }, { scale: base * scale, duration: dur * 0.3, ease: "power2.out", immediateRender: false }, at);
  tl.fromTo(el, { scale: base * scale }, { scale: base, duration: dur * 0.7, ease: ease.settle, immediateRender: false }, at + dur * 0.3);
  return dur;
}

function sparkleOnce(tl, host, t, r, { size = 30, color: col } = {}) {
  host = arr(host)[0];
  if (getComputedStyle(host).position === "static") host.style.position = "relative";
  const s = mk("i", "mo-spark", { left: r.range(15, 85) + "%", top: r.range(15, 85) + "%", width: size + "px", height: size + "px" }, host);
  if (col) s.style.background = col;
  gs().set(s, { xPercent: -50, yPercent: -50, scale: 0, opacity: 0, rotation: 0 });
  tl.fromTo(s, { scale: 0, opacity: 1, rotation: 0 }, { scale: 1, rotation: 45, duration: 0.16, ease: ease.pop, immediateRender: false }, t);
  tl.fromTo(s, { scale: 1, opacity: 1, rotation: 45 }, { scale: 0, opacity: 0, rotation: 90, duration: 0.24, ease: "power2.in", immediateRender: false }, t + 0.16);
  return 0.4;
}

const KINDS = {
  blink(tl, el, t, b) {
    tl.fromTo(el, { opacity: b.opacity }, { opacity: b.opacity * 0.15, duration: 0.07, ease: "power1.in", immediateRender: false }, t);
    tl.fromTo(el, { opacity: b.opacity * 0.15 }, { opacity: b.opacity, duration: 0.16, ease: "power2.out", immediateRender: false }, t + 0.07);
    return 0.23;
  },
  tick(tl, el, t, b) {
    tl.fromTo(el, { y: b.y }, { y: b.y - 6, duration: 0.07, ease: "power2.out", immediateRender: false }, t);
    tl.fromTo(el, { y: b.y - 6 }, { y: b.y, duration: 0.18, ease: ease.pop, immediateRender: false }, t + 0.07);
    return 0.25;
  },
  pulse(tl, el, t, b) {
    tl.fromTo(el, { scale: b.scale }, { scale: b.scale * 1.22, duration: 0.1, ease: "power2.out", immediateRender: false }, t);
    tl.fromTo(el, { scale: b.scale * 1.22 }, { scale: b.scale, duration: 0.3, ease: "sine.inOut", immediateRender: false }, t + 0.1);
    return 0.4;
  },
  glyph(tl, el, t, b) {
    tl.fromTo(el, { rotation: b.rotation }, { rotation: b.rotation + 360, duration: 0.42, ease: "back.inOut(1.4)", immediateRender: false }, t);
    return 0.42;
  },
  sparkle(tl, el, t, b, r) { return sparkleOnce(tl, el, t, r); },
  /* object life (section 17): the pool element is an object <svg>; these animate its tagged parts only */
  sway: (tl, el, t, b, r) => life.sway(tl, el, { at: t, seed: r.next() }),
  swing: (tl, el, t, b, r) => life.swing(tl, el, { at: t, seed: r.next() }),
  sheen: (tl, el, t) => life.sheen(tl, el, { at: t }),
  glint: (tl, el, t) => life.glint(tl, el, { at: t }),
  wiggle: (tl, el, t, b, r) => life.wiggle(tl, el, { at: t, seed: r.next() }),
  slosh: (tl, el, t, b, r) => life.slosh(tl, el, { at: t, seed: r.next() }),
  bubble: (tl, el, t) => life.bubble(tl, el, { at: t }),
  caret: (tl, el, t) => life.caret(tl, el, { at: t }),
  pop: (tl, el, t) => life.pop(tl, el, { at: t }),
};

export const onsets = {
  /* pool: elements or { el, from, to, base:{opacity,scale,y,rotation}, kinds:[...] }.
     `every` is a number, or a function of time (story.plan().pace). `quiet` = [[a,b]] windows with NO secondary
     onsets (the held breath of the tension beat). Returns { times, maxGap }. */
  schedule(tl, pool, { at = 0, duration, every = 0.4, seed = 3, kinds = ["blink", "tick", "pulse", "glyph", "sparkle"], tail = 0.5, quiet = [] } = {}) {
    const r = rng(seed), end = at + duration;
    const P = pool.map((p) => {
      const o = p && p.el ? p : { el: p };
      return { el: o.el, from: o.from ?? at, to: o.to ?? end, kinds: o.kinds || kinds, last: -9, busy: -9,
        base: { opacity: 1, scale: 1, y: 0, rotation: 0, ...(o.base || {}) } };
    });
    const iv = (t) => (typeof every === "function" ? every(t) : every);
    const times = [];
    let t = at + r.range(0.05, iv(at) * 0.6);
    while (t < end - tail) {
      const q = quiet.find(([a, b]) => t >= a && t < b);
      if (q) { t = q[1]; continue; }
      const live = P.filter((p) => t >= p.from && t + 0.45 <= p.to);
      if (live.length) {
        const free = live.filter((p) => p.busy <= t);
        const cand = free.length ? free : live;
        const minLast = Math.min(...cand.map((p) => p.last));
        const p = r.pick(cand.filter((q2) => q2.last === minLast));
        const kind = r.pick(p.kinds);
        const dur = KINDS[kind](tl, p.el, t, p.base, r);
        p.last = t; p.busy = t + dur;
        times.push(t);
      }
      const step = iv(t);
      t += (isFinite(step) ? step : 0.3) * r.range(0.6, 0.95);
    }
    let maxGap = 0;
    for (let i = 1; i < times.length; i++) maxGap = Math.max(maxGap, times[i] - times[i - 1]);
    return { times, maxGap };
  },

  sparkle(tl, el, { at = 0, count = 3, gap = 0.09, seed = 21, size = 30, color: col } = {}) {
    const r = rng(seed);
    for (let i = 0; i < count; i++) sparkleOnce(tl, el, at + i * gap, r, { size, color: col });
  },
};

/* ================================================================== 10. CONNECTOR PULSE (dot along an SVG path) */
export function pulseAlong(tl, path, { at = 0, duration = 1, ease: e = "power2.inOut", r = 7, color: col = null, trail = 3, lag = 0.045,
  steps = 28, fade = 0.1, opacity = 1, halo = true, nodes = [] } = {}) {
  col = col || color.pick("hero");
  const L = path.getTotalLength(), parent = path.parentNode, easeFn = typeof e === "function" ? e : gs().parseEase(e);
  const pts = [], prog = [];
  for (let i = 0; i <= steps; i++) {
    const p = Math.min(1, Math.max(0, easeFn(i / steps)));
    prog.push(p);
    pts.push(path.getPointAtLength(L * p));
  }
  const heads = [];
  const total = trail + 1 + (halo ? 1 : 0);
  for (let j = 0; j < total; j++) {
    const isHalo = halo && j === 0, k = halo ? j - 1 : j;
    const rad = isHalo ? r * 2.4 : r * (1 - 0.16 * k);
    const op = (isHalo ? 0.22 : 1 - 0.22 * k) * opacity;
    const c = document.createElementNS(NS, "circle");
    c.setAttribute("r", rad); c.setAttribute("fill", col); c.setAttribute("class", "mo-pulse");
    parent.insertBefore(c, path.nextSibling);
    gs().set(c, { x: pts[0].x, y: pts[0].y, opacity: 0 });
    const t0 = at + Math.max(0, k) * lag;
    tl.set(c, { x: pts[0].x, y: pts[0].y }, t0);
    tl.to(c, { keyframes: pts.slice(1).map((p) => ({ x: p.x, y: p.y, duration: duration / steps, ease: "none" })) }, t0);
    tl.fromTo(c, { opacity: 0 }, { opacity: op, duration: fade, ease: "none", immediateRender: false }, t0);
    tl.fromTo(c, { opacity: op }, { opacity: 0, duration: fade, ease: "none", immediateRender: false }, t0 + duration - fade);
    heads.push(c);
  }
  nodes.forEach((n) => {
    const i = prog.findIndex((p) => p >= n.p - 1e-6);
    if (i >= 0) flash(tl, n.el, { at: at + duration * (i / steps), scale: n.scale || 1.45, dur: n.dur || 0.4, base: n.base ?? 1 });
  });
  return heads;
}

/* A train of back-to-back pulses that exactly fills `duration`. */
export function pulseTrain(tl, path, { at = 0, duration, count = 3, seed = 11, overlap = 0, speedJitter = 0.35, eases = ["sine.inOut", "power2.inOut"], ...rest } = {}) {
  const r = rng(seed), ds = Array.from({ length: count }, () => 1 + (r.next() - 0.5) * 2 * speedJitter);
  const s = [0]; let acc = 0;
  for (let i = 0; i < count - 1; i++) { acc += ds[i] * (1 - overlap); s.push(acc); }
  const k = duration / (s[count - 1] + ds[count - 1]);
  for (let i = 0; i < count; i++) pulseAlong(tl, path, { ...rest, at: at + s[i] * k, duration: ds[i] * k, ease: eases[i % eases.length] });
}

/* ================================================================== 11. TYPEWRITER (caret + per-character jitter) */
function splitText(el, unit) {
  const units = [];
  const walk = (node) => {
    for (const child of Array.from(node.childNodes)) {
      if (child.nodeType === 3) {
        const txt = child.nodeValue; if (!txt) continue;
        const frag = document.createDocumentFragment();
        const parts = unit === "word" ? txt.split(/(\s+)/) : Array.from(txt);
        for (const p of parts) {
          if (p === "") continue;
          if (/^\s+$/.test(p)) { frag.appendChild(document.createTextNode(p)); continue; }
          const s = document.createElement("span"); s.className = "mo-u"; s.textContent = p; frag.appendChild(s); units.push(s);
        }
        node.replaceChild(frag, child);
      } else if (child.nodeType === 1) walk(child);
    }
  };
  walk(el);
  return units;
}

/* unit "char" (Latin) or "word". Arabic is forced to "word": splitting letters breaks joining. */
export function typewriter(tl, el, { at = 0, duration = 1, unit = "char", caret = true, jitter = 0.45, seed = 5, pause = 0.5,
  lift = 4, caretUntil = null, blink = 0.5, lead = 0.06, unitDur = 0.07 } = {}) {
  if (/[؀-ۿ]/.test(el.textContent)) unit = "word";
  const units = splitText(el, unit), n = units.length, r = rng(seed);
  if (!n) return { units, times: [] };
  gs().set(units, { opacity: 0 });
  const w = units.map((u) => {
    const ch = u.textContent;
    return (1 + (r.next() - 0.5) * 2 * jitter) + (/[.,:;!?\-]/.test(ch) ? pause : 0);
  });
  const sum = w.reduce((a, b) => a + b, 0), span = Math.max(0.05, duration - lead);
  const times = []; let acc = 0;
  for (let i = 0; i < n; i++) { times.push(at + lead + span * (acc / sum)); acc += w[i]; }
  units.forEach((u, i) => {
    const jl = lift * r.range(0.5, 1.4), jr = r.range(-3, 3);
    tl.fromTo(u, { opacity: 0, y: jl, rotation: jr }, { opacity: 1, y: 0, rotation: 0, duration: unitDur, ease: "power2.out", immediateRender: false }, times[i]);
  });
  if (caret) {
    const carets = [];
    for (let i = 0; i <= n; i++) {
      const c = document.createElement("span"); c.className = "mo-caret";
      if (i === 0) units[0].parentNode.insertBefore(c, units[0]); else units[i - 1].after(c);
      carets.push(c);
    }
    gs().set(carets, { opacity: 0 });
    const tEnd = at + duration, until = caretUntil ?? tEnd + 0.12;
    carets.forEach((c, i) => {
      const t0 = i === 0 ? at : times[i - 1];
      const t1 = i < n ? times[i] : null;
      tl.set(c, { opacity: 1 }, t0);
      if (t1 !== null) { tl.set(c, { opacity: 0 }, t1); return; }
      const half = blink * 0.6;
      for (let k = 1, t = t0 + half; t < until; k++, t = t0 + half * (k)) tl.set(c, { opacity: k % 2 ? 0 : 1 }, t);
      tl.set(c, { opacity: 0 }, until);
    });
  }
  return { units, times };
}

/* ================================================================== 12. FOCUS PULL (blur + dim the rest, sharpen the hero) */
export const focus = {
  pull(tl, { hero = null, others, at = 0, duration = 0.45, blur = 4, dim = 0.45, baseOpacity = 1, heroBlurFrom = 0, ease: e = "power2.inOut" } = {}) {
    tl.fromTo(others, { filter: "blur(0px)", opacity: baseOpacity }, { filter: `blur(${blur}px)`, opacity: baseOpacity * dim, duration, ease: e, immediateRender: false }, at);
    if (hero) tl.fromTo(hero, { filter: `blur(${heroBlurFrom}px)` }, { filter: "blur(0px)", duration, ease: e, immediateRender: false }, at);
  },
  release(tl, { others, at = 0, duration = 0.45, blur = 4, dim = 0.45, baseOpacity = 1, ease: e = "power2.inOut" } = {}) {
    tl.fromTo(others, { filter: `blur(${blur}px)`, opacity: baseOpacity * dim }, { filter: "blur(0px)", opacity: baseOpacity, duration, ease: e, immediateRender: false }, at);
  },
};

/* ================================================================== 13. STATE COLOUR (idle -> active -> done, with glow)
   States come from the post's colour script (color.states). Every state also needs a second cue: pass `badge`. */
export function stateChange(tl, el, { from = "idle", to = "active", at = 0, duration = 0.35, states = null, props = null, ease: e = "power2.out", badge = null, badgeOut = null } = {}) {
  states = states || color.states();
  const a = states[from], b = states[to], keys = (props || Object.keys(b)).filter((k) => k in a && k in b);
  const A = {}, B = {};
  keys.forEach((k) => { A[k] = a[k]; B[k] = b[k]; });
  tl.fromTo(el, A, { ...B, duration, ease: e, immediateRender: false }, at);
  if (badge) tl.fromTo(badge, { scale: 0.3, opacity: 0 }, { scale: 1, opacity: 1, duration: duration * 1.2, ease: ease.pop, immediateRender: false }, at + duration * 0.35);
  if (badgeOut) tl.fromTo(badgeOut, { scale: 1, opacity: 1 }, { scale: 0.3, opacity: 0, duration: duration * 0.8, ease: "power2.in", immediateRender: false }, at);
}

/* ================================================================== 14. COUNTER (v4: whole values, never scrambled digits)
   style "roll" (default): the old whole value slides out and the new whole value slides in, in one mask window.
   style "step": the value steps through `steps` whole, valid numbers (JOD 0.000 -> 14.000 -> 28.000 -> 42.000 -> 56.000), one change per beat.
   style "odometer" (DEPRECATED, v3): every digit column spins past 0-9; mid-roll it shows meaningless digits and reads as a render glitch. */
export function counter(tl, el, { to, from = null, at = 0, duration = 0.6, stagger = 0.07, ease: e = null, spin = true, lh = 1.1, restBefore = "from", style = "roll", steps = 4 } = {}) {
  el = arr(el)[0];
  const dest = String(to ?? el.textContent.trim());
  let src = String(from ?? (style === "odometer" ? dest.replace(/\d/g, "0") : dest.replace(/\d+(\.(\d+))?/, (m, f, d) => (0).toFixed(d ? d.length : 0))));
  if (style === "odometer") return counterOdometer(tl, el, { dest, src, at, duration, stagger, e: e || "power3.inOut", spin, lh, restBefore });
  const rows = [src, dest];
  if (style === "step") {
    const num = (s) => parseFloat(String(s).replace(/[^0-9.\-]/g, "")), dec = ((String(dest).match(/\.(\d+)/) || [])[1] || "").length;
    const a = isFinite(num(src)) ? num(src) : 0, b = num(dest), at0 = String(dest).search(/[0-9]/), pre = at0 > 0 ? String(dest).slice(0, at0) : "";
    rows.length = 0;
    for (let k = 0; k <= steps; k++) rows.push(k === 0 ? src : k === steps ? dest : pre + (a + (b - a) * k / steps).toFixed(dec));
  }
  el.textContent = "";
  Object.assign(el.style, { display: "inline-block", overflow: "hidden", height: lh + "em", lineHeight: lh, verticalAlign: "top", whiteSpace: "pre" });
  el.setAttribute("aria-label", dest);
  el.classList.add("mo-roll");
  ["overlap", "occlusion", "overflow"].forEach((a) => el.setAttribute("data-layout-allow-" + a, "true"));
  const col = mk("span", "mo-roll-col", { display: "block" }, el), n = rows.length;
  rows.forEach((t) => { const r = mk("span", "", { display: "block", height: lh + "em", lineHeight: lh, whiteSpace: "pre" }, col); r.textContent = t; ["overlap", "occlusion", "overflow"].forEach((a) => r.setAttribute("data-layout-allow-" + a, "true")); });
  const yp = (k) => -100 * k / n;
  gs().set(col, { yPercent: yp(restBefore === "to" ? n - 1 : 0) });
  if (restBefore === "to") tl.set(col, { yPercent: yp(0) }, Math.max(0, at - 0.02));
  if (style === "step") for (let k = 1; k < n; k++) tl.set(col, { yPercent: yp(k) }, at + duration * k / (n - 1));
  else tl.fromTo(col, { yPercent: yp(0) }, { yPercent: yp(1), duration, ease: e || ease.heavy, immediateRender: false }, at);
  return [col];
}

function counterOdometer(tl, el, { dest, src, at, duration, stagger, e, spin, lh, restBefore }) {
  while (src.length < dest.length) src = "0" + src;
  src = src.slice(src.length - dest.length);
  el.textContent = "";
  Object.assign(el.style, { display: "flex", alignItems: "center", whiteSpace: "pre" });
  el.setAttribute("aria-label", dest);
  const chars = Array.from(dest), cols = [];
  let rank = 0;
  for (let i = chars.length - 1; i >= 0; i--) {
    const ch = chars[i];
    if (!/\d/.test(ch)) continue;
    const s = parseInt(src[i], 10), d = parseInt(ch, 10), turns = spin ? (rank === 0 ? 2 : rank === 1 ? 1 : 0) : 0;
    const dist = ((d - s + 10) % 10) + 10 * turns, R = 10 * (turns + 2), end = s + dist;
    cols.push({ i, s, end, R, rank });
    rank++;
  }
  chars.forEach((ch, i) => {
    const c = cols.find((q) => q.i === i);
    if (!c) { mk("span", "mo-static", { display: "block", height: lh + "em", lineHeight: lh, whiteSpace: "pre" }, el).textContent = ch; return; }
    const win = mk("span", "mo-roll", { display: "block", height: lh + "em", overflow: "hidden", lineHeight: lh }, el);
    const col = mk("span", "mo-roll-col", { display: "block" }, win);
    [win, col].forEach((n) => ["overlap", "occlusion", "overflow"].forEach((a) => n.setAttribute("data-layout-allow-" + a, "true")));
    for (let k = 0; k < c.R; k++) {
      const row = mk("span", "", { display: "block", height: lh + "em", textAlign: "center" }, col);
      row.textContent = String(k % 10);
      ["overlap", "occlusion", "overflow"].forEach((a) => row.setAttribute("data-layout-allow-" + a, "true"));
    }
    c.col = col;
  });
  cols.forEach((c) => {
    const yp = (idx) => -100 * idx / c.R;
    gs().set(c.col, { yPercent: yp(restBefore === "to" ? c.end : c.s) });
    if (restBefore === "to") tl.set(c.col, { yPercent: yp(c.s) }, Math.max(0, at - 0.02));
    tl.fromTo(c.col, { yPercent: yp(c.s) }, { yPercent: yp(c.end), duration, ease: e, immediateRender: false }, at + c.rank * stagger);
  });
  return cols.map((c) => c.col);
}

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

/* ================================================================== 17. OBJECTS (the cast: real things, never flat swatches)
   Hand-built inline SVG in brand/motion/objects/*.svg (packed into objects.data.js by objects/build.mjs).
   Each has layered shading, a highlight and a soft contact shadow, driven by CSS custom properties that INHERIT:
   --light-x / --light-y (-1..1, +x = light from the right, -y = from above) and --light-i (intensity), plus the
   object's own colours (--obj-base, --obj-accent, --obj-face, --obj-ink, ...). Set them on any ancestor.
   Parts are tagged data-part="..." so idle "life" helpers can animate them; every life move starts and ends at rest. */
let _objN = 0;
function uniqIds(markup, uid) {
  let out = markup;
  [...markup.matchAll(/\bid="([^"]+)"/g)].map((m) => m[1]).forEach((id) => {
    out = out.split(`id="${id}"`).join(`id="${uid}-${id}"`).split(`url(#${id})`).join(`url(#${uid}-${id})`).split(`href="#${id}"`).join(`href="#${uid}-${id}"`);
  });
  return out;
}
const parts = (obj, name) => Array.from(arr(obj)[0].querySelectorAll(`[data-part="${name}"]`));
const vbw = (obj) => { const v = arr(obj)[0].viewBox && arr(obj)[0].viewBox.baseVal; return v && v.width ? v.width : 200; };
/* rest -> a1 -> a2 ... -> rest on one property, equal segments, explicit fromTo states (seek-safe) */
function osc(tl, el, prop, amps, t, dt, e = "sine.inOut", rest = 0) {
  const v = [rest, ...amps.map((a) => rest + a), rest];
  for (let i = 0; i < v.length - 1; i++) tl.fromTo(el, { [prop]: v[i] }, { [prop]: v[i + 1], duration: dt, ease: e, immediateRender: false }, t + i * dt);
  return dt * (v.length - 1);
}
const dirOf = (seed, t) => (rng(seed == null ? "d" + t : seed).next() < 0.5 ? -1 : 1);

export const life = {
  /* fabric hanging from the collar: a damped sway, the folds follow a beat late. shirt */
  sway(tl, obj, { at = 0, amp = 1.6, dur = 0.88, seed = null } = {}) {
    const d = dirOf(seed, at), dt = dur / 4;
    parts(obj, "hang").forEach((h) => { osc(tl, h, "rotation", [amp * d, -amp * 0.7 * d, amp * 0.35 * d], at, dt); osc(tl, h, "skewX", [amp * 0.9 * d, -amp * 0.6 * d, amp * 0.3 * d], at, dt); });
    parts(obj, "folds").forEach((f) => osc(tl, f, "x", [1.8 * d, -1.2 * d, 0.6 * d], at + 0.07, dt));
    return dur + 0.07;
  },
  /* the handles swing from where they are stitched on, the back one a beat behind. tote */
  swing(tl, obj, { at = 0, amp = 3.4, dur = 0.96, seed = null } = {}) {
    const d = dirOf(seed, at), dt = dur / 4;
    parts(obj, "handle").forEach((h) => osc(tl, h, "rotation", [amp * d, -amp * 0.72 * d, amp * 0.38 * d], at, dt));
    parts(obj, "handleback").forEach((h) => osc(tl, h, "rotation", [amp * 0.7 * d, -amp * 0.5 * d, amp * 0.25 * d], at + 0.06, dt));
    return dur + 0.06;
  },
  /* a specular band crosses the object's silhouette (every object has a clipped data-part="sheen") */
  sheen(tl, obj, { at = 0, dur = 0.8, opacity = 0.7 } = {}) {
    const travel = vbw(obj) + 240;
    parts(obj, "sheen").forEach((g) => {
      tl.fromTo(g, { x: 0 }, { x: travel, duration: dur, ease: ease.soft, immediateRender: false }, at);
      tl.fromTo(g, { opacity: 0 }, { opacity: opacity, duration: dur * 0.3, ease: "power1.out", immediateRender: false }, at);
      tl.fromTo(g, { opacity: opacity }, { opacity: 0, duration: dur * 0.3, ease: "power1.in", immediateRender: false }, at + dur * 0.7);
    });
    return dur;
  },
  glint(tl, obj, o = {}) { return life.sheen(tl, obj, { dur: 0.7, opacity: 0.6, ...o }); },
  /* small living jitter: antennae twitch in opposition, legs scuttle, a cursor wobbles on its tip. bug, cursors */
  wiggle(tl, obj, { at = 0, amp = 8, dur = 0.5, seed = null } = {}) {
    const d = dirOf(seed, at), dt = dur / 4;
    parts(obj, "ant").forEach((a, i) => osc(tl, a, "rotation", [amp * d * (i ? -1 : 1), -amp * 0.8 * d * (i ? -1 : 1), amp * 0.4 * d * (i ? -1 : 1)], at + i * 0.04, dt));
    parts(obj, "legs").forEach((l) => osc(tl, l, "rotation", [2.4 * d, -2.4 * d, 1.6 * d], at, dt * 0.6, "sine.inOut"));
    const cur = arr(obj)[0].dataset.object || "";
    if (cur.startsWith("cursor")) parts(obj, "wiggle").forEach((w) => osc(tl, w, "rotation", [amp * 0.5 * d, -amp * 0.35 * d, amp * 0.15 * d], at, dt));
    return dur + 0.04;
  },
  /* liquid sloshes in the glass. flask */
  slosh(tl, obj, { at = 0, amp = 3, dur = 0.9, seed = null } = {}) {
    const d = dirOf(seed, at), dt = dur / 4;
    parts(obj, "liquid").forEach((l) => { osc(tl, l, "rotation", [amp * d, -amp * 0.7 * d, amp * 0.35 * d], at, dt); osc(tl, l, "x", [2.4 * d, -1.6 * d, 0.8 * d], at, dt); });
    return dur;
  },
  /* bubbles rise and fade, then come back at rest. flask */
  bubble(tl, obj, { at = 0, rise = 26, dur = 0.7 } = {}) {
    const bs = parts(obj, "bubble");
    bs.forEach((b, i) => {
      const t = at + i * 0.12;
      tl.fromTo(b, { y: 0 }, { y: -rise, duration: dur, ease: "power1.out", immediateRender: false }, t);
      tl.fromTo(b, { opacity: 1 }, { opacity: 0, duration: dur, ease: "power1.in", immediateRender: false }, t);
      tl.set(b, { y: 0 }, t + dur + 0.02);
      tl.fromTo(b, { opacity: 0 }, { opacity: 1, duration: 0.14, ease: "power1.out", immediateRender: false }, t + dur + 0.03);
    });
    return dur + 0.2 + Math.max(0, bs.length - 1) * 0.12;
  },
  /* terminal caret blinks once */
  caret(tl, obj, { at = 0 } = {}) {
    parts(obj, "caret").forEach((c) => { tl.fromTo(c, { opacity: 1 }, { opacity: 0, duration: 0.06, immediateRender: false }, at); tl.fromTo(c, { opacity: 0 }, { opacity: 1, duration: 0.06, immediateRender: false }, at + 0.22); });
    return 0.3;
  },
  /* the tick on a badge pops */
  pop(tl, obj, { at = 0, scale = 1.16 } = {}) {
    parts(obj, "check").forEach((c) => { tl.fromTo(c, { scale: 1 }, { scale, duration: 0.1, ease: "power2.out", immediateRender: false }, at); tl.fromTo(c, { scale }, { scale: 1, duration: 0.36, ease: ease.spring, immediateRender: false }, at + 0.1); });
    return 0.46;
  },
};

export const objects = {
  names: () => Object.keys(OBJ_SVG),
  /* put an object into host; returns the <svg>. opts: { id, width, height, vars: { "obj-base": "#..." }, className, style } */
  mount(host, name, { id = null, width = null, height = null, vars = null, className = "", style = null } = {}) {
    const src = OBJ_SVG[name];
    if (!src) throw new Error("objects.mount: unknown object '" + name + "' (have: " + Object.keys(OBJ_SVG).join(", ") + ")");
    host = arr(host)[0];
    const tpl = document.createElement("template");
    tpl.innerHTML = uniqIds(src, "mo-" + name + "-" + (id || ++_objN));
    const svg = tpl.content.firstElementChild;
    svg.setAttribute("class", ("mo-obj " + className).trim());
    if (width != null) svg.setAttribute("width", width);
    if (height != null) svg.setAttribute("height", height);
    svg.setAttribute("aria-hidden", "true");
    if (vars) Object.entries(vars).forEach(([k, v]) => svg.style.setProperty(k.startsWith("--") ? k : "--" + k, v));
    if (style) Object.assign(svg.style, style);
    host.appendChild(svg);
    allow(svg);
    svg.querySelectorAll("[data-pivot]").forEach((el) => gs().set(el, { svgOrigin: el.getAttribute("data-pivot") }));
    return svg;
  },
  /* static light on an object or container: { x, y, i } */
  setLight(el, { x = -0.6, y = -0.6, i = 1 } = {}) { arr(el).forEach((e) => { e.style.setProperty("--light-x", x); e.style.setProperty("--light-y", y); e.style.setProperty("--light-i", i); }); },
  /* drive the same light path as light.cast/rim onto a container: every object inside follows (highlight and shadow shift) */
  follow(tl, container, { path, at = 0, duration, step = 0.1 } = {}) {
    sample(tl, container, { at, duration, step, fn: (t) => { const L = path(t); return { "--light-x": +L.x.toFixed(3), "--light-y": +L.y.toFixed(3), "--light-i": +L.i.toFixed(3) }; } });
  },
  /* press state: the face of a button sinks onto its lip, then springs back */
  press(tl, obj, { at = 0, depth = 6, down = 0.07, up = 0.36 } = {}) {
    parts(obj, "face").forEach((f) => {
      tl.fromTo(f, { y: 0 }, { y: depth, duration: down, ease: "power2.in", immediateRender: false }, at);
      tl.fromTo(f, { y: depth }, { y: 0, duration: up, ease: ease.spring, immediateRender: false }, at + down);
    });
    return down + up;
  },
  /* which idle kinds an object supports (for onsets.schedule pools) */
  idleKinds(name) {
    const n = typeof name === "string" ? name : arr(name)[0].dataset.object;
    return ({ shirt: ["sway", "sheen"], tote: ["swing", "sheen"], bug: ["wiggle", "sheen"], flask: ["slosh", "bubble", "sheen"], terminal: ["caret", "sheen"], "check-badge": ["pop", "sheen"],
      "button-checkout": ["glint"], "cursor-arrow": ["wiggle"], "cursor-hand": ["wiggle"] })[n] || ["sheen"];
  },
  /* pool entry for onsets.schedule: objects.pool(svg, { from, to }) -> { el, kinds, from, to }. Keep `to` at least 0.9 s before the loop end. */
  pool(obj, { from, to, kinds } = {}) { const el = arr(obj)[0]; return { el, kinds: kinds || objects.idleKinds(el.dataset.object), ...(from != null ? { from } : {}), ...(to != null ? { to } : {}) }; },
};

/* ================================================================== 19. STANDARD v4 (council 2026-10-16): grid, type, cut, split, poster
   All deterministic and seek-safe: explicit fromTo states, per-frame sampled clip-paths, no random, no tween-time DOM measuring.
   Times are seconds; use grid.f(frames) / U(...) to land on whole frames. Every directional helper takes rtl (Arabic: strikes and
   whips run right to left, the split mirrors, masks get extra headroom, no letter-spacing, words only). */
const FR = 1 / TOKENS.FPS;
const ALLOW = ["overlap", "occlusion", "overflow", "escape"];
const allowAll = (e) => ALLOW.forEach((a) => e.setAttribute("data-layout-allow-" + a, "true"));
const isArabic = (s) => /[؀-ۿ]/.test(s);

/* ---- M.grid: the beat-grid lock. One pulse every `pulse` frames (default 12 = 0.48 s); big moves land on beats ---- */
export const grid = {
  fps: TOKENS.FPS,
  f: (n, fps = TOKENS.FPS) => n / fps,                                        /* frames -> seconds */
  snap: (t, fps = TOKENS.FPS) => Math.round(t * fps) / fps,
  beat: (n, pulse = 12, fps = TOKENS.FPS) => (n * pulse) / fps,               /* time of beat n */
  lock: (t, pulse = 12, fps = TOKENS.FPS) => Math.round(t * fps / pulse) * pulse / fps,   /* nearest beat time */
  onBeat: (t, pulse = 12, fps = TOKENS.FPS) => Math.abs(t * fps / pulse - Math.round(t * fps / pulse)) < 1e-6,
  /* a bar flashes on every beat (a felt metronome, never a move). Beats whose flash overlaps a hold are skipped, so a dead stop stays dead. */
  beats(tl, el, { duration, pulse = 12, fps = TOKENS.FPS, hi = 0.95, lo = 0.12, fade = 7, skip = [] } = {}) {
    gs().set(el, { opacity: lo });
    for (let f = 0; f < duration * fps - 1e-6; f += pulse) {
      const t0 = f / fps, t1 = (f + fade) / fps;
      if (skip.some(([a, b]) => t0 < b && t1 > a)) continue;
      tl.fromTo(el, { opacity: hi }, { opacity: lo, duration: fade / fps, ease: "power2.out", immediateRender: false }, t0);
    }
  },
  /* a strip that runs linearly, exactly `unit` px per loop (so frame N == frame 0), and stands still inside every hold */
  ticker(tl, el, { duration, unit = TOKENS.W, holds = [], at = 0, fps = TOKENS.FPS, dir = -1 } = {}) {
    const held = (t) => holds.reduce((s, [a, b]) => s + Math.max(0, Math.min(b, t) - Math.min(a, t)), 0);
    const live = duration - held(duration);
    sample(tl, el, { at, duration, step: 1 / fps, fn: (t) => ({ x: dir * unit * ((t - at) - held(t - at)) / live }) });
  },
};

/* ---- M.type: word masks with weighted overshoot, strike-through, re-entry ---- */
export const type = {
  ease: { heavy: bezier(0.25, 1.3, 0.4, 1), light: bezier(0.16, 1, 0.3, 1), stop: bezier(0.1, 0.9, 0.2, 1), out: bezier(0.55, 0, 0.9, 0.4) },
  /* Split an element's text into masked words (a .mo-w inside a .mo-mk, which clips). Arabic gets word units only, letter-spacing 0,
     line-height 1.4 and extra mask headroom (hamza, dots, tails). Returns the word elements in reading order (.masks, .rtl attached).
     Rest state is visible (poster); hide with gsap.set(words, { yPercent: 118 }) only if the word enters later. */
  words(el, { rtl = null } = {}) {
    el = arr(el)[0];
    const ar = rtl != null ? rtl : isArabic(el.textContent), list = el.textContent.trim().split(/\s+/), words = [], masks = [];
    el.textContent = "";
    if (ar) { el.setAttribute("dir", "rtl"); el.setAttribute("lang", "ar"); el.style.letterSpacing = "0"; if (!el.style.lineHeight) el.style.lineHeight = "1.4"; }
    list.forEach((t, i) => {
      if (i) el.appendChild(document.createTextNode(" "));
      const m = mk("span", "mo-mk" + (ar ? " mo-mk-ar" : ""), null, el), w = mk("span", "mo-w", null, m);
      w.textContent = t; allowAll(m); allowAll(w); masks.push(m); words.push(w);
    });
    words.masks = masks; words.rtl = ar;
    return words;
  },
  /* rise out of the mask: heavy = late arrival with about 3 % overshoot, light = clean snap. Returns the end time. */
  enter(tl, w, { at = 0, dur = 0.5, weight = "light", from = 118 } = {}) {
    tl.fromTo(w, { yPercent: from }, { yPercent: 0, duration: dur, ease: weight === "heavy" ? type.ease.heavy : type.ease.light, immediateRender: false }, at);
    return at + dur;
  },
  /* words in reading order (Arabic: right to left, because the DOM order is logical), `gap` apart; weights: ["heavy","light",...] */
  enterWords(tl, words, { at = 0, gap = 0.06, dur = 0.4, weights = null } = {}) {
    const w = arr(words);
    w.forEach((el, i) => type.enter(tl, el, { at: at + i * gap, dur, weight: weights ? weights[i % weights.length] : "light" }));
    return at + (w.length - 1) * gap + dur;
  },
  /* leave upward through the mask on an accelerating ease; one frame apart */
  exit(tl, w, { at = 0, dur = 0.24, to = -118 } = {}) {
    tl.fromTo(w, { yPercent: 0 }, { yPercent: to, duration: dur, ease: type.ease.out, immediateRender: false }, at);
    return at + dur;
  },
  exitWords(tl, words, { at = 0, gap = FR, dur = 0.24 } = {}) {
    const w = arr(words);
    w.forEach((el, i) => type.exit(tl, el, { at: at + i * gap, dur }));
    return at + (w.length - 1) * gap + dur;
  },
  /* follow-through on a beat: the word drops px and springs back (weight for few pixels) */
  nudge(tl, w, { at = 0, px = 7 } = {}) {
    tl.fromTo(w, { y: 0 }, { y: px, duration: 2 * FR, ease: "power2.in", immediateRender: false }, at);
    tl.fromTo(w, { y: px }, { y: 0, duration: 8 * FR, ease: ease.spring, immediateRender: false }, at + 2 * FR);
  },
  /* RE-ENTRY: a word that left through the mask comes back from below, so it never retraces its exit. Same as enter; named so the
     intent is in the script. For a return at a bigger size, pass a second, bigger element. */
  reenter(tl, w, opts = {}) { return type.enter(tl, w, opts); },
  /* push `outs` out through their masks while `ins` rise: a real hand-over, not a cross-fade */
  swap(tl, outs, ins, { at = 0, outDur = 0.22, delay = 0.14, inDur = 0.5, gap = 0.05, weights = null } = {}) {
    type.exitWords(tl, outs, { at, dur: outDur });
    return type.enterWords(tl, ins, { at: at + delay, gap, dur: inDur, weights });
  },
  /* STRIKE-THROUGH: a bar inside the word's mask (so it clips with it). Returns the bar. Reveal with type.strike. */
  strikeBar(word, { color = "var(--c-accent, currentColor)", rtl = false, top = "54%", thick = "0.11em" } = {}) {
    word = arr(word)[0];
    const mask = word.parentNode;
    if (getComputedStyle(mask).position === "static") mask.style.position = "relative";
    const bar = mk("i", "mo-strike", { position: "absolute", left: "0", right: "0", top, height: thick, background: color, pointerEvents: "none" }, mask);
    allowAll(bar);
    gs().set(bar, { clipPath: rtl ? "inset(0 0 0 100%)" : "inset(0 100% 0 0)" });
    return bar;
  },
  /* the bar draws in along the reading direction (ltr: left to right; rtl: right to left); out = it leaves the same way */
  strike(tl, bar, { at = 0, dur = 0.2, rtl = false, out = false } = {}) {
    const hid = rtl ? "inset(0 0 0 100%)" : "inset(0 100% 0 0)", full = "inset(0 0% 0 0)", gone = rtl ? "inset(0 100% 0 0)" : "inset(0 0 0 100%)";
    if (out) tl.fromTo(bar, { clipPath: full }, { clipPath: gone, duration: dur, ease: type.ease.out, immediateRender: false }, at);
    else tl.fromTo(bar, { clipPath: hid }, { clipPath: full, duration: dur, ease: type.ease.light, immediateRender: false }, at);
    return at + dur;
  },
};

/* ---- M.cut: hard cut, match cut, circle iris from an element, flat whip wipe ---- */
export const cut = {
  ease: { swell: bezier(0.55, 0, 0.8, 0.08), slam: bezier(0.7, 0, 0.84, 0), out: bezier(0.05, 0.9, 0.16, 1), brake: bezier(0.45, 0, 0.1, 1) },
  /* swap scenes on one frame */
  hard(tl, at, { hide = [], show = [] } = {}) {
    arr(hide).forEach((e) => tl.set(e, { autoAlpha: 0 }, at));
    arr(show).forEach((e) => tl.set(e, { autoAlpha: 1 }, at));
  },
  /* MATCH CUT. mode "swell": `from` dips, then swells on a steep ease-in (fastest on the last frame), the cut lands on `at`, `into`
     opens at the same size, carries on 2 frames and settles. mode "collapse": `from` (a full-frame slab) is clipped down onto
     rectTo on the same ramp, the cut lands when it matches, and `into` (the real element, e.g. the button) takes over.
     hide / show are the scenes swapped on the cut. rect = { x, y, w, h, r }. */
  match(tl, { at, from, into, mode = "swell", peak = 1.2, swellDur = 0.74, dip = 0.965, carry = 1.035, settle = 0.4, hide = [], show = [],
    rectFrom = null, rectTo = null, size = [TOKENS.W, TOKENS.H], collapseDur = 0.32 } = {}) {
    if (mode === "collapse") {
      const [W, H] = size, a = rectFrom || { x: 0, y: 0, w: W, h: H, r: 0 }, b = rectTo, t0 = at - collapseDur;
      const R = (p) => { const L = (k) => a[k] + ((b[k] || 0) - a[k]) * p; return `inset(${L("y")}px ${W - L("x") - L("w")}px ${H - L("y") - L("h")}px ${L("x")}px round ${L("r") || 0}px)`; };
      sample(tl, from, { at: t0, duration: collapseDur, step: FR, fn: (t) => ({ clipPath: R(cut.ease.swell(clamp((t - t0) / collapseDur, 0, 1))) }) });
      cut.hard(tl, at, { hide: [from, ...arr(hide)], show });
      tl.fromTo(into, { scale: 1.08 }, { scale: 1, duration: settle, ease: ease.spring, immediateRender: false }, at);
      return { at, t0 };
    }
    const t0 = at - swellDur;
    tl.fromTo(from, { scale: 1 }, { scale: dip, duration: 0.08, ease: "power2.out", immediateRender: false }, t0);
    tl.fromTo(from, { scale: dip }, { scale: peak, duration: swellDur - 0.08, ease: cut.ease.swell, immediateRender: false }, t0 + 0.08);
    cut.hard(tl, at, { hide, show });
    tl.set(from, { scale: 1 }, at + 0.1);
    tl.fromTo(into, { scale: peak }, { scale: peak * carry, duration: 2 * FR, ease: "power2.out", immediateRender: false }, at);
    tl.fromTo(into, { scale: peak * carry }, { scale: 1, duration: settle, ease: ease.overshootSoft, immediateRender: false }, at + 2 * FR);
    return { at, t0 };
  },
  /* CIRCLE IRIS out of a point (the clicked element's centre). `reveal` is clipped by a circle that grows on a violent-start ease-out; an
     optional `rim` (a full-frame element) draws a flat ring that leads by `lag` s. reverse = it closes back into the point.
     One keyframe per frame. Returns { R, reach(d), end }: reach(d) = when the edge is d px from the centre (settle things as it passes). */
  iris(tl, { at, dur = 0.4, cx, cy, rMax = 1250, rim = null, reveal, lag = 0.08, ease: e = cut.ease.out, rimColor = "rgb(255,201,60)", reverse = false } = {}) {
    const rl = rim && !reverse ? lag : 0;
    const R = (t, off) => { const p = e(clamp((t - at - off) / dur, 0, 1)); return rMax * (reverse ? 1 - p : p); };
    const clip = (r) => `circle(${r.toFixed(1)}px at ${cx}px ${cy}px)`;
    const ringBg = (t) => { const a = R(t, lag).toFixed(1), b = R(t, 0).toFixed(1); return `radial-gradient(circle at ${cx}px ${cy}px, rgba(0,0,0,0) ${a}px, ${rimColor} ${a}px, ${rimColor} ${b}px, rgba(0,0,0,0) ${b}px)`; };
    if (!reverse) gs().set(reveal, { clipPath: clip(0) });
    if (rim && !reverse) {
      gs().set(rim, { backgroundImage: ringBg(at) });
      sample(tl, rim, { at, duration: dur + lag, step: FR, fn: (t) => ({ backgroundImage: ringBg(t) }) });
      tl.set(rim, { backgroundImage: "none" }, at + dur + lag + FR);
    }
    sample(tl, reveal, { at: at + rl, duration: dur, step: FR, fn: (t) => ({ clipPath: clip(R(t, rl)) }) });
    const reach = (d) => { for (let t = at + rl; t <= at + rl + dur + 1e-3; t += FR / 4) if ((reverse ? rMax - R(t, rl) : R(t, rl)) >= d) return t; return at + rl + dur; };
    return { R, reach, end: at + rl + dur };
  },
  /* FLAT WHIP WIPE: parallelogram panels step across the frame, one position per frame, each trailing the last by `gap` frames. rtl runs
     right to left (the panels mirror). Pass panels (elements) or colors (panels are made in host). X = x of the leading panel per frame
     (ltr). Returns { start, end, swapAt }: the leading panel covers the frame at swapAt, so put the scene swap there. */
  whip(tl, { at, panels = null, colors = null, host = "#stage", X = [-2300, -1850, -1200, -400, 600, 1150], width = 1900, slant = 220, gap = 1, rtl = false, z = 60, stageW = TOKENS.W } = {}) {
    let els = panels ? arr(panels) : [];
    if (!els.length && colors) els = colors.map((c) => mk("div", "mo-wp", { position: "absolute", left: "0", top: "0", height: TOKENS.H + "px", zIndex: String(z), background: c }, arr(host)[0]));
    const xs = X.map((x) => (rtl ? stageW - width - x : x));
    const poly = rtl ? `polygon(calc(100% - ${slant}px) 0, 0 0, ${slant}px 100%, 100% 100%)` : `polygon(${slant}px 0, 100% 0, calc(100% - ${slant}px) 100%, 0 100%)`;
    els.forEach((el, i) => {
      el.style.width = width + "px"; el.style.clipPath = poly; allowAll(el);
      gs().set(el, { x: xs[0], xPercent: 0 });
      const t0 = at + i * gap * FR;
      tl.set(el, { x: xs[0] }, t0);
      tl.to(el, { keyframes: xs.slice(1).map((x) => ({ x, duration: FR, ease: "none" })) }, t0);
      tl.set(el, { x: xs[0] }, t0 + (xs.length - 1) * FR + FR);
    });
    let k = X.findIndex((x) => x >= stageW - width + slant && x <= -slant);
    if (k < 0) k = Math.floor(X.length / 2);
    return { start: at, end: at + ((els.length - 1) * gap + X.length - 1) * FR, swapAt: at + k * FR, panels: els };
  },
};

/* ---- M.split: a two-pane split on ONE beat. a = the page (YOU SEE), b = the tree (AGENT READS). ltr: a left, b right; rtl mirrors
   (page right, tree left). Panes open from their outer edges toward the divider, which drops; content is laid out by the post. ---- */
export const split = {
  make(host, { rtl = false, top = 108, height = 1060, width = TOKENS.W, ratio = 0.4, divider = 6, ids = { a: "pane-a", b: "pane-b", div: "pane-div" } } = {}) {
    host = arr(host)[0];
    const aW = Math.round(width * ratio - divider / 2), bW = width - aW - divider;
    const aX = rtl ? width - aW : 0, bX = rtl ? 0 : aW + divider, dX = rtl ? bW : aW;
    const pane = (id, x, w) => { const e = mk("div", "mo-pane", { position: "absolute", left: x + "px", top: top + "px", width: w + "px", height: height + "px", overflow: "hidden", zIndex: "10" }, host); e.id = id; allowAll(e); return e; };
    const a = pane(ids.a, aX, aW), b = pane(ids.b, bX, bW);
    const div = mk("div", "mo-div", { position: "absolute", left: dX + "px", top: top + "px", width: divider + "px", height: height + "px", background: "var(--c-ink, #000)", transformOrigin: "50% 0", zIndex: "11" }, host);
    div.id = ids.div; allowAll(div);
    gs().set(a, { clipPath: split.closed("a", rtl) }); gs().set(b, { clipPath: split.closed("b", rtl) }); gs().set(div, { scaleY: 0 });
    return { a, b, div, rtl, geo: { aX, aW, bX, bW, dX, top, height, divider } };
  },
  closed: (side, rtl) => ((side === "a") === !rtl ? "inset(0px 100% 0px 0px)" : "inset(0px 0px 0px 100%)"),
  open(tl, { a, b, div, rtl = false, at = 0, dur = 0.48 } = {}) {
    tl.fromTo(a, { clipPath: split.closed("a", rtl) }, { clipPath: "inset(0px 0% 0px 0%)", duration: dur, ease: type.ease.stop, immediateRender: false }, at);
    tl.fromTo(b, { clipPath: split.closed("b", rtl) }, { clipPath: "inset(0px 0% 0px 0%)", duration: dur, ease: type.ease.stop, immediateRender: false }, at);
    tl.fromTo(div, { scaleY: 0 }, { scaleY: 1, duration: dur * 0.75, ease: type.ease.light, immediateRender: false }, at);
    return at + dur;
  },
  close(tl, { a, b, div, rtl = false, at = 0, dur = 0.4 } = {}) {
    tl.fromTo(a, { clipPath: "inset(0px 0% 0px 0%)" }, { clipPath: split.closed("a", rtl), duration: dur, ease: type.ease.out, immediateRender: false }, at);
    tl.fromTo(b, { clipPath: "inset(0px 0% 0px 0%)" }, { clipPath: split.closed("b", rtl), duration: dur, ease: type.ease.out, immediateRender: false }, at);
    tl.fromTo(div, { scaleY: 1 }, { scaleY: 0, duration: dur * 0.6, ease: "power2.in", immediateRender: false }, at + dur * 0.4);
    return at + dur;
  },
};

/* ---- M.poster: frame 0 is a FINISHED poster (the whole hook readable at a 400 px thumbnail, nothing masked or blank). The words are
   visible at rest, leave through their masks, and come back before the seam, so the loop returns to the poster. ---- */
export const poster = {
  loop(tl, words, { leaveAt, restoreAt, leaveGap = FR, leaveDur = 0.24, restoreGap = 0.05, restoreDur = 0.5, weights = null } = {}) {
    const leaveEnd = type.exitWords(tl, words, { at: leaveAt, gap: leaveGap, dur: leaveDur });
    const restoreEnd = type.enterWords(tl, words, { at: restoreAt, gap: restoreGap, dur: restoreDur, weights });
    return { leaveEnd, restoreEnd };
  },
  /* after loop.register: frame 0 must show every poster element (yPercent 0, opacity 1, scale > 0) and frame D must equal it.
     Returns a list of problems (empty = ok). */
  check(tl, els, { D, props = ["yPercent", "opacity", "scale", "x", "y"], tol = 0.5 } = {}) {
    const list = arr(els), bad = [], read = () => list.map((e) => props.map((p) => gs().getProperty(e, p)));
    tl.seek(0); const a = read(); tl.seek(D); const z = read(); tl.seek(0);
    list.forEach((e, i) => {
      const nm = e.id || (e.textContent || "").slice(0, 12), yp = a[i][0], op = a[i][1], sc = a[i][2];
      if (Math.abs(yp) > tol) bad.push("poster: '" + nm + "' is masked at frame 0 (yPercent " + yp + ")");
      if (op < 0.99 || sc < 0.01) bad.push("poster: '" + nm + "' is faded or collapsed at frame 0");
      props.forEach((p, j) => { if (Math.abs(a[i][j] - z[i][j]) > tol * (p === "opacity" || p === "scale" ? 0.01 : 1)) bad.push("poster: '" + nm + "' " + p + " differs between frame 0 (" + a[i][j] + ") and frame D (" + z[i][j] + ")"); });
    });
    return bad;
  },
};

registerEases();

export default { TOKENS, EASE, ease, WEIGHT, bezier, spring, rng, hash, periodic, sample, color, light, hand, story,
  onsets, flash, pulseAlong, pulseTrain, typewriter, focus, stateChange, counter, overlap, loop, objects, life,
  grid, type, cut, split, poster };
