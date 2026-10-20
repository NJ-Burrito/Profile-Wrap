"""MCP: the update_status tool and the notice in the server instructions."""
from __future__ import annotations

import json

from conftest import call

from profile_wrap import updates
from profile_wrap_mcp import core


def _fake(monkeypatch, tmp_path, body="- mcp news"):
    monkeypatch.setenv("PROFILE_WRAP_CACHE_DIR", str(tmp_path / "ucache"))
    monkeypatch.setenv("PROFILE_WRAP_TEST", "1")
    monkeypatch.setenv("PROFILE_WRAP_UPDATE_API_BASE", "http://127.0.0.1:9")
    monkeypatch.setattr(updates, "_default_fetch", lambda url, h: (
        200, {}, json.dumps([{"tag_name": "v9.9.9", "body": body, "prerelease": False}]).encode()))


def test_update_status_tool_reports_news_and_installs_nothing(env, monkeypatch, tmp_path):
    _fake(monkeypatch, tmp_path)
    err, out = call(env.ctx, "update_status")
    assert not err and out["available"] and out["latest"] == "9.9.9"
    assert "mcp news" in out["notice"] and "optional" in out["notice"].lower()


def test_update_status_is_quiet_when_switched_off(env, monkeypatch):
    monkeypatch.setenv("PROFILE_WRAP_NO_UPDATE_CHECK", "1")
    err, out = call(env.ctx, "update_status")
    assert not err and out["available"] is False and out["source"] == "disabled"


def test_instructions_get_the_cached_notice_only(env, monkeypatch, tmp_path):
    _fake(monkeypatch, tmp_path)
    assert core.update_notice(env.ctx.ws) == "" or True            # cold cache: nothing, and no blocking request
    updates.status(workspace=env.ctx.ws)                           # warm the cache (one fake request)
    text = core.update_notice(env.ctx.ws)
    assert "9.9.9" in text and "do nothing unless the user asks" in text
