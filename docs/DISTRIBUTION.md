# Profile-Wrap distribution: where it is listed and who does each step

Profile-Wrap is independent and **not affiliated with LinkedIn**. No listing, package or plugin name contains "LinkedIn",
"claude-" or "anthropic-"; "for LinkedIn" appears in descriptions only. Ready-to-paste texts: `docs/listings/`.
Privacy policy for every listing: `docs/PRIVACY.md`. Screenshots: `docs/assets/board.png`, `hero.gif`, `flow.svg`.

Who: **Lead/CI** = the build session or GitHub Actions; **The maintainer** = needs his own login or click.
Status values: `todo`, `ready` (files done, waiting for a step), `submitted`, `live`. Update the dated row after each step.

## Order

1. Release v0.2.0 (tag, GitHub Release, CI green). 2. PyPI `profile-wrap`. 3. PyPI `profile-wrap-mcp` (needs 2).
4. Official MCP Registry (needs 3). 5. mcp.so, Glama, Smithery (need the public repo; Smithery also needs the bundle).
6. Anthropic plugin directory (needs 3, because the plugin starts `uvx profile-wrap-mcp==0.2.0`).

## Status

| Directory | Needs first | Who | Status | Date | Link |
|---|---|---|---|---|---|
| PyPI `profile-wrap` | pending publisher, tag `v0.2.0` | The maintainer (once) then CI | todo | 2026-10-16 | |
| PyPI `profile-wrap-mcp` | PyPI `profile-wrap` live | The maintainer (once) then CI | todo | 2026-10-16 | |
| Official MCP Registry | PyPI `profile-wrap-mcp` live | The maintainer (login) | todo | 2026-10-16 | |
| mcp.so | public repo | The maintainer | todo | 2026-10-16 | |
| Glama | `glama.json` on `main` | The maintainer (claim) | ready | 2026-10-16 | |
| Smithery | MCPB bundle | Lead builds, the maintainer publishes | todo | 2026-10-16 | |
| Anthropic plugin directory | PyPI `profile-wrap-mcp` live | The maintainer (paid claude.ai) | ready | 2026-10-16 | |

## 1. PyPI, trusted publishing (no token stored anywhere)

Needs: a PyPI account and the repo `NJ-Burrito/profile-wrap` public. Files: `.github/workflows/release.yml` (package C),
`pyproject.toml` (name `profile-wrap`), `mcp/pyproject.toml` (name `profile-wrap-mcp`), `mcp/README.md`.

**The maintainer, once per package** (a pending publisher creates the project on first upload):

1. Sign in at https://pypi.org/manage/account/publishing/ .
2. Add a pending GitHub publisher with exactly these values, twice:

   | Field | `profile-wrap` | `profile-wrap-mcp` |
   |---|---|---|
   | PyPI project name | `profile-wrap` | `profile-wrap-mcp` |
   | Owner | `NJ-Burrito` | `NJ-Burrito` |
   | Repository | `profile-wrap` | `profile-wrap` |
   | Workflow filename | `release.yml` | `release.yml` |
   | Environment | `pypi` | `pypi-mcp` |

3. On GitHub: Settings > Environments > New environment `pypi` (optionally require your approval as reviewer).

**Lead/CI**: the PyPI job in `release.yml` has `permissions: id-token: write`, `environment: pypi`, builds both wheels and
sdists and uploads with `pypa/gh-action-pypi-publish`; upload `profile-wrap` first, then `profile-wrap-mcp`.
Commands to check before tagging: `uv build` and `uv build mcp`, then `uvx twine check dist/*`.
Release: `git tag v0.2.0 && git push origin v0.2.0` (Lead only). Check after: `uvx profile-wrap-mcp==0.2.0 --help`.

## 2. Official MCP Registry

Needs: `profile-wrap-mcp` 0.2.0 live on PyPI; `mcp/README.md` carries `mcp-name: io.github.NJ-Burrito/profile-wrap-mcp`
(done); `mcp/server.json` (schema 2025-12-11). Text: `docs/listings/official-mcp-registry.md`.

**Check before publishing:** `mcp/server.json` says version `0.1.0` in two places, while `mcp/pyproject.toml` is `0.2.0`.
Set both `version` fields in `server.json` to `0.2.0` (Lead, package E file).

**The maintainer** (GitHub login, namespace `io.github.NJ-Burrito/*`), from the repo folder:

