"""Is the scheduler really working? ``schedule_health()`` answers with structured findings for ``doctor``.

Three kinds of finding, none of them needs the network:

* **heartbeat**: for each enabled job, did it run when it should have? The previous scheduled moment is
  computed from the job's rule and compared with ``data/logs/runs.jsonl`` and the job's heartbeat
  (``data/state/heartbeat.json``). A job that started and never finished is reported too. A job with no
  run at all on a brand-new install is not an alarm (the install time is the earliest a job can be owed).
  ``paused`` and ``not_due`` rows count as "the job fired", not as failures.
* **registration**: does the operating system still hold the entries ``schedule install`` recorded, and are
  they healthy? Windows: the task exists, is not disabled and its "Last Result" is not an error. systemd:
  the timer is enabled and active, nothing is in the failed list, and user timers can run while signed out
  (linger). cron: the managed block is present (and a cron daemon is running where that can be told).
  launchd: the job is loaded and its last exit code is zero.
* **last exit**: the most recent run of a job ended in a failure.

``Finding`` carries the same fields as a doctor check (``id``, ``label``, ``status`` of ``pass`` / ``warn`` /
``fail`` / ``skip``, ``detail``, ``hint``) plus the ``job`` it concerns, so doctor can add each one with
``self.add(f.id, f.label, f.status, f.detail, hint=f.hint)``.
"""
from __future__ import annotations

import datetime as _dt
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from profile_wrap import tzutil
from profile_wrap.fsutil import read_jsonl

from . import backends as bk
from . import install as inst
from .jobs import Job, jobs_from_config
from .runner import read_heartbeats

# A daily or weekly job gets this long after its slot to run (the catch-up window of the backends:
# StartWhenAvailable, Persistent=true, launchd's run-after-sleep) before it counts as "did not run".
CATCHUP_GRACE_H = 6.0
# An interval job is overdue after this many of its own intervals without a run.
INTERVAL_GRACE = 2
# Rows that prove the scheduler fired the job even though no work was done.
FIRED_STATUSES_NOT_FAILURES = ("ok", "paused", "not_due", "busy")
FAILED_STATUSES = ("failed", "timeout", "tool_missing", "crashed", "unknown_job")
# schtasks "Last Result" values that are not errors: 0 success, 0x41301 running, 0x41303 not yet run.
WIN_NOT_ERRORS = (0, 267009, 267011)


@dataclass(frozen=True)
class Finding:
    id: str
    label: str
    status: str          # pass | warn | fail | skip
    detail: str
    hint: str = ""
    job: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


# --------------------------------------------------------------------------- previous fire time

def prev_fire(job: Job, before: _dt.datetime, tz: str) -> Optional[_dt.datetime]:
    """The last moment ``job`` was due at or before ``before`` (aware, in ``tz``); None for login jobs.

    Interval jobs have no fixed anchor (the OS counts from the install or from boot), so this returns
    ``before`` itself and the caller uses the interval as the grace.
    """
    r = job.rule
    if r.kind == "login" or job.long_lived:
        return None
    local = before.astimezone(tzutil.get_zone(tz))
    if r.kind == "interval":
        return local
    for back in range(0, 9):
        day = local.date() - _dt.timedelta(days=back)
        if r.kind == "weekly" and day.weekday() != r.weekday:
            continue
        cand = tzutil.localize(_dt.datetime.combine(day, _dt.time(r.hour, r.minute)), tz)
        if cand <= local:
            return cand
    return None


def _parse(text: Any, tz: str) -> Optional[_dt.datetime]:
    try:
        moment = _dt.datetime.fromisoformat(str(text))
    except ValueError:
        return None
    return moment if moment.tzinfo else tzutil.localize(moment, tz)


# --------------------------------------------------------------------------- heartbeat

def _run_rows(ws: Path) -> Dict[str, List[Dict[str, Any]]]:
    rows, _bad = read_jsonl(Path(ws) / "data" / "logs" / "runs.jsonl")
    out: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        if isinstance(r, dict) and r.get("job") and not r.get("dry_run"):
            out.setdefault(str(r["job"]), []).append(r)
    return out


