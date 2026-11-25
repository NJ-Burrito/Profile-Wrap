"""PW-R07: one shared ``notify_once`` with a time to live."""
from __future__ import annotations

from profile_wrap import notify as nm
from test_sched_common import isolate, mkws, toasts  # noqa: F401


def test_two_calls_with_one_key_notify_once(mkws, toasts):
    ws = mkws()
    assert nm.notify_once("job:x:failed", "t", "m", ws, now=1000.0) is True
    assert nm.notify_once("job:x:failed", "t", "m", ws, now=1001.0) is False
    assert len(toasts) == 1


def test_a_different_key_notifies_at_once(mkws, toasts):
    ws = mkws()
    nm.notify_once("job:x:failed", "t", "m", ws, now=1.0)
    assert nm.notify_once("job:x:timeout", "t", "m", ws, now=2.0) is True
    assert len(toasts) == 2


def test_ttl_expiry_notifies_again(mkws, toasts):
    ws = mkws()
    nm.notify_once("k", "t", "m", ws, ttl_hours=1, now=0.0)
    assert nm.notify_once("k", "t", "m", ws, ttl_hours=1, now=3599.0) is False
    assert nm.notify_once("k", "t", "m", ws, ttl_hours=1, now=3601.0) is True


def test_clear_notice_lets_the_next_failure_notify_at_once(mkws, toasts):
    ws = mkws()
    nm.notify_once("job:x:failed", "t", "m", ws, now=1.0)
    assert nm.clear_notice(ws, "job:x:", prefix=True) == 1
    assert nm.notify_once("job:x:failed", "t", "m", ws, now=2.0) is True


def test_a_corrupt_state_file_is_tolerated(mkws, toasts):
    ws = mkws()
    path = ws / nm.SEEN_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    assert nm.notify_once("k", "t", "m", ws, now=1.0) is True
    assert nm.notify_once("k", "t", "m", ws, now=2.0) is False


def test_notify_once_never_raises_when_the_channel_does(mkws, monkeypatch):
    ws = mkws()

    def boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(nm, "notify", boom)
    assert nm.notify_once("k", "t", "m", ws) is False
