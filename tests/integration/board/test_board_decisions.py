"""Allow, Reject, Improve: status rules, the gate, races, the worker guard, the kill switch."""
from __future__ import annotations

import datetime as dt
import json
import threading

import pytest
from board_helpers import FakeRunner, history, make_draft, meta_of, read_decisions

BAD_CAPTION = "This sentence—has an em dash.\n"


def test_allow_runs_the_real_gate_then_queues_and_logs_twice(board, ws):
    srv, c = board
    d = make_draft(ws, "a1", scheduled_at=(dt.datetime.now().astimezone() + dt.timedelta(hours=3)).isoformat())
    code, body = c.decide("a1", "allow")
    assert code == 200 and body["status"] == "queued" and body["warnings"] == []
    assert meta_of(d)["status"] == "queued"
    gates = json.loads((d / "gates.json").read_text())
    assert gates["summary"] == "PASS"
    hist = history(d)
    assert hist[-1]["action"] == "allow" and hist[-1]["to"] == "queued"
    rows = read_decisions(ws)
    assert rows[-1]["slug"] == "a1" and rows[-1]["action"] == "allow"


def test_allow_is_refused_when_the_gate_fails(board, ws):
    srv, c = board
    d = make_draft(ws, "bad1", caption=BAD_CAPTION)
    code, body = c.decide("bad1", "allow")
    assert code == 422 and body["error"] == "gate_failed" and body["fails"]
    assert meta_of(d)["status"] == "draft" and not (d / "review.json").exists()


@pytest.mark.parametrize("status,code", [("revising", 409), ("queued", 409), ("needs_check", 409), ("rejected", 409),
                                         ("demo", 409), ("posted", 409)])
def test_allow_is_refused_from_the_wrong_status(board, ws, status, code):
    srv, c = board
    d = make_draft(ws, "s1", status)
    got, body = c.decide("s1", "allow")
    assert got == code and meta_of(d)["status"] == status
    assert not (d / "gates.json").exists(), "the gate must not even run for a refused status"


def test_demo_and_posted_are_read_only_for_every_decision(board, ws):
    srv, c = board
    make_draft(ws, "d1", "demo")
    make_draft(ws, "p1", "posted", base="published")
    for slug in ("d1", "p1"):
        assert c.decide(slug, "allow")[0] == 409
        assert c.decide(slug, "reject", confirm=True)[0] == 409
        assert c.decide(slug, "improve", "x")[0] == 409
    state = c.get_json("/api/state")[1]
    assert all(p["read_only"] and not any(p["can"].values()) for p in state["posts"])


def test_a_published_copy_wins_over_a_draft_folder_with_the_same_name(board, ws):
    srv, c = board
    make_draft(ws, "twin", "draft")
    make_draft(ws, "twin", "posted", base="published")
    assert c.decide("twin", "allow")[0] == 409


def test_concurrent_allows_have_one_winner_and_the_rest_are_refused(board, ws):
    srv, c = board
    d = make_draft(ws, "race")
    results = []
    barrier = threading.Barrier(8)

    def go():
        barrier.wait()
        results.append(c.decide("race", "allow")[0])

    threads = [threading.Thread(target=go) for _ in range(8)]
    [t.start() for t in threads]
    [t.join(60) for t in threads]
    assert sorted(results) == [200] + [409] * 7, results
    assert meta_of(d)["status"] == "queued"
    assert len([r for r in read_decisions(ws) if r["slug"] == "race" and r["action"] == "allow"]) == 1
    assert len(history(d)) == 1


def test_allow_races_against_reject_leave_exactly_one_outcome(board, ws):
    srv, c = board
    d = make_draft(ws, "race2")
    out = {}

    def allow():
        out["allow"] = c.decide("race2", "allow")[0]

    def reject():
        out["reject"] = c.decide("race2", "reject", confirm=True)[0]

    ts = [threading.Thread(target=allow), threading.Thread(target=reject)]
    [t.start() for t in ts]
    [t.join(60) for t in ts]
    final = meta_of(d)["status"]
    if out["allow"] == 200:
        assert final == "queued" or (final == "rejected" and out["reject"] == 200)
    else:
        assert final == "rejected" and out["reject"] == 200
    assert len(history(d)) >= 1


