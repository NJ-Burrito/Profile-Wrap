/* motion.legacy.js - OPTIONAL module (off by default). Camera 2D, CSS-3D depth, ambient layers and bokeh were retired for
   posts by the Standard v4 council (size, nausea). They stay here so older projects can still upgrade.
   Import it only from a project that needs it:  import * as Legacy from "./motion.legacy.js"; */
import { allow, TAU, gs, arr, NS, clamp, TOKENS, rng, hash, periodic, sample, ease, EASE, WEIGHT, bezier, spring, color, light, hand, hex2rgb, rgb2hex, relLum, contrast, mix, ensure, onColor } from "./core.js";
/* ================================================================== 3. AMBIENT (back layer, never the subject)
   Every helper takes env(absTime) -> 0..1 from story.plan().calm so the world can hold its breath at tension. */
export const ambient = {
  /* Soft light blobs / gradient washes orbiting on closed loops. targets = elements (blobs). */
  drift(tl, targets, { at = 0, duration, seed = 1, ampX = 60, ampY = 40, ampScale = 0.06, minCycles = 1, maxCycles = 2, step = 0.1, env = null } = {}) {
    track(tl, targets, {
      at, duration, step, init: { scale: 1 },
      fns: (i) => ({
        x: withEnv(periodic(hash(seed) + i * 7 + 1, { amp: ampX, minCycles, maxCycles }), env, at, duration),
        y: withEnv(periodic(hash(seed) + i * 7 + 2, { amp: ampY, minCycles, maxCycles }), env, at, duration),
        scale: (() => { const f = withEnv(periodic(hash(seed) + i * 7 + 3, { amp: ampScale, minCycles, maxCycles }), env, at, duration); return (u) => 1 + f(u); })(),
      }),
    });
  },

  /* Layers = [{ el, depth }]; nearer (bigger depth) moves more. Closed loop. (2D; real parallax is in `depth`.) */
  parallax(tl, layers, { at = 0, duration, amp = 14, seed = 5, minCycles = 1, maxCycles = 2, step = 0.1, env = null } = {}) {
    layers.forEach((L, i) => {
      const d = L.depth ?? 1;
      track(tl, L.el, {
        at, duration, step,
        fns: {
          x: withEnv(periodic(hash(seed) + i * 5 + 1, { amp: amp * d, minCycles, maxCycles }), env, at, duration),
          y: withEnv(periodic(hash(seed) + i * 5 + 2, { amp: amp * d * 0.7, minCycles, maxCycles }), env, at, duration),
        },
      });
    });
  },

  /* A light band crossing the frame, wrapped so the loop is seamless. el = a .mo-sweep element. */
  sweep(tl, el, { at = 0, duration, from = -700, to = 1800, phase = 0, laps = 1, skew = -14, opacity = 1 } = {}) {
    gs().set(el, { skewX: skew, opacity });
    wrapTravel(tl, el, "x", from, to, { at, duration, phase, laps });
  },

  /* Dust / bokeh specks on closed orbits. Creates the elements inside `container`.
     exclude = [x, y, w, h] keeps specks out of a reading area. Returns the created elements. */
  motes(tl, container, { at = 0, duration, count = 24, seed = 3, w = TOKENS.W, h = TOKENS.H, size = [3, 8], orbit = [10, 46],
    alpha = [0.18, 0.5], depth = 1, color: col, blur = 0, exclude = null, minCycles = 1, maxCycles = 3, step = 0.1, cls = "mo-mote", env = null, z = null } = {}) {
    const r = rng(seed), out = [];
    container = arr(container)[0];
    for (let i = 0; i < count; i++) {
      let x, y, tries = 0;
      do { x = r.range(0, w); y = r.range(0, h); tries++; }
      while (exclude && tries < 40 && x > exclude[0] && x < exclude[0] + exclude[2] && y > exclude[1] && y < exclude[1] + exclude[3]);
      const s = r.range(size[0], size[1]) * depth;
      const el = mk("i", cls, { left: x + "px", top: y + "px", width: s + "px", height: s + "px" }, container);
      if (col) el.style.background = col;
      if (blur) el.style.filter = `blur(${blur}px)`;
      if (z !== null) gs().set(el, { z: Array.isArray(z) ? r.range(z[0], z[1]) : z });
      const o = r.range(orbit[0], orbit[1]) * depth, base = r.range(alpha[0], alpha[1]), tw = base * 0.6;
      out.push(el);
      track(tl, el, {
        at, duration, step,
        fns: {
          x: withEnv(periodic(hash(seed) + i * 11 + 1, { amp: o, minCycles, maxCycles, terms: 2 }), env, at, duration),
          y: withEnv(periodic(hash(seed) + i * 11 + 2, { amp: o, minCycles, maxCycles, terms: 2 }), env, at, duration),
          opacity: (() => { const f = periodic(hash(seed) + i * 11 + 3, { amp: tw, minCycles: 1, maxCycles: 4, terms: 2 }); return (u) => Math.max(0, base + f(u)); })(),
        },
      });
    }
    return out;
  },

  /* Film grain: a seeded noise tile whose offset jumps `fps` times a second. Keep alpha <= 0.04 for GIF
     output (the 256-colour palette turns stronger grain into banding and bloats the file). */
  grain(tl, el, { at = 0, duration, seed = 9, size = 160, alpha = 0.035, fps = 8 } = {}) {
    const r = rng(seed), c = document.createElement("canvas");
    c.width = c.height = size;
    const ctx = c.getContext("2d"), img = ctx.createImageData(size, size);
    for (let i = 0; i < size * size; i++) {
      const v = Math.floor(r.next() * 256);
      img.data[i * 4] = img.data[i * 4 + 1] = img.data[i * 4 + 2] = v;
      img.data[i * 4 + 3] = 255;
    }
    ctx.putImageData(img, 0, 0);
    el.style.backgroundImage = `url(${c.toDataURL("image/png")})`;
    el.style.backgroundSize = size + "px " + size + "px";
    el.style.opacity = String(alpha);
    const n = Math.floor(duration * fps);
    for (let i = 0; i < n; i++) tl.set(el, { backgroundPosition: `${r.int(0, size)}px ${r.int(0, size)}px` }, at + i / fps);
  },
};

