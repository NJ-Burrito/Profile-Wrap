"""``njli run <job>``: pause, locks, jitter, hard timeout with tree kill, logs, dry run, tool checks, daemon."""
from __future__ import annotations

import datetime as dt
import json
import os
import random
import subprocess
import sys
import time
from pathlib import Path

import pytest

from schedhelp import cfg_of
from njli import limits
from njli.plan.locking import guarded
from njli.schedule import proctree, runner
from njli.schedule.jobs import JOB_TABLE

PY = sys.executable


def rows(ws):
    p = ws / "data" / "logs" / "runs.jsonl"
    return [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


def go(ws, name="token_check", cfg=None, **kw):
    kw.setdefault("notify_user", False)
    kw.setdefault("sleep", lambda s: None)   # never really sleep through a jitter wait
    kw.setdefault("argv_override", [PY, "-c", "print('hello from the job')"])
    return runner.run_job(ws, cfg or cfg_of(ws), name, **kw)


def test_a_job_runs_logs_and_records_one_line(mkws):
    ws = mkws()
    out = go(ws)
    assert out.ok and out.status == "ok" and out.exit == 0
    log = (ws / "data" / "logs" / "token_check.log").read_text(encoding="utf-8")
    assert "hello from the job" in log and "exit=0" in log
    r = rows(ws)
    assert len(r) == 1 and r[0]["job"] == "token_check" and r[0]["ok"] is True and r[0]["exit"] == 0
    assert r[0]["seconds"] >= 0 and r[0]["dry_run"] is False


def test_a_failing_job_is_recorded_and_notified_without_a_traceback(mkws, monkeypatch):
    ws = mkws()
    sent = []
    monkeypatch.setattr(runner, "notify", lambda *a, **k: sent.append(a))
    out = runner.run_job(ws, cfg_of(ws), "token_check", argv_override=[PY, "-c", "import sys; sys.stderr.write('bad token'); sys.exit(3)"])
    assert out.exit == 3 and out.status == "failed" and "bad token" in out.message
    assert rows(ws)[0]["ok"] is False
    assert sent and "token_check" in sent[0][0] and "failed" in sent[0][0]


def test_paused_jobs_exit_4_before_doing_anything(mkws):
    ws = mkws()
    limits.pause(ws, None, "test")
    called = []
    out = go(ws, run=lambda *a, **k: called.append(1))
    assert out.exit == 4 and out.status == "paused" and called == []
    assert rows(ws)[0]["status"] == "paused"
    limits.resume(ws)
    assert go(ws).ok


def test_pause_kinds_apply_to_the_right_jobs(mkws):
    ws = mkws()
    limits.pause(ws, "comments", "t")
    assert go(ws, "token_check").ok, "a comments pause does not stop the token check"
    assert go(ws, "engage_prepare").exit == 4
    assert go(ws, "connect_weekly").exit == 4
    limits.resume(ws)
    limits.pause(ws, "posting", "t")
    assert go(ws, "post_due").exit == 4 and go(ws, "build_week", argv_override=[PY, "-c", "pass"]).ok


def test_a_job_that_is_still_running_is_not_started_twice(mkws):
    ws = mkws()
    with guarded(ws, "job-token_check", stale_after=600, wait=0):
        out = go(ws, run=lambda *a, **k: pytest.fail("started a second copy"))
    assert out.exit == 0 and out.status == "busy"
    assert go(ws).status == "ok", "the lock is released afterwards"


def test_jitter_is_bounded_logged_and_skippable(mkws):
    ws = mkws()
    cfg = cfg_of(ws)
    assert cfg["schedule"]["jobs"]["build_week"]["jitter_min"] == 20
    slept = []

    class Fixed(random.Random):
        def uniform(self, a, b):
            assert (a, b) == (0, 20 * 60)
            return 123.4

    out = go(ws, "build_week", sleep=slept.append, rng=Fixed())
    assert out.jitter_s == 123.4 and slept == [123.4]
    assert "jitter 123.4s of 20 min" in (ws / "data" / "logs" / "build_week.log").read_text(encoding="utf-8")
    assert rows(ws)[-1]["jitter_s"] == 123.4
    slept.clear()
    go(ws, "build_week", sleep=slept.append, no_jitter=True)
    assert slept == [], "--no-jitter (systemd does its own) sleeps nothing"
    for seed in range(50):  # the bound holds for any draw
        rng = random.Random(seed)
        v = rng.uniform(0, 20 * 60)
        assert 0 <= v <= 1200
    assert go(ws, "token_check", sleep=lambda s: pytest.fail("no jitter configured")).ok


def test_pause_during_the_jitter_wait_stops_the_run(mkws):
    ws = mkws()
    out = go(ws, "build_week", sleep=lambda s: limits.pause(ws, None, "during jitter"),
             rng=random.Random(1), run=lambda *a, **k: pytest.fail("ran after a pause"))
    assert out.exit == 4 and "jitter" in out.message


def test_the_hard_timeout_kills_the_whole_process_tree(mkws, tmp_path):
    ws = mkws()
    pidfile = tmp_path / "grandchild.pid"
    code = (
        "import subprocess, sys, time\n"
        "c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(300)'])\n"
        f"open({str(pidfile)!r}, 'w').write(str(c.pid))\n"
        "time.sleep(300)\n"
    )
    t0 = time.time()
    out = go(ws, argv_override=[PY, "-c", code], timeout_override=3)
    assert out.status == "timeout" and out.exit == 124 and time.time() - t0 < 60
    child = int(pidfile.read_text())
    end = time.time() + 15
    while time.time() < end and proctree.pid_alive(child):
        time.sleep(0.1)
    assert not proctree.pid_alive(child), "the grandchild survived the job's timeout"
    assert rows(ws)[-1]["timed_out"] is True


def test_the_child_gets_a_scrubbed_environment(mkws, monkeypatch):
    ws = mkws()
    for name in ("LINKEDIN_CLIENT_SECRET", "GITHUB_TOKEN", "AWS_SECRET_ACCESS_KEY", "SOME_SHELL_TOKEN"):
        monkeypatch.setenv(name, "must-not-leak")
    monkeypatch.setenv("NJLI_TEST", "1")
    marker = ws / "work" / "env.json"
    out = go(ws, argv_override=[PY, "-c", f"import os, json; open({str(marker)!r}, 'w').write(json.dumps(sorted(os.environ)))"])
    assert out.ok
    env = {k.upper() for k in json.loads(marker.read_text(encoding="utf-8"))}
    assert not env & {"LINKEDIN_CLIENT_SECRET", "GITHUB_TOKEN", "AWS_SECRET_ACCESS_KEY", "SOME_SHELL_TOKEN"}
    assert "PYTHONUTF8" in env and "NJLI_TEST" in env and "PATH" in env


def test_a_missing_tool_is_a_message_not_a_traceback(mkws, monkeypatch, tmp_path):
    ws = mkws()
    sent = []
    monkeypatch.setattr(runner, "notify", lambda *a, **k: sent.append(a))
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.delenv("NJLI_CLAUDE_BIN", raising=False)
    monkeypatch.setattr(runner.claude_runner.paths, "home", lambda: tmp_path / "nohome")
    out = runner.run_job(ws, cfg_of(ws), "build_week", run=lambda *a, **k: pytest.fail("ran without claude"))
    assert out.exit == 1 and out.status == "tool_missing" and "tool missing: claude" in out.message
    assert "Traceback" not in (ws / "data" / "logs" / "build_week.log").read_text(encoding="utf-8")
    assert sent and "cannot run" in sent[0][0]


def test_dry_run_makes_no_call_for_jobs_that_do_not_run_themselves(mkws):
    ws = mkws()
    for name in sorted(JOB_TABLE):
        if name == "build_week":
            continue
        out = runner.run_job(ws, cfg_of(ws), name, dry_run=True, notify_user=False,
                             run=lambda *a, **k: pytest.fail(f"{name} started a process in a dry run"))
        assert out.exit == 0 and out.status == "dry_run" and "would run" in out.message, name
    assert not (ws / "data" / "logs" / "token_check.log").exists()


def test_build_week_dry_run_passes_dry_run_down_and_spends_no_tokens(mkws):
    ws = mkws()
    seen = []

    def fake_run(cmd, **kw):
        seen.append(list(cmd))
        return proctree.TreeResult(rc=0, stdout="dry run: 0 entries", stderr="", timed_out=False, pid=0, seconds=0.0)

    out = runner.run_job(ws, cfg_of(ws), "build_week", dry_run=True, run=fake_run, notify_user=False)
    assert out.ok and seen and seen[0][-1] == "--dry-run" and "build-week" in seen[0]


def test_dry_run_of_the_real_build_week_command_end_to_end(mkws, tmp_path, monkeypatch):
    """A real child process: `njli run build_week --dry-run` -> `njli build-week --dry-run`; no worker, no model."""
    ws = mkws()
    spy = tmp_path / "claude-spy.txt"
    shim = tmp_path / "claude_shim.py"
    shim.write_text(f"open({str(spy)!r}, 'a').write('called')\n", encoding="utf-8")
    monkeypatch.setenv("NJLI_CLAUDE_BIN", str(shim))
    out = runner.run_job(ws, cfg_of(ws), "build_week", dry_run=True, notify_user=False,
                         run=lambda cmd, **kw: proctree.run_tree(cmd, timeout=120, cwd=kw.get("cwd"),
                                                                 env={**runner.child_env(cfg_of(ws)), "NJLI_CONFIG_DIR": os.environ["NJLI_CONFIG_DIR"]}))
    assert out.ok, out.message
    assert not spy.exists(), "no claude process was started"


def test_a_job_that_ran_recently_is_skipped_unless_forced(mkws):
    ws = mkws()
    now = dt.datetime(2026, 11, 2, 9, 0, tzinfo=dt.timezone.utc)
    (ws / "data" / "logs" / "runs.jsonl").write_text(json.dumps(
        {"at": (now - dt.timedelta(days=30)).isoformat(), "job": "profile_review", "ok": True, "exit": 0}) + "\n", encoding="utf-8")
    def clock():
        return now

    out = go(ws, "profile_review", now=clock, run=lambda *a, **k: pytest.fail("ran too soon"))
    assert out.status == "not_due" and out.exit == 0
    assert go(ws, "profile_review", now=clock, force=True).status == "ok"
    (ws / "data" / "logs" / "runs.jsonl").write_text(json.dumps(
        {"at": (now - dt.timedelta(days=91)).isoformat(), "job": "profile_review", "ok": True, "exit": 0}) + "\n", encoding="utf-8")
    assert go(ws, "profile_review", now=clock).status == "ok", "90 days have passed"


def test_unknown_job_is_a_usage_error(mkws):
    ws = mkws()
    out = runner.run_job(ws, cfg_of(ws), "nope")
    assert out.exit == 2 and out.status == "unknown_job" and "known:" in out.message


def test_logs_rotate_by_size(mkws):
    ws = mkws()
    log = ws / "data" / "logs" / "token_check.log"
    log.write_bytes(b"x" * (2 * 1024 * 1024))
    cfg = cfg_of(ws)
    cfg["schedule"]["log_rotate_mb"] = 1
    go(ws, cfg=cfg)
    assert (ws / "data" / "logs" / "token_check.log.1").stat().st_size >= 2 * 1024 * 1024
    assert log.stat().st_size < 1024
    for _ in range(5):
        log.write_bytes(b"y" * (2 * 1024 * 1024))
        go(ws, cfg=cfg)
    assert not (ws / "data" / "logs" / "token_check.log.4").exists(), "at most three old logs are kept"


def test_a_prompt_less_cli_entry_smoke_of_the_real_command(mkws, tmp_path):
    """ENTRY_SMOKE: the real `python -m njli run ...` path, as the scheduler calls it."""
    ws = mkws()
    env = {**os.environ, "PYTHONUTF8": "1"}
    root = str(Path(__file__).resolve().parents[3])
    env["PYTHONPATH"] = root
    r = subprocess.run([PY, "-m", "njli", "run", "doctor_weekly", "--dry-run", "--workspace", str(ws)],
                       capture_output=True, text=True, env=env, timeout=120, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    assert "dry_run" in r.stdout
    r = subprocess.run([PY, "-m", "njli", "run", "nope", "--workspace", str(ws)], capture_output=True, text=True,
                       env=env, timeout=120, encoding="utf-8")
    assert r.returncode == 2


def test_the_daemon_fires_jobs_by_the_same_rules(mkws):
    ws = mkws()
    cfg = cfg_of(ws)
    cfg["schedule"]["jobs"] = {"token_check": {"enabled": True, "when": "DAILY 09:30"},
                               "board": {"enabled": True, "at_login": True},
                               "post_due": {"enabled": False, "every_min": 15}}
    state = {"t": dt.datetime(2026, 11, 2, 9, 0, tzinfo=dt.timezone.utc)}
    ran = []
    out = []

    def sleep(_s):
        state["t"] += dt.timedelta(minutes=10)

    def fake(w, c, name, **kw):
        ran.append((name, state["t"].strftime("%H:%M")))
        return runner.Outcome(name, 0, "ok")

    fired = runner.daemon(ws, cfg, tick_s=600, now=lambda: state["t"], sleep=sleep, run=fake, max_ticks=8, out=out.append)
    assert fired == ["board", "token_check"]
    assert dict(ran)["board"] == "09:00" and dict(ran)["token_check"] in ("09:30", "09:40")
    assert any("njli daemon" in ln for ln in out)


def test_the_daemon_runs_interval_jobs_repeatedly(mkws):
    ws = mkws()
    cfg = cfg_of(ws)
    cfg["schedule"]["jobs"] = {"token_check": {"enabled": True, "every_min": 20}}
    state = {"t": dt.datetime(2026, 11, 2, 9, 0, tzinfo=dt.timezone.utc)}
    ran = []

    def sleep(_s):
        state["t"] += dt.timedelta(minutes=10)

    runner.daemon(ws, cfg, tick_s=600, now=lambda: state["t"], sleep=sleep,
                  run=lambda w, c, n, **k: ran.append(n) or runner.Outcome(n, 0, "ok"), max_ticks=10, out=lambda s: None)
    assert len(ran) >= 3


def test_run_tree_is_what_the_runner_uses_so_a_clean_exit_with_children_is_also_cleaned(mkws, tmp_path):
    ws = mkws()
    pidfile = tmp_path / "orphan.pid"
    code = ("import subprocess, sys\n"
            "c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(300)'])\n"
            f"open({str(pidfile)!r}, 'w').write(str(c.pid))\n")
    assert go(ws, argv_override=[PY, "-c", code]).ok
    orphan = int(pidfile.read_text())
    end = time.time() + 15
    while time.time() < end and proctree.pid_alive(orphan):
        time.sleep(0.1)
    assert not proctree.pid_alive(orphan)
