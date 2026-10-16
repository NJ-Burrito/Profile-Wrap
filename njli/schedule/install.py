"""Install, remove, query and preview the scheduler entries for a workspace.

Everything the installer creates is recorded in ``.njl/workspace.json`` under ``created_schedule``;
``remove`` deletes exactly those entries and nothing else. ``--dry-run`` returns the exact files and
commands without touching the machine. Commands go through an injectable ``run`` so tests can record
them; the real round trips are exercised in CI on each OS (``tests/integration/schedule``).
"""
from __future__ import annotations

import datetime as _dt
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from njli import paths, tzutil
from njli.atomic import atomic_write_bytes, atomic_write_json
from njli.bootstrap import runtime as runtime_mod
from njli.fsutil import read_json, read_jsonl
from njli.plan.locking import guarded

from . import backends as bk
from .jobs import Job, ScheduleError, jobs_from_config, to_local_rule

Runner = Callable[[Sequence[str], Optional[str]], Tuple[int, str]]
STATE_REL = ".njl/workspace.json"


def default_run(cmd: Sequence[str], stdin: Optional[str] = None) -> Tuple[int, str]:
    try:
        r = subprocess.run(list(cmd), input=stdin, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=120,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, f"{cmd[0]}: {exc}"
    return r.returncode, (r.stdout + r.stderr).strip()


# --------------------------------------------------------------------------- backend choice

def platform_name(platform: Optional[str] = None) -> str:
    p = platform or sys.platform
    return "windows" if p.startswith("win") else "macos" if p == "darwin" else "linux"


def detect_backend(cfg: Mapping[str, Any], run: Runner = default_run, platform: Optional[str] = None) -> str:
    choice = cfg.get("schedule", {}).get("backend", "auto")
    if choice not in ("auto", "windows", "systemd", "cron", "launchd", "daemon"):
        raise ScheduleError(f"schedule.backend {choice!r} is not one of auto, windows, systemd, cron, launchd, daemon")
    if choice != "auto":
        return choice
    osn = platform_name(platform)
    if osn == "windows":
        return "windows"
    if osn == "macos":
        return "launchd"
    rc, _ = run(["systemctl", "--user", "show-environment"], None)
    return "systemd" if rc == 0 else "cron"


def build_context(workspace: Path, cfg: Mapping[str, Any], *, platform: Optional[str] = None,
                  which: Callable[..., Optional[str]] = shutil.which, entry: Optional[List[str]] = None,
                  path_env: Optional[str] = None, home: Optional[Path] = None, uid: Optional[int] = None,
                  require_runtime: bool = True) -> bk.Context:
    """Resolve the interpreter, the stable runtime and the tools' absolute paths now, at install time."""
    ws = Path(workspace).resolve()
    if entry is None:
        if require_runtime and runtime_mod.current_version(paths.runtime_dir()) is None:
            raise ScheduleError("there is no stable runtime for the scheduler to call. "
                                "Run `njli runtime install` first (schedulers never call the plugin folder).")
        entry = runtime_mod.entry_command()
    path_env = os.environ.get("PATH", "") if path_env is None else path_env
    tools: Dict[str, str] = {}
    for tool in bk.CAPTURED_TOOLS:
        found = which(tool, path=path_env) if path_env else which(tool)
        if found:
            tools[tool] = str(Path(found).resolve()) if platform_name(platform) != "windows" else str(found)
    pythonw = None
    if platform_name(platform) == "windows":
        cand = Path(entry[0]).with_name("pythonw.exe")
        pythonw = str(cand) if cand.is_file() else None
    return bk.Context(profile=cfg.get("profile_id", "default"), workspace=str(ws), entry=list(entry),
                      path_env=path_env, tools=tools, home=str(home or paths.home()),
                      uid=os.getuid() if uid is None and hasattr(os, "getuid") else (uid or 501),
                      pythonw=pythonw)


# --------------------------------------------------------------------------- plan

def plan_rows(cfg: Mapping[str, Any], local_tz: Optional[str] = None, *, include_disabled: bool = True,
              reference: Optional[_dt.date] = None) -> List[Dict[str, Any]]:
    cfg_tz = cfg.get("locale", {}).get("timezone") or "UTC"
    local_tz = local_tz or tzutil.detect_timezone()
    rows = []
    enabled_names = {j.name for j in jobs_from_config(cfg)}
    for job in jobs_from_config(cfg, include_disabled=True):
        enabled = job.name in enabled_names
        if not include_disabled and not enabled:
            continue
        local, changed = to_local_rule(job.rule, cfg_tz, local_tz, reference)
        rows.append({"job": job.name, "enabled": enabled, "when": job.rule.describe(),
                     "timezone": cfg_tz, "local_when": local.describe() if changed else "",
                     "local_timezone": local_tz if changed else "", "jitter_min": job.jitter_min,
                     "timeout_s": job.timeout_s, "command": " ".join(["njli", *job.argv])})
    return rows


def localised_jobs(cfg: Mapping[str, Any], only: Optional[Sequence[str]], local_tz: Optional[str],
                   reference: Optional[_dt.date] = None) -> List[Job]:
    """Enabled jobs with their rules converted to the machine's timezone (what the OS scheduler needs)."""
    cfg_tz = cfg.get("locale", {}).get("timezone") or "UTC"
    local_tz = local_tz or tzutil.detect_timezone()
    out = []
    for job in jobs_from_config(cfg, only=only):
        rule, _ = to_local_rule(job.rule, cfg_tz, local_tz, reference)
        job.rule = rule
        out.append(job)
    return out


# --------------------------------------------------------------------------- state

def _state_path(ws: Path) -> Path:
    return Path(ws) / STATE_REL


def read_state(ws: Path) -> Dict[str, Any]:
    data = read_json(_state_path(ws), default={})
    return data if isinstance(data, dict) else {}


def _write_entries(ws: Path, mutate: Callable[[List[Dict[str, Any]]], List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    with guarded(ws, "workspace-state", stale_after=120, wait=10):
        state = read_state(ws)
        state["created_schedule"] = mutate(list(state.get("created_schedule", [])))
        _state_path(ws).parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(_state_path(ws), state)
        return state["created_schedule"]


def recorded(ws: Path) -> List[Dict[str, Any]]:
    return list(read_state(ws).get("created_schedule", []))


# --------------------------------------------------------------------------- results

@dataclass
class Action:
    what: str               # write | run | remove-file
    target: str
    text: str = ""

    def line(self) -> str:
        return {"write": f"write   {self.target}", "run": f"run     {self.target}",
                "remove-file": f"delete  {self.target}"}[self.what]


@dataclass
class Result:
    backend: str
    dry_run: bool
    actions: List[Action] = field(default_factory=list)
    entries: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _systemd_dir(ctx: bk.Context) -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    return (Path(xdg) if xdg else Path(ctx.home) / ".config") / "systemd" / "user"


def _launchd_dir(ctx: bk.Context) -> Path:
    return Path(ctx.home) / "Library" / "LaunchAgents"


def _utf16(text: str) -> bytes:
    return b"\xff\xfe" + text.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-16-le")


# --------------------------------------------------------------------------- install

def install(workspace: Path, cfg: Mapping[str, Any], *, backend: Optional[str] = None,
            only: Optional[Sequence[str]] = None, dry_run: bool = False, run: Runner = default_run,
            ctx: Optional[bk.Context] = None, local_tz: Optional[str] = None,
            platform: Optional[str] = None) -> Result:
    ws = Path(workspace).resolve()
    backend = backend or detect_backend(cfg, run, platform)
    res = Result(backend=backend, dry_run=dry_run)
    if backend == "daemon":
        res.notes.append("backend 'daemon': nothing to install. Run `njli daemon` in a terminal, a "
                         "container or a service manager you control.")
        return res
    all_known = {j.name for j in jobs_from_config(cfg, include_disabled=True)}
    for name in only or ():
        if name not in all_known:
            res.errors.append(f"unknown job: {name}")
        elif name not in {j.name for j in jobs_from_config(cfg)}:
            res.errors.append(f"job {name} is not enabled in config.schedule.jobs (and post_due also needs "
                              "posting.mode=api_scheduled with a valid acknowledgement)")
    if res.errors:
        return res
    jobs = localised_jobs(cfg, only, local_tz)
    if not jobs:
        res.notes.append("no job is enabled: nothing to install")
        return res
    try:
        ctx = ctx or build_context(ws, cfg, platform=platform, require_runtime=not dry_run)
    except ScheduleError as exc:
        res.errors.append(str(exc))
        return res
    arts = bk.render(backend, ctx, jobs)
    created: List[Dict[str, Any]] = []
    stamp = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")

    def record(art: bk.Artifact, path: str = "") -> None:
        created.append({"backend": backend, "job": art.job, "kind": art.kind, "name": art.name,
                        "path": path, "installed_at": stamp})

    if backend == "windows":
        for art in arts:
            xml_path = ws / "data" / "schedule" / art.filename
            res.actions.append(Action("write", str(xml_path), art.text))
            for cmd in bk.windows_commands(ctx, art, str(xml_path)):
                res.actions.append(Action("run", " ".join(cmd)))
            record(art, str(xml_path))
    elif backend == "systemd":
        udir = _systemd_dir(ctx)
        for art in arts:
            res.actions.append(Action("write", str(udir / art.filename), art.text))
            record(art, str(udir / art.filename))
        for cmd in bk.systemd_commands(arts):
            res.actions.append(Action("run", " ".join(cmd)))
    elif backend == "cron":
        block = arts[0]
        res.actions.append(Action("run", "crontab -l", ""))
        res.actions.append(Action("write", "crontab (managed block only)", block.text))
        res.actions.append(Action("run", "crontab -"))
        record(block, "")
        res.notes.append("cron has no catch-up: a post slot missed while the machine slept follows the "
                         "missed-slot rule. On a server, `loginctl enable-linger` keeps user timers running.")
    elif backend == "launchd":
        ldir = _launchd_dir(ctx)
        for art in arts:
            res.actions.append(Action("write", str(ldir / art.filename), art.text))
            for cmd in bk.launchd_commands(ctx, art, str(ldir / art.filename)):
                res.actions.append(Action("run", " ".join(cmd)))
            record(art, str(ldir / art.filename))
        missing = [t for t in bk.CAPTURED_TOOLS if t not in ctx.tools]
        if missing:
            res.notes.append("launchd runs with a minimal PATH and these tools were not found now: "
                             + ", ".join(missing))
        res.notes.append("launchd runs missed intervals once after sleep but cannot wake the Mac; "
                         "see `pmset` in docs/SCHEDULING.md.")
    res.entries = created
    if dry_run:
        return res

    # ---- for real
    def fail(msg: str) -> Result:
        res.errors.append(msg)
        return res

    done: List[Dict[str, Any]] = []
    if backend == "windows":
        for art, entry in zip(arts, created):
            p = Path(entry["path"])
            p.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_bytes(p, _utf16(art.text))
            rc, out = run(bk.windows_commands(ctx, art, str(p))[0], None)
            if rc != 0:
                _write_entries(ws, lambda cur, d=done: _merge(cur, d))
                return fail(f"schtasks could not register {art.name}: {out}")
            done.append(entry)
    elif backend == "systemd":
        udir = _systemd_dir(ctx)
        udir.mkdir(parents=True, exist_ok=True)
        for art in arts:
            atomic_write_bytes(udir / art.filename, art.text.encode("utf-8"))
        for entry in created:
            done.append(entry)
        _write_entries(ws, lambda cur: _merge(cur, done))
        for cmd in bk.systemd_commands(arts):
            rc, out = run(cmd, None)
            if rc != 0:
                return fail(f"{' '.join(cmd)} failed: {out}")
    elif backend == "cron":
        rc, current = run(["crontab", "-l"], None)
        current = current if rc == 0 else ""
        merged = bk.merge_cron_block(current, ctx, jobs)
        rc, out = run(["crontab", "-"], merged)
        if rc != 0:
            return fail(f"crontab could not be written: {out}")
        done.extend(created)
    elif backend == "launchd":
        ldir = _launchd_dir(ctx)
        ldir.mkdir(parents=True, exist_ok=True)
        for art, entry in zip(arts, created):
            p = ldir / art.filename
            atomic_write_bytes(p, art.text.encode("utf-8"))
            done.append(entry)
            _write_entries(ws, lambda cur, d=done: _merge(cur, d))
            run(bk.launchd_remove_commands(ctx, art.name)[0], None)  # reinstall: ignore "not loaded"
            rc, out = run(bk.launchd_commands(ctx, art, str(p))[0], None)
            if rc != 0:
                return fail(f"launchctl could not load {art.name}: {out}")
    _write_entries(ws, lambda cur: _merge(cur, done))
    return res


def _merge(current: List[Dict[str, Any]], new: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    keys = {(e["backend"], e["name"]) for e in new}
    return [e for e in current if (e.get("backend"), e.get("name")) not in keys] + list(new)


# --------------------------------------------------------------------------- remove

def remove(workspace: Path, cfg: Mapping[str, Any], *, only: Optional[Sequence[str]] = None,
           dry_run: bool = False, run: Runner = default_run, ctx: Optional[bk.Context] = None) -> Result:
    """Delete exactly the entries recorded in ``created_schedule`` (optionally only some jobs)."""
    ws = Path(workspace).resolve()
    entries = [e for e in recorded(ws) if not only or e.get("job") in only or e.get("job") == "*"]
    res = Result(backend=",".join(sorted({e["backend"] for e in entries})) or "none", dry_run=dry_run,
                 entries=entries)
    if not entries:
        res.notes.append("nothing recorded: no scheduler entries were created by njli in this workspace")
        return res
    removed: List[Dict[str, Any]] = []
    profile = cfg.get("profile_id", "default")
    uid = os.getuid() if hasattr(os, "getuid") else 501
    cron_done = False
    for e in entries:
        b = e["backend"]
        if b == "windows":
            res.actions.append(Action("run", f"schtasks /Delete /TN {e['name']} /F"))
            if e.get("path"):
                res.actions.append(Action("remove-file", e["path"]))
            if not dry_run:
                rc, out = run(["schtasks", "/Delete", "/TN", e["name"], "/F"], None)
                if rc != 0 and "cannot find" not in out.lower() and "does not exist" not in out.lower():
                    res.errors.append(f"schtasks could not delete {e['name']}: {out}")
                    continue
                _unlink(e.get("path"))
        elif b == "systemd":
            res.actions.append(Action("run", f"systemctl --user disable --now {e['name']}"))
            res.actions.append(Action("remove-file", e["path"]))
            if not dry_run:
                run(["systemctl", "--user", "disable", "--now", e["name"]], None)
                _unlink(e.get("path"))
        elif b == "cron":
            if cron_done:
                continue
            cron_done = True
            res.actions.append(Action("run", "crontab -l"))
            res.actions.append(Action("write", f"crontab (without the njli:{profile} block)"))
            if not dry_run:
                rc, current = run(["crontab", "-l"], None)
                rest = bk.strip_cron_block(current if rc == 0 else "", profile)
                if rest.strip():
                    rc, out = run(["crontab", "-"], rest)
                else:
                    rc, out = run(["crontab", "-r"], None)
                if rc != 0:
                    res.errors.append(f"crontab could not be updated: {out}")
                    continue
        elif b == "launchd":
            res.actions.append(Action("run", f"launchctl bootout gui/{uid}/{e['name']}"))
            res.actions.append(Action("remove-file", e["path"]))
            if not dry_run:
                run(["launchctl", "bootout", f"gui/{uid}/{e['name']}"], None)
                _unlink(e.get("path"))
        removed.append(e)
    if systemd_touched(entries) and not dry_run:
        run(["systemctl", "--user", "daemon-reload"], None)
    if not dry_run and removed:
        gone = {(e["backend"], e["name"]) for e in removed}
        _write_entries(ws, lambda cur: [e for e in cur if (e.get("backend"), e.get("name")) not in gone])
    return res


def systemd_touched(entries: Sequence[Mapping[str, Any]]) -> bool:
    return any(e.get("backend") == "systemd" for e in entries)


def _unlink(path: Optional[str]) -> None:
    if path:
        try:
            Path(path).unlink()
        except OSError:
            pass


# --------------------------------------------------------------------------- status / next

def last_runs(ws: Path) -> Dict[str, Dict[str, Any]]:
    rows, _bad = read_jsonl(Path(ws) / "data" / "logs" / "runs.jsonl")
    out: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        if isinstance(r, dict) and r.get("job"):
            out[r["job"]] = r
    return out


def last_success(ws: Path, job: str) -> Optional[_dt.datetime]:
    rows, _ = read_jsonl(Path(ws) / "data" / "logs" / "runs.jsonl")
    best = None
    for r in rows:
        if isinstance(r, dict) and r.get("job") == job and r.get("ok") and r.get("at") and not r.get("dry_run"):
            try:
                best = _dt.datetime.fromisoformat(r["at"])
            except ValueError:
                continue
    return best


def next_fire(job: Job, after: _dt.datetime, tz: str) -> Optional[_dt.datetime]:
    """The next moment ``job`` fires after ``after`` (aware, in ``tz``); None for login and long-lived jobs."""
    r = job.rule
    local = after.astimezone(tzutil.get_zone(tz))
    if r.kind == "login":
        return None
    if r.kind == "interval":
        return local + _dt.timedelta(minutes=r.interval_min)
    for add in range(0, 9):
        day = local.date() + _dt.timedelta(days=add)
        if r.kind == "weekly" and day.weekday() != r.weekday:
            continue
        cand = tzutil.localize(_dt.datetime.combine(day, _dt.time(r.hour, r.minute)), tz)
        if cand > local:
            return cand
    return None


def upcoming(cfg: Mapping[str, Any], now: _dt.datetime, hours: int = 48) -> List[Dict[str, Any]]:
    tz = cfg.get("locale", {}).get("timezone") or "UTC"
    end = now + _dt.timedelta(hours=hours)
    rows: List[Dict[str, Any]] = []
    for job in jobs_from_config(cfg):
        t = next_fire(job, now, tz)
        step = _dt.timedelta(minutes=job.rule.interval_min) if job.rule.kind == "interval" else None
        while t is not None and t <= end:
            rows.append({"job": job.name, "at": t.isoformat(timespec="minutes")})
            if step is None or len(rows) > 500:
                break
            t = t + step
        if job.rule.kind == "login":
            rows.append({"job": job.name, "at": "at login"})
    return sorted(rows, key=lambda r: (r["at"] == "at login", r["at"]))


def status(workspace: Path, cfg: Mapping[str, Any], *, run: Runner = default_run,
           now: Optional[_dt.datetime] = None) -> Dict[str, Any]:
    ws = Path(workspace).resolve()
    tz = cfg.get("locale", {}).get("timezone") or "UTC"
    now = now or tzutil.now(tz)
    rec = recorded(ws)
    expected = {j.name for j in jobs_from_config(cfg)}
    installed = {e["job"] for e in rec if e.get("job") != "*"}
    if any(e["backend"] == "cron" for e in rec):
        installed |= expected  # one block holds them all: checked below
    runs = last_runs(ws)
    live: Dict[str, bool] = {}
    for e in rec:
        b = e["backend"]
        if b == "windows":
            rc, _ = run(["schtasks", "/Query", "/TN", e["name"]], None)
            live[e["job"]] = rc == 0
        elif b == "systemd":
            rc, out = run(["systemctl", "--user", "is-enabled", e["name"]], None)
            live[e["job"]] = live.get(e["job"], False) or rc == 0
        elif b == "cron":
            rc, out = run(["crontab", "-l"], None)
            has = rc == 0 and bk.cron_block_markers(cfg.get("profile_id", "default"))[0] in out
            for name in expected:
                live[name] = has
        elif b == "launchd":
            uid = os.getuid() if hasattr(os, "getuid") else 501
            rc, _ = run(["launchctl", "print", f"gui/{uid}/{e['name']}"], None)
            live[e["job"]] = rc == 0
    jobs = {j.name: j for j in jobs_from_config(cfg)}
    rows = []
    for name in sorted(expected | installed):
        last = runs.get(name, {})
        nxt = next_fire(jobs[name], now, tz) if name in jobs else None
        rows.append({"job": name, "expected": name in expected, "recorded": name in installed,
                     "registered": live.get(name, False), "last_run": last.get("at", ""),
                     "last_exit": last.get("exit"), "next_run": nxt.isoformat(timespec="minutes") if nxt else ""})
    drift = [r["job"] for r in rows if r["expected"] != r["recorded"] or (r["recorded"] and not r["registered"])]
    return {"profile": cfg.get("profile_id", "default"), "rows": rows, "drift": drift,
            "entries": len(rec)}
