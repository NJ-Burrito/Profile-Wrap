# Compliance contract

This file is the contract every skill, agent and command of Profile-Wrap follows. Its sha256 (together with `docs/TERMS-AND-RISK.md`) binds every acknowledgement you type with `profile-wrap config ack`. If this file changes in an update, the hash no longer matches and the affected action drops back to draft or notify until you accept it again.

Not legal advice. LinkedIn's terms change; read the current text yourself before you rely on anything here.

## What the package does

- It posts to your own profile through LinkedIn's official API, using your own free developer app and a token you create by signing in yourself.
- It drafts, gates and schedules your content. A person presses Allow before any draft can be queued, and the gate must pass first.
- It writes comment, reply and connection-note drafts for you to post by hand.

## What the package does not do (layer 1: no code path)

The following are not implemented, and `profile-wrap compliance lint` fails the build if code or skill text appears for them:

- Handling the account owner's LinkedIn sign-in secrets, browser sessions or stored login state.
- Driving a browser against linkedin.com. The renderer opens only local files or `127.0.0.1`.
- Reading or sending direct messages (any messaging endpoint).
- Sending connection invitations. The invitations API is partner-only; Connect is always a human click.
- Editing a profile or filling forms on LinkedIn.
- Rotating or faking a User-Agent. The package sends one neutral User-Agent and always sends the `Linkedin-Version` header.
- Hiding automation. Scheduling jitter and the time-of-day spread exist to match your audience's hours and to keep request rates low. They are not a way to look like a person, and every ledger row records the automation mode that produced it.
- Using third-party scheduling or session-based tools. See `automation-landscape.md`.

The only module allowed to reach the LinkedIn API host is `profile_wrap/linkedin/`, and it may call only `/v2/userinfo`, `/rest/posts`, `/rest/images` and `/rest/documents`. The legacy social-actions route exists only in the experimental extra described below.

## Hard ceilings (layer 2: `policy.py`, not configurable upward)

| Rule | Value |
|---|---|
| Comments plus replies per day | at most 10 |
| Comments per post | 1 |
| Gap between automated actions | at least 60 seconds, with a hard stop for the day on a 429 or 403 answer |
| Gap between posts | at least 12 hours (default 20); one post per `due` run |
| Posts per week | at most 7 |
| Connection slots waiting | at most 5; a note is at most 200 characters |
| Likes | off by default |

Counters come from one append-only log shared by API-posted and hand-posted items.

## Acknowledged opt-ins (layer 3)

Each needs a typed acknowledgement stored with the date and the hash of this file and `TERMS-AND-RISK.md`:

1. **Unattended posting** (`posting.mode = api_scheduled`). The API Terms restrict using the APIs to automate posting; whether that reaches a scheduled post to your own account is not defined in the text. You carry the risk.
2. **API comments and replies** (experimental extra only). The User Agreement restricts bots that comment or like. The route is undocumented and may be closed.
3. **Apify reader** (`profile-wrap config ack apify`). A third-party service that scrapes the Services, which the User Agreement restricts; it reads your own posts and the recent posts of profiles you choose. Capped per day and paced to the free monthly credit; it rests when the credit is gone. The token is read from an environment variable and goes only to api.apify.com.
4. **Public reader** (free, `engagement.reading.provider = "public"`, `profile-wrap config ack public`). It reads LinkedIn pages that open without a sign-in: the comments and counts of your own posts and the recent posts of profiles you choose to engage with. The User Agreement restricts scraping the Services. GET only, at least 3 s between pages, at most 30 pages a day by default, one fixed browser User-Agent, no Referer, no login state, no proxy, no redirects; HTTP 999, 429 or 403 on a post page stops it for the day. Guest profile pages are rate-limited per IP, so reads are spread across the day: at most 2 profile pages per run, 20 minutes apart (kept across runs), 12 a day, and a 999 on a profile page pauses profile reads for 6 hours.
5. **Tavily reader** (free plan, `engagement.reading.providers` includes `tavily`, `profile-wrap config ack tavily`). A web search service finds the recent public LinkedIn posts of profiles you choose; Profile-Wrap never opens LinkedIn for it. Whether that reaches the User Agreement's limit on scraping is not defined in the text. Paced to the calendar month (1,000 credits, 100 never spent), searches cached 3 days, one page per fetch. The key is read from an environment variable and goes only to api.tavily.com. Used together with Apify (Apify first) and the public reader (last).
6. **Likes.**

## Posting safety

- The gate re-runs immediately before the POST. A post that does not pass is refused.
- The post flow is ledger-first and idempotent: a `pending` row is written before anything is sent. A POST that errors or times out after sending, or a crash after the row is written, leaves the row `pending`. The next run marks it `needs_check` and never reposts. A person confirms on the board whether it went out. There is no blind retry.
- A 429 or 403 answer stops the run. Later runs honour the stop.
- The Bearer token is sent only to the LinkedIn API and OAuth hosts. It is never sent to the media upload host or to any other host.
- `profile-wrap pause` writes a kill-switch file; every job and API call checks it first and exits with code 4.

## Truth

- Numbers in a post must trace to a verified fact in your own register. Only you, in a terminal, can mark a fact verified.
- A passing gate shows traceability to your register, not that what is in the register is true.

## Privacy

- Tokens and the app's client secret live in the config directory with user-only permissions, never in a workspace or repository.
- Third-party data (names of people who engage with your posts) stays in the git-ignored `engage/` folder and is purged on the retention schedule. You are the controller of that data.

## Documentation honesty

Every document that quotes LinkedIn text keeps the quote short, attributed and dated, and says it is not legal advice.
