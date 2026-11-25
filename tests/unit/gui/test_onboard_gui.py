"""The app's copy-mode first run and the Connect LinkedIn screen, through the real HTTP entry point."""
from __future__ import annotations

import json
import socket
import time

import pytest
from gui_helpers import Client

from profile_wrap import config, init_wizard
from profile_wrap.gui.server import GuiServer
from profile_wrap.linkedin import auth, connect, post

SECRET = "Zq8Lm2Zq8Lm2Zq8L"
CLIENT_ID = "86abcdEF12gh34"
ANSWERS = {"schema_version": 1, "where": {"profile_id": "app-first-run"},
           "who": {"name": "Sam Example", "languages": ["en", "ar"], "timezone": "Europe/Lisbon", "goal": "authority"}}
NO_DOCTOR = lambda _w: {"summary": {"pass": 1, "warn": 0, "fail": 0}, "checks": []}  # noqa: E731


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def save_token(cfg, days=60, scopes="openid profile w_member_social"):
    now = time.time()
    auth.save_token(auth.secrets_dir(cfg), {"access_token": "tok", "expires_at": now + days * 86400,
                                            "author": "urn:li:person:X", "name": "Sam Example",
                                            "scopes": scopes, "created": now})


@pytest.fixture()
def first_ws(tmp_path):
    ws = init_wizard.init_workspace(tmp_path / "first", json.loads(json.dumps(ANSWERS)), git=False)["workspace"]
    from pathlib import Path
    ws = Path(ws)
    config.set_value(ws, "linkedin.redirect_uri", json.dumps(f"http://localhost:{free_port()}/callback"))
    return ws


@pytest.fixture()
def opened():
    return []


@pytest.fixture()
def app(first_ws, opened):
    def factory(cfg, open_browser=None):
        def wait(redirect, state, timeout, on_ready=None):
            on_ready()
            return "the-code"

        def complete(c, code, cid, secret, redirect, hp=None, version=None):
            save_token(config.load(first_ws))
            return auth.load_token(auth.secrets_dir(config.load(first_ws)))
        return connect.SignIn(cfg, wait=wait, complete=complete, open_browser=open_browser, timeout=5)

    server = GuiServer(first_ws, doctor_fn=NO_DOCTOR, signin_factory=factory, open_browser=opened.append).start_background()
    yield Client(server), server
    server.shutdown()


def cfg_of(ws):
    return config.load(ws)


# ------------------------------------------------------------------ copy mode is the first run

def test_a_new_workspace_opens_the_app_in_copy_mode(app):
    client, _ = app
    status, home = client.get("/api/home")
    assert status == 200 and home["posting_mode"] == "copy" and home["ui_language"] == "en"


def test_the_home_script_shows_the_copy_steps_only_in_copy_mode(app):
    js = (init_wizard.paths.resource("gui_assets") / "gui.js").read_text(encoding="utf-8")
    assert 'd.posting_mode === "copy"' in js and "home.copy.s4" in js and "home.copy.link_connect" in js


def make_draft(ws, slug="hello", caption="A plain, true sentence.", status="draft"):
    folder = ws / "drafts" / slug
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "meta.json").write_text(json.dumps({"slug": slug, "status": status, "format": "text", "title": "T"}), encoding="utf-8")
    (folder / "caption.txt").write_text(caption, encoding="utf-8")


def test_copy_is_refused_for_a_bad_name_a_missing_draft_and_a_failed_gate(app, first_ws, monkeypatch):
    client, _ = app
    status, body = client.post("/api/build/copy", {"slug": "../x"})
    assert status == 422 and body["code"] == "copy.refused.slug"
    status, body = client.post("/api/build/copy", {"slug": "nope"})
    assert status == 422 and body["code"] == "copy.refused.nodraft"
    make_draft(first_ws)
    monkeypatch.setattr(post, "default_gate", lambda slug, ws, write=True: {"summary": "FAIL", "fails": ["numbers: bad"]})
    status, body = client.post("/api/build/copy", {"slug": "hello"})
    assert status == 422 and body["code"] == "copy.refused.gate" and body["params"]["count"] == 1


