"""The guided Connect LinkedIn flow: every step's own check, every refusal, both languages."""
from __future__ import annotations

import datetime as dt
import socket
import threading
import time

import pytest

from profile_wrap import config, i18n
from profile_wrap.linkedin import auth, connect

SECRET = "Zq8Lm2Zq8Lm2Zq8L"
CLIENT_ID = "86abcdEF12gh34"
ALL_SCOPES = "openid profile w_member_social"


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def token(cfg, days=60, scopes=ALL_SCOPES, name="Sam Example"):
    now = time.time()
    auth.save_token(auth.secrets_dir(cfg), {"access_token": "tok", "expires_at": now + days * 86400,
                                            "author": "urn:li:person:X", "name": name, "scopes": scopes, "created": now})


def by_id(rows):
    return {r["id"]: r for r in rows}


def steps_of(cfg, free=True):
    return connect.steps(cfg, port_free_fn=lambda p: free)


# ------------------------------------------------------------------ refusals

@pytest.mark.parametrize("uri,code", [
    ("https://localhost:8765/callback", "res.redirect.scheme"),
    ("http://example.com:8765/callback", "res.redirect.host"),
    ("http://localhost/callback", "res.redirect.port"),
    ("http://localhost:8765", "res.redirect.path"),
    ("", "res.redirect.scheme"),
])
def test_a_bad_redirect_address_is_refused_with_its_own_message(uri, code):
    with pytest.raises(connect.ConnectError) as err:
        connect.parse_redirect(uri)
    assert err.value.code == code


def test_a_good_redirect_address_is_parsed():
    assert connect.parse_redirect("http://localhost:8765/callback")["port"] == 8765


@pytest.mark.parametrize("cid,code", [
    ("", "res.creds.id_empty"), (None, "res.creds.id_empty"), ("has space 1234", "res.creds.id_format"),
    ("short", "res.creds.id_format"), ("x" * 41, "res.creds.id_format")])
def test_a_bad_client_id_is_refused(cid, code):
    with pytest.raises(connect.ConnectError) as err:
        connect.check_client_id(cid)
    assert err.value.code == code


@pytest.mark.parametrize("secret,code", [
    ("", "res.creds.secret_empty"), (None, "res.creds.secret_empty"), ("has a space 123", "res.creds.secret_format"),
    ("short", "res.creds.secret_format")])
def test_a_bad_client_secret_is_refused_and_never_echoed(secret, code):
    with pytest.raises(connect.ConnectError) as err:
        connect.check_client_secret(secret)
    assert err.value.code == code
    if secret:
        assert secret not in str(err.value)


def test_refused_credentials_write_nothing(cfg):
    for cid, secret in (("bad id", SECRET), (CLIENT_ID, "no good"), ("", ""), (CLIENT_ID, "")):
        with pytest.raises(connect.ConnectError):
            connect.save_credentials(cfg, cid, secret)
    assert not (auth.secrets_dir(cfg) / auth.CLIENT_FILE).exists()


def test_valid_credentials_are_stored_the_existing_way(cfg):
    connect.save_credentials(cfg, f" {CLIENT_ID} ", SECRET)
    assert auth.read_client(auth.secrets_dir(cfg)) == (CLIENT_ID, SECRET)


@pytest.mark.parametrize("key", ["password", "Password", " passwd ", "li_password", "linkedin_password", "pwd"])
def test_a_login_password_in_any_request_is_refused(key):
    with pytest.raises(connect.ConnectError) as err:
        connect.refuse_password({"client_id": CLIENT_ID, key: "hunter22"})
    assert err.value.code == "res.creds.password_refused"
    assert "hunter22" not in str(err.value)


def test_a_request_without_a_password_passes():
    connect.refuse_password({"client_id": CLIENT_ID, "key": SECRET})


# ------------------------------------------------------------------ the five checks

def test_a_fresh_start_says_what_to_do_at_each_step(cfg):
    assert [r["id"] for r in steps_of(cfg)] == list(connect.STEP_IDS)
    rows = by_id(steps_of(cfg))
    assert rows["app"]["state"] == "todo" and rows["products"]["state"] == "wait"
    assert rows["redirect"]["state"] == "done" and rows["credentials"]["state"] == "todo"
    assert rows["signin"]["code"] == "res.signin.blocked"


