# Quickstart

Five minutes from nothing to a working demo, then about an hour to your first real draft.
Python 3.10 or newer is the only requirement for steps 1 and 2.

## 1. Install

```bash
uv tool install nj-linkedin          # or: pipx install nj-linkedin, or: python -m pip install nj-linkedin
njli --version
```

As a Claude Code plugin instead: `/plugin marketplace add NJ-Burrito/nj-linkedin`, then
`/plugin install nj-linkedin@nj-linkedin`, then say "set up LinkedIn".

On Windows, `tzdata` is installed with the package. If `njli doctor` says it cannot load a time zone,
run `uv pip install tzdata`.

## 2. Run the demo

```bash
njli init --demo --yes
njli demo run
```

What you should see: a list of `PASS` lines (init, doctor, facts lint, three gates, the sample GIF,
board health, Allow, a post to the fake LinkedIn, `due`, the fake `claude`, the scheduler preview, the
leak scan) and a last line like `17 of 17 steps passed`. The exit code is 0.

Nothing leaves your machine. The "LinkedIn" is a small server on 127.0.0.1, the "model" is a script,
and the config and data folders are temporary. The persona, Maya Rivera, is fictional.

Want to look around? `njli init --demo --yes` printed the workspace path. Then:

```bash
njli review list --workspace <that path>
njli board --workspace <that path> --open
```

## 3. Check your machine

```bash
njli doctor
```

Every WARN says what it stops and gives the install line for your OS. You do not need all of them:

| You want | You need |
|---|---|
| Drafting by hand, the gate, the board | Python 3.10+ |
| AI drafting and review | the `claude` CLI |
| Slides and GIFs | Node 22+, Chrome or Chromium, and ffmpeg for GIFs |

## 4. Set up your own workspace

In Claude Code, run `/nj-linkedin:setup`. From a terminal:

```bash
njli init --express
```

You answer seven questions (who you are, languages, timezone, goal, cadence). Everything else gets a
conservative default: 3 posts a week, 3 comment drafts a day, notes under 200 characters.

## 5. Add facts, plan, draft

```bash
njli facts add --claim "Cut the weekly review to 30 minutes" --numbers "30 minutes" --source notes/review.md
njli facts verify F01 --evidence notes/review.md       # you, in a terminal; an agent cannot
njli calendar fill --weeks 1
njli build-week --dry-run
njli gate <slug>
```

Every number in a caption must cite a verified fact with the same value and unit. That is the rule
that stops invented results.

## 6. Review, allow, post

```bash
njli board --open                    # or: njli review list
njli review allow <slug>             # you decide
njli post <slug> --dry               # preview, sends nothing
njli post <slug> --now               # sends; needs your LinkedIn app (next step)
```

## 7. Connect your LinkedIn app (only for posting)

Follow [docs/linkedin-app-setup.md](docs/linkedin-app-setup.md): create a free developer app, add the
"Share on LinkedIn" product, then:

```bash
njli auth
njli selftest
```

`selftest` is read-only. It never posts.

## 8. Automate (optional)

```bash
njli schedule install --dry-run      # shows the exact files and commands for your OS
njli pause --all                     # the kill switch, any time
```

Unattended posting needs `posting.mode: api_scheduled` and a typed acknowledgement. Read
[docs/TERMS-AND-RISK.md](docs/TERMS-AND-RISK.md) first.

## If something fails

`njli doctor`, then [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md). Paste the failing line of
`njli demo run` into an issue; it has no private data.