def _installed_at(ws: Path, job: str, tz: str) -> Optional[_dt.datetime]:
    parsed = [_parse(e.get("installed_at"), tz) for e in inst.recorded(ws)
              if e.get("job") in (job, "*") and e.get("installed_at")]
    stamps = [s for s in parsed if s is not None]
    return max(stamps) if stamps else None


def heartbeat_findings(workspace: Path, cfg: Mapping[str, Any], now: Optional[_dt.datetime] = None
                       ) -> List[Finding]:
    """Per enabled job: ``job_ran:<job>`` (should have run and did not) and ``job_exit:<job>`` (last run failed)."""
    ws = Path(workspace)
    tz = cfg.get("locale", {}).get("timezone") or "UTC"
    now = now or tzutil.now(tz)
    runs = _run_rows(ws)
    beats = read_heartbeats(ws)
    out: List[Finding] = []
    for job in jobs_from_config(cfg):
        if job.long_lived or job.rule.kind == "login":
            continue
        rows = runs.get(job.name, [])
        last = rows[-1] if rows else None
        last_at = _parse(last.get("at"), tz) if last else None
        installed = _installed_at(ws, job.name, tz)
        label = f"Job {job.name} ran on time"
        due = prev_fire(job, now, tz)
        late = False
        if due is not None:
            if job.rule.kind == "interval":
                grace = _dt.timedelta(minutes=job.rule.interval_min * INTERVAL_GRACE)
                since = last_at or installed
                late = since is not None and now - since > grace
                expect = f"every {job.rule.interval_min} min"
            else:
                grace = _dt.timedelta(hours=CATCHUP_GRACE_H)
                # nothing is owed for a slot that came before the entry existed
                owed_now = installed is None or installed <= due
                ran = last_at is not None and last_at >= due - _dt.timedelta(minutes=5)
                late = owed_now and not ran and now > due + grace
                expect = job.rule.describe()
            if late:
                since_txt = last_at.isoformat(timespec="minutes") if last_at else "never"
                out.append(Finding(f"job_ran:{job.name}", label, "warn",
                                   f"{job.name} should have run ({expect}) but its last run was {since_txt}",
                                   "Run `profile-wrap schedule status`; if it is registered, check that the "
                                   "machine was on and signed in (see docs/PLATFORMS.md), then "
                                   f"`profile-wrap run {job.name}` once by hand.", job.name))
            else:
                out.append(Finding(f"job_ran:{job.name}", label, "pass" if last_at or installed else "skip",
                                   f"last run {last_at.isoformat(timespec='minutes')}" if last_at
                                   else "not due yet since it was installed", "", job.name))
        beat = beats.get(job.name, {})
        started, ended = _parse(beat.get("last_start"), tz), _parse(beat.get("last_end"), tz)
        if started is not None and (ended is None or ended < started):
            limit = _dt.timedelta(seconds=(job.timeout_s or 3600) + 300)
            if now - started > limit:
                out.append(Finding(f"job_finished:{job.name}", f"Job {job.name} finished", "warn",
                                   f"{job.name} started {started.isoformat(timespec='minutes')} and never "
                                   "recorded an end (crashed or killed)",
                                   "See data/logs/crash.log and data/logs/" + job.name + ".log.", job.name))
        if last is not None and last.get("status") in FAILED_STATUSES:
            out.append(Finding(f"job_exit:{job.name}", f"Job {job.name} last exit", "warn",
                               f"last run ended {last.get('status')} (exit {last.get('exit')}) at {last.get('at')}",
                               f"See data/logs/{job.name}.log", job.name))
    return out


# --------------------------------------------------------------------------- live registration

def _win_last_result(text: str) -> Optional[int]:
    m = re.search(r"^\s*Last Result:\s*(-?\d+|0x[0-9a-fA-F]+)\s*$", text, re.M | re.I)
    if not m:
        return None
    raw = m.group(1)
    try:
        value = int(raw, 16) if raw.lower().startswith("0x") else int(raw)
    except ValueError:
        return None
    return value & 0xFFFFFFFF if value < 0 else value


