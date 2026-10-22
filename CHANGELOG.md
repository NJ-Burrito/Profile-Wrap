# Changelog

All notable changes to Profile-Wrap. The format follows [Keep a Changelog](https://keepachangelog.com/),
and versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Changed

- The GitHub repository is now NJ-Burrito/Profile-Wrap and the site is https://nj-burrito.github.io/Profile-Wrap/. Every link and display name says Profile-Wrap. Package names, the command and the plugin and registry ids stay lowercase `profile-wrap`.

## [0.3.0] - 2026-10-20

### Breaking

- The risk text changed, so every earlier acknowledgement is stale. Re-run `profile-wrap config ack <action>` for every
  acknowledgement you use (`apify`, `public`, and so on); until then that feature falls back to its safe mode.

### Added

- Optional update notifier. Every surface asks GitHub (one anonymous read of the public releases list, cached for an hour,
  3 s timeout; the desktop app and board check on a background thread) whether a newer release exists and says so inside that surface: a stderr line in the
  CLI (it reads the cache and refreshes on a background thread it waits for at most 0.3 s), a banner with What's new / Update / Skip this version / Later in the desktop app and the review board (English and
  Arabic), a `SessionStart` hook in the Claude Code plugin, an `update_status` MCP tool plus a notice in the server
  instructions, and a first step in the five skills. `profile-wrap update [check|news|apply|skip|later] [--json]` shows the
  release notes (plain parsing, no model call) and the exact command for your install method; `apply` asks y/N first and
  only runs for `uv tool`, `pipx`, `pip` and git clones. Nothing is ever updated unless you choose. Off with
  `updates.check = false` or `PROFILE_WRAP_NO_UPDATE_CHECK=1`, and off under CI and in tests. See `UPDATING.md` and
  `docs/PRIVACY.md`.
- `profile-wrap read posts <profile-url> [--json] [--text]` lists a person's recent posts through the readers you switched on.
- Free `public` reading provider (`engagement.reading.provider = "public"`): reads the public LinkedIn pages of your
  own posts (counts, comments) and of profiles you choose, with no third party. Opt-in with
  `profile-wrap config ack public`; GET only, 3 s between pages, 30 pages a day by default, stops on HTTP 999/429/403 (profile pages: 2 per run, 20 minutes apart, 12 a day, 6-hour pause after a 999),
  no Referer, no login state, no proxy. `profile-wrap doctor` shows the provider in use. The risk text
  (`docs/references/compliance.md`, `docs/TERMS-AND-RISK.md`) changed, so earlier acknowledgements ask to be accepted again.
- Two free readers that complement each other: `engagement.reading.providers = ["apify", "tavily", "public"]` (any subset,
  in this order, `public` last). Apify first for same-day posts, paced so its free monthly credit lasts the billing cycle;
  Tavily (`profile-wrap config ack tavily`, key from the environment variable named in `reading.tavily.key_env`) fills the
  people and days Apify does not cover, paced so 1,000 free credits last the calendar month with a 100-credit reserve,
  a 3-day search cache, a ledger that fails closed and one URL per extract call. A reader that cannot answer hands over
  to the next. `profile-wrap doctor` lists each reader and what it may still spend today, with no network call.
  `api.tavily.com` is reachable only with its own acknowledgement. New module `profile_wrap/linkedin/readers.py`.
- The experimental comments extra repeats a comment once with the `ugcPost` address when LinkedIn answers 400 `actual threadUrn`
  (posts with media).

### Changed

- The public reader sends the neutral `profile-wrap/<version>` User-Agent (no browser look-alike); `http.request` no longer lets a caller replace it.
- Tavily `topic` defaults to empty; the doctor makes no network call; a bought Tavily text is cached; `tvly-` keys are caught by the leak scan.
- The Apify risk text now says it also reads the recent posts of profiles you choose (it said own content only), so a
  stored Apify acknowledgement asks to be accepted again.

## [0.2.1] - 2026-10-16

### Fixed

