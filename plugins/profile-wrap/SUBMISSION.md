# Submit Profile-Wrap to Anthropic's plugin directory (The maintainer, from your own account)

Source: Anthropic's pre-submission checklist and publishing docs, read 2026-10-16. Portal wording can change, so where
a label below differs on screen, follow the screen and keep the intent. Everything here is done by you; nothing is
submitted automatically.

## A. Before you open the portal (all must be true)

- [ ] You have a paid claude.ai plan and can sign in at https://claude.ai.
- [ ] The repository https://github.com/NJ-Burrito/profile-wrap is public and `main` contains the folder
      `plugins/profile-wrap/` at version 0.2.0 (tag `v0.2.0` exists).
- [ ] `profile-wrap-mcp` 0.2.0 is published on PyPI. The plugin starts it with `uvx profile-wrap-mcp==0.2.0`, and a
      pinned launcher whose version does not exist makes the plugin fail. Check: `uvx profile-wrap-mcp==0.2.0 --help`.
- [ ] `profile_wrap` is on PyPI, or the README install line is changed to install from GitHub.
- [ ] These URLs open in a private browser window (they are in `plugin.json`):
      `docs/PRIVACY.md`, `LICENSE`, `README.md` and the issues page on GitHub, and the raw `assets/icon.svg` link.
- [ ] In the repo folder, run `claude plugin validate --strict plugins/profile-wrap`. It must say "Validation passed".
- [ ] `python -m profile_wrap.leakcheck scan --tree .` prints PASS (no keys or tokens anywhere).
- [ ] Optional dry run on your machine: `claude plugin marketplace add NJ-Burrito/profile-wrap`, then
      `claude plugin install profile-wrap@profile-wrap`. It should install version 0.2.0 with 5 skills and 6 commands.

## B. Facts the portal checks (already satisfied, listed so you can confirm)

| Check | State in this folder |
|---|---|
| One plugin per submission, `.claude-plugin/plugin.json` present | yes, `plugins/profile-wrap` |
| Name lowercase, digits, hyphens, at most 64 chars, not reserved, no "linkedin", "claude-" or "anthropic-" | `profile-wrap` |
| README with at least 40 words outside code blocks | yes, with install, privacy and "not affiliated with LinkedIn" |
| `LICENSE` file and `license` field | MIT, both |
| Under 512 files, files under 256 KiB, no binaries | 75 files, text and one SVG |
| No symlinks, submodules, LFS, `.DS_Store`, `.gitattributes` filters | none |
| No hooks, no shell variables in launchers | no hooks folder; the MCP launcher is pinned |
| No credentials | secrets are kept in the OS keychain, nothing in the folder |
| Directory fields | `documentationUrl`, `supportUrl`, `privacyPolicyUrl`, `termsOfServiceUrl`, `icon` |

Expect a human reviewer to look at it anyway: a pinned `uvx` launcher is always held for review, and the name must
not be mistakable for a known brand.

## C. Submit, click by click

1. [ ] Open https://claude.ai/directory/manage and sign in with your paid account.
2. [ ] Click the button to submit a new plugin (wording such as "Submit plugin" or "Add plugin").
3. [ ] Choose GitHub as the source and authorise the GitHub connection if asked. Grant access to `NJ-Burrito/profile-wrap` only.
4. [ ] Select the repository `NJ-Burrito/profile-wrap`, branch `main`.
5. [ ] When asked for the plugin folder, enter `plugins/profile-wrap` (the folder that contains `.claude-plugin/plugin.json`).
6. [ ] Wait for the automatic checks. If one fails, copy its message and fix the file named; do not edit the portal fields to hide it.
7. [ ] Check that the preview shows: name `profile-wrap`, version 0.2.0, MIT, the icon, and the five links.
8. [ ] If asked about the MCP server, answer: stdio, started by `uvx` from PyPI, local only, no remote URL. If asked about
      data, answer: no data leaves the machine except to LinkedIn's official API when the user posts, and to the AI provider the user selects.
9. [ ] Accept the Anthropic Software Directory Policy only after you have read it (it was not read when this checklist was written).
10. [ ] Press submit. Save the confirmation page or email in `research/profile-wrap/` as evidence.

## D. After submitting

- [ ] A scan runs first. A first submission that fails the security scan is rejected, so read its message before resubmitting.
- [ ] A reviewer may ask questions by email. Answer from the README and `docs/PRIVACY.md`; the plugin does not read DMs
      and has no posting path except through the user's own developer app.
- [ ] Once approved, record the directory link in `docs/DISTRIBUTION.md` and the date.
- [ ] Each later release: bump `version` in `plugins/profile-wrap/.claude-plugin/plugin.json` and in the root
      `.claude-plugin/marketplace.json`, publish the new `profile-wrap-mcp` first, update the pin in `.mcp.json`, then resubmit.

## E. If you want to publish without waiting (no review)

Users can already install from your own marketplace: `/plugin marketplace add NJ-Burrito/profile-wrap`, then
`/plugin install profile-wrap@profile-wrap`. This does not depend on the directory.
