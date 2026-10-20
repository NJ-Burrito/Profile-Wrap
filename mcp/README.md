# profile-wrap-mcp

<!-- mcp-name: io.github.NJ-Burrito/profile-wrap-mcp -->
mcp-name: io.github.NJ-Burrito/profile-wrap-mcp

A stdio [MCP](https://modelcontextprotocol.io) server for a [Profile-Wrap](https://github.com/NJ-Burrito/profile-wrap) workspace.
It lets an MCP client (Claude Code, Codex, any other) check the workspace, draft a post from a topic, run the
fact gate, manage unverified facts and read the review board. It can also post, but **only a draft a person
already pressed Allow on, on the review board**.

Independent, open source (MIT). **Not affiliated with LinkedIn.** The server talks to LinkedIn only through the
official API with your own developer app, and only inside `post_allowed`.

## Tools

| Tool | What it does | Writes |
|---|---|---|
| `workspace_status` | posting mode, pauses and stops, 20 h gap, token state, draft counts, posts today | nothing |
| `update_status` | is a newer release on GitHub, and what is new (optional; installs nothing; one cached anonymous read) | nothing |
| `calendar_list` | content-calendar entries, optional status filter | nothing |
| `draft_create` | new text draft from a topic with your chosen provider; verified facts only; state `draft` | `drafts/<slug>/` |
| `gate_run` | the deterministic gate on a draft (numbers, claims, language, banned patterns) | `gates.json` |
| `facts_list` | the fact register with each fact's status | nothing |
| `facts_add` | adds a fact as **unverified**; a person verifies it in a terminal | `research/facts.md` |
| `review_state` | review-board state of one draft or all, and whether it was Allowed | nothing |
| `post_allowed` | posts one board-Allowed draft; `confirm=false` (default) is a dry run | ledger, draft status |

Resources: `pw://calendar`, `pw://drafts`, `pw://drafts/{slug}`.

## Safety

- `post_allowed` refuses every state except `allowed` (draft, revising, hold, rejected, needs_check, missed, posted, demo),
  and refuses an `allowed` status that has no board Allow as the latest entry in the review history.
- It calls `profile_wrap.linkedin.post.publish`, the same function as `profile-wrap post --now`: gate PASS, 20 h gap,
  one post a day, posting lock, 429/403 stop, pauses, and the ledger row written before anything is sent.
- No tool reads direct messages, sends connection invitations, comments, likes or verifies a fact.
- No key or token is ever returned. `draft_create` sends the topic and your verified facts to the provider you chose.

## Install

```bash
uvx profile-wrap-mcp --workspace /path/to/your/workspace
claude mcp add profile-wrap -- uvx profile-wrap-mcp --workspace /path/to/your/workspace
```

Without `--workspace` the server uses `PROFILE_WRAP_WORKSPACE`, then the usual Profile-Wrap lookup.
More: [docs/MCP.md](https://github.com/NJ-Burrito/profile-wrap/blob/main/docs/MCP.md).
