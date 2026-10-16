"""``profile-wrap calendar``, ``profile-wrap plan`` and ``profile-wrap build-week``, registered through register(subparsers)."""
from __future__ import annotations

import argparse
import datetime as _dt
import json
from pathlib import Path
from typing import Any, Dict, List

from profile_wrap import config as cfgmod
from profile_wrap import limits, policy, tzutil
from profile_wrap.plan import build_week as bw
from profile_wrap.plan import calendar as calmod
from profile_wrap.plan import holidays as hol
from profile_wrap.plan import spread, timing

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
    from profile_wrap.cli import resolve_workspace
    return resolve_workspace(args)


def _cfg(ws: Path) -> Dict[str, Any]:
    return cfgmod.load(ws) if (ws / "config" / "profile-wrap.json").exists() else cfgmod.defaults()


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


# ------------------------------------------------------------------------ calendar

def cmd_calendar_add(args: argparse.Namespace) -> int:
    ws, cfg = _ws(args), None
    cfg = _cfg(ws)
    claims = [c.strip() for c in (args.claims or "").split(",") if c.strip()]
    lang = args.lang or cfg["persona"].get("primary_language", "en")
    fmt = args.format or (cfg["posting"].get("formats_enabled") or ["text"])[0]

    def change(cal: Dict[str, Any]) -> Dict[str, Any]:
        return calmod.add_entry(cal, date=args.date, slug=args.slug, title=args.title, lang=lang, format=fmt,
                                pillar=args.pillar, angle=args.angle, hook=args.hook, claims=claims,
                                time=args.time, time_reason=args.time_reason, series=args.series,
                                pair=args.pair)

    try:
        entry = calmod.update(ws, change)
        report = calmod.validate(calmod.load(ws), cfg, workspace=ws)
    except calmod.CalendarError as exc:
        print(f"FAIL {exc}")
        return FAIL
    problems = [m for m in report.errors if args.slug in m or args.date in m]
    _emit(args, {"ok": not problems, "entry": entry, "errors": problems},
          [f"added {entry['slug']} on {entry['date']}"] + [f"FAIL {m}" for m in problems])
    return FAIL if problems else OK


def cmd_calendar_validate(args: argparse.Namespace) -> int:
    ws = _ws(args)
    cfg = _cfg(ws)
    try:
        report = calmod.validate(calmod.load(ws), cfg, workspace=ws)
    except (calmod.CalendarError, hol.HolidayError) as exc:
        print(f"FAIL {exc}")
        return FAIL
    lines = [f"FAIL {m}" for m in report.errors] + [f"WARN {m}" for m in report.warnings]
    lines.append(f"{'FAIL' if report.errors else 'PASS'} calendar: {len(report.errors)} errors, "
                 f"{len(report.warnings)} warnings")
    _emit(args, {"ok": report.ok, "errors": report.errors, "warnings": report.warnings}, lines)
    return OK if report.ok else FAIL


def cmd_calendar_render(args: argparse.Namespace) -> int:
    ws = _ws(args)
    path = calmod.write_md(ws, calmod.load(ws))
    _emit(args, {"path": str(path)}, [f"wrote {path}"])
    return OK


def cmd_calendar_fill(args: argparse.Namespace) -> int:
    ws = _ws(args)
    cfg = _cfg(ws)
    start = _dt.date.fromisoformat(args.start) if args.start else tzutil.now(cfg["locale"]["timezone"]).date()
    holidays = hol.load(ws, cfg)
    added: List[Dict[str, Any]] = []
    if args.dry_run:
        cal = calmod.load(ws)
        added = calmod.fill(cal, cfg, weeks=args.weeks, start=start, holidays=holidays)
    else:
        added = calmod.update(ws, lambda cal: calmod.fill(cal, cfg, weeks=args.weeks, start=start,
                                                          holidays=holidays))
        calmod.write_md(ws, calmod.load(ws))
    _emit(args, {"added": added, "dry_run": args.dry_run},
          [f"{'would add' if args.dry_run else 'added'} {e['slug']} ({e.get('pillar') or 'no pillar'}, {e['format']})"
           for e in added] + [f"{len(added)} open slots"])
    return OK


# ------------------------------------------------------------------------ plan

def _window_row(day: _dt.date, cfg: Dict[str, Any], holidays: hol.Holidays) -> Dict[str, Any]:
    base = spread.window_for(cfg)
    name = holidays.blocked(day)
    win, shift = holidays.shifted_window(day, base)
    return {"date": day.isoformat(), "weekday": ("mon", "tue", "wed", "thu", "fri", "sat", "sun")[day.weekday()],
            "blocked": name, "window": f"{win[0]}-{win[1]}", "shift": shift}


