"""Entry point of the frozen Profile-Wrap desktop app.

No arguments: open the app (``profile-wrap gui``). A first run with no workspace creates the demo
workspace in ~/profile-wrap/default so the window has something to show. Any arguments are passed
through to the normal CLI, so ``Profile-Wrap --selftest`` and ``Profile-Wrap demo run`` both work.
"""
from __future__ import annotations

import multiprocessing
import sys


def _argv(argv: list[str]) -> list[str]:
    if not argv:
        return ["gui"]
    if argv[0].startswith("-") and argv[0] not in ("-h", "--help", "--version"):
        return ["gui", *argv]  # e.g. --selftest, --browser
    return argv


def _ensure_workspace() -> None:
    from profile_wrap import cli, config, paths
    import argparse
    ws = cli.resolve_workspace(argparse.Namespace(workspace=None, profile=None))
    if not config.config_path(ws).is_file():
        cli.main(["init", "--demo", "--yes", "--workspace", str(ws)])


def main() -> int:
    multiprocessing.freeze_support()
    argv = _argv(sys.argv[1:])
    if argv == ["gui"]:
        try:
            _ensure_workspace()
        except Exception as exc:  # noqa: BLE001 - the window still opens; it explains the problem
            print(f"Profile-Wrap: could not prepare a workspace ({exc})", file=sys.stderr)
    from profile_wrap.cli import main as cli_main
    return cli_main(argv)


if __name__ == "__main__":
    sys.exit(main())
