"""build-week: catch-up (PW-R03), best-effort log (PW-R06), browser preflight before any model call."""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "integration" / "schedule"))
from schedhelp import cfg_of, make_ws  # noqa: E402

from profile_wrap import claude_runner as cr  # noqa: E402
from profile_wrap import cli  # noqa: E402
from profile_wrap.plan import build_week as bw  # noqa: E402
from profile_wrap.plan import calendar as cal  # noqa: E402

TODAY = dt.date(2026, 11, 2)


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("PROFILE_WRAP_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("PROFILE_WRAP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PROFILE_WRAP_TEST", "1")


@pytest.fixture()
def ws(tmp_path):
    return make_ws(tmp_path)


def ent(offset, slug=None, **kw):
    e = {"date": (TODAY + dt.timedelta(days=offset)).isoformat(), "slug": slug or f"post-{offset}", "lang": "en",
         "format": "text", "title": f"Title {offset}", "status": "planned", "angle": "an angle"}
    e.update(kw)
    return e


def seed(ws, *entries):
    cal.update(ws, lambda c: c["entries"].extend(entries))


class Spy:
    def __init__(self, ws, fail=()):
        self.ws, self.calls, self.fail = ws, [], set(fail)

    def __call__(self, workspace, cfg, *, job, kind, prompt, allow, expect=(), exe=None, **kw):
        self.calls.append((kind, job))
        slug = job.split("-", 1)[1]
        if kind == "build":
            if slug in self.fail:
                return cr.WorkerResult(cr.FAILED, proc_rc=1, err="worker crashed")
            dd = self.ws / "drafts" / slug
            (dd / "caption.txt").write_text("Hook\n\nBody\n", encoding="utf-8")
            (dd / "meta.json").write_text(json.dumps({"slug": slug, "title": "T"}), encoding="utf-8")
        elif kind == "review":
            out = self.ws / expect[0]
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps({"seat": "council-editor", "verdict": "pass", "blockers": [], "notes": []}),
                           encoding="utf-8")
        return cr.WorkerResult(cr.OK)


def steps():
    return bw.Steps(lambda s, f: (0, ""), lambda s: (0, ""), lambda s: (0, "PASS"))


def run(ws, spy, **kw):
    return bw.build_week(ws, cfg_of(ws), today=TODAY, steps=steps(), runner=spy, notify_user=False, **kw)


# ---------------------------------------------------------------- catch-up

def test_catch_up_picks_entries_one_to_seven_days_out_only_when_asked(ws):
    seed(ws, ent(0), ent(1), ent(7), ent(9), ent(20))
    off = run(ws, Spy(ws), dry_run=True)
    assert [i.slug for i in off.items] == ["post-9"]
    on = run(ws, Spy(ws), dry_run=True, catchup=True)
    assert [i.slug for i in on.items] == ["post-1", "post-7", "post-9"]
    assert "catch-up" in on.items[0].detail and "catch-up" not in on.items[2].detail


def test_catch_up_builds_a_missed_week_and_marks_it_built(ws):
    seed(ws, ent(3), ent(5))
    spy = Spy(ws)
    rep = run(ws, spy, catchup=True)
    assert [i.status for i in rep.items] == ["built", "built"]
    assert {e["slug"]: e["status"] for e in cal.load(ws)["entries"]} == {"post-3": "built", "post-5": "built"}
    assert (ws / "drafts" / "post-3" / "meta.json").is_file()


def test_catch_up_skips_entries_that_already_have_a_draft_or_are_not_briefed(ws):
    seed(ws, ent(2), ent(3, title="Open slot", open=True), ent(4, status="skipped"))
    (ws / "drafts" / "post-2").mkdir()
    rep = run(ws, Spy(ws), dry_run=True, catchup=True)
    assert rep.items == []
    assert any("already exists" in s.detail for s in rep.skipped)


def test_the_command_line_has_catch_up_on_by_default_and_no_catchup_turns_it_off(ws, capsys):
    soon = dt.date.today() + dt.timedelta(days=2)       # the command line uses the real calendar day
    seed(ws, ent(2, date=soon.isoformat()))
    assert cli.main(["build-week", "--workspace", str(ws), "--dry-run", "--json"]) == 0
    assert [i["slug"] for i in json.loads(capsys.readouterr().out)["items"]] == ["post-2"]
    assert cli.main(["build-week", "--workspace", str(ws), "--dry-run", "--json", "--no-catchup"]) == 0
    assert json.loads(capsys.readouterr().out)["items"] == []


# ---------------------------------------------------------------- retry marker

def test_a_failed_entry_is_retried_next_run_and_succeeds(ws):
    seed(ws, ent(9))
    rep = run(ws, Spy(ws, fail={"post-9"}))
    assert rep.items[0].status == "failed" and "attempt 1 of 3" in rep.items[0].detail
    e = cal.find(cal.load(ws), "post-9")
    assert e["status"] == "planned" and e["build_attempts"] == 1 and e["build_failed_at"]
    assert (ws / "drafts" / "post-9").exists(), "the failed run left a folder, which must not block the retry"
    rep2 = run(ws, Spy(ws))
    assert [i.status for i in rep2.items] == ["built"]
    e = cal.find(cal.load(ws), "post-9")
    assert e["status"] == "built" and "build_attempts" not in e and "build_failed_at" not in e


def test_a_failing_entry_stops_after_the_cap_and_is_listed_with_the_fix(ws):
    seed(ws, ent(9))
    for n in (1, 2, 3):
        rep = run(ws, Spy(ws, fail={"post-9"}))
        assert rep.items[0].status == "failed", n
    assert "giving up" in rep.items[0].detail
    spy = Spy(ws)
    rep = run(ws, spy)
    assert rep.items == [] and spy.calls == []
    assert "failed 3 times" in rep.skipped[0].detail and "--slug post-9" in rep.skipped[0].detail
    # an explicit --slug still runs it
    rep = run(ws, Spy(ws), slug="post-9")
    assert [i.status for i in rep.items] == ["built"]


