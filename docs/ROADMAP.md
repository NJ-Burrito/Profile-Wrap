# Roadmap

Dates are not promised. Order is. Written 2026-11-06 from two reviews of 0.3.1 (a devil's advocate and a product and engineering consultant). Both sit in the maintainer's Linkedin repo at `research/profile-wrap/review-2026-11-06-devil.md` and `review-2026-11-06-consultant.md`. Below they are called **devil** and **consultant**.

Everything under "Next", "60 days", "90 days" and "Proposed cuts" is a proposal for the maintainer to decide. Nothing here deletes code.

Value is H, M or L. Effort is S (days), M (1 to 2 weeks), L (a month or more).

## Now (done in 0.3.1)

- Python 3.11 floor, uv for installs, Pillow 13.0.0 security pin (CHANGELOG).
- Official-API posting, fact gate, review board, five skills, MCP server, desktop app (text drafts), offline demo.
- Docs made honest (this change): README, site and docs state the real setup and the real AI-helper options, say that the desktop app makes text drafts only, and drop "autopilot" and "your own ChatGPT account".
- Measured baseline (devil, consultant): 1 star, 15 unique visitors in 14 days, about 30 PyPI downloads a week. No user feedback yet.

## Next 30 days: first run and proof

| Item | Value | Effort | Backed by |
|---|---|---|---|
| Watch 3 non-technical people go from the release page to one real post, no help, timed. Everything else depends on it | H | S | devil #1 |
| ~~Copy mode as the default first run in the desktop app ("copy post, open LinkedIn"); API posting becomes opt-in~~ **Done 2026-11-07**: `init` starts new workspaces in `copy`, the app opens on the copy steps, Build has the copy buttons, `profile-wrap copy <draft>`; existing workspaces keep their mode | H | S | consultant 3 (#1), devil rework |
| Plain writing-helper chooser: "I have Claude Code", "I have an API key", "free local model" | H | S | consultant 5.4, devil #2 |
| Re-publish the MCP Registry entry (it shows 0.2.1, `server.json` is 0.3.1) | M | S | consultant 6.1 |
| Shrink the sdist (15.9 MB against a 0.66 MB wheel) with an include list | L | S | consultant 4 |
| Merge or group the 8 open dependabot PRs; add a CI check that README, pyproject and this file agree on the version | M | S | devil #5, consultant 7 |
| Make `auth` fail in plain words at each step | M | S | devil rework |
| A real 45-second screen recording in place of the concept GIF | M | S | consultant 5.1 |
| Submit to awesome-claude-code and awesome-mcp-servers | M | S | consultant 6.2 |
| Ask LinkedIn developer support whether own-account scheduled posting through `w_member_social` is allowed, and keep the answer | H | S | devil #3 |
| Two LinkedIn posts with a "tell me what broke" call, then count installs for 7 days | M | S | devil #6 |

Target: 5 first drafts finished by people who are not the maintainer.

## 60 days: close the loop

| Item | Value | Effort | Backed by |
|---|---|---|---|
| Voice profile from 5 past posts, with a before and after on the board (proves "in your voice") | H | M | consultant 3 (#2) |
| Analytics import and a weekly summary | H | M | consultant 3 (#3) |
| ~~Guided "Connect LinkedIn" screen with a live check per step~~ **Done 2026-11-07**: desktop screen and `profile-wrap auth connect`, English and Arabic, shows the re-sign-in date, never asks for a password | H | M | consultant 3 (#4) |
| LinkedIn preview card (mobile width, "see more" cut) | M | S | consultant 3 (#5) |
| Start Windows code signing and Apple notarisation | H | M (cost) | consultant 3 (#9), risk 3 |
| One article on the fact gate; 2 or 3 search pages with real screenshots | M | M | consultant 6.4 |

Target: 10 weekly users (self-reported) and one public quote.

## 90 days: pick the niche from evidence

| Item | Value | Effort | Backed by |
|---|---|---|---|
| Post-mortem loop at 72 hours that feeds the next week plan | M | M | consultant 3 (#7) |
| Idea inbox: paste a link or a bullet, get 3 angles | M | M | consultant 3 (#6) |
| Show HN or Product Hunt, only once copy mode and signed builds are live | M | S | consultant 6.2 |
| Decide with data: plugin-first, desktop-first or both. If the desktop app shows no uptake after 20 real tries, hold it at maintenance | H | S | devil #4, consultant 8 |
| Release 0.4.0 | M | M | consultant 8 |

## Proposed cuts (proposals only, nothing removed)

| Cut | Why | Backed by |
|---|---|---|
| Scraping readers (Apify, Tavily, public pages) | They contradict "official API only" and add legal risk and docs. Option: move them to a separate opt-in package | devil #3, consultant risk 2 |
| Codex plugin copy and duplicate skill trees | Skills live in 3 to 4 places and drift unless the build script runs. Option: generate on release only | devil #4 |
| Linux desktop build | 2 downloads, 31 MB. Wait until someone asks | devil, consultant |
| Directory chasing (Glama and similar) | Developers browse registries, the target reader does not | devil #6 |
| Four equal front doors in the README | Two doors: "I use Claude Code or Codex" (plugin) and "I do not" (desktop). Skills and MCP go under "More ways" | consultant 5.2, devil #4 |

Not planned: logging in to LinkedIn, driving a browser against it, reading messages, other networks (Postiz has 14 platforms; breadth is not winnable), video (was v1.1; defer), multi-profile agency mode until someone asks.

## Open questions for the maintainer

1. Who is the first user: developers who live in Claude Code (smaller surface, fits one maintainer), or non-technical professionals (needs copy mode, signed builds and a guided connect)? The devil argues for the first. The consultant would serve both with two front doors.
2. Keep `api_scheduled`? LinkedIn's API terms bar using the API to automate posting, and nobody has asked LinkedIn about own-account scheduling. Until there is an answer, click per post is the safe default.
3. Keep the scraping readers, move them out, or remove them?
4. Are most of the roughly 11 desktop and wheel downloads you? If so the real user count is near zero and the 30-day test matters more than any feature.
5. Fund code signing (Windows certificate, Apple developer account)?
6. One release a month, to cap the legal re-read and re-acknowledge cost of every wording change?
7. `pyproject.toml` still says "Alpha" and authors "profile-wrap contributors". Change them to match the README? Not touched here (metadata is out of scope for this change).
8. The Arabic site (`site/ar/`) still names "ChatGPT" as an AI helper. It needs the same fix and was out of scope here.

## Earlier plan (history)

v0.1 shipped the posting loop. The v0.2 items (research, profile, engagement, tracking) were not built as first planned. Analytics import lives on above as a 60-day item. The rest is parked until users ask.
