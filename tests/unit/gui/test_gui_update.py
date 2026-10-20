"""The desktop app's update banner: API, buttons, and the guarantee that a bare server never asks GitHub."""
from __future__ import annotations

import json

import pytest

from profile_wrap import updates
from profile_wrap.gui import server as srv


class _Fetch:
    def __init__(self):
        self.calls = 0

    def __call__(self, url, headers):
        self.calls += 1
        body = [{"tag_name": "v9.9.9", "name": "v9.9.9", "body": "- shiny", "html_url": "https://example.invalid/r",
                 "prerelease": False, "draft": False}]
        return 200, {}, json.dumps(body).encode()


@pytest.fixture()
def fetch(monkeypatch, tmp_path):
    monkeypatch.setenv("PROFILE_WRAP_CACHE_DIR", str(tmp_path / "ucache"))
    monkeypatch.setenv("PROFILE_WRAP_TEST", "1")
    monkeypatch.setenv("PROFILE_WRAP_UPDATE_API_BASE", "http://127.0.0.1:9")
    f = _Fetch()
    monkeypatch.setattr(updates, "_default_fetch", f)
    monkeypatch.setattr(updates, "toast_once", lambda *a, **k: False)
    return f


def test_bare_server_reads_the_cache_only(client, fetch):
    status, body = client.get("/api/update")
    assert status == 200 and body["notify"] is False and fetch.calls == 0


def test_enabled_server_reports_news_and_buttons_work(live, client, fetch):
    live.app.update_enabled = True
    status, body = client.get("/api/update")
    assert status == 200 and body["notify"] and body["latest"] == "9.9.9"
    assert "shiny" in body["news"][0]["body"] and "argv" not in body["method"]
    status, body = client.post("/api/update/later")
    assert status == 200 and body["notify"] is False and body["snoozed"] is True
    status, body = client.post("/api/update/skip")
    assert status == 200 and body["skipped"] is True
    assert fetch.calls == 1                                    # the cache served the later calls


def test_update_api_needs_the_token_and_origin(client, fetch):
    assert client.get("/api/update", headers={"X-PW-Token": "wrong"})[0] == 403
    assert client.post("/api/update/skip", headers={"Origin": "http://evil.example"})[0] == 403


def test_page_carries_the_banner_slot_and_script_wiring(client, live):
    status, html = client.get(f"/?t={live.token}", headers={"X-PW-Token": None})
    assert status == 200 and b'id="update"' in html
    js = (srv.assets_dir() / "gui.js").read_text(encoding="utf-8")
    for needle in ("/api/update", "What's new", "Skip this version", "Later", "Update"):
        assert needle in js
