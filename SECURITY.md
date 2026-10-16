# Security policy

## Reporting a vulnerability

Do not open a public issue for a security problem. Use GitHub's private vulnerability reporting ("Security" tab, "Report a vulnerability") on this repository. Include the version (`profile-wrap --version`), your OS, and the smallest steps that reproduce it. Expect an acknowledgement within 7 days and a fix or a written assessment within 30 days. There is no bug bounty.

## What counts

- A path that reads or writes a secret outside the config directory, or sends a token to a host other than LinkedIn.
- A way for a model worker to run a shell, read the config directory, or change files outside its allowlist.
- A way to post, comment or like without the acknowledgement, gate and pause checks.
- A leak of personal data, a font or a secret in a release artefact.

## What this package does about it

- Secrets live only in the config directory with user-only permissions; never in a workspace or repository.
- The package never reads or stores a LinkedIn password.
- Content workers run in a sandbox directory with a scrubbed environment and no shell; their output is scanned for token shapes.
- The only module that talks to the LinkedIn API is `profile_wrap/linkedin/`, with an endpoint allowlist. `profile-wrap compliance lint` enforces that and runs in tests, CI and `doctor`.
- `profile-wrap leaks scan` blocks fonts, photos, secrets, personal paths, real LinkedIn identifiers and denylisted private terms before a release.
- `profile-wrap pause` is a kill switch every job checks first.

## Supported versions

Only the latest release receives fixes.

## Not legal advice

Using automation on LinkedIn is governed by LinkedIn's terms, which you must read yourself. See `docs/TERMS-AND-RISK.md`.
