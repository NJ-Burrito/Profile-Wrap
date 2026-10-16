"""The commands through ``profile_wrap.cli.main`` in this process (so coverage sees them), plus edge cases."""
from __future__ import annotations

import datetime
import json
import threading
import time
import urllib.request

import pytest
from conftest import GIF, PNG, gate_pass

from profile_wrap import cli, limits
from profile_wrap.linkedin import api, auth, due, post, selftest, social_extra, versions


def main(env, *args):
    return cli.main([*args, "--workspace", str(env.ws)])


def test_auth_check_and_status_and_versions(env, capsys):
    assert main(env, "auth", "check") == 0
    assert "token: ok" in capsys.readouterr().out
    assert main(env, "auth", "check", "--json") == 0
    assert json.loads(capsys.readouterr().out)["state"] == "ok"
    (env.cfg_dir / auth.TOKEN_FILE).unlink()
    assert main(env, "auth", "check") == 1
    capsys.readouterr()
    assert main(env, "status") == 0
    assert "posting mode" in capsys.readouterr().out
    assert main(env, "api-versions") == 0
    assert "selected: 202609" in capsys.readouterr().out
    env.set_config(linkedin={"api_version": "202510"})
    assert main(env, "api-versions") == 1


def test_selftest_command(env, capsys):
    assert main(env, "selftest") == 0
    assert "selftest: PASS" in capsys.readouterr().out
    assert main(env, "selftest", "comments") == 1                  # closed route: 403
    out = capsys.readouterr().out
    assert "comments probe" in out and "nothing was posted" in out
    assert main(env, "selftest", "--json") == 0
    assert json.loads(capsys.readouterr().out)["summary"] == "PASS"


def test_post_command_paths(env, capsys):
    env.draft("a", first_comment="Notes.", fmt="image", assets=[("p.png", PNG)])
    assert main(env, "post", "a", "--dry") == 0
    assert "--- media ---" in capsys.readouterr().out
    assert main(env, "post", "a", "--dry", "--json") == 0
    assert json.loads(capsys.readouterr().out)["format"] == "image"
    assert main(env, "post", "nope", "--dry") == 1
    assert main(env, "post", "a", "--resolve") == 2
    assert main(env, "post", "a", "--resolve", "--posted") == 1    # not waiting for a check
    env.set_config(posting={"mode": "copy"})
    assert main(env, "post", "a", "--now") == 0                    # copy mode: only the block
    assert "post this by hand" in capsys.readouterr().out
    assert env.fake.requests == []


def test_post_now_and_resolve_through_the_command(env, capsys):
    env.draft("a")
    env.fake.script("posts", {"status": 502})
    assert main(env, "post", "a", "--now") == 1
    assert "NEEDS CHECK" in capsys.readouterr().err
    assert main(env, "status") == 0
    assert "NEEDS CHECK a" in capsys.readouterr().out
    assert main(env, "post", "a", "--resolve", "--posted", "--url",
                "https://www.linkedin.com/feed/update/urn:li:share:DEMO000005/") == 0
    assert env.meta("a")["status"] == "posted"
    capsys.readouterr()
    assert main(env, "post", "a", "--now", "--json") == 0          # status posted: guard refusal
    assert json.loads(capsys.readouterr().out)["status"] == "refused"


def test_due_command_json(env, capsys):
    env.scheduled()
    env.draft("a")
    assert main(env, "due", "--json") == 0
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "posted" and data["url"].startswith("https://www.linkedin.com/")
    limits.pause(env.ws, "posting")
    assert main(env, "due") == 4


def test_auth_command_reports_one_line_without_a_terminal(env, capsys, monkeypatch):
    (env.cfg_dir / auth.TOKEN_FILE).unlink()
    monkeypatch.setattr("sys.stdin", open(__file__, encoding="utf-8"))
    assert main(env, "auth", "--paste-redirect") == 1
    assert "LINKEDIN_CLIENT_ID" in capsys.readouterr().err


def test_auth_with_a_browser_callback_end_to_end(env):
    (env.cfg_dir / auth.TOKEN_FILE).unlink()
    auth.save_client(env.cfg_dir, "cid", "csecret")
    env.set_config(linkedin={"redirect_uri": "http://localhost:18771/callback", "timeout_s": 2})
    opened = []

    def fake_browser(url):
        opened.append(url)
        state = url.split("state=")[1].split("&")[0]

        def go():
            time.sleep(0.3)
            urllib.request.urlopen(f"http://127.0.0.1:18771/callback?code=c1&state={state}", timeout=5).read()
        threading.Thread(target=go, daemon=True).start()

    rec = auth.run_auth(env.cfg(), open_browser=fake_browser, hp=api.host_policy(env.cfg()),
                        callback_timeout=15, out=lambda t: None)
    assert opened and rec["author"].startswith("urn:li:person:")
    assert auth.token_status(env.cfg_dir)["state"] == "ok"