```
cd mcp
mcp-publisher login github
mcp-publisher publish
```

Install the tool first if missing (`brew install mcp-publisher`, or the release binary from
https://github.com/modelcontextprotocol/registry/releases ). Verify:
`curl "https://registry.modelcontextprotocol.io/v0.1/servers?search=io.github.NJ-Burrito/profile-wrap-mcp"` lists the entry.
The registry is in preview; if a command or schema URL has changed, follow https://modelcontextprotocol.io/registry/quickstart .
Optional later: publish from GitHub Actions with OIDC (`mcp-publisher login github-oidc`).

## 3. mcp.so

Needs: public repo. **The maintainer**: open https://mcp.so/submit , give the repository URL
`https://github.com/NJ-Burrito/profile-wrap`, check the pulled name, description and tags against
`docs/listings/mcp-so.md`, submit. Listing goes live after their review. No files in the repo are required.

## 4. Glama

Needs: `glama.json` in the repo root on `main` (done: `$schema` + `maintainers: ["NJ-Burrito"]`; the copy in `mcp/` stays for
the package). **The maintainer**: sign in to https://glama.ai with GitHub, find the Profile-Wrap server (add the repository on
https://glama.ai/mcp/servers if it is not indexed), claim it as maintainer `NJ-Burrito`, paste the text from
`docs/listings/glama.md`. Glama grades licence, quality and maintenance on its page; submission rules beyond the ownership
claim were not verified.

## 5. Smithery

Needs: Smithery account; a stdio server is published as an MCPB bundle (a URL publish needs a public HTTPS server, which
Profile-Wrap does not run). Files: `mcp/smithery.yaml` (metadata, launches `uvx profile-wrap-mcp`).
**Lead**: build `profile-wrap-mcp.mcpb` (`npx @anthropic-ai/mcpb pack`, from `mcp/` with a `manifest.json`; package E owns
the manifest). **The maintainer**: `smithery auth login`, then `smithery mcp publish ./profile-wrap-mcp.mcpb -n NJ-Burrito/profile-wrap-mcp`
(exact namespace per his Smithery account; command from https://smithery.ai/docs/build/publish ). Paste text from
`docs/listings/smithery.md`. Not verified: whether Smithery reads `smithery.yaml` for a stdio bundle.

## 6. Anthropic plugin directory (Claude Code)

Needs: paid claude.ai plan; `plugins/profile-wrap/` at 0.2.0 on `main`; `profile-wrap-mcp` 0.2.0 live on PyPI.
Files: `plugins/profile-wrap/.claude-plugin/plugin.json` (five directory URL fields set), `plugins/profile-wrap/SUBMISSION.md`
(the click-by-click checklist, followed as written), `docs/listings/anthropic-plugin-directory.md`.
**Lead** before the maintainer starts: `claude plugin validate --strict plugins/profile-wrap` and
`python -m profile_wrap.leakcheck scan --tree .` must pass. **The maintainer** (only he submits): open https://claude.ai/directory/manage
and follow `plugins/profile-wrap/SUBMISSION.md` sections A to D. Record the directory link and date in the status table.
Self-hosted route, no review, works now: `claude plugin marketplace add NJ-Burrito/profile-wrap`, then
`claude plugin install profile-wrap@profile-wrap`.

## 7. OpenAI Codex (not in the maintainer's list, kept for completeness)

The Codex plugin (`plugins/profile-wrap-codex/`, marketplace `.agents/plugins/marketplace.json`) installs from the repo with
`codex plugin marketplace add NJ-Burrito/profile-wrap`. A public OpenAI directory submission and an awesome-codex-cli pull
request are not planned; steps are in `docs/CODEX.md`.

## Known gaps

- `plugin.json` `privacyPolicyUrl` is `https://github.com/NJ-Burrito/profile-wrap/blob/main/docs/PRIVACY.md` (a page URL, not the
  raw file). It opens and is https; the portal accepts it, but the raw form would be
  `https://raw.githubusercontent.com/NJ-Burrito/profile-wrap/main/docs/PRIVACY.md`. Lead decides; plugin files are not edited here.
- `docs/PRIVACY.md` must be on `main` before any submission, or those URLs 404.
- `release.yml` does not exist yet (package C); the PyPI steps depend on it.
- Directory rules change; where a screen differs from this file, follow the screen and keep the intent.
