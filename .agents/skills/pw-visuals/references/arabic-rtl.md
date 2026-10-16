# Arabic and right-to-left visuals

Arabic and English are both first-class. The visual of a bilingual pair is one unit: fix both sides.

## Slides

- `<html lang="ar" dir="rtl">`. Use logical properties and `flex` so the layout mirrors; the template does this.
- Font: `var(--brand-arabic)`. Latin runs fall back to your `text` family, so digits and product names still render.
- `letter-spacing: 0` always (any spacing breaks the joins). Line-height 1.4 for headlines, 1.6 for body.
- Give masks and clipped lines extra headroom (hamza, dots, tails): the template's `.mo-mk-ar` does it for the motion library.
- Latin digits and units in UI-like text unless the audience expects Arabic-Indic digits; keep one choice per post.
- Mirror direction in a layout, not in an icon that has a fixed meaning (a check mark, a logo, a play button).
- The overflow gate checks the right edge too, so a right-to-left slide that spills is caught.

## GIFs

- Words only: word-level masks, never letter-by-letter or typewriter prose (`M.typewriter` forces words).
- Strikes and whips run right to left. The split mirrors (page right, panel left). Code stays left to right.
- The identity card moves to the bottom right; the signature plate sits on the other side and is not mirrored.
- Pass `rtl: true` to the directional helpers (`M.type.strike`, `M.cut.whip`, `M.split.make`).
- Avoid palette colours the audience reads as a warning (very dark reds) unless the topic is a warning.

## Checks before it goes out

`profile-wrap gate <slug>` (Arabic hygiene on the caption and alt text), the overflow and font-floor gates in `profile-wrap render`, and the language
seat of the council for regional fit. Proofread text on the frames too, not only the caption.
