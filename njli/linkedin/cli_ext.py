"""Commands: auth, selftest, post, due, status, api-versions (registered by ``njli.cli``)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

from .. import config as config_mod
from .. import ledger, limits, policy
from . import auth, due, post, selftest, versions


def _ws(args: argparse.Namespace) -> Path:
    from ..cli import resolve_workspace

    return resolve_workspace(args)


def _emit(args: argparse.Namespace, obj: Any) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def _outcome(args: argparse.Namespace, out: post.Outcome) -> int:
    if getattr(args, "json", False):
        _emit(args, out.as_dict())
    else:
        label = {"posted": "POSTED", "refused": "REFUSED", "needs_check": "NEEDS CHECK",
                 "failed": "FAILED", "stopped": "STOPPED", "paused": "PAUSED",
                 "skipped": "SKIPPED"}.get(out.status, out.status.upper())
        line = f"{label} {out.slug}: {out.reason}".rstrip(": ")
        print(line, file=sys.stderr if out.exit_code not in (0,) else sys.stdout)
        if out.url:
            print(out.url)
    return out.exit_code


# ----------------------------------------------------------------- handlers

def cmd_auth(args: argparse.Namespace) -> int:
    ws = _ws(args)
    cfg = config_mod.load(ws)
    if getattr(args, "what", None) == "check":
        status = auth.token_status(auth.secrets_dir(cfg), int(cfg["linkedin"]["token_warn_days"]))
        if getattr(args, "json", False):
            _emit(args, status)
        else:
            print(f"token: {status['state']} - {status['message']}")
        return policy.EXIT_OK if status["state"] in ("ok", "warn") else policy.EXIT_FAIL
    try:
        auth.run_auth(cfg, paste_redirect=bool(args.paste_redirect), hp=_hp(cfg))
    except Exception as exc:  # noqa: BLE001 - one actionable line, no traceback
        print(f"njli auth: {exc}", file=sys.stderr)
        return policy.EXIT_FAIL
    return policy.EXIT_OK


def _hp(cfg: Dict[str, Any]):
    from . import api

    return api.host_policy(cfg)


def cmd_selftest(args: argparse.Namespace) -> int:
    ws = _ws(args)
    cfg = config_mod.load(ws)
    result = selftest.run_selftest(ws, cfg, getattr(args, "what", None))
    if getattr(args, "json", False):
        _emit(args, result)
    else:
        for c in result["checks"]:
            print(f"{c['result']:4} {c['name']}: {c['detail']}")
        print("selftest: " + result["summary"] + (" (probe only, nothing was posted)"
                                                 if result["probe_only"] else ""))
    return policy.EXIT_OK if result["summary"] == "PASS" else policy.EXIT_FAIL


def _copy_block(p: Dict[str, Any]) -> List[str]:
    lines = ["--- caption ---", _unesc(p["body"]["commentary"]), ""]
    if p.get("first_comment"):
        lines += ["--- first comment (post it yourself) ---", p["first_comment"], ""]
    lines += ["--- alt text ---", p.get("alt") or "", ""]
    if p["assets"]:
        lines += ["--- media ---"] + p["assets"]
    return lines


def _unesc(text: str) -> str:
    import re

    text = re.sub(r"\{hashtag\|\\#\|([^}]*)\}", r"#\1", text)
    return re.sub(r"\\([\\|{}@\[\]()<>#*_~])", r"\1", text)


def cmd_post(args: argparse.Namespace) -> int:
    ws = _ws(args)
    cfg = config_mod.load(ws)
    if args.resolve:
        if not (args.posted or args.not_posted):
            print("njli post --resolve needs --posted or --not-posted", file=sys.stderr)
            return policy.EXIT_USAGE
        try:
            row = post.resolve_needs_check(ws, args.slug, bool(args.posted), url=args.url)
        except ValueError as exc:
            print(f"njli post: {exc}", file=sys.stderr)
            return policy.EXIT_FAIL
        print(f"{args.slug}: {row.get('state')}")
        return policy.EXIT_OK
    mode = config_mod.effective_modes(cfg, ws)["posting"]
    if args.dry or mode == "copy" or not args.now:
        try:
            p = post.plan(ws, args.slug, cfg)
        except (OSError, ValueError) as exc:
            print(f"njli post: {exc}", file=sys.stderr)
            return policy.EXIT_FAIL
        if getattr(args, "json", False):
            _emit(args, p)
        else:
            print(f"dry run for '{args.slug}' (nothing is sent, no ledger row is written)")
            print(f"format: {p['format']}  status: {p['status']}  gate: {p['gate']}  "
                  f"gap: {p['gap'] or 'ok'}")
            for prob in p["problems"]:
                print(f"PROBLEM {prob}")
            print()
            print("\n".join(_copy_block(p)))
            if mode == "copy":
                print("\nposting.mode is 'copy': post this by hand.")
            elif not args.dry:
                print(f"\nTo send it: njli post {args.slug} --now")
        return policy.EXIT_OK
    out = post.publish(ws, args.slug, cfg, by="human")
    return _outcome(args, out)


def cmd_due(args: argparse.Namespace) -> int:
    ws = _ws(args)
    cfg = config_mod.load(ws)
    out = due.run_due(ws, cfg)
    return _outcome(args, out)


def cmd_status(args: argparse.Namespace) -> int:
    ws = _ws(args)
    cfg = config_mod.load(ws)
    st = auth.token_status(auth.secrets_dir(cfg), int(cfg["linkedin"]["token_warn_days"]))
    vers = versions.report(cfg)
    modes = config_mod.effective_modes(cfg, ws)
    rows = ledger.entries(ws)
    queue = []
    for p in sorted((ws / "drafts").glob("*/meta.json")):
        try:
            meta = json.loads(p.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            queue.append({"slug": p.parent.name, "status": "unreadable"})
            continue
        queue.append({"slug": meta.get("slug", p.parent.name), "status": meta.get("status"),
                      "scheduled_at": meta.get("scheduled_at")})
    last = ledger.last_activity(ws)
    out: Dict[str, Any] = {"token": st, "api_version": vers.get("selected"), "version_warnings": vers.get("warnings"),
           "modes": modes, "paused": limits.pause_flags(ws), "stop": post.stop_active(ws),
           "ledger": {"rows": len(rows), "needs_check": [r["slug"] for r in rows
                                                         if r.get("state") == "needs_check"],
                      "last_activity": last.isoformat() if last else None},
           "drafts": queue}
    if getattr(args, "json", False):
        _emit(args, out)
        return policy.EXIT_OK
    print(f"token: {st['state']} - {st['message']}")
    print(f"api version: {vers.get('selected')}" + ("".join(f"\n  warning: {w}" for w in vers.get("warnings", []))))
    print(f"posting mode: {modes['posting']}" + (f" (paused: {', '.join(out['paused'])})" if out["paused"] else ""))
    for note in modes["notes"]:
        print(f"  note: {note}")
    if out["stop"]:
        print(f"stopped: {out['stop']}")
    for r in out["ledger"]["needs_check"]:
        print(f"  NEEDS CHECK {r}: confirm with 'njli post {r} --resolve --posted|--not-posted'")
    print(f"ledger rows: {out['ledger']['rows']}")
    for d in queue:
        print(f"  {str(d.get('status')):12} {str(d.get('scheduled_at') or '-'):26} {d['slug']}")
    return policy.EXIT_OK


def _fetch_versions_page() -> str:
    from ..http import HostPolicy, request

    resp = request("GET", versions.VERSIONS_PAGE, hp=HostPolicy(extra_hosts=(versions.VERSIONS_HOST,)),
                   timeout=30.0)
    if not resp.ok:
        raise RuntimeError(f"the versioning page answered {resp.status}")
    return resp.text()


def cmd_api_versions(args: argparse.Namespace) -> int:
    ws = _ws(args)
    cfg = config_mod.load(ws)
    refreshed = None
    if args.refresh:
        try:
            refreshed = versions.refresh(_fetch_versions_page)
        except Exception as exc:  # noqa: BLE001
            print(f"njli api-versions: cannot refresh: {exc}", file=sys.stderr)
            return policy.EXIT_FAIL
    rep = versions.report(cfg)
    if refreshed:
        rep["refresh"] = refreshed
    if getattr(args, "json", False):
        _emit(args, rep)
    else:
        print(f"table retrieved {rep['retrieved']}")
        for v in rep["versions"]:
            print(f"  {v['version']}  sunset {v['sunset'] or 'unknown':10}  {v['state']}")
        print(f"selected: {rep['selected']}")
        for w in rep["warnings"]:
            print(f"  warning: {w}")
        if refreshed:
            print("new versions seen (sunset date unverified): " + (", ".join(refreshed["added"]) or "none"))
    return policy.EXIT_OK if rep["ok"] else policy.EXIT_FAIL


# ----------------------------------------------------------------- registration

def _common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--workspace", default=argparse.SUPPRESS, help="workspace folder")
    p.add_argument("--profile", default=argparse.SUPPRESS, help="profile id")
    p.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="machine-readable output")


def register(subparsers: Any) -> None:
    p = subparsers.add_parser("auth", help="sign in to your own LinkedIn app (3-legged OAuth)")
    p.add_argument("what", nargs="?", choices=["check"], help="'check' shows the token state")
    p.add_argument("--paste-redirect", action="store_true",
                   help="print the link and paste the final address back (SSH, containers)")
    _common(p)
    p.set_defaults(func=cmd_auth)

    p = subparsers.add_parser("selftest", help="read-only checks; never posts")
    p.add_argument("what", nargs="?", choices=["comments"], help="'comments' makes one non-posting probe")
    _common(p)
    p.set_defaults(func=cmd_selftest)

    p = subparsers.add_parser("post", help="preview a post, or send one with --now")
    p.add_argument("slug", help="draft folder name under drafts/")
    p.add_argument("--dry", "--dry-run", dest="dry", action="store_true",
                   help="show the copy-ready block and checks; send nothing")
    p.add_argument("--now", action="store_true", help="send it (the draft must be queued by Allow)")
    p.add_argument("--resolve", action="store_true", help="record whether a needs_check post went out")
    p.add_argument("--posted", action="store_true", help="with --resolve: it is live")
    p.add_argument("--not-posted", dest="not_posted", action="store_true", help="with --resolve: it is not live")
    p.add_argument("--url", help="with --resolve --posted: the post's address")
    _common(p)
    p.set_defaults(func=cmd_post)

    p = subparsers.add_parser("due", help="post the queued draft whose slot has come (scheduled job)")
    _common(p)
    p.set_defaults(func=cmd_due)

    p = subparsers.add_parser("status", help="token, API version, mode, queue and ledger")
    _common(p)
    p.set_defaults(func=cmd_status)

    p = subparsers.add_parser("api-versions", help="show the Linkedin-Version table and the one in use")
    p.add_argument("--refresh", action="store_true", help="look for newer versions on the versioning page")
    _common(p)
    p.set_defaults(func=cmd_api_versions)
