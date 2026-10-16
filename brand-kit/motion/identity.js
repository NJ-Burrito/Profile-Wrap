/* identity.js - the opt-in identity card (photo, name, role) and its signature beat. MIT.
   Everything personal is read from window.__brand, which YOUR project fills from brand/identity/ (never from this file):
     window.__brand = { identity: { name: "...", role: "...", names: { ar: "..." }, roles: { ar: "..." },
                        photo: "./motion/photo.jpg", signature: { viewBox: [x, y, w, h], strokes: [[id, len, width, "M... C..."], ...] } } };
   The signature data is written by "njli motion signature" (typed or traced) into brand/identity/signature.data.js, which
   assigns window.__brand.identity.signature. This module has no default name, role, photo or stroke.

   identity(tl, { plan | total, at?, where?, lang, accent, root, id, signature?, ... }) -> { el, at, end, problems: [], signature }.
   The card is fixed to the frame (a child of the stage, never of a camera group): bottom-left (Arabic: bottom-right), 40 px from
   the edges, visible from frame 0. Once per loop it grows to 1.25x with a light ring sweep, then settles. Throws if the beat would
   land in the payoff or within 0.5 s of the loop seam. */
import { ease, arr } from "./core.js";

const brand = () => (globalThis.__brand && globalThis.__brand.identity) || {};

/* The signature is drawn stroke by stroke (stroke-dashoffset, pathLength = 1) on a plate beside the card at its peak extent,
   so the two never overlap. It is never mirrored, writes in during the beat and is fully off before the loop seam. */
function signatureBeat(tl, S, { host, card, L, id, t0, D, accent, ink, width, scale, gap, write, fade, seamTail, bold, up, settle, hold: cardHold }) {
  const vb = S.viewBox, problems = [];
  const avail = D - seamTail - t0;
  const wr = Math.min(write, avail - fade - 0.12);
  if (!(wr >= 0.6)) return { el: null, at: t0, end: t0, problems: ["signature skipped: only " + avail.toFixed(2) + " s between the beat start and the loop seam"] };
  const hold = Math.max(0, avail - fade - wr), end = t0 + wr + hold + fade;
  const padX = 18, padY = 7, stageW = host.clientWidth || 1080;
  const plate = document.createElement("div");
  plate.id = id + "-signature"; plate.className = "mo-sig mo-sig-" + L; plate.setAttribute("aria-hidden", "true");
  plate.setAttribute("data-layout-allow-overlap", "true"); plate.setAttribute("data-layout-allow-occlusion", "true");
  Object.assign(plate.style, { position: "absolute", bottom: "40px", zIndex: "50", boxSizing: "border-box", direction: "ltr", pointerEvents: "none",
    opacity: "0", borderRadius: "34px", padding: padY + "px " + padX + "px", color: ink,
    background: "color-mix(in srgb, var(--c-base, #101010) 84%, transparent)" });
  const svgNS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(svgNS, "svg");
  svg.setAttribute("viewBox", vb.join(" ")); svg.setAttribute("fill", "none"); svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-linecap", "round"); svg.setAttribute("stroke-linejoin", "round");
  svg.style.display = "block"; svg.style.overflow = "visible";
  const paths = S.strokes.map(([sid, len, w, d]) => {
    const p = document.createElementNS(svgNS, "path");
    p.setAttribute("d", d); p.setAttribute("pathLength", "1"); p.setAttribute("stroke-width", String(+(w * bold).toFixed(1)));
    const o0 = 1 + ((w * bold) / 2 + 1) / len;           /* start offset: the dash plus its round cap sit fully before the path start */
    p.setAttribute("stroke-dasharray", "1 3"); p.setAttribute("stroke-dashoffset", String(+o0.toFixed(4)));
    if (sid === "swash-main") p.style.stroke = accent;
    svg.appendChild(p);
    return { el: p, len, o0 };
  });
  plate.appendChild(svg); host.appendChild(plate);
  const place = () => {
    const W = card.offsetWidth || (L === "ar" ? 540 : 380);
    const edge = 40 + W + gap;
    let w = width; const room = stageW - (40 + W * scale + gap) - 2 * padX - 16;
    if (w > room) w = Math.max(200, room);
    const h = Math.round(w * vb[3] / vb[2]);
    svg.setAttribute("width", w); svg.setAttribute("height", h);
    plate.style.width = (w + 2 * padX) + "px"; plate.style.height = (h + 2 * padY) + "px";
    plate.style.left = L === "ar" ? "" : edge + "px"; plate.style.right = L === "ar" ? edge + "px" : "";
    return { w, h, edge };
  };
  const geo = place();
  try { if (document.fonts && document.fonts.ready) document.fonts.ready.then(place); } catch (e) { /* placement stays as measured */ }
  const lift = 0.02, total = paths.reduce((a, q) => a + Math.pow(q.len, 0.85), 0), usable = wr - lift * (paths.length - 1);
  let tt = t0 + 0.04; const fadeIn = 0.16;
  tl.fromTo(plate, { opacity: 0 }, { opacity: 1, duration: fadeIn, ease: "sine.out", immediateRender: false }, t0);
  const dx = (L === "ar" ? -1 : 1), shift = () => dx * (card.offsetWidth || (L === "ar" ? 540 : 380)) * (scale - 1);
  tl.fromTo(plate, { x: 0 }, { x: shift, duration: up, ease: ease.overshootSoft, immediateRender: false }, t0);
  tl.fromTo(plate, { x: shift }, { x: 0, duration: settle, ease: ease.heavyDrop, immediateRender: false }, t0 + up + cardHold);
  paths.forEach((q) => {
    const dur = usable * Math.pow(q.len, 0.85) / total;
    tl.fromTo(q.el, { strokeDashoffset: q.o0 }, { strokeDashoffset: 0, duration: dur, ease: q.len > 120 ? ease.soft : "none", immediateRender: false }, tt);
    tt += dur + lift;
  });
  tl.fromTo(plate, { opacity: 1 }, { opacity: 0, duration: fade, ease: "sine.inOut", immediateRender: false }, end - fade);
  return { el: plate, at: t0, end, write: wr, hold, w: geo.w, h: geo.h, problems };
}

