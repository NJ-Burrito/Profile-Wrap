# Fonts

Fonts are configuration. Nothing in this repository is a font file, and no family is banned or privileged: family names are
plain strings in `config/njli.json` (`brand.fonts`).

## Three sources (`brand.font_source`)

| Source | What happens |
|---|---|
| `google_ofl` (default) | `njli fonts fetch` installs IBM Plex Sans and IBM Plex Sans Arabic (SIL Open Font License 1.1) from the pinned fontsource npm packages into `brand/fonts/`, with their licence files. The folder is git-ignored. Other OFL families can be added to `data/fonts-ofl.json`. |
| `user_files` | You point `brand.fonts.<role>.files` at your own font files. They are read in place; the package never copies, bundles or redistributes them. |
| `system` | The family is expected to be installed on this computer. No files are read. |

Roles: `display` (headlines), `text` (body), `arabic` (Arabic text; Latin runs fall back to the `text` family).

## Licensed fonts you own

If you use a commercial or custom typeface (for example a foundry's family), check its licence before using it in images and
videos. Many end-user licences cover desktop use but not embedding glyphs in distributed images, PDFs or video. That is your
decision and your responsibility; this package only reads the files you name. Never commit them: `brand/fonts/` and common font
extensions are git-ignored, and `njli leaks scan` flags any font binary in a repository.

## Loading rule

The generated `fonts.css` carries base64 `@font-face` rules and the variables `--brand-display`, `--brand-text`, `--brand-sans`
and `--brand-arabic`. **A render fails when a configured family did not load.** The static lane checks every family in the
browser (a declared face must report "loaded"; a system family must measure differently from the generic fallbacks) and the GIF
lane refuses to start without the files. There is no silent fallback face.

## Checks

- `njli fonts check` lists what resolves and what is missing.
- `gate.required_font_substrings` for the PDF check derives from the same config: the families with spaces removed, unless you set it.
- Document posts are checked with `pdffonts` (optional): no Type 3 fonts, no families outside the configured ones.
