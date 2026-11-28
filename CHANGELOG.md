# Changelog

All notable changes to Profile-Wrap. The format follows [Keep a Changelog](https://keepachangelog.com/),
and versions follow [Semantic Versioning](https://semver.org/).

## [0.6.0] - 2026-11-28

### Added

- New logo and app icon: a profile card wrapped by a rust band (`brand/`, drawn by `brand/make_brand.py`), used by the GUI, the review board and the site, with a real favicon set in place of the placeholder.
- The desktop GUI loads the workspace's brand fonts (`brand.fonts` in the config) the way the review board does, through `/assets/fonts.css` and `/fonts/<file>`; no font name or file is in the repository.
- Off-screen renderers for the GUI (`tools/render_gui.py`) and the review board (`tools/render_board.py`), and `media/make_media.py`, which rebuilds the README and site pictures from a throwaway demo workspace.

### Changed

- The desktop GUI is redesigned: stat tiles and a "next post" card on Home, a health-check list, a stepper on Connect, an update banner, empty states, dark mode and a narrow layout. About 125 strings that were hard-coded English now come from the English and Arabic string files. Same screens, controls and API calls.
- The review board is redesigned: cards with a status stripe, decision, gate and council cards, stat tiles for metrics, a progress meter on Profile, dark mode and a narrow layout; Arabic mirrors right to left. Same data, actions and API calls.
- The motion library `brand-kit/motion/core.js` is split into modules under `brand-kit/motion/core/`; `core.js` re-exports every name as before. Project sync and the motion upgrade copy and hash the `core/` folder too.
- README, site (English and Arabic) and `docs/GUI.md` describe 0.6.0, with new screenshots, hero and social card.

## [0.5.0] - 2026-11-23

### Added

- Narrated video styles: `profile-wrap new-gif <slug> --style console-stage` scaffolds a styled HyperFrames project from `brand-kit/templates/styles/*` (styles are discovered from that folder; an unknown style is refused with the list). `profile-wrap render <slug>` then delivers `drafts/<slug>/out/<slug>.mp4` (ffprobe-checked, atomic) and records `format: "video"` and the style in `render.json`. The GIF-only rules (loop seam, 250 frames, still-frame share, 4:5) do not apply to it. Set `visuals.default_style` to make a style the default for `new-gif` (empty by default: the plain GIF template).
- Console-stage is subject-driven: `new-gif --style console-stage --theme-from <logo or screenshot> [--theme theme.json] [--canvas WxH] [--subject ...] [--motif ...]` derives a contrast-checked theme (`profile-wrap visuals theme --from <img> [--out theme.json]`; Python standard library plus ffmpeg) and writes `theme.json` and `theme.css` into the project. The template reads only those tokens (no fixed navy or orange), takes any canvas, and has a motif slot.
- Console-stage VFX and SFX slots: `fx.js` (ripple, burst, bubbles, pulse, shine, shake, count, sparkles, drain; seeded, on the paused timeline) and a cue-synced sound kit (`sfx/make_sfx.py` computes the WAVs into the project at scaffold; no audio binary is stored in the template). `render` mixes the cues the composition logs into `assets/sfx-mix.wav` (-16 LUFS target, peak limited) and records the loudness in `render.json`.
- `new-gif` writes `drafts/<slug>/meta.json` (kept if it exists; `--force` rewrites it), so a fresh scaffold renders without hand-made metadata.
- `video` is a known draft format (meta, gate, build-week). It is not in `posting.formats_enabled` by default, and posting an MP4 through the LinkedIn API is not built yet. No voice engine is wired: narration timing is set by hand in the template.

## [0.4.1] - 2026-11-23

### Security

- A signature SVG with a DOCTYPE or ENTITY declaration is refused before it is parsed (stdlib ElementTree expands internal entities; found by the nj-whitehat scan).
- The board item id hash is marked `usedforsecurity=False` (it is an id, not a credential check).

## [0.4.0] - 2026-11-17

### Added

- Copy mode is the first-run default: `init` and the desktop app start new workspaces in copy mode (draft, gate, copy, paste by hand), with no LinkedIn developer app needed. Existing workspaces keep their mode. New `profile-wrap copy <draft>`.
- `profile-wrap copy <draft> --posted [--url URL]` records a post you pasted by hand: one ledger row, and the draft and its calendar entry become `posted`. A second call refuses. The review board has the same step as an "I posted it" button on copy-mode drafts.
- A guided Connect LinkedIn screen in the desktop app (Alt+6) and `profile-wrap auth connect [--lang ar]`: five checked steps for the developer app, products, redirect URL, client id and secret, and sign-in, with the re-sign-in date. Posting through the API stays opt-in.
- Copy mode gets due reminders. The `post_due` job is on by default and, unless `posting.mode` is an acknowledged `api_scheduled`, only reminds you: "a post is due" (again every 3 hours) and "post missed". It never posts and never calls LinkedIn. Turn it off with `schedule.jobs.post_due.enabled = false`.
- `profile-wrap auth check --online` asks LinkedIn once whether it still accepts your token. A 401 is remembered as "rejected" (also when it happens while posting) until you sign in again; a network error is "unknown", never a failure. `auth check --notify` raises one desktop notice a day when the token is expiring, rejected, expired or missing, and the daily `token_check` job now does both.
- `doctor` checks the plan: every planned day in the next 7 days needs a draft, a queued post or a posted row. A gap today or tomorrow is a FAIL, a farther one a WARN; an empty calendar is a WARN. The review board shows the same result as a banner on every tab. Set the window with `schedule.horizon_days` and `schedule.horizon_fail_days`.
- `doctor` also reports whether the scheduler is really working: jobs that should have run and did not, jobs that started and never finished, failed last runs, and the live registration on your system (Task Scheduler, systemd, cron, launchd). Every scheduled run records a heartbeat in `data/state/heartbeat.json`.
- `profile-wrap doctor --notify` sends one notification that lists the WARN and FAIL checks; the weekly `doctor_weekly` job uses it. Notifications are sent once per `schedule.notify_ttl_hours` (default 12) for the same problem, and a success clears the notice.
- `build-week` catches up: besides entries 8 to 14 days out it builds briefed entries 1 to 7 days out that have no draft (`--no-catchup` turns it off). A failed entry is retried on the next run and stops after 3 attempts (`schedule.build_max_attempts`) with the fix command. It checks that the render browser starts before it makes any model call.
- `calendar insert <date> ...` and `calendar shift --from DATE --days N`, both with `--dry-run`. Posted, skipped, blocked and `pinned` entries never move, a bilingual pair moves as one, and moves land on the next free posting day that is not a blocked holiday.
- Angle check for series: a calendar entry can carry a `subject`. `calendar validate` warns when a later post on the same subject repeats an earlier angle (`plan.angle_overlap_max`, default 0.5) or has no angle, and `plan.subject_min_gap_days` adds a minimum gap. The build prompt and the editor seat list the angles already used.
- Stale-fact guard: mark a fact `volatile` (a version, count or price; `facts add --volatile`). `profile-wrap facts stale [--days N]` lists volatile facts not re-read in the last 14 days, and the gate warns when a post cites one older than `gate.volatile_max_age_days`.
- New gate checks: `versions` (a version-like string must appear in a cited verified fact; `gate.versions`, warns by default), `first_comment_promise` (a caption that promises a link "in the first comment" fails when there is no first comment with a URL; `gate.first_comment_promise`) and `pair` (a bilingual pair must cite the same claims and stay in step; `gate.pair`, warns by default). See `docs/GATES.md`.
- `profile-wrap track week [--week 2026-W46]` writes the weekly numbers from your ledger (offline; a metric nobody measured says "not measured", never 0), with a weekly-read prompt (`track prompt`) and a `LEARNINGS.md` check (`track check`, `track init`). `pw-plan` reads `LEARNINGS.md` as a hint, and `/profile-wrap:week learn` runs the loop. The existing `track_daily` job now does something.
- A profile apply-by-hand checklist (`pw-setup`), a planning method for series about a tool or project, and the evidence references (`docs/references/evidence-scale.md`, `growth-evidence.md`).
- The new screens and messages are in English and Arabic (`gui_assets/i18n/`).

### Changed

- `post_due` is no longer refused outside `api_scheduled`; `schedule install --only post_due` needs only the job enabled in the config.
- Scheduler failure notices (failed, timed out, tool missing, crashed) are sent once per problem instead of on every run. An uncaught crash in a job writes its traceback to `data/logs/crash.log`.
- The write skill tells the writer to re-read the source on the day before citing a product, version, count, price or release fact, and to set `meta.pair` on both halves of a bilingual pair.
- `docs/SCHEDULING.md` and `docs/PLATFORMS.md` describe the reminders, the Windows sign-in and wake trade-off, and how to tell the scheduler is really working.

### Fixed

- A log file that cannot be written (locked or read-only) no longer fails or hides a job or a `build-week` run: it falls back to stderr and a separate log file.
- Windows scheduled tasks start `pythonw.exe` directly, and a test now forbids a `cmd` or `conhost` wrapper that hides the exit code.
- The growth council seat and the planning skill cited two reference files that did not exist; they do now, and a test checks that every reference an agent, skill, prompt or command cites exists.

### Removed

- The optional non-official readers (two third-party services and public-page reading) and the `read posts` command. Profile-Wrap now reads only through LinkedIn's official API. An old config that still sets the reading keys fails `config validate` with a message naming what to delete; `read` exits 2 with the reason.

## [0.3.1] - 2026-11-06

### Changed

- Python 3.11 or newer is required (3.10 reached end of life). The GitHub workflows now use `astral-sh/setup-uv` and uv instead of setup-python and pip, and Pillow is pinned to 13.0.0 or newer for every user, which closes the open Pillow security alerts.
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
