# GIF standard (motion v4)

The full rules are in `docs/MOTION.md`. This is the checklist a GIF must satisfy before it goes to the board.

## Pipeline

1. `njli new-gif <slug>`: copies `brand-kit/templates/gif-project` to `videos/<slug>/` and syncs the library, `brand.js`, `fonts.css` and GSAP.
2. Edit the `COPY`-style text, the colour script and the cast in `index.html`. Keep the arc code unless you pick another preset.
3. `njli render <slug>`:
   - probe (Chrome loads `index.html`; plan, poster, hold and palette problems stop the run before the slow part);
   - `hyperframes@<pin> lint`, `check`, `render -q delivery --crf 10 --low-memory-mode`;
   - ffmpeg `palettegen stats_mode=full` and `paletteuse dither=none diff_mode=rectangle`;
   - ffprobe decodes the temp GIF and counts frames (at most 250), then it is swapped in atomically; temp files never survive.
4. `njli visuals metrics <slug>`.

## Checklist

1. One arc preset, different from the neighbouring posts; `plan.check()` returns `[]`.
2. Poster frame 0: the whole hook readable at a 400 px thumbnail; `poster.check` returns `[]`.
3. Type is the hero: hook 140 px or larger, word-level masks, a strike and a re-entry where the idea is a contradiction.
4. Cuts on the beat grid: a match cut, a click iris from the clicked element, or a flat whip; a split on one beat.
5. Hold rule: a dead stop of at most 0.8 s before the hit, logged in `shot-plan.json`, nothing moving inside it.
6. Colour per post, contrast table with zero failures, recorded in `shot-plan.json` (`palette`, `contrast_pairs`).
7. Real objects from the kit with the post's palette; each idle move ends 0.9 s before the seam.
8. Identity card only if the user enabled it (`references/identity-card.md`).
9. Still frames under 8 % with the hold excluded; an onset in the first 0.25 s and the last 0.5 s.
10. Text at least 28 px; icons are Lucide; no emoji glyphs on frames.
11. Seam: first and last frame agree (limit 3.0); one flash per loop, never red.
12. At most 250 frames and `gate.gif.max_mb`.

## Reading the metrics

`still` is the share of frame steps with almost no change, minus the logged hold. `seam_band_diff` is the mean luminance difference
between the first and last frame. `flashes` counts opposing luminance swings of 10 % or more. `poster_ink` is the share of frame 0
that is not its background colour. A failure names the number and the limit; fix that one thing and render once more.

## Anti-slop list (any one sends it back)

- A coloured square standing in for a shirt, bag, button or cursor.
- One thing moving at a time with nothing else alive, or constant motion with no dead stop and no single hit.
- Camera orbit or dolly, bokeh, morphs, a vignette over content, ghosted text at the hit.
- Letter-by-letter or typewriter Arabic; letter-spacing on Arabic.
- Scrambling digit counters.
- A dead stop that is not logged; pulse rings and glints used as filler.
- A fixed palette reused post after post; dark by default.
- A masked or blank frame 0; the signature at a fixed second; the same preset as the neighbouring post.
- Panes with an empty bottom third; rows under 34 px or in pale ink; tiny dashboard text.
