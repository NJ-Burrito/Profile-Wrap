"""``profile-wrap run <job>``: the one code path every scheduled job takes, and the foreground daemon.

For one run it:

* sets ``PYTHONUTF8=1`` and a scrubbed environment for the child;
* checks the pause flags first and exits 4 when paused;
* takes a per-job lock (``O_EXCL`` plus PID liveness, stale after the job's timeout);
* applies jitter (a random sleep up to the job's ``jitter_min``, logged);
* runs the job with a hard timeout and kills the whole process tree;
* writes ``data/logs/<job>.log`` (size rotation) and one line to ``data/logs/runs.jsonl``;
* notifies on a failure, a timeout or a missing tool, and never prints a traceback for those.

``--dry-run`` prints what would happen. Only commands that are known to honour their own
``--dry-run`` (``build-week``) are started, and they spend no model tokens and write only to
``work/dryrun/``.
"""
from __future__ import annotations

import datetime as _dt
import random
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional

from profile_wrap import claude_runner, limits, policy, tzutil
from profile_wrap.fsutil import append_jsonl
from profile_wrap.locks import LockHeld, named_lock
from profile_wrap.notify import notify

from . import install as inst
from .jobs import JOB_TABLE, Job, jobs_from_config, profile_wrap_argv, profile_wrap_env
from .proctree import TreeResult, run_tree

# Jobs whose command honours --dry-run itself; the others only print what they would run.
DRYRUN_NATIVE = ("build_week",)
# Tools a job needs before it can start (checked, then reported as "tool missing").
JOB_TOOLS: Dict[str, List[str]] = {
    "build_week": ["claude"], "research_weekly": ["claude"], "engage_prepare": ["claude"],
    "replies_watch": ["claude"], "connect_weekly": ["claude"],
}
FATAL_TAIL = 1500
MAX_LOG_APPEND = 200_000


@dataclass
class Outcome:
    job: str
    exit: int
    status: str            # ok | failed | timeout | paused | busy | not_due | tool_missing | dry_run | unknown_job
    seconds: float = 0.0
    jitter_s: float = 0.0
    message: str = ""
    lines: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.exit == 0


def rotate_log(path: Path, max_mb: float, keep: int = 3) -> bool:
    """Rotate ``path`` to ``path.1`` .. ``path.<keep>`` when it is over ``max_mb`` megabytes."""
    try:
        if not path.exists() or path.stat().st_size <= max_mb * 1024 * 1024:
            return False
    except OSError:
        return False
    for i in range(keep, 0, -1):
        older = path.with_name(f"{path.name}.{i}")
        newer = path if i == 1 else path.with_name(f"{path.name}.{i - 1}")
        if newer.exists():
            try:
                if older.exists():
                    older.unlink()
                newer.replace(older)
            except OSError:
                return False
    return True


def child_env(cfg: Mapping[str, Any], source: Optional[Mapping[str, str]] = None) -> Dict[str, str]:
    """The environment a job runs in: the runner allowlist, what an OS needs, ``PROFILE_WRAP_*`` and the tool paths."""
    import os
    src = dict(os.environ if source is None else source)
    runner = (cfg.get("models", {}) or {}).get("runner", {}) or {}
    names = set(runner.get("env_allow") or []) | set(claude_runner.OS_ENV) | {"PYTHONPATH", "NODE_PATH"}
    apify_env = ((cfg.get("engagement", {}) or {}).get("reading", {}) or {}).get("apify", {}).get("token_env")
    if apify_env:
        names.add(apify_env)
    if runner.get("api_key_env"):
        names.add(runner["api_key_env"])
    lower = {k.lower(): k for k in src}
    env: Dict[str, str] = {}
    for n in names:
        k = lower.get(n.lower())
        if k is not None:
            env[k] = src[k]
    for k, v in src.items():
        if k.startswith("PROFILE_WRAP_"):
            env[k] = v
    env["PYTHONUTF8"] = "1"
    if "PYTHONPATH" in profile_wrap_env():  # running from source: the child needs the package on its path
        env["PYTHONPATH"] = profile_wrap_env()["PYTHONPATH"]
    return env


def _log_path(ws: Path, job: str) -> Path:
    return Path(ws) / "data" / "logs" / f"{job}.log"


def _append_log(ws: Path, cfg: Mapping[str, Any], job: str, header: str, body: str) -> None:
    path = _log_path(ws, job)
    path.parent.mkdir(parents=True, exist_ok=True)
    rotate_log(path, float(cfg.get("schedule", {}).get("log_rotate_mb", 5)))
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(header + "\n")
        if body:
            fh.write(body[-MAX_LOG_APPEND:] + ("\n" if not body.endswith("\n") else ""))


