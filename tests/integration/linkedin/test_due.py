"""``njli due`` through the real CLI entry and the library: scheduling rules and concurrency."""
from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys

from conftest import ROOT, gate_pass

from njli import limits
from njli.linkedin import due


def cli(env, *args, check_env=None):
    e = dict(os.environ)
    e.update(check_env or {})
    return subprocess.run([sys.executable, "-m", "njli", *args, "--workspace", str(env.ws)],
                          capture_output=True, text=True, timeout=120, cwd=str(ROOT), env=e)


def test_due_posts_one_draft_per_run_sorted_by_slot(env):
    env.scheduled()
    env.draft("late", slot_hours_ago=1)
    env.draft("early", slot_hours_ago=3)
    out = due.run_due(env.ws, env.cfg(), gate_fn=gate_pass)
    assert out.status == "posted" and out.slug == "early"
    assert [p["body"]["commentary"] for p in env.fake.posts] == ["A plain sentence about testing."]
    again = due.run_due(env.ws, env.cfg(), gate_fn=gate_pass)
    assert again.status == "refused" and again.exit_code == 0 and "gap guard" in again.reason
    assert len(env.fake.posts) == 1
    assert env.meta("late")["status"] == "queued"


def test_missed_slot_becomes_missed_and_is_not_posted(env):
    env.scheduled()
    env.draft("old", slot_hours_ago=7)
    out = due.run_due(env.ws, env.cfg(), gate_fn=gate_pass)
    assert out.status == "skipped" and env.meta("old")["status"] == "missed"
    assert env.fake.requests == []


def test_future_slot_waits(env):
    env.scheduled()
    env.draft("soon", slot_hours_ago=-3)
    assert due.run_due(env.ws, env.cfg(), gate_fn=gate_pass).reason == "nothing due"
    assert env.fake.requests == []


def test_click_mode_only_notifies(env):
    env.draft("a")                                    # posting.mode defaults to api_click
    out = due.run_due(env.ws, env.cfg(), gate_fn=gate_pass)
    assert out.status == "skipped" and "notified" in out.reason
    assert env.fake.requests == []
    notes = (env.ws / "data" / "logs" / "notifications.jsonl").read_text(encoding="utf-8")
    assert "a" in notes
    due.run_due(env.ws, env.cfg(), gate_fn=gate_pass)
    assert (env.ws / "data" / "logs" / "notifications.jsonl").read_text(encoding="utf-8").count("is due now") == 1


def test_unacknowledged_scheduled_mode_downgrades_to_notify(env):
    env.set_config(posting={"mode": "api_scheduled"})  # no typed acknowledgement
    env.draft("a")
    out = due.run_due(env.ws, env.cfg(), gate_fn=gate_pass)
    assert out.status == "skipped" and env.fake.requests == []


def test_corrupt_meta_does_not_stop_the_run(env):
    env.scheduled()
    env.draft("good")
    broken = env.ws / "drafts" / "broken"
    broken.mkdir()
    (broken / "meta.json").write_text("{not json", encoding="utf-8")
    out = due.run_due(env.ws, env.cfg(), gate_fn=gate_pass)
    assert out.status == "posted" and out.slug == "good"


def test_gate_failure_in_due_holds_the_draft_and_exits_zero(env):
    env.scheduled()
    env.draft("a")
    out = due.run_due(env.ws, env.cfg(),
                      gate_fn=lambda s, w, write=True: {"summary": "FAIL", "fails": ["x"]})
    assert out.status == "refused" and out.kind == "gate"
    assert env.meta("a")["status"] == "hold"


def test_guard_refusal_exits_zero_through_the_cli_and_logs_once(env):
    env.scheduled()
    env.draft("a")
    env.draft("b", slot_hours_ago=2)
    first = cli(env, "due")
    assert first.returncode == 0, first.stderr + first.stdout
    assert len(env.fake.posts) == 1
    second = cli(env, "due")
    assert second.returncode == 0 and "gap guard" in second.stdout
    third = cli(env, "due")
    assert third.returncode == 0
    log = (env.ws / "data" / "logs" / "post-due.jsonl").read_text(encoding="utf-8").splitlines()
    assert sum("gap guard" in x for x in log) == 1          # not log spam
    assert len(env.fake.posts) == 1


def test_paused_due_exits_four(env):
    env.scheduled()
    env.draft("a")
    limits.pause(env.ws, "posting")
    result = cli(env, "due")
    assert result.returncode == 4 and env.fake.requests == []


def test_two_concurrent_due_runs_produce_one_post(env):
    env.scheduled()
    env.draft("a")
    procs = [subprocess.Popen([sys.executable, "-m", "njli", "due", "--workspace", str(env.ws), "--json"],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                              cwd=str(ROOT), env=dict(os.environ)) for _ in range(2)]
    outs = [p.communicate(timeout=120) for p in procs]
    assert [p.returncode for p in procs] == [0, 0], outs
    assert len(env.fake.posts) == 1
    states = [r["state"] for r in env.ledger_rows()]
    assert states.count("posted") == 1 and "needs_check" not in states
    results = [json.loads(o[0])["status"] for o in outs]
    assert sorted(results) == ["posted", "refused"], results


def test_status_and_post_dry_run_through_the_cli(env):
    env.draft("a", first_comment="Read more in the notes.")
    status = cli(env, "status", "--json")
    assert status.returncode == 0
    data = json.loads(status.stdout)
    assert data["api_version"] == "202609" and data["token"]["state"] == "ok"
    dry = cli(env, "post", "a", "--dry")
    assert dry.returncode == 0 and "--- caption ---" in dry.stdout and "first comment" in dry.stdout
    assert env.fake.requests == [] and env.ledger_rows() == []
    preview = cli(env, "post", "a")                     # no --now: a preview, never a send
    assert preview.returncode == 0 and env.fake.requests == []
    sent = cli(env, "post", "a", "--now")
    assert sent.returncode == 0, sent.stderr
    assert len(env.fake.posts) == 1


def test_missing_token_gives_one_actionable_line(env):
    for f in env.cfg_dir.glob("token.json"):
        f.unlink()
    env.draft("a")
    result = cli(env, "post", "a", "--now")
    assert result.returncode == 1 and "njli auth" in result.stderr
    assert "Traceback" not in result.stderr


def test_api_versions_command(env):
    result = cli(env, "api-versions", "--json")
    data = json.loads(result.stdout)
    assert result.returncode == 0 and data["selected"] == "202609"
    assert {v["version"] for v in data["versions"]} >= {"202510", "202609"}
    assert dt.date.fromisoformat(data["retrieved"])
