# Banner

A profile banner is 1584x396. `profile-wrap visuals banner --headline "..." [--subline "..."] [--dir rtl] [--c-bg #hex --c-ink #hex --c-accent #hex]`
fills `brand/banner/banner.html` (seeded from `brand-kit/templates/banner.html`; edit your copy freely) and renders:

- `brand/banner/out/banner@1x.png` and `banner@2x.png`;
- `brand/banner/out/banner-safezone.png`, a preview with the safe zone drawn (skip with `--no-overlay`).

Outputs go into the workspace, never into the plugin. Only text you supply appears: the template invents no credentials, names or numbers.

## Gates

- **Safe zone.** On desktop the profile photo overlaps the lower left of the banner (lower right for right-to-left). The default zone
  is 420x276 px from that corner. No text may sit inside it; the render fails and names the text.
- **Minimum font.** No visible text under 28 px.
- Fonts come from your config and must load.

The layout is not verified against LinkedIn's current crop. Check the result on a phone and on desktop before you upload it; LinkedIn
changes how it crops banners.

## Content

One line of value for your reader, one supporting line. Do not paste a phone number or an email into a banner. The headline follows
the same rules as a caption: no invented numbers, no filler.
