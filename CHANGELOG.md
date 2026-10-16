# Changelog

All notable changes to Profile-Wrap. The format follows [Keep a Changelog](https://keepachangelog.com/),
and versions follow [Semantic Versioning](https://semver.org/).

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
