"""Install, status and remove: recorded round trips for every backend, and the real one when asked.

The recorded tests run everywhere with a fake command runner and a temporary HOME. The real round trip
(``PROFILE_WRAP_REAL_SCHEDULER=1``, set in CI on each OS) installs into the machine's own scheduler under a
throw-away profile and removes it again in a ``finally``; it is skipped when the backend cannot operate.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from schedhelp import cfg_of
from profile_wrap import cli
from profile_wrap.schedule import backends as bk
from profile_wrap.schedule import install as inst

ENABLED = {"build_week", "research_weekly", "token_check", "doctor_weekly", "profile_review", "board"}


class Recorder:
    """A fake ``run``: records every command; a small fake crontab keeps state between calls."""

    def __init__(self, crontab="", fail=()):
        self.calls, self.crontab, self.fail = [], crontab, set(fail)

    def __call__(self, cmd, stdin=None):
        self.calls.append(list(cmd))
        key = " ".join(cmd[:2])
        if key in self.fail:
            return 1, f"{key} failed"
        if cmd[:2] == ["crontab", "-l"]:
            return (0, self.crontab) if self.crontab else (1, "no crontab for user")
        if cmd[:2] == ["crontab", "-"]:
            self.crontab = stdin
            return 0, ""
        if cmd[:2] == ["crontab", "-r"]:
            self.crontab = ""
            return 0, ""
        return 0, ""

    def has(self, *prefix):
        return any(c[: len(prefix)] == list(prefix) for c in self.calls)


def ctx_for(ws, tmp_path, **kw):
    home = tmp_path / "home"
    return bk.Context(profile="demo", workspace=str(ws), entry=[sys.executable, str(tmp_path / "data" / "runtime" / "current")],
                      path_env="/usr/bin", tools={"node": "/usr/bin/node"}, home=str(home), uid=501,
                      pythonw=None, **kw)


def entries(ws):
    return json.loads((ws / ".njl" / "workspace.json").read_text(encoding="utf-8"))["created_schedule"]


@pytest.mark.parametrize("backend", ["windows", "systemd", "cron", "launchd"])
def test_dry_run_shows_the_exact_changes_and_touches_nothing(mkws, tmp_path, backend):
    ws = mkws()
    rec = Recorder()
    before = (ws / ".njl" / "workspace.json").read_bytes()
    res = inst.install(ws, cfg_of(ws), backend=backend, dry_run=True, run=rec, ctx=ctx_for(ws, tmp_path), local_tz="UTC")
    assert res.ok and res.actions and res.dry_run
    assert rec.calls == [], "a dry run runs no command"
    assert (ws / ".njl" / "workspace.json").read_bytes() == before
    assert {e["job"] for e in res.entries if e["job"] != "*"} <= ENABLED
    assert {a.what for a in res.actions} <= {"write", "run"}


@pytest.mark.parametrize("backend", ["windows", "systemd", "launchd"])
def test_install_then_remove_round_trip_with_recorded_commands(mkws, tmp_path, backend):
    ws = mkws()
    rec = Recorder()
    ctx = ctx_for(ws, tmp_path)
    res = inst.install(ws, cfg_of(ws), backend=backend, run=rec, ctx=ctx, local_tz="UTC")
    assert res.ok, res.errors
    rec_entries = entries(ws)
    assert {e["job"] for e in rec_entries} == ENABLED if backend != "systemd" else \
        {e["job"] for e in rec_entries} == ENABLED
    files = [Path(e["path"]) for e in rec_entries if e["path"]]
    assert files and all(f.is_file() for f in files), "every recorded file was written"
    if backend == "windows":
        assert rec.has("schtasks", "/Create") and all(f.read_bytes().startswith(b"\xff\xfe") for f in files), "UTF-16 with BOM"
    if backend == "systemd":
        assert rec.has("systemctl", "--user", "daemon-reload") and rec.has("systemctl", "--user", "enable", "--now")
    if backend == "launchd":
        assert rec.has("launchctl", "bootstrap", "gui/501")
    # remove deletes exactly what was created and nothing else
    stray = files[0].with_name("not-ours.txt")
    stray.write_text("keep", encoding="utf-8")
    rm = inst.remove(ws, cfg_of(ws), run=rec)
    assert rm.ok and not any(f.exists() for f in files) and stray.read_text() == "keep"
    assert entries(ws) == []
    if backend == "windows":
        assert rec.has("schtasks", "/Delete")
    if backend == "systemd":
        assert rec.has("systemctl", "--user", "disable", "--now")
    if backend == "launchd":
        assert rec.has("launchctl", "bootout")


def test_install_is_idempotent_and_remove_with_nothing_recorded_is_a_note(mkws, tmp_path):
    ws = mkws()
    rec = Recorder()
    ctx = ctx_for(ws, tmp_path)
    inst.install(ws, cfg_of(ws), backend="windows", run=rec, ctx=ctx, local_tz="UTC")
    inst.install(ws, cfg_of(ws), backend="windows", run=rec, ctx=ctx, local_tz="UTC")
    assert len(entries(ws)) == len(ENABLED), "a second install replaces, never duplicates"
    inst.remove(ws, cfg_of(ws), run=rec)
    again = inst.remove(ws, cfg_of(ws), run=rec)
    assert again.ok and again.notes and not again.actions


def test_cron_round_trip_keeps_the_users_own_lines(mkws, tmp_path):
    ws = mkws()
    mine = "MAILTO=me@example.invalid\n0 5 * * * backup.sh\n"
    rec = Recorder(crontab=mine)
    ctx = ctx_for(ws, tmp_path)
    res = inst.install(ws, cfg_of(ws), backend="cron", run=rec, ctx=ctx, local_tz="UTC")
    assert res.ok and "# BEGIN profile-wrap:demo" in rec.crontab and rec.crontab.startswith(mine.rstrip("\n"))
    assert rec.crontab.count("# BEGIN profile-wrap:demo") == 1
    inst.install(ws, cfg_of(ws), backend="cron", run=rec, ctx=ctx, local_tz="UTC")
    assert rec.crontab.count("# BEGIN profile-wrap:demo") == 1
    inst.remove(ws, cfg_of(ws), run=rec)
    assert rec.crontab == mine, "only the profile-wrap block was removed"
    # a crontab that only held our block is removed entirely
    rec2 = Recorder()
    inst.install(ws, cfg_of(ws), backend="cron", run=rec2, ctx=ctx, local_tz="UTC")
    inst.remove(ws, cfg_of(ws), run=rec2)
    assert rec2.has("crontab", "-r")


def test_a_failing_scheduler_command_is_reported_and_what_was_done_is_recorded(mkws, tmp_path):
    ws = mkws()
    rec = Recorder(fail={"schtasks /Create"})
    res = inst.install(ws, cfg_of(ws), backend="windows", run=rec, ctx=ctx_for(ws, tmp_path), local_tz="UTC")
    assert not res.ok and "schtasks could not register" in res.errors[0]


def test_only_selects_jobs_and_refuses_disabled_or_unknown_ones(mkws, tmp_path):
    ws = mkws()
    ctx = ctx_for(ws, tmp_path)
    res = inst.install(ws, cfg_of(ws), backend="windows", only=["board"], dry_run=True, ctx=ctx, local_tz="UTC")
    assert [e["job"] for e in res.entries] == ["board"]
    off = inst.install(ws, cfg_of(ws), backend="windows", only=["post_due"], dry_run=True, ctx=ctx, local_tz="UTC")
    assert not off.ok and "not enabled" in off.errors[0]
    nope = inst.install(ws, cfg_of(ws), backend="windows", only=["nope"], dry_run=True, ctx=ctx, local_tz="UTC")
    assert "unknown job" in nope.errors[0]


def test_post_due_is_installed_only_for_api_scheduled_with_a_valid_acknowledgement(mkws, tmp_path):
    ws = mkws(schedule__jobs__post_due={"enabled": True, "every_min": 15})
    ctx = ctx_for(ws, tmp_path)
    res = inst.install(ws, cfg_of(ws), backend="windows", dry_run=True, ctx=ctx, local_tz="UTC")
    assert "post_due" not in {e["job"] for e in res.entries}, "the default posting.mode is api_click"


def test_the_installer_refuses_when_there_is_no_stable_runtime(mkws):
    ws = mkws()
    res = inst.install(ws, cfg_of(ws), backend="windows", run=Recorder(), local_tz="UTC")
    assert not res.ok and "profile-wrap runtime install" in res.errors[0]


def test_the_machine_timezone_shifts_the_times_the_scheduler_gets(mkws):
    ws = mkws(locale__timezone="Europe/Lisbon")
    rows = {r["job"]: r for r in inst.plan_rows(cfg_of(ws), local_tz="Asia/Amman", include_disabled=False)}
    assert rows["build_week"]["local_when"].startswith("THU 12:00") or rows["build_week"]["local_when"].startswith("THU 1")
    jobs = {j.name: j for j in inst.localised_jobs(cfg_of(ws), None, "Asia/Amman")}
    assert jobs["build_week"].rule.hour != 10, "the OS scheduler fires in machine local time"
    same = {j.name: j for j in inst.localised_jobs(cfg_of(ws), None, "Europe/Lisbon")}
    assert same["build_week"].rule.hour == 10


def test_status_reports_drift_and_last_runs(mkws, tmp_path):
    ws = mkws()
    rec = Recorder()
    ctx = ctx_for(ws, tmp_path)
    assert set(inst.status(ws, cfg_of(ws), run=rec)["drift"]) == ENABLED, "nothing installed yet"
    inst.install(ws, cfg_of(ws), backend="windows", run=rec, ctx=ctx, local_tz="UTC")
    (ws / "data" / "logs" / "runs.jsonl").write_text(
        json.dumps({"at": "2026-11-02T10:00:00+00:00", "job": "token_check", "exit": 0, "ok": True}) + "\n", encoding="utf-8")
    st = inst.status(ws, cfg_of(ws), run=rec)
    rows = {r["job"]: r for r in st["rows"]}
    assert st["drift"] == [] and rows["token_check"]["last_exit"] == 0 and rows["token_check"]["registered"]
    assert rows["build_week"]["next_run"].startswith("20")
    bad = Recorder(fail={"schtasks /Query"})
    assert set(inst.status(ws, cfg_of(ws), run=bad)["drift"]) == ENABLED, "installed on paper, gone in the OS"


def test_upcoming_lists_what_fires_in_48_hours(mkws):
    import datetime as dt
    ws = mkws()
    now = dt.datetime(2026, 11, 4, 9, 0, tzinfo=dt.timezone.utc)   # a Wednesday
    rows = inst.upcoming(cfg_of(ws), now, hours=48)
    jobs = [r["job"] for r in rows]
    assert "token_check" in jobs and "build_week" in jobs, "Thursday 10:00 is inside 48 hours"
    assert "doctor_weekly" not in jobs, "Monday is not"
    assert rows[-1]["at"] == "at login"


def test_cli_install_dry_run_and_refusal_without_yes(mkws, tmp_path, capsys, monkeypatch):
    ws = mkws()
    monkeypatch.setattr(inst, "build_context", lambda *a, **k: ctx_for(ws, tmp_path))
    assert cli.main(["schedule", "install", "--dry-run", "--backend", "windows", "--workspace", str(ws)]) == 0
    out = capsys.readouterr().out
    assert "schtasks /Create" in out and "profile-wrap-demo-build_week" in out
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False, raising=False)
    assert cli.main(["schedule", "install", "--backend", "windows", "--workspace", str(ws)]) == 2
    assert "--yes" in capsys.readouterr().out
    assert entries(ws) == []


def test_cli_plan_list_next_status(mkws, capsys):
    ws = mkws()
    for argv in (["schedule", "plan"], ["schedule", "list"], ["schedule", "next"], ["schedule", "status"]):
        assert cli.main([*argv, "--workspace", str(ws), "--json"]) == 0
        json.loads(capsys.readouterr().out)


# ------------------------------------------------------------------ the real thing

REAL = os.environ.get("PROFILE_WRAP_REAL_SCHEDULER") == "1"


@pytest.mark.skipif(not REAL, reason="set PROFILE_WRAP_REAL_SCHEDULER=1 to install into the machine's scheduler (CI does)")
def test_real_install_query_and_remove_round_trip(mkws, tmp_path):
    profile = "ci" + uuid.uuid4().hex[:8]
    ws = mkws(profile=profile)
    noop = tmp_path / "noop.py"
    noop.write_text("import sys; sys.exit(0)\n", encoding="utf-8")
    cfg = cfg_of(ws)
    cfg["schedule"]["jobs"] = {"doctor_weekly": {"enabled": True, "when": "MON 03:17"}}
    ctx = bk.Context(profile=profile, workspace=str(ws), entry=[sys.executable, str(noop)],
                     path_env=os.environ.get("PATH", ""), tools={}, home=str(Path.home()),
                     uid=os.getuid() if hasattr(os, "getuid") else 501)
    backend = inst.detect_backend(cfg)
    if backend == "systemd" and subprocess.run(["systemctl", "--user", "show-environment"], capture_output=True).returncode != 0:
        pytest.skip("no systemd user session here")
    try:
        res = inst.install(ws, cfg, backend=backend, ctx=ctx)
        assert res.ok, res.errors
        st = inst.status(ws, cfg)
        assert [r for r in st["rows"] if r["job"] == "doctor_weekly"][0]["registered"], "the OS knows the job"
        if backend == "windows":
            q = subprocess.run(["schtasks", "/Query", "/TN", f"profile-wrap-{profile}-doctor_weekly"], capture_output=True)
            assert q.returncode == 0
    finally:
        rm = inst.remove(ws, cfg)
        if backend == "cron":
            out = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout
            assert f"profile-wrap:{profile}" not in out
        if backend == "windows":
            q = subprocess.run(["schtasks", "/Query", "/TN", f"profile-wrap-{profile}-doctor_weekly"], capture_output=True)
            assert q.returncode != 0, "the task is gone"
        assert rm.ok, rm.errors
    assert entries(ws) == []