def test_the_cap_comes_from_the_config_key_when_set(ws):
    seed(ws, ent(9))
    cfg = cfg_of(ws)
    cfg.setdefault("schedule", {})["build_max_attempts"] = 1
    bw.build_week(ws, cfg, today=TODAY, steps=steps(), runner=Spy(ws, fail={"post-9"}), notify_user=False)
    rep = bw.build_week(ws, cfg, today=TODAY, steps=steps(), runner=Spy(ws), notify_user=False)
    assert rep.items == [] and "failed 1 times" in rep.skipped[0].detail


def test_a_queued_draft_is_never_rebuilt_even_with_a_failure_marker(ws):
    seed(ws, ent(9, build_failed_at="2026-11-01T00:00:00+00:00", build_attempts=1))
    (ws / "drafts" / "post-9").mkdir()
    (ws / "drafts" / "post-9" / "meta.json").write_text(json.dumps({"status": "queued"}), encoding="utf-8")
    assert run(ws, Spy(ws), dry_run=True).items == []


# ---------------------------------------------------------------- best-effort log

def test_a_log_that_cannot_be_written_never_stops_the_build(ws, monkeypatch):
    seed(ws, ent(9))
    real_open = Path.open

    def deny(self, *a, **k):
        if self.name == "build.log":
            raise PermissionError("locked by another process")
        return real_open(self, *a, **k)
    monkeypatch.setattr(Path, "open", deny)
    rep = run(ws, Spy(ws))
    assert [i.status for i in rep.items] == ["built"]
    fallback = list((ws / "work").glob("build-fallback-*.log"))
    assert fallback and "build post-9" in fallback[0].read_text(encoding="utf-8")


def test_when_every_log_target_fails_the_message_goes_to_stderr(ws, monkeypatch, capsys):
    def deny(self, *a, **k):
        raise PermissionError("no")
    monkeypatch.setattr(Path, "open", deny)
    bw._log(ws, "hello")
    assert "hello" in capsys.readouterr().err


# ---------------------------------------------------------------- browser preflight

def test_no_browser_means_no_model_call_and_the_fix_command(ws):
    seed(ws, ent(9, format="slides"))
    spy = Spy(ws)

    def missing(w, cfg):
        raise bw.BuildError("cannot render: no browser found. Fix: winget install Google.Chrome")
    with pytest.raises(bw.BuildError, match="Fix: winget"):
        bw.build_week(ws, cfg_of(ws), today=TODAY, steps=steps(), runner=spy, notify_user=False, preflight=missing)
    assert spy.calls == []
    assert "preflight failed" in (ws / "work" / "build.log").read_text(encoding="utf-8")
    assert cal.find(cal.load(ws), "post-9")["status"] == "planned"


def test_preflight_runs_only_for_formats_that_render(ws):
    seed(ws, ent(9, format="text"))
    called = []
    run(ws, Spy(ws), preflight=lambda w, c: called.append(1))
    assert called == []
    seed(ws, ent(10, format="slides"))
    run(ws, Spy(ws), preflight=lambda w, c: called.append(1))
    assert called == [1]


def test_the_real_preflight_is_on_when_the_real_steps_are_used(ws, monkeypatch):
    seed(ws, ent(9, format="gif"))
    monkeypatch.setattr(bw, "browser_preflight", lambda w, c: (_ for _ in ()).throw(bw.BuildError("cannot render: x")))
    spy = Spy(ws)
    with pytest.raises(bw.BuildError):
        bw.build_week(ws, cfg_of(ws), today=TODAY, runner=spy, notify_user=False)
    assert spy.calls == []


def test_browser_preflight_reports_a_missing_browser_with_the_os_fix(ws):
    from profile_wrap.visuals import VisualsError

    def none(cfg):
        raise VisualsError("no browser found.")
    with pytest.raises(bw.BuildError) as ei:
        bw.browser_preflight(ws, {}, require=none)
    assert "cannot render" in str(ei.value) and "Fix:" in str(ei.value)


def test_browser_preflight_reports_a_browser_that_will_not_start(ws, tmp_path):
    from profile_wrap.visuals.browser import Browser
    exe = tmp_path / "chrome"
    exe.write_text("x", encoding="utf-8")
    with pytest.raises(bw.BuildError, match="did not start: crashed"):
        bw.browser_preflight(ws, {}, require=lambda c: Browser(exe, "test"), smoke=lambda p, w: (False, "crashed"))
    assert bw.browser_preflight(ws, {}, require=lambda c: Browser(exe, "test"), smoke=lambda p, w: (True, "")) == str(exe)


def test_the_launch_smoke_uses_a_throwaway_profile_and_cleans_it_up(ws, tmp_path):
    exe = tmp_path / "fake-chrome.py"
    exe.write_text("import sys\nassert any(a.startswith('--user-data-dir=') for a in sys.argv)\n"
                   "assert 'about:blank' in sys.argv\n", encoding="utf-8")
    runner = tmp_path / "run.cmd" if sys.platform == "win32" else tmp_path / "run.sh"
    if sys.platform == "win32":
        runner.write_text(f'@"{sys.executable}" "{exe}" %*\n', encoding="utf-8")
    else:
        runner.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{exe}" "$@"\n', encoding="utf-8")
        runner.chmod(0o755)
    ok, reason = bw._launch_smoke(runner, ws, timeout=60)
    assert ok, reason
    assert not list((ws / "work").glob(".preflight-*"))
