"""``njli board`` and ``njli review list|allow|reject|improve``."""
from __future__ import annotations

import argparse
import json
import sys
import webbrowser
from pathlib import Path
from typing import Any, Dict

from .. import config as config_mod
from .. import policy


def _workspace(args: argparse.Namespace) -> Path:
    from ..cli import resolve_workspace
    ws = resolve_workspace(args)
    if not config_mod.config_path(ws).is_file():
        raise config_mod.ConfigError(f"{ws} is not a workspace (no config/njli.json). Run 'njli init' first, "
                                     "or pass --workspace.")
    return ws


def _cmd_board(args: argparse.Namespace) -> int:
    from .server import BoardServer, PortInUse, probe_health
    ws = _workspace(args)
    try:
        server = BoardServer(ws, port=args.port)
    except PortInUse as exc:
        found = probe_health(args.port) if args.port else None
        print(f"njli board: {exc}", file=sys.stderr)
        if found:
            print("njli board: a board is already answering there.", file=sys.stderr)
        return policy.EXIT_FAIL
    except ValueError as exc:
        print(f"njli board: {exc}", file=sys.stderr)
        return policy.EXIT_FAIL
    recovered = server.prepare()
    print(f"Review board on {server.url}  (workspace {ws.name}; stop it with Ctrl+C)", flush=True)
    for slug in recovered:
        print(f"njli board: {slug} was left revising by a previous run and is back to draft.", flush=True)
    if args.open:
        webbrowser.open(server.url)
    try:
        server.httpd.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
    return policy.EXIT_OK


def _decider(ws: Path, inline_worker: bool = False):
    from .server import BoardApp
    app = BoardApp(ws, start_worker=False)
    app.worker.inline = inline_worker
    return app.store, app.decider, app


def _exit_for(code: int) -> int:
    if code == 200:
        return policy.EXIT_OK
    return policy.EXIT_CONFLICT if code == 409 else policy.EXIT_FAIL


def _show(code: int, payload: Dict[str, Any], as_json: bool) -> int:
    if as_json:
        print(json.dumps({"http": code, **payload}, indent=2, ensure_ascii=False))
    elif code == 200:
        print(f"ok: now {payload.get('status')}")
        for w in payload.get("warnings", []):
            print(f"warning: {w['message']}")
    else:
        print(f"refused ({payload.get('error')}): {payload.get('message')}", file=sys.stderr)
        for line in payload.get("fails", []):
            print(f"  FAIL {line}", file=sys.stderr)
    return _exit_for(code)


def _confirm(prompt: str, yes: bool) -> bool:
    if yes:
        return True
    try:
        interactive = sys.stdin.isatty()
    except (AttributeError, ValueError):
        interactive = False
    if not interactive:
        print("njli review: this needs a person: pass --yes to confirm, or run it in a terminal.", file=sys.stderr)
        return False
    return input(prompt + " [y/N] ").strip().lower() in ("y", "yes")


def _cmd_list(args: argparse.Namespace) -> int:
    store, _decider_, _app = _decider(_workspace(args))
    posts = store.state()["posts"]
    if args.status:
        posts = [p for p in posts if p["status"] == args.status]
    if args.json:
        print(json.dumps(posts, indent=2, ensure_ascii=False))
        return policy.EXIT_OK
    if not posts:
        print("no drafts")
    for p in posts:
        print(f"{p['status']:<11} {p.get('gate') or '-':<5} {p.get('scheduled_at') or '-':<26} {p['slug']}")
    return policy.EXIT_OK


def _cmd_allow(args: argparse.Namespace) -> int:
    _, decider, _app = _decider(_workspace(args))
    if not _confirm(f"Queue {args.slug} for posting?", args.yes):
        return policy.EXIT_FAIL
    code, payload = decider.decide(args.slug, "allow")
    return _show(code, payload, args.json)


def _cmd_reject(args: argparse.Namespace) -> int:
    _, decider, _app = _decider(_workspace(args))
    if not _confirm(f"Reject {args.slug}? It will not be posted.", args.yes):
        return policy.EXIT_FAIL
    code, payload = decider.decide(args.slug, "reject", args.note or "", confirm=True)
    return _show(code, payload, args.json)


def _cmd_improve(args: argparse.Namespace) -> int:
    store, decider, app = _decider(_workspace(args), inline_worker=True)
    code, payload = decider.decide(args.slug, "improve", args.note)
    if code == 200:
        app.worker.run_queued()  # after decide() released its lock
        result = app.worker.last_result
        payload = {**payload, "status": store.status_of(store.read_meta(store.find(args.slug)[1])[0], "drafts"),
                   "gates": result.get("gates"), "error": result.get("error")}
        if result.get("error"):
            print(f"njli review: the revision failed: {result['error']}", file=sys.stderr)
            return policy.EXIT_FAIL
    return _show(code, payload, args.json)


def register(subparsers: Any) -> None:
    from ..cli import _common
    p = subparsers.add_parser("board", help="start the local review board (127.0.0.1 only)")
    p.add_argument("--port", type=int, help="port (default: board.port in the config, 8770)")
    p.add_argument("--open", action="store_true", help="open the board in your browser")
    _common(p)
    p.set_defaults(func=_cmd_board)

    r = subparsers.add_parser("review", help="list drafts and decide on them from the terminal")
    rs = r.add_subparsers(dest="review_cmd", required=True)
    q = rs.add_parser("list", help="list drafts with status, gate and slot")
    q.add_argument("--status", choices=policy.POST_STATUSES)
    _common(q)
    q.set_defaults(func=_cmd_list)
    q = rs.add_parser("allow", help="queue a draft (the gate must pass); a worker cannot do this")
    q.add_argument("slug")
    q.add_argument("--yes", action="store_true", help="confirm without asking")
    _common(q)
    q.set_defaults(func=_cmd_allow)
    q = rs.add_parser("reject", help="reject a draft")
    q.add_argument("slug")
    q.add_argument("--note")
    q.add_argument("--yes", action="store_true", help="confirm without asking")
    _common(q)
    q.set_defaults(func=_cmd_reject)
    q = rs.add_parser("improve", help="ask a worker to change a draft, then re-render and re-gate it")
    q.add_argument("slug")
    q.add_argument("--note", required=True, help="what to change")
    _common(q)
    q.set_defaults(func=_cmd_improve)
