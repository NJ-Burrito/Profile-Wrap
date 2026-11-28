/* core/color.js - Section 1: colour script, contrast and mixing helpers. Part of core.js (split by section, pure move). */
import { allow, arr, clamp, gs, mk } from "./base.js";

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
