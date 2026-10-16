"""Run a command and kill its whole process tree.

Windows: a Job Object with kill-on-close (``taskkill /T`` as a second net). POSIX: a new session
and ``killpg``. Output goes to temporary files, not pipes, so a grandchild that inherited a pipe
can never block the parent. The prompt for a worker is handed over through a file used as stdin.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

IS_WINDOWS = sys.platform == "win32"
DEFAULT_MAX_OUTPUT = 4 * 1024 * 1024


@dataclass
class TreeResult:
    rc: int
    stdout: str
    stderr: str
    timed_out: bool
    pid: int
    seconds: float
    truncated: bool = False


class _WinJob:
    """Job Object that kills every process still in it when terminated or closed."""

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        self.k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k = self.k32
        k.CreateJobObjectW.restype = wintypes.HANDLE
        k.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
        k.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID,
                                              wintypes.DWORD]
        k.OpenProcess.restype = wintypes.HANDLE
        k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        k.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        k.CloseHandle.argtypes = [wintypes.HANDLE]

        class Basic(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64),
                        ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD),
                        ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t),
                        ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t),
                        ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class IoCounters(ctypes.Structure):
            _fields_ = [(n, ctypes.c_uint64) for n in ("ro", "wo", "oo", "rt", "wt", "ot")]

        class Extended(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", Basic), ("IoInfo", IoCounters),
                        ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        self.handle = k.CreateJobObjectW(None, None)
        if not self.handle:
            raise OSError("CreateJobObject failed")
        info = Extended()
        info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        ok = k.SetInformationJobObject(self.handle, 9, ctypes.byref(info), ctypes.sizeof(info))
        if not ok:
            raise OSError("SetInformationJobObject failed")

    def assign(self, pid: int) -> bool:
        proc = self.k32.OpenProcess(0x0001 | 0x0100, False, pid)  # TERMINATE | SET_QUOTA
        if not proc:
            return False
        try:
            return bool(self.k32.AssignProcessToJobObject(self.handle, proc))
        finally:
            self.k32.CloseHandle(proc)

    def terminate(self) -> None:
        if self.handle:
            self.k32.TerminateJobObject(self.handle, 1)

    def close(self) -> None:
        if self.handle:
            self.k32.CloseHandle(self.handle)
            self.handle = None


class TreeProcess:
    """A started process plus the means to kill everything it started."""

    def __init__(self, proc: subprocess.Popen, job: Optional[_WinJob]):
        self.proc = proc
        self.job = job

    @property
    def pid(self) -> int:
        return self.proc.pid

    def kill_tree(self) -> None:
        if IS_WINDOWS:
            if self.job is not None:
                self.job.terminate()
            # second net (only while the leader lives, so a recycled pid is never hit)
            if self.proc.poll() is None:
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(self.proc.pid)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        else:
            for sig in (signal.SIGTERM, signal.SIGKILL):
                try:
                    os.killpg(self.proc.pid, sig)
                except (ProcessLookupError, PermissionError):
                    break
                if sig == signal.SIGTERM:
                    time.sleep(0.2)
        try:
            self.proc.kill()
        except OSError:
            pass

    def close(self) -> None:
        if self.job is not None:
            self.job.close()


def start_tree(cmd: Sequence[str], *, cwd: Optional[Path] = None,
               env: Optional[Mapping[str, str]] = None, stdin: Any = None, stdout: Any = None,
               stderr: Any = None) -> TreeProcess:
    kwargs: dict = dict(cwd=str(cwd) if cwd else None, env=dict(env) if env is not None else None,
                        stdin=stdin, stdout=stdout, stderr=stderr)
    job: Optional[_WinJob] = None
    if IS_WINDOWS:
        kwargs["creationflags"] = (getattr(subprocess, "CREATE_NO_WINDOW", 0)
                                   | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        try:
            job = _WinJob()
        except OSError:
            job = None
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(list(cmd), **kwargs)
    if job is not None and not job.assign(proc.pid):
        job.close()
        job = None
    return TreeProcess(proc, job)


def _read_capped(path: Path, cap: int) -> tuple[str, bool]:
    size = path.stat().st_size
    with open(path, "rb") as fh:
        if size > cap:
            fh.seek(size - cap)
        data = fh.read()
    return data.decode("utf-8", errors="replace"), size > cap


def run_tree(cmd: Sequence[str], *, input_text: Optional[str] = None, timeout: float,
             cwd: Optional[Path] = None, env: Optional[Mapping[str, str]] = None,
             max_output: int = DEFAULT_MAX_OUTPUT) -> TreeResult:
    """Run ``cmd`` with a hard ``timeout`` (seconds); always kill every descendant afterwards."""
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="njli-run-", ignore_cleanup_errors=True) as tmp:
        tmpdir = Path(tmp)
        in_path, out_path, err_path = tmpdir / "in", tmpdir / "out", tmpdir / "err"
        in_path.write_bytes((input_text or "").encode("utf-8"))
        with open(in_path, "rb") as fin, open(out_path, "wb") as fout, open(err_path, "wb") as ferr:
            tp = start_tree(cmd, cwd=cwd, env=env, stdin=fin, stdout=fout, stderr=ferr)
            timed_out = False
            try:
                rc = tp.proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                tp.kill_tree()
                try:
                    rc = tp.proc.wait(timeout=10)
                except subprocess.TimeoutExpired:  # pragma: no cover - kill did not take
                    rc = -9
            finally:
                tp.kill_tree()  # descendants that outlived a clean exit
                tp.close()
        out, t1 = _read_capped(out_path, max_output)
        err, t2 = _read_capped(err_path, max_output)
    return TreeResult(rc=124 if timed_out else rc, stdout=out, stderr=err, timed_out=timed_out,
                      pid=tp.pid, seconds=time.monotonic() - started, truncated=t1 or t2)


def pid_alive(pid: int) -> bool:
    from njli.locks import pid_alive as _alive
    return _alive(pid)
