"""PW-R08 and the schedule-health hook: ``doctor --notify`` sends one summary; findings from
``profile_wrap.schedule.schedule_health`` are rendered when that function exists."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "integration" / "schedule"))
from schedhelp import make_ws  # noqa: E402

from profile_wrap import cli, doctor  # noqa: E402
from profile_wrap import notify as notify_mod  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("PROFILE_WRAP_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("PROFILE_WRAP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PROFILE_WRAP_TEST", "1")


def result_of(*rows):
    return {"checks": [{"id": i, "name": n, "status": s, "detail": d, "hint": ""} for i, n, s, d in rows]}


def test_nothing_is_sent_when_every_check_passes(monkeypatch):
    sent = []
    monkeypatch.setattr(notify_mod, "notify", lambda *a, **k: sent.append((a, k)) or "log")
    assert doctor.notify_summary(result_of(("a", "A", "pass", ""), ("b", "B", "skip", "")), mode="log") is None
    assert sent == []


def test_one_notification_lists_every_warn_and_fail(monkeypatch):
    sent = []
    monkeypatch.setattr(notify_mod, "notify", lambda title, msg, workspace=None, mode="auto":
                        sent.append((title, msg, mode)) or "log")
    channel = doctor.notify_summary(result_of(("a", "Token", "fail", "expired"), ("b", "Browser", "warn", "none"),
                                              ("c", "Fine", "pass", "")), mode="log")
    assert channel == "log" and len(sent) == 1
    title, msg, mode = sent[0]
    assert title == "Profile-Wrap doctor: 1 failing" and mode == "log"
    assert "FAIL Token: expired" in msg and "WARN Browser: none" in msg and "Fine" not in msg


def test_a_warn_only_result_says_warnings(monkeypatch):
    sent = []
    monkeypatch.setattr(notify_mod, "notify", lambda title, *a, **k: sent.append(title) or "log")
    doctor.notify_summary(result_of(("b", "Browser", "warn", "none")), mode="log")
    assert sent == ["Profile-Wrap doctor: 1 warning(s)"]


def test_with_a_workspace_the_same_summary_is_sent_once_per_ttl(tmp_path, monkeypatch):
    ws = make_ws(tmp_path)
    sent = []
    monkeypatch.setattr(notify_mod, "notify", lambda title, msg, workspace=None, mode="auto":
                        sent.append(title) or "log")
    rows = result_of(("b", "B", "warn", "x"), ("a", "A", "fail", "y"))
    assert doctor.notify_summary(rows, ws, mode="log") == "log"
    assert doctor.notify_summary(rows, ws, mode="log") is None
    assert len(sent) == 1
    seen = json.loads((ws / "data" / "state" / "notify-seen.json").read_text(encoding="utf-8"))
    assert list(seen) == ["doctor:a=fail,b=warn"]
    # a different set of problems is a new key and notifies at once
    assert doctor.notify_summary(result_of(("c", "C", "warn", "z")), ws, mode="log") == "log"
    assert len(sent) == 2


def test_mode_off_in_the_config_sends_nothing(tmp_path, monkeypatch):
    ws = make_ws(tmp_path)
    cfgp = ws / "config" / "profile-wrap.json"
    cfg = json.loads(cfgp.read_text(encoding="utf-8"))
    cfg["schedule"]["notify"] = "off"
    cfgp.write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.setattr(notify_mod, "notify", lambda *a, **k: pytest.fail("must not notify"))
    assert doctor.notify_summary(result_of(("b", "B", "warn", "x")), ws) is None


def test_the_command_line_flag_notifies_once_and_keeps_the_exit_code(tmp_path, monkeypatch, capsys):
    ws = make_ws(tmp_path)
    sent = []
    monkeypatch.setattr(notify_mod, "notify", lambda title, msg, workspace=None, mode="auto":
                        sent.append((title, workspace, mode)) or "log")
    monkeypatch.setattr(doctor, "run", lambda **kw: {
        "schema_version": 1, "plugin_version": "x", "os": "linux", "python": "3", "workspace": str(ws),
        "generated_at": "t", "summary": {"pass": 0, "warn": 1, "fail": 0, "skip": 0},
        "checks": [{"id": "horizon", "name": "Posts", "status": "warn", "detail": "empty", "hint": ""}]})
    rc = cli.main(["doctor", "--workspace", str(ws), "--notify"])
    assert rc == 0 and len(sent) == 1 and sent[0][1] == ws
    assert cli.main(["doctor", "--workspace", str(ws)]) == 0 and len(sent) == 1, "no flag, no notification"


def test_schedule_health_findings_are_rendered_when_the_function_exists(tmp_path, monkeypatch):
    import profile_wrap.schedule.health as sched
    ws = make_ws(tmp_path)
    monkeypatch.setattr(sched, "schedule_health", lambda w, cfg=None: [
        {"id": "stale", "name": "build_week", "severity": "warning", "message": "has not run for 9 days",
         "hint": "profile-wrap run build_week"},
        {"id": "gone", "title": "Task", "status": "fail", "detail": "the task is missing"}])
    rows = {c["id"]: c for c in doctor.run(workspace=ws)["checks"] if c["id"].startswith("schedule_")}
    assert rows["schedule_stale"]["status"] == "warn" and rows["schedule_stale"]["hint"] == "profile-wrap run build_week"
    assert rows["schedule_gone"]["status"] == "fail" and rows["schedule_gone"]["detail"] == "the task is missing"


def test_a_clean_schedule_health_is_one_pass_row(tmp_path, monkeypatch):
    import profile_wrap.schedule.health as sched
    ws = make_ws(tmp_path)
    monkeypatch.setattr(sched, "schedule_health", lambda w, cfg: [])
    row = next(c for c in doctor.run(workspace=ws)["checks"] if c["id"] == "schedule_health")
    assert row["status"] == "pass"


def test_a_crashing_schedule_health_is_a_warning(tmp_path, monkeypatch):
    import profile_wrap.schedule.health as sched
    ws = make_ws(tmp_path)

    def boom(*a):
        raise RuntimeError("nope")
    monkeypatch.setattr(sched, "schedule_health", boom)
    row = next(c for c in doctor.run(workspace=ws)["checks"] if c["id"] == "schedule_health")
    assert row["status"] == "warn" and "nope" in row["detail"]


def test_the_real_schedule_health_findings_become_rows(tmp_path):
    ws = make_ws(tmp_path)
    rows = [c for c in doctor.run(workspace=ws)["checks"] if c["id"].startswith("schedule_")]
    assert rows, "schedule_health must report at least one row"
    assert all(c["status"] in ("pass", "warn", "fail", "skip") for c in rows)


def test_a_rejected_token_is_a_failing_doctor_row(tmp_path, monkeypatch):
    import time
    from profile_wrap import paths
    from profile_wrap.linkedin import auth
    ws = make_ws(tmp_path)
    cfg_dir = paths.config_dir(json.loads((ws / "config" / "profile-wrap.json").read_text(encoding="utf-8"))["profile_id"])
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "token.json").write_text(json.dumps(
        {"access_token": "x", "expires_at": time.time() + 40 * 86400, "name": "n"}), encoding="utf-8")
    row = next(c for c in doctor.run(workspace=ws)["checks"] if c["id"] == "token")
    assert row["status"] == "pass"
    auth.mark_rejected(cfg_dir, 401, "revoked")
    row = next(c for c in doctor.run(workspace=ws)["checks"] if c["id"] == "token")
    assert row["status"] == "fail" and "rejected" in row["detail"]
