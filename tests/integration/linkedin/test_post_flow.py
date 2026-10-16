"""The post flow against the fake server: every format, and every failure path."""
from __future__ import annotations

import datetime as dt
import json
import subprocess
import sys
import textwrap
import time

import pytest
from conftest import GIF, PDF, PNG, ROOT, gate_fail, gate_pass

from njli import ledger, limits
from njli.linkedin import api, post, versions


def run(env, slug="d1", **kw):
    kw.setdefault("gate_fn", gate_pass)
    return post.publish(env.ws, slug, env.cfg(), **kw)


# ------------------------------------------------------------------ each format

def test_text_post_with_ledger_meta_and_report(env):
    env.draft("t1", caption="Hello #testing_tips (more)\n", first_comment="Notes in the thread.")
    out = run(env, "t1")
    assert out.status == "posted" and out.exit_code == 0
    sent = env.fake.posts[0]["body"]
    assert sent["author"] == "urn:li:person:DEMO000000"
    assert sent["commentary"] == "Hello {hashtag|\\#|testing\\_tips} \\(more\\)"
    assert sent["lifecycleState"] == "PUBLISHED" and "content" not in sent
    rows = env.ledger_rows()
    assert [r["state"] for r in rows] == ["pending", "posted"]          # ledger first, then complete
    assert rows[0]["idempotency_key"] == rows[1]["idempotency_key"]
    done = rows[-1]
    assert done["urn"] == out.urn and done["url"].startswith("https://www.linkedin.com/")
    assert done["automation"]["mode"] == "api_click" and done["automation"]["by"] == "human"
    assert ledger.validate_row(done) == []
    meta = env.meta("t1")
    assert meta["status"] == "posted" and meta["urn"] == out.urn
    assert (env.ws / "drafts" / "t1").is_dir()                          # nothing is moved on disk
    assert "t1" in (env.ws / "published" / "REPORT.md").read_text(encoding="utf-8")
    assert out.details["first_comment_manual"] is True                   # no extra: left for the human


def test_single_image_and_gif(env):
    env.draft("i1", fmt="image", assets=[("a.png", PNG)], alt="A chart.")
    assert run(env, "i1").status == "posted"
    content = env.fake.posts[0]["body"]["content"]["media"]
    assert content["altText"] == "A chart." and content["id"].startswith("urn:li:image:")
    assert env.fake.uploads and env.fake.uploads[0]["token"] == ""        # no Bearer to the media host
    env.draft("g1", fmt="gif", assets=[("loop.gif", GIF)], slot_hours_ago=2)
    assert run(env, "g1", now=dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=25)).status == "posted"
    assert env.fake.posts[1]["body"]["content"]["media"]["id"].startswith("urn:li:image:")


def test_multi_image(env):
    env.draft("m1", fmt="slides", assets=[(f"s{i}.png", PNG) for i in range(3)], alt="one\ntwo\nthree")
    assert run(env, "m1").status == "posted"
    images = env.fake.posts[0]["body"]["content"]["multiImage"]["images"]
    assert [i["altText"] for i in images] == ["one", "two", "three"]
    assert len(env.fake.calls("PUT")) == 3


def test_document_pdf(env):
    env.draft("p1", fmt="document", assets=[("deck.pdf", PDF)], extra={"document_title": "The deck"})
    assert run(env, "p1").status == "posted"
    media = env.fake.posts[0]["body"]["content"]["media"]
    assert media["title"] == "The deck" and media["id"].startswith("urn:li:document:")
    assert env.fake.calls("POST", "/rest/documents")


def test_little_text_escapes_arabic_and_underscore_tags():
    got = post.little_text("مرحبا #اختبار_البرمجيات (test) *x*")
    assert got == "مرحبا {hashtag|\\#|اختبار\\_البرمجيات} \\(test\\) \\*x\\*"


# ------------------------------------------------------------------ failures

def test_429_stops_the_run_and_later_runs_honour_it(env):
    env.draft("a")
    env.draft("b", slot_hours_ago=2)
    env.fake.script("posts", {"status": 429, "headers": {"Retry-After": "1200"}})
    out = run(env, "a")
    assert out.status == "stopped"
    assert [r["state"] for r in env.ledger_rows()] == ["pending", "failed"]
    assert env.meta("a")["status"] == "queued"                           # nothing was sent: stays queued
    again = run(env, "b")
    assert again.status == "refused" and again.kind == "guard" and again.exit_code == 0
    assert "stopped" in again.reason
    assert len(env.fake.calls("POST", "/rest/posts")) == 1               # exactly one attempt, no retry


