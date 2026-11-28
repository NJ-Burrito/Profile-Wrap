/* core/light.js - Section 6: light source the scene responds to. Part of core.js (split by section, pure move). */
import { NS, TOKENS, allow, arr, clamp, gs, hash, mk, sample } from "./base.js";
import { ease } from "./ease.js";

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
