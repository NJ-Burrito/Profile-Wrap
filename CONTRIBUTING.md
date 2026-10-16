# Contributing

Thanks for helping. Small, tested changes are easiest to review.

## Set up

```bash
git clone https://github.com/NJ-Burrito/nj-linkedin
cd nj-linkedin
uv sync                                  # or: python -m venv .venv && pip install -e ".[dev]"
uv run --with tzdata python -m njli demo run     # the whole pipeline, offline
```

## Before you open a pull request

```bash
uv run --with pytest --with tzdata python -m pytest -q
python -m njli.compliance lint --root .
python -m njli.leakcheck scan --tree .
```

CI runs the same on Windows, macOS and Linux, plus the README quickstart (`njli init --demo --yes`
and `njli demo run`). All three must pass.

## Rules that are not negotiable

- **Official API only.** The only code that talks to LinkedIn lives in `njli/linkedin/`. No login, cookies,
  browser automation against linkedin.com, message reading or invitation sending. `compliance lint` enforces it.
- **Limits are ceilings.** Config can lower a cap, never raise it. A new action needs a cap, a pause check and
  an acknowledgement.
- **No personal data.** Demo data is the fictional persona Maya Rivera: reserved domains (`example.com`,
  `example.invalid`), fake ids (`urn:li:person:DEMO000000`). Never add a real name, client, URL, token, font,
  photo or signature. `leaks scan` fails the build if you do.
- **Standard library only in the core.** Python 3.10+. Extras (`media`, `xlsx`, `sig`) stay optional.
- **Cross-platform paths.** Use `pathlib`; test the Windows and POSIX branches.
- **Arabic and English are both first-class.** A bilingual pair changes together.
- **A test for every refusal.** If a change makes the tool refuse something, a test shows the refusal and its message.

## Where things are

| Path | What |
|---|---|
| `njli/` | The package; each area has a `cli_ext.py` with `register(subparsers)` |
| `njli/demo/` | Fake LinkedIn, fake `claude`, `demo run` |
| `examples/demo-persona/` | The fictional workspace data; regenerate the sample GIF with `python examples/make_demo_gif.py` |
| `schema/`, `data/`, `templates/` | JSON schemas, caps and pins, workspace templates |
| `skills/`, `commands/`, `agents/`, `prompts/` | The Claude Code plugin |
| `tests/` | `unit/`, `integration/`, `e2e/` |

## Style

Plain words, short sentences, no filler. Commit messages say what and why. Add a line to
[CHANGELOG.md](CHANGELOG.md) for anything a user can see.

## Reporting a security problem

Not in a public issue. See [SECURITY.md](SECURITY.md).
