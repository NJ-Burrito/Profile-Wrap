from __future__ import annotations

import json
import multiprocessing
import os
import subprocess
import sys
import time

import pytest

from profile_wrap import locks


def test_acquire_release_and_reacquire(tmp_path):
    path = tmp_path / "a.lock"
    lock = locks.FileLock(path)
    with lock:
        assert path.exists() and lock.held
        info = json.loads(path.read_text(encoding="utf-8"))
        assert info["pid"] == os.getpid()
    assert not path.exists() and not lock.held
    with locks.FileLock(path):
        pass
    lock.release()  # releasing something not held is a no-op


def test_second_holder_is_refused(tmp_path):
    path = tmp_path / "a.lock"
    with locks.FileLock(path):
        with pytest.raises(locks.LockHeld) as excinfo:
            locks.FileLock(path).acquire()
        assert str(os.getpid()) in str(excinfo.value)
        assert excinfo.value.owner["pid"] == os.getpid()
    assert locks.FileLock(path).acquire().held


def test_wait_times_out_then_succeeds_after_release(tmp_path):
    import threading

    path = tmp_path / "w.lock"
    first = locks.FileLock(path).acquire()
    started = time.time()
    with pytest.raises(locks.LockHeld):
        locks.FileLock(path, wait=0.3, poll=0.05).acquire()
    assert time.time() - started >= 0.25
    threading.Timer(0.2, first.release).start()
    got = locks.FileLock(path, wait=3, poll=0.05).acquire()
    assert got.held
    got.release()


def _dead_pid() -> int:
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


def test_lock_of_a_dead_process_is_stale(tmp_path):
    import socket

    path = tmp_path / "dead.lock"
    path.write_text(json.dumps({"pid": _dead_pid(), "host": socket.gethostname(),
                                "token": "x", "created": time.time()}), encoding="utf-8")
    lock = locks.FileLock(path)
    assert lock.is_stale(lock.owner())
    assert lock.acquire().held
    assert json.loads(path.read_text(encoding="utf-8"))["pid"] == os.getpid()


def test_lock_from_another_host_is_trusted_until_old(tmp_path):
    path = tmp_path / "remote.lock"
    path.write_text(json.dumps({"pid": 999999, "host": "some-other-host", "token": "x",
                                "created": time.time()}), encoding="utf-8")
    with pytest.raises(locks.LockHeld):
        locks.FileLock(path).acquire()
    path.write_text(json.dumps({"pid": 999999, "host": "some-other-host", "token": "x",
                                "created": time.time() - 7200}), encoding="utf-8")
    assert locks.FileLock(path, stale_after=3600).acquire().held


def test_live_lock_older_than_timeout_is_broken(tmp_path):
    import socket

    path = tmp_path / "old.lock"
    path.write_text(json.dumps({"pid": os.getpid(), "host": socket.gethostname(), "token": "x",
                                "created": time.time() - 100}), encoding="utf-8")
    with pytest.raises(locks.LockHeld):
        locks.FileLock(path).acquire()            # no timeout: a live owner stays the owner
    assert locks.FileLock(path, stale_after=10).acquire().held


def test_unreadable_lock_is_stale_only_when_old(tmp_path):
    path = tmp_path / "junk.lock"
    path.write_text("not json", encoding="utf-8")
    lock = locks.FileLock(path)
    assert lock.owner() is None
    assert not lock.is_stale(None)
    old = time.time() - 60
    os.utime(path, (old, old))
    assert lock.is_stale(None)
    assert lock.acquire().held
    gone = locks.FileLock(tmp_path / "missing.lock")
    assert gone.is_stale(None)


def test_release_does_not_remove_someone_elses_lock(tmp_path):
    path = tmp_path / "steal.lock"
    mine = locks.FileLock(path).acquire()
    path.write_text(json.dumps({"pid": os.getpid(), "token": "someone-else", "host": "h",
                                "created": time.time()}), encoding="utf-8")
    mine.release()
    assert path.exists()


def test_pid_alive():
    assert locks.pid_alive(os.getpid())
    assert not locks.pid_alive(0)
    assert not locks.pid_alive(-5)
    assert not locks.pid_alive(_dead_pid())


def test_named_lock_sanitises_name(tmp_path):
    lock = locks.named_lock(tmp_path, "post due/../x", stale_after=5)
    assert lock.path.parent == tmp_path / "data" / "locks"
    assert "/" not in lock.path.name and "\\" not in lock.path.name
    with lock:
        assert lock.path.exists()


def _race(args):
    path, out_dir, idx = args
    from profile_wrap import locks as L

    try:
        with L.FileLock(path):
            (open(os.path.join(out_dir, f"won-{idx}"), "w")).close()
            time.sleep(0.4)
        return 1
    except L.LockHeld:
        return 0


def test_concurrent_processes_only_one_wins(tmp_path):
    path = str(tmp_path / "race.lock")
    out = tmp_path / "out"
    out.mkdir()
    ctx = multiprocessing.get_context("spawn")
    with ctx.Pool(4) as pool:
        results = pool.map(_race, [(path, str(out), i) for i in range(4)])
    assert sum(results) >= 1
    assert len(list(out.iterdir())) == sum(results)
    # at the moment of overlap only one process held the lock; none left it behind
    assert not os.path.exists(path)


def _gone(path, timeout=2.0):
    end = time.time() + timeout
    while time.time() < end:
        if not path.exists():
            return True
        time.sleep(0.01)
    return not path.exists()


def test_release_survives_concurrent_readers(tmp_path):
    """Windows refuses unlink while another thread reads the file; release must retry, not leak."""
    import threading

    path = tmp_path / "busy.lock"
    stop = threading.Event()

    def reader():
        while not stop.is_set():
            try:
                path.read_text(encoding="utf-8")
            except OSError:
                pass

    readers = [threading.Thread(target=reader) for _ in range(12)]
    for t in readers:
        t.start()
    try:
        for _ in range(40):
            lk = locks.FileLock(path)
            lk.acquire()
            lk.release()
            assert not lk.held
            # gone, or a tombstone that the next acquirer breaks at once
            assert _gone(path, 0.05) or locks.FileLock(path).is_stale(locks.FileLock(path).owner())
    finally:
        stop.set()
        for t in readers:
            t.join()
