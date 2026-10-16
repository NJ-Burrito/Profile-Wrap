"""`njli gate <slug>`, registered through register(subparsers)."""
from __future__ import annotations

import argparse
import json

from .runner import format_lines, run_gate

EXIT_OK, EXIT_FAIL = 0, 1


def _run(args) -> int:
    result = run_gate(getattr(args, "slug", None), getattr(args, "workspace", None),
                      profile=getattr(args, "profile", None))
    if getattr(args, "json", False):
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for line in format_lines(result):
            print(line)
    return EXIT_OK if result["summary"] == "PASS" else EXIT_FAIL


def register(subparsers) -> None:
    p = subparsers.add_parser("gate", help="run the deterministic gates on drafts/<slug> and write gates.json")
    p.add_argument("slug", nargs="?", help="draft folder name under drafts/")
    p.add_argument("--workspace", default=argparse.SUPPRESS, help="workspace path (default: NJLI_WORKSPACE or cwd)")
    p.add_argument("--profile", default=argparse.SUPPRESS, help="profile id (default: default)")
    p.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="print gates.json")
    p.set_defaults(func=_run)
