# Accessibility

- **Alt text is required** (`gate.require_alt_text`). `alt.txt` says what the visual shows and what it means, in the post's language, in
  one or two sentences, and is passed as `altText` when posting. The caption repeats the message: a GIF cannot be paused.
- **Contrast.** WCAG ratios are computed from the colours written in `shot-plan.json` (`contrast_pairs`: `[foreground, background,
  minimum]`): 4.5:1 for text, 7:1 for the hook where you can, 3:1 for 140 px type and larger. Zero failures. Add a second cue (shape,
  icon, position) to anything that relies on colour alone.
- **Size.** No visible text under 28 px at 1080 wide. Check legibility at 360 px wide on the contact sheet.
- **Motion safety.** At most one flash per loop, never red, at most 3 flashes in any second. The first and last frames agree so the
  loop does not jump. A static poster frame carries the message for readers who see only the first frame.
- **Review.** Contact sheets (an ffmpeg tile of evenly spaced frames) go to the council. The design seat checks the 360 px view.
  The user approves by eye on the board before Allow.
- **No imitation.** The pipeline never captures or imitates LinkedIn's interface or logos.
- **Language.** For Arabic, see `arabic-rtl.md`; set `lang` and `dir` on the page.