def test_prompt_client_stores_secrets_in_the_config_dir(env):
    (env.cfg_dir / auth.CLIENT_FILE).unlink(missing_ok=True)
    cid, secret = auth.prompt_client(env.cfg_dir, input_fn=lambda p: "id-9", secret_fn=lambda p: "sec-9")
    assert (cid, secret) == ("id-9", "sec-9")
    assert auth.read_client(env.cfg_dir) == ("id-9", "sec-9")
    with pytest.raises(auth.AuthError):
        auth.prompt_client(env.cfg_dir, input_fn=lambda p: "", secret_fn=lambda p: "")


def test_token_errors_are_actionable(env):
    (env.cfg_dir / auth.TOKEN_FILE).write_text("{bad", encoding="utf-8")
    with pytest.raises(auth.AuthError, match="profile-wrap auth"):
        auth.load_token(env.cfg_dir)
    (env.cfg_dir / auth.TOKEN_FILE).write_text('{"access_token": "x"}', encoding="utf-8")
    with pytest.raises(auth.AuthError, match="incomplete"):
        auth.load_token(env.cfg_dir)
    env.fake.script("token", {"status": 400, "body": {"error": "invalid_grant"}})
    with pytest.raises(auth.AuthError, match="400"):
        auth.exchange_code("c", "i", "s", "http://localhost:8765/callback", hp=api.host_policy(env.cfg()))


def test_userinfo_rejection_and_selftest_failures(env):
    client = api.Client("tok-secret-1", "202609", hp=api.host_policy(env.cfg()), timeout=2)
    env.fake.script("userinfo", {"status": 401})
    with pytest.raises(api.ApiError, match="401"):
        client.userinfo()
    env.fake.script("userinfo", {"status": 403, "body": {"m": 1}})
    with pytest.raises(api.ApiError):
        client.userinfo()
    env.fake.sub = "OTHER"
    result = selftest.run_selftest(env.ws, env.cfg())
    assert result["summary"] == "FAIL"
    env.set_config(linkedin={"api_version": "202510", "timeout_s": 2})
    assert selftest.run_selftest(env.ws, env.cfg())["summary"] == "FAIL"
    (env.cfg_dir / auth.TOKEN_FILE).unlink()
    assert selftest.run_selftest(env.ws, env.cfg(), "comments")["summary"] == "FAIL"


def test_draft_problems_are_refused_before_the_ledger(env):
    env.draft("big", caption="x" * 3100)
    out = post.publish(env.ws, "big", env.cfg(), gate_fn=gate_pass)
    assert out.status == "refused" and "limit" in out.reason and env.ledger_rows() == []
    env.draft("none", caption="")
    assert "empty" in post.publish(env.ws, "none", env.cfg(), gate_fn=gate_pass).reason
    env.draft("pdfs", fmt="document", assets=[("a.png", PNG)])
    assert post.publish(env.ws, "pdfs", env.cfg(), gate_fn=gate_pass).status == "refused"
    env.draft("miss", fmt="image", extra={"assets": ["gone.png"]})
    assert "not found" in post.publish(env.ws, "miss", env.cfg(), gate_fn=gate_pass).reason
    assert "not found" in post.publish(env.ws, "ghost", env.cfg(), gate_fn=gate_pass).reason
    assert env.fake.requests == []


def test_403_on_post_holds_and_writes_a_day_long_stop(env):
    env.draft("a")
    env.fake.script("posts", {"status": 403})
    out = post.publish(env.ws, "a", env.cfg(), gate_fn=gate_pass)
    assert out.status == "failed" and env.meta("a")["status"] == "hold"
    assert post.stop_active(env.ws)
    assert "stopped" in due.run_due(env.ws, env.cfg()).reason


def test_201_without_a_post_id_is_needs_check(env):
    env.draft("a")
    env.fake.script("posts", {"status": 201, "body": None})
    assert post.publish(env.ws, "a", env.cfg(), gate_fn=gate_pass).status == "needs_check"


def test_version_report_and_social_extra_edges(env):
    rep = versions.report(env.cfg())
    assert rep["ok"] and rep["selected"] == "202609"
    assert versions.classify("209901", versions.load_table(), datetime.date(2026, 10, 16))[0] == "unknown"
    assert social_extra.enabled(env.ws, env.cfg()) == (False, "the comments-api extra is not installed")
    assert social_extra.maybe_first_comment(env.ws, env.cfg(), None, "urn:li:share:1", "", "x") == ("none", "")


def test_gif_post_via_the_cli_with_the_real_gate_is_refused_without_alt_text(env, capsys):
    env.draft("g", fmt="gif", assets=[("l.gif", GIF)], alt=None)
    assert main(env, "post", "g", "--now") == 1
    assert env.fake.requests == []
