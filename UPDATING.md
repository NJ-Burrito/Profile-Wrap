# Updating

Code is read-only and separate from your data. An update never edits your facts, voice, calendar,
drafts, published posts or config values.

## 1. Update the package

| You installed with | Run |
|---|---|
| Claude Code plugin | `/plugin update profile-wrap` |
| `uv tool` | `uv tool upgrade profile-wrap` |
| `pipx` | `pipx upgrade profile-wrap` |
| Git clone | `git pull`, then `uv sync` |

Read the new entries in [CHANGELOG.md](CHANGELOG.md) first.

### Optional update notice

Every surface (the command line, the desktop app, the review board, the Claude Code plugin at session start, the MCP
server and the skills) checks GitHub for a newer release when it starts, and tells you inside that surface. It never
updates anything unless you choose to. Updating is always optional.

```bash
profile-wrap update            # is there a newer release? (same as: update check)
profile-wrap update news       # what's new, release by release, newest first
profile-wrap update apply      # shows the exact command for your install, asks y/N, then runs it (--yes skips the question)
profile-wrap update skip       # hide this version; a newer one is announced again
profile-wrap update later      # remind me in 24 hours
```

`update apply` runs the command only for `uv tool`, `pipx`, `pip` and git-clone installs. For the Claude Code plugin
(`/plugin update profile-wrap`) and the desktop app (download the new installer from the releases page) it prints the
instructions and runs nothing. The desktop app and the board show a banner with What's new, Update, Skip this version
and Later. "What's new" is the release notes copied as text (or the matching `CHANGELOG.md` sections); no model is called.

To switch the check off: `profile-wrap config set updates.check false`, or set `PROFILE_WRAP_NO_UPDATE_CHECK=1`.
Set `updates.prereleases` to `true` (or `PROFILE_WRAP_UPDATE_PRERELEASES=1`) to hear about release candidates.
If the repository is ever renamed, GitHub answers the releases request with a 301 redirect. The check never follows
redirects (so no request can be sent to another host), treats that as "could not check" and says nothing; update by the
commands in section 1 until a release changes the address. It is off by itself under CI and in the test suite. What is sent, and how often, is in [docs/PRIVACY.md](docs/PRIVACY.md).

## 2. Check your workspace

```bash
profile-wrap doctor
```

`doctor` detects drift between the code and the stable runtime copy that schedulers call, and an API
version table older than 90 days. To fix drift:

```bash
profile-wrap runtime status
profile-wrap runtime sync
profile-wrap migrate --help          # idempotent migrations; --dry-run shows what would change
```

## 3. Upgrade the templates

Your workspace holds copies of managed and seeded templates (the `CLAUDE.md` rules block, agents,
prompts, the brand kit). They upgrade by a three-way compare against the version you started from.

```bash
profile-wrap upgrade --check         # preview; same as --dry-run
profile-wrap upgrade --apply         # overwrite / keep / write <file>.new
profile-wrap upgrade --resolve --mine      # after a conflict: keep my files
profile-wrap upgrade --resolve --theirs    # or take the new templates
```

| Class | Examples | Rule |
|---|---|---|
| managed | `.claude/agents/*`, brand-kit copy, launchers, `.gitignore` | replaced only if you have not edited them |
| seeded | `prompts/*.md`, strategy templates, `voice.md` skeleton | created once, then merged |
| user | config values, facts, voice, calendar, drafts, published, metrics | never touched |

Both you and the template changed a file? Your file stays, the new text is written beside it as
`<file>.new`, the conflict is recorded, and `profile-wrap upgrade` exits 3 until you run `--resolve`.
Backups go to `.njl/backup/<timestamp>/`.

## 4. Re-acknowledge when the terms text changes

If an update changes `docs/TERMS-AND-RISK.md` or `docs/references/compliance.md`, the stored
acknowledgement no longer matches. Unattended posting and API comments drop back to notify or draft
until you run `profile-wrap config ack <action>` again. Upgrades never silently weaken a safety setting.

## 5. Motion library and API versions

- A bump of `brand/motion/VERSION` offers `profile-wrap motion upgrade`.
- `profile-wrap api-versions` shows the `Linkedin-Version` table and the version in use.

## Going back

Restore the files from `.njl/backup/<timestamp>/`, or `git checkout` them: your workspace is its own
git repository. Reinstall an older package version with `uv tool install profile-wrap==<version>`.
