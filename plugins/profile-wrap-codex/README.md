# Profile-Wrap for Codex

Profile-Wrap is a fact-gated, compliance-first content pipeline for LinkedIn: it plans the week, writes
drafts that must pass deterministic gates, builds the visuals, and posts only after a person presses Allow
on the local review board. It uses the official LinkedIn API through your own developer app and nothing else.
This project is independent and not affiliated with LinkedIn.

This folder is the Codex plugin. It carries the same five capabilities as the Claude Code plugin, as
portable Agent Skills (`SKILL.md` with `name` and `description`):

| Skill | What it does |
|---|---|
| `pw-setup` | set up the workspace, run `profile-wrap doctor`, pause, upgrade |
| `pw-plan` | plan the week: strategy, calendar, posting windows, holidays |
| `pw-write` | write a draft and pass the gates (facts, style, Arabic hygiene) |
| `pw-visuals` | slides, GIF and banner, with the visual checks |
| `pw-ship` | review, Allow, queue, post and report; every refusal explained |

The skills call the `profile-wrap` command line, so install it first (`uv tool install profile-wrap`).
There are no hooks in this plugin. The optional read-only MCP server (`profile-wrap-mcp`) is configured
in `config.toml`; see `docs/CODEX.md` in the repository.

Install from a local checkout: `codex plugin marketplace add <path-to-profile-wrap>`.
Paths such as `docs/GATES.md` in the skills refer to the Profile-Wrap repository.
Licence: MIT.
