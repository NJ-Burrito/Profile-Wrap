---
name: njl-setup
description: Set up, check, pause, upgrade or try nj-linkedin. Use for "set up LinkedIn", "onboard me", "first run", "init", "doctor", "why did it fail", "pause everything", "upgrade", "uninstall" or "show me a demo". Runs the resumable interview with AskUserQuestion, creates the workspace, and explains every check.
---

# njl-setup

Set up the nj-linkedin workspace, check the machine, and keep it healthy. Work the nj-method way:
analyse the ask, look up before improvising, plan with file checkpoints, run, review against the
request. Every stage leaves a file the next stage reads, so a stop resumes where it left off.

The command is `"${CLAUDE_PLUGIN_ROOT}/bin/njli"` (Windows without a POSIX shell:
`"${CLAUDE_PLUGIN_ROOT}\bin\njli.cmd"`). Below it is written `njli`.

## Compliance first

Read `${CLAUDE_PLUGIN_ROOT}/docs/references/compliance.md` before anything else. This package uses
the official LinkedIn API only, through the user's own developer app. If a request conflicts with
it (logging in to LinkedIn, driving a browser against it, reading messages, sending invitations,
editing a profile, hiding automation), refuse that part and offer the draft-only alternative. If
the user offers a LinkedIn login secret, stop and tell them it is never needed, never stored and
never used.

## Entry modes

| The user says | Do this |
|---|---|
| "show me", "try it", no LinkedIn app yet | `njli init --demo` (zero questions; fictional persona; a temp workspace) |
| "quick setup" | express path: the 7 questions of step 2, defaults for the rest |
| "set me up" | full path: all steps below |
| "doctor", "why did it fail" | `njli doctor` and explain each WARN or FAIL with its hint |
| "pause" | `njli pause [--posting|--comments|--all]`; `njli resume` to undo |
| "upgrade", "new version" | see Upgrade |

## The interview (full path)

Ask through **AskUserQuestion, in batches of at most 4 questions, with options**. Never leave a
question as prose. The exact questions, options and the mapping to the answers file are in
`references/questions.md`. After every batch, write that step's answers into the answers file
(shape in `references/answers-file.md`) and apply it, so a stop loses nothing:

| # | Step | Command |
|---|---|---|
| 0 | Preflight | `njli doctor`; show the table. Stop only if Python is too old or the `claude` CLI is missing; offer the demo instead |
| 1 | Where | workspace path and profile id (default `~/nj-linkedin/<profile>`) |
| 2 | Who | name, handle, role, niche, audience, regions, languages, time zone (auto-detected, confirm), goal |
| 3 | Privacy | `private_terms` (employers, clients, products), sensitive subjects |
| 4 | Facts | 10 to 15 questions; rows are written as `draft` |
| 5 | Voice | 3 to 5 past posts, or 6 style questions; style preset `plain`, `impact_copy` or `adhd_emoji` |
| 6 | Brand | font source (open-licence default, or the user's own licensed files; never copied out), palette mode, identity card |
| 7 | Cadence and caps | show the conservative defaults and the risk of raising each, up to the ceiling |
| 8 | Models | tiered or single; login or API key (recommended for unattended runs) |
| 9 | LinkedIn app | skippable; the checklist is `docs/linkedin-app-setup.md`; credentials are typed by the user into a hidden prompt, never into chat |
| 10 | Mode consent | one card per action class; the user types the acknowledgement themselves |
| 11 | Scheduler | `njli schedule install --dry-run`; the user confirms before anything is installed |
| 12 | Profile | optional paste or data-export ingest |
| 13 | First week | `njli calendar fill --weeks 1`, or say which facts are missing |
| 14 | Wrap-up | `CLAUDE.md`, `handoff.md`, first commit, `njli leaks scan --workspace`; say what is automated, what is manual, what happens next |

Apply an answers file with `njli init --answers answers.json --yes` (new workspace), or re-enter one
step on an existing workspace with `njli init --section <name> --answers answers.json`.
`.njl/onboarding.json` records which steps are done, skipped or handled by another command.

## Rules for the interview

- **Facts are never marked verified by you.** Write them as `draft`. The user verifies each one in a
  terminal with `njli facts verify <ID> --evidence <path|url>`; the command refuses when run by an
  agent. A gate proves traceability to the user's register, not that the register is true. Say so.
- **Consent is typed by the user.** `njli config ack <action>` prompts for the phrase in a terminal.
  Never type it for them and never put it in an answers file you wrote yourself. Skipping keeps the
  safe default (draft only, human clicks).
- **Defaults are conservative on purpose**: 3 posts a week, comment cap 3 a day, 3 connection slots
  a week, window 09:00 to 12:29 local. Raising any is allowed up to the ceiling in
  `njli config show`; say what it risks. Ceilings cannot be raised by config.
- **Both languages are first class.** If the user posts in Arabic and English, keep the pair as one
  unit and set the primary language.
- Fonts: the default is an open-licence family. If the user owns licensed fonts, point at their
  files; the package never copies, bundles or uploads them.

## Upgrade

1. `njli upgrade --check` previews. 2. `njli upgrade --apply` overwrites untouched managed files,
keeps files the user edited, and writes `<file>.new` where both changed (exit 3).
3. Merge the `.new` files, delete them, run `njli upgrade --resolve`. 4. `njli migrate` runs the
idempotent migrations; one that touches a safety setting asks first and shows a diff.
5. `njli doctor`. Backups are in `.njl/backup/`.

After a plugin update, `njli doctor` shows runtime drift; `njli runtime sync` refreshes the stable
copy schedulers call. Jobs keep working meanwhile.

## When something fails

Run `njli doctor` before guessing. Read `docs/TROUBLESHOOTING.md` for the symptom. Exit codes:
0 ok, 1 fail, 2 usage, 3 conflicts to resolve, 4 paused.

## Done means

The workspace exists, `njli config validate` and `njli handoff check` pass, `njli doctor` shows no
FAIL, and the user knows the next command. Say plainly what was not verified.