def test_copy_returns_the_text_once_the_gate_passes(app, first_ws, monkeypatch):
    client, _ = app
    make_draft(first_ws, caption="مرحبا\nسطر ثان")
    monkeypatch.setattr(post, "default_gate", lambda slug, ws, write=True: {"summary": "PASS", "fails": []})
    status, body = client.post("/api/build/copy", {"slug": "hello"})
    assert status == 200 and body["caption"] == "مرحبا\nسطر ثان" and body["open_url"].startswith("https://www.linkedin.com/")


def test_copy_needs_the_token_and_the_origin(app):
    client, _ = app
    assert client.post("/api/build/copy", {"slug": "x"}, headers={"X-PW-Token": "nope"})[0] == 403
    assert client.post("/api/build/copy", {"slug": "x"}, headers={"Origin": "http://evil.example"})[0] == 403


# ------------------------------------------------------------------ languages and assets

def test_both_language_files_are_served_and_nothing_else_under_i18n(app):
    client, _ = app
    for lang in ("en", "ar"):
        status, body, hdr = client.call("GET", f"/assets/i18n/{lang}.json", headers={"X-PW-Token": None})
        assert status == 200 and "json" in hdr["Content-Type"] and json.loads(body)
    assert client.call("GET", "/assets/i18n/fr.json", headers={"X-PW-Token": None})[0] == 404
    assert client.call("GET", "/assets/i18n/../gui.js", headers={"X-PW-Token": None})[0] in (404, 200)
    assert client.call("GET", "/assets/i18n/..%2f..%2fpyproject.toml", headers={"X-PW-Token": None})[0] == 404


def test_the_page_follows_the_saved_language_and_flips_direction(app):
    client, server = app
    html = client.call("GET", "/connect?t=" + server.token, headers={"X-PW-Token": None})[1].decode()
    assert 'lang="en" dir="ltr"' in html and 'data-screen="connect"' in html
    assert client.post("/api/settings/language", {"lang": "ar"})[1] == {"lang": "ar"}
    html = client.call("GET", "/connect?t=" + server.token, headers={"X-PW-Token": None})[1].decode()
    assert 'lang="ar" dir="rtl"' in html
    assert client.get("/api/home")[1]["ui_language"] == "ar"


def test_an_unknown_language_is_refused(app, first_ws):
    client, _ = app
    assert client.post("/api/settings/language", {"lang": "fr"})[0] == 400
    assert config.load(first_ws)["board"]["ui_language"] == "en"


def test_the_connect_screen_is_in_the_nav_and_has_a_shortcut(app):
    client, server = app
    html = client.call("GET", "/?t=" + server.token, headers={"X-PW-Token": None})[1].decode()
    assert f'href="/connect?t={server.token}"' in html
    js = (init_wizard.paths.resource("gui_assets") / "gui.js").read_text(encoding="utf-8")
    assert '"/connect"' in js and '"123456"' in js


# ------------------------------------------------------------------ connect: the checks

def test_the_connect_view_lists_five_steps_and_hides_every_secret(app, first_ws):
    client, _ = app
    status, view = client.get("/api/connect")
    assert status == 200 and [s["id"] for s in view["steps"]] == list(connect.STEP_IDS)
    assert view["posting_mode"] == "copy" and view["redirect_uri"].startswith("http://localhost:")
    assert view["reauth"]["expires_on"] is None and view["products"][0] == "Share on LinkedIn"
    connect.save_credentials(cfg_of(first_ws), CLIENT_ID, SECRET)
    raw = client.call("GET", "/api/connect")[1].decode()
    assert SECRET not in raw


def test_saving_credentials_refuses_bad_values_with_a_code_and_never_echoes_the_secret(app, first_ws):
    client, _ = app
    cases = [({"client_id": "", "key": SECRET}, "res.creds.id_empty"),
             ({"client_id": "has space", "key": SECRET}, "res.creds.id_format"),
             ({"client_id": CLIENT_ID, "key": ""}, "res.creds.secret_empty"),
             ({"client_id": CLIENT_ID, "key": "bad secret here"}, "res.creds.secret_format")]
    for body, code in cases:
        status, raw, _ = client.call("POST", "/api/connect/credentials", body)
        assert status == 422 and json.loads(raw)["code"] == code
        assert body["key"].encode() not in raw or body["key"] == ""
    assert not (auth.secrets_dir(cfg_of(first_ws)) / auth.CLIENT_FILE).exists()


