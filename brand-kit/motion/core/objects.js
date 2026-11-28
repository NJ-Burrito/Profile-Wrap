/* core/objects.js - Section 17: objects (the cast) and their idle life. Part of core.js (split by section, pure move). */
import { SVG as OBJ_SVG } from "../objects.data.js";
import { allow, arr, gs, rng, sample } from "./base.js";
import { ease } from "./ease.js";

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
