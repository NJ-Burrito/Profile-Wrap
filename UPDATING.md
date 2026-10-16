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
