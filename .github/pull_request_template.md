## What and why

## Checks

- [ ] `python -m pytest -q` passes
- [ ] `python -m njli.compliance lint --root .` passes
- [ ] `python -m njli.leakcheck scan --tree .` passes
- [ ] No real person, client, token, font or photo in the diff (demo data stays fictional)
- [ ] `CHANGELOG.md` has a line for user-visible changes
