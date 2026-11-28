/* core/effects.js - Sections 10-14: connector pulse, typewriter, focus pull, state colour, counter. Part of core.js (split by section, pure move). */
import { NS, arr, gs, mk, rng } from "./base.js";
import { color } from "./color.js";
import { ease } from "./ease.js";
import { flash } from "./onsets.js";

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
