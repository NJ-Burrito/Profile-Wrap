# Style DNA: console-stage

A narrated product-release film: a near-black field with a navy glow top right and an ember glow bottom left, one device on
screen, a two-line headline with one orange accent word, a typed terminal panel, audio waveforms, kicker labels, a node
diagram, and an end card with an install command. Measured from one reference (a 82 s, 1280x720, 30 fps LinkedIn post film,
narrated, AAC stereo 44.1 kHz). Everything below is a number read from its frames or audio unless marked NOT_MEASURED.
The starter template is `brand-kit/templates/styles/console-stage/` (default canvas 1280x720, 30 fps, 12 s rehearsal cut; any canvas with `--canvas WxH`).

## 0. The theme comes from the subject (owner, 2026-11-23)

The navy-and-ember palette in section 1 is what the reference film measured. It is NOT the template's look: the owner scored a fixed palette
4/10 and asked for colours, theme and scenes that follow the idea of the tool the post is about. So the template holds no colour of its own.
Everything visual is a token in `theme.json` (palette, two glow colours, canvas, motif), turned into `theme.css` at scaffold:

```
profile-wrap visuals theme --from <logo-or-screenshot> --out theme.json      # derive, contrast-check, print
profile-wrap new-gif <slug> --style console-stage --theme-from <logo-or-screenshot> --canvas 1080x1350 --subject "..." --motif "..."
```

`theme.derive` reads the image through ffmpeg (stdlib only), takes the dominant hue as the accent and the next distinct hue as the result
colour (a near neighbour toward green when the subject has only one), builds a dark field tinted by the accent, two glows, a panel and a line,
and lifts every text colour until all pairs pass (text 4.5, UI 3). `theme.check` lists every pair and is the gate: `new-gif` refuses a theme
that fails. Without `--theme-from` the neutral default theme is used; a real post always passes one. The same tokens drive the device glow,
the chips, the sparkles and every effect colour. Scenes follow the subject too: the `#motif` layer is the subject's own picture (NJ-Flush: the
logo's swirl as a water vortex that spins up and drains on the flush, a RAM meter that fills, four tier rows that fill like a level meter). Keep
the grammar (stage, headline with one accent word, proof panel, 8-frame dissolves) and replace the motif, the scenes and the numbers for each
subject. Never reuse another post's colours on a neighbouring post.

What is copied is the look and the motion, never the assets: the reference's typeface, logo, mascot, phone footage and copy
belong to their creators and are not used. Type is the workspace brand font (variables `--brand-sans` and `--brand-display`;
the workspace font plan only, no fallback face). The logo is a brand slot (a rounded square and a dot in the template) replaced by the
workspace brand mark. Device footage is a brand-neutral CSS device frame.

## 1. The look

| Token | Value | Where measured |
|---|---|---|
| Field | `#121116` | top-left corner, all frames |
| Navy glow | `#172039` at the top-right corner, fading to `#0F121D` at the bottom-right | corner samples, 0 to 82 s |
| Ember glow | `#382116` at the bottom-left corner, `#1B1618` at mid-left | edge sampling, 5 heights |
| Gradient | two elliptical radial gradients (about 900x620 px from the top-right, 820x600 px from the bottom-left) over the field | template `#stage` |
| Grain | a dot grid, 32 px pitch, 1 px dots at about 7 % white, very low contrast (read after 5x brightness boost) | frame at 78 s |
| Ink (headline) | `#EDF2FC` | headline pixels |
| Accent (hero word, kicker, prompt `$`, progress bar, waveform) | `#FF6200` (samples FF5F00 to FF6D0A) | five elements |
| Result green (second accent, command output, kicker "listen", pass) | `#46E080` (samples 43E67F to 64D493) | four elements |
| Sub line | `#9296A5` | 'A real iPhone...' line |
| Panel fill / border | `#141722` / `#2B2D3B`, 2 px, radius about 12 px | panel edge profile |
| Phone glow | orange `0 0 44px 12px` at 0.45 alpha (recording), then green at 0.5 (done); measured green halo `#20483E` | 1 s and 3 to 4 s |

Contrast, computed from the template's own variables (`work/styles-2026-11-23/console-stage/contrast.py`), 19 text pairs, 0 failures:
ink on field 16.74, ink on ember 13.39, ink on navy 14.37, ink on panel 15.92; accent on field 6.26, on ember 5.01, on panel 5.95;
green on field 10.95, on ember 8.76, on panel 10.41; muted on field 6.38, on ember 5.10, on navy 5.47; footnote `#9A9AA6` on field 6.75,
on ember 5.40; corner mark `#8B94AC` on field 6.20, on navy 5.32; dark text on orange fill 6.26; accent on panel border 4.54 (UI, min 3).
Two reference greys failed (`#81818B` on ember 3.90, `#7D869F` on navy 4.44), so the template lifts them.
`hyperframes check` also passes (74 of 74 text checks, WCAG AA).

