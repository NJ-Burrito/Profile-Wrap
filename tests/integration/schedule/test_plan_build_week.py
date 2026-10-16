"""``njli build-week``: dry run spends no model, builds stay drafts, failures are contained."""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import pytest

from schedhelp import cfg_of
from njli import claude_runner as cr
from njli import cli
from njli.plan import build_week as bw
from njli.plan import calendar as cal

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runner"))
import wsfix  # noqa: E402

TODAY = dt.date(2026, 11, 2)


def d(offset: int) -> str:
    return (TODAY + dt.timedelta(days=offset)).isoformat()


def seed(ws, *entries):
    cal.update(ws, lambda c: c["entries"].extend(entries))


def ent(offset, slug=None, **kw):
    e = {"date": d(offset), "slug": slug or f"post-{offset}", "lang": "en", "format": "text",
         "title": f"Title {offset}", "status": "planned", "angle": "an angle"}
    e.update(kw)
    return e


class Spy:
    """Stands in for the worker runner: writes the files a real worker would, counts the calls."""

    def __init__(self, ws, *, fail_build=(), verdict="pass"):
        self.ws, self.calls, self.fail_build, self.verdict = ws, [], set(fail_build), verdict

    def __call__(self, workspace, cfg, *, job, kind, prompt, allow, expect=(), exe=None, **kw):
        self.calls.append((kind, job, list(allow)))
        slug = job.split("-", 1)[1]
        if kind == "build":
            if slug in self.fail_build:
                return cr.WorkerResult(cr.FAILED, proc_rc=1, err="worker crashed")
            dd = self.ws / "drafts" / slug
            (dd / "caption.txt").write_text("Hook line\n\nBody line\n", encoding="utf-8")
            (dd / "meta.json").write_text(json.dumps({"slug": slug, "title": "From worker", "status": "queued",
                                                      "scheduled_at": "1999-01-01T00:00:00+00:00"}), encoding="utf-8")
            if "videos/" + slug + "/**" in allow:
                (self.ws / "videos" / slug).mkdir(parents=True, exist_ok=True)
                (self.ws / "videos" / slug / "index.html").write_text("<html></html>", encoding="utf-8")
        elif kind == "review":
            out = self.ws / expect[0]
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps({"seat": "council-editor", "verdict": self.verdict, "blockers": [],
                                       "notes": ["ok"]}), encoding="utf-8")
        elif kind == "fix":
            pass
        return cr.WorkerResult(cr.OK)


class Steps:
    def __init__(self, gate_results=((0, "PASS"),)):
        self.log, self.gate_results = [], list(gate_results)

    def as_steps(self):
        def scaffold(slug, fmt):
            self.log.append(("scaffold", slug))
            return 0, ""

        def render(slug):
            self.log.append(("render", slug))
            return 0, ""

        def gate(slug):
            self.log.append(("gate", slug))
            return self.gate_results.pop(0) if len(self.gate_results) > 1 else self.gate_results[0]

        return bw.Steps(scaffold, render, gate)


def run_build(ws, cfg, spy, steps, **kw):
    return bw.build_week(ws, cfg, today=TODAY, steps=steps.as_steps(), runner=spy, notify_user=False, **kw)


def test_dry_run_calls_no_model_and_changes_nothing(mkws):
    ws = mkws()
    seed(ws, ent(9), ent(10, format="gif"), ent(30))
    before = (ws / "strategy" / "calendar.json").read_bytes()

    def forbidden(*a, **k):
        raise AssertionError("a model was called during --dry-run")

    class NoSteps:
        def __getattr__(self, name):
            raise AssertionError("a step ran during --dry-run")

    rep = bw.build_week(ws, cfg_of(ws), today=TODAY, dry_run=True, runner=forbidden, steps=NoSteps(),
                        notify_user=False)
    assert rep.dry_run and rep.model_calls == 0
    assert [i.slug for i in rep.items] == ["post-9", "post-10"], "only entries 8-14 days ahead"
    assert all(i.time and i.scheduled_at.startswith(i.date + "T" + i.time) for i in rep.items)
    assert (ws / "strategy" / "calendar.json").read_bytes() == before
    assert not (ws / "drafts" / "post-9").exists() and not (ws / "videos" / "post-10").exists()
    plan = json.loads((ws / "work" / "dryrun" / "build-week.json").read_text(encoding="utf-8"))
    assert plan["dry_run"] is True and len(plan["items"]) == 2


