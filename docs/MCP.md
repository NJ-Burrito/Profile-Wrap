# Profile-Wrap MCP server (`profile-wrap-mcp`)

A separate package (`mcp/`, PyPI name `profile-wrap-mcp`) that exposes a workspace to MCP clients over stdio.
Independent, not affiliated with LinkedIn.

## Connect

```bash
# Claude Code
claude mcp add profile-wrap -- uvx profile-wrap-mcp --workspace "<workspace folder>"
# Codex (config.toml)  [mcp_servers.profile-wrap]  command = "uvx"  args = ["profile-wrap-mcp", "--workspace", "<folder>"]
```

From a source checkout: `python -m profile_wrap_mcp --workspace <folder>` (install `mcp/` with `uv pip install -e mcp`).

## Tools and the posting rule

See `mcp/README.md` for the table. The one write path to LinkedIn is `post_allowed`:

1. The draft's status must be `queued` (the board's Allow) **and** its `review.json` history must end with a board
   `allow` decision. A hand-edited status is not enough.
2. `confirm=false` (default) returns the dry-run plan. `confirm=true` calls `profile_wrap.linkedin.post.publish`.
3. `publish` then enforces: posting not paused, no 429/403 stop, no other run holding the posting lock, draft not already in
   the ledger, the 20 h gap, a valid token and API version, gate PASS, a valid draft, and writes the ledger row before the
   first request. `posting.mode: copy` never sends.
4. The server adds a cap of one post a day.

Every other state is refused with a reason and nothing is written: `draft`, `revising`, `hold`, `rejected`, `needs_check`,
`missed`, `posted`, `demo`. Only a person can press Allow; the server has no allow, reject or verify tool.

## What it never does

Read direct messages, send connection invitations, comment, like, verify a fact, edit config, or return a key or token.

## Listing checklist (Lead, later)

- PyPI: publish `profile-wrap-mcp` (README carries `mcp-name: io.github.NJ-Burrito/profile-wrap-mcp`). Needs `profile_wrap` 0.2.x on PyPI first.
- Official registry: `mcp-publisher login github`, `mcp-publisher publish` from `mcp/` (`server.json` validates against the 2025-12-11 schema).
- Glama: `mcp/glama.json` goes in the repo root to claim ownership. Smithery: `mcp/smithery.yaml`; a stdio server may need an MCPB bundle instead (research 03, section 3b).
- Pin `profile_wrap` and `mcp` versions at release.
