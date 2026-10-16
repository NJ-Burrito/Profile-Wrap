"""Sign-in, the version table, the selftest probes and the opt-in extra."""
from __future__ import annotations

import datetime as dt
import json
import threading
import time
import urllib.request
from pathlib import Path

import pytest
from conftest import gate_pass

from njli import config as config_mod
from njli import policy
from njli.http import HostPolicy, HttpError, request, token_allowed
from njli.linkedin import api, auth, post, selftest, social_extra, versions

TODAY = dt.date(2026, 10, 16)


# ------------------------------------------------------------------ auth

def _no_token(env):
    (env.cfg_dir / auth.TOKEN_FILE).unlink()


def test_paste_redirect_flow_saves_a_private_token(env):
    _no_token(env)
    auth.save_client(env.cfg_dir, "client-id-1", "client-secret-1")
    seen = {}

    def paste(prompt):
        url = seen["url"]
        state = url.split("state=")[1].split("&")[0]
        return f"http://localhost:8765/callback?code=abc123&state={state}"

    out = []
    rec = auth.run_auth(env.cfg(), paste_redirect=True, input_fn=paste,
                        hp=api.host_policy(env.cfg()), out=lambda t: (out.append(t), seen.update(url=t.split("\n")[-1])))
    assert rec["author"] == "urn:li:person:DEMO000000" and rec["access_token"] == "fake-access-token"
    saved = json.loads((env.cfg_dir / auth.TOKEN_FILE).read_text(encoding="utf-8"))
    assert saved["name"] == "Maya Rivera"
    token_calls = [r for r in env.fake.requests if r["path"].endswith("/accessToken")]
    assert token_calls and "client_secret=client-secret-1" not in str(env.ws)
    assert not any("client-secret-1" in p.read_text(encoding="utf-8", errors="ignore")
                   for p in env.ws.rglob("*") if p.is_file())


def test_state_mismatch_and_errors_are_refused():
    with pytest.raises(auth.AuthError, match="state"):
        auth.parse_redirect("http://localhost:8765/callback?code=x&state=other", "mine")
    with pytest.raises(auth.AuthError, match="refused"):
        auth.parse_redirect("http://localhost:8765/callback?error=access_denied&error_description=no", "mine")
    assert auth.parse_redirect("?code=ok&state=mine", "mine") == "ok"


def test_local_callback_flow_and_timeout(env):
    port = 18765
    redirect = f"http://localhost:{port}/callback"
    state = "st-1"

    def browser():
        time.sleep(0.4)
        for host in ("127.0.0.1",):
            urllib.request.urlopen(f"http://{host}:{port}/callback?code=zz&state={state}", timeout=5).read()

    t = threading.Thread(target=browser)
    t.start()
    assert auth.wait_for_callback(redirect, state, timeout=10) == "zz"
    t.join()
    with pytest.raises(auth.AuthError, match="no answer"):
        auth.wait_for_callback(redirect, state, timeout=1)


def test_token_status_warns_and_expires(env):
    assert auth.token_status(env.cfg_dir)["state"] == "ok"
    tok = auth.load_token(env.cfg_dir)
    tok["expires_at"] = time.time() + 5 * 86400
    auth.save_token(env.cfg_dir, tok)
    assert auth.token_status(env.cfg_dir, 10)["state"] == "warn"
    tok["expires_at"] = time.time() - 10
    auth.save_token(env.cfg_dir, tok)
    assert auth.token_status(env.cfg_dir)["state"] == "expired"
    with pytest.raises(auth.AuthError):
        auth.require_token(env.cfg_dir)
    _no_token(env)
    assert auth.token_status(env.cfg_dir)["state"] == "missing"


def test_missing_client_without_a_terminal_is_one_actionable_error(env, monkeypatch):
    _no_token(env)
    monkeypatch.setattr("sys.stdin", open(__file__, encoding="utf-8"))   # not a TTY
    with pytest.raises(auth.AuthError, match="LINKEDIN_CLIENT_ID"):
        auth.run_auth(env.cfg(), paste_redirect=True)


# ------------------------------------------------------------------ token hosts (unit)

def test_token_allowed_only_for_linkedin_api_and_oauth_hosts():
    hp = HostPolicy()
    assert token_allowed("api.linkedin.com", hp) and token_allowed("www.linkedin.com", hp)
    for host in ("upload.licdn.com", "dms.linkedin.com", "evil.example", "api.linkedin.com.evil.example",
                 "api.apify.com", "127.0.0.1"):
        assert not token_allowed(host, hp), host


def test_request_refuses_a_token_to_an_upload_host(env):
    with pytest.raises(HttpError) as exc:
        request("PUT", "https://upload.licdn.com/mp/1", body=b"x", token="secret", upload=True,
                hp=HostPolicy(demo=True))
    assert exc.value.kind == "blocked_host"
    assert env.fake.requests == []


def test_request_refuses_endpoints_outside_the_allowlist(env):
    with pytest.raises(HttpError) as exc:
        request("GET", "https://api.linkedin.com/v2/me", token="t", linkedin_version="202609",
                hp=HostPolicy(demo=True))
    assert exc.value.kind == "blocked_endpoint" and env.fake.requests == []


# ------------------------------------------------------------------ versions

