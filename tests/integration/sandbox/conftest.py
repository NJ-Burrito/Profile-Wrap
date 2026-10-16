from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runner"))
import wsfix  # noqa: E402


@pytest.fixture()
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("NJLI_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("NJLI_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("NJLI_TEST", "1")
    return wsfix.make_workspace(tmp_path)


@pytest.fixture()
def cfg():
    return wsfix.base_config()
