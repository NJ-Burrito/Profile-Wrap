# Posting reference

## Statuses

`draft`, `revising`, `hold`, `queued`, `missed`, `needs_check`, `posted`, `rejected`, `demo`.
`posted` and `demo` are read-only. Only Allow sets `queued`. Improve returns a draft to `draft`.

## Formats sent

| meta.format and assets | Sent as |
|---|---|
| `text`, no assets | text post |
| `image` or `gif`, one png/jpg/gif | single image (a GIF is an image upload) |
| `slides` or `multi_image`, 2 to 20 images | multi-image post; `alt.txt` may have one line per image |
| `document`, one PDF | document post, title from `meta.document_title` or `meta.title` |

Assets are looked up in the draft folder, then `out/`. Links go in `first_comment.txt`, never in
the caption. Commentary is escaped for LinkedIn's "little text" format (reserved characters, and
hashtags as entities, Arabic and underscore tags included). Visibility is `posting.visibility`.

## The ledger

`published/ledger.jsonl` is append-only. One post is one idempotency key; each change appends a
complete row with the same key. States: `pending`, `posted`, `needs_check`, `confirmed`, `failed`.
Readers keep the latest row per key. `automation.mode` and `automation.by` are recorded on every
row. The gap guard and the daily counters read only this file.

## Refusals and what they mean

| Message starts | Meaning | Exit |
|---|---|---|
| `gap guard` | last post is newer than `min_gap_hours` | 0 |
| `already in the ledger` | one draft, one post | 0 |
| `draft status is ... not 'queued'` | press Allow on the board first | 0 |
| `another post run is in progress` | the lock is held | 0 |
| `LinkedIn stopped the last request` | a 429 or 403 stop is active | 0 |
| `the gate does not pass` | fix the draft, the gate re-runs | 1 |
| `no access token` / `expired` | run `njli auth` | 1 |
| `... sunset` | set `linkedin.api_version` to `auto` or newer | 1 |
| `ledger is not writable` | nothing was sent; fix the disk, retry | 1 |
| `upload failed before posting` | nothing was posted; the draft stays queued | 1 |
| `LinkedIn rejected the post` | the draft is put on `hold` with the reason | 1 |
| paused | `njli resume` | 4 |

## Lock and recovery

The lock file is `work/posting.lock` (`O_EXCL`, PID liveness, stale after 30 minutes). Every check
runs inside it, so two concurrent runs cannot both post. At the start of every run, any `pending`
row without a result becomes `needs_check`. If the ledger cannot be written after a successful post,
`work/posting-recovery.json` holds the post address and the user is notified.

## The board and other writers

The board (and anything else writing `meta.json` or the ledger) takes the same lock file.