- Release pipeline: the MCP package publishes to PyPI from its own environment (`pypi-mcp`), because PyPI allows one
  trusted publisher per repository, workflow and environment. The GitHub Release no longer waits on PyPI.

## [0.2.0] - 2026-10-16

### Added

- Desktop app: `profile-wrap gui` opens a local window (Home, Board, Providers, Build, Settings), light and dark,
  keyboard navigation. Downloadable builds for Windows, macOS and Linux on every GitHub Release (unsigned for now;
  see `docs/INSTALL-DESKTOP.md`).
- Any AI provider: Anthropic, OpenAI, OpenRouter, Google Gemini, local Ollama, or your own Claude Code. Keys are
  stored in the operating system keychain and only ever sent to the provider you chose (`docs/PROVIDERS.md`).
- `profile-wrap-mcp`: a separate MCP server with 8 tools; it posts only drafts you already Allowed on the board
  (`docs/MCP.md`).
- Claude Code plugin in `plugins/profile-wrap/` and an OpenAI Codex plugin with portable Agent Skills
  (`docs/CODEX.md`).
- Release pipeline: PyPI trusted publishing for `profile-wrap` and `profile-wrap-mcp`, SHA256SUMS and build
  provenance; listing kits and privacy policy (`docs/DISTRIBUTION.md`, `docs/PRIVACY.md`).

## [0.1.1] - 2026-10-16

### Changed

- Renamed from nj-linkedin to Profile-Wrap: package `njli` is now `profile_wrap`, the command `njli` is now
  `profile-wrap` (short alias `pw`), `NJLI_*` environment variables are now `PROFILE_WRAP_*`, skills `njl-*` are
  now `pw-*`, `config/njli.json` is now `config/profile-wrap.json`, and the repository is NJ-Burrito/profile-wrap.

## [0.1.0] - 2026-10-16

First public release.

### Added

- Workspace creation: `profile-wrap init --demo`, `--express`, and `--answers a.json --yes` (resumable, replayable).
- Facts and stats registers; a claim-bound number gate (same value, same unit, verified by you in a terminal).
- Deterministic gates: slop words, private terms, never-say list, links, hashtags, invisible characters,
  Arabic hygiene (hamza, taa marbuta, Persian letters, tatweel, mixed numerals, bidi), render checks.
- Planning: calendar, per-post posting minutes inside your audience window, holiday presets, `build-week`.
- Visuals: slides to 2x PNG and PDF, looping GIFs with the motion library, banner, fonts and icons tools.
- A local review board on 127.0.0.1 and the same decisions in `profile-wrap review`.
- Official-API posting with your own developer app: `auth`, `selftest`, `post`, `due`, `status`, ledger-first
  sends, `needs_check` recovery, API version table with sunset warnings.
- Scheduling for Windows Task Scheduler, launchd, systemd, cron and a foreground daemon, with `--dry-run`.
- A headless Claude runner with a sandbox, a scrubbed environment and secret scanning of worker output.
- Safety: caps that config cannot raise, acknowledgements bound to the text hash, `pause`, endpoint and host allowlists.
- Template upgrades (`profile-wrap upgrade`) and idempotent migrations (`profile-wrap migrate`).
- Release gates: `profile-wrap leaks scan`, `profile-wrap compliance lint`, `profile-wrap doctor`.
- The demo: `profile-wrap demo run|up|down`, a fake LinkedIn, a fake `claude`, and the fictional persona Maya Rivera
  (12 facts, 14 calendar entries, one draft in every status, an Arabic post with its English twin).
- Claude Code plugin: five skills (`pw-setup`, `pw-plan`, `pw-write`, `pw-visuals`, `pw-ship`), six
  commands, review and writer agents, and a marketplace file.
- CI on Windows, macOS and Linux: tests, leak scan, compliance lint, and the README quickstart.

### Not in this release

- Research and profile tooling, engagement and tracking commands (planned for v0.2; see `docs/ROADMAP.md`).
- Video and narration pipelines (v1.1).