def test_a_busy_port_is_a_redirect_fix_not_a_silent_failure(cfg):
    rows = by_id(steps_of(cfg, free=False))
    assert rows["redirect"]["state"] == "fix" and rows["redirect"]["code"] == "res.redirect.busy"
    assert rows["redirect"]["params"]["port"] == 8765


def test_the_port_check_sees_a_real_listener():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(1)
    try:
        assert connect.port_free(s.getsockname()[1]) is False
    finally:
        s.close()


def test_the_config_must_ask_for_the_scopes_the_products_grant(cfg):
    cfg["linkedin"]["scopes"] = ["openid", "profile"]
    row = by_id(steps_of(cfg))["products"]
    assert row["state"] == "fix" and row["code"] == "res.products.config_scopes"
    assert "w_member_social" in row["params"]["missing"]


def test_credentials_steps_follow_what_is_saved(cfg):
    connect.save_credentials(cfg, CLIENT_ID, SECRET)
    rows = by_id(steps_of(cfg))
    assert rows["app"]["state"] == "done" and rows["credentials"]["state"] == "done"
    assert rows["signin"]["code"] == "res.signin.todo"


def test_a_client_id_in_a_bad_shape_is_flagged_from_the_file(cfg):
    auth.save_client(auth.secrets_dir(cfg), "bad id!", SECRET)
    rows = by_id(steps_of(cfg))
    assert rows["credentials"]["code"] == "res.creds.id_format" and rows["app"]["state"] == "fix"


def test_a_good_token_finishes_steps_two_and_five(cfg):
    connect.save_credentials(cfg, CLIENT_ID, SECRET)
    token(cfg)
    rows = by_id(steps_of(cfg))
    assert rows["products"]["state"] == "done" and rows["signin"]["state"] == "done"
    assert rows["signin"]["params"]["name"] == "Sam Example" and rows["signin"]["params"]["days"] >= 59
    assert connect.overview(cfg, port_free_fn=lambda p: True)["ready"] is True


def test_a_token_missing_a_product_names_the_missing_permission(cfg):
    connect.save_credentials(cfg, CLIENT_ID, SECRET)
    token(cfg, scopes="openid profile")
    row = by_id(steps_of(cfg))["products"]
    assert row["state"] == "fix" and row["code"] == "res.products.missing_scope"
    assert row["params"]["missing"] == "w_member_social"


def test_an_expired_or_nearly_expired_token_asks_for_a_new_sign_in(cfg):
    connect.save_credentials(cfg, CLIENT_ID, SECRET)
    token(cfg, days=-1)
    assert by_id(steps_of(cfg))["signin"]["code"] == "res.signin.expired"
    token(cfg, days=3)
    assert by_id(steps_of(cfg))["signin"]["code"] == "res.signin.soon"


def test_the_overview_never_carries_the_secret(cfg):
    connect.save_credentials(cfg, CLIENT_ID, SECRET)
    token(cfg)
    assert SECRET not in repr(connect.overview(cfg, port_free_fn=lambda p: True))


# ------------------------------------------------------------------ the 60-day date

def test_the_reauth_date_is_the_token_expiry_and_the_warning_start(cfg):
    token(cfg, days=60)
    info = connect.reauth_info(cfg)
    want = (dt.datetime.now() + dt.timedelta(days=60)).date()
    assert info["expires_on"] in (want.isoformat(), (want - dt.timedelta(days=1)).isoformat())
    expires = dt.date.fromisoformat(info["expires_on"])
    assert info["warn_from"] == (expires - dt.timedelta(days=cfg["linkedin"]["token_warn_days"])).isoformat()
    assert info["lifetime_days"] == 60


def test_before_the_first_sign_in_there_is_no_date_yet(cfg):
    info = connect.reauth_info(cfg)
    assert info["expires_on"] is None and info["state"] == "missing"


# ------------------------------------------------------------------ opting in to API posting

def test_api_posting_is_refused_without_a_sign_in(first_run_ws):
    with pytest.raises(connect.ConnectError) as err:
        connect.enable_api_posting(first_run_ws)
    assert err.value.code == "api.refused.token"
    assert config.load(first_run_ws)["posting"]["mode"] == "copy"


def test_api_posting_is_refused_on_an_expired_token(first_run_ws, cfg):
    token(cfg, days=-2)
    with pytest.raises(connect.ConnectError):
        connect.enable_api_posting(first_run_ws)
    assert config.load(first_run_ws)["posting"]["mode"] == "copy"


