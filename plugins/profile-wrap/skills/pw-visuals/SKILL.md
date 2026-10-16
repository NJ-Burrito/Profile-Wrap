---
name: pw-visuals
description: Build the visual of a LinkedIn post. Use for "slides", "carousel", "document post", "GIF", "animate this", "make it more dynamic", "banner", "fonts", "identity card", "signature", "motion standard", "devil mode", "council", "trials" or "upgrade the motion library". Produces slides.html to 2x PNG and PDF, or a HyperFrames project to a looping GIF, with render.json and metrics. Never posts anything.
---

# pw-visuals

Turn an approved draft into its visual. Work the nj-method way: look up before improvising, plan with file checkpoints, run each
machine step once, review against the request. The command is `profile-wrap` (installed with `uv tool install profile_wrap`); the workspace is the
current folder or `--workspace <path>`.

## Compliance first

This skill makes files. It never posts, never logs in to LinkedIn and never captures or imitates LinkedIn's interface or logos.
The user approves the visual by eye on the board before anything is allowed to post.

## Pick the format

| Format | Command | Result |
|---|---|---|
| `slides` / `document` | write `drafts/<slug>/slides.html` from `brand-kit/templates/slides.html`, then `profile-wrap render <slug>` | `out/slide-NN.png` at 2x, `out/<slug>.pdf` (more than one slide), `out/render.json` |
| `gif` | `profile-wrap new-gif <slug>`, edit `videos/<slug>/index.html`, set `video_project` in `meta.json`, `profile-wrap render <slug>`, `profile-wrap visuals metrics <slug>` | `out/<slug>.gif`, `out/render.json`, `out/metrics.json` |
| `banner` | `profile-wrap visuals banner --headline "..."` | `brand/banner/out/banner@1x.png`, `@2x.png`, `banner-safezone.png` |
| `text` | nothing to render | |

## First time

1. `profile-wrap fonts check`. If it fails: `profile-wrap fonts fetch` (OFL default) or set `brand.fonts` to your own files. See `docs/FONTS.md`.
2. GIFs and slides need Node >= 22. `profile-wrap assets fetch` installs the pinned Playwright, HyperFrames and GSAP into the workspace.
   `profile-wrap doctor` names what is missing for your system (ffmpeg, a browser).
3. Read `docs/MOTION.md` before any animation.

## Procedure

1. Read the draft (`meta.json`, `caption.txt`, `alt.txt`) and the storyboard. One idea per slide or per beat.
2. Pick the palette for this post (light or mid-tone by default, differs from the neighbouring posts) and write it first.
3. Build with the kit only: Lucide icons (`<i data-icon="name"></i>`, `profile-wrap icons add <name>` for a missing one) and the object kit
   for real things. No emoji glyphs on frames, no placeholders, no copied logos.
4. Render once. A gate failure is fixed once, then re-rendered once; a second failure is reported with the failing line.
5. For a GIF read the metrics. Fix only what the numbers name.
6. Make the contact sheet for the council (ffmpeg tile) and run the design seat at 360 px.
7. Write `alt.txt` (what the visual shows, in the post's language). The caption repeats the message.

## References

| Need | Read |
|---|---|
| GIF rules, arc, hold log, metrics, size | `references/gif-standard.md` and `docs/MOTION.md` |
| Slides: template, gates, icons, PDF | `references/slides.md` |
| Banner: size, safe zone, fonts | `references/banner.md` |
| Identity card and signature (opt-in) | `references/identity-card.md` |
| The motion round: devil, trials, council, promote | `references/motion-round.md` |
| Arabic and right-to-left | `references/arabic-rtl.md` |
| Alt text, contrast, reduced motion | `references/accessibility.md` |

## Do not

- Edit the motion library from inside a post job: library changes are their own task, then `profile-wrap motion upgrade --queued-only`.
- Copy a font, photo or signature file into a draft or the repository. They stay in the user's own folders.
- Change `status`, `scheduled_at` or `review.json` when re-rendering a queued post.
