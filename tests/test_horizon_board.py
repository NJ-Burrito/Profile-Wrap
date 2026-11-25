"""The board: the horizon banner feed and the "I posted it" button for copy-mode drafts."""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "integration" / "board"))
from board_helpers import Client, make_draft, make_ws  # noqa: E402

from profile_wrap import copymode  # noqa: E402
from profile_wrap.board.server import BoardServer  # noqa: E402

BOARD = Path(__file__).resolve().parents[1] / "profile_wrap" / "board"


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    for name in ("PROFILE_WRAP_WORKER", "PROFILE_WRAP_WORKSPACE", "PROFILE_WRAP_CLAUDE_BIN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PROFILE_WRAP_TEST", "1")
    monkeypatch.setenv("PROFILE_WRAP_CONFIG_DIR", str(tmp_path / "cfgdir"))
    monkeypatch.setenv("PROFILE_WRAP_DATA_DIR", str(tmp_path / "datadir"))
    monkeypatch.setenv("PROFILE_WRAP_HOME", str(tmp_path / "home"))


@pytest.fixture()
def serve(tmp_path):
    servers = []

    def start(**cfg):
        ws = make_ws(tmp_path, **cfg)
        srv = BoardServer(ws, port=0, notify_fn=lambda t, m: None, start_worker=False)
        srv.start_background()
        servers.append(srv)
        return ws, srv, Client(srv)

    yield start
    for s in servers:
        s.shutdown()


def test_horizon_endpoint_flags_a_missing_draft_and_an_empty_calendar(serve):
    ws, srv, c = serve()
    code, body = c.get_json("/api/horizon")
    assert code == 200 and body["status"] == "warn" and body["empty"] is True
    srv.app._horizon = None
    (ws / "strategy").mkdir(exist_ok=True)
    tomorrow = (dt.date.today() + dt.timedelta(days=1)).isoformat()
    (ws / "strategy" / "calendar.json").write_text(json.dumps({"schema_version": 1, "entries": [
        {"date": tomorrow, "slug": "soon", "lang": "en", "format": "text", "title": "T", "status": "planned"}]}),
        encoding="utf-8")
    code, body = c.get_json("/api/horizon")
    assert body["status"] == "fail" and body["missing"][0]["slug"] == "soon"


def test_the_ui_carries_the_banner_and_the_button_in_both_languages():
    js = (BOARD / "app" / "board.js").read_text(encoding="utf-8")
    assert "/api/horizon" in js and "/api/posted" in js and "d.can_mark_posted" in js
    for lang in ("en", "ar"):
        strings = json.loads((BOARD / "i18n" / f"{lang}.json").read_text(encoding="utf-8"))
        for key in ("actions.posted", "msg.posted", "banner.horizon", "banner.horizon.empty",
                    "err.refused", "err.unavailable"):
            assert strings.get(key), (lang, key)


def test_the_button_is_offered_in_copy_mode_only(serve):
    ws, srv, c = serve(posting={"mode": "copy"})
    make_draft(ws, "d1", "draft")
    make_draft(ws, "p1", "posted")
    assert c.get_json("/api/draft/d1")[1]["can_mark_posted"] is True
    assert c.get_json("/api/draft/p1")[1]["can_mark_posted"] is False


def test_the_button_is_hidden_when_the_mode_is_not_copy(tmp_path):
    ws = make_ws(tmp_path / "other", posting={"mode": "api_click"})
    make_draft(ws, "d1", "draft")
    srv = BoardServer(ws, port=0, notify_fn=lambda t, m: None, start_worker=False)
    try:
        assert srv.app.store.draft_detail("d1")["can_mark_posted"] is False
    finally:
        srv.httpd.server_close()


def test_posted_calls_copymode_mark_posted_through_the_csrf_path(serve, monkeypatch):
    ws, srv, c = serve(posting={"mode": "copy"})
    make_draft(ws, "d1", "draft")
    calls = []
    monkeypatch.setattr(copymode, "mark_posted",
                        lambda slug, url=None, ws=None: calls.append((ws, slug, url)) or {"state": "posted"})
    code, body = c.post("/api/posted", {"slug": "d1"})
    assert code == 200 and body["ok"] is True and body["state"] == "posted"
    assert calls == [(ws, "d1", None)]
    # the same security rules as every POST: Origin and token
    assert c.post("/api/posted", {"slug": "d1"}, origin=None)[0] == 403
    assert c.post("/api/posted", {"slug": "d1"}, token="wrong")[0] == 403
    assert len(calls) == 1


def test_posted_rejects_a_bad_slug(serve):
    ws, srv, c = serve(posting={"mode": "copy"})
    assert c.post("/api/posted", {"slug": "../etc"})[0] == 400


def test_posted_refusal_is_a_422_with_the_reason(serve, monkeypatch):
    ws, srv, c = serve(posting={"mode": "copy"})

    def refuse(slug, url=None, ws=None):
        raise copymode.PostedRefused("d1 is already in the ledger")
    monkeypatch.setattr(copymode, "mark_posted", refuse)
    code, body = c.post("/api/posted", {"slug": "d1"})
    assert code == 422 and body["error"] == "refused" and "already" in body["message"]
