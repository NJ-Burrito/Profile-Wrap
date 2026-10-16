# Identity card and signature (opt-in, off by default)

A small card fixed to the frame of a GIF: round photo, name and role, with one beat per loop and, optionally, a drawn signature.
Turn it on in the config: `brand.identity.enabled`, `name`, `role`, `photo`, `signature` (`none`, `typed` or `svg`).

## Rules

- The photo is the user's own file. It is read from the path in the config and copied into the video project as `motion/photo.<ext>`
  (git-ignored). It is never fetched, never committed and never uploaded anywhere but LinkedIn with the post.
- The library names nobody by default. `identity.js` reads `window.__brand.identity`, which `motion/brand.js` fills from the config.
- Placement: bottom left (right for Arabic), 40 px from the edges, visible from frame 0, a child of the stage, never of a camera group.
  Keep the bottom 150 px free: the card's 1.25x beat reaches that band, and the loop-seam check compares that band.
- The beat position varies by preset: `hook` (rides the first big word, ends 0.3 s before the hit), `release`, or `signoff`
  (the last beat before the seam). Never at a fixed second, never within 0.6 s of the hit unless `hook`, never within 0.5 s of the seam.
  `identity()` throws on a bad time.

## Signature modes

| Mode | How |
|---|---|
| `none` | no signature |
| `typed` | `njli motion signature typed --text "Your Name" --font path/to/ScriptFont.ttf`. The outline of the name in your font, drawn on stroke by stroke. Needs `fonttools` only (extra `sig`). Use an OFL script font or one you are licensed to use. |
| `svg` | `njli motion signature svg my-signature.svg`: every `<path>` becomes a stroke in document order. |
| trace | `njli motion signature trace my-signature.png [--waypoints strokes.json]`: your handwriting becomes strokes. Needs pillow, numpy and scikit-image (extra `sig`). Waypoints fix the writing order when the automatic order is wrong. |

The result is `brand/identity/signature.data.js`. It is your own data: never inside the motion core, never in a public repository.
The signature is never mirrored for Arabic; the plate moves to the other side and the ink still reads left to right.