### Type roles (px on the 1280 canvas; sizes read from glyph heights, line pitch exact)

| Role | Size / line | Weight | Notes |
|---|---|---|---|
| Hook headline | 64 / 80 | bold | 3 lines, group gap +32 px before the last line, x = 88 |
| Section headline | 56 / 64 | bold | 2 lines, x = 600, top 92 |
| Kicker | 16 / 20 | bold | caps, tracking 0.22em, accent colour (green on a "listen" step), top 68 |
| Sub | 20 / 28 | regular | `#9296A5`, one line, top 236 |
| Terminal | 19 / 28 | mono in the reference; brand sans in the template | prompt `$` accent, output green or grey |
| Title card | 56 / 64 | bold caps, tracking 0.01em | centred, mark at the left |
| End card | title 56, sub 22, command 28, url 22, footnote 15 | | centred |
| Corner mark | 15 | medium | `#8B94AC`, right 48, top 26 |

The reference mono face is not available to this tool. The template reads `--brand-mono` and falls back to the brand sans. If the owner
wants a code face, that is a one-time decision (the workspace brand font is the standing rule).

### Layout grid and safe zones

Three layouts, all on 1280x720 with 88 px side margins on text-only frames and 48 px on the corner mark.

| Layout | Geometry |
|---|---|
| Hook | headline left x = 88, first line centre y = 240; device on the right x 906 to 1204, y 49 to 671 (298x622) |
| Section | device left x 160 to 466, y 31 to 677 (306x646, radius 46); text column x = 600 to 1200 (600 wide); panel x 600, y 315, 600x212 |
| Wide | headline top-left x = 88, kicker y 63, title y 100 to 136; content below y 200; device or screenshot on the right |
| Card | everything centred on x = 640: title centre y 208 to 256, sub below, command box 446x70 at y 347 (end) |

Progress bar: 4 px, accent, bottom edge, width = t / duration x 1280 (linear; at 20 s it ends at x 312 = 20/82 x 1280).
Keep text inside 5 % of each edge for LinkedIn crops: 64 px sides, 36 px top and bottom.

### Recurring components

1. Device frame: 3 px bezel, radius 46, inner screen radius 40, island, status row, two cards, URL bar. Content is neutral.
2. Terminal panel with prompt `$`, typed command, block caret, ellipsis while waiting, green output line.
3. Kicker label above the headline; the same style under the panel as a caption for a waveform ("INTO THE ... MICROPHONE").
4. Waveform: vertical bars of one accent colour, orange for outgoing/recording, green for incoming/played back.
5. Command chips (outlined, radius 15; the active ones fill orange with dark text).
6. Node diagram (28 to 42 s): rounded cards 172x156 with an icon, a name (bold 28) and a grey sub, connected by a thin line with orange and green travelling dots; tag rows "acts as" (orange outlined) and "captures" (green outlined) below. A PASS stamp (green fill, dark text) appears over a result.
7. End card: mark, "Out now", command box with an accent border (2 px, radius 14), url, a one-line footnote at y 628.

## 2. Motion (per component; enter = fade plus rise)

| Component | Enter | Exit |
|---|---|---|
| Headline block, each line | opacity 0 to 1 and +6 px rise, 0.2 to 0.27 s, `power2.out`; second line 0.1 s after the first | on a step change: a 1-frame hard drop, the kicker snaps, then the next block rises in |
| Sub line | fade plus 4 px rise, 0.25 to 0.3 s after the headline | with the block |
| Panel | linear fade 0.27 s | with the scene dissolve |
| Typing | 40 to 45 characters per second (measured about 45 cps in the reference at its "2x speed" marker); the block caret (about 10x20 px, grey) blinks at 0.5 s | |
| Wait | ellipsis ". . ." in accent, visible until the result line appears; the result line fades in 0.1 s | |
| Waveform | draws left to right as a clip, 1.5 s for 64 bars; or bars scale in with a 0.035 s stagger | |
| Device glow | linear cross-fade orange to green over 0.5 s, while the waveform plays | |
| Chips | rise 0.2 s, 0.1 s stagger; two of them fill orange 0.2 s linear | |
| Progress bar | linear, whole film | |

No camera moves, no zoom, no counters, no springs or overshoot: all easing is `power2.out` or linear. The only emphasis is the colour of one word.
Reduced motion: the film is not interactive; ship the poster frame (frame 0) as the thumbnail.

## 3. Transitions catalog