def test_allow_warns_about_the_slot(board, ws):
    srv, c = board
    make_draft(ws, "none1")
    code, body = c.decide("none1", "allow")
    assert code == 200 and [w["code"] for w in body["warnings"]] == ["no_schedule"]
    old = (dt.datetime.now().astimezone() - dt.timedelta(hours=30)).isoformat()
    make_draft(ws, "late1", scheduled_at=old)
    code, body = c.decide("late1", "allow")
    assert code == 200 and [w["code"] for w in body["warnings"]] == ["past_missed_window"]


def test_council_pass_is_required_when_configured(start, ws):
    cfg = json.loads((ws / "config" / "njli.json").read_text())
    cfg["gate"] = {"require_council_pass": True}
    (ws / "config" / "njli.json").write_text(json.dumps(cfg))
    srv, c = start()
    d = make_draft(ws, "c1")
    assert c.decide("c1", "allow")[1]["error"] == "council_missing"
    (d / "review").mkdir()
    (d / "review" / "council-editor.json").write_text(json.dumps({"seat": "council-editor", "verdict": "revise"}))
    assert c.decide("c1", "allow")[1]["error"] == "council_not_passed"
    (d / "review" / "council-editor.json").write_text(json.dumps({"seat": "council-editor", "verdict": "pass", "blockers": []}))
    assert c.decide("c1", "allow")[0] == 200


def test_a_worker_environment_can_never_allow(board, ws, monkeypatch):
    srv, c = board
    d = make_draft(ws, "w1")
    monkeypatch.setenv("NJLI_WORKER", "1")
    code, body = c.decide("w1", "allow")
    assert code == 403 and body["error"] == "worker_forbidden" and meta_of(d)["status"] == "draft"


def test_reject_needs_confirmation(board, ws):
    srv, c = board
    d = make_draft(ws, "r1")
    code, body = c.decide("r1", "reject")
    assert code == 400 and body["error"] == "confirm_required" and meta_of(d)["status"] == "draft"
    code, body = c.decide("r1", "reject", "not my tone", confirm=True)
    assert code == 200 and meta_of(d)["status"] == "rejected"
    assert history(d)[-1]["note"] == "not my tone"
    assert c.decide("r1", "reject", confirm=True)[0] == 409


def test_bad_inputs(board, ws):
    srv, c = board
    assert c.decide("Not A Slug", "allow")[0] == 400
    assert c.decide("../x", "allow")[0] == 400
    assert c.decide("nope", "allow")[0] == 404
    make_draft(ws, "ok1")
    assert c.decide("ok1", "explode")[0] == 400
    assert c.decide("ok1", "improve", "   ")[0] == 400


# ----------------------------------------------------------------- Improve

def test_improve_runs_the_worker_re_renders_regregates_and_returns_a_draft(start, ws):
    def edit(spec):
        cap = spec.workspace / spec.allow[0] / "caption.txt"
        cap.write_text("Shorter and plainer.\n", encoding="utf-8")
        meta = spec.workspace / spec.allow[0] / "meta.json"
        m = json.loads(meta.read_text())
        m["status"] = "queued"          # a worker tries to queue its own work
        meta.write_text(json.dumps(m))

    runner = FakeRunner(edit)
    renders = []
    srv, c = start(runner=runner, render_fn=lambda slug: (renders.append(slug) or (0, "rendered")))
    d = make_draft(ws, "i1", "queued", fmt="slides", media=True, extra={"assets": ["out/card.png"]})
    (d / "alt.txt").write_text("A plain card showing one sentence.\n", encoding="utf-8")
    code, body = c.decide("i1", "improve", "make it shorter")
    assert code == 200 and body["status"] == "revising"
    assert srv.app.worker.drain(60)
    m = meta_of(d)
    assert m["status"] == "draft", "the worker's attempt to queue must be overridden"
    gates = json.loads((d / "gates.json").read_text())
    # the fake renderer writes nothing, so the slides gate rightly fails on the missing render report:
    # the point here is that the gate ran again after the worker and its verdict was recorded.
    assert m["last_revision_gates"] == ("PASS" if gates["summary"] == "PASS" else "FAIL") and "last_revision" in m
    assert gates["summary"] == "FAIL" and any("render.json" in f for f in gates["fails"])
    assert (d / "caption.txt").read_text() == "Shorter and plainer.\n"
    assert renders == ["i1"]
    spec = runner.calls[0]
    assert spec.tools == "Read,Glob,Grep,Edit,Write" and "Bash" not in spec.tools
    assert "make it shorter" in spec.prompt and spec.allow == ["drafts/i1"]
    actions = [h["action"] for h in history(d)]
    assert actions == ["improve", "revision"]


