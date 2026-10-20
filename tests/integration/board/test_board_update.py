"""The board's update banner endpoint and Arabic strings."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from profile_wrap import updates
from profile_wrap.board import server as board_server

I18N = Path(board_server.__file__).parent / "i18n"


@pytest.fixture()
def fake(monkeypatch, tmp_path):
    monkeypatch.setenv("PROFILE_WRAP_CACHE_DIR", str(tmp_path / "ucache"))
    monkeypatch.setenv("PROFILE_WRAP_UPDATE_API_BASE", "http://127.0.0.1:9")
    calls = []

    def fetch(url, headers):
        calls.append(url)
        return 200, {}, json.dumps([{"tag_name": "v9.9.9", "body": "- board news", "prerelease": False}]).encode()

    monkeypatch.setattr(updates, "_default_fetch", fetch)
    monkeypatch.setattr(updates, "toast_once", lambda *a, **k: False)
    return calls


def test_board_reads_cache_only_unless_enabled(board, fake):
    srv, c = board
    code, body = c.get_json("/api/update")
    assert code == 200 and body["notify"] is False and not fake
    srv.app.update_enabled = True
    code, body = c.get_json("/api/update")
    data = body
    assert data["notify"] and data["latest"] == "9.9.9" and "board news" in data["news"][0]["body"]


def test_board_skip_and_later_need_the_token(board, fake):
    srv, c = board
    srv.app.update_enabled = True
    c.request("GET", "/api/update")
    assert c.request("POST", "/api/update/skip", token=None)[0] == 403
    code, body = c.post("/api/update/later", {})
    assert code == 200 and body["snoozed"] is True


def test_both_languages_have_every_update_string():
    en = json.loads((I18N / "en.json").read_text(encoding="utf-8"))
    ar = json.loads((I18N / "ar.json").read_text(encoding="utf-8"))
    keys = sorted(k for k in en if k.startswith("update."))
    assert len(keys) >= 9 and keys == sorted(k for k in ar if k.startswith("update."))
    assert all(ar[k] and ar[k] != en[k] for k in keys)
    js = (Path(board_server.__file__).parent / "app" / "board.js").read_text(encoding="utf-8")
    for k in keys:
        assert f'"{k}"' in js, k
