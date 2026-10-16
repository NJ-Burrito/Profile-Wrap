"""``profile-wrap gui [--selftest] [--browser] [--workspace DIR]``."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from .. import config as config_mod
from .. import policy


def _cmd_gui(args: argparse.Namespace) -> int:
    from . import window
    if args.selftest:
        from .selftest import run_selftest
        return run_selftest(json_out=args.json)
    from ..cli import resolve_workspace
    ws = resolve_workspace(args)
    if not config_mod.config_path(ws).is_file():
        print(f"profile-wrap gui: {ws} is not a workspace (no config/profile-wrap.json). "
              "Run 'profile-wrap init' first, or pass --workspace.", file=sys.stderr)
        return policy.EXIT_FAIL
    return window.run(Path(ws), force_browser=args.browser)


def register(subparsers: Any) -> None:
    p = subparsers.add_parser("gui", help="open the desktop app (a native window, or your browser)")
    p.add_argument("--workspace", help="workspace folder (default: current folder, PROFILE_WRAP_WORKSPACE, "
                                       "or ~/profile-wrap/<profile>)")
    p.add_argument("--profile", help="profile id (default: default)")
    p.add_argument("--json", action="store_true", help="machine-readable --selftest result")
    p.add_argument("--browser", action="store_true", help="use your default browser instead of a native window")
    p.add_argument("--selftest", action="store_true",
                   help="start the server headless, check /health and every screen, exit 0; no network")
    p.set_defaults(func=_cmd_gui)