export function identity(tl, { root = "#stage", photo = null, lang = "en", name = null, role = null, accent = "var(--c-accent)",
  plan = null, total = null, at = null, where = null, duration = 0.9, scale = 1.25, seamGuard = 0.5, id = "identity",
  signature = true, sigInk = "var(--c-ink, #fff)", sigAccent = null, sigWidth = 280, sigWrite = 1.0, sigFade = 0.25, sigGap = 16, sigBold = 1.5, sigSeamTail = 0.2 } = {}) {
  const host = arr(root)[0];
  if (!host) throw new Error("identity: root '" + root + "' not found");
  const B = brand(), L = lang === "ar" ? "ar" : "en";
  const nm = name || (B.names && B.names[L]) || B.name, rl = role || (B.roles && B.roles[L]) || B.role, ph = photo || B.photo || null;
  if (!nm) throw new Error("identity: no name; set window.__brand.identity.name (or pass { name }). The library names nobody by default.");
  const D = plan ? plan.duration : total;
  if (D == null) throw new Error("identity: pass { plan } or { total } (loop length in seconds)");
  const t0 = at != null ? at : (plan ? plan.phases.release[0] + 0.55 : null);
  if (t0 == null) throw new Error("identity: pass { at } (the beat start) when there is no plan");
  const end = t0 + duration, problems = [];
  /* where: "release" (default with a plan), "hook" (rides the first big word, must end before the hit) or "signoff" (the last beat before the seam). */
  const W = where || (plan ? "release" : "free");
  if (end > D - seamGuard) problems.push("identity beat ends " + end.toFixed(2) + " s: within " + seamGuard + " s of the loop seam (" + D + " s)");
  if (plan && W === "release" && t0 < plan.phases.release[0]) problems.push("identity beat starts at " + t0 + " s, before the release phase (" + plan.phases.release[0] + " s): it would coincide with the payoff");
  if (plan && W !== "hook" && t0 < plan.hit + 0.6) problems.push("identity beat starts within 0.6 s of the payoff hit (" + plan.hit + " s)");
  if (plan && W === "hook" && end > plan.hit - 0.3) problems.push("identity beat (hook) ends " + end.toFixed(2) + " s: within 0.3 s of the hit (" + plan.hit + " s)");
  if (problems.length) throw new Error("identity: " + problems.join("; "));

  const el = document.createElement("div");
  el.id = id; el.className = "mo-id mo-id-" + L; el.setAttribute("lang", L); el.setAttribute("dir", L === "ar" ? "rtl" : "ltr");
  el.style.setProperty("--id-accent", accent);
  el.setAttribute("data-layout-allow-overlap", "true"); el.setAttribute("data-layout-allow-occlusion", "true");
  const esc = (v) => String(v).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/"/g, "&quot;");
  el.innerHTML = '<i class="mo-id-glow"></i><div class="mo-id-photo">' + (ph ? '<img src="' + esc(ph) + '" alt="" width="200" height="200" />' : "") +
    '<i class="mo-id-ring"></i><i class="mo-id-sweep"></i></div>' +
    '<div class="mo-id-text"><b class="mo-id-name">' + esc(nm) + "</b>" + (rl ? '<span class="mo-id-role">' + esc(rl) + "</span>" : "") + "</div>";
  host.appendChild(el);

  const glow = el.querySelector(".mo-id-glow"), sweep = el.querySelector(".mo-id-sweep");
  const up = 0.34, settle = 0.38, hold = Math.max(0, duration - up - settle);
  tl.fromTo(el, { scale: 1 }, { scale, duration: up, ease: ease.overshootSoft, immediateRender: false }, t0);
  tl.fromTo(el, { scale }, { scale: 1, duration: settle, ease: ease.heavyDrop, immediateRender: false }, t0 + up + hold);
  tl.fromTo(glow, { opacity: 0 }, { opacity: 0.55, duration: up, ease: "sine.out", immediateRender: false }, t0);
  tl.fromTo(glow, { opacity: 0.55 }, { opacity: 0, duration: settle + hold * 0.5, ease: "sine.inOut", immediateRender: false }, t0 + up + hold * 0.5);
  tl.fromTo(sweep, { opacity: 0, rotation: -90 }, { opacity: 1, rotation: 90, duration: 0.2, ease: "none", immediateRender: false }, t0 + 0.02);
  tl.fromTo(sweep, { rotation: 90 }, { rotation: 270, duration: duration - 0.2, ease: "sine.inOut", immediateRender: false }, t0 + 0.22);
  tl.fromTo(sweep, { opacity: 1 }, { opacity: 0, duration: 0.24, ease: "power1.in", immediateRender: false }, t0 + duration - 0.24);
  let sig = null;
  if (signature !== false && B.signature && B.signature.strokes && B.signature.strokes.length) {
    sig = signatureBeat(tl, B.signature, { host, card: el, L, id, t0, D, accent: sigAccent || accent, ink: sigInk, width: sigWidth, scale, gap: sigGap,
      write: sigWrite, fade: sigFade, seamTail: sigSeamTail, bold: sigBold, up, settle, hold });
    problems.push(...sig.problems);
  }
  return { el, at: t0, end, problems, signature: sig };
}

export default { identity };
