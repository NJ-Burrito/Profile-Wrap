"""The app through its real HTTP entry point: binding, token, origin, key handling, screens, selftest."""
from __future__ import annotations

import json
import re
import socket
from pathlib import Path

import pytest

from gui_helpers import FAKE_KEY, Client
from profile_wrap.gui import server as srv
from profile_wrap.gui.server import SCREENS, GuiServer

REPO = Path(__file__).resolve().parents[3]


def test_binds_loopback_only_on_a_random_port(live, ws):
    assert live.httpd.server_address[0] == "127.0.0.1" and live.port > 1023
    other = GuiServer(ws)
    try:
        assert other.port != live.port and other.token != live.token
    finally:
        other.httpd.server_close()
    with pytest.raises(ValueError):
        GuiServer(ws, host="0.0.0.0")


def test_health_needs_no_token_but_checks_host(client):
    status, body = client.get("/health", headers={"X-PW-Token": None})
    assert status == 200 and body["ok"] is True
    status, _ = client.get("/health", headers={"Host": "evil.example"})
    assert status == 403


@pytest.mark.parametrize("path,screen", list(SCREENS.items()))
def test_every_screen_needs_the_token_and_renders(client, live, path, screen):
    for bad in (path, path + "?t=nope"):
        assert client.call("GET", bad, headers={"X-PW-Token": None})[0] == 403
    status, body, hdr = client.call("GET", f"{path}?t={live.token}", headers={"X-PW-Token": None})
    html = body.decode()
    assert status == 200 and f'data-screen="{screen}"' in html and live.token in html
    assert "default-src 'none'" in hdr["Content-Security-Policy"] and hdr["Cache-Control"] == "no-store"


def test_nav_links_carry_the_token_so_every_screen_opens_from_the_app(client, live):
    status, body, _ = client.call("GET", "/?t=" + live.token)
    html = body.decode()
    assert status == 200
    for path in SCREENS:
        assert f'href="{path}?t={live.token}"' in html


def test_wrong_token_everywhere_is_refused(client):
    assert client.get("/api/home", headers={"X-PW-Token": "nope"})[0] == 403
    assert client.post("/api/providers/use", {"provider": "ollama"}, headers={"X-PW-Token": "nope"})[0] == 403


def test_post_needs_this_servers_origin(client):
    assert client.post("/api/doctor", headers={"Origin": "http://evil.example"})[0] == 403
    assert client.post("/api/doctor", headers={"Origin": None})[0] == 403
    assert client.post("/api/doctor", headers={"Host": "evil.example"})[0] == 403
    assert client.post("/api/doctor")[0] == 200


def test_body_limits_and_shape(client):
    assert client.post("/api/doctor", raw=b"{" + b" " * 25000 + b"}")[0] == 413
    assert client.post("/api/doctor", raw=b"not json")[0] == 400
    assert client.post("/api/doctor", raw=b"[1]")[0] == 400
    assert client.call("PUT", "/api/doctor")[0] == 405


def test_unknown_routes(client):
    assert client.get("/api/nope")[0] == 404
    assert client.get("/nope")[0] == 404
    assert client.get("/assets/../../etc/passwd")[0] == 404
    assert client.get("/assets/gui.py")[0] == 404


def test_key_is_never_echoed_back_anywhere(client, keychain, ws):
    status, out = client.post("/api/providers/key", {"provider": "anthropic", "key": FAKE_KEY})
    assert status == 200 and out["key"] == "****" + FAKE_KEY[-4:]
    assert keychain.store[("profile-wrap", "anthropic")] == FAKE_KEY
    for path in ("/api/providers", "/api/home", "/api/settings"):
        status, body, _ = client.call("GET", path)
        assert FAKE_KEY not in body.decode()
    # a refusal that quotes the key text must redact it
    status, out = client.post("/api/providers/key", {"provider": "anthropic", "key": FAKE_KEY + " extra"})
    assert status == 400 and FAKE_KEY not in json.dumps(out)
    # nothing on disk holds it
    for p in ws.rglob("*"):
        if p.is_file() and p.stat().st_size < 2_000_000:
            assert FAKE_KEY.encode() not in p.read_bytes(), p
    status, out = client.post("/api/providers/key/delete", {"provider": "anthropic"})
    assert out["removed"] is True and ("profile-wrap", "anthropic") not in keychain.store


def test_provider_flow_use_test_and_home(client, keychain):
    client.post("/api/providers/key", {"provider": "openai", "key": FAKE_KEY})
    status, out = client.post("/api/providers/use", {"provider": "openai", "model": "m1"})
    assert status == 200 and out["model"] == "m1"
    status, out = client.post("/api/providers/test", {"provider": "openai"})
    assert out["ok"] and out["status"] == 200 and FAKE_KEY not in json.dumps(out)
    home = client.get("/api/home")[1]
    assert home["provider"] == "openai" and home["next_post"]["slug"] == "plain-day"
    assert home["doctor"]["summary"]["pass"] == 1


def test_build_flow_over_http(client, keychain):
    client.post("/api/providers/use", {"provider": "anthropic", "model": "m"})
    entries = client.get("/api/calendar")[1]["entries"]
    assert [e["slug"] for e in entries] == ["plain-day", "gif-day"] and not entries[0]["has_draft"]
    status, out = client.post("/api/build/draft", {"slug": "plain-day"})
    assert status == 200 and out["caption"].startswith("Short hook")
    status, gate = client.post("/api/build/gate", {"slug": "plain-day"})
    assert status == 200 and gate["summary"] in ("PASS", "FAIL")
    assert client.post("/api/build/draft", {"slug": "plain-day"})[0] == 409
    assert client.post("/api/build/draft", {"slug": "gif-day"})[0] == 422
    assert client.post("/api/build/text", {"slug": "plain-day"})[1]["caption"].startswith("Short hook")
    assert client.get("/api/calendar")[1]["entries"][0]["has_draft"] is True


