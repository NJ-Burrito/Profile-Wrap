"""Fixtures for the app tests: a demo workspace, a fake keychain, a fake provider, a live GuiServer."""
from __future__ import annotations

from pathlib import Path

import pytest

from gui_helpers import Client, FakeKeyring, FakeProvider
from profile_wrap import init_wizard
from profile_wrap.gui.server import GuiServer
from profile_wrap.plan import calendar as cal_mod
from profile_wrap.providers import keystore


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    for name in ("PROFILE_WRAP_WORKSPACE", "PROFILE_WRAP_PLUGIN_ROOT", "CLAUDE_PLUGIN_ROOT", "PROFILE_WRAP_CLAUDE_BIN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PROFILE_WRAP_CONFIG_DIR", str(tmp_path / "cfgdir"))
    monkeypatch.setenv("PROFILE_WRAP_DATA_DIR", str(tmp_path / "datadir"))
    monkeypatch.setenv("PROFILE_WRAP_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("PYTHONUTF8", "1")
    for pid in ("ANTHROPIC", "OPENAI", "OPENROUTER", "GEMINI"):
        monkeypatch.delenv(f"PROFILE_WRAP_{pid}_API_KEY", raising=False)
    return tmp_path


@pytest.fixture()
def keychain(monkeypatch):
    fake = FakeKeyring()
    monkeypatch.setattr(keystore, "_keyring", lambda: fake)
    return fake


@pytest.fixture()
def ws(tmp_path) -> Path:
    summary = init_wizard.init_workspace(tmp_path / "ws", init_wizard.DEMO_ANSWERS, git=False)
    root = Path(summary["workspace"])
    cal = cal_mod.empty()
    cal_mod.add_entry(cal, date="2099-01-05", slug="plain-day", title="A plain day", lang="en", format="text")
    cal_mod.add_entry(cal, date="2099-01-06", slug="gif-day", title="A gif day", lang="en", format="gif")
    cal_mod.save(root, cal)
    return root


@pytest.fixture()
def fake_provider():
    return FakeProvider()


@pytest.fixture()
def live(ws, fake_provider):
    server = GuiServer(ws, provider_factory=fake_provider,
                       doctor_fn=lambda _w: {"summary": {"pass": 1, "warn": 0, "fail": 0}, "checks": []}).start_background()
    yield server
    server.shutdown()


@pytest.fixture()
def client(live):
    return Client(live)
