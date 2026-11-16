"""Shared fixtures for the ``test_sched_*`` files: an isolated workspace and a notification recorder."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "integration" / "schedule"))
from schedhelp import cfg_of, make_ws  # noqa: E402,F401

pytest.importorskip("zoneinfo")


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("PROFILE_WRAP_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("PROFILE_WRAP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PROFILE_WRAP_TEST", "1")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    monkeypatch.delenv("PROFILE_WRAP_DUE_REMINDER_ONLY", raising=False)
    (tmp_path / "home").mkdir(exist_ok=True)


@pytest.fixture()
def mkws(tmp_path):
    def build(**kw):
        return make_ws(tmp_path, **kw)
    return build


@pytest.fixture()
def toasts(monkeypatch):
    """Record every notification instead of showing it; returns the list of (title, message)."""
    from profile_wrap import notify as notify_mod

    seen = []

    def fake(title, message, workspace=None, mode="auto"):
        seen.append((title, message))
        return "log"

    monkeypatch.setattr(notify_mod, "notify", fake)
    return seen
