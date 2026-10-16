# Scheduling

Profile-Wrap runs its recurring work (the weekly build, research, health checks, due posts, engagement
drafts) through the scheduler your operating system already has. There is one job model, one installer, three
native backends and one runner. No hook, no background service of its own.

```text
profile-wrap schedule plan        what the jobs are and when they fire, in your timezone
profile-wrap schedule install     show the exact files or commands, then register them
profile-wrap schedule status      installed versus expected, last run, next run
profile-wrap schedule next        what fires in the next 48 hours
profile-wrap schedule remove      delete exactly what install created
profile-wrap run <job>            run a job now, through the same code path the scheduler uses
profile-wrap daemon               a foreground loop for containers and people who refuse system schedulers
profile-wrap pause / resume       the kill switch every job checks first
```

## The jobs

Set in `config/profile-wrap.json` under `schedule.jobs`. The times are in `locale.timezone`; `schedule plan` also
shows them in the machine's timezone when the two differ, because the operating system fires in machine time.

| Job | Runs | Default | What it does |
|---|---|---|---|
| `build_week` | Thursday 10:00, up to 20 minutes of jitter | on | builds drafts for planned entries 8 to 14 days ahead; never queues |
| `research_weekly` | Friday 09:00 | on | the trend scan and the researcher worker |
| `token_check` | daily 09:30 | on | warns before the LinkedIn token expires |
| `doctor_weekly` | Monday 08:00 | on | `profile-wrap doctor` and a notification if something broke |
| `profile_review` | every 90 days (a daily check; the runner skips the days in between) | on | reminds you to re-score the profile |
| `board` | at login, restarted if it stops | on | the local review board on 127.0.0.1 |
| `post_due` | every 15 minutes | off | posts the queued draft whose slot has come; on only with `posting.mode = api_scheduled` and its acknowledgement |
| `engage_prepare` | daily 11:00, up to 30 minutes of jitter | off | drafts comments for you to post |
| `replies_watch` | every 3 hours | off | drafts replies to comments on your own posts |
| `connect_weekly` | Sunday 10:00 | off | shortlists people for you to connect with |
| `track_daily` | daily 21:00 | off | imports your metrics export |

With `copy` or `api_click` posting, `post_due` stays off: you post by hand, or press "Post now" on the board.
Engagement jobs only draft unless you switched on the experimental API comment mode and acknowledged it.

Every entry is named `profile-wrap-<profile>-<job>` (macOS: `io.profile_wrap.<profile>.<job>`), so two profiles on one
machine never collide.

## What gets scheduled

Every entry runs the same command:

```text
<absolute interpreter> <data>/runtime/current[/profile-wrap.pyz] run <job> --workspace <absolute workspace>
```

The interpreter is the one found when you ran `install`. The code is the stable copy made by
`profile-wrap runtime install`, not the plugin folder, so a plugin update never changes what a scheduled job runs
until you run `profile-wrap runtime sync`. `profile-wrap doctor` reports a difference between the two. There is no `python -m`
and no relative path in any entry.

`install` refuses when there is no stable runtime yet, and says to run `profile-wrap runtime install`.

## Backends

| OS | Mechanism | Catch-up after sleep or shutdown |
|---|---|---|
| Windows | Task Scheduler: one XML file per job in `data/schedule/`, registered with `schtasks /Create /XML ... /F` | `StartWhenAvailable`: a missed run starts when the machine is back |
| Linux with a user session | `systemctl --user` timers with `Persistent=true` and `RandomizedDelaySec` | `Persistent=true` runs a missed timer at the next start |
| Linux without one | a marked block in your crontab (`# BEGIN profile-wrap:<profile>` to `# END profile-wrap:<profile>`), each line wrapped in `flock -n` | none: cron has no catch-up |
| macOS | LaunchAgents `io.profile_wrap.<profile>.<job>.plist` loaded with `launchctl bootstrap gui/<uid>` | launchd runs a missed interval once after wake, but cannot wake the Mac |
| Any | `profile-wrap daemon` | none while it is not running |

`schedule.backend` is `auto` by default. Choose another with `--backend` on install or in the config.

### Windows

