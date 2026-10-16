from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from schedhelp import cfg_of, make_ws  # noqa: E402,F401

pytest.importorskip("zoneinfo")


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("NJLI_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("NJLI_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("NJLI_TEST", "1")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    (tmp_path / "home").mkdir(exist_ok=True)


@pytest.fixture()
def mkws(tmp_path):
    def build(**kw):
        return make_ws(tmp_path, **kw)
    return build
