# Profile-Wrap with OpenAI Codex

Profile-Wrap is independent and not affiliated with LinkedIn or OpenAI. The Codex plugin carries the same five
capabilities as the Claude Code plugin: `pw-setup`, `pw-plan`, `pw-write`, `pw-visuals`, `pw-ship` (set up, plan
the week, write with gates, visuals, ship with Allow). The skills are portable Agent Skills (`SKILL.md` with
`name` and `description`) that call the `profile-wrap` command line. The plugin has no hooks, which keeps it
eligible for OpenAI's public plugin directory.

## 1. Install the command line

```
uv tool install profile-wrap
profile-wrap --version
```

## 2. Add the skills

Pick one.

**As a plugin (any folder):**

```
codex plugin marketplace add NJ-Burrito/profile-wrap     # or a local path to a checkout
codex plugin add profile-wrap-codex@profile-wrap
```

Codex reads `.agents/plugins/marketplace.json` at the repository root, which points at
`plugins/profile-wrap-codex/`.

**As repository skills:** open Codex inside a checkout. It scans `.agents/skills/` from the current folder up to
the repository root, so the five skills are found with no install. Copy `.agents/skills/` to
`~/.agents/skills/` to have them in every project.

Skills with the same name do not merge, so use one route at a time.

## 3. Optional: the read-only MCP server

`profile-wrap-mcp` (facts lookup, caption gate check, board status, calendar) has no posting tool; posting stays
in the CLI. Add it to `~/.codex/config.toml`, or to `.codex/config.toml` in a trusted project:

```toml
[mcp_servers.profile-wrap]
command = "uvx"
args = ["profile-wrap-mcp==0.2.0"]
startup_timeout_sec = 30
tool_timeout_sec = 60
```

Or add it from the command line: `codex mcp add profile-wrap -- uvx profile-wrap-mcp==0.2.0`. Pin the version.
The server is a local stdio process, so it is not part of the plugin that goes to a public directory.

## 4. AGENTS.md section for your workspace

Paste this into the `AGENTS.md` of the folder where you run `profile-wrap init`:

```markdown
## Profile-Wrap rules

- Use the `pw-setup`, `pw-plan`, `pw-write`, `pw-visuals` and `pw-ship` skills for content work.
- Official LinkedIn API through the user's own developer app only. Never log in to LinkedIn, drive a browser
  against it, read or send messages, send invitations, edit the profile or hide automation.
- Build drafts, never queue them. Only the user pressing Allow on `profile-wrap board` queues a draft.
- Never run `profile-wrap post --now`, `due`, `auth` or `config ack` on your own; show the command instead.
- Numbers come from `research/facts.md` and carry a verified source. Do not invent one.
- Run `profile-wrap gate <slug>` before calling a draft ready. Say "not verified" where nothing checked it.
```

## 5. Differences from the Claude Code plugin

- No slash commands, no hooks, no bundled council agents: the council seats in `pw-write` are review passes you run
  from the seat files in the repository's `agents/` folder.
- Questions are asked in plain chat; the setup interview resumes from `config/profile-wrap.json`.
- The skill folders carry their own copy of the compliance reference. Paths like `docs/GATES.md` refer to the
  Profile-Wrap repository.

## 6. Validate

```
npx skills-ref validate .agents/skills/pw-write        # each skill
codex plugin marketplace add <path-to-checkout>
codex plugin list                                      # shows profile-wrap-codex@profile-wrap
```

`tests/unit/codex/` checks the same rules offline.