def cmd_plan_windows(args: argparse.Namespace) -> int:
    ws = _ws(args)
    cfg = _cfg(ws)
    holidays = hol.load(ws, cfg)
    start = _dt.date.fromisoformat(args.start) if args.start else tzutil.now(cfg["locale"]["timezone"]).date()
    weekdays = cfg["posting"].get("weekdays") or []
    rows = []
    for off in range(args.weeks * 7):
        row = _window_row(start + _dt.timedelta(days=off), cfg, holidays)
        if args.all or row["weekday"] in weekdays:
            rows.append(row)
    lines = [f"{r['date']} {r['weekday']}  " + (f"BLOCKED ({r['blocked']})" if r["blocked"] else
             f"window {r['window']}" + (f"  [{r['shift']}]" if r["shift"] else "")) for r in rows]
    _emit(args, {"timezone": cfg["locale"]["timezone"], "rows": rows},
          [f"times are {cfg['locale']['timezone']}"] + lines)
    return OK


def cmd_plan_slots(args: argparse.Namespace) -> int:
    ws = _ws(args)
    cfg = _cfg(ws)
    cal = calmod.load(ws)
    holidays = hol.load(ws, cfg)
    target = args.target
    try:
        _dt.date.fromisoformat(target)
        entries = [e for e in cal["entries"] if e.get("date") == target]
        if not entries:
            print(f"no calendar entry on {target}")
            return FAIL
    except ValueError:
        e = calmod.find(cal, target)
        if e is None:
            print(f"no calendar entry with slug {target}")
            return FAIL
        entries = [e]
    rows = []
    for e in entries:
        hhmm, relaxed, note = bw.assign_time(e, ws, cfg, cal, holidays)
        rows.append({"slug": e["slug"], "date": e["date"], "time": hhmm, "relaxed": relaxed, "note": note,
                     "scheduled_at": bw.scheduled_at(e["date"], hhmm, cfg["locale"]["timezone"])})
    _emit(args, {"slots": rows}, [f"{r['slug']}  {r['date']} {r['time']}  {r['note']}"
                                  + (f"  RELAXED {','.join(r['relaxed'])}" if r["relaxed"] else "") for r in rows])
    return OK


def cmd_plan_recipe(args: argparse.Namespace) -> int:
    ws = _ws(args)
    cfg = _cfg(ws)
    tz = args.tz or cfg["locale"]["timezone"]
    regions = [r.strip() for r in (args.audience or "").split(",") if r.strip()] or         list(cfg["locale"].get("audience_regions") or [])
    if args.list:
        rows = timing.load_recipe()["regions"]
        _emit(args, {"regions": rows}, [f"{r['id']:16} {r['tz']:22} {r['label']}" for r in rows])
        return OK
    sug = timing.suggest_window(tz, regions)
    window_json = json.dumps({"start": sug.start, "end": sug.end})
    cmds = [f"profile-wrap plan recipe --audience {','.join(regions)} --apply" if regions else "profile-wrap plan recipe --apply",
            "or set both ends at once (one key at a time can fail the width rule):",
            f"profile-wrap config set posting.window '{window_json}'"]
    if args.apply:
        rep = cfgmod.set_value(ws, "posting.window", window_json)
        if rep.errors:
            print("FAIL " + "; ".join(rep.errors))
            return FAIL
        if regions:
            rep = cfgmod.set_value(ws, "locale.audience_regions", json.dumps(regions))
            if rep.errors:
                print("FAIL " + "; ".join(rep.errors))
                return FAIL
    lines = [f"your timezone: {tz}; audience: {', '.join(regions) or 'not set'}"]
    lines += [f"  {r}: reads {w} your time" for r, w in sug.per_region.items()]
    lines += [f"suggested posting.window: {sug.start} to {sug.end} ({sug.width + 1} minutes)"]
    lines += [f"note: {n}" for n in sug.notes]
    lines += ["applied to config/profile-wrap.json"] if args.apply else ["to apply:"] + [f"  {c}" for c in cmds]
    lines.append("This is a starting point from other accounts' data, not a promise: docs/references/timing-recipe.md")
    _emit(args, {"timezone": tz, "regions": regions, "start": sug.start, "end": sug.end, "notes": sug.notes,
                 "per_region": sug.per_region, "commands": cmds}, lines)
    return OK


def cmd_plan_holidays(args: argparse.Namespace) -> int:
    ws = _ws(args)
    cfg = _cfg(ws)
    if args.list or not args.preset:
        rows = hol.list_presets()
        _emit(args, {"presets": rows}, [f"{r['id']:14} {r['label']}" for r in rows])
        return OK
    try:
        path = hol.install_preset(ws, args.preset, cfg)
    except hol.HolidayError as exc:
        print(f"FAIL {exc}")
        return FAIL
    _emit(args, {"path": str(path)}, [f"holidays preset '{args.preset}' written to {path}"])
    return OK


# ------------------------------------------------------------------------ build-week

