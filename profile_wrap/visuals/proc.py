"""Run external tools with a hard timeout that kills the whole process tree (npx, node, chrome, ffmpeg children)."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from . import VisualsError


@dataclass
class Result:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out

    def tail(self, n: int = 600) -> str:
        text = (self.stderr.strip() + "\n" + self.stdout.strip()).strip()
        return text[-n:]


def kill_tree(proc: "subprocess.Popen[str]") -> None:
    """Kill the process and everything it started. Safe to call on an already-finished process."""
    if proc.poll() is not None and sys.platform != "win32":
        return
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, timeout=30,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        proc.kill()
    except OSError:
        pass


def run(cmd: Sequence[str], cwd: Optional[Path] = None, env: Optional[Dict[str, str]] = None,
        timeout: float = 1800) -> Result:
    """Run ``cmd`` (a list, never a shell string). On timeout the whole tree is killed and ``timed_out`` is set."""
    full_env = dict(os.environ)
    full_env["PYTHONUTF8"] = "1"
    full_env.update(env or {})
    kwargs: dict = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0) | \
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        kwargs["start_new_session"] = True
    try:
        proc = subprocess.Popen(list(cmd), cwd=str(cwd) if cwd else None, env=full_env, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", **kwargs)
    except OSError as exc:
        return Result(127, "", f"{cmd[0]} could not start: {exc}")
    try:
        out, err = proc.communicate(timeout=timeout)
        # A grandchild may outlive a normal exit (a browser the tool forgot to close): sweep the group.
        if sys.platform != "win32":
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                pass
        return Result(proc.returncode, out or "", err or "")
    except subprocess.TimeoutExpired:
        kill_tree(proc)
        try:
            out, err = proc.communicate(timeout=30)
        except subprocess.SubprocessError:
            out, err = "", ""
        return Result(-1, out or "", (err or "") + f"\n{cmd[0]} timed out after {timeout:.0f}s", timed_out=True)


def must(cmd: Sequence[str], what: str, **kw) -> Result:
    res = run(cmd, **kw)
    if not res.ok:
        raise VisualsError(f"{what} failed (exit {res.returncode}): {res.tail()}")
    return res


def split_cmd(cmd: List[str]) -> str:
    return " ".join(cmd)
