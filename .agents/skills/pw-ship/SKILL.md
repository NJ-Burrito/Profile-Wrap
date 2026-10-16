---
name: pw-ship
description: Review, allow, queue, post and report. Use for "review board", "allow", "reject", "improve", "post it", "queue", "schedule", "automate", "token", "api version", "missed post", "needs check", "report" or "what went out". Runs the ledger-first post flow on the user's own LinkedIn developer app and explains every refusal.
---

# pw-ship

Take a draft that passed its gate to a live post, safely, and keep an honest record. Work the
staged way: analyse the ask, look up before improvising, plan with file checkpoints, run, review
against the request. The ledger is the checkpoint: `published/ledger.jsonl`.

The command is `profile-wrap` (install with `uv tool install profile-wrap`, or from the release; check with `profile-wrap --version`).

## Compliance first

Read `references/compliance.md` in this skill folder before anything else. Posting goes through
the official LinkedIn API on the user's own developer app, nothing else. Refuse any request to log
in to LinkedIn, drive a browser against it, read or send messages, send invitations, edit the
profile, or hide automation, and offer the draft-only alternative. If the user offers a LinkedIn
login secret, tell them it is never needed and never stored.

## Human gates (never skipped, never done for the user)

- A build never sets `queued`. Only the user pressing Allow does, and Allow needs a gate PASS.
- You never run `profile-wrap post --now`, `profile-wrap due`, `profile-wrap auth` or `profile-wrap config ack` on your own. Show the
  command and let the user run it, or run it only when the user has just asked for exactly that.
- A typed acknowledgement is typed by the user, in a terminal. Never type it for them.

## Entry modes

| The user says | Do this |
|---|---|
| "what is ready", "status" | `profile-wrap status`; summarise token, API version, mode, queue, `needs_check` |
| "show me the post", "copy it" | `profile-wrap post <slug> --dry`: the copy-ready block (caption, first comment, alt text, media) and every check, nothing sent |
| "post it now" | confirm the draft is `queued`, then `profile-wrap post <slug> --now` (the user's call) |
| "schedule", "automate" | explain the three modes below; unattended posting needs the typed acknowledgement |
| "board", "allow", "reject" | `profile-wrap board`; decisions are made there (see `references/posting.md`) |
| "token", "sign in", "expired" | `profile-wrap auth check`; `profile-wrap auth` (user runs it); `docs/linkedin-app-setup.md` |
| "api version", "sunset" | `profile-wrap api-versions`; `--refresh` looks for newer ones; a human re-checks dates |
| "did it go out?", "needs check" | see Needs check |
| "what went out", "report" | read `published/REPORT.md` and the ledger; do not invent numbers |

## Posting modes (`posting.mode`)

- `copy`: no API. Produce the copy-ready block.
- `api_click` (default): the user presses Allow, then Post now. A person starts each post.
- `api_scheduled`: the `due` job posts at the slot. Needs a typed `api_scheduled` acknowledgement
  bound to the hash of the risk text; read `docs/TERMS-AND-RISK.md` to the user first. If the text
  changed since they accepted, the mode drops to `api_click` until they accept again.

With `copy` or `api_click`, the scheduled `due` job only notifies when a slot arrives.

## The flow, in the order it runs

Gate re-run, refuse a slug already in the ledger, minimum gap (12 h floor, 20 h default), take the
lock, write a `pending` ledger row, upload media, POST once, complete the row, then the optional
first comment, then `meta.status = posted`. Nothing is moved on disk. Details and every refusal
message: `references/posting.md`.

Never retry a post by hand-editing the ledger. If something is unclear, the answer is
`needs_check`, not a second POST.

## Needs check

A POST that errored or timed out after sending, or a run that died after the `pending` row, leaves
the draft `needs_check`. It is never reposted. Ask the user to open LinkedIn and look, then record
what they found: `profile-wrap post <slug> --resolve --posted [--url <address>]` or `--not-posted`
(the draft returns to `draft`; the user allows it again if they still want it out).

## Guard refusals are not failures

A refused gap guard, a slug already posted, a held lock or a draft that is not `queued` prints
`REFUSED ...` and exits 0. A failed gate, a missing or expired token, a sunset API version or a
rejected post exits 1 and says what to do. A pause exits 4. A 429 or 403 writes a stop that later
runs honour; do not work around it.

## Tokens and versions

The token lasts about 60 days and cannot be refreshed. `profile-wrap doctor` and the board warn from 10 days
before. `Linkedin-Version: auto` picks the newest version in the dated table; a sunset version is
refused before any request. See `references/token-and-versions.md`.

## The experimental extra

Comments through the legacy social-actions route are not part of the core and never claimed to
work. `profile-wrap selftest comments` makes one non-posting probe. Do not enable the mode; describe it from
`docs/references/community-management-api.md` if asked.

## Report once

End with what was posted or refused, the link, and what the user must do next. Say "not verified"
where nothing checked it.
