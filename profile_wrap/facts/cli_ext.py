"""`profile-wrap facts ...` and `profile-wrap stats ...`, registered through register(subparsers)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import registers as reg

EXIT_OK, EXIT_FAIL = 0, 1


def _ws(args) -> Path:
    from profile_wrap.gate.config import resolve_workspace
    return resolve_workspace(getattr(args, "workspace", None), getattr(args, "profile", None))


def _cfg(ws: Path) -> dict:
    from profile_wrap.gate.config import load_config
    return load_config(ws)[0]


def _facts_file(ws: Path) -> Path:
    return ws / _cfg(ws)["persona"].get("facts_file", "research/facts.md")


def _stats_file(ws: Path) -> Path:
    return _facts_file(ws).parent / "stats.md"


def _emit(args, payload: dict, lines: list[str]) -> None:
    if getattr(args, "json", False):
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for ln in lines:
            print(ln)


def _lint(args, kind: str) -> int:
    ws = _ws(args)
    path = _facts_file(ws) if kind == "fact" else _stats_file(ws)
    r = reg.load_register(path, kind)
    issues = reg.lint_register(r)
    fails = [m for lvl, m in issues if lvl == "FAIL"]
    lines = [f"{lvl} {m}" for lvl, m in issues] + [
        f"{'FAIL' if fails else 'PASS'} {path.name}: {len(r.entries)} entries, {len(fails)} fail, "
        f"{len(issues) - len(fails)} warn"]
    _emit(args, {"ok": not fails, "path": str(path), "entries": len(r.entries),
                 "issues": [{"level": lvl, "message": m} for lvl, m in issues]}, lines)
    return EXIT_FAIL if fails else EXIT_OK


def _add_fact(args) -> int:
    ws = _ws(args)
    try:
        e = reg.add_entry(_facts_file(ws), "fact", text=args.claim, numbers=args.numbers, source=args.source,
                          ident=args.id)
    except ValueError as exc:
        print(f"FAIL {exc}")
        return EXIT_FAIL
    _emit(args, {"ok": True, "id": e.id, "status": e.status},
          [f"added {e.id} as draft. Verify it yourself in a terminal: profile-wrap facts verify {e.id} --evidence <path|url>"])
    return EXIT_OK


def _add_stat(args) -> int:
    ws = _ws(args)
    cfg = _cfg(ws)
    if args.grade.upper() not in reg.GRADES:
        print(f"FAIL grade must be one of {'/'.join(reg.GRADES)}")
        return EXIT_FAIL
    retrieved = reg.parse_date(args.retrieved) if args.retrieved else reg.today()
    if retrieved is None:
        print("FAIL --retrieved must be an ISO date (YYYY-MM-DD)")
        return EXIT_FAIL
    expires = reg.parse_date(args.expires) if args.expires else reg.default_expiry(
        retrieved, int(cfg["research"].get("stats_expiry_days", 90)))
    if expires is None:
        print("FAIL --expires must be an ISO date (YYYY-MM-DD)")
        return EXIT_FAIL
    try:
        e = reg.add_entry(_stats_file(ws), "stat", text=args.stat, numbers=args.numbers, source=args.url,
                          ident=args.id, extra={"retrieved": retrieved.isoformat(), "expires": expires.isoformat(),
                                                "grade": args.grade.upper(), "sample": args.sample or ""})
    except ValueError as exc:
        print(f"FAIL {exc}")
        return EXIT_FAIL
    _emit(args, {"ok": True, "id": e.id, "status": e.status, "expires": expires.isoformat()},
          [f"added {e.id} as draft (grade {args.grade.upper()}, expires {expires.isoformat()}). "
           f"Verify it yourself: profile-wrap stats verify {e.id} --evidence <path|url>"])
    return EXIT_OK


def _verify(args, kind: str) -> int:
    ws = _ws(args)
    path = _facts_file(ws) if kind == "fact" else _stats_file(ws)
    try:
        e = reg.verify_entry(path, kind, args.id, args.evidence, workspace=ws, verifier=args.verifier or "")
    except reg.VerifyRefused as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        return EXIT_FAIL
    _emit(args, {"ok": True, "id": e.id, "status": e.status}, [f"{e.id} is now verified"])
    return EXIT_OK


def _expire(args) -> int:
    ws = _ws(args)
    when = reg.parse_date(args.today) if args.today else None
    changed = reg.expire_stats(_stats_file(ws), on_date=when, dry_run=args.dry_run)
    verb = "would expire" if args.dry_run else "expired"
    _emit(args, {"ok": True, "expired": changed, "dry_run": bool(args.dry_run)},
          [f"{verb} {i}" for i in changed] or ["no stat has passed its expiry date"])
    return EXIT_OK


def _export(args, kind: str) -> int:
    ws = _ws(args)
    r = reg.load_register(_facts_file(ws) if kind == "fact" else _stats_file(ws), kind)
    if not r.exists:
        print("FAIL " + "; ".join(r.problems))
        return EXIT_FAIL
    print(json.dumps(reg.export_entries(r, args.verified_only), ensure_ascii=False, indent=2))
    return EXIT_OK


def _common(p: argparse.ArgumentParser) -> None:
    # SUPPRESS keeps the global --workspace/--json values when the sub-command does not repeat them
    p.add_argument("--workspace", default=argparse.SUPPRESS, help="workspace path (default: PROFILE_WRAP_WORKSPACE or cwd)")
    p.add_argument("--profile", default=argparse.SUPPRESS, help="profile id (default: default)")
    p.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="machine-readable output")


def register(subparsers) -> None:
    facts = subparsers.add_parser("facts", help="facts register: add, lint, verify, export")
    fs = facts.add_subparsers(dest="facts_cmd", required=True)
    p = fs.add_parser("add", help="add a draft fact")
    p.add_argument("--claim", required=True)
    p.add_argument("--numbers", default="", help="e.g. '30%%; 180 hours'")
    p.add_argument("--source", required=True)
    p.add_argument("--id")
    _common(p)
    p.set_defaults(func=_add_fact)
    p = fs.add_parser("lint", help="check ids, sources, supersedes chains, number units")
    _common(p)
    p.set_defaults(func=lambda a: _lint(a, "fact"))
    p = fs.add_parser("verify", help="mark a fact verified (terminal only, never from an agent)")
    p.add_argument("id")
    p.add_argument("--evidence", required=True, help="file path or http(s) URL that shows the record")
    p.add_argument("--verifier")
    _common(p)
    p.set_defaults(func=lambda a: _verify(a, "fact"))
    p = fs.add_parser("export", help="print the register as JSON")
    p.add_argument("--verified-only", action="store_true")
    _common(p)
    p.set_defaults(func=lambda a: _export(a, "fact"))

    stats = subparsers.add_parser("stats", help="stats register: add, lint, expire, verify")
    ss = stats.add_subparsers(dest="stats_cmd", required=True)
    p = ss.add_parser("add", help="add a draft third-party stat")
    p.add_argument("--stat", required=True)
    p.add_argument("--numbers", default="")
    p.add_argument("--url", required=True)
    p.add_argument("--grade", required=True)
    p.add_argument("--retrieved")
    p.add_argument("--expires")
    p.add_argument("--sample")
    p.add_argument("--id")
    _common(p)
    p.set_defaults(func=_add_stat)
    p = ss.add_parser("lint", help="check the stats register")
    _common(p)
    p.set_defaults(func=lambda a: _lint(a, "stat"))
    p = ss.add_parser("expire", help="mark stats past their expiry date as expired")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--today", help=argparse.SUPPRESS)
    _common(p)
    p.set_defaults(func=_expire)
    p = ss.add_parser("verify", help="mark a stat verified (terminal only)")
    p.add_argument("id")
    p.add_argument("--evidence", required=True)
    p.add_argument("--verifier")
    _common(p)
    p.set_defaults(func=lambda a: _verify(a, "stat"))
