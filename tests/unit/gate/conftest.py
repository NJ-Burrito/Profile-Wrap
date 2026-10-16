"""Fixtures for the gate and facts tests: a throwaway workspace built from tests/fixtures/captions."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from gate_helpers import FIX, make_draft


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("PROFILE_WRAP_WORKER", raising=False)
    monkeypatch.delenv("PROFILE_WRAP_WORKSPACE", raising=False)
    monkeypatch.delenv("PROFILE_WRAP_DATA_ROOT", raising=False)


@pytest.fixture()
def ws(tmp_path) -> Path:
    """Workspace with config, facts and stats registers, and evidence notes."""
    root = tmp_path / "ws"
    (root / "config").mkdir(parents=True)
    (root / "research").mkdir()
    (root / "notes").mkdir()
    (root / "drafts").mkdir()
    shutil.copy(FIX / "config.json", root / "config" / "profile-wrap.json")
    shutil.copy(FIX / "facts.md", root / "research" / "facts.md")
    shutil.copy(FIX / "stats.md", root / "research" / "stats.md")
    for n in ("review-time", "audit", "clinics", "pilot"):
        (root / "notes" / f"{n}.md").write_text("evidence\n", encoding="utf-8")
    return root


@pytest.fixture()
def draft(ws):
    def _make(*a, **kw):
        return make_draft(ws, *a, **kw)
    return _make
