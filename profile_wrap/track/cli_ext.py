"""``profile-wrap track``: week, prompt, check, init. Registered through register(subparsers).

``profile-wrap track`` with no subcommand is ``track week`` for the current week (the scheduler's ``track_daily``
job runs it that way).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, List

from profile_wrap import config as cfgmod
from profile_wrap import policy, tzutil
from profile_wrap.track import learnings, week

OK, FAIL, USAGE = policy.EXIT_OK, policy.EXIT_FAIL, policy.EXIT_USAGE


def _ws(args: argparse.Namespace) -> Path:
    from profile_wrap.cli import resolve_workspace
    return resolve_workspace(args)


def _tz(ws: Path) -> str:
    cfg = cfgmod.load(ws) if (ws / "config" / "profile-wrap.json").exists() else cfgmod.defaults()
    return str(cfg["locale"]["timezone"])


def _label(args: argparse.Namespace, tz: str) -> str:
    if getattr(args, "week", None):
        week.parse_week(args.week)
        return str(args.week).strip()
    if getattr(args, "date", None):
        import datetime as dt
        return week.week_label_for(dt.date.fromisoformat(args.date))
    return week.week_label_for(tzutil.now(tz).date())


def _guard(fn: Any) -> Any:
    import functools

    @functools.wraps(fn)
    def wrapper(args: argparse.Namespace) -> int:
        try:
            return int(fn(args))
        except (week.TrackError, tzutil.TimezoneUnavailable, cfgmod.ConfigError, ValueError, OSError) as exc:
            print(f"FAIL {exc}")
            return FAIL

    return wrapper


@_guard
def cmd_week(args: argparse.Namespace) -> int:
    ws = _ws(args)
    tz = _tz(ws)
    label = _label(args, tz)
    report = week.report_for(ws, label, tz)
    if getattr(args, "dry_run", False):
        target = None
    else:
        target = week.write_report(ws, report)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        for line in week.render_lines(report):
            print(line)
        print(f"wrote {target}" if target else "dry run: nothing written")
    return OK


@_guard
def cmd_prompt(args: argparse.Namespace) -> int:
    ws = _ws(args)
    label = _label(args, _tz(ws))
    path = week.weekly_path(ws, label)
    if not path.is_file():
        print(f"FAIL {path} does not exist; run `profile-wrap track week --week {label}` first")
        return FAIL
    report = json.loads(path.read_text(encoding="utf-8"))
    print(learnings.read_prompt(ws, label, report))
    return OK


@_guard
def cmd_check(args: argparse.Namespace) -> int:
    ws = _ws(args)
    label = _label(args, _tz(ws))
    problems: List[str] = []
    rp = learnings.read_path(ws, label)
    if rp.is_file():
        problems += [f"{rp.name}: {p}" for p in learnings.check_read(rp.read_text(encoding="utf-8"))]
    else:
        problems.append(f"{rp} does not exist")
    lp = ws / learnings.LEARNINGS_REL
    if lp.is_file():
        problems += [f"{lp.name}: {p}" for p in learnings.check_learnings(lp.read_text(encoding="utf-8"))]
    if args.json:
        print(json.dumps({"week": label, "problems": problems}, indent=2, ensure_ascii=False))
    else:
        for p in problems:
            print(f"FAIL {p}")
        if not problems:
            print(f"PASS weekly read and LEARNINGS.md for {label}")
    return FAIL if problems else OK


@_guard
def cmd_init(args: argparse.Namespace) -> int:
    ws = _ws(args)
    made = learnings.init_learnings(ws)
    print(f"wrote {made}" if made else f"{ws / learnings.LEARNINGS_REL} already exists; left as it is")
    return OK


def _common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--workspace")
    p.add_argument("--profile")
    p.add_argument("--json", action="store_true")


def _week_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--week", help="ISO week, e.g. 2026-W46 (default: the current week)")
    p.add_argument("--date", help="any date in the week, YYYY-MM-DD")


def register(subparsers: Any) -> None:
    t = subparsers.add_parser("track", help="weekly learnings: numbers from the ledger, a weekly read, LEARNINGS.md")
    _common(t)
    _week_args(t)
    t.add_argument("--dry-run", action="store_true")
    t.set_defaults(func=cmd_week)
    sub = t.add_subparsers(dest="track_cmd")
    w = sub.add_parser("week", help="write metrics/weekly/<week>.json (null stays null: not measured)")
    _common(w)
    _week_args(w)
    w.add_argument("--dry-run", action="store_true", help="print the report, write nothing")
    w.set_defaults(func=cmd_week)
    r = sub.add_parser("prompt", help="print the weekly-read prompt for a week (the model call is yours)")
    _common(r)
    _week_args(r)
    r.set_defaults(func=cmd_prompt)
    c = sub.add_parser("check", help="check the weekly read and LEARNINGS.md headings and line cap")
    _common(c)
    _week_args(c)
    c.set_defaults(func=cmd_check)
    i = sub.add_parser("init", help="create research/analysis-kb/LEARNINGS.md from the template")
    _common(i)
    i.set_defaults(func=cmd_init)
