"""PW-R05: heartbeat ("a job should have run and did not") and live registration per operating system."""
from __future__ import annotations

import datetime as dt
import json

import pytest

from profile_wrap.schedule import health as hl
from profile_wrap.schedule import runner
from profile_wrap.schedule.jobs import jobs_from_config
from test_sched_common import cfg_of, isolate, mkws, toasts  # noqa: F401

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 11, 18, 12, 0, tzinfo=UTC)      # a Wednesday


def ids(findings, status=None):
    return {f.id for f in findings if status is None or f.status == status}


def add_runs(ws, *rows):
    p = ws / "data" / "logs" / "runs.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def install_mark(ws, job, when, backend="cron"):
    state = ws / ".njl" / "workspace.json"
    data = json.loads(state.read_text(encoding="utf-8"))
    data["created_schedule"].append({"backend": backend, "job": job, "kind": "x", "name": f"profile-wrap-demo-{job}",
                                     "path": "", "installed_at": when.isoformat()})
    state.write_text(json.dumps(data), encoding="utf-8")


def only_jobs(ws, **specs):
    """A workspace config where only the named jobs are enabled."""
    cfg = cfg_of(ws)
    for name in cfg["schedule"]["jobs"]:
        cfg["schedule"]["jobs"][name]["enabled"] = False
    for name, spec in specs.items():
        cfg["schedule"]["jobs"][name].update({"enabled": True, **spec})
    return cfg


def test_prev_fire_for_each_rule_kind(mkws):
    cfg = only_jobs(mkws(), token_check={"when": "DAILY 09:30"}, build_week={"when": "THU 10:00"})
    jobs = {j.name: j for j in jobs_from_config(cfg)}
    assert hl.prev_fire(jobs["token_check"], NOW, "UTC") == dt.datetime(2026, 11, 18, 9, 30, tzinfo=UTC)
    assert hl.prev_fire(jobs["token_check"], NOW.replace(hour=9, minute=0), "UTC") == \
        dt.datetime(2026, 11, 17, 9, 30, tzinfo=UTC)
    assert hl.prev_fire(jobs["build_week"], NOW, "UTC") == dt.datetime(2026, 11, 12, 10, 0, tzinfo=UTC)


def test_a_daily_job_that_did_not_run_is_flagged(mkws):
    ws = mkws()
    cfg = only_jobs(ws, token_check={"when": "DAILY 09:30"})
    install_mark(ws, "token_check", NOW - dt.timedelta(days=5))
    add_runs(ws, {"at": "2026-11-16T09:30:02+00:00", "job": "token_check", "exit": 0, "ok": True, "status": "ok"})
    found = hl.heartbeat_findings(ws, cfg, dt.datetime(2026, 11, 18, 16, 0, tzinfo=UTC))   # slot + 6.5 h
    assert "job_ran:token_check" in ids(found, "warn")


def test_a_job_within_its_grace_window_is_not_flagged(mkws):
    ws = mkws()
    cfg = only_jobs(ws, token_check={"when": "DAILY 09:30"})
    install_mark(ws, "token_check", NOW - dt.timedelta(days=5))
    add_runs(ws, {"at": "2026-11-17T09:30:02+00:00", "job": "token_check", "exit": 0, "ok": True, "status": "ok"})
    soon = dt.datetime(2026, 11, 18, 10, 30, tzinfo=UTC)       # slot 09:30 + 1 h, inside the catch-up window
    assert "job_ran:token_check" in ids(hl.heartbeat_findings(ws, cfg, soon), "pass")


def test_a_job_that_ran_after_its_slot_passes(mkws):
    ws = mkws()
    cfg = only_jobs(ws, token_check={"when": "DAILY 09:30"})
    install_mark(ws, "token_check", NOW - dt.timedelta(days=5))
    add_runs(ws, {"at": "2026-11-18T09:30:01+00:00", "job": "token_check", "exit": 0, "ok": True, "status": "ok"})
    assert "job_ran:token_check" in ids(hl.heartbeat_findings(ws, cfg, NOW), "pass")


def test_paused_and_not_due_rows_count_as_having_run(mkws):
    ws = mkws()
    cfg = only_jobs(ws, token_check={"when": "DAILY 09:30"})
    install_mark(ws, "token_check", NOW - dt.timedelta(days=5))
    add_runs(ws, {"at": "2026-11-18T09:30:01+00:00", "job": "token_check", "exit": 4, "ok": False, "status": "paused"})
    found = hl.heartbeat_findings(ws, cfg, NOW)
    assert "job_ran:token_check" in ids(found, "pass") and "job_exit:token_check" not in ids(found)


def test_a_brand_new_install_does_not_alarm(mkws):
    ws = mkws()
    cfg = only_jobs(ws, token_check={"when": "DAILY 09:30"}, post_due={"every_min": 15})
    install_mark(ws, "token_check", NOW - dt.timedelta(hours=1))      # installed after today's slot
    install_mark(ws, "post_due", NOW - dt.timedelta(minutes=10))
    assert not ids(hl.heartbeat_findings(ws, cfg, NOW), "warn")


