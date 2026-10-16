"""Cross-process locks: ``O_EXCL`` lock files with PID liveness and a stale timeout.

A lock file holds JSON: pid, host, token, created (epoch seconds). A lock is
stale when its owner process is gone, or when it is older than ``stale_after``
seconds. Stale locks are broken by an atomic rename so two breakers cannot both
win.
"""
from __future__ import annotations

import json
import os
import socket
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional


class LockHeld(Exception):
    """The lock is held by a live process."""

    def __init__(self, path: Path, owner: Optional[Dict[str, Any]] = None):
        self.path = Path(path)
        self.owner = owner or {}
        pid = self.owner.get("pid", "unknown")
        super().__init__(f"lock {self.path.name} is held by pid {pid}")


def pid_alive(pid: int) -> bool:
    """Best-effort liveness check that works on Windows, macOS and Linux."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        process_query_limited = 0x1000
        handle = kernel32.OpenProcess(process_query_limited, False, int(pid))
        if not handle:
            # 5 = access denied: the process exists but belongs to someone else.
            return ctypes.GetLastError() == 5  # type: ignore[attr-defined]
        try:
            code = ctypes.c_ulong()
            if kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return code.value == 259  # STILL_ACTIVE
            return True
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


class FileLock:
    """``with FileLock(path, stale_after=3600): ...``"""

    def __init__(self, path: Any, stale_after: Optional[float] = None, wait: float = 0.0,
                 poll: float = 0.1):
        self.path = Path(path)
        self.stale_after = stale_after
        self.wait = wait
        self.poll = poll
        self.token = uuid.uuid4().hex
        self._held = False

    # -- inspection -------------------------------------------------------
    def owner(self) -> Optional[Dict[str, Any]]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def is_stale(self, info: Optional[Dict[str, Any]]) -> bool:
        if info is None:
            # Unreadable or half-written: stale only once it is old enough to be sure.
            try:
                age = time.time() - self.path.stat().st_mtime
            except OSError:
                return True
            return age > 5
        if info.get("released"):
            return True
        pid = info.get("pid")
        same_host = info.get("host") == socket.gethostname()
        if same_host and isinstance(pid, int) and not pid_alive(pid):
            return True
        created = info.get("created")
        if self.stale_after is not None and isinstance(created, (int, float)):
            return time.time() - created > self.stale_after
        return False

    # -- acquire / release ------------------------------------------------
    def _try_create(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            return False
        payload = {"pid": os.getpid(), "host": socket.gethostname(), "token": self.token,
                   "created": time.time()}
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload))
        return True

    def _break_stale(self) -> None:
        grave = self.path.with_name(f"{self.path.name}.stale.{uuid.uuid4().hex[:8]}")
        try:
            os.replace(str(self.path), str(grave))
        except OSError:
            return
        try:
            grave.unlink()
        except OSError:
            pass

    def _take_over(self, seen: Dict[str, Any]) -> bool:
        payload = {"pid": os.getpid(), "host": socket.gethostname(), "token": self.token,
                   "created": time.time()}
        try:
            with open(self.path, "r+", encoding="utf-8") as handle:
                now = json.loads(handle.read() or "{}")
                if not now.get("released") or now.get("token") != seen.get("token"):
                    return False
                handle.seek(0)
                handle.truncate()
                handle.write(json.dumps(payload))
        except (OSError, ValueError):
            return False
        time.sleep(0.002)
        mine = self.owner()
        return bool(mine) and mine.get("token") == self.token

    def acquire(self) -> "FileLock":
        deadline = time.time() + self.wait
        while True:
            if self._try_create():
                self._held = True
                return self
            info = self.owner()
            if self.is_stale(info):
                self._break_stale()
                if self.path.exists():
                    # Windows will not rename a file other threads hold open. A tombstone is ours to
                    # overwrite in place; for any other stale lock wait a moment and try again.
                    if info and info.get("released") and self._take_over(info):
                        self._held = True
                        return self
                    time.sleep(0.005)
                continue
            if time.time() >= deadline:
                raise LockHeld(self.path, info)
            time.sleep(self.poll)

    def release(self) -> None:
        if not self._held:
            return
        # Windows refuses to unlink a file another thread has open at that instant, so retry with a
        # short backoff. If readers keep it open the whole time, overwrite it with a tombstone
        # (``released``): every acquirer treats that as stale, so the lock is never leaked.
        delay = 0.001
        deadline = time.monotonic() + 0.5
        while time.monotonic() < deadline:
            info = self.owner()
            if info is None and not self.path.exists():
                break  # already gone
            if info is not None and info.get("token") != self.token:
                break  # someone else's lock now: not ours to remove
            if info is not None:
                try:
                    self.path.unlink()
                    break
                except FileNotFoundError:
                    break
                except OSError:
                    pass
            time.sleep(delay)
            delay = min(delay * 2, 0.05)
        else:
            self._tombstone()
        self._held = False

    def _tombstone(self) -> None:
        for _ in range(200):
            try:
                with open(self.path, "r+", encoding="utf-8") as handle:
                    info = json.loads(handle.read() or "{}")
                    if info.get("token") not in (None, self.token):
                        return
                    handle.seek(0)
                    handle.truncate()
                    handle.write(json.dumps({"released": True, "token": self.token, "pid": 0,
                                             "host": socket.gethostname(), "created": 0}))
                return
            except FileNotFoundError:
                return
            except (OSError, ValueError):
                time.sleep(0.005)

    @property
    def held(self) -> bool:
        return self._held

    def __enter__(self) -> "FileLock":
        return self.acquire()

    def __exit__(self, *exc: Any) -> None:
        self.release()


def lock_dir(workspace: Any) -> Path:
    return Path(workspace) / "data" / "locks"


def named_lock(workspace: Any, name: str, stale_after: Optional[float] = None,
               wait: float = 0.0) -> FileLock:
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in name)
    return FileLock(lock_dir(workspace) / f"{safe}.lock", stale_after=stale_after, wait=wait)
