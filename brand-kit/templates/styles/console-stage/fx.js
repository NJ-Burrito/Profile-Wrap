/* PWFX: the console-stage effects kit. Deterministic VFX and the sound cue log, all on the ONE paused timeline.
   Rules (docs/MOTION.md): seeded noise only (no Math.random, Date, performance.now), finite tweens (no repeat:-1), explicit start
   states, at most one flash a film and never red, every effect cleans itself up (ends invisible) so a seek anywhere is exact.
   Colours come from the theme variables (theme.css), never from this file. Each effect that has a sound logs a cue
   (role, t, db) into fx.cues; the composition publishes them as window.__probe.sfx and profile-wrap mixes them (sfx/*.wav). */
(function () {
  const rgbOf = (cssVar) => {                       // "#rrggbb" from a theme variable -> "r,g,b"
    const v = getComputedStyle(document.documentElement).getPropertyValue(cssVar).trim();
    const m = /^#([0-9a-f]{6})$/i.exec(v);
    if (!m) return "255,255,255";
    return [0, 2, 4].map((i) => parseInt(m[1].slice(i, i + 2), 16)).join(",");
  };

  window.PWFX = function (o) {
    const { tl, seeded } = o;
    const layer = o.layer;                           // a position:absolute container on top of the scenes
    const cues = [];
    const fx = { cues };
    let uid = 0;
    const mk = (cls, css, parent) => {
      const e = document.createElement("div");
      e.id = "fx" + uid++;
      e.className = "fxp " + (cls || "");
      Object.assign(e.style, css || {});
      (parent || layer).appendChild(e);
      return e;
    };
    const rnd = (seed) => seeded(seed || 1);

    /* ---- sound cue log ---- */
    fx.cue = (role, t, db) => { cues.push({ role, t: Math.round(t * 1000) / 1000, db: db || 0 }); };

    /* ---- ripple: an expanding ring (water, a click, a landing) ---- */
    fx.ripple = (x, y, at, p) => {
      p = p || {};
      const r = p.r || 150, w = p.w || 3, col = p.color || "var(--c-accent)", dur = p.dur || 0.9;
      const e = mk("", { left: x - r + "px", top: y - r + "px", width: 2 * r + "px", height: 2 * r + "px", borderRadius: "50%",
        border: w + "px solid " + col, opacity: 0 });
      tl.fromTo(e, { scale: 0.08, opacity: 0.9 }, { scale: 1, opacity: 0, duration: dur, ease: "power2.out", immediateRender: false }, at);
      return e;
    };

    /* ---- burst: splash particles that fly up and fall under gravity ---- */
    fx.burst = (x, y, at, p) => {
      p = p || {};
      const n = p.n || 14, spread = p.spread || 240, rise = p.rise || 220, col = p.color || "var(--c-accent)", r = rnd(p.seed || 3);
      for (let i = 0; i < n; i++) {
        const sz = 5 + Math.round(r() * 8), dx = (r() - 0.5) * 2 * spread, up = rise * (0.45 + 0.55 * r()), d = 0.55 + 0.35 * r();
        const e = mk("", { left: x - sz / 2 + "px", top: y - sz / 2 + "px", width: sz + "px", height: sz + "px", borderRadius: "50%", background: col, opacity: 0 });
        tl.fromTo(e, { opacity: 1, x: 0 }, { x: dx, duration: d, ease: "none", immediateRender: false }, at);
        tl.fromTo(e, { y: 0 }, { y: -up, duration: d * 0.42, ease: "power2.out", immediateRender: false }, at);
        tl.to(e, { y: up * 0.35, duration: d * 0.58, ease: "power2.in", immediateRender: false }, at + d * 0.42);
        tl.to(e, { opacity: 0, duration: d * 0.3, ease: "none", immediateRender: false }, at + d * 0.7);
      }
      if (p.sound !== false) fx.cue(p.sound || "splash", at, p.db === undefined ? -8 : p.db);
    };

    /* ---- bubbles: outlined circles rising with a sway; each can pop (cue) at the top ---- */
    fx.bubbles = (x0, x1, y0, at, p) => {
      p = p || {};
      const n = p.n || 9, rise = p.rise || 420, col = p.color || "var(--c-accent)", r = rnd(p.seed || 5);
      for (let i = 0; i < n; i++) {
        const sz = 12 + Math.round(r() * 22), x = x0 + (x1 - x0) * r(), t0 = at + r() * (p.spread || 1.2), d = 0.9 + 0.8 * r(), sway = (r() - 0.5) * 70;
        const e = mk("", { left: x - sz / 2 + "px", top: y0 - sz / 2 + "px", width: sz + "px", height: sz + "px", borderRadius: "50%", border: "2px solid " + col, opacity: 0 });
        tl.fromTo(e, { opacity: 0, y: 0, x: 0, scale: 0.6 }, { opacity: 0.85, scale: 1, duration: 0.18, ease: "none", immediateRender: false }, t0);
        tl.fromTo(e, { y: 0 }, { y: -rise * (0.6 + 0.4 * r()), duration: d, ease: "power1.out", immediateRender: false }, t0);
        tl.fromTo(e, { x: 0 }, { x: sway, duration: d * 0.5, ease: "sine.inOut", yoyo: true, repeat: 1, immediateRender: false }, t0);
        tl.to(e, { opacity: 0, duration: 0.14, ease: "none", immediateRender: false }, t0 + d - 0.12);
        if (p.pops && i < p.pops) fx.cue("pop", t0 + d - 0.1, -14);
      }
    };

    /* ---- pulse: a glow pulse on an accent element (drop-shadow breathes out and back, scale 1 to 1.05 to 1) ---- */
    fx.pulse = (sel, at, p) => {
      p = p || {};
      const rgb = rgbOf(p.cssVar || "--c-accent"), d = p.dur || 0.8, px = p.px || 26;
      tl.fromTo(sel, { filter: `drop-shadow(0 0 0px rgba(${rgb},0))`, scale: 1 },
        { filter: `drop-shadow(0 0 ${px}px rgba(${rgb},0.85))`, scale: 1.05, duration: d * 0.4, ease: "power2.out", immediateRender: false }, at);
      tl.to(sel, { filter: `drop-shadow(0 0 0px rgba(${rgb},0))`, scale: 1, duration: d * 0.6, ease: "power2.inOut", immediateRender: false }, at + d * 0.4);
    };

    /* ---- shine: a light sweep through text that carries the .shine class ---- */
    fx.shine = (sel, at, dur) => {
      tl.fromTo(sel, { backgroundPosition: "100% 0%" }, { backgroundPosition: "0% 0%", duration: dur || 0.9, ease: "power1.inOut", immediateRender: false }, at);
    };

    /* ---- shake: a short seeded camera shake on a wrapper (heavy hits only); lands back at rest ---- */
    fx.shake = (sel, at, p) => {
      p = p || {};
      const dur = p.dur || 0.4, amp = p.amp || 9, step = 1 / 30, steps = Math.round(dur / step), r = rnd(p.seed || 9);
      for (let i = 0; i < steps; i++) {
        const k = 1 - i / steps;
        tl.set(sel, { x: Math.round((r() - 0.5) * 2 * amp * k), y: Math.round((r() - 0.5) * 2 * amp * k * 0.7), rotation: (r() - 0.5) * 0.8 * k }, at + i * step);
      }
      tl.set(sel, { x: 0, y: 0, rotation: 0 }, at + steps * step);
      if (p.sound !== false) fx.cue(p.sound || "thump", at, p.db === undefined ? -4 : p.db);
    };

    /* ---- count: a number that runs from one value to another (the tween is a proxy object, so a seek is exact) ---- */
    fx.count = (sel, from, to, at, dur, p) => {
      p = p || {};
      const dec = p.dec === undefined ? 1 : p.dec, unit = p.unit || "", el = document.querySelector(sel), proxy = { v: from };
      const show = () => { el.textContent = proxy.v.toFixed(dec) + unit; };
      show();
      tl.fromTo(proxy, { v: from }, { v: to, duration: dur, ease: p.ease || "power2.out", onUpdate: show, immediateRender: false }, at);
      tl.call(() => { proxy.v = to; show(); }, null, at + dur + 0.001);
    };

    /* ---- sparkles: small four-point stars that pop and fade around a point (a number landing) ---- */
    fx.sparkles = (x, y, at, p) => {
      p = p || {};
      const n = p.n || 8, rad = p.radius || 110, col = p.color || "var(--c-ok)", r = rnd(p.seed || 7);
      for (let i = 0; i < n; i++) {
        const a = (i / n) * Math.PI * 2 + r() * 0.5, d = rad * (0.6 + 0.6 * r()), sz = 14 + Math.round(r() * 14), t0 = at + r() * 0.2;
        const e = mk("", { left: x - sz / 2 + "px", top: y - sz / 2 + "px", width: sz + "px", height: sz + "px", opacity: 0, color: col });
        e.innerHTML = '<svg viewBox="0 0 24 24" width="100%" height="100%"><path d="M12 0 L14.5 9.5 L24 12 L14.5 14.5 L12 24 L9.5 14.5 L0 12 L9.5 9.5 Z" fill="currentColor"/></svg>';
        tl.fromTo(e, { opacity: 1, scale: 0.2, x: 0, y: 0, rotation: 0 }, { scale: 1, x: Math.cos(a) * d, y: Math.sin(a) * d, rotation: 90, duration: 0.5, ease: "power2.out", immediateRender: false }, t0);
        tl.to(e, { opacity: 0, scale: 0.3, duration: 0.3, ease: "none", immediateRender: false }, t0 + 0.4);
      }
      if (p.sound !== false) fx.cue(p.sound || "sparkle", at, p.db === undefined ? -10 : p.db);
    };

    /* ---- drain: a swirl that spins up while it shrinks into its centre (the motif's "empty" move) ---- */
    fx.drain = (sel, at, dur, p) => {
      p = p || {};
      tl.fromTo(sel, { rotation: 0, scale: 1, opacity: 1 }, { rotation: p.turns ? p.turns * 360 : 540, scale: 0.06, duration: dur, ease: "power2.in", immediateRender: false }, at);
      tl.to(sel, { opacity: 0, duration: 0.15, ease: "none", immediateRender: false }, at + dur - 0.1);
    };

    return fx;
  };
})();