def _windows(entries: List[Dict[str, Any]], run: inst.Runner) -> List[Finding]:
    out: List[Finding] = []
    for e in entries:
        name, job = e["name"], e.get("job")
        rc, text = run(["schtasks", "/Query", "/TN", name, "/V", "/FO", "LIST"], None)
        if rc != 0:
            out.append(Finding(f"sched_registered:{job}", f"Task {name} registered", "warn",
                               f"Windows has no task {name}", "Run `profile-wrap schedule install`.", job))
            continue
        status = re.search(r"^\s*Scheduled Task State:\s*(\S+)|^\s*Status:\s*(\S+)", text, re.M | re.I)
        state = (status.group(1) or status.group(2)) if status else ""
        last = _win_last_result(text)
        if state.lower() == "disabled":
            out.append(Finding(f"sched_registered:{job}", f"Task {name} registered", "warn",
                               f"task {name} is disabled", "Enable it in Task Scheduler or reinstall.", job))
        elif last is not None and last not in WIN_NOT_ERRORS:
            out.append(Finding(f"sched_last_result:{job}", f"Task {name} last result", "warn",
                               f"Windows reports last result {last} (0x{last:X}) for {name}",
                               "Look at data/logs/crash.log and the job log; a non-zero result with no "
                               "runs.jsonl row means the runner crashed before it could write one.", job))
        else:
            out.append(Finding(f"sched_registered:{job}", f"Task {name} registered", "pass",
                               f"registered, last result {last if last is not None else 'n/a'}", "", job))
    return out


def _systemd(entries: List[Dict[str, Any]], run: inst.Runner) -> List[Finding]:
    out: List[Finding] = []
    rc, failed_text = run(["systemctl", "--user", "--failed", "--no-legend", "--plain"], None)
    failed = failed_text if rc == 0 else ""
    seen: set = set()
    for e in entries:
        name, job = e["name"], e.get("job")
        if e.get("kind") == "unit-service" and any(x.get("kind") == "unit-timer" and x.get("job") == job
                                                    for x in entries):
            if name in failed:
                out.append(Finding(f"sched_failed:{job}", f"Unit {name} healthy", "warn",
                                   f"systemd lists {name} as failed", f"`journalctl --user -u {name}`", job))
            continue
        if name in seen:
            continue
        seen.add(name)
        rc1, _ = run(["systemctl", "--user", "is-enabled", name], None)
        rc2, _ = run(["systemctl", "--user", "is-active", name], None)
        if rc1 != 0 or rc2 != 0:
            what = "not enabled" if rc1 != 0 else "enabled but not active (it will not fire)"
            out.append(Finding(f"sched_registered:{job}", f"Timer {name} active", "warn",
                               f"{name} is {what}", "Run `profile-wrap schedule install`.", job))
        else:
            out.append(Finding(f"sched_registered:{job}", f"Timer {name} active", "pass", "enabled and active",
                               "", job))
    user = os.environ.get("USER") or os.environ.get("LOGNAME") or ""
    if user:
        rc, text = run(["loginctl", "show-user", user, "-p", "Linger"], None)
        if rc == 0 and "Linger=no" in text:
            out.append(Finding("sched_linger", "systemd linger", "warn",
                               "linger is off: user timers stop when you sign out and do not start at boot",
                               f"Run `loginctl enable-linger {user}` on a headless machine or server."))
        elif rc == 0:
            out.append(Finding("sched_linger", "systemd linger", "pass", "linger is on"))
    return out


def _cron(entries: List[Dict[str, Any]], cfg: Mapping[str, Any], run: inst.Runner) -> List[Finding]:
    rc, text = run(["crontab", "-l"], None)
    begin = bk.cron_block_markers(cfg.get("profile_id", "default"))[0]
    out: List[Finding] = []
    if rc != 0 or begin not in text:
        out.append(Finding("sched_registered:cron", "cron block present", "warn",
                           "the profile-wrap block is missing from the crontab",
                           "Run `profile-wrap schedule install`."))
    else:
        out.append(Finding("sched_registered:cron", "cron block present", "pass", "managed block found"))
    for daemon in ("cron", "crond"):
        rc, _ = run(["pidof", daemon], None)
        if rc == 0:
            out.append(Finding("sched_cron_daemon", "cron daemon running", "pass", f"{daemon} is running"))
            return out
    rc, _ = run(["pidof", "cron"], None)
    if rc == 1:  # pidof exists and found nothing (127 means pidof itself is missing: say nothing)
        out.append(Finding("sched_cron_daemon", "cron daemon running", "warn", "no cron or crond process found",
                           "Start the cron service (for example `sudo systemctl enable --now cron`)."))
    return out