def test_api_posting_is_refused_when_the_token_lacks_the_posting_scope(first_run_ws, cfg):
    token(cfg, scopes="openid profile")
    with pytest.raises(connect.ConnectError) as err:
        connect.enable_api_posting(first_run_ws)
    assert err.value.code == "res.products.missing_scope"


def test_opting_in_gives_click_mode_never_scheduled_and_can_be_undone(first_run_ws, cfg):
    token(cfg)
    assert connect.enable_api_posting(first_run_ws) == "api_click"
    assert config.load(first_run_ws)["posting"]["mode"] == "api_click"
    assert connect.back_to_copy_mode(first_run_ws) == "copy"
    assert config.load(first_run_ws)["posting"]["mode"] == "copy"


# ------------------------------------------------------------------ error mapping

@pytest.mark.parametrize("text,code", [
    ("LinkedIn refused the request: unauthorized_scope_error", "res.signin.error.scope"),
    ("redirect_uri does not match", "res.signin.error.redirect"),
    ("LinkedIn answered 401 to the token request: invalid_client", "res.signin.error.client"),
    ("no answer from the browser within 180 seconds", "res.signin.error.timeout"),
    ("cannot listen on port 8765 for the redirect", "res.redirect.busy"),
    ("something else", "res.signin.error.other")])
def test_known_failures_get_a_plain_explanation(text, code):
    assert connect.explain_error(text) == code


# ------------------------------------------------------------------ the desktop sign-in session

def session(cfg, wait, complete, timeout=5):
    cfg["linkedin"]["redirect_uri"] = f"http://localhost:{free_port()}/callback"
    return connect.SignIn(cfg, wait=wait, complete=complete, timeout=timeout, open_browser=lambda url: None)


def ok_complete(cfg):
    def complete(c, code, cid, secret, redirect, hp=None, version=None):
        token(cfg)
        return auth.load_token(auth.secrets_dir(cfg))
    return complete


def test_signin_is_refused_until_the_credentials_are_saved(cfg):
    s = session(cfg, lambda *a, **k: "code", ok_complete(cfg))
    with pytest.raises(connect.ConnectError) as err:
        s.start()
    assert err.value.code == "res.signin.blocked" and s.state == "idle"


def test_signin_is_refused_on_a_bad_redirect_or_a_busy_port(cfg):
    connect.save_credentials(cfg, CLIENT_ID, SECRET)
    s = connect.SignIn(cfg, wait=lambda *a, **k: "c", complete=ok_complete(cfg))
    cfg["linkedin"]["redirect_uri"] = "https://localhost:1/callback"
    with pytest.raises(connect.ConnectError) as err:
        s.start()
    assert err.value.code == "res.redirect.scheme"
    blocker = socket.socket()
    blocker.bind(("127.0.0.1", 0))
    blocker.listen(1)
    try:
        cfg["linkedin"]["redirect_uri"] = f"http://localhost:{blocker.getsockname()[1]}/callback"
        with pytest.raises(connect.ConnectError) as err:
            s.start()
        assert err.value.code == "res.redirect.busy"
    finally:
        blocker.close()


def test_a_successful_signin_ends_done_with_the_name_and_days(cfg):
    connect.save_credentials(cfg, CLIENT_ID, SECRET)
    seen = {}

    def wait(redirect, state, timeout, on_ready=None):
        seen["state"] = state
        on_ready()
        return "the-code"

    s = session(cfg, wait, ok_complete(cfg))
    opened = []
    s.open_browser = opened.append
    snap = s.start()
    assert snap["state"] == "waiting" and "client_id=" + CLIENT_ID in snap["url"] and SECRET not in snap["url"]
    s.join()
    assert s.state == "done" and s.params["name"] == "Sam Example" and s.params["days"] >= 59
    assert opened and opened[0] == s.url and seen["state"] in s.url


def test_a_failed_signin_is_explained_and_the_secret_is_redacted(cfg):
    connect.save_credentials(cfg, CLIENT_ID, SECRET)

    def complete(*a, **k):
        raise auth.AuthError(f"LinkedIn answered 400: unauthorized_scope_error for {SECRET}")

    s = session(cfg, lambda *a, **k: "c", complete)
    s.start()
    s.join()
    assert s.state == "error" and s.code == "res.signin.error.scope"
    assert SECRET not in repr(s.snapshot())