def _record(ws: Path, row: Dict[str, Any]) -> None:
    try:
        append_jsonl(Path(ws) / "data" / "logs" / "runs.jsonl", row)
    except OSError:
        pass


def _notify(ws: Path, cfg: Mapping[str, Any], title: str, message: str) -> None:
    try:
        notify(title, message, workspace=ws, mode=cfg.get("schedule", {}).get("notify", "auto"))
    except Exception:  # a notification can never fail a job
        pass


def check_tools(job: str, cfg: Mapping[str, Any], which: Callable[..., Optional[str]] = shutil.which) -> List[str]:
    missing = []
    for tool in JOB_TOOLS.get(job, []):
        if tool == "claude":
            if not claude_runner.find_claude(cfg):
                missing.append("claude")
        elif not which(tool):
            missing.append(tool)
    return missing


def run_job(workspace: Path, cfg: Mapping[str, Any], name: str, *, dry_run: bool = False,
            force: bool = False, no_jitter: bool = False, sleep: Callable[[float], None] = time.sleep,
            rng: Optional[random.Random] = None, now: Optional[Callable[[], _dt.datetime]] = None,
            argv_override: Optional[List[str]] = None, timeout_override: Optional[float] = None,
            run: Callable[..., TreeResult] = run_tree, notify_user: bool = True,
            jitter_min_override: Optional[int] = None) -> Outcome:
    ws = Path(workspace).resolve()
    tz = cfg.get("locale", {}).get("timezone") or "UTC"
    clock = now or (lambda: tzutil.now(tz))
    if name not in JOB_TABLE:
        return Outcome(name, policy.EXIT_USAGE, "unknown_job",
                       message=f"unknown job: {name} (known: {', '.join(sorted(JOB_TABLE))})")
    configured = {j.name: j for j in jobs_from_config(cfg, only=[name], include_disabled=True)}
    job: Job = configured.get(name) or Job(name=name, argv=list(JOB_TABLE[name]["argv"]),
                                           rule=inst_default_rule(), timeout_s=int(JOB_TABLE[name]["timeout"]),
                                           pause_kind=JOB_TABLE[name]["pause"],
                                           long_lived=name in ("board",))
    jitter_min = job.jitter_min if jitter_min_override is None else jitter_min_override
    stamp = clock().isoformat(timespec="seconds")
    base_row: Dict[str, Any] = {"at": stamp, "job": name, "dry_run": dry_run}
    cmd = argv_override or profile_wrap_argv(*job.argv, "--workspace", str(ws))
    if dry_run and name in DRYRUN_NATIVE:
        cmd = cmd + ["--dry-run"]

    if limits.is_paused(ws, job.pause_kind):
        out = Outcome(name, policy.EXIT_PAUSED, "paused", message="paused: work/PAUSE exists "
                      "(`profile-wrap resume` lifts it)")
        _record(ws, {**base_row, "exit": out.exit, "ok": False, "status": "paused"})
        return out

    if dry_run and name not in DRYRUN_NATIVE:
        lines = [f"dry run: {name}", "would run: " + " ".join(["profile-wrap", *job.argv]),
                 f"timeout {job.timeout_s}s, jitter up to {jitter_min} min; no API call, no model call"]
        _record(ws, {**base_row, "exit": 0, "ok": True, "status": "dry_run"})
        return Outcome(name, 0, "dry_run", message=lines[1], lines=lines)

    if job.min_interval_days and not force and not dry_run:
        last = inst.last_success(ws, name)
        if last is not None:
            age = clock() - (last if last.tzinfo else last.replace(tzinfo=clock().tzinfo))
            if age < _dt.timedelta(days=job.min_interval_days):
                msg = f"not due: last success {last.date()} is under {job.min_interval_days} days ago"
                _record(ws, {**base_row, "exit": 0, "ok": True, "status": "not_due"})
                return Outcome(name, 0, "not_due", message=msg)

    missing = [] if (dry_run or argv_override) else check_tools(name, cfg)
    if missing:
        msg = f"tool missing: {', '.join(missing)} (see `profile-wrap doctor`)"
        _append_log(ws, cfg, name, f"[{stamp}] {msg}", "")
        _record(ws, {**base_row, "exit": 1, "ok": False, "status": "tool_missing", "missing": missing})
        if notify_user:
            _notify(ws, cfg, f"profile-wrap: {name} cannot run", msg)
        return Outcome(name, policy.EXIT_FAIL, "tool_missing", message=msg)

    lock = named_lock(ws, f"job-{name}", stale_after=max(job.timeout_s, 60) + 60, wait=0)
    try:
        lock.acquire()
    except LockHeld:
        msg = "another run of this job is in progress; skipping this one"
        _record(ws, {**base_row, "exit": 0, "ok": True, "status": "busy"})
        return Outcome(name, 0, "busy", message=msg)
    try:
        jitter_s = 0.0
        if jitter_min and not no_jitter and not dry_run:
            jitter_s = round((rng or random).uniform(0, jitter_min * 60), 1)
            _append_log(ws, cfg, name, f"[{stamp}] jitter {jitter_s}s of {jitter_min} min", "")
            sleep(jitter_s)
            if limits.is_paused(ws, job.pause_kind):
                _record(ws, {**base_row, "exit": policy.EXIT_PAUSED, "ok": False, "status": "paused",
                             "jitter_s": jitter_s})
                return Outcome(name, policy.EXIT_PAUSED, "paused", jitter_s=jitter_s,
                               message="paused during the jitter wait")
        limit = timeout_override if timeout_override is not None else (job.timeout_s or 10 ** 9)
        started = time.monotonic()
        res = run(cmd, timeout=limit, cwd=ws, env=child_env(cfg))
        elapsed = round(time.monotonic() - started, 1)
        body = res.stdout + (("\n[stderr]\n" + res.stderr) if res.stderr.strip() else "")
        status = "timeout" if res.timed_out else "ok" if res.rc == 0 else "failed"
        _append_log(ws, cfg, name, f"[{stamp}] {name} exit={res.rc} status={status} {elapsed}s", body)
        _record(ws, {**base_row, "exit": res.rc, "ok": res.rc == 0, "status": status, "seconds": elapsed,
                     "jitter_s": jitter_s, "timed_out": res.timed_out})
        out = Outcome(name, res.rc, status, seconds=elapsed, jitter_s=jitter_s,
                      message=(res.stderr.strip() or res.stdout.strip())[-FATAL_TAIL:])
        if dry_run:
            out.lines = [ln for ln in res.stdout.splitlines()][-50:]
        if res.rc != 0 and notify_user:
            _notify(ws, cfg, f"profile-wrap: {name} {'timed out' if res.timed_out else 'failed'}",
                    f"exit {res.rc}. See data/logs/{name}.log")
        return out
    finally:
        lock.release()


