"""PW-R01: ``post_due`` in copy mode is a reminder-only job. Plus the Windows command-line guard."""
from __future__ import annotations

import datetime as dt
import json
import sys

import pytest

from profile_wrap.linkedin import due, post
from profile_wrap.schedule import backends as bk
from profile_wrap.schedule import install as inst
from profile_wrap.schedule.jobs import JOB_TABLE, jobs_from_config, reminder_only, wanted
from test_sched_common import cfg_of, isolate, mkws, toasts  # noqa: F401

NOW = dt.datetime(2026, 11, 16, 12, 0, tzinfo=dt.timezone.utc)


def draft(ws, slug, hours_ago):
    folder = ws / "drafts" / slug
    folder.mkdir(parents=True, exist_ok=True)
    slot = NOW - dt.timedelta(hours=hours_ago)
    (folder / "meta.json").write_text(json.dumps({"slug": slug, "status": "queued",
                                                  "scheduled_at": slot.isoformat()}), encoding="utf-8")
    return folder


@pytest.fixture()
def never_posts(monkeypatch):
    def forbidden(*a, **k):
        raise AssertionError("the reminder-only job must never call post.publish")

    monkeypatch.setattr(post, "publish", forbidden)


POST_DUE = {"enabled": True, "every_min": 15}


@pytest.mark.parametrize("mode", ["copy", "api_click", "api_scheduled"])
def test_post_due_is_wanted_in_every_posting_mode_when_enabled(mkws, mode):
    ws = mkws(posting__mode=mode, schedule__jobs__post_due=POST_DUE)
    assert wanted(cfg_of(ws), "post_due")
    assert "post_due" in {j.name for j in jobs_from_config(cfg_of(ws))}


def test_post_due_is_enabled_by_default_and_can_be_turned_off(mkws):
    from profile_wrap import config as cfgmod
    assert cfgmod.defaults()["schedule"]["jobs"]["post_due"]["enabled"] is True
    ws = mkws(posting__mode="copy", schedule__jobs__post_due={"enabled": False, "every_min": 15})
    assert not wanted(cfg_of(ws), "post_due")


@pytest.mark.parametrize("mode", ["copy", "api_click", "api_scheduled"])
def test_nothing_posts_unless_the_mode_is_an_acknowledged_api_scheduled(mkws, toasts, never_posts, mode):
    """The default config runs post_due everywhere, so only an acknowledged api_scheduled may reach post.publish.

    ``api_scheduled`` here has no acknowledgement, so it is downgraded and only reminds.
    """
    ws = mkws(posting__mode=mode)
    draft(ws, "monday-post", hours_ago=1)
    out = due.run_due(ws, cfg_of(ws), now=NOW)          # no reminder_only argument, no environment flag
    assert out.status == "skipped" and "notified" in out.reason
    assert [t for t, _ in toasts] == ["Profile-Wrap: a post is due"]


def test_reminder_only_follows_the_effective_mode(mkws):
    assert reminder_only(cfg_of(mkws(posting__mode="copy")), "post_due")
    assert reminder_only(cfg_of(mkws(posting__mode="api_click")), "post_due")
    # api_scheduled without a valid acknowledgement is downgraded to api_click, so it is a reminder too
    assert reminder_only(cfg_of(mkws(posting__mode="api_scheduled")), "post_due")
    assert not reminder_only(cfg_of(mkws(posting__mode="copy")), "token_check")


def test_a_due_copy_draft_notifies_once_and_never_posts(mkws, toasts, never_posts):
    ws = mkws(posting__mode="copy")
    draft(ws, "monday-post", hours_ago=1)
    cfg = cfg_of(ws)
    out = due.run_due(ws, cfg, now=NOW, reminder_only=True)
    assert out.status == "skipped" and "notified" in out.reason
    assert [t for t, _ in toasts] == ["Profile-Wrap: a post is due"]
    due.run_due(ws, cfg, now=NOW + dt.timedelta(minutes=15), reminder_only=True)
    assert len(toasts) == 1, "a second run inside the reminder interval stays quiet"


def test_a_still_unposted_slot_reminds_again_after_the_interval(mkws, toasts, never_posts):
    ws = mkws(posting__mode="copy")
    draft(ws, "monday-post", hours_ago=1)
    cfg = cfg_of(ws)
    due.run_due(ws, cfg, now=NOW, reminder_only=True)
    due.run_due(ws, cfg, now=NOW + dt.timedelta(hours=due.REMIND_AGAIN_HOURS + 0.1), reminder_only=True)
    assert len(toasts) == 2


def test_a_missed_copy_draft_notifies_missed_once(mkws, toasts, never_posts):
    ws = mkws(posting__mode="copy")
    draft(ws, "old-post", hours_ago=7)
    cfg = cfg_of(ws)
    due.run_due(ws, cfg, now=NOW, reminder_only=True)
    assert [t for t, _ in toasts] == ["Profile-Wrap: post missed"]
    assert json.loads((ws / "drafts" / "old-post" / "meta.json").read_text(encoding="utf-8"))["status"] == "missed"


def test_the_environment_flag_forces_reminder_only_even_in_api_scheduled(mkws, toasts, never_posts, monkeypatch):
    ws = mkws(posting__mode="api_scheduled")
    draft(ws, "monday-post", hours_ago=1)
    monkeypatch.setenv(due.REMINDER_ENV, "1")
    out = due.run_due(ws, cfg_of(ws), now=NOW)
    assert out.status == "skipped" and toasts


# ------------------------------------------------------------------ installs on every backend

def ctx_for(ws, tmp_path, **kw):
    return bk.Context(profile="demo", workspace=str(ws), entry=[sys.executable, str(tmp_path / "runtime")],
                      path_env="/usr/bin", tools={}, home=str(tmp_path / "home"), uid=501, pythonw=None, **kw)


@pytest.mark.parametrize("backend", ["windows", "systemd", "cron", "launchd"])
def test_a_copy_mode_workspace_renders_a_post_due_entry_on_every_backend(mkws, tmp_path, backend):
    ws = mkws(posting__mode="copy", schedule__jobs__post_due=POST_DUE)
    res = inst.install(ws, cfg_of(ws), backend=backend, dry_run=True, ctx=ctx_for(ws, tmp_path), local_tz="UTC")
    assert res.ok
    assert "post_due" in " ".join(a.target + a.text for a in res.actions)


def test_job_argv_for_the_scheduled_checks():
    assert JOB_TABLE["token_check"]["argv"] == ["auth", "check", "--online", "--notify"]
    assert JOB_TABLE["doctor_weekly"]["argv"] == ["doctor", "--json", "--notify"]


# ------------------------------------------------------------------ Windows: no console wrapper

def test_the_windows_task_never_wraps_the_command_in_conhost_or_cmd(mkws, tmp_path):
    ws = mkws(posting__mode="copy", schedule__jobs__post_due=POST_DUE)
    ctx = ctx_for(ws, tmp_path)
    ctx.pythonw = str(tmp_path / "pythonw.exe")
    for job in jobs_from_config(cfg_of(ws)):
        art = bk.render_task_xml(ctx, job)
        cmd, args = bk.windows_action(ctx, job)
        text = (cmd + " " + args + " " + art.text).lower()
        assert "conhost" not in text and "--headless" not in text, "conhost hides the job's exit code"
        assert "cmd /c" not in text and "cmd.exe" not in text and "&gt;&gt;" not in text and ">>" not in text
        assert cmd.lower().endswith(("pythonw.exe", "python.exe"))