The reference has one transition type: a linear cross-dissolve of 8 frames (0.267 s), frame-diff peaks at 30 fps
(`work/.../diff.py`, 160x90 grey):

| At | Between | Peak diff |
|---|---|---|
| 4.03 s | hook to title card | 2.5 |
| 7.07 s | title card to first step | 2.9 |
| 27.17 s | listen step to the diagram | 2.0 |
| 42.03 s | diagram to web step | 9.5 |
| 55.03 s | check step to session step | 9.9 |
| 69.03 s | session step to replay | 11.1 |
| 76.03 s | replay to end card | 12.9 |

Inside a scene the headline swaps on a hard cut (14.03 s, 17.97 s: one blank frame, then lines rise in, 0.1 s apart, sub 0.3 s later).
Content cuts inside footage (57.07 s) belong to the footage, not to the style. The template uses the same dissolve (`DISS = 8/30`).

## 4. Story structure (82 s reference; template compresses it)

| Beat | Reference time | Template time |
|---|---|---|
| Hook: a question in three lines, device with waveform, glow orange then green | 0 to 4.0 | 0 to 3.0 |
| Reveal: brand and version, one-line tagline, five command chips filling in | 4.3 to 7.1 | 3.0 to 4.9 |
| How: three action steps (find, speak, listen), each a headline + typed commands | 7.1 to 27.2 | 4.9 to 9.4 (two steps) |
| How it connects: node diagram | 27.2 to 42.0 | not in the starter |
| Proof: a goal in plain English, an independent check with a PASS stamp, a whole-job session | 42.0 to 69.0 | not in the starter |
| Replay: the product's own player | 69.0 to 76.0 | not in the starter |
| CTA: brand, "out now", install command, link, honest footnote | 76.0 to 82.0 | 9.4 to 12.0 |

## 5. Caption and voice sync

