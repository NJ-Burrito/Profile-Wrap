## What and why

## Checks

- [ ] `python -m pytest -q` passes
- [ ] `python -m profile_wrap.compliance lint --root .` passes
- [ ] `python -m profile_wrap.leakcheck scan --tree .` passes
- [ ] No real person, client, token, font or photo in the diff (demo data stays fictional)
- [ ] `CHANGELOG.md` has a line for user-visible changes