def test_improve_with_text_format_does_not_render(start, ws):
    renders = []
    srv, c = start(render_fn=lambda slug: (renders.append(slug) or (0, "x")))
    d = make_draft(ws, "i2", fmt="text")
    assert c.decide("i2", "improve", "tweak")[0] == 200
    assert srv.app.worker.drain(60) and renders == []
    assert meta_of(d)["status"] == "draft" and meta_of(d)["last_revision_gates"] == "PASS"


def test_hostile_worker_edits_outside_the_allowlist_are_reverted_and_logged(start, ws):
    (ws / "scripts").mkdir()
    (ws / "videos" / "i3").mkdir(parents=True)
    (ws / "videos" / "i3" / "index.html").write_text("<p>video</p>", encoding="utf-8")
    other = make_draft(ws, "other")
    facts_before = (ws / "research" / "facts.md").read_text(encoding="utf-8")
    other_caption = (other / "caption.txt").read_text()

    def edit(spec):
        (spec.workspace / "research" / "facts.md").write_text("| F99 | invented | 99 |", encoding="utf-8")
        (spec.workspace / "scripts" / "evil.py").write_text("print(1)", encoding="utf-8")
        (spec.workspace / "drafts" / "other" / "caption.txt").write_text("hijacked", encoding="utf-8")
        (spec.workspace / "config" / "njli.json").unlink()
        (spec.workspace / "videos" / "i3" / "index.html").write_text("<p>video v2</p>", encoding="utf-8")

    srv, c = start(runner=FakeRunner(edit))
    d = make_draft(ws, "i3", fmt="gif", extra={"video_project": "videos/i3"})
    cfg_before = (ws / "config" / "njli.json").read_bytes()
    assert c.decide("i3", "improve", "change the video")[0] == 200
    assert srv.app.worker.drain(60)
    assert (ws / "research" / "facts.md").read_text(encoding="utf-8") == facts_before
    assert not (ws / "scripts" / "evil.py").exists()
    assert (other / "caption.txt").read_text() == other_caption
    assert (ws / "config" / "njli.json").read_bytes() == cfg_before
    assert (ws / "videos" / "i3" / "index.html").read_text() == "<p>video v2</p>", "the video project is allowed"
    last = history(d)[-1]
    assert last["action"] == "revision"
    restored = " ".join(last["restored"])
    assert "facts.md" in restored and "evil.py" in restored and "caption.txt" in restored and "njli.json" in restored


def test_a_worker_may_not_edit_a_video_project_outside_videos(start, ws):
    (ws / "brand").mkdir()
    (ws / "brand" / "x.css").write_text("a{}", encoding="utf-8")

    def edit(spec):
        (spec.workspace / "brand" / "x.css").write_text("evil{}", encoding="utf-8")

    srv, c = start(runner=FakeRunner(edit))
    make_draft(ws, "i4", fmt="gif", extra={"video_project": "brand"})
    assert c.decide("i4", "improve", "x")[0] == 200 and srv.app.worker.drain(60)
    assert (ws / "brand" / "x.css").read_text() == "a{}"


