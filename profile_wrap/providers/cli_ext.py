"""``profile-wrap providers list|set-key|test|use``.

Exit codes follow ``policy``: 0 ok, 1 failure (including a missing key), 2 usage. A key is read from
a hidden prompt or standard input, never from the command line, and is shown only as its last four
characters.
"""
from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path
from typing import Any, Dict, List

from .. import policy
from . import SPECS, ProviderError, get_provider, keystore, settings


def _ws(args: argparse.Namespace) -> Path:
    from ..cli import resolve_workspace
    return resolve_workspace(args)


def _emit(args: argparse.Namespace, obj: Any) -> None:
    from ..cli import emit_json
    emit_json(obj)


def _key_state(pid: str) -> Dict[str, str]:
    spec = SPECS[pid]
    if not spec.needs_key:
        return {"key": "not needed", "source": "-"}
    found = keystore.get_key(pid)
    if not found:
        return {"key": "missing", "source": "-"}
    return {"key": keystore.mask(found.key), "source": found.source}


def cmd_list(args: argparse.Namespace) -> int:
    chosen = settings.load(_ws(args)) if not getattr(args, "no_workspace", False) else {}
    rows: List[Dict[str, Any]] = []
    for pid, spec in SPECS.items():
        row = {"id": pid, "label": spec.label, "in_use": chosen.get("provider") == pid,
               "model": chosen.get("model") if chosen.get("provider") == pid else spec.default_model,
               **_key_state(pid)}
        rows.append(row)
    if args.json:
        _emit(args, {"providers": rows, "keychain": keystore.keychain_available()})
        return policy.EXIT_OK
    print(f"{'':2}{'provider':12}{'key':14}{'from':9}model")
    for r in rows:
        print(f"{'*' if r['in_use'] else ' ':2}{r['id']:12}{r['key']:14}{r['source']:9}{r['model']}")
    print("keychain: " + ("available" if keystore.keychain_available()
                          else "not available (use PROFILE_WRAP_<PROVIDER>_API_KEY)"))
    return policy.EXIT_OK


def _read_key(args: argparse.Namespace) -> str:
    if args.stdin:
        return sys.stdin.readline().strip()
    return getpass.getpass(f"API key for {args.provider} (hidden): ").strip()


def cmd_set_key(args: argparse.Namespace) -> int:
    spec = SPECS[args.provider]
    if not spec.needs_key:
        print(f"{args.provider} needs no key.")
        return policy.EXIT_OK
    try:
        keystore.set_key(args.provider, _read_key(args))
    except keystore.KeystoreError as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        return policy.EXIT_FAIL
    found = keystore.get_key(args.provider)
    print(f"stored key for {args.provider}: {keystore.mask(found.key) if found else '****'} (OS keychain)")
    return policy.EXIT_OK


def cmd_test(args: argparse.Namespace) -> int:
    ws = _ws(args)
    chosen = settings.load(ws)
    pid = args.provider or chosen.get("provider")
    if not pid:
        print("FAIL no provider chosen. Run `profile-wrap providers use <provider>` first.", file=sys.stderr)
        return policy.EXIT_FAIL
    model = args.model or (chosen.get("model") if chosen.get("provider") == pid else None)
    base = chosen.get("base_url") if chosen.get("provider") == pid else None
    if pid == "claude-code":
        from .. import claude_runner as cr
        from .. import config as cfgmod
        found = cr.find_claude(cfgmod.load(ws) if (ws / "config").exists() else None)
        if not found:
            print("FAIL claude CLI not found. Install it or set PROFILE_WRAP_CLAUDE_BIN.", file=sys.stderr)
            return policy.EXIT_FAIL
        print("PASS claude-code: claude CLI found (no model call made)")
        return policy.EXIT_OK
    try:
        prov = get_provider(pid, model, base)
        prov.api_key()
        res = prov.complete("", [{"role": "user", "content": "Reply with the single word OK."}],
                            max_tokens=16, timeout=args.timeout)
    except ProviderError as exc:
        status = f" status {exc.status}" if exc.status else ""
        print(f"FAIL {pid}: {exc.kind}{status}: {exc}", file=sys.stderr)
        return policy.EXIT_FAIL
    print(f"PASS {pid}: model {res.model} answered (status 200)")
    return policy.EXIT_OK


def cmd_use(args: argparse.Namespace) -> int:
    spec = SPECS[args.provider]
    model = args.model or spec.default_model
    ws = _ws(args)
    settings.save(ws, args.provider, model, args.base_url)
    print(f"provider set: {args.provider}, model {model} (saved in {settings.REL.as_posix()}; no key stored there)")
    if spec.needs_key and not keystore.get_key(args.provider):
        print("WARN " + keystore.missing_key_message(args.provider), file=sys.stderr)
    return policy.EXIT_OK


def _common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--workspace")
    p.add_argument("--profile")
    p.add_argument("--json", action="store_true")


def register(subparsers: Any) -> None:
    p = subparsers.add_parser("providers", help="model providers and their API keys")
    sub = p.add_subparsers(dest="providers_cmd", required=True)
    ids = list(SPECS)

    q = sub.add_parser("list", help="providers, key status (last 4 characters only) and the one in use")
    _common(q)
    q.set_defaults(func=cmd_list)

    q = sub.add_parser("set-key", help="store a key in the OS keychain (hidden prompt or --stdin)")
    q.add_argument("provider", choices=ids)
    q.add_argument("--stdin", action="store_true", help="read the key from one line of standard input")
    _common(q)
    q.set_defaults(func=cmd_set_key)

    q = sub.add_parser("test", help="one cheap call; prints pass or fail and the status, never the key")
    q.add_argument("provider", nargs="?", choices=ids)
    q.add_argument("--model")
    q.add_argument("--timeout", type=float, default=30.0)
    _common(q)
    q.set_defaults(func=cmd_test)

    q = sub.add_parser("use", help="record the provider and model to use (never the key)")
    q.add_argument("provider", choices=ids)
    q.add_argument("--model")
    q.add_argument("--base-url", help="for a self-hosted or proxied endpoint")
    _common(q)
    q.set_defaults(func=cmd_use)
