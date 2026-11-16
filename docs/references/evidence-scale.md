# Evidence scale

How Profile-Wrap grades a finding about what works on LinkedIn, and what each grade allows. The council growth seat
(`agents/council-growth.md`), the planning skill and the trends prompt (`prompts/trends.md`) all use this scale.

## Grades

| Grade | Meaning | May be quoted in a public post |
|---|---|---|
| A | Primary source, measured: the publisher's own report or data, with a URL, a sample size and a date | Yes, when it is in `research/stats.md`, verified by you, and not expired |
| B | Reputable secondary: a credible outlet summarising a primary source you did not open | No. Use it as a second opinion |
| C | Anecdote or a single account's experience, or a secondary blog with no traceable original | No |
| X | Unverified, or the source could not be found | Never |

The grade belongs to the evidence for one finding, not to the publisher. A grade-A report can hold a figure that
is grade X because the report does not show how it was measured.

## Rules

1. Every finding carries a URL, a retrieval date and a grade. A finding without a source is `opinion`; say so.
2. Mark what you reasoned to, rather than read, as `INFERRED`. Never present a guess as a finding.
3. A third-party figure is quotable only when it is grade A, `verified` by the user, and unexpired. The gate
   enforces this for cited stats (`profile_wrap/gate/claims.py`).
4. Stats expire (`research.stats_expiry_days`, default 90). An expired figure is re-read from its source, not reused.
5. Studies describe other people's accounts. Your own numbers in `metrics/` beat them for your account, once
   there are enough posts to tell. A sample of fewer than ten posts supports no conclusion: call it a hypothesis.
6. A missing value is "not measured", never zero. Do not average over missing values.
7. When two sources disagree, record both and say which one a post may quote.

## Registers

- Your own facts: `research/facts.md`, verified by you (see `docs/GATES.md`).
- Third-party figures: `research/stats.md`, with `grade`, `retrieved` and `expires`.
- Findings Profile-Wrap ships with: `docs/references/growth-evidence.md`.