def test_an_interval_job_is_overdue_after_two_intervals(mkws):
    ws = mkws()
    cfg = only_jobs(ws, post_due={"every_min": 15})
    install_mark(ws, "post_due", NOW - dt.timedelta(days=1))
    add_runs(ws, {"at": (NOW - dt.timedelta(minutes=29)).isoformat(), "job": "post_due", "exit": 0, "ok": True,
                  "status": "ok"})
    assert "job_ran:post_due" in ids(hl.heartbeat_findings(ws, cfg, NOW), "pass")
    # 31 minutes since the last run: more than two 15-minute intervals
    (ws / "data" / "logs" / "runs.jsonl").write_text(json.dumps(
        {"at": (NOW - dt.timedelta(minutes=31)).isoformat(), "job": "post_due", "exit": 0, "ok": True,
         "status": "ok"}) + "\n", encoding="utf-8")
    assert "job_ran:post_due" in ids(hl.heartbeat_findings(ws, cfg, NOW), "warn")


def test_a_failed_last_run_is_reported_with_its_exit(mkws):
    ws = mkws()
    cfg = only_jobs(ws, token_check={"when": "DAILY 09:30"})
    install_mark(ws, "token_check", NOW - dt.timedelta(days=5))
    add_runs(ws, {"at": "2026-11-18T09:30:01+00:00", "job": "token_check", "exit": 1, "ok": False, "status": "failed"})
    bad = [f for f in hl.heartbeat_findings(ws, cfg, NOW) if f.id == "job_exit:token_check"]
    assert bad and bad[0].status == "warn" and "exit 1" in bad[0].detail


def test_a_started_job_that_never_ended_is_flagged(mkws):
    ws = mkws()
    cfg = only_jobs(ws, token_check={"when": "DAILY 09:30"})
    install_mark(ws, "token_check", NOW - dt.timedelta(days=5))
    add_runs(ws, {"at": "2026-11-18T09:30:01+00:00", "job": "token_check", "exit": 0, "ok": True, "status": "ok"})
    runner.heartbeat(ws, "token_check", last_start="2026-11-18T09:30:00+00:00", last_end="2026-11-17T09:30:09+00:00")
    assert "job_finished:token_check" in ids(hl.heartbeat_findings(ws, cfg, NOW), "warn")


# ------------------------------------------------------------------ live registration (fake `run`)

class FakeOS:
    def __init__(self, answers=None):
        self.answers, self.calls = answers or {}, []

    def __call__(self, cmd, stdin=None):
        self.calls.append(list(cmd))
        for prefix, result in self.answers.items():
            if " ".join(cmd).startswith(prefix):
                return result
        return 0, ""


def mark_backend(ws, backend, jobs, kind="unit-timer", name_fmt="profile-wrap-demo-{job}"):
    state = ws / ".njl" / "workspace.json"
    data = json.loads(state.read_text(encoding="utf-8"))
    for j in jobs:
        data["created_schedule"].append({"backend": backend, "job": j, "kind": kind, "name": name_fmt.format(job=j),
                                         "path": "", "installed_at": "2026-11-01T00:00:00+00:00"})
    state.write_text(json.dumps(data), encoding="utf-8")


WIN_OK = "TaskName: x\nStatus: Ready\nLast Result: 0\n"


def test_windows_a_missing_task_is_a_warning(mkws):
    ws = mkws()
    cfg = only_jobs(ws, token_check={"when": "DAILY 09:30"})
    mark_backend(ws, "windows", ["token_check"], kind="task-xml")
    found = hl.registration_findings(ws, cfg, run=FakeOS({"schtasks": (1, "ERROR: cannot find")}))
    assert "sched_registered:token_check" in ids(found, "warn")


def test_windows_a_non_zero_last_result_is_a_warning_and_zero_passes(mkws):
    ws = mkws()
    cfg = only_jobs(ws, token_check={"when": "DAILY 09:30"})
    mark_backend(ws, "windows", ["token_check"], kind="task-xml")
    bad = hl.registration_findings(ws, cfg, run=FakeOS({"schtasks": (0, "Status: Ready\nLast Result: 2147942402\n")}))
    assert "sched_last_result:token_check" in ids(bad, "warn")
    good = hl.registration_findings(ws, cfg, run=FakeOS({"schtasks": (0, WIN_OK)}))
    assert "sched_registered:token_check" in ids(good, "pass")
    never = hl.registration_findings(ws, cfg, run=FakeOS({"schtasks": (0, "Status: Ready\nLast Result: 267011\n")}))
    assert not ids(never, "warn")


