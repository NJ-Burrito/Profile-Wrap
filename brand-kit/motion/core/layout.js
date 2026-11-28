/* core/layout.js - Section 19a (v4): beat grid and word-mask type. Part of core.js (split by section, pure move). */
import { TOKENS, arr, gs, mk, sample } from "./base.js";
import { bezier, ease } from "./ease.js";

/* ================================================================== 19. STANDARD v4 (council 2026-10-16): grid, type, cut, split, poster
   All deterministic and seek-safe: explicit fromTo states, per-frame sampled clip-paths, no random, no tween-time DOM measuring.
   Times are seconds; use grid.f(frames) / U(...) to land on whole frames. Every directional helper takes rtl (Arabic: strikes and
   whips run right to left, the split mirrors, masks get extra headroom, no letter-spacing, words only). */
export const FR = 1 / TOKENS.FPS;
const ALLOW = ["overlap", "occlusion", "overflow", "escape"];
export const allowAll = (e) => ALLOW.forEach((a) => e.setAttribute("data-layout-allow-" + a, "true"));
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