def inst_default_rule():
    from .jobs import Rule
    return Rule("daily", hour=9, minute=0)


# --------------------------------------------------------------------------------- daemon

def daemon(workspace: Path, cfg: Mapping[str, Any], *, tick_s: float = 20.0,
           now: Optional[Callable[[], _dt.datetime]] = None, sleep: Callable[[float], None] = time.sleep,
           run: Optional[Callable[..., Outcome]] = None, max_ticks: Optional[int] = None,
           stop: Optional[threading.Event] = None, out: Callable[[str], None] = print) -> List[str]:
    """Foreground scheduler for containers and people who refuse system schedulers.

    Every enabled job fires by the same rules the native backends use. A job still running is not
    started again. Stops on Ctrl-C, on ``stop`` or after ``max_ticks`` (tests).
    """
    ws = Path(workspace).resolve()
    tz = cfg.get("locale", {}).get("timezone") or "UTC"
    clock = now or (lambda: tzutil.now(tz))
    runner = run or (lambda w, c, n, **kw: run_job(w, c, n, **kw))
    jobs = jobs_from_config(cfg)
    fired: List[str] = []
    nxt: Dict[str, Optional[_dt.datetime]] = {}
    threads: List[threading.Thread] = []
    started = clock()
    for j in jobs:
        nxt[j.name] = started if j.rule.kind == "login" else inst.next_fire(j, started, tz)
    out(f"profile-wrap daemon: {len(jobs)} jobs, timezone {tz}. Ctrl-C to stop.")
    ticks = 0
    try:
        while True:
            t = clock()
            for j in jobs:
                due = nxt.get(j.name)
                if due is not None and t >= due:
                    fired.append(j.name)
                    out(f"{t.isoformat(timespec='seconds')} start {j.name}")
                    th = threading.Thread(target=lambda n=j.name: runner(ws, cfg, n), daemon=False)
                    th.start()
                    threads.append(th)
                    nxt[j.name] = None if j.rule.kind == "login" else inst.next_fire(j, t, tz)
            ticks += 1
            if (max_ticks is not None and ticks >= max_ticks) or (stop is not None and stop.is_set()):
                break
            sleep(tick_s)
    except KeyboardInterrupt:
        out("profile-wrap daemon: stopping")
    for th in threads:
        th.join(timeout=5)
    return fired