def test_a_worker_that_corrupts_meta_json_does_not_lose_the_draft(start, ws):
    def edit(spec):
        (spec.workspace / spec.allow[0] / "meta.json").write_text("{broken", encoding="utf-8")

    srv, c = start(runner=FakeRunner(edit))
    d = make_draft(ws, "i5", extra={"title": "Keep me"})
    c.decide("i5", "improve", "x")
    assert srv.app.worker.drain(60)
    m = meta_of(d)
    assert m["title"] == "Keep me" and m["status"] == "draft"


def test_a_failed_worker_never_leaves_the_post_revising(start, ws):
    srv, c = start(runner=FakeRunner(rc=3))
    d = make_draft(ws, "f1")
    assert c.decide("f1", "improve", "x")[0] == 200 and srv.app.worker.drain(60)
    m = meta_of(d)
    assert m["status"] == "draft" and m["last_revision_gates"] == "FAIL" and "failed" in m["last_revision_error"]
    assert "did not run" in (d / "review-reply.txt").read_text()


def test_a_crashing_runner_is_an_error_not_a_stuck_post(start, ws):
    def boom(spec):
        raise RuntimeError("runner exploded")

    srv, c = start(runner=boom)
    d = make_draft(ws, "f2")
    assert c.decide("f2", "improve", "x")[0] == 200 and srv.app.worker.drain(60)
    assert meta_of(d)["status"] == "draft" and "exploded" in meta_of(d)["last_revision_error"]


def test_improve_without_a_worker_is_a_503_and_changes_nothing(start, ws):
    srv, c = start(runner=None)
    srv.app.worker.runner = None
    d = make_draft(ws, "n1")
    code, body = c.decide("n1", "improve", "x")
    assert code == 503 and body["error"] == "worker_unavailable" and meta_of(d)["status"] == "draft"
    assert c.get_json("/api/state")[1]["worker"] is False


def test_a_restart_recovers_a_post_left_revising(start, ws):
    d = make_draft(ws, "stuck", "revising")
    srv, c = start()
    assert meta_of(d)["status"] == "draft"
    assert history(d)[-1]["action"] == "recovered"


def test_pause_blocks_improve_and_the_kill_switch_round_trips(board, ws):
    srv, c = board
    d = make_draft(ws, "p1")
    assert c.post("/api/pause", {"kind": "all", "paused": True})[0] == 200
    assert (ws / "work" / "PAUSE").exists()
    assert c.get_json("/api/state")[1]["pause"] == ["all"]
    assert c.decide("p1", "improve", "x")[1]["error"] == "paused"
    assert meta_of(d)["status"] == "draft"
    assert c.post("/api/pause", {"kind": "all", "paused": False})[0] == 200
    assert not (ws / "work" / "PAUSE").exists()
    assert c.post("/api/pause", {"kind": "posting", "paused": True})[0] == 200
    assert (ws / "work" / "PAUSE.posting").exists()
    assert c.post("/api/pause", {"kind": "bogus", "paused": True})[0] == 400


def test_the_guard_does_not_revert_a_click_made_while_a_job_runs(start, ws):
    (ws / "engage").mkdir()
    rows = {"schema_version": 1, "items": [{"urn": "u1", "kind": "comment", "text": "hello there", "status": "pending"}]}
    (ws / "engage" / "pending.json").write_text(json.dumps(rows))
    gate = threading.Event()
    done = threading.Event()

    def edit(spec):
        gate.set()
        done.wait(30)

    srv, c = start(runner=FakeRunner(edit))
    make_draft(ws, "g1")
    c.decide("g1", "improve", "x")
    assert gate.wait(30)
    item = c.get_json("/api/pending")[1]["pending"][0]["id"]
    assert c.post("/api/pending-done", {"id": item, "action": "done"})[0] == 200
    done.set()
    assert srv.app.worker.drain(60)
    saved = json.loads((ws / "engage" / "pending.json").read_text())
    assert saved["items"][0]["status"] == "posted"
