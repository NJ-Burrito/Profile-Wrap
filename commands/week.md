---
description: Plan the week on LinkedIn: strategy, calendar, posting slots, and (on your yes) the weekly draft build. Drafts only; nothing is posted or queued.
argument-hint: "[weeks ahead | build | dry-run | learn]"
---
Use the `pw-plan` skill. Read `${CLAUDE_PLUGIN_ROOT}/docs/references/compliance.md` first.

Arguments: `$ARGUMENTS`

- No argument: look at the next four weeks of `strategy/calendar.json`, say what is planned, what is open
  and what is blocked, and propose the next week's posts.
- A number: plan that many weeks ahead (`profile-wrap calendar fill --weeks N`, then fill the open slots with the user).
- `dry-run`: run `"${CLAUDE_PLUGIN_ROOT}/bin/profile-wrap" build-week --dry-run` and show what it would build. This spends
  no model tokens.
- `learn`: run `"${CLAUDE_PLUGIN_ROOT}/bin/profile-wrap" track week`, then `track prompt` and do the weekly read it
  describes, then `track check`. Numbers that were not measured stay "not measured"; nothing is guessed.
- `build`: show the dry run first. On the user's yes, run `"${CLAUDE_PLUGIN_ROOT}/bin/profile-wrap" build-week`.

Report what was built, what failed and why, and point the user at the review board
(`/profile-wrap:board`). A build never queues a draft; only the user's Allow does.
