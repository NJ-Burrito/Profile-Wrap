/* core/shots.js - Section 19b (v4): cut, split, poster. Part of core.js (split by section, pure move). */
import { TOKENS, arr, clamp, gs, mk, sample } from "./base.js";
import { bezier, ease } from "./ease.js";
import { FR, allowAll, type } from "./layout.js";

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