def test_a_second_signin_while_one_waits_is_refused(cfg):
    connect.save_credentials(cfg, CLIENT_ID, SECRET)
    gate = threading.Event()

    def wait(*a, **k):
        gate.wait(5)
        return "c"

    s = session(cfg, wait, ok_complete(cfg))
    s.start()
    try:
        with pytest.raises(connect.ConnectError) as err:
            s.start()
        assert err.value.code == "res.signin.busy"
    finally:
        gate.set()
        s.join()


# ------------------------------------------------------------------ the terminal walk-through

def script(answers):
    prompts = []
    it = iter(answers)

    def input_fn(prompt=""):
        prompts.append(prompt)
        return next(it)

    return input_fn, prompts


def fake_signin(cfg):
    def run(c, **kw):
        token(cfg)
        return auth.load_token(auth.secrets_dir(cfg))
    return run


def walk(cfg, answers, **kw):
    lines = []
    input_fn, prompts = script(answers)
    kw.setdefault("sign_in", fake_signin(cfg))
    kw.setdefault("port_free_fn", lambda p: True)
    kw.setdefault("secret_fn", lambda p: SECRET)
    code = connect.run_guided(cfg, input_fn=input_fn, out=lines.append, **kw)
    return code, "\n".join(lines), prompts


def test_the_guided_walk_goes_through_all_five_steps_and_ends_signed_in(cfg):
    code, text, prompts = walk(cfg, ["", "", "", CLIENT_ID, "", ""])
    assert code == 0
    for n in range(1, 6):
        assert f"Step {n} of 5" in text
    assert cfg["linkedin"]["redirect_uri"] in text and "sign in again by" in text.lower()
    assert SECRET not in text
    assert not any("password" in p.lower() for p in prompts)
    assert auth.read_client(auth.secrets_dir(cfg)) == (CLIENT_ID, SECRET)


def test_the_guided_walk_in_arabic_speaks_arabic(cfg):
    code, text, _ = walk(cfg, ["", "", "", CLIENT_ID, "", ""], lang="ar")
    assert code == 0 and i18n.t("step.signin.title", "ar") in text and i18n.t("connect.nopassword", "ar") in text


def test_the_guided_walk_stops_at_the_first_failed_check_and_says_why(cfg):
    code, text, _ = walk(cfg, ["", "", ""], port_free_fn=lambda p: False)
    assert code == 1 and "Port 8765 is busy" in text
    assert not (auth.secrets_dir(cfg) / auth.CLIENT_FILE).exists()


def test_the_guided_walk_refuses_a_bad_client_id_and_stores_nothing(cfg):
    code, text, _ = walk(cfg, ["", "", "", "not a valid id"])
    assert code == 1 and "letters and digits" in text
    assert not (auth.secrets_dir(cfg) / auth.CLIENT_FILE).exists()


def test_q_stops_the_walk(cfg):
    code, text, _ = walk(cfg, ["q"])
    assert code == 1 and "Stopped" in text


def test_a_failed_signin_in_the_terminal_is_explained(cfg):
    def boom(c, **kw):
        raise auth.AuthError("LinkedIn refused the request: unauthorized_scope_error")

    code, text, _ = walk(cfg, ["", "", "", CLIENT_ID, ""], sign_in=boom)
    assert code == 1 and "Add both products" in text


def test_the_walk_can_opt_in_to_api_posting_at_the_end(first_run_ws, cfg):
    code, _, _ = walk(cfg, ["", "", "", CLIENT_ID, "", "y"], ws=first_run_ws)
    assert code == 0 and config.load(first_run_ws)["posting"]["mode"] == "api_click"


def test_the_walk_stays_in_copy_mode_when_the_user_declines(first_run_ws, cfg):
    walk(cfg, ["", "", "", CLIENT_ID, "", "n"], ws=first_run_ws)
    assert config.load(first_run_ws)["posting"]["mode"] == "copy"


def test_auth_connect_needs_a_terminal(first_run_ws, capsys):
    from profile_wrap import cli

    code = cli.main(["auth", "connect", "--workspace", str(first_run_ws)])
    err = capsys.readouterr().err
    assert code == 1 and "needs a terminal" in err
    code = cli.main(["auth", "connect", "--lang", "ar", "--workspace", str(first_run_ws)])
    assert code == 1 and i18n.t("cli.needs_tty", "ar") in capsys.readouterr().err
