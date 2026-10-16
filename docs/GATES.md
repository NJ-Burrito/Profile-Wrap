# Gates

`njli gate <slug>` runs deterministic checks on `drafts/<slug>/` and writes `drafts/<slug>/gates.json`.
No model is called. Exit code 0 is PASS, 1 is FAIL. A gate guarantees that a number can be traced to
your register of facts. It does not prove the register is true.

```text
njli gate my-post            # human output: PASS/FAIL line, then one FAIL or WARN line per finding
njli gate my-post --json     # the gates.json content
```

Allow (queueing a post) requires a PASS, and the gate runs again just before a post is sent. A build
can never set a post to `queued` on its own.

## What is read

| Surface | File | Notes |
|---|---|---|
| caption | `caption.txt` | the post body |
| first comment | `first_comment.txt` | gated too (`gate.first_comment_gated`); links are allowed here |
| alt text | `alt.txt` | required for `slides` and `gif` posts (`gate.require_alt_text`) |
| slides | `slides.html` | visible text, `alt`, `aria-label` and `title` attributes; scripts and styles are ignored |
| video | `meta.video_project` folder | text of every `.html` file, plus `.txt`, `.srt`, `.vtt` narration and captions |
| facts | `research/facts.md` (`persona.facts_file`) and `research/stats.md` | the registers the claims point at |

## Checks

| Check | Fails when | Config |
|---|---|---|
| meta | `meta.json` is missing, has a BOM, is not a JSON object, lacks `slug lang format pillar status claims`, the slug differs from the folder, the language or format is not allowed | `persona.languages`, `posting.formats_enabled` |
| facts | the facts file is missing, unreadable or has no table (a BOM is a warning) | `persona.facts_file` |
| claims | a cited id does not exist, is not `verified`, is a demo fact in a live workspace, or is a stat that is not grade A, is expired or not verified | |
| numbers | a number in any scanned surface is not proven by a cited claim (below) | `gate.numbers` |
| caption / hook | the caption is empty or longer than `caption_max`; the first line is longer than `hook_max` (warn above `hook_target`) | `gate.caption_max`, `hook_max`, `hook_target` |
| slop | a banned word or phrase, a "it's not X, it's Y" contrast, a `never_say` term, or invisible characters | `data/banned-words/*.json`, `gate.extra_banned`, `persona.never_say` |
| private_terms | a `persona.private_terms` entry appears on any text surface (case, spacing and zero-width characters do not hide it) | `persona.private_terms` |
| em_dash, en_dash | an em dash fails, an en dash warns | `gate.em_dash`, `gate.en_dash` |
| links | a URL, `www.` host or bare domain with any known TLD in the caption body (the first comment may hold links) | `gate.links_in_body` |
| hashtags | more than `hashtags_max`, Arabic hashtags included | `gate.hashtags_max` |
| job_seeking | "open to work" style phrases unless `persona.goal` is `job_seeking` | |
| contact | an email address anywhere; a phone-like number warns | |
| arabic | only when `meta.lang` includes `ar`: Persian letters, tatweel, bidi controls, Latin comma or question mark next to Arabic (mixed numeral systems warn) | |
| alt | alt text missing for a visual post | `gate.require_alt_text` |
| render | an asset is missing, the render is older than its source, PDF fonts fall outside the brand fonts or use Type 3, the PDF page count differs from the slide count, a GIF does not decode, has too many frames, is too large, too still, has a loop seam jump or flashes | `gate.gif`, `gate.required_font_substrings` |
| review | `gate.require_council_pass` is on and `review.json` has no passing verdict | |
| custom:... | a user gate in `hooks/gate_*.py` reported a failure | |

## Numbers: claim-bound

Every number in a public text must match the **value and unit** of a number in a cited, verified fact
(or a current, verified grade-A stat). A seven that appears somewhere else in the register proves
nothing: "7 bugs" fails when the cited fact says "7 dashboards" or when no fact is cited.

- Digits are normalised first: Arabic-Indic and Persian digits count as the same number.
- `30%` and `30 minutes` are different numbers. `10k` equals `10,000`.
- A fact whose number has no unit matches any unit; write units so a fact proves only what it says.
- If the text has no unit word after the number ("it took 30."), the value alone has to match.
- Number words ("seven bugs") are not checked and warn (`gate.numbers.number_words`: `warn`, `fail`, `off`).
- Bare digits below `gate.numbers.min_bare_digit` (10) with no unit warn; they are not proof.

These are not treated as claims: dates and times, years and months, version numbers, phone numbers
and ids, URLs, list markers (`1.`, `2)`), ordinals (`3rd`), ages ("aged 8"), labels such as "step 3" or
"chapter 2", and the post's own list counts ("5 tips"). The exact lists are in
`njli/gate/numbers.py`. If one of these is really a claim in your post, rewrite it or cite a fact.

## Overrides

A person can waive one named finding in `meta.json`:

```json
"overrides": [{"check": "numbers", "token": "7 bugs", "reason": "counted on the sprint board, screenshot kept"}]
```

- The `token` is the text shown in the FAIL line.
- A reason of at least 8 characters is required (`gate.overrides.require_reason`).
- At most `gate.overrides.max_per_post` (2) waivers apply; extra ones fail. `gate.overrides.allow=false` switches them off.
- Every waiver is written to `gates.json` under `overrides` with the reason and time, and the review board shows it.
- A waiver that matches nothing is reported.

## gates.json

```text
schema_version, slug, summary (PASS|FAIL), checked_at, lang,
claims, surfaces, user_gates, skipped,
checks      {name: {ok, detail}}
findings    [{check, severity (fail|warn|overridden), surface, token, message}]
fails, warnings   one readable line each
overrides   [{check, token, reason, applied, matched, at}]
input_sha256      hash of everything the gate read; a later step compares it to prove the PASS is current
```

## Tools that may be missing

`pdffonts`, `pdfinfo`, `ffprobe`, `ffmpeg` and Pillow are optional. With `gate.tools_missing` set to
`skip_with_warning` (default) a missing tool gives a WARN line with an install hint for your system and
that check is skipped. Set it to `fail` to make a missing tool a FAIL. The gate never ends in a traceback
because a tool, the facts file, the config or a BOM is missing; each gives a readable line.

## Facts and stats registers

```text
njli facts add --claim "..." --numbers "30 minutes" --source notes/x.md
njli facts lint
njli facts verify F01 --evidence notes/x.md        # terminal only
njli facts export [--verified-only]
njli stats add --stat "..." --numbers "60%" --url https://... --grade A
njli stats expire [--dry-run]
njli stats verify S01 --evidence https://...
```

`verify` refuses without an interactive terminal and refuses when `NJLI_WORKER=1`, which every agent
and scheduled job runs with. It asks you to type the id back. The verifier name and date are recorded.
"Verifier is not author" is a convention here, not something the software can enforce for one user.
Third-party stats must be grade A, verified and unexpired before a post may quote them.

## Comments, replies and connection notes

`njli.gate.check_text(text, kind, workspace, claims=[...])` applies the same text rules (slop, private
terms, links, dashes, Arabic hygiene, claim-bound numbers) to a short text. `kind` is `comment`, `reply`
or `note`. A note is limited to 200 characters and cannot hold a hashtag; the limit cannot be raised by
configuration.

## Your own gates

A file `hooks/gate_<name>.py` in the workspace may define
`check(draft_dir, meta, surfaces, cfg)` and return a list of strings (failures) or dicts
`{"severity": "fail|warn", "message": "...", "token": "..."}`. It is your code and runs with your rights,
so `njli doctor` lists such files. An error inside one becomes a FAIL line.
