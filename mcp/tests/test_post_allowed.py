"""post_allowed: refuses every state that is not Allowed on the board; keeps every posting guard."""
from __future__ import annotations

import datetime as dt
import json

import pytest
from conftest import call, gate_fail

from profile_wrap import limits
from profile_wrap.linkedin import post

NOT_ALLOWED = ["draft", "revising", "hold", "missed", "needs_check", "posted", "rejected", "demo"]


def nothing_sent(env):
    return env.fake.posts == [] and env.ledger_rows() == []


@pytest.mark.parametrize("state", NOT_ALLOWED)
def test_refuses_every_non_allowed_state(env, state):
    env.draft("s1", status=state, allow_history=True)     # even with an old Allow in the history
    for confirm in (False, True):
        err, out = call(env.ctx, "post_allowed", {"slug": "s1", "confirm": confirm})
        assert out["status"] == "refused" and out["kind"] == "not_allowed"
        assert state in out["reason"] or "allowed" in out["reason"]
    assert nothing_sent(env)


def test_refuses_queued_without_a_board_allow(env):
    env.draft("s1", status="queued", allow_history=False)   # status edited by hand
    err, out = call(env.ctx, "post_allowed", {"slug": "s1", "confirm": True})
    assert out["status"] == "refused" and "no board Allow" in out["reason"]
    assert nothing_sent(env)


def test_refuses_queued_when_latest_decision_is_not_allow(env):
    folder = env.draft("s1")
    (folder / "review.json").write_text(json.dumps({"history": [
        {"action": "allow", "to": "queued"}, {"action": "improve", "to": "revising"}]}), encoding="utf-8")
    err, out = call(env.ctx, "post_allowed", {"slug": "s1", "confirm": True})
    assert out["status"] == "refused" and nothing_sent(env)


def test_unknown_or_bad_slug_is_an_error_and_sends_nothing(env):
    for slug in ("nope", "../x", "A B"):
        err, out = call(env.ctx, "post_allowed", {"slug": slug, "confirm": True})
        assert out["status"] == "refused"
    assert nothing_sent(env)


def test_dry_run_default_sends_nothing(env):
    env.draft("ok1")
    err, out = call(env.ctx, "post_allowed", {"slug": "ok1"})
    assert not err and out["status"] == "dry" and out["plan"]["body"]["commentary"]
    assert nothing_sent(env)


def test_allowed_draft_posts_ledger_first_once(env):
    env.draft("ok1")
    err, out = call(env.ctx, "post_allowed", {"slug": "ok1", "confirm": True})
    assert not err and out["status"] == "posted", out
    assert len(env.fake.posts) == 1
    rows = env.ledger_rows()
    assert [r["state"] for r in rows] == ["pending", "posted"]       # ledger first, then complete
    assert rows[0]["automation"]["by"] == "mcp"
    meta = json.loads((env.ws / "drafts" / "ok1" / "meta.json").read_text(encoding="utf-8"))
    assert meta["status"] == "posted"
    # a second call is refused: status is now posted
    err, again = call(env.ctx, "post_allowed", {"slug": "ok1", "confirm": True})
    assert again["status"] == "refused" and len(env.fake.posts) == 1


def test_daily_cap_and_gap(env):
    env.draft("a")
    env.draft("b")
    assert call(env.ctx, "post_allowed", {"slug": "a", "confirm": True})[1]["status"] == "posted"
    err, out = call(env.ctx, "post_allowed", {"slug": "b", "confirm": True})
    assert out["status"] == "refused" and out["kind"] == "daily_cap"
    assert len(env.fake.posts) == 1


def test_gap_guard_from_publish_is_kept(env, monkeypatch):
    # the 1-a-day cap is lifted here so the 20 h gap inside post.publish is what refuses
    from profile_wrap_mcp import core
    monkeypatch.setattr(core, "MAX_POSTS_PER_DAY", 99)
    env.draft("a")
    now = dt.datetime.now(dt.timezone.utc)
    from profile_wrap import ledger
    ledger.append(env.ws, {"slug": "earlier", "state": "pending", "idempotency_key": "k-earlier",
                           "started_at": (now - dt.timedelta(hours=30)).isoformat(timespec="seconds"),
                           "automation": {"mode": "api_click", "by": "human", "api_version": "202609"}})
    ledger.update(env.ws, "k-earlier", state="posted", posted_at=(now - dt.timedelta(hours=5)).isoformat(timespec="seconds"),
                  urn="urn:li:share:1", url="https://www." + "linked" + "in.com/" + "feed/update/urn:li:share:1")
    err, out = call(env.ctx, "post_allowed", {"slug": "a", "confirm": True})
    assert out["status"] == "refused" and "gap guard" in out["reason"], out
    assert env.fake.posts == []


def test_gate_failure_blocks_posting(env):
    env.draft("a")
    env.ctx.gate_fn = gate_fail
    err, out = call(env.ctx, "post_allowed", {"slug": "a", "confirm": True})
    assert out["status"] == "refused" and out["kind"] == "gate"
    assert env.fake.posts == []


def test_pause_and_stop_and_lock_are_kept(env):
    env.draft("a")
    limits.pause(env.ws, "posting", "test")
    assert call(env.ctx, "post_allowed", {"slug": "a", "confirm": True})[1]["status"] == "paused"
    limits.resume(env.ws, "posting")
    post.write_stop(env.ws, "429", 3600)
    out = call(env.ctx, "post_allowed", {"slug": "a", "confirm": True})[1]
    assert out["status"] == "refused" and "stopped" in out["reason"]
    (env.ws / post.STOP_REL).unlink()
    from profile_wrap.locks import FileLock
    lock = FileLock(env.ws / post.LOCK_REL, stale_after=1800, wait=0)
    lock.acquire()
    try:
        out = call(env.ctx, "post_allowed", {"slug": "a", "confirm": True})[1]
        assert out["status"] == "refused" and "in progress" in out["reason"]
    finally:
        lock.release()
    assert env.fake.posts == []


def test_copy_mode_never_sends(env):
    env.set_config(posting={"mode": "copy"})
    env.draft("a")
    out = call(env.ctx, "post_allowed", {"slug": "a", "confirm": True})[1]
    assert out["status"] == "refused" and env.fake.posts == []


def test_only_one_posting_path_in_the_package():
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "profile_wrap_mcp").glob("*.py")
    text = "\n".join(p.read_text(encoding="utf-8") for p in src)
    assert text.count("post.publish(") == 1
    for forbidden in ("create_post", "create_comment", "social_extra", "linkedin.api", "linkedin import api",
                      "socialActions", "urllib", "requests", "httpx"):
        assert forbidden not in text, forbidden