def test_systemd_inactive_timer_and_missing_linger_are_warnings(mkws, monkeypatch):
    ws = mkws()
    monkeypatch.setenv("USER", "demo")
    cfg = only_jobs(ws, token_check={"when": "DAILY 09:30"})
    mark_backend(ws, "systemd", ["token_check"], name_fmt="profile-wrap-demo-{job}.timer")
    found = hl.registration_findings(ws, cfg, run=FakeOS({
        "systemctl --user is-active": (3, "inactive"), "loginctl show-user": (0, "Linger=no")}))
    assert {"sched_registered:token_check", "sched_linger"} <= ids(found, "warn")


def test_systemd_healthy_timer_passes(mkws, monkeypatch):
    ws = mkws()
    monkeypatch.setenv("USER", "demo")
    cfg = only_jobs(ws, token_check={"when": "DAILY 09:30"})
    mark_backend(ws, "systemd", ["token_check"], name_fmt="profile-wrap-demo-{job}.timer")
    found = hl.registration_findings(ws, cfg, run=FakeOS({"loginctl show-user": (0, "Linger=yes")}))
    assert not ids(found, "warn") and "sched_linger" in ids(found, "pass")


def test_cron_block_missing_and_cron_daemon_down(mkws):
    ws = mkws()
    cfg = only_jobs(ws, token_check={"when": "DAILY 09:30"})
    mark_backend(ws, "cron", ["*"], kind="cron-block", name_fmt="profile-wrap:demo")
    found = hl.registration_findings(ws, cfg, run=FakeOS({"crontab -l": (0, "0 * * * * other"), "pidof": (1, "")}))
    assert {"sched_registered:cron", "sched_cron_daemon"} <= ids(found, "warn")


def test_cron_block_present_passes(mkws):
    ws = mkws()
    cfg = only_jobs(ws, token_check={"when": "DAILY 09:30"})
    mark_backend(ws, "cron", ["*"], kind="cron-block", name_fmt="profile-wrap:demo")
    found = hl.registration_findings(ws, cfg, run=FakeOS({"crontab -l": (0, "# BEGIN profile-wrap:demo\nx\n")}))
    assert "sched_registered:cron" in ids(found, "pass") and "sched_cron_daemon" in ids(found, "pass")


def test_cron_without_pidof_says_nothing_about_the_daemon(mkws):
    ws = mkws()
    cfg = only_jobs(ws, token_check={"when": "DAILY 09:30"})
    mark_backend(ws, "cron", ["*"], kind="cron-block", name_fmt="profile-wrap:demo")
    found = hl.registration_findings(ws, cfg, run=FakeOS({"crontab -l": (0, "# BEGIN profile-wrap:demo\n"),
                                                          "pidof": (127, "not found")}))
    assert "sched_cron_daemon" not in ids(found)


def test_launchd_not_loaded_and_bad_exit_code(mkws):
    ws = mkws()
    cfg = only_jobs(ws, token_check={"when": "DAILY 09:30"})
    mark_backend(ws, "launchd", ["token_check"], kind="plist", name_fmt="io.profile_wrap.demo.{job}")
    gone = hl.registration_findings(ws, cfg, run=FakeOS({"launchctl print": (113, "Could not find service")}))
    assert "sched_registered:token_check" in ids(gone, "warn")
    bad = hl.registration_findings(ws, cfg, run=FakeOS({"launchctl print": (0, "state = waiting\n\tlast exit code = 78\n")}))
    assert "sched_last_result:token_check" in ids(bad, "warn")
    ok = hl.registration_findings(ws, cfg, run=FakeOS({"launchctl print": (0, "\tlast exit code = 0\n")}))
    assert "sched_registered:token_check" in ids(ok, "pass")


def test_nothing_recorded_but_jobs_enabled_is_a_warning(mkws):
    ws = mkws()
    cfg = only_jobs(ws, token_check={"when": "DAILY 09:30"})
    assert "sched_installed" in ids(hl.registration_findings(ws, cfg, run=FakeOS()), "warn")


def test_an_enabled_job_with_no_entry_is_a_warning(mkws):
    ws = mkws()
    cfg = only_jobs(ws, token_check={"when": "DAILY 09:30"}, board={"at_login": True})
    mark_backend(ws, "windows", ["token_check"], kind="task-xml")
    found = hl.registration_findings(ws, cfg, run=FakeOS({"schtasks": (0, WIN_OK)}))
    assert "sched_registered:board" in ids(found, "warn")


def test_schedule_health_returns_structured_findings_and_never_raises(mkws):
    ws = mkws()
    cfg = only_jobs(ws, token_check={"when": "DAILY 09:30"})

    def boom(cmd, stdin=None):
        raise RuntimeError("scheduler exploded")

    found = hl.schedule_health(ws, cfg, now=NOW, run=boom)
    assert found and all(isinstance(f, hl.Finding) for f in found)
    assert all(set(f.as_dict()) == {"id", "label", "status", "detail", "hint", "job"} for f in found)
    assert "sched_health_error" in ids(found, "warn") or "sched_installed" in ids(found)
    assert hl.schedule_health(ws, cfg, now=NOW, live=False) is not None