The reference has no on-screen captions. The narration (about 40 phrases, from the post's caption file) leads the visual: every headline
change starts within 0.15 s of the matching sentence start (the sentence about the Roadie at 28.87 s lands on the diagram that dissolved in at 27.17 s,
so the picture runs about 1.7 s ahead of its words). Gaps in the voice are 1 to 6 s long, filled with the product's own screen audio.
In this tool: no voice is generated (Gemini is banned). The template keeps `NARRATION.cues` (empty) and `T` (scene times) as the voice clock;
fill `cues` from a real recording only, each cue running to the next cue's start, so the narrator is never cut at a caption's last word and
no unspoken text is captioned. Captions follow the voice, not the reverse. The caption path is written but not exercised by the rehearsal (no voice exists).

## 6. Sound

Reference, measured with ffmpeg: integrated loudness -24.6 LUFS, true peak -1.0 dBFS, loudness range 4.1 LU; per-second RMS stays between -26 and -13 dBFS
for the whole 82 s (never silent), so a continuous bed runs under the voice. Whether that bed is music is NOT_MEASURED (no stem separation).

The template now carries sound effects (no voice, no music). The composition logs every hit as a cue (`fx.cue(role, t, db)`) on the same timeline
clock as the picture; `window.__probe.sfx` publishes them; `profile-wrap render` reads them, places each role's WAV from `sfx/` with its onset
on the cue, sums them, gains the mix to -16 LUFS integrated under a -1.5 dB peak limiter (`assets/sfx-mix.wav`), and HyperFrames plays it as
one `<audio>` track (a fade-out lane at the end, a duck lane under any owner-supplied sound). `render.json` records the cue count, the roles, the
premaster and master loudness and the delivered MP4's own loudness and true peak. Cues the template makes: whoosh on every dissolve, click on a
click, tick as a meter fills, key taps on terminal typing, thump on the result and on a camera shake, splash on a burst, pop on a bubble,
sparkle on a landing number. HyperFrames' own mixer sets the final level of the MP4; read `render.json` `audio` for the delivered values.

| File (`sfx/`) | Role | Source and licence |
|---|---|---|
| click, tick, key, whoosh, thump, pop, splash, sparkle (`.wav`, 44.1 kHz mono) | the roles above | computed in code by `sfx/make_sfx.py` (seeded, stdlib only, no recording or sample inside); the repository's licence |
| `make_sfx.py` | rewrites the eight files byte for byte | the repository's licence |

A post may add its own sounds as `sfx/<role>.wav` or as a separate `<audio>` clip when the owner supplies them (the NJ-Flush post plays the owner's
`flush-light.wav` from his NJ-Flush repository; that file is mixed from Mixkit recordings under the Mixkit Sound Effects Free License, per that
repository's README, and is not part of the template). Honest limits: the earshot skill's package and its shipped sound bank were NOT installed on
this machine, so no bank sound was used and no earshot reading (match, realness, sync sheet, critique) exists. The kit is made in code and checked
only by measurement (loudness, peak, cue-onset sample tests), never by ear. The owner listens.

## 7. Aspect variants

- Native: 1280x720 (16:9), the reference and the template.
- LinkedIn feed 4:5 (1080x1350): stack the layouts. Hook: headline on top (about 64 px, x = 64), device below, 520x1080 max. Section: kicker and headline
  (56 px) on top, the panel at 936 px wide below it, the device as a cropped strip or beside the panel in a 2-column 540/540 split only when
  its content stays 28 px or larger. Terminal text 28 px minimum at 1080 wide. Built for the NJ-Flush post (`--canvas 1080x1350`; the stage reads
  `--w` and `--h`; the layout coordinates are the post's own: kicker y 150, headline 112 and 80 px, panels 936 wide at x = 72, sub 36 px, footnote 26 px).
- Both layouts keep the progress bar and the dissolve unchanged.

## 8. Do and don't

Do: keep one accent word per headline; one result green; type the commands at 40 to 45 cps; dissolve between scenes in 8 frames; keep the device on
screen across steps; let the progress bar run linear; verify every command and claim shown on screen against its source before the render.

Don't: keep the reference palette as a default; copy the reference's face, logo, mascot, device footage, product copy or music; use any non-brand typeface; add springs, zoom or
camera moves; caption unspoken text; call any TTS or ASR model (Gemini is banned); use the personal Facebook or Instagram account; use red as an accent;
put the same accent colours on two neighbouring posts (the theme comes from each post's subject, section 0); flash more than once a film;
shake the camera except on a heavy hit.

## 8a. Authoring a post from the template (demo lessons, 2026-11-23)

A 30 s, five-scene silent post (hook, what heals, the risk, the check, the close) was built from the starter with no change to its look.
Set the film length only in the stage's `data-duration`; the script reads it (it was a second hard-coded `12` before). `.tl.miss` is the
orange line for a failing or warning terminal row, `.ic` is the Lucide icon slot (paste the icon's inner paths into an inline 24x24 svg).
Scene times live in `T`; add scenes by copying the `xfade` plus `rise` pattern, never by changing the dissolve length. Fonts come from the
workspace `brand.fonts` (`font_source: user_files` for the owner's own files, referenced in place, never copied into a tracked path).
A workspace cannot live inside the plugin directory (the CLI refuses it): use a folder outside the repo. `new-gif` writes the project
only; `render <slug>` also needs `drafts/<slug>/meta.json` with `video_project` set.

## 9. Evidence

Reference: 1280x720, 30 fps, 82.0 s, h264 + AAC. Analysis frames, pixel samples (`palette.py`), bounding boxes (`bbox.py`), frame-diff (`diff.py`) and
contrast (`contrast.py`) are in `work/styles-2026-11-23/console-stage/`. Rehearsal: `rehearsal/renders/video.mp4`, 1280x720, 360 frames, 12.0 s; sheet
`rehearsal_sheet.png` beside `reference_sheet_li_01.png`.


## 10. VFX kit (`fx.js`) and the NJ-Flush post (2026-11-23)

`PWFX({ tl, seeded, layer })` returns the effects, all seeded, on the one paused timeline, finite, ending invisible: `ripple` (an expanding ring), `burst`
(splash particles under gravity, plus a splash cue), `bubbles` (rising outlined circles that sway, optional pop cues), `pulse` (a glow breathes on an
accent element), `shine` (a light sweep through text with the `.shine` class), `shake` (a 1/30 s stepped, decaying camera shake on `#cam`, plus a thump
cue; heavy hits only), `count` (a number that runs between two values through a proxy tween, exact on any seek), `sparkles` (four-point stars that pop and
fade where a number lands), `drain` (a swirl that spins up while it shrinks). Colours come from the theme variables. At most one flash a film and never
red; the NJ-Flush post uses none.

The NJ-Flush post (`work/styles-2026-11-23/flush/`): 1080x1350, 30 s, English, on-screen text only. Theme derived from the owner's logo
(accent #2ebed3, result #59eb83); motif = the logo's swirl as a draining water vortex. Story: hook (RAM at 45%, 14.4 of 31.9 GB) -> one double-click (two
clicks 0.22 s apart, the flush sound under the second) -> four tiers fill like a meter (heavy and clogged shake) -> the real run (14.4 GB (45%) to 8.4 GB
(26%); free 17.5 to 23.5 GB; standby cache 17.4 to 0.5 GB: the Lead's measurement on one PC, v1.2.0, first run) -> how to get it, with the honest
not-code-signed line. Every other number and sentence is a fact from the NJ-Flush README.
