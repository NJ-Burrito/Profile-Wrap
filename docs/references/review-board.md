# Review board

`njli board` starts a small local web page where you look at each draft as it will appear on LinkedIn and
decide: **Allow**, **Reject** or **Improve**. It is a standard-library `ThreadingHTTPServer`; there is no
framework and nothing to install. This page is the reference for what it does, what it writes and what it
refuses. It is not legal advice; the safety contract is `compliance.md` and `docs/TERMS-AND-RISK.md`.

## Start it

```
njli board [--port N] [--open] [--workspace PATH]
```

- Binds `127.0.0.1` (or `::1`, `localhost`) only. `board.host` in the config must be one of those; anything
  else is refused at start.
- Default port `8770` (`board.port`). If it is taken the command says so, tells you to open the running board
  or pick `--port`, and exits with 1. `GET /api/health` answers `{"ok": true, "board": "nj-linkedin", ...}`
  without a token, which is how the second start recognises a board that is already running.
- A scheduler job (`board`, at login) runs the same command.
- Stop it with Ctrl+C. A draft left `revising` by a previous run is returned to `draft` at start.

From the terminal, without a browser: `njli review list|allow|reject|improve` use the same code as the buttons.
`allow` and `reject` ask for confirmation in a terminal, or take `--yes`. `allow` refuses when `NJLI_WORKER=1`.

## Statuses and decisions

Statuses: `draft`, `revising`, `hold`, `queued`, `missed`, `needs_check`, `posted`, `rejected`, `demo`.
`demo` and `posted` (and anything under `published/`) are read-only: every decision on them returns 409.

| Decision | Allowed from | What happens |
|---|---|---|
| **Allow** | `draft`, `hold`, `missed` | The gate must PASS (and the council, if `gate.require_council_pass`). Then `queued`. A missing or past `scheduled_at` comes back as a warning, not a refusal. Refused with 409 for `revising`, `queued`, `needs_check`, `rejected` and the read-only statuses. A worker can never allow (403 when `NJLI_WORKER=1`). |
| **Reject** | `draft`, `hold`, `queued`, `missed` | Needs `confirm: true` (the button asks twice). Then `rejected`. |
| **Improve** | `draft`, `hold`, `queued`, `missed` | A note is required. The draft becomes `revising`, a worker edits it, the board re-renders and re-gates, and it comes back as `draft`. Never auto-queued, whatever the worker wrote into `meta.json`. |

Two clicks racing for one draft get one winner and one 409: every decision re-reads the draft's `meta.json`
inside a lock (`work/posting.lock`, the same lock the posting code holds while it posts) and checks the status again.

Every decision appends one row to `review/decisions.jsonl` and one entry to `drafts/<slug>/review.json`.

### `review.json`

```json
{ "schema_version": 1, "verdict": "pass", "seats": [{"seat": "council-editor", "verdict": "pass"}],
  "merged_at": "...", "history": [{"at": "...", "action": "allow", "from": "draft", "to": "queued"}] }
```

`verdict` is the council result the gate reads when `require_council_pass` is on. The board builds it from the
seat files `drafts/<slug>/review/<seat>.json` (`pass` only if every seat passes, `blockers` if any seat has
blockers, else `revise`) just before an Allow. `history` is the decision log. A bare list from an older export is read as the history.

## Improve: the worker

1. The board sets `revising`, logs the note, queues the job and answers at once.
2. One background worker takes the job, builds the prompt from `prompts/improve.md` (the workspace copy wins),
   with the note inside `<<<NOTE ... NOTE>>>` markers that the note cannot close.
3. It runs the Claude worker through `claude_runner.run_job`: no Bash, tools `Read Glob Grep Edit Write`, a
   scrubbed environment, a turn and time cap, and the whole-tree guard of `sandbox.py`. The worker may change
   only `drafts/<slug>/` and its `video_project` (which must sit under `videos/`).
4. The board runs its own guard as well: every file outside those two folders is hashed first, and what changed
   or appeared is restored or deleted afterwards and logged as `RESTORED` in `review/jobs/<time>-improve-<slug>.log` and in the draft's history. Files the board itself wrote during the job (a click on another tab) are left alone.
5. For any format other than `text` it runs `njli render <slug>`, then the gate. The draft returns as `draft` with
   `last_revision`, `last_revision_gates` (`PASS` or `FAIL`) and, on failure, a one-line `review-reply.txt`.
6. A failed, crashed or timed-out worker is an error line, never a post stuck in `revising`.

If no Claude CLI is found, Improve answers 503 and changes nothing; edit by hand and run `njli gate <slug>`.
While `work/PAUSE` exists no worker starts.

## Tabs

