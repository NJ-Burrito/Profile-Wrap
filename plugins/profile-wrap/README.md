# Profile-Wrap (Claude Code plugin)

Profile-Wrap helps you plan, write, check and ship LinkedIn posts from Claude Code, inside LinkedIn's terms.
Every claim in a draft must trace to a fact you supplied, a deterministic gate checks the caption before anything
can be queued, Arabic and English are both first-class, and a local review board is the only place a draft becomes
"Allowed". Posting uses the official LinkedIn API through a developer app that you own. Nothing is automated
behind your back, and every connection invite stays a human click.

Profile-Wrap is an independent open-source project. It is not affiliated with, endorsed by or sponsored by LinkedIn.

## What is in this plugin

| Part | Names |
|---|---|
| Skills | `pw-setup`, `pw-plan`, `pw-write`, `pw-visuals`, `pw-ship` |
| Slash commands | `/profile-wrap:setup`, `:week`, `:board`, `:post`, `:pause`, `:doctor` |
| MCP server | `profile-wrap`, launched with `uvx profile-wrap-mcp==0.2.1` (needs `uv`) |

The skills and commands drive the `profile-wrap` command line tool, which does the real work on your machine.

## Install

1. Install the tool: `uv tool install profile_wrap` (Python 3.10 or newer).
2. In Claude Code: `/plugin marketplace add NJ-Burrito/profile-wrap`, then `/plugin install profile-wrap@profile-wrap`.
3. Run `/profile-wrap:setup demo` for a no-account tour, then `/profile-wrap:doctor` to check your machine.

## Privacy

- Your workspace (drafts, facts, ledger) stays in a folder on your computer.
- Profile-Wrap has no server and no telemetry. It sends data only to LinkedIn's official API when you post, and to
  the AI provider you choose, with your own key.
- API keys live in your operating system keychain, never in files, logs or the ledger.
- The plugin reads no messages and never collects LinkedIn passwords.

Full policy: https://github.com/NJ-Burrito/profile-wrap/blob/main/docs/PRIVACY.md

## Licence

MIT, see `LICENSE`. Source and issues: https://github.com/NJ-Burrito/profile-wrap