def cmd_build_week(args: argparse.Namespace) -> int:
    ws = _ws(args)
    cfg = _cfg(ws)
    try:
        if args.cleanup:
            moved = bw.cleanup(ws, args.cleanup)
            _emit(args, {"moved": moved}, moved or ["nothing to clean up"])
            return OK
        lo, hi = bw.parse_days(args.days)
        if not args.dry_run and limits.is_paused(ws):
            print("paused: work/PAUSE exists; `profile-wrap resume` to build again")
            return policy.EXIT_PAUSED
        report = bw.build_week(ws, cfg, days=(lo, hi), slug=args.slug, dry_run=args.dry_run)
    except (bw.BuildError, calmod.CalendarError, hol.HolidayError) as exc:
        print(f"FAIL {exc}")
        return FAIL
    lines = []
    for i in report.items:
        tag = {"planned": "would build" if report.dry_run else "planned"}.get(i.status, i.status)
        lines.append(f"{tag:11} {i.date} {i.time} {i.slug} ({i.lang}/{i.format})"
                     + (f"  {i.detail}" if i.detail else ""))
    lines += [f"skipped    {s.slug}: {s.detail}" for s in report.skipped]
    lines.append(f"{'dry run: ' if report.dry_run else ''}{len(report.items)} entries, "
                 f"{len(report.built)} built, {len(report.failed)} failed, {report.model_calls} model calls")
    _emit(args, report.as_dict(), lines)
    return FAIL if report.failed and not report.built else OK


# ------------------------------------------------------------------------ register

def register(subparsers: Any) -> None:
    cal = subparsers.add_parser("calendar", help="the content calendar (strategy/calendar.json)")
    csub = cal.add_subparsers(dest="calendar_cmd", required=True)
    p = csub.add_parser("add", help="add an entry")
    _common(p)
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--slug", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--lang")
    p.add_argument("--format")
    p.add_argument("--pillar")
    p.add_argument("--angle")
    p.add_argument("--hook")
    p.add_argument("--claims", help="comma-separated fact ids, e.g. F01,F02")
    p.add_argument("--time", help="HH:MM; must fit the window or carry --time-reason")
    p.add_argument("--time-reason")
    p.add_argument("--series")
    p.add_argument("--pair", help="slug (or pair id) of the other half of a bilingual pair")
    p.set_defaults(func=_safe(cmd_calendar_add))
    p = csub.add_parser("validate", help="duplicates, window, holidays, claim ids")
    _common(p)
    p.set_defaults(func=_safe(cmd_calendar_validate))
    p = csub.add_parser("render-md", help="write strategy/calendar.md from the JSON")
    _common(p)
    p.set_defaults(func=_safe(cmd_calendar_render))
    p = csub.add_parser("fill", help="add open slots for the next weeks")
    _common(p, dry_run=True)
    p.add_argument("--weeks", type=int, default=1)
    p.add_argument("--start", help="first day, YYYY-MM-DD (default: today)")
    p.set_defaults(func=_safe(cmd_calendar_fill))

    plan = subparsers.add_parser("plan", help="posting windows, slots and holidays")
    psub = plan.add_subparsers(dest="plan_cmd", required=True)
    p = psub.add_parser("windows", help="the posting window for each planned day")
    _common(p)
    p.add_argument("--weeks", type=int, default=2)
    p.add_argument("--start")
    p.add_argument("--all", action="store_true", help="every day, not only posting weekdays")
    p.set_defaults(func=_safe(cmd_plan_windows))
    p = psub.add_parser("slots", help="the per-slug minute for a slug or a date")
    _common(p)
    p.add_argument("target", help="a calendar slug or YYYY-MM-DD")
    p.set_defaults(func=_safe(cmd_plan_slots))
    p = psub.add_parser("recipe", help="suggest posting.window from where your audience is")
    _common(p)
    p.add_argument("--audience", help="comma-separated region ids (see --list)")
    p.add_argument("--tz", help="your timezone (default: config)")
    p.add_argument("--list", action="store_true", help="list the region ids")
    p.add_argument("--apply", action="store_true", help="write posting.window (and the regions) to the config")
    p.set_defaults(func=_safe(cmd_plan_recipe))
    p = psub.add_parser("holidays", help="list or install a holidays preset")
    _common(p)
    p.add_argument("--list", action="store_true")
    p.add_argument("--preset")
    p.set_defaults(func=_safe(cmd_plan_holidays))

    p = subparsers.add_parser("build-week", help="build drafts for the next planned entries (never queues)")
    _common(p, dry_run=True)
    p.add_argument("--days", default="8-14", help="build entries this many days ahead (default 8-14)")
    p.add_argument("--slug", help="build one entry")
    p.add_argument("--cleanup", metavar="SLUG", help="move a failed build's folders to work/trash/")
    p.set_defaults(func=_safe(cmd_build_week))