- The action is `pythonw.exe` when it sits next to the interpreter (no console window), else `python.exe`.
- Settings: `StartWhenAvailable` on; `WakeToRun` only for a job whose config sets `wake: true`;
  `MultipleInstancesPolicy` is `IgnoreNew`; an execution limit per job (the job's timeout plus five minutes);
  restart on failure and a logon trigger for the board.
- The XML is written as UTF-16 with a byte order mark, which `schtasks` requires.

### Linux

- Each job is a `.service` plus a `.timer` in `~/.config/systemd/user/`. The board is a service wanted by
  `default.target` with `Restart=on-failure`.
- systemd adds the random delay itself, so its entries pass `--no-jitter` and the runner does not delay twice.
- On a server where nobody is logged in, user timers stop at logout: run `loginctl enable-linger $USER` once.
- The crontab route edits only its own block, leaves every other line alone, and removes only that block.

### macOS

- The PATH launchd gives a job is minimal. `install` records the absolute paths of `node`, `npx`, `ffmpeg`,
  `ffprobe` and `claude` and your PATH into the plist's `EnvironmentVariables` (as `PATH`, `PROFILE_WRAP_NODE`,
  `PROFILE_WRAP_NPX`, `PROFILE_WRAP_FFMPEG`, `PROFILE_WRAP_FFPROBE` and `PROFILE_WRAP_CLAUDE_BIN`). A tool that is missing when you install
  is left out and `install` says so. `profile-wrap doctor --launchd-dryrun` shows what would be captured.
- Reinstall after you move or upgrade one of those tools (Homebrew moves them), or the old path stays in the
  plist.
- A closed lid sleeps the Mac and launchd cannot wake it. `pmset repeat wakeorpoweron MTWRFSU 09:55:00` wakes
  it five minutes before a 10:00 job; it needs an administrator and changes a system setting, so profile-wrap does not
  run it for you.

## The runner

`profile-wrap run <job>` is what every entry calls. In this order:

1. Sets `PYTHONUTF8=1` and gives the job a scrubbed environment (`models.runner.env_allow`, what an operating
   system needs to start a process, `PROFILE_WRAP_*`; no LinkedIn secrets and no shell tokens).
2. Checks the pause flags. Paused: it records the fact and exits with code **4**.
3. For a job that fires daily but means "every N days", checks the last success and exits 0 if it is too soon
   (`--force` skips this).
4. Re-checks the tools the job needs (for the model jobs, the `claude` CLI). A missing tool is one message, a
   notification and exit 1, not a traceback.
5. Takes a per-job lock (`O_EXCL` plus a check that the owner process is alive, stale after the job's timeout).
   A second copy of a running job exits 0 and says so.
6. Waits a random time up to the job's `jitter_min` and logs it. The jitter spreads load and posting times
   across your audience's hours; it is not a way to look like a person, and `automation.mode` is recorded on
   every ledger row. It re-checks the pause flag afterwards.
7. Runs the job with a hard timeout and kills the whole process tree: a Job Object on Windows, a process group
   on Linux and macOS. A grandchild that outlived its parent is killed too.
8. Writes `data/logs/<job>.log` (rotated at `schedule.log_rotate_mb`, three old files kept) and one line to
   `data/logs/runs.jsonl`.
9. Notifies on a failure, a timeout or a missing tool.

Exit codes: 0 ok, 1 failed, 2 unknown job, 4 paused, 124 timed out.

## Dry run

`profile-wrap run <job> --dry-run` prints what the job would do. It makes no API call, spends no model tokens and
writes only under `work/dryrun/`. For `build_week` it starts `profile-wrap build-week --dry-run`, which lists the
entries and their times and starts no worker. For the other jobs it prints the command and stops.
`profile-wrap schedule install --dry-run` prints the exact files and commands, and `--show-files` their contents.

## Sleeping laptops

A slot that was missed while the machine slept is not posted late by accident:

- Windows and systemd run a missed job when the machine is back; launchd runs it once.
- `post_due` then applies the missed-slot rule: a slot later than `posting.missed_after_hours` (default 6)
  becomes `missed` and you are notified. You reschedule it on the board.
- The 12-hour minimum gap and the one-post-per-run rule hold whatever the scheduler does.
- If you prefer late posts to missed ones, set `run_if_within_hours` on the `post_due` job in the config; it is opt-in.

## Remove and reinstall

`install` records every file and command it made in `.njl/workspace.json` (`created_schedule`). `remove` reads
that list and deletes exactly those entries, leaving your own scheduled tasks, crontab lines and units alone.
Running `install` again replaces entries, never duplicates them. Run `profile-wrap schedule remove` before you delete a workspace or uninstall, so no scheduler entry is left pointing at it.

## Troubleshooting

| Symptom | Look at |
|---|---|
| A job never ran | `profile-wrap schedule status`; then the OS: Task Scheduler's History tab, `systemctl --user list-timers`, `launchctl print gui/$UID/io.profile_wrap.<profile>.<job>` |
| A job ran and did nothing | `data/logs/<job>.log`, and `profile-wrap doctor` for the pause flag |
| "tool missing" | install the tool, then on macOS run `profile-wrap schedule install` again so the path is captured |
| It runs the old code after an update | `profile-wrap runtime sync` |
| Two builds overlapped | they cannot: the second exits 0; check `data/locks/` for a stale lock after a crash |
