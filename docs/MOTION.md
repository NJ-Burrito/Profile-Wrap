# Motion standard v4

The rules every animated post follows. The library is `brand-kit/motion/` (copied into your workspace as `brand/motion/`
and into each video project as `videos/<slug>/motion/`). The numbers below are enforced by `profile-wrap visuals metrics` and by the
composition's own probe, not by taste.

## What a GIF post is

A 8 to 10 second seamless loop at 1080x1350 (4:5), 25 fps, at most 250 frames, at most `gate.gif.max_mb` (default 40 MiB, an
empirical default, not a LinkedIn guarantee). One paused GSAP timeline, rendered by HyperFrames, turned into a GIF by ffmpeg.

## Keep and drop

| Keep | Drop for posts (the legacy module still exists for old projects) |
|---|---|
| Kinetic hero type: hook 140 to 230 px, word masks, weighted overshoot, strike-through, re-entry (`M.type`) | Camera orbit and dolly, 3D stage, bokeh (`motion.legacy.js`) |
| A split on one beat (`M.split`), a locked camera, a match cut, a click iris, a flat whip (`M.cut`) | Morph transitions, ghosted overlapping text at the hit |
| Frame 0 is a finished poster (`M.poster`); a beat grid (`M.grid`) | A vignette or grade dim over content, scrambling counters |
| A dead stop instead of a dim (`story.preset("no-dim")`) | Pulse rings and glints used as still-frame filler |
| A light or mid-tone base (dark in at most 2 of 7 posts) | Letter-by-letter or typewriter Arabic |

## The rules

1. **One paused timeline.** No `Math.random`, `Date` or `performance.now`; seeded noise only; explicit `fromTo` states; no
   tween-time DOM measuring; no `repeat: -1`.
2. **Poster frame 0.** The whole hook is readable at a 400 px thumbnail, nothing masked or blank, and the loop returns to it
   (`poster.check` returns `[]`; `metrics` also measures that frame 0 is not a blank field).
3. **Onsets.** A new small event in the first 0.25 s and in the last 0.5 s, so the loop edges are never dead.
4. **Loop seam.** Frame N equals frame 0; park hidden elements at their frame-0 pose. Nothing important within 0.5 s of the seam.
   `metrics` compares the first and last frame (identity band when the card is on, whole frame otherwise; limit 3.0, and a
   motion upgrade may be at most 2.0 worse than the previous GIF's own seam).
5. **Hold rule.** A dead stop of at most 0.8 s before the hit is allowed and must be logged in `shot-plan.json`
   (`hold: [{at, end, frames, why}]`). Nothing runs inside it (the probe checks it). Frames inside a logged hold are excluded
   from the still-frame share. Everywhere else still frames stay under `gate.gif.max_still_pct` (default 8).
6. **Type floors.** 28 px minimum at 1080 wide, hook 140 px or larger; zero WCAG contrast failures (`contrast_pairs` in
   `shot-plan.json`, computed from the colours as written).
7. **One flash per loop**, never red, at most `gate.gif.flash_max_per_s` (default 3) a second.
8. **Arabic.** Word-level masks only, never letter-by-letter. Letter-spacing 0, line-height 1.4, extra mask headroom. Strikes and
   whips run right to left and the split mirrors. Code stays left to right. See `skills/pw-visuals/references/arabic-rtl.md`.
9. **Cast rule.** Real objects from the kit (`brand-kit/objects/core`, 37 objects; `maker`, 12 more), never a flat swatch or
   coloured square for a real thing. No emoji glyphs on frames; Lucide icons for small UI symbols. Objects take the post's
   palette through `--obj-*` variables and the light through `M.objects.follow`.
10. **Colour per post.** No fixed theme: each post derives its palette from its topic (`M.color.script`), and neighbouring posts
    never share a preset or a hero colour. Record the palette in `shot-plan.json`.
11. **Verify what the frame claims.** Any domain statement shown on screen (a syntax, a number, a name) is checked against its
    source before the render, and numbers on frames pass the same claim-bound gate as the caption.

## Story arc presets

`M.story.preset(name, overrides)` for a 10 s loop. Neighbouring posts in the queue never share a preset.

| Preset | Hit | Tension | Identity card beat |
|---|---|---|---|
| `early-hit` | about 3.9 s | dim 0.9 s | `hook` |
| `mid-hit` | about 5.2 s | dim 1.4 s | `release` |
| `late-hit` | about 6.6 s | dim 1.6 s | `signoff` |
| `no-dim` | about 4.1 s | dead stop 0.3 to 0.8 s, logged | `signoff` |

## Wiring

`profile-wrap new-gif <slug>` copies `brand-kit/templates/gif-project` into `videos/<slug>/` and syncs `core.js`, `identity.js`,
`motion.css`, `objects.data.js`, a generated `brand.js` and `assets/fonts.css`, and GSAP into `vendor/`. The page loads GSAP as a
classic script, then `import * as M from "./motion/core.js"`. Lint wants a literal `window.__timelines["<id>"] = tl` after
`M.loop.register(...)`. The template's probe writes `window.__probe` into a `data-probe` attribute; `profile-wrap render` reads it before
the slow render and stops on any problem.

## Library layout

- `core.js`: grid, type, cut, split, poster, story arc presets, eases, light, colour script, counter, loop verify, onsets, objects.
- `identity.js`: the opt-in identity card and signature beat. It reads `window.__brand.identity` and has no defaults.
- `motion.css`: layer and structure classes; fonts through `--brand-*` variables.
- `motion.legacy.js`: camera, depth, ambient, bokeh. Optional, off by default.
- `VERSION`: `profile-wrap motion status` lists projects whose library differs; `profile-wrap motion upgrade --queued-only` re-renders them.

## Counters

`M.counter` defaults to `style: "roll"` (whole old value out, whole new value in); `"step"` steps through whole valid values.
Digit columns that spin through 0 to 9 read as a render glitch mid-roll and are not offered as a default.

## GIF size

A 256-colour GIF without dithering struggles with gradients, blurs, full-frame sweeps and a moving camera. Cheapest: a locked
camera, flat fills, clip-path reveals, a small clock strip. If a render is over the cap, the trim pass tries 20 fps, then 192
colours, then stops and names the problem; an MP4 export is planned for v1.1.