def test_timeout_after_send_gives_needs_check_and_no_repost(env):
    env.draft("a")
    env.fake.script("posts", {"delay": 3.5})                             # client timeout is 2 s
    out = run(env, "a")
    assert out.status == "needs_check"
    assert env.ledger_rows()[-1]["state"] == "needs_check"
    assert env.meta("a")["status"] == "needs_check"
    again = run(env, "a")
    assert again.status == "refused" and again.exit_code == 0
    time.sleep(1.8)                                                        # let the slow handler finish
    assert len(env.fake.calls("POST", "/rest/posts")) == 1


def test_dropped_connection_after_send_is_needs_check(env):
    env.draft("a")
    env.fake.script("posts", {"drop": True})
    assert run(env, "a").status == "needs_check"
    assert len(env.fake.calls("POST", "/rest/posts")) == 1


def test_server_error_is_needs_check_not_a_retry(env):
    env.draft("a")
    env.fake.script("posts", {"status": 503})
    assert run(env, "a").status == "needs_check"
    assert len(env.fake.calls("POST", "/rest/posts")) == 1


def test_rejected_post_holds_the_draft(env):
    env.draft("a")
    env.fake.script("posts", {"status": 422, "body": {"message": "bad commentary"}})
    out = run(env, "a")
    assert out.status == "failed" and env.meta("a")["status"] == "hold"
    assert env.ledger_rows()[-1]["state"] == "failed"


def test_nothing_reachable_is_failed_not_needs_check(env, monkeypatch):
    import urllib.error

    from njli.http import HttpError

    env.draft("a")

    def refused(*a, **k):
        try:
            raise urllib.error.URLError(ConnectionRefusedError("refused"))
        except urllib.error.URLError as exc:
            raise HttpError("network", "cannot reach host") from exc

    monkeypatch.setattr(api, "request", refused)
    out = run(env, "a")
    assert out.status == "failed" and "never left" in out.reason


def test_crash_between_post_and_ledger_completion_recovers_without_repost(env):
    env.draft("a")
    script = textwrap.dedent(f"""
        import os, sys
        sys.path.insert(0, {str(ROOT)!r})
        from njli import config, ledger
        from njli.linkedin import post
        real = ledger.update
        def boom(*a, **k):
            os._exit(9)                       # the process dies right after the POST succeeded
        ledger.update = boom
        cfg = config.load({str(env.ws)!r})
        post.publish({str(env.ws)!r}, "a", cfg, gate_fn=lambda s, w, write=True: {{"summary": "PASS"}})
    """)
    proc = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 9, proc.stderr
    assert len(env.fake.posts) == 1
    assert [r["state"] for r in env.ledger_rows()] == ["pending"]
    out = run(env, "a")                                                  # the next run recovers
    assert out.status == "refused"
    assert env.ledger_rows()[-1]["state"] == "needs_check"
    assert env.meta("a")["status"] == "needs_check"
    assert len(env.fake.posts) == 1                                      # and never reposts


def test_ledger_append_failure_sends_nothing(env, monkeypatch):
    env.draft("a")

    def broken(ws, row):
        raise ledger.LedgerError("disk full")

    monkeypatch.setattr(ledger, "append", broken)
    out = run(env, "a")
    assert out.status == "refused" and "nothing was sent" in out.reason
    assert env.fake.requests == []


def test_ledger_completion_failure_leaves_pending_and_a_recovery_note(env, monkeypatch):
    env.draft("a")
    real = ledger.update

    def failing(ws, key, **changes):
        if changes.get("state") == "posted":
            raise ledger.LedgerError("disk full")
        return real(ws, key, **changes)

    monkeypatch.setattr(ledger, "update", failing)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    out = run(env, "a")
    assert out.status == "needs_check" and out.url
    assert (env.ws / post.RECOVERY_REL).is_file()
    monkeypatch.setattr(ledger, "update", real)
    assert run(env, "a").status == "refused"
    assert len(env.fake.posts) == 1


def test_hostile_upload_host_is_refused_and_the_token_goes_nowhere_else(env):
    env.draft("a", fmt="image", assets=[("a.png", PNG)])
    env.fake.script("init_image", {"upload_host": "evil.example.invalid"})
    out = run(env, "a")
    assert out.status == "failed" and "refusing upload host" in out.reason
    assert not env.fake.calls("PUT") and not env.fake.calls("POST", "/rest/posts")
    for bad in ("http://upload.licdn.com/x", "https://api.linkedin.com/rest/posts",
                "https://www.linkedin.com/x", "https://licdn.com.evil.example/x", "ftp://a.licdn.com/x"):
        with pytest.raises(Exception):
            api.check_upload_url(bad)
    assert api.check_upload_url("https://upload.licdn.com/mp/1") == "upload.licdn.com"