def test_dry_run_through_the_command_line_spawns_no_worker(mkws, capsys, monkeypatch):
    ws = mkws()
    seed(ws, ent(9))
    called = []
    monkeypatch.setattr(cr, "run_worker", lambda *a, **k: called.append(1))
    monkeypatch.setattr(bw, "default_steps", lambda *a, **k: (_ for _ in ()).throw(AssertionError("steps")))
    # the command uses the real clock, so ask for a wide window around the entry
    rc = cli.main(["build-week", "--dry-run", "--days", "0-3650", "--workspace", str(ws), "--json"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0 and called == [] and out["model_calls"] == 0 and out["dry_run"] is True


def test_selection_rules(mkws):
    ws = mkws()
    (ws / "drafts" / "post-9").mkdir(parents=True)
    (ws / "published" / "ledger.jsonl").parent.mkdir(exist_ok=True)
    (ws / "published" / "ledger.jsonl").write_text(json.dumps({"slug": "post-10", "state": "posted"}) + "\n",
                                                   encoding="utf-8")
    seed(ws, ent(9), ent(10), ent(11, status="built"), ent(12, open=True), ent(13), ent(14), ent(15), ent(7))
    todo, skipped = bw.select(cal.load(ws), ws, today=TODAY, lo=8, hi=14)
    assert [e["slug"] for e in todo] == ["post-13", "post-14"]
    reasons = {s.slug: s.detail for s in skipped}
    assert "already exists" in reasons["post-9"] and "already exists" in reasons["post-10"]
    assert "open slot" in reasons["post-12"]
    one, _ = bw.select(cal.load(ws), ws, today=TODAY, lo=8, hi=14, only="post-15")
    assert [e["slug"] for e in one] == ["post-15"], "--slug ignores the day window"


def test_a_successful_build_stays_a_draft_and_marks_the_calendar_built(mkws):
    ws = mkws()
    seed(ws, ent(9, claims=["F01"]), ent(10, format="gif"))
    spy, steps = Spy(ws), Steps()
    rep = run_build(ws, cfg_of(ws), spy, steps)
    assert [i.status for i in rep.items] == ["built", "built"] and rep.model_calls == 4
    for slug in ("post-9", "post-10"):
        meta = json.loads((ws / "drafts" / slug / "meta.json").read_text(encoding="utf-8"))
        assert meta["status"] == "draft", "a build never queues"
        assert meta["scheduled_at"].startswith(d(int(slug.split("-")[1]))), "the contract fields are the orchestrator's"
        assert meta["scheduled_at"] != "1999-01-01T00:00:00+00:00"
        assert meta["slug"] == slug and meta["lang"] == "en"
    assert json.loads((ws / "drafts" / "post-9" / "meta.json").read_text(encoding="utf-8"))["claims"] == ["F01"]
    assert json.loads((ws / "drafts" / "post-10" / "meta.json").read_text(encoding="utf-8"))["video_project"] == "videos/post-10"
    hist = json.loads((ws / "drafts" / "post-9" / "review.json").read_text(encoding="utf-8"))
    assert hist[0]["action"] == "council-editor" and hist[0]["verdict"] == "pass"
    entries = {e["slug"]: e for e in cal.load(ws)["entries"]}
    assert entries["post-9"]["status"] == "built" and entries["post-9"]["time"] and entries["post-9"]["time_auto"]
    assert ("scaffold", "post-10") in steps.log and ("render", "post-10") in steps.log
    assert ("render", "post-9") not in steps.log, "text posts have nothing to render"
    # the build worker may write the draft and the project, nothing else
    build_calls = [c for c in spy.calls if c[0] == "build"]
    assert build_calls[0][2] == ["drafts/post-9/**"]
    assert build_calls[1][2] == ["drafts/post-10/**", "videos/post-10/**"]
    review_calls = [c for c in spy.calls if c[0] == "review"]
    assert review_calls[0][2] == ["drafts/post-9/review/council-editor.json"]


def test_times_are_stable_distinct_and_avoid_taken_minutes(mkws):
    ws = mkws()
    seed(ws, ent(9), ent(10), ent(11))
    (ws / "published").mkdir(exist_ok=True)
    first = bw.build_week(ws, cfg_of(ws), today=TODAY, dry_run=True)
    again = bw.build_week(ws, cfg_of(ws), today=TODAY, dry_run=True)
    assert [i.time for i in first.items] == [i.time for i in again.items], "stable"
    assert len({i.time for i in first.items}) == 3
    assert all(int(i.time[-2:]) % 5 != 0 for i in first.items)
    gaps = [(dt.datetime.fromisoformat(b.scheduled_at) - dt.datetime.fromisoformat(a.scheduled_at)).total_seconds() / 3600
            for a, b in zip(first.items, first.items[1:])]
    assert all(g >= 20.25 for g in gaps), gaps
    # a ledger post on a neighbouring day pushes the slot
    row = {"slug": "old", "state": "posted", "posted_at": f"{d(8)}T12:20:00+00:00"}
    (ws / "published" / "ledger.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    pushed = bw.build_week(ws, cfg_of(ws), today=TODAY, dry_run=True)
    t0 = dt.datetime.fromisoformat(pushed.items[0].scheduled_at)
    assert (t0 - dt.datetime.fromisoformat(row["posted_at"])).total_seconds() / 3600 >= 20.25


def test_a_calendar_time_wins_over_the_spread(mkws):
    ws = mkws()
    seed(ws, ent(9, time="11:11"))
    rep = bw.build_week(ws, cfg_of(ws), today=TODAY, dry_run=True)
    assert rep.items[0].time == "11:11" and rep.items[0].detail == "from the calendar"


def test_one_gate_failure_gets_one_fix_pass(mkws):
    ws = mkws()
    seed(ws, ent(9))
    spy = Spy(ws)
    steps = Steps(gate_results=[(1, "FAIL numbers: 7 bugs"), (0, "PASS")])
    rep = run_build(ws, cfg_of(ws), spy, steps)
    assert rep.items[0].status == "built"
    assert [c[0] for c in spy.calls] == ["build", "fix", "review"]
    assert [s for s in steps.log if s[0] == "gate"] == [("gate", "post-9")] * 2


def test_a_second_gate_failure_fails_the_entry_and_the_next_one_still_builds(mkws):
    ws = mkws()
    seed(ws, ent(9), ent(10))

    class Flaky(Steps):
        def as_steps(self):
            s = super().as_steps()
            real = s.gate

            def gate(slug):
                real(slug)
                return (1, "FAIL numbers: 7 bugs") if slug == "post-9" else (0, "PASS")
            return bw.Steps(s.scaffold, s.render, gate)

    spy = Spy(ws)
    rep = run_build(ws, cfg_of(ws), spy, Flaky())
    assert [i.status for i in rep.items] == ["failed", "built"]
    assert "gate failed" in rep.items[0].detail
    entries = {e["slug"]: e["status"] for e in cal.load(ws)["entries"]}
    assert entries == {"post-9": "planned", "post-10": "built"}
    assert [c[0] for c in spy.calls].count("fix") == 1, "exactly one fix pass for the failing entry"


def test_a_failed_worker_is_an_error_with_a_reason(mkws):
    ws = mkws()
    seed(ws, ent(9))
    rep = run_build(ws, cfg_of(ws), Spy(ws, fail_build={"post-9"}), Steps())
    assert rep.items[0].status == "failed" and "worker crashed" in rep.items[0].detail
    assert cal.find(cal.load(ws), "post-9")["status"] == "planned"
    log = (ws / "work" / "build.log").read_text(encoding="utf-8")
    assert "FAILED post-9" in log


def test_a_review_with_blockers_is_recorded_not_hidden(mkws):
    ws = mkws()
    seed(ws, ent(9))
    rep = run_build(ws, cfg_of(ws), Spy(ws, verdict="blockers"), Steps())
    assert rep.items[0].status == "built" and rep.items[0].verdict == "blockers"
    hist = json.loads((ws / "drafts" / "post-9" / "review.json").read_text(encoding="utf-8"))
    assert hist[-1]["verdict"] == "blockers"


def test_a_second_build_cannot_start_while_one_runs(mkws):
    ws = mkws()
    seed(ws, ent(9))
    from njli.plan.locking import guarded
    with guarded(ws, "build-week", stale_after=3600, wait=0):
        with pytest.raises(bw.BuildError):
            run_build(ws, cfg_of(ws), Spy(ws), Steps())


def test_cleanup_moves_a_failed_build_aside(mkws):
    ws = mkws()
    seed(ws, ent(9))
    run_build(ws, cfg_of(ws), Spy(ws, fail_build={"post-9"}), Steps())
    (ws / "drafts" / "post-9").mkdir(exist_ok=True)
    (ws / "drafts" / "post-9" / "caption.txt").write_text("half", encoding="utf-8")
    moved = bw.cleanup(ws, "post-9")
    assert moved and not (ws / "drafts" / "post-9").exists()
    assert any((ws / "work" / "trash").rglob("caption.txt"))
    assert cal.find(cal.load(ws), "post-9")["status"] == "planned"


def test_cleanup_refuses_posted_and_queued_drafts(mkws):
    ws = mkws()
    (ws / "drafts" / "q").mkdir(parents=True)
    (ws / "drafts" / "q" / "meta.json").write_text(json.dumps({"status": "queued"}), encoding="utf-8")
    with pytest.raises(bw.BuildError):
        bw.cleanup(ws, "q")
    (ws / "published" / "ledger.jsonl").write_text(json.dumps({"slug": "p"}) + "\n", encoding="utf-8")
    with pytest.raises(bw.BuildError):
        bw.cleanup(ws, "p")


def test_days_option_is_validated():
    assert bw.parse_days("8-14") == (8, 14)
    for bad in ("8", "14-8", "a-b", "-1-3"):
        with pytest.raises(bw.BuildError):
            bw.parse_days(bad)


def test_every_shipped_prompt_renders_with_the_values_the_build_supplies(mkws):
    """The templates and the orchestrator agree on the placeholder names."""
    ws = mkws()
    entry = ent(9)
    values = bw.prompt_values(ws, cfg_of(ws), entry, "2026-11-11T10:07:00+00:00")
    values["entry"] = cr.defang(values["entry"])
    for name, extra in (("build", {}), ("fix", {"failure": "x"}),
                        ("review", {"seat": "council-editor", "seat_brief": "b", "audience_regions": "none",
                                    "draft_text": "t"})):
        text = cr.prompt_body(cr.load_prompt(ws, name))
        out = cr.render_prompt(text, {**values, **extra})
        assert "{{" not in out


def test_end_to_end_through_the_real_runner_and_the_fake_cli(mkws, tmp_path):
    """build-week -> run_worker -> sandbox -> fake claude. A hostile edit is reverted and the build still passes."""
    ws = mkws()
    seed(ws, ent(9))
    fake_cmd = wsfix.FAKE_CMD
    prompts = ws / "prompts"
    prompts.mkdir(exist_ok=True)
    (prompts / "build.md").write_text(
        f"# test build\n---\nROOT: {ws}\nSLUG: {{{{slug}}}}\nFAKE: ok,edit_facts\n{{{{entry}}}}\n", encoding="utf-8")
    (prompts / "review.md").write_text(
        f"# test review\n---\nROOT: {ws}\nSLUG: {{{{slug}}}}\nFAKE: review_pass\n{{{{draft_text}}}}\n", encoding="utf-8")
    facts_before = (ws / "research" / "facts.md").read_bytes()
    rep = bw.build_week(ws, cfg_of(ws), today=TODAY, steps=Steps().as_steps(), exe=fake_cmd, notify_user=False)
    assert rep.items[0].status == "built", rep.items[0].detail
    assert (ws / "research" / "facts.md").read_bytes() == facts_before, "the worker's edit was reverted"
    hist = json.loads((ws / "drafts" / "post-9" / "review.json").read_text(encoding="utf-8"))
    assert hist[0]["verdict"] == "pass"
    meta = json.loads((ws / "drafts" / "post-9" / "meta.json").read_text(encoding="utf-8"))
    assert meta["status"] == "draft"
    runner_log = (ws / "data" / "logs" / "runner.jsonl").read_text(encoding="utf-8")
    assert '"restored":1' in runner_log
