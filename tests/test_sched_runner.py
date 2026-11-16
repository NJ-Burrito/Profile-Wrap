"""PW-R06 (runner part), PW-R07 (runner notices), PW-R05 (heartbeat record), PW-R01 (reminder flag)."""
from __future__ import annotations

import json
import sys

from profile_wrap.schedule import runner
from test_sched_common import cfg_of, isolate, mkws, toasts  # noqa: F401

PY = sys.executable
OK = [PY, "-c", "print('hello')"]
BAD = [PY, "-c", "import sys; sys.exit(3)"]


def go(ws, argv, name="token_check", **kw):
    kw.setdefault("sleep", lambda s: None)
    return runner.run_job(ws, cfg_of(ws), name, argv_override=argv, **kw)


def rows(ws):
    p = ws / "data" / "logs" / "runs.jsonl"
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


def test_a_log_that_cannot_be_written_never_stops_the_job(mkws, monkeypatch):
    ws = mkws()
    real_open = open

    def deny(path, *a, **k):
        if str(path).endswith("token_check.log"):
            raise PermissionError("locked by another program")
        return real_open(path, *a, **k)

    monkeypatch.setattr("builtins.open", deny)
    out = go(ws, BAD, notify_user=False)
    assert out.exit == 3 and out.status == "failed"
    assert rows(ws)[-1]["exit"] == 3, "the outcome row is still written"
    fallbacks = list((ws / "data" / "logs").glob("fallback-token_check-*.log"))
    assert len(fallbacks) == 1 and "exit=3" in fallbacks[0].read_text(encoding="utf-8")


def test_the_outcome_row_is_written_before_the_log(mkws, monkeypatch):
    ws = mkws()
    order = []
    monkeypatch.setattr(runner, "_record", lambda w, row: order.append("record"))
    monkeypatch.setattr(runner, "_append_log", lambda *a, **k: order.append("log"))
    go(ws, OK, notify_user=False)
    assert order == ["record", "log"]


def test_two_fallback_logs_never_share_a_name(mkws):
    ws = mkws()
    runner._fallback_log(ws, "j", "a")
    runner._fallback_log(ws, "j", "b")
    assert len(list((ws / "data" / "logs").glob("fallback-j-*.log"))) == 2


def test_a_crash_writes_crash_log_with_the_traceback_and_exits_one(mkws, monkeypatch, toasts):
    ws = mkws()

    def boom(*a, **k):
        raise RuntimeError("registry exploded")

    monkeypatch.setattr(runner, "run_job", boom)
    out = runner.safe_run(ws, cfg_of(ws), "build_week")
    assert out.exit == 1 and out.status == "crashed"
    text = (ws / "data" / "logs" / "crash.log").read_text(encoding="utf-8")
    assert "RuntimeError: registry exploded" in text and "Traceback" in text and "build_week" in text
    assert rows(ws)[-1]["status"] == "crashed"
    assert len(toasts) == 1 and "crashed" in toasts[0][0]


def test_cmd_run_returns_one_when_run_job_crashes(mkws, monkeypatch):
    import argparse

    from profile_wrap.schedule import cli_ext

    ws = mkws()

    def boom(*a, **k):
        raise ValueError("bad")

    monkeypatch.setattr(runner, "run_job", boom)
    args = argparse.Namespace(workspace=str(ws), profile=None, job="token_check", dry_run=False, force=False,
                              no_jitter=True, json=False)
    assert cli_ext.cmd_run(args) == 1
    assert "ValueError: bad" in (ws / "data" / "logs" / "crash.log").read_text(encoding="utf-8")


def test_repeated_failures_notify_once_then_success_resets(mkws, toasts):
    ws = mkws()
    go(ws, BAD)
    go(ws, BAD)
    assert len(toasts) == 1
    go(ws, OK)                      # success clears the job's notices
    go(ws, BAD)
    assert len(toasts) == 2


def test_a_different_status_notifies_again(mkws, toasts):
    ws = mkws()
    go(ws, BAD)
    go(ws, [PY, "-c", "import time; time.sleep(30)"], timeout_override=0.5)
    assert [t for t, _ in toasts] == ["profile-wrap: token_check failed", "profile-wrap: token_check timed out"]


def test_the_heartbeat_records_last_start_end_and_exit(mkws):
    ws = mkws()
    go(ws, BAD, notify_user=False)
    beat = runner.read_heartbeats(ws)["token_check"]
    assert beat["exit"] == 3 and beat["status"] == "failed" and beat["ok"] is False
    assert beat["last_start"] and beat["last_end"]
    go(ws, OK, notify_user=False)
    assert runner.read_heartbeats(ws)["token_check"]["ok"] is True


def test_a_dry_run_leaves_no_heartbeat(mkws):
    ws = mkws()
    runner.run_job(ws, cfg_of(ws), "token_check", dry_run=True)
    assert runner.read_heartbeats(ws) == {}


def test_a_corrupt_heartbeat_file_is_tolerated(mkws):
    ws = mkws()
    path = ws / runner.HEARTBEAT_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("[[[", encoding="utf-8")
    assert runner.read_heartbeats(ws) == {}
    runner.heartbeat(ws, "x", exit=0)
    assert runner.read_heartbeats(ws)["x"]["exit"] == 0


def test_the_reminder_only_flag_reaches_the_post_due_child(mkws):
    ws = mkws(schedule__jobs__post_due={"enabled": True, "every_min": 15})
    seen = {}

    class R:
        rc, stdout, stderr, timed_out = 0, "", "", False

    def fake_run(cmd, timeout, cwd, env):
        seen.update(env)
        return R()

    runner.run_job(ws, cfg_of(ws), "post_due", run=fake_run, notify_user=False)
    assert seen.get("PROFILE_WRAP_DUE_REMINDER_ONLY") == "1"
    seen.clear()
    runner.run_job(ws, cfg_of(ws), "token_check", run=fake_run, notify_user=False)
    assert "PROFILE_WRAP_DUE_REMINDER_ONLY" not in seen