def test_settings_over_http(client, ws, tmp_path):
    out = client.post("/api/settings/posting-mode", {"mode": "copy"})[1]
    assert out["posting_mode"] == "copy"
    out = client.post("/api/settings/job", {"name": "post_due", "enabled": True})[1]
    assert {"name": "post_due", "enabled": True} in out["jobs"]
    assert client.post("/api/settings/posting-mode", {"mode": "x"})[0] == 400
    assert client.post("/api/settings/workspace", {"path": str(tmp_path)})[0] == 422
    assert client.post("/api/settings/workspace", {"path": str(ws)})[0] == 200


def test_board_starts_on_loopback_and_stops_with_the_app(ws):
    server = GuiServer(ws, doctor_fn=lambda _w: {"summary": {}, "checks": []}).start_background()
    client = Client(server)
    try:
        assert client.get("/api/board")[1] == {"running": False, "url": None}
        status, out = client.post("/api/board/start")
        assert status == 200 and out["url"].startswith("http://127.0.0.1:")
        board_port = int(re.search(r":(\d+)/", out["url"]).group(1))
        with socket.create_connection(("127.0.0.1", board_port), timeout=3):
            pass
    finally:
        server.shutdown()
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", board_port), timeout=1)


def test_quit_sets_the_event(client, live):
    assert not live.app.quit.is_set()
    client.post("/api/quit")
    assert live.app.quit.is_set()


def test_assets_have_no_inline_code_no_external_origin_no_linkedin_logo():
    html = (REPO / "gui_assets" / "index.html").read_text(encoding="utf-8")
    js = (REPO / "gui_assets" / "gui.js").read_text(encoding="utf-8")
    css = (REPO / "gui_assets" / "gui.css").read_text(encoding="utf-8")
    assert not re.search(r"<script(?![^>]*\bsrc=)", html) and "<style" not in html and ' style="' not in html
    for text in (html, js, css):
        assert not re.search(r"(https?:)?//(?!www\.w3\.org)[a-z0-9.-]+\.[a-z]{2,}", text, re.I), "external origin"
        assert "innerHTML" not in text and "@import" not in text and "@font-face" not in text
    assert "linkedin" not in (html + js + css).lower().replace("not affiliated with linkedin", "")
    assert not list((REPO / "gui_assets").glob("*.woff*")) and not list((REPO / "gui_assets").glob("*.ttf"))
    assert 'lang="en"' in html and 'aria-label="Screens"' in html and 'class="skip"' in html


def test_selftest_passes_headless_and_only_touches_loopback(monkeypatch, capsys):
    from profile_wrap.gui.selftest import run_selftest
    real = socket.socket.connect

    def guard(self, address):
        host = address[0] if isinstance(address, tuple) else address
        assert host in ("127.0.0.1", "::1", "localhost"), f"selftest reached {address}"
        return real(self, address)

    monkeypatch.setattr(socket.socket, "connect", guard)
    assert run_selftest() == 0
    out = capsys.readouterr().out
    assert "FAIL" not in out and "passed" in out


def test_selftest_json(capsys):
    from profile_wrap.gui.selftest import run_selftest
    assert run_selftest(json_out=True) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is True and any(c["check"].startswith("screen build") for c in data["checks"])


def test_cli_registers_gui_and_runs_the_selftest(monkeypatch, capsys):
    import argparse
    from profile_wrap.gui import cli_ext
    parser = argparse.ArgumentParser()
    cli_ext.register(parser.add_subparsers(dest="cmd"))
    args = parser.parse_args(["gui", "--selftest", "--json"])
    assert args.func(args) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True


def test_cli_refuses_a_folder_that_is_not_a_workspace(tmp_path, capsys):
    import argparse
    from profile_wrap.gui import cli_ext
    parser = argparse.ArgumentParser()
    cli_ext.register(parser.add_subparsers(dest="cmd"))
    args = parser.parse_args(["gui", "--workspace", str(tmp_path / "empty")])
    assert args.func(args) == 1
    assert "not a workspace" in capsys.readouterr().err


def test_browser_fallback_when_pywebview_is_missing(ws, monkeypatch, capsys):
    from profile_wrap.gui import window
    opened = []
    monkeypatch.setattr(window, "have_webview", lambda: False)
    monkeypatch.setattr(window.webbrowser, "open", lambda url: opened.append(url) or
                        threading_quit(url))

    def threading_quit(url):
        # simulate the user pressing Quit: hit the API with the token from the launch URL
        token = url.split("?t=")[1]
        port = int(re.search(r":(\d+)/", url).group(1))
        import urllib.request
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/quit", data=b"{}", method="POST",
                                     headers={"X-PW-Token": token, "Origin": f"http://127.0.0.1:{port}",
                                              "Content-Type": "application/json"})
        urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=10).read()
        return True

    assert window.run(ws) == 0
    assert opened and opened[0].startswith("http://127.0.0.1:") and "?t=" in opened[0]
    assert "pywebview is not installed" in capsys.readouterr().err
