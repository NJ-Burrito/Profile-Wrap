"""PW-R04: live token probe, a durable "rejected" state cleared by re-auth, and the scheduled check."""
from __future__ import annotations

import argparse
import json
import time

import pytest

from profile_wrap.http import HttpError
from profile_wrap.linkedin import api, auth, cli_ext
from test_sched_common import cfg_of, isolate, mkws, toasts  # noqa: F401


class FakeClient:
    def __init__(self, error=None):
        self.error, self.calls = error, 0

    def userinfo(self):
        self.calls += 1
        if self.error:
            raise self.error
        return {"sub": "DEMO000000", "name": "Maya Rivera"}


def token(cfg, days=30):
    d = auth.secrets_dir(cfg)
    auth.save_token(d, {"access_token": "fake-token", "author": "urn:li:person:DEMO000000",
                        "expires_at": time.time() + days * 86400, "name": "Maya Rivera"})
    return d


def test_a_200_is_ok_and_makes_exactly_one_call(mkws):
    cfg = cfg_of(mkws())
    token(cfg)
    c = FakeClient()
    assert auth.online_check(cfg, client=c)["online"] == "ok" and c.calls == 1
    assert auth.token_status(auth.secrets_dir(cfg))["state"] == "ok"


def test_a_401_writes_the_durable_rejected_state(mkws):
    cfg = cfg_of(mkws())
    d = token(cfg)
    res = auth.online_check(cfg, client=FakeClient(api.ApiError("nope", 401)))
    assert res["online"] == "rejected"
    st = auth.token_status(d)
    assert st["state"] == "rejected" and "401" in st["message"] and st["rejected_at"]
    # durable: a later call with no probe still says rejected
    assert auth.token_status(d, warn_days=1)["state"] == "rejected"


def test_saving_a_new_token_clears_rejected(mkws):
    cfg = cfg_of(mkws())
    d = token(cfg)
    auth.mark_rejected(d, 401, "x")
    assert auth.token_status(d)["state"] == "rejected"
    token(cfg)                       # what `auth`, `auth connect` and the desktop app all end with
    assert auth.token_status(d)["state"] == "ok"


@pytest.mark.parametrize("err", [HttpError("timeout", "timed out"), OSError("network down"),
                                 api.ApiError("server error", 503)])
def test_a_network_or_server_error_is_unknown_and_changes_nothing(mkws, err):
    cfg = cfg_of(mkws())
    d = token(cfg)
    assert auth.online_check(cfg, client=FakeClient(err))["online"] == "unknown"
    assert auth.token_status(d)["state"] == "ok"


def test_no_token_means_the_probe_is_skipped(mkws):
    cfg = cfg_of(mkws())
    c = FakeClient()
    assert auth.online_check(cfg, client=c)["online"] == "skipped" and c.calls == 0


def test_check_online_exits_non_zero_on_rejected(mkws, monkeypatch, capsys):
    ws = mkws()
    token(cfg_of(ws))
    args = argparse.Namespace(workspace=str(ws), profile=None, what="check", json=True, online=True, notify=False)
    monkeypatch.setattr(api, "Client", lambda *a, **k: FakeClient(api.ApiError("nope", 401)))
    assert cli_ext.cmd_auth(args) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["state"] == "rejected" and out["online"] == "rejected"


def test_check_online_exits_zero_when_unreachable(mkws, monkeypatch, capsys):
    ws = mkws()
    token(cfg_of(ws))
    args = argparse.Namespace(workspace=str(ws), profile=None, what="check", json=True, online=True, notify=False)
    monkeypatch.setattr(api, "Client", lambda *a, **k: FakeClient(OSError("down")))
    assert cli_ext.cmd_auth(args) == 0
    assert json.loads(capsys.readouterr().out)["online"] == "unknown"


def test_the_scheduled_check_notifies_once_on_warn(mkws, toasts, capsys):
    ws = mkws()
    token(cfg_of(ws), days=3)        # inside token_warn_days
    args = argparse.Namespace(workspace=str(ws), profile=None, what="check", json=False, online=False, notify=True)
    assert cli_ext.cmd_auth(args) == 0
    assert cli_ext.cmd_auth(args) == 0
    assert [t for t, _ in toasts] == ["Profile-Wrap: LinkedIn sign-in expires soon"]


def test_the_scheduled_check_notifies_on_rejected_and_ok_clears(mkws, toasts, monkeypatch, capsys):
    ws = mkws()
    cfg = cfg_of(ws)
    token(cfg)
    args = argparse.Namespace(workspace=str(ws), profile=None, what="check", json=False, online=True, notify=True)
    monkeypatch.setattr(api, "Client", lambda *a, **k: FakeClient(api.ApiError("nope", 401)))
    assert cli_ext.cmd_auth(args) == 1
    assert [t for t, _ in toasts] == ["Profile-Wrap: LinkedIn rejected the token"]
    token(cfg)                                                 # re-auth
    monkeypatch.setattr(api, "Client", lambda *a, **k: FakeClient())
    assert cli_ext.cmd_auth(args) == 0                         # ok: notices cleared
    monkeypatch.setattr(api, "Client", lambda *a, **k: FakeClient(api.ApiError("nope", 401)))
    assert cli_ext.cmd_auth(args) == 1
    assert len(toasts) == 2