def test_a_linkedin_password_is_refused_everywhere_it_could_arrive(app, first_ws):
    client, _ = app
    for path in ("/api/connect/credentials", "/api/connect/signin/start"):
        status, body = client.post(path, {"client_id": CLIENT_ID, "key": SECRET, "password": "hunter22"})
        assert status == 422 and body["code"] == "res.creds.password_refused"
    assert not (auth.secrets_dir(cfg_of(first_ws)) / auth.CLIENT_FILE).exists()


def test_saved_credentials_land_in_the_config_dir_not_the_workspace_and_move_steps_to_done(app, first_ws):
    client, _ = app
    status, raw, _ = client.call("POST", "/api/connect/credentials", {"client_id": CLIENT_ID, "key": SECRET})
    assert status == 200 and SECRET.encode() not in raw
    view = json.loads(raw)
    rows = {s["id"]: s for s in view["steps"]}
    assert rows["credentials"]["state"] == "done" and rows["app"]["state"] == "done"
    saved = auth.secrets_dir(cfg_of(first_ws)) / auth.CLIENT_FILE
    assert SECRET in saved.read_text(encoding="utf-8")
    for path in first_ws.rglob("*"):
        if path.is_file() and path.stat().st_size < 1_000_000:
            assert SECRET not in path.read_text(encoding="utf-8", errors="ignore"), path


# ------------------------------------------------------------------ connect: sign-in

def test_signin_is_refused_before_the_credentials_exist(app):
    client, _ = app
    status, body = client.post("/api/connect/signin/start", {})
    assert status == 422 and body["code"] == "res.signin.blocked"


def test_the_signin_runs_in_the_background_and_ends_with_the_reauth_date(app, first_ws, opened):
    client, _ = app
    client.post("/api/connect/credentials", {"client_id": CLIENT_ID, "key": SECRET})
    status, snap = client.post("/api/connect/signin/start", {})
    assert status == 200 and snap["state"] == "waiting" and "client_id=" + CLIENT_ID in snap["url"]
    assert SECRET not in json.dumps(snap)
    for _ in range(100):
        state = client.get("/api/connect/signin")[1]
        if state["state"] != "waiting":
            break
        time.sleep(0.05)
    assert state["state"] == "done" and state["code"] == "res.signin.done"
    assert opened and opened[0].startswith("https://www.linkedin.com/oauth/")
    view = client.get("/api/connect")[1]
    assert view["ready"] is True and view["reauth"]["expires_on"] and view["reauth"]["warn_from"]
    assert view["posting_mode"] == "copy", "signing in must not switch the mode"


# ------------------------------------------------------------------ connect: opting in to API posting

def test_api_posting_is_refused_without_a_sign_in_and_the_mode_stays_copy(app, first_ws):
    client, _ = app
    status, body = client.post("/api/connect/enable-api", {})
    assert status == 422 and body["code"] == "api.refused.token"
    assert config.load(first_ws)["posting"]["mode"] == "copy"


def test_after_a_sign_in_the_user_can_opt_in_to_click_mode_and_go_back(app, first_ws):
    client, _ = app
    save_token(cfg_of(first_ws))
    status, view = client.post("/api/connect/enable-api", {})
    assert status == 200 and view["posting_mode"] == "api_click"
    assert config.load(first_ws)["posting"]["mode"] == "api_click"
    status, view = client.post("/api/connect/copy-mode", {})
    assert status == 200 and view["posting_mode"] == "copy"


def test_opting_in_never_reaches_scheduled_posting(app, first_ws):
    client, _ = app
    save_token(cfg_of(first_ws))
    client.post("/api/connect/enable-api", {})
    assert config.load(first_ws)["posting"]["mode"] != "api_scheduled"
    assert config.effective_modes(config.load(first_ws), first_ws)["posting"] == "api_click"


def test_connect_endpoints_need_the_token_and_the_origin(app):
    client, _ = app
    assert client.get("/api/connect", headers={"X-PW-Token": "nope"})[0] == 403
    for path in ("/api/connect/credentials", "/api/connect/signin/start", "/api/connect/enable-api", "/api/connect/copy-mode"):
        assert client.post(path, {}, headers={"X-PW-Token": "nope"})[0] == 403
        assert client.post(path, {}, headers={"Origin": "http://evil.example"})[0] == 403
