"""An in-process MCP client lists the tools and calls each one against mocks. No real network."""
from __future__ import annotations

import json

from conftest import call, gate_fail, with_client

EXPECTED = {"workspace_status", "calendar_list", "draft_create", "gate_run", "facts_list", "facts_add",
            "review_state", "post_allowed"}


def test_lists_exactly_the_documented_tools(env):
    tools = with_client(env.ctx, lambda c: c.list_tools())
    names = {t.name for t in tools.tools}
    assert names == EXPECTED
    for t in tools.tools:
        assert t.description and len(t.description) > 40, t.name
    # nothing for messages, invitations, comments, or fact verification
    bad = ("dm", "message", "invite", "invitation", "connect", "comment", "verify", "inbox")
    assert not [n for n in names if any(b in n for b in bad)]
    post_tool = next(t for t in tools.tools if t.name == "post_allowed")
    assert "Allow" in post_tool.description and "confirm" in post_tool.description
    ro = {t.name: t.annotations.read_only_hint for t in tools.tools if t.annotations}
    assert ro["workspace_status"] and ro["calendar_list"] and ro["facts_list"] and ro["review_state"]
    assert not ro["post_allowed"]


def test_workspace_status(env):
    env.draft("a", status="draft", allow_history=False)
    env.draft("b")
    err, out = call(env.ctx, "workspace_status")
    assert not err and out["drafts_by_state"] == {"draft": 1, "allowed": 1}
    assert out["posts_today"] == 0 and out["token"]["state"] == "ok"
    assert "tok-secret" not in json.dumps(out)


def test_calendar_list_and_resource(env):
    cal = {"schema_version": 1, "entries": [
        {"date": "2026-10-20", "slug": "x", "title": "X", "lang": "en", "format": "text", "status": "planned"},
        {"date": "2026-10-21", "slug": "y", "title": "Y", "lang": "en", "format": "text", "status": "posted"}]}
    (env.ws / "strategy" / "calendar.json").write_text(json.dumps(cal), encoding="utf-8")
    err, out = call(env.ctx, "calendar_list", {"status": "planned"})
    assert not err and out["count"] == 1 and out["entries"][0]["slug"] == "x"
    res = with_client(env.ctx, lambda c: c.read_resource("pw://calendar"))
    assert json.loads(res.contents[0].text)["count"] == 2


def test_draft_create_uses_provider_and_never_posts(env):
    err, out = call(env.ctx, "draft_create", {"topic": "Why tests come first", "slug": "tests-first"})
    assert not err and out["slug"] == "tests-first" and out["status"] == "draft"
    assert out["gate_preview"] == "PASS"
    meta = json.loads((env.ws / "drafts" / "tests-first" / "meta.json").read_text(encoding="utf-8"))
    assert meta["status"] == "draft" and meta["created_by"] == "profile-wrap-mcp"
    assert "failing test" in (env.ws / "drafts" / "tests-first" / "caption.txt").read_text(encoding="utf-8")
    system, messages = env.provider.calls[0]
    assert "never invent" in system and "Why tests come first" in messages[0]["content"]
    assert env.fake.posts == [] and env.ledger_rows() == []
    # no overwrite
    err2, out2 = call(env.ctx, "draft_create", {"topic": "again", "slug": "tests-first"})
    assert out2["status"] == "refused" and "already exists" in out2["reason"]


def test_draft_create_without_provider_is_refused(env):
    (env.ws / "config" / "providers.json").unlink()
    err, out = call(env.ctx, "draft_create", {"topic": "x"})
    assert out["status"] == "refused" and "no provider" in out["reason"]


def test_gate_run(env):
    env.draft("g1", status="draft", allow_history=False)
    err, out = call(env.ctx, "gate_run", {"slug": "g1"})
    assert not err and out["summary"] == "PASS"
    env.ctx.gate_fn = gate_fail
    err, out = call(env.ctx, "gate_run", {"slug": "g1"})
    assert not err and out["summary"] == "FAIL" and out["fails"]
    err, out = call(env.ctx, "gate_run", {"slug": "../../etc"})
    assert out["status"] == "refused"


def test_facts_add_is_unverified_and_listed(env):
    err, out = call(env.ctx, "facts_add", {"claim": "I ran 12 workshops", "numbers": "12 workshops",
                                           "source": "my calendar"})
    assert not err and out["status"] == "draft" and out["id"]
    err, listed = call(env.ctx, "facts_list", {"status": "draft"})
    assert not err and any(f["id"] == out["id"] and f["status"] == "draft" for f in listed["facts"])
    err, bad = call(env.ctx, "facts_add", {"claim": "", "source": ""})
    assert bad["status"] == "refused"
    # a model cannot pass a status or verify: extra arguments are not accepted
    err, _ = call(env.ctx, "facts_add", {"claim": "c", "source": "s", "status": "verified"})
    err2, listed2 = call(env.ctx, "facts_list", {"status": "verified"})
    assert all(f["claim"] != "c" for f in listed2["facts"])


def test_review_state_and_draft_resources(env):
    env.draft("r1", status="hold", allow_history=False)
    env.draft("r2")
    err, out = call(env.ctx, "review_state", {})
    states = {d["slug"]: d for d in out["drafts"]}
    assert states["r1"]["state"] == "hold" and not states["r1"]["allowed_on_board"]
    assert states["r2"]["state"] == "allowed" and states["r2"]["allowed_on_board"]
    err, one = call(env.ctx, "review_state", {"slug": "r2"})
    assert one["count"] == 1
    listing = with_client(env.ctx, lambda c: c.read_resource("pw://drafts"))
    assert json.loads(listing.contents[0].text)["count"] == 2
    d = with_client(env.ctx, lambda c: c.read_resource("pw://drafts/r2"))
    assert json.loads(d.contents[0].text)["caption"].startswith("A plain sentence")


def test_draft_resource_rejects_path_traversal(env):
    import pytest
    with pytest.raises(Exception):
        with_client(env.ctx, lambda c: c.read_resource("pw://drafts/..%2F..%2Fconfig"))
