# Changelog

All notable changes to nj-linkedin. The format follows [Keep a Changelog](https://keepachangelog.com/),
and versions follow [Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-10-16

First public release.

### Added

- Workspace creation: `njli init --demo`, `--express`, and `--answers a.json --yes` (resumable, replayable).
- Facts and stats registers; a claim-bound number gate (same value, same unit, verified by you in a terminal).
- Deterministic gates: slop words, private terms, never-say list, links, hashtags, invisible characters,
  Arabic hygiene (hamza, taa marbuta, Persian letters, tatweel, mixed numerals, bidi), render checks.
- Planning: calendar, per-post posting minutes inside your audience window, holiday presets, `build-week`.
- Visuals: slides to 2x PNG and PDF, looping GIFs with the motion library, banner, fonts and icons tools.
- A local review board on 127.0.0.1 and the same decisions in `njli review`.
- Official-API posting with your own developer app: `auth`, `selftest`, `post`, `due`, `status`, ledger-first
  sends, `needs_check` recovery, API version table with sunset warnings.
- Scheduling for Windows Task Scheduler, launchd, systemd, cron and a foreground daemon, with `--dry-run`.
- A headless Claude runner with a sandbox, a scrubbed environment and secret scanning of worker output.
- Safety: caps that config cannot raise, acknowledgements bound to the text hash, `pause`, endpoint and host allowlists.
- Template upgrades (`njli upgrade`) and idempotent migrations (`njli migrate`).
- Release gates: `njli leaks scan`, `njli compliance lint`, `njli doctor`.
- The demo: `njli demo run|up|down`, a fake LinkedIn, a fake `claude`, and the fictional persona Maya Rivera
  (12 facts, 14 calendar entries, one draft in every status, an Arabic post with its English twin).
- Claude Code plugin: five skills (`njl-setup`, `njl-plan`, `njl-write`, `njl-visuals`, `njl-ship`), six
  commands, review and writer agents, and a marketplace file.
- CI on Windows, macOS and Linux: tests, leak scan, compliance lint, and the README quickstart.

### Not in this release

- Research and profile tooling, engagement and tracking commands (planned for v0.2; see `docs/ROADMAP.md`).
- Video and narration pipelines (v1.1).
