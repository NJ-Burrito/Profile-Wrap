/* core/onsets.js - Section 9: micro-onsets. Part of core.js (split by section, pure move). */
import { arr, gs, mk, rng } from "./base.js";
import { ease } from "./ease.js";
import { life } from "./objects.js";

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
