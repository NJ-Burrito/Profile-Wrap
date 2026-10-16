# Facts register (EXAMPLE: fictional persona Maya Rivera, not a real person)

This is the only place a number in a post can come from. A draft cites fact ids in `meta.claims`;
the gate then checks every number in the caption, first comment, alt text, slides and video text
against the cited, verified facts: same value, same unit.

How to use it:

1. Add a row with `profile-wrap facts add --claim "..." --numbers "30 minutes" --source notes/where-it-came-from.md`.
   New rows are `draft`.
2. Open a terminal and run `profile-wrap facts verify F01 --evidence <file or URL>`. Only you can do this; an
   agent cannot (`PROFILE_WRAP_WORKER=1` refuses, and so does a missing terminal).
3. Cite the id in a draft: `"claims": ["F01"]`.

Columns:

- `numbers`: each figure with its unit, separated by `;`. Write `7 bugs`, not `7`. Percentages are
  written `30%`. Dates and ids are not claims and do not belong here.
- `status`: `draft`, `verified`, `do_not_use` or `superseded`.
- `supersedes`: the id this row replaces. Mark the old row `superseded`.
- `demo`: `yes` for fictional rows like these. A demo fact never passes the gate in a live workspace.

Delete these example rows when you start your own register (`profile-wrap init` does this for you).

| id | claim | numbers | source | status | verified_by | verified_at | evidence | usage | supersedes | demo | added |
|---|---|---|---|---|---|---|---|---|---|---|---|
| F01 | Maya shortened the weekly status review for the fictional Lantern Data Co-op | 30 minutes | examples/notes/review-time.md | verified | demo | 2026-01-05 | examples/notes/review-time.md |  |  | yes | 2026-01-05 |
| F02 | A dashboard audit at the co-op found dashboards nobody opened | 7 dashboards | examples/notes/audit.md | verified | demo | 2026-01-05 | examples/notes/audit.md |  |  | yes | 2026-01-05 |
| F03 | The reminder template was tried by partner clinics | 3 clinics | examples/notes/pilot.md | draft |  |  |  |  |  | yes | 2026-01-06 |
| F04 | Maya's availability for new projects in spring | 1 project | examples/notes/availability.md | verified | demo | 2026-01-07 | examples/notes/availability.md |  |  | yes | 2026-01-07 |
