---
description: Preview a post, or send one the user has allowed. Never sends without --now.
argument-hint: "<slug> [--dry | --now | --resolve --posted | --not-posted]"
---
Run `"${CLAUDE_PLUGIN_ROOT}/bin/profile-wrap" post $ARGUMENTS`. With no flag, or with `--dry`, it prints the
copy-ready block and every check and sends nothing. Only run it with `--now` when the user has just
asked to post this exact draft, and only if the draft is `queued` (Allow on the board sets that).
Show the output as it is. If it says `REFUSED`, give the reason and the one next step from the
pw-ship skill (`references/posting.md`). If the draft is `needs_check`, never retry: ask the user to
look at LinkedIn, then use `--resolve --posted` or `--not-posted`.