| Tab | Source | Notes |
|---|---|---|
| Posts | `drafts/*`, `published/*` | A LinkedIn-style card (`dir` follows the post language), media from `out/`, first comment, alt text, gate result, council seats, history, the three decisions. |
| Comments to post | `engage/pending.json` | Copy, open, Done or Skip. Done appends one row to `published/comments.jsonl`, which the daily cap counts. |
| Connect | `engage/connect.json` | Note to copy, profile link, "I sent it" or Skip. The board has no invitation or message code; you click Connect on LinkedIn. |
| Profile fixes | `profile/steps.json`, `profile/progress.json` | Done state lives on the server. With no steps file the tab shows how to create an audit. Step links must start with `https://www.linkedin.com/` or they are not shown. |
| Metrics | `published/ledger.jsonl`, `metrics/track.jsonl` | Posted rows, the queue, the latest snapshot. |
| Settings | config, acknowledgements, `doctor` | Token-expiry banner, modes in effect after acknowledgement downgrades, doctor results, and the red **Pause everything** button (writes `work/PAUSE`; the posting and comment buttons write `work/PAUSE.posting` and `work/PAUSE.comments`). |

The UI is in `i18n/en.json` and `i18n/ar.json` (same keys; a test enforces it). It uses system fonts unless
`brand.fonts` lists files present in `brand/fonts/`. There is no `aria-live` over the feed, only over the toast. When a POST returns 403 (the board was restarted and the page holds an old token) the page shows
**Reload** and does not pretend the click worked.

## Security

- **Token.** A random token is made at every start and put in the page. Every POST needs it in `X-Review-Token`
  (403 otherwise, with `"reload": true`).
- **Host.** The `Host` header must be `127.0.0.1`, `localhost` or `[::1]` on the port in use, or the answer is 421.
  This defeats DNS rebinding.
- **Origin.** A POST without an `Origin` that names this server is refused with 403.
- **Bodies.** JSON only (415), at most 20,000 bytes (413). The body is read before any refusal, so a refused
  upload is never reset half way.
- **Files.** Only these routes serve files: `/media/<drafts|published>/<slug>/<file>` (images in that draft's
  `out/`), `/fonts/<file>` (`brand/fonts/`), `/avatar` (the configured identity photo, inside the workspace and not
  in `config/`, `profile/`, `research/`, `data/`, `work/` or `.git`), plus the app's own page, script, style and
  strings. Names are checked after one decode: no dot-first segment, no separator, no `%` left over, no drive
  colon, a strict character set, an image or font extension, and the resolved path (symlinks followed) must stay inside its folder. Everything else, including `research/`, `config/`, `profile/`, `.git` and `%2e%2e` tricks, is 404.
- **Headers.** `Content-Security-Policy` (`default-src 'none'`, scripts and styles from the board only, no
  inline code), `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`,
  `Cache-Control: no-store`. The page builds its DOM with text nodes only.
- **Writes.** Atomic (temp file then replace), under the shared lock. Appends use `O_APPEND`.
- **Reads.** A corrupt `meta.json`, `gates.json`, `review.json`, `connect.json`, `pending.json`, `steps.json` or
  ledger line gives a degraded 200 with the file named in `problems`, never a dropped connection.
- **Links.** Any URL shown to be opened must start with `https://www.linkedin.com/`.

## API

JSON over HTTP. GET needs no token; every POST needs the token and an Origin.

| Route | Answer |
|---|---|
| `GET /api/health` | liveness, version, busy job, pause flags |
| `GET /api/state` | the list: one row per draft (no captions), counts, pause flags; `ETag`, `If-None-Match` gives 304 |
| `GET /api/draft/<slug>` | caption, first comment, alt, media URLs, gate detail, seats, history |
| `GET /api/pending`, `/api/connect`, `/api/profile`, `/api/metrics`, `/api/settings` | the tabs |
| `POST /api/decision` | `{slug, action: allow\|reject\|improve, note?, confirm?}` |
| `POST /api/pending-done`, `/api/connect-done` | `{id, action: done\|skip}` |
| `POST /api/profile-done` | `{id, done: bool}` |
| `POST /api/pause` | `{kind: all\|posting\|comments, paused: bool}` |

Errors are `{"error": "<code>", "message": "..."}`; every code has a string in both languages.

### State cost

`/api/state` is rebuilt only when a stamp changes. The stamp is the mtime of `drafts/` and `published/` plus the
name, size and mtime of each draft's `meta.json` and `gates.json` (two `stat` calls a draft), reused for one second.
A change made through the board refreshes it at once. Each row is cached by those two files' stats, so after one edit
only that draft is read again; a cold build reads the files on eight threads. With 500 drafts the test budget is a
cold build under 6 s (it opens about a thousand files, which real-time virus scanners slow down), 304 under 0.25 s,
and one changed draft under 1.5 s.

## Files

Read: `drafts/*/{meta.json,gates.json,review.json,review/*.json,caption.txt,first_comment.txt,alt.txt,out/*}`,
`published/*`, `published/ledger.jsonl`, `engage/{pending,connect}.json`, `profile/{steps,progress}.json`,
`metrics/track.jsonl`, `config/njli.json`, `data/logs/notifications.jsonl`.
Written: `drafts/*/{meta.json,review.json,review-reply.txt}`, `review/decisions.jsonl`, `review/jobs/*.log`,
`engage/{pending,connect}.json` (status only), `published/comments.jsonl`, `profile/progress.json`, `work/PAUSE*`.
It never writes outside the workspace and never reads the config dir (secrets) except the expiry of the token through `doctor`.
