"""A lock that is safe between threads of one process and between processes.

``njli.locks.FileLock`` is a cross-process ``O_EXCL`` lock; two threads of the same process that race on
it can break each other's lock file. Taking an in-process lock first removes that race for the
calendar and the workspace state file, which are the files several commands write.
"""
from __future__ import annotations

import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Iterator, Optional

from njli.locks import named_lock

_registry_guard = threading.Lock()
_thread_locks: Dict[str, threading.RLock] = {}


def _thread_lock(key: str) -> threading.RLock:
    with _registry_guard:
        return _thread_locks.setdefault(key, threading.RLock())


@contextmanager
def guarded(workspace: Path, name: str, *, stale_after: Optional[float] = None,
            wait: float = 0.0) -> Iterator[None]:
    """Hold the thread lock, then the file lock. Raises ``LockHeld`` when ``wait`` runs out."""
    key = f"{Path(workspace).resolve()}::{name}"
    tl = _thread_lock(key)
    if not tl.acquire(timeout=wait if wait > 0 else 0):
        from njli.locks import LockHeld
        raise LockHeld(Path(workspace) / "data" / "locks" / f"{name}.lock", {"pid": "this process"})
    try:
        with named_lock(workspace, name, stale_after=stale_after, wait=wait):
            yield
    finally:
        tl.release()