/* ================================================================== 4. CAMERA 2D (applied to wrappers / layers) */
function pose(k, d, origin) {
  const s = 1 + (k.scale - 1) * d, a = k.aim || origin, f = k.follow ?? 1;
  return { scale: s, x: -(s - 1) * (a[0] - origin[0]) * f, y: -(s - 1) * (a[1] - origin[1]) * f };
}

export const camera = {
  /* Generic path. keys = [{ t, scale, aim:[x,y], follow:0..1, ease }] with t relative to `at`.
     targets may be several layers; depths[i] scales how far layer i moves (parallax from the camera). */
  move(tl, targets, keys, { at = 0, origin = [TOKENS.W / 2, TOKENS.H / 2], depths = null } = {}) {
    const els = arr(targets);
    els.forEach((el, j) => {
      const d = depths ? depths[j] : 1;
      gs().set(el, { transformOrigin: `${origin[0]}px ${origin[1]}px` });
      tl.set(el, pose(keys[0], d, origin), at + keys[0].t);
      for (let i = 1; i < keys.length; i++) {
        const a = keys[i - 1], b = keys[i];
        tl.fromTo(el, pose(a, d, origin), { ...pose(b, d, origin), duration: b.t - a.t, ease: b.ease || "sine.inOut", immediateRender: false }, at + a.t);
      }
    });
  },
  pushIn(tl, targets, { at = 0, duration = 4, from = 1, to = 1.04, aim = null, follow = 0.5, ease: e = "sine.inOut", origin, depths } = {}) {
    camera.move(tl, targets, [{ t: 0, scale: from }, { t: duration, scale: to, aim, follow, ease: e }], { at, origin, depths });
  },
  punch(tl, targets, { at = 0, base = 1, to = 1.1, aim = null, follow = 0.6, anticipate = 0.12, inDur = 0.26, hold = 0.5, outDur = 0.9, origin, depths } = {}) {
    const a = anticipate, keys = [{ t: 0, scale: base, aim, follow }];
    if (a > 0) keys.push({ t: a, scale: base - 0.012, aim, follow, ease: "power2.out" });
    keys.push({ t: a + inDur, scale: to, aim, follow, ease: ease.snap });
    keys.push({ t: a + inDur + hold, scale: to, aim, follow, ease: "none" });
    keys.push({ t: a + inDur + hold + outDur, scale: base, aim: null, ease: "sine.inOut" });
    camera.move(tl, targets, keys, { at, origin, depths });
    return a + inDur + hold + outDur;
  },
  settle(tl, targets, { at = 0, duration = 0.9, from = 1.04, aim = null, ease: e = "sine.inOut", origin, depths } = {}) {
    camera.move(tl, targets, [{ t: 0, scale: from, aim }, { t: duration, scale: 1, aim: null, ease: e }], { at, origin, depths });
  },
  /* Small seeded handheld drift. Put it on a PARENT of the element that carries the camera path. Exact loop. */
  handheld(tl, targets, { at = 0, duration, amp = 3, rot = 0.12, seed = 7, minCycles = 2, maxCycles = 5, step = 0.08, origin = [TOKENS.W / 2, TOKENS.H / 2], env = null } = {}) {
    arr(targets).forEach((el) => gs().set(el, { transformOrigin: `${origin[0]}px ${origin[1]}px` }));
    track(tl, targets, {
      at, duration, step,
      fns: (i) => ({
        x: withEnv(periodic(hash(seed) + i * 3 + 1, { amp, minCycles, maxCycles }), env, at, duration),
        y: withEnv(periodic(hash(seed) + i * 3 + 2, { amp: amp * 0.8, minCycles, maxCycles }), env, at, duration),
        rotation: withEnv(periodic(hash(seed) + i * 3 + 3, { amp: rot, minCycles, maxCycles }), env, at, duration),
      }),
    });
  },
};