def test_bearer_token_is_sent_only_to_allowlisted_endpoints(env):
    env.draft("a", fmt="image", assets=[("a.png", PNG)])
    assert run(env, "a").status == "posted"
    for req in env.fake.requests:
        if req["method"] == "PUT":
            assert req["token"] == ""
        else:
            assert req["token"] == "Bearer tok-secret-1"
            assert req["path"] in ("/v2/userinfo", "/rest/posts", "/rest/images", "/rest/documents")
            assert req["headers"]["linkedin-version"]
            assert req["headers"]["user-agent"].startswith("nj-linkedin/")


def test_sunset_version_is_refused_before_any_request(env):
    env.draft("a")
    env.set_config(linkedin={"api_version": "202510", "timeout_s": 2})
    out = run(env, "a")
    assert out.status == "refused" and out.exit_code == 1 and "sunset" in out.reason
    assert env.fake.requests == [] and env.ledger_rows() == []


def test_gate_failure_refuses_and_sends_nothing(env):
    env.draft("a")
    out = run(env, "a", gate_fn=gate_fail)
    assert out.status == "refused" and out.kind == "gate" and out.exit_code == 1
    assert env.fake.requests == [] and env.ledger_rows() == []


def test_real_gate_runs_through_the_real_caller(env):
    env.draft("a", caption="A plain sentence about testing.\n")
    out = post.publish(env.ws, "a", env.cfg())                          # default gate, no stub
    assert out.status == "posted", out.reason
    gates = json.loads((env.ws / "drafts" / "a" / "gates.json").read_text(encoding="utf-8"))
    assert gates["summary"] == "PASS"


def test_real_gate_failure_blocks_the_post(env):
    env.draft("a", caption="We shipped 7 bugs fixes this week.\n")
    out = post.publish(env.ws, "a", env.cfg())
    assert out.status == "refused" and out.kind == "gate"
    assert env.fake.requests == []


def test_a_slug_in_the_ledger_is_never_posted_again(env):
    env.draft("a")
    assert run(env, "a").status == "posted"
    env.set_config()
    meta = env.meta("a")
    meta["status"] = "queued"
    (env.ws / "drafts" / "a" / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    later = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=30)
    out = run(env, "a", now=later)
    assert out.status == "refused" and "already in the ledger" in out.reason
    assert len(env.fake.posts) == 1


def test_gap_guard_blocks_a_second_post_within_the_minimum(env):
    env.draft("a")
    env.draft("b", slot_hours_ago=2)
    assert run(env, "a").status == "posted"
    out = run(env, "b")
    assert out.status == "refused" and out.exit_code == 0 and "gap guard" in out.reason
    later = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=21)
    assert run(env, "b", now=later).status == "posted"


def test_gap_floor_is_twelve_hours_even_if_config_says_less(env):
    env.draft("a")
    env.draft("b", slot_hours_ago=2)
    env.set_config(posting={"min_gap_hours": 1})
    assert run(env, "a").status == "posted"
    soon = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=5)
    assert run(env, "b", now=soon).status == "refused"


def test_paused_posting_exits_4(env):
    env.draft("a")
    limits.pause(env.ws, "posting")
    out = run(env, "a")
    assert out.status == "paused" and out.exit_code == 4 and env.fake.requests == []


def test_a_draft_that_is_not_queued_is_refused(env):
    env.draft("a", status="draft")
    out = run(env, "a")
    assert out.status == "refused" and "Allow" in out.reason


def test_needs_check_blocks_then_the_human_resolves_it(env):
    env.draft("a")
    env.fake.script("posts", {"status": 503})
    assert run(env, "a").status == "needs_check"
    row = post.resolve_needs_check(env.ws, "a", posted=True, url="https://www.linkedin.com/feed/update/urn:li:share:DEMO000001/")
    assert row["state"] == "confirmed" and env.meta("a")["status"] == "posted"
    env.draft("b", slot_hours_ago=2)
    env.draft("c", slot_hours_ago=3)
    env.fake.script("posts", {"status": 503})
    later = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=25)
    assert run(env, "b", now=later).status == "needs_check"
    post.resolve_needs_check(env.ws, "b", posted=False)
    assert env.ledger_rows()[-1]["state"] == "failed" and env.meta("b")["status"] == "draft"
    with pytest.raises(ValueError):
        post.resolve_needs_check(env.ws, "c", posted=True)


def test_failed_row_allows_a_later_retry(env):
    env.draft("a")
    env.fake.script("posts", {"status": 422})
    assert run(env, "a").status == "failed"
    meta = env.meta("a")
    meta["status"] = "queued"
    (env.ws / "drafts" / "a" / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    assert run(env, "a").status == "posted"
    assert len(env.fake.calls("POST", "/rest/posts")) == 2


def test_copy_mode_never_calls_the_api(env):
    env.draft("a")
    env.set_config(posting={"mode": "copy"})
    out = run(env, "a")
    assert out.status == "refused" and env.fake.requests == []


def test_version_table_is_consulted(env):
    cfg = env.cfg()
    version, warns = versions.resolve(cfg)
    assert version == "202609"