def _launchd(entries: List[Dict[str, Any]], run: inst.Runner) -> List[Finding]:
    uid = os.getuid() if hasattr(os, "getuid") else 501
    out: List[Finding] = []
    for e in entries:
        name, job = e["name"], e.get("job")
        rc, text = run(["launchctl", "print", f"gui/{uid}/{name}"], None)
        if rc != 0:
            out.append(Finding(f"sched_registered:{job}", f"Job {name} loaded", "warn",
                               f"launchd has no job {name}", "Run `profile-wrap schedule install`.", job))
            continue
        m = re.search(r"last exit code\s*=\s*(-?\d+)", text)
        if m and int(m.group(1)) != 0:
            out.append(Finding(f"sched_last_result:{job}", f"Job {name} last exit", "warn",
                               f"launchd reports last exit code {m.group(1)} for {name}",
                               f"See data/logs/{job}.launchd.log", job))
        else:
            out.append(Finding(f"sched_registered:{job}", f"Job {name} loaded", "pass", "loaded", "", job))
    return out


def registration_findings(workspace: Path, cfg: Mapping[str, Any], *, run: inst.Runner = inst.default_run
                          ) -> List[Finding]:
    """Ask the operating system, for each backend that ``schedule install`` recorded, whether it still holds the entries."""
    ws = Path(workspace)
    rec = inst.recorded(ws)
    out: List[Finding] = []
    expected = [j.name for j in jobs_from_config(cfg)]
    if not rec:
        if expected:
            out.append(Finding("sched_installed", "Scheduler entries", "warn",
                               "no scheduler entries are recorded for this workspace",
                               "Run `profile-wrap schedule install` (or `profile-wrap daemon` where there is "
                               "no system scheduler)."))
        else:
            out.append(Finding("sched_installed", "Scheduler entries", "skip", "no job is enabled"))
        return out
    by_backend: Dict[str, List[Dict[str, Any]]] = {}
    for e in rec:
        by_backend.setdefault(e.get("backend", ""), []).append(e)
    if "windows" in by_backend:
        out += _windows(by_backend["windows"], run)
    if "systemd" in by_backend:
        out += _systemd(by_backend["systemd"], run)
    if "cron" in by_backend:
        out += _cron(by_backend["cron"], cfg, run)
    if "launchd" in by_backend:
        out += _launchd(by_backend["launchd"], run)
    recorded_jobs = {e.get("job") for e in rec}
    if "*" not in recorded_jobs:
        for name in expected:
            if name not in recorded_jobs:
                out.append(Finding(f"sched_registered:{name}", f"Job {name} installed", "warn",
                                   f"{name} is enabled in the config but has no scheduler entry",
                                   "Run `profile-wrap schedule install`.", name))
    return out


# --------------------------------------------------------------------------- entry point

def schedule_health(workspace: Path, cfg: Mapping[str, Any], *, now: Optional[_dt.datetime] = None,
                    run: inst.Runner = inst.default_run, live: bool = True) -> List[Finding]:
    """Structured scheduler findings for ``doctor`` (see the module docstring). Never raises.

    ``live=False`` skips the operating-system queries (heartbeat only). ``run`` is injectable for tests.
    """
    findings: List[Finding] = []
    for part in (lambda: heartbeat_findings(workspace, cfg, now),
                 (lambda: registration_findings(workspace, cfg, run=run)) if live else (lambda: [])):
        try:
            findings += part()
        except Exception as exc:  # noqa: BLE001 - the health check itself must never break doctor
            findings.append(Finding("sched_health_error", "Scheduler health check", "warn",
                                    f"could not complete: {type(exc).__name__}: {exc}"))
    return findings


__all__ = ["Finding", "schedule_health", "heartbeat_findings", "registration_findings", "prev_fire"]
