# Interview questions by step

Use AskUserQuestion: at most 4 questions per call, each with 2 to 4 options and a free-text
"Other". Ask in the language the user writes in. The answers go into the answers file
(`answers-file.md`).

## Step 1: Where (1 question)
- Where should the workspace live? Options: `~/nj-linkedin/<profile>` (default), another folder.
  The folder must be outside the plugin directory. Profile id: lower case letters, digits, `-`, `_`.

## Step 2: Who (7 questions in two batches; this is also the express path)
Batch A: name; public handle (the part after `/in/`); role or headline; niche or topic.
Batch B: audience (who reads); languages posted in (options: English; Arabic; both; other) and the
primary one; goal (authority, clients, job_seeking, hiring, network). Time zone is auto-detected:
confirm it in one line. Regions of the audience are optional.
- The goal changes profile rules, connection scoring and CTA wording. `job_seeking` is the only goal
  that allows job-seeking phrases.

## Step 3: Privacy (2 questions)
- Names that must never appear (employers, clients, products, internal hosts): `private_terms`.
- Any subject that needs a no-names rule (for example minors)? Add to `sensitive_rules`.

## Step 4: Facts (10 to 15 short questions, 4 per batch)
Ask for things the user can show proof of: roles and dates, counts they measured, results with a
number, credentials, projects. For each answer record `claim`, `number` (with its unit, or empty)
and `source` (where the proof is). Rows become `draft`. Do not round, guess or add numbers.

## Step 5: Voice (2 questions)
- Paste 3 to 5 past posts, or answer six style questions (sentence length, formality, humour,
  emoji use, how you open, how you close).
- Style preset: `plain` (no emoji rules), `impact_copy` (bold anchor, outcome with one true number),
  `adhd_emoji` (emoji-led short lines).

## Step 6: Brand (3 questions)
- Font source: open-licence default (fetched at setup), system fonts, or your own licensed files
  (give the file paths per role; they are never copied or uploaded).
- Palette: new colours per post, or one fixed palette.
- Identity card on or off; photo path (optional); signature none, typed or svg.

## Step 7: Cadence and caps (4 questions)
Show the defaults with the risk of raising each: posts per week (3, ceiling 7), comments plus
replies per day (3, ceiling 10), connection slots per week (3, ceiling 5), posting window (09:00 to
12:29 local). Holidays preset by region.

## Step 8: Models (2 questions)
- Tiered (lead, standard, economy) or one model for everything.
- Auth for headless runs: login, or API key (recommended unattended; scheduled runs use plan limits).
  Store only the **name** of the environment variable.

## Step 10: Mode consent (one card per action class)
Posting unattended, API comments and replies, the Apify reader, likes. Show the plain risk text
from `docs/TERMS-AND-RISK.md`. The user types the acknowledgement in a terminal with
`njli config ack <action>`. Never record it for them.
