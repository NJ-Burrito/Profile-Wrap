"""Fixtures for the board tests. No real LinkedIn or Claude call: the worker runner is a fake."""
from __future__ import annotations

import pytest
from board_helpers import Client, FakeRunner, make_ws

from profile_wrap.board.server import BoardServer


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    for name in ("PROFILE_WRAP_WORKER", "PROFILE_WRAP_WORKSPACE", "PROFILE_WRAP_CLAUDE_BIN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PROFILE_WRAP_TEST", "1")
    monkeypatch.setenv("PROFILE_WRAP_CONFIG_DIR", str(tmp_path / "cfgdir"))
    monkeypatch.setenv("PROFILE_WRAP_DATA_DIR", str(tmp_path / "datadir"))
    monkeypatch.setenv("PROFILE_WRAP_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("PYTHONUTF8", "1")


@pytest.fixture()
def ws(tmp_path):
    return make_ws(tmp_path)


@pytest.fixture()
def runner():
    return FakeRunner()


@pytest.fixture()
def start(ws, runner):
    servers = []

    def _start(**kw):
        kw.setdefault("runner", runner)
        kw.setdefault("notify_fn", lambda t, m: None)
        kw.setdefault("render_fn", lambda slug: (0, "ok"))
        srv = BoardServer(kw.pop("workspace", ws), port=0, **kw)
        srv.start_background()
        servers.append(srv)
        return srv, Client(srv)

    yield _start
    for s in servers:
        s.shutdown()


@pytest.fixture()
def board(start):
    return start()
