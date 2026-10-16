"""Find a Python >= 3.10 and print one actionable message when there is none.

Keep this file parseable by Python 3.9: no ``match``, no ``X | Y`` annotations, no
parenthesised context managers. The shims in ``bin/`` import it before anything else.
"""
from __future__ import print_function

import os
import shutil
import subprocess
import sys

MIN_VERSION = (3, 10)

HINTS = {
    "windows": "winget install Python.Python.3.12   (or: scoop install python)",
    "macos": "brew install python@3.12",
    "linux": "sudo apt install python3.12   (or: sudo dnf install python3.12)",
}


def os_name():
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def version_message(version_info=None, os_label=None):
    """Return None when the version is fine, else exactly one actionable message."""
    info = tuple(version_info if version_info is not None else sys.version_info[:3])
    if info[:2] >= MIN_VERSION:
        return None
    label = os_label or os_name()
    found = ".".join(str(p) for p in info[:3])
    return (
        "njli needs Python 3.10 or newer, but this is Python %s.\n"
        "  Fix: %s\n"
        "  Or install uv (https://docs.astral.sh/uv/) and run:  uv run --python 3.12 njli ..."
        % (found, HINTS.get(label, HINTS["linux"]))
    )


def candidates():
    """Interpreter commands to try, most specific first."""
    if os_name() == "windows":
        out = [["py", "-3.13"], ["py", "-3.12"], ["py", "-3.11"], ["py", "-3.10"], ["py", "-3"]]
    else:
        out = [["python3.13"], ["python3.12"], ["python3.11"], ["python3.10"]]
    return out + [["python3"], ["python"]]


def probe(cmd):
    """Return the (major, minor, micro) of an interpreter command, or None."""
    exe = shutil.which(cmd[0])
    if not exe:
        return None
    try:
        out = subprocess.check_output(
            [exe] + cmd[1:] + ["-c", "import sys;print('%d.%d.%d' % sys.version_info[:3])"],
            stderr=subprocess.STDOUT, timeout=20)
        parts = out.decode("ascii", "replace").strip().split(".")
        return (int(parts[0]), int(parts[1]), int(parts[2]))
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return None


def find(env_override=True):
    """Return (command_list, version) of the first Python >= 3.10, else (None, best_found)."""
    forced = os.environ.get("NJLI_PYTHON") if env_override else None
    best = None
    tries = [[forced]] if forced else []
    tries += candidates()
    for cmd in tries:
        ver = probe(cmd)
        if ver is None:
            continue
        if ver[:2] >= MIN_VERSION:
            return cmd, ver
        if best is None or ver > best:
            best = ver
    return None, best


def main(argv=None):
    """CLI: print the interpreter command for the shims, or the fix message (exit 1)."""
    cmd, ver = find()
    if cmd:
        print(" ".join(cmd))
        return 0
    message = version_message(ver if ver else (0, 0, 0))
    if ver is None:
        message = (
            "njli did not find any Python on PATH.\n  Fix: %s" % HINTS[os_name()]
        )
    sys.stderr.write(message + "\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
