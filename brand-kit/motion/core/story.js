/* core/story.js - Section 8: story arc presets. Part of core.js (split by section, pure move). */
import { TOKENS } from "./base.js";

/* ================================================================== 8. STORY ARC (hook, build, tension, payoff, release)
   A plan fixes the phase times and gives the helpers a rhythm: fast build, slow tension, fast payoff, slow release.
   plan.calm(t) lowers secondary activity during tension ON PURPOSE; plan.pace(t) is the onset interval per phase. */
export const story = {
  /* v4: mode "stop" makes the tension a DEAD STOP (nothing moves for buildEnd..tensionEnd, at most 0.8 s) instead of a dim:
     calm() stays 1, the stop is a logged hold (plan.holds -> shot-plan.json) and the tension-length check becomes the hold check. */
  plan({ duration = 8, fps = TOKENS.FPS, hookEnd = 0.8, buildEnd = 3.6, tensionEnd = 5.0, hit = 5.2, payoffEnd = 5.9,
    floor = 0.1, ramp = 0.4, pace = {}, mode = "dim" } = {}) {
    const P = { hook: [0, hookEnd], build: [hookEnd, buildEnd], tension: [buildEnd, tensionEnd], payoff: [tensionEnd, payoffEnd], release: [payoffEnd, duration] };
    const paces = { hook: 0.2, build: 0.26, tension: Infinity, payoff: 0.17, release: 0.5, ...pace };
    const phaseAt = (t) => Object.keys(P).find((k) => t >= P[k][0] && t < P[k][1]) || "release";
    const stop = mode === "stop";
    const calm = (t) => {
      if (stop) return 1;
      const a = buildEnd - ramp, b = buildEnd, c = hit - 0.05, d = hit + 0.2;
      let w = 0;
      if (t >= a && t < b) w = (t - a) / (b - a);
      else if (t >= b && t < c) w = 1;
      else if (t >= c && t < d) w = 1 - (t - c) / (d - c);
      const s = w * w * (3 - 2 * w);
      return 1 - (1 - floor) * s;
    };
    const plan = {
      duration, fps, hit, phases: P, paces, floor, mode,
      phaseAt, calm,
      pace: (t) => paces[phaseAt(t)],
      quiet: [[buildEnd, stop ? tensionEnd : hit - 0.05]],
      /* logged holds for shot-plan.json: [{ at, end, why }]; the still-frame gate allows these and nothing else */
      holds: stop ? [{ at: buildEnd, end: tensionEnd, why: "dead stop before the hit" }] : [],
      label(tl) { Object.keys(P).forEach((k) => tl.addLabel(k, P[k][0])); tl.addLabel("hit", hit); },
      /* events per second per phase, from the paces */
      tempo() { const o = {}; Object.keys(P).forEach((k) => { o[k] = isFinite(paces[k]) ? +(1 / paces[k]).toFixed(2) : 0; }); return o; },
      /* sanity checks the arc grammar. Returns a list of problems (empty = ok). */
      check() {
        const bad = [], T = plan.tempo();
        if (P.hook[1] - P.hook[0] > 1.2) bad.push("hook longer than 1.2 s");
        const tlen = P.tension[1] - P.tension[0];
        if (stop) {
          if (tlen < 0.3 || tlen > 0.8) bad.push("dead stop must be 0.3-0.8 s (is " + tlen.toFixed(2) + " s)");
          if (hit - P.tension[1] > 0.6) bad.push("hit more than 0.6 s after the dead stop: the silence will not lead into it");
        } else if (tlen < 0.8) bad.push("tension shorter than 0.8 s: the held breath will not read");
        if (!(T.tension < T.build * 0.5)) bad.push("tension must be less than half as busy as the build");
        if (!(T.payoff >= T.build * 0.9)) bad.push("payoff should be at least as fast as the build");
        if (hit < P.payoff[0] || hit > P.payoff[1]) bad.push("hit is outside the payoff phase");
        if (duration - payoffEnd < 0.9) bad.push("release shorter than 0.9 s: the loop will not breathe");
        if (hit > duration - 0.5) bad.push("payoff within 0.5 s of the seam");
        return bad;
      },
    };
    return plan;
  },
};

/* ARC PRESETS (Standard v4). A post picks ONE; two neighbours in the queue never share a preset. Times are for a 10 s loop and
   scale with `duration`. identity.where (see identity.js) says where the card beat and the signature go: "hook" (rides the first big word),
   "release" (after the payoff), "signoff" (the last thing before the seam). Override any field: M.story.preset("no-dim", { hit: 4.08 }). */
story.presets = {
  "early-hit": { hookEnd: 0.8, buildEnd: 2.6, tensionEnd: 3.5, hit: 3.9, payoffEnd: 5.0, mode: "dim", identity: "hook",
    note: "hit at about 3.9 s; dim tension 0.9 s; the rest of the loop is payoff and a long release" },
  "mid-hit": { hookEnd: 0.8, buildEnd: 3.6, tensionEnd: 5.0, hit: 5.2, payoffEnd: 6.2, mode: "dim", identity: "release",
    note: "the v3 shape: hit at about 5.2 s after a 1.4 s dim" },
  "late-hit": { hookEnd: 1.0, buildEnd: 4.8, tensionEnd: 6.4, hit: 6.6, payoffEnd: 7.4, mode: "dim", identity: "signoff",
    note: "a long build, the hit at about 6.6 s, a short release" },
  "no-dim": { hookEnd: 1.2, buildEnd: 3.4, tensionEnd: 3.9, hit: 4.1, payoffEnd: 5.4, mode: "stop", identity: "signoff",
    note: "no grade shift, no vignette: the tension is a logged DEAD STOP (0.3-0.8 s), then the hit at about 4 s" },
};
story.preset = function preset(name, over = {}) {
  const base = story.presets[name];
  if (!base) throw new Error("story.preset: unknown preset '" + name + "' (" + Object.keys(story.presets).join(", ") + ")");
  const o = { duration: 10, ...base, ...over };
  const k = o.duration / 10, sc = (v) => (over[v] != null ? over[v] : +(base[v] * k).toFixed(3));
  const plan = story.plan({ duration: o.duration, fps: o.fps, hookEnd: sc("hookEnd"), buildEnd: sc("buildEnd"), tensionEnd: sc("tensionEnd"), hit: sc("hit"), payoffEnd: sc("payoffEnd"), mode: o.mode });
  const where = over.identity || base.identity, D = o.duration;
  const at = where === "hook" ? +(plan.phases.hook[1] * 0.6).toFixed(2) : where === "release" ? +(plan.phases.release[0] + 0.55).toFixed(2) : +(D - 2.35).toFixed(2);
  plan.preset = name; plan.note = base.note;
  plan.identity = { where, at };   /* M.identity(tl, { plan, where: plan.identity.where, at: U(plan.identity.at), ... }) */
  return plan;
};