def test_auto_picks_newest_non_sunset():
    table = versions.load_table()
    assert versions.resolve({"linkedin": {"api_version": "auto"}}, TODAY, table)[0] == "202609"
    late = dt.date(2027, 9, 16)
    with pytest.raises(versions.VersionError):
        versions.resolve({"linkedin": {"api_version": "auto"}}, late, table)


def test_sunset_version_refused_and_near_sunset_warns():
    table = versions.load_table()
    with pytest.raises(versions.VersionError, match="sunset"):
        versions.resolve({"linkedin": {"api_version": "202510"}}, TODAY, table)
    version, warns = versions.resolve({"linkedin": {"api_version": "202511", "sunset_warn_days": 60}},
                                      TODAY, table)
    assert version == "202511" and any("sunsets in" in w for w in warns)
    _v, unknown = versions.resolve({"linkedin": {"api_version": "202701"}}, TODAY, table)
    assert any("not in the dated table" in w for w in unknown)
    with pytest.raises(versions.VersionError, match="YYYYMM"):
        versions.resolve({"linkedin": {"api_version": "latest"}}, TODAY, table)


def test_refresh_adds_unverified_versions_to_the_data_dir_only(env):
    plugin_before = (Path(versions.paths.resource("data", "linkedin-versions.json"))).read_text(encoding="utf-8")
    result = versions.refresh(lambda: "versions 202609 and 202610 are listed; also 201001", TODAY)
    assert result["added"] == ["202610"] and result["written"]
    table = versions.load_table()
    new = [v for v in table["versions"] if v["version"] == "202610"][0]
    assert new["unverified"] is True and new["sunset"] is None
    assert Path(versions.paths.resource("data", "linkedin-versions.json")).read_text(encoding="utf-8") == plugin_before
    assert versions.refresh(lambda: "202610", TODAY)["added"] == []


# ------------------------------------------------------------------ selftest

def test_plain_selftest_never_posts(env):
    result = selftest.run_selftest(env.ws, env.cfg())
    assert result["summary"] == "PASS"
    assert [r["method"] for r in env.fake.requests] == ["GET"]


def test_selftest_comments_is_a_non_posting_probe_closed_route(env):
    result = selftest.run_selftest(env.ws, env.cfg(), "comments")
    probes = [r for r in env.fake.requests if r["path"].startswith("/v2/socialActions/")]
    assert len(probes) == 1 and probes[0]["method"] == "POST"
    assert probes[0]["body"] in ({}, None) and "urn%3Ali%3Aactivity%3A0" in probes[0]["path"] or "activity:0" in probes[0]["path"]
    assert not env.fake.posts and not env.fake.comments
    assert not env.fake.calls("POST", "/rest/")
    rec = social_extra.read_record(env.ws)
    assert rec["result"] == "disabled" and rec["status"] == 403
    assert result["summary"] == "FAIL" and result["probe_only"] is True


def test_selftest_comments_open_route_is_reachable_not_proven(env):
    env.fake.social_actions = "open"
    selftest.run_selftest(env.ws, env.cfg(), "comments")
    assert not env.fake.comments                      # the invalid body created nothing
    rec = social_extra.read_record(env.ws)
    assert rec["result"] == "reachable" and "not proven" in rec["note"]
    assert social_extra.record_fresh(env.ws)
    assert not social_extra.record_fresh(env.ws, now=time.time() + 31 * 86400)


# ------------------------------------------------------------------ the extra

def _enable_extra(env):
    env.set_config(engagement={"comments": {"mode": "api", "daily_cap": 3, "reply_reserve": 2}})
    config_mod.ack(env.ws, "comments_api", policy.ACK_PHRASE, config_dir=env.cfg_dir)
    marker = social_extra.marker_path()
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("{}", encoding="utf-8")


def test_first_comment_is_left_for_the_human_without_the_extra(env):
    env.draft("a", first_comment="More in the notes.")
    out = post.publish(env.ws, "a", env.cfg(), gate_fn=gate_pass)
    assert out.status == "posted" and out.details["first_comment_manual"] is True
    assert not env.fake.comments and not env.fake.calls("POST", "/v2/socialActions")


def test_first_comment_through_the_extra_after_a_fresh_probe(env):
    env.fake.social_actions = "open"
    _enable_extra(env)
    selftest.run_selftest(env.ws, env.cfg(), "comments")
    env.draft("a", first_comment="More in the notes.")
    out = post.publish(env.ws, "a", env.cfg(), gate_fn=gate_pass)
    assert out.status == "posted" and out.details["first_comment_state"] == "posted"
    assert len(env.fake.comments) == 1
    assert env.ledger_rows()[-1]["first_comment_state"] == "posted"
    assert social_extra.comments_today(env.ws) == 1


def test_403_on_the_extra_falls_back_to_draft_and_the_post_stays_live(env):
    _enable_extra(env)
    social_extra.write_record(env.ws, "reachable", 400, "test")
    env.draft("a", first_comment="More in the notes.")
    out = post.publish(env.ws, "a", env.cfg(), gate_fn=gate_pass)        # route is closed: 403
    assert out.status == "posted" and out.details["first_comment_state"] == "failed"
    assert social_extra.read_record(env.ws)["result"] == "disabled"
    assert social_extra.enabled(env.ws, env.cfg())[0] is False
    assert env.meta("a")["status"] == "posted"