/* ================================================================== 5. DEPTH (CSS 3D: perspective, orbit, layers, DOF, parallax)
   Structure:  #stage (perspective)  >  #world (preserve-3d, the camera moves THIS)  >  layers (preserve-3d)  >  objects with z.
   Rules: no opacity<1, filter, clip or overflow on any ancestor of 3D objects (each flattens the 3D context);
   put those on leaf objects only. Objects at z < 0 are smaller: depth.layer() compensates scale. */
const KEYMAP = { ry: "rotationY", rx: "rotationX", rz: "rotation" };
export const depth = {
  P: 1500,
  origin: [TOKENS.W / 2, TOKENS.H / 2],

  /* Layout centre that PROJECTS to screen point (sx, sy) for an object at depth z. Use it to put a fragment exactly where
     you want it on screen: perspective pulls far objects toward the vanishing point. */
  at(sx, sy, z) {
    const f = (depth.P - z) / depth.P, o = depth.origin;
    return [o[0] + (sx - o[0]) * f, o[1] + (sy - o[1]) * f];
  },

  /* Make the stage a 3D camera. world = the single child that the camera moves. */
  rig(stage, world, { perspective = 1500, origin = [TOKENS.W / 2, TOKENS.H / 2] } = {}) {
    depth.P = perspective; depth.origin = origin;
    const st = arr(stage)[0];
    st.style.perspective = perspective + "px";
    st.style.perspectiveOrigin = `${origin[0]}px ${origin[1]}px`;
    arr(world).forEach((w) => { w.style.transformStyle = "preserve-3d"; gs().set(w, { transformOrigin: `${origin[0]}px ${origin[1]}px 0px` }); });
    document.querySelectorAll(".mo3d").forEach((e) => { e.style.transformStyle = "preserve-3d"; });
  },

  /* Place an element at depth z (positive = toward the viewer). Scale compensates so layout positions still read true. */
  place(el, z = 0, { compensate = true, ...rest } = {}) {
    const k = compensate ? (depth.P - z) / depth.P : 1;
    gs().set(el, { z, scale: k, ...rest });
    return k;
  },

  /* depth-of-field: blur radius in px for an object at z when the focus plane is focusZ */
  dof(z, focusZ = 0, { perUnit = 0.0095, max = 14, free = 40 } = {}) {
    const d = Math.max(0, Math.abs(z - focusZ) - free);
    return Math.min(max, +(d * perUnit).toFixed(2));
  },

  /* Camera orbit / dolly on the world. keys = [{ t, ry, rx, rz, z, x, y, scale, ease }], t relative to `at`.
     Missing channels carry over from the previous key. First and last key identical = loop-exact. */
  orbit(tl, world, keys, { at = 0 } = {}) {
    const norm = keys.map((k) => { const o = { t: k.t, ease: k.ease }; for (const p in k) { if (p === "t" || p === "ease") continue; o[KEYMAP[p] || p] = k[p]; } return o; });
    const ch = new Set(); norm.forEach((k) => Object.keys(k).forEach((p) => { if (p !== "t" && p !== "ease") ch.add(p); }));
    const state = {}; ch.forEach((p) => { state[p] = norm[0][p] ?? 0; });
    const poses = norm.map((k) => { ch.forEach((p) => { if (k[p] !== undefined) state[p] = k[p]; }); return { ...state }; });
    arr(world).forEach((w) => {
      tl.set(w, poses[0], at + norm[0].t);
      for (let i = 1; i < norm.length; i++) {
        const dt = norm[i].t - norm[i - 1].t;
        if (dt <= 0) { tl.set(w, poses[i], at + norm[i].t); continue; }
        tl.fromTo(w, poses[i - 1], { ...poses[i], duration: dt, ease: norm[i].ease || ease.soft, immediateRender: false }, at + norm[i - 1].t);
      }
    });
  },

  /* Floating UI fragments in depth: shapes only (no text), partially hidden behind the hero, tumbling a little,
     blurred by distance. Creates elements in `container` (a .mo3d layer). Returns them. */
  fragments(tl, container, { at = 0, duration, count = 9, seed = "frag", zRange = [-900, -260], area = [0, 0, TOKENS.W, TOKENS.H],
    roles = ["ambient", "system", "hero"], strong = 0, focusZ = 0, minCycles = 1, maxCycles = 2, step = 0.1, env = null, tumble = 11,
    spots = null, zs = null, kinds: kindList = null } = {}) {
    const r = rng(seed), out = [];
    container = arr(container)[0];
    const kinds = kindList || ["pill", "node", "tag", "bracket", "bars"];
    for (let i = 0; i < count; i++) {
      const kind = kinds[i % kinds.length], role = i < strong ? "hero" : roles[r.int(0, roles.length - 1)];
      const z = zs ? zs[i % zs.length] : r.range(zRange[0], zRange[1]);
      const sp = spots ? spots[i % spots.length] : [r.range(area[0], area[0] + area[2]), r.range(area[1], area[1] + area[3])];
      const col = `var(--c-${role}, #888)`;
      const el = mk("div", "mo-frag mo-" + kind, { left: "0px", top: "0px", borderColor: col, color: col }, container);
      allow(el);
      el.setAttribute("aria-hidden", "true");
      if (kind === "pill") { el.style.width = r.int(210, 300) + "px"; el.style.height = "62px"; mk("i", "", { background: col }, el); mk("b", "", { background: col }, el); }
      if (kind === "node") { const s = r.int(54, 84); el.style.width = el.style.height = s + "px"; mk("i", "", { background: col }, el); }
      if (kind === "tag") { el.style.width = r.int(170, 230) + "px"; el.style.height = r.int(110, 150) + "px"; mk("b", "", { background: col }, el); mk("b", "", { background: col }, el); mk("b", "", { background: col }, el); }
      if (kind === "bracket") { el.style.width = r.int(120, 170) + "px"; el.style.height = r.int(110, 170) + "px"; }
      if (kind === "bars") { el.style.width = r.int(150, 210) + "px"; el.style.height = "92px"; mk("b", "", { background: col }, el); mk("b", "", { background: col }, el); }
      const k = (depth.P - z) / depth.P, blur = depth.dof(z, focusZ);
      const [cx, cy] = depth.at(sp[0], sp[1], z);
      el.style.left = cx - parseFloat(el.style.width) / 2 + "px"; el.style.top = cy - parseFloat(el.style.height) / 2 + "px";
      if (blur > 0.3) el.style.filter = `blur(${blur}px)`;
      const base = { z, scale: k, opacity: clamp(0.78 - Math.abs(z) * 0.00045, 0.28, 0.8) };
      out.push(el);
      const a = r.range(18, 46) * (1 - z / 1200), fx = hash(seed) + i * 13;
      track(tl, el, {
        at, duration, step, init: base,
        fns: {
          x: withEnv(periodic(fx + 1, { amp: a, minCycles, maxCycles, terms: 2 }), env, at, duration),
          y: withEnv(periodic(fx + 2, { amp: a * 0.8, minCycles, maxCycles, terms: 2 }), env, at, duration),
          rotationY: withEnv(periodic(fx + 3, { amp: tumble, minCycles, maxCycles, terms: 2 }), env, at, duration),
          rotationX: withEnv(periodic(fx + 4, { amp: tumble * 0.6, minCycles, maxCycles, terms: 2 }), env, at, duration),
          rotation: withEnv(periodic(fx + 5, { amp: 4, minCycles, maxCycles, terms: 2 }), env, at, duration),
        },
      });
    }
    return out;
  },

  /* A big out-of-focus disc that passes near the lens (z > 0, heavily blurred). Opacity is 0 before and after,
     so it never touches the loop seam. role = palette role for its colour. */
  pass(tl, container, { at = 0, duration = 1.2, from = [-200, 900], to = [1300, 560], z = 700, size = 200, role = "hero", alpha = 0.22, blur = 16, ease: e = ease.soft, rise = 0.3 } = {}) {
    container = arr(container)[0];
    const el = mk("i", "mo-bokeh", { left: -size / 2 + "px", top: -size / 2 + "px", width: size + "px", height: size + "px",
      background: `radial-gradient(closest-side, var(--c-${role}, #fff), color-mix(in srgb, var(--c-${role}, #fff) 40%, transparent) 70%, transparent)`, filter: `blur(${blur}px)` }, container);
    allow(el);
    gs().set(el, { x: from[0], y: from[1], z, scale: (depth.P - z) / depth.P, opacity: 0 });
    tl.fromTo(el, { x: from[0], y: from[1] }, { x: to[0], y: to[1], duration, ease: e, immediateRender: false }, at);
    tl.fromTo(el, { opacity: 0 }, { opacity: alpha, duration: duration * rise, ease: "power1.out", immediateRender: false }, at);
    tl.fromTo(el, { opacity: alpha }, { opacity: 0, duration: duration * rise, ease: "power1.in", immediateRender: false }, at + duration * (1 - rise));
    return el;
  },

  /* Slow bokeh discs near the lens on closed orbits (parallax with the orbit). */
  bokeh(tl, container, { at = 0, duration, count = 4, seed = "bokeh", z = [380, 760], size = [90, 170], alpha = [0.08, 0.18], roles = ["hero", "accent"],
    blur = 12, orbit = [26, 70], exclude = null, minCycles = 1, maxCycles = 2, step = 0.1, env = null } = {}) {
    const r = rng(seed), out = [];
    container = arr(container)[0];
    for (let i = 0; i < count; i++) {
      let x, y, tries = 0;
      do { x = r.range(0, TOKENS.W); y = r.range(0, TOKENS.H); tries++; }
      while (exclude && tries < 40 && x > exclude[0] && x < exclude[0] + exclude[2] && y > exclude[1] && y < exclude[1] + exclude[3]);
      const zz = r.range(z[0], z[1]), s = r.range(size[0], size[1]), role = roles[i % roles.length], a = r.range(alpha[0], alpha[1]);
      const el = mk("i", "mo-bokeh", { left: x - s / 2 + "px", top: y - s / 2 + "px", width: s + "px", height: s + "px",
        background: `radial-gradient(closest-side, var(--c-${role}, #fff), color-mix(in srgb, var(--c-${role}, #fff) 40%, transparent) 70%, transparent)`, filter: `blur(${blur}px)` }, container);
      allow(el); out.push(el);
      const o = r.range(orbit[0], orbit[1]), fx = hash(seed) + i * 17;
      track(tl, el, { at, duration, step, init: { z: zz, scale: (depth.P - zz) / depth.P, opacity: a },
        fns: { x: withEnv(periodic(fx + 1, { amp: o, minCycles, maxCycles, terms: 2 }), env, at, duration), y: withEnv(periodic(fx + 2, { amp: o * 0.7, minCycles, maxCycles, terms: 2 }), env, at, duration) } });
    }
    return out;
  },
};

export default { ambient, camera, depth };
