/* core.js - Profile-Wrap motion library, Standard v4 (HyperFrames + GSAP). MIT.
   One ES module facade: the code lives in core/*.js (split by section, every export name unchanged).
   Every helper adds tweens to a GIVEN paused timeline: helper(tl, targets, opts).
   Rules baked in (see docs/MOTION.md): deterministic (seeded rng, no Math.random / Date / performance.now),
   seek-safe (explicit fromTo states, no onUpdate side effects, no tween-time DOM measuring),
   loop-exact (periodic motion uses whole cycles; one-shots return to their rest state).
   NO DEFAULT PALETTE: every post defines its own colour script (color.script) and the library reads it.
   Needs the global `gsap` (load it with a classic <script> before importing this module).
   The identity card lives in identity.js; camera, depth and ambient (deprecated for posts) live in motion.legacy.js.

   Sections: 1 colour script . 2 eases . 6 light . 7 hand-animated feel . 8 story arc . 9 micro-onsets . 10 connector pulse .
             11 typewriter . 12 focus pull . 13 state colour . 14 counter . 15 follow-through . 16 loop stitch . 17 objects .
             19 v4: grid . type . cut . split . poster ; story.presets ; counter (whole values, never scrambled digits) */
export { TAU, gs, arr, NS, clamp, allow, TOKENS, hash, rng, periodic, sample } from "./core/base.js";
export { hex2rgb, rgb2hex, relLum, contrast, mix, ensure, onColor, color } from "./core/color.js";
export { bezier, spring, ease, WEIGHT, EASE } from "./core/ease.js";
export { light } from "./core/light.js";
export { hand } from "./core/hand.js";
export { story } from "./core/story.js";
export { flash, onsets } from "./core/onsets.js";
export { pulseAlong, pulseTrain, typewriter, focus, stateChange, counter } from "./core/effects.js";
export { overlap, loop } from "./core/loop.js";
export { life, objects } from "./core/objects.js";
export { grid, type } from "./core/layout.js";
export { cut, split, poster } from "./core/shots.js";

import { registerEases } from "./core/ease.js";
import { TOKENS, rng, hash, periodic, sample } from "./core/base.js";
import { color } from "./core/color.js";
import { EASE, ease, WEIGHT, bezier, spring } from "./core/ease.js";
import { light } from "./core/light.js";
import { hand } from "./core/hand.js";
import { story } from "./core/story.js";
import { onsets, flash } from "./core/onsets.js";
import { pulseAlong, pulseTrain, typewriter, focus, stateChange, counter } from "./core/effects.js";
import { overlap, loop } from "./core/loop.js";
import { objects, life } from "./core/objects.js";
import { grid, type } from "./core/layout.js";
import { cut, split, poster } from "./core/shots.js";

registerEases();

export default { TOKENS, EASE, ease, WEIGHT, bezier, spring, rng, hash, periodic, sample, color, light, hand, story,
  onsets, flash, pulseAlong, pulseTrain, typewriter, focus, stateChange, counter, overlap, loop, objects, life,
  grid, type, cut, split, poster };
