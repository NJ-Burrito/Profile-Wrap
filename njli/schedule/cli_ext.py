"""``njli schedule ...``, ``njli run <job>`` and ``njli daemon``, registered through register(subparsers).

``njli pause`` and ``njli resume`` stay in the core CLI (they only write the flag files under ``work/``).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

from njli import config as cfgmod
from njli import policy, tzutil
from njli.schedule import install as inst
from njli.schedule import runner
from njli.schedule.jobs import JOB_TABLE, ScheduleError, jobs_from_config

OK, FAIL, USAGE = policy.EXIT_OK, policy.EXIT_FAIL, policy.EXIT_USAGE


def _safe(fn):
    """Turn the errors a user can fix into one readable line and exit code 1."""
    import functools

    @functools.wraps(fn)
    def wrapper(args):
        try:
            return fn(args)
        except (tzutil.TimezoneUnavailable, cfgmod.ConfigError, ValueError, OSError) as exc:
            print(f"FAIL {exc}")
            return FAIL

    return wrapper


def _ws(args: argparse.Namespace) -> Path:
    from njli.cli import resolve_workspace
    return resolve_workspace(args)


def _cfg(ws: Path) -> Dict[str, Any]:
    return cfgmod.load(ws) if (ws / "config" / "njli.json").exists() else cfgmod.defaults()


def _emit(args: argparse.Namespace, payload: Any, lines: List[str]) -> None:
    if getattr(args, "json", False):
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        for line in lines:
            print(line)


def _common(p: argparse.ArgumentParser, dry_run: bool = False) -> None:
    p.add_argument("--workspace")
    p.add_argument("--profile")
    p.add_argument("--json", action="store_true")
    if dry_run:
        p.add_argument("--dry-run", action="store_true")


def _only(args: argparse.Namespace) -> List[str]:
    return [x.strip() for x in (getattr(args, "only", None) or "").split(",") if x.strip()]


def cmd_plan(args: argparse.Namespace) -> int:
    ws = _ws(args)
    cfg = _cfg(ws)
    try:
        rows = inst.plan_rows(cfg, local_tz=args.local_timezone, include_disabled=args.all)
    except ScheduleError as exc:
        print(f"FAIL {exc}")
        return FAIL
    lines = [f"times are {cfg['locale']['timezone']} (the config timezone)"]
    for r in rows:
        mark = "on " if r["enabled"] else "off"
        extra = f"   [machine {r['local_timezone']}: {r['local_when']}]" if r["local_when"] else ""
        jit = f", jitter up to {r['jitter_min']} min" if r["jitter_min"] else ""
        lines.append(f"{mark} {r['job']:16} {r['when']:22} {r['command']}{jit}{extra}")
    _emit(args, {"timezone": cfg["locale"]["timezone"], "jobs": rows}, lines)
    return OK


def cmd_install(args: argparse.Namespace) -> int:
    ws = _ws(args)
    cfg = _cfg(ws)
    try:
        res = inst.install(ws, cfg, backend=args.backend, only=_only(args) or None, dry_run=True)
    except ScheduleError as exc:
        print(f"FAIL {exc}")
        return FAIL
    if res.errors:
        _emit(args, {"ok": False, "errors": res.errors}, [f"FAIL {m}" for m in res.errors])
        return FAIL
    lines = [f"backend: {res.backend}"] + [a.line() for a in res.actions] + [f"note: {n}" for n in res.notes]
    if args.dry_run:
        if args.show_files:
            for a in res.actions:
                if a.text:
                    lines += [f"--- {a.target}", a.text.rstrip("\n")]
        _emit(args, {"ok": True, "dry_run": True, "backend": res.backend,
                     "actions": [{"what": a.what, "target": a.target} for a in res.actions],
                     "notes": res.notes}, lines)
        return OK
    if not res.actions:
        _emit(args, {"ok": True, "installed": 0}, lines)
        return OK
    for line in lines:
        print(line)
    if not args.yes:
        if not sys.stdin.isatty():
            print("Not applied: these are the exact changes. Re-run with --yes to apply them.")
            return USAGE
        if input("Apply these changes? [y/N] ").strip().lower() not in ("y", "yes"):
            print("Not applied.")
            return FAIL
    real = inst.install(ws, cfg, backend=args.backend, only=_only(args) or None, dry_run=False)
    if real.errors:
        _emit(args, {"ok": False, "errors": real.errors}, [f"FAIL {m}" for m in real.errors])
        return FAIL
    _emit(args, {"ok": True, "installed": len(real.entries)},
          [f"installed {len(real.entries)} scheduler entries ({real.backend})"])
    return OK


def cmd_remove(args: argparse.Namespace) -> int:
    ws = _ws(args)
    cfg = _cfg(ws)
    res = inst.remove(ws, cfg, only=_only(args) or None, dry_run=args.dry_run)
    lines = [a.line() for a in res.actions] + [f"note: {n}" for n in res.notes]
    lines += [f"FAIL {m}" for m in res.errors]
    if not res.errors:
        lines.append(("would remove " if args.dry_run else "removed ") + f"{len(res.entries)} entries")
    _emit(args, {"ok": res.ok, "removed": len(res.entries), "errors": res.errors, "dry_run": args.dry_run}, lines)
    return OK if res.ok else FAIL


def cmd_status(args: argparse.Namespace) -> int:
    ws = _ws(args)
    cfg = _cfg(ws)
    st = inst.status(ws, cfg)
    lines = [f"profile {st['profile']}: {st['entries']} entries recorded"]
    for r in st["rows"]:
        state = ("ok" if r["registered"] else "NOT REGISTERED") if r["recorded"] else \
            ("MISSING" if r["expected"] else "extra")
        lines.append(f"{r['job']:16} {state:15} last {r['last_run'] or 'never':25} exit "
                     f"{r['last_exit'] if r['last_exit'] is not None else '-':3} next {r['next_run'] or '-'}")
    if st["drift"]:
        lines.append("drift: " + ", ".join(st["drift"]) + "  (run `njli schedule install`)")
    _emit(args, st, lines)
    return FAIL if st["drift"] and args.strict else OK


def cmd_list(args: argparse.Namespace) -> int:
    ws = _ws(args)
    cfg = _cfg(ws)
    on = {j.name for j in jobs_from_config(cfg)}
    rec = {e.get("job") for e in inst.recorded(ws)}
    rows = [{"job": n, "enabled": n in on, "installed": n in rec, "command": "njli " + " ".join(JOB_TABLE[n]["argv"])}
            for n in sorted(JOB_TABLE)]
    _emit(args, {"jobs": rows}, [f"{'on ' if r['enabled'] else 'off'} {'installed' if r['installed'] else '-':9} "
                                 f"{r['job']:16} {r['command']}" for r in rows])
    return OK


def cmd_next(args: argparse.Namespace) -> int:
    ws = _ws(args)
    cfg = _cfg(ws)
    tz = cfg["locale"]["timezone"]
    rows = inst.upcoming(cfg, tzutil.now(tz), hours=args.hours)
    _emit(args, {"timezone": tz, "hours": args.hours, "fires": rows},
          [f"next {args.hours} hours ({tz})"] + [f"{r['at']}  {r['job']}" for r in rows] if rows else
          [f"nothing fires in the next {args.hours} hours"])
    return OK


def cmd_run(args: argparse.Namespace) -> int:
    ws = _ws(args)
    cfg = _cfg(ws)
    out = runner.run_job(ws, cfg, args.job, dry_run=args.dry_run, force=args.force, no_jitter=args.no_jitter)
    if getattr(args, "json", False):
        print(json.dumps({"job": out.job, "exit": out.exit, "status": out.status, "seconds": out.seconds,
                          "jitter_s": out.jitter_s, "message": out.message}, indent=2))
    else:
        for line in out.lines or ([out.message] if out.message else []):
            print(line)
        print(f"{out.job}: {out.status} (exit {out.exit})")
    return out.exit


def cmd_daemon(args: argparse.Namespace) -> int:
    ws = _ws(args)
    cfg = _cfg(ws)
    if not jobs_from_config(cfg):
        print("no job is enabled in config.schedule.jobs: nothing for the daemon to run")
        return FAIL
    runner.daemon(ws, cfg, tick_s=args.tick)
    return OK


def register(subparsers: Any) -> None:
    sch = subparsers.add_parser("schedule", help="install, inspect and remove scheduled jobs")
    sub = sch.add_subparsers(dest="schedule_cmd", required=True)

    p = sub.add_parser("plan", help="print the jobs and when they fire, in your timezone")
    _common(p)
    p.add_argument("--all", action="store_true", help="include jobs that are switched off")
    p.add_argument("--local-timezone", help="the machine timezone (default: detected)")
    p.set_defaults(func=_safe(cmd_plan))

    p = sub.add_parser("install", help="register the enabled jobs with the OS scheduler")
    _common(p, dry_run=True)
    p.add_argument("--only", help="comma-separated job names")
    p.add_argument("--backend", choices=["windows", "systemd", "cron", "launchd", "daemon"])
    p.add_argument("--yes", action="store_true", help="apply without asking")
    p.add_argument("--show-files", action="store_true", help="with --dry-run: print the file contents")
    p.set_defaults(func=_safe(cmd_install))

    p = sub.add_parser("remove", help="remove exactly what `install` created")
    _common(p, dry_run=True)
    p.add_argument("--only")
    p.set_defaults(func=_safe(cmd_remove))

    p = sub.add_parser("status", help="installed versus expected, last run, next run")
    _common(p)
    p.add_argument("--strict", action="store_true", help="exit 1 when installed and expected differ")
    p.set_defaults(func=_safe(cmd_status))

    p = sub.add_parser("list", help="every known job and whether it is on")
    _common(p)
    p.set_defaults(func=_safe(cmd_list))

    p = sub.add_parser("next", help="what fires in the next 48 hours")
    _common(p)
    p.add_argument("--hours", type=int, default=48)
    p.set_defaults(func=_safe(cmd_next))

    p = sub.add_parser("run", help="run a job now, through the same code path as the scheduler")
    _common(p, dry_run=True)
    p.add_argument("job", choices=sorted(JOB_TABLE))
    p.add_argument("--force", action="store_true", help="ignore the 'ran recently' rule")
    p.add_argument("--no-jitter", action="store_true")
    p.set_defaults(func=_safe(cmd_run))

    p = subparsers.add_parser("run", help="run a scheduled job (this is what the scheduler calls)")
    _common(p, dry_run=True)
    p.add_argument("job", choices=sorted(JOB_TABLE))
    p.add_argument("--force", action="store_true", help="ignore the 'ran recently' rule")
    p.add_argument("--no-jitter", action="store_true", help="skip the jitter sleep (systemd does its own)")
    p.set_defaults(func=_safe(cmd_run))

    p = subparsers.add_parser("daemon", help="foreground scheduler for containers and servers")
    _common(p)
    p.add_argument("--tick", type=float, default=20.0, help="seconds between checks")
    p.set_defaults(func=_safe(cmd_daemon))
