#!/usr/bin/env python3
"""Launcher: run njli from this source tree (the plugin dir).

Scheduled jobs never use this file; they call the stable copy made by
``njli runtime install`` (<data>/runtime/current). This shim stays parseable by Python 3.9
so it can print one actionable message instead of a SyntaxError.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from njli.bootstrap import find_python  # noqa: E402


def _fake_version():
    # Test hook, honoured only when NJLI_TEST=1: pretend to be an older interpreter.
    if os.environ.get("NJLI_TEST") == "1" and os.environ.get("NJLI_FAKE_PYVER"):
        return tuple(int(p) for p in os.environ["NJLI_FAKE_PYVER"].split(".")[:3])
    return None


def run():
    message = find_python.version_message(_fake_version())
    if message:
        sys.stderr.write(message + "\n")
        return 1
    from njli.cli import main
    return main()


if __name__ == "__main__":
    sys.exit(run())
