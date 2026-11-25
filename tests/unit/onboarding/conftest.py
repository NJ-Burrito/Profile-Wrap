"""Fixtures for the onboarding tests: isolated dirs, a first-run workspace."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from onboard_helpers import FIRST_RUN_ANSWERS

from profile_wrap import config, init_wizard


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    for name in ("PROFILE_WRAP_WORKSPACE", "PROFILE_WRAP_PLUGIN_ROOT", "CLAUDE_PLUGIN_ROOT", "PROFILE_WRAP_CLAUDE_BIN",
                 "LINKEDIN_CLIENT_ID", "LINKEDIN_CLIENT_SECRET"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PROFILE_WRAP_CONFIG_DIR", str(tmp_path / "cfgdir"))
    monkeypatch.setenv("PROFILE_WRAP_DATA_DIR", str(tmp_path / "datadir"))
    monkeypatch.setenv("PROFILE_WRAP_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("PYTHONUTF8", "1")
    return tmp_path


@pytest.fixture()
def first_run_ws(tmp_path) -> Path:
    summary = init_wizard.init_workspace(tmp_path / "ws", json.loads(json.dumps(FIRST_RUN_ANSWERS)), git=False)
    return Path(summary["workspace"])


@pytest.fixture()
def cfg(first_run_ws):
    return config.load(first_run_ws)
