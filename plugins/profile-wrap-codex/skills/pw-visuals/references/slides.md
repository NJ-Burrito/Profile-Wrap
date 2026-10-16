# Slides

`drafts/<slug>/slides.html` holds one `<section class="slide">` per slide, each exactly 1080x1350. `profile-wrap render <slug>` renders them
in a headless browser at 2x (2160x2700) into `out/slide-NN.png`, and a tagged PDF `out/<slug>.pdf` when there is more than one slide.

Start from `brand-kit/templates/slides.html`: it defines the colour variables, the type scale, the masthead, `.grow` and the footer.

## What the renderer does

- Injects the base64 fonts and the `--brand-*` variables from your config. Use `font-family: var(--brand-display)`, `--brand-text`,
  `--brand-sans`, `--brand-arabic`. Never name a family in the page.
- Inlines local images (`src="..."` with single or double quotes, png, jpg, svg, webp, gif) and CSS `url(...)` as data URIs.
- Replaces `<i data-icon="name"></i>` with the Lucide SVG. A missing icon: `profile-wrap icons add <name>` (ISC licence travels with it).
- Fails if a configured family did not load.

## Gates (a failure is never shipped)

| Gate | Rule |
|---|---|
| overflow | no element leaves its slide on any side (so right-to-left slides are checked too); opt out only with `.portrait` or `.bleed` |
| `.grow` | a `.grow` block must not be taller than its space |
| font floor | no visible text under 28 px; opt out with the class `allow-small` only for a legal footnote |
| fonts | every configured family loaded |

## Style

Fewer words, bigger visuals, one point per slide. The caption carries the sentences; slides carry the point. Icons are vector
Lucide icons; emoji glyphs are not in your fonts and would fall back to another face, so they go in the caption only.

## Document posts

PDF checks use `pdffonts` and `pdfinfo` when installed (optional): no Type 3 fonts, no families outside the configured ones, page
count equal to the slide count. `gate.required_font_substrings` derives from the same config.
