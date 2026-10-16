# Caption rules

These are the defaults. Limits come from `config/njli.json` (`gate.*`); the gate enforces what can be
checked by a program. The style preset (`plain`, `impact_copy`, `adhd_emoji`) changes the look, never
the rules below.

## Shape

- **Hook line first.** The first line is what shows before "see more". It must be under `gate.hook_max`
  (210) characters, and aim for `gate.hook_target` (40) or less. It names the topic or the payoff.
  It does not start with a greeting or "I'm excited to".
- **One idea per line.** Short lines. A blank line between blocks.
- **Length.** Under `gate.caption_max` (3000). For a post with a visual, 300 to 900 characters is
  usually enough; the visual carries the detail. A text-only post can run to 1,300 to 2,500.
- **Close once.** End with one specific question the reader can answer in a line, or end without a
  question. Never "Thoughts?", "Agree?" or "Comment below".

## Numbers

- Every figure comes from a verified fact cited in `meta.claims`: same value, same unit. See `docs/GATES.md`.
- Write the unit with the number: "7 dashboards", not "7".
- Round numbers (a dozen, hundreds) are still claims. Cut them or cite them.
- Dates, years, step numbers and list markers are fine without a claim.

## Links, tags and mentions

- **No link in the caption body.** Put it in `first_comment.txt`. The gate fails a URL, a `www.` host
  or a bare domain in the caption.
- **At most 3 hashtags** (`gate.hashtags_max`), Arabic ones included. Put them on the last line.
- Tag a person only with their agreement, and never a name that is in `persona.private_terms`.

## Words and marks

- No em dashes (fail). En dashes warn: write "8 to 16" or use a hyphen.
- No "it's not X, it's Y" or "this isn't X, it's Y" contrast. State the point.
- No banned words (`data/banned-words/en.json`, `ar.json`) and nothing on `persona.never_say`.
- No invisible characters, no private terms, no email addresses.
- No job-seeking phrases ("open to work") unless `persona.goal` is `job_seeking`.

## First comment

`first_comment.txt` holds the link, a short source line, or an extra detail. It passes the same gate as
the caption, except that a link is allowed. Keep it to one or two lines.

## Alt text

`alt.txt` is required for `slides` and `gif` posts. Describe what a reader would miss without seeing
it: what the chart or scene shows, in the post's language, in one or two sentences. It must not repeat
the caption, and any number in it needs a cited claim too.

## Bilingual pairs

Write the two languages together as one unit, each in its own `drafts/<slug>` folder (or the folders the
calendar names). Same claims, same facts, same hook idea, each in natural phrasing. Do not translate
word for word. Gate both; a fix to one side is applied to the other.
