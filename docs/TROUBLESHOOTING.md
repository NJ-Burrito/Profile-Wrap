# Troubleshooting

Start with `njli doctor`. It prints PASS, WARN or FAIL for each item, with the fix for your OS. Add
`--json` for machine-readable output and `--online` to test the network. Exit codes for every
command: 0 ok, 1 fail, 2 usage, 3 conflicts to resolve, 4 paused.

| Symptom | Cause | Fix |
|---|---|---|
| "njli needs Python 3.10 or newer" | the first Python on PATH is 3.9 or older | install Python 3.12 (the message prints the line for your OS), or set `NJLI_PYTHON` |
| `njli: command not found` | the plugin `bin/` is not on PATH | call `${CLAUDE_PLUGIN_ROOT}/bin/njli`, or install with `uv tool install nj-linkedin` |
| "time zone ... cannot be loaded" | Windows without `tzdata` | `uv pip install tzdata` |
| `config validate` says "unknown key" | a typo, or a key from another version | remove or fix the key; `njli config show` lists the real ones |
| "above the ceiling of ..." | a value beyond a locked limit | lower it; ceilings live in the code and cannot be raised by config |
| "posting.window ... minutes wide" | the window plus the gap leaves no room for consecutive days | shorten the window or lower `min_gap_hours` (never below 12) |
| `needs an acknowledgement` | `api_scheduled`, API comments or Apify without the typed acknowledgement | run `njli config ack <action>` in a terminal, or switch the mode back |
| "downgraded until you accept again" | the shipped risk text changed in an update | read the new text and run `njli config ack <action>` again |
| `init` refuses the folder | it is inside the plugin directory, or not empty | choose a folder under your home directory |
| `upgrade --apply` exits 3 | a file was edited by you and changed in the new release | merge the `<file>.new` files, delete them, then `njli upgrade --resolve` (or `--mine` / `--theirs`) |
| "runtime/current is 0.1.0, plugin is 0.2.0" | the plugin was updated | `njli runtime sync` (jobs kept running on the old copy meanwhile) |
| a scheduled job did nothing, exit 4 | the pause flag is set | `njli resume` |
| `handoff check` fails | headings differ from the six required | the headings are exactly: `# goals`, `## current state`, `## files in flight`, `## changed`, `## failed attempts`, `## next step` |
| macOS job cannot find `node` or `claude` | launchd has a minimal PATH | re-run `njli schedule install` so absolute paths are captured; test with `njli doctor --launchd-dryrun` |
| macOS blocks a downloaded browser | Gatekeeper quarantine | `xattr -dr com.apple.quarantine <path-to-browser>` |
| `claude` runs by hand but not from a job | the login is not reachable from the scheduler | use an API key: `njli config set models.runner.auth '"api_key"'` and name the variable in `models.runner.api_key_env` |
| a symlink error installing the runtime on Windows | no permission to create symlinks | nothing to do: a junction or copy is used and works the same |

## Locks and stale state

Locks are files under `<workspace>/data/locks/`. A lock is broken automatically when its process is
gone or it is older than its timeout. If something is truly stuck, `njli doctor` names it; delete only
the `.lock` file it names, after checking no `njli` process is running.

## Backups

Upgrades and migrations copy what they change into `<workspace>/.njl/backup/<timestamp>/` first.
Restore by copying the file back.

## Still stuck

Run `njli doctor --json`, remove anything private, and open an issue with the output and the exact
command. Never paste tokens or the contents of the secrets directory.
