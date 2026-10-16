"""Shared fixtures: every test runs with config, data and home dirs inside tmp_path."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from core_helpers import FIXTURES, REPO, load_answers_fixture


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    """Never touch the real user dirs; never see an outer workspace or a test override."""
    for name in ("PROFILE_WRAP_WORKSPACE", "PROFILE_WRAP_PLUGIN_ROOT", "CLAUDE_PLUGIN_ROOT", "PROFILE_WRAP_LINKEDIN_BASE",
                 "PROFILE_WRAP_WORKER", "PROFILE_WRAP_BROWSER", "PROFILE_WRAP_CLAUDE_BIN", "PROFILE_WRAP_PYTHON", "PROFILE_WRAP_TEST",
                 "PROFILE_WRAP_FAKE_PYVER", "HYPERFRAMES_BROWSER_PATH"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PROFILE_WRAP_CONFIG_DIR", str(tmp_path / "cfgdir"))
    monkeypatch.setenv("PROFILE_WRAP_DATA_DIR", str(tmp_path / "datadir"))
    monkeypatch.setenv("PROFILE_WRAP_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("PYTHONUTF8", "1")
    return tmp_path


@pytest.fixture()
def plugin_root(tmp_path) -> Path:
    """A throwaway plugin root: real templates, data and schema plus the two risk documents."""
    root = tmp_path / "plugin"
    for name in ("templates", "data", "schema"):
        shutil.copytree(REPO / name, root / name,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    (root / "profile_wrap").mkdir()
    docs = root / "docs"
    (docs / "references").mkdir(parents=True)
    (docs / "references" / "compliance.md").write_text("# Compliance\nversion one\n", encoding="utf-8")
    (docs / "TERMS-AND-RISK.md").write_text("# Terms and risk\nversion one\n", encoding="utf-8")
    return root


@pytest.fixture()
def answers_dir() -> Path:
    return FIXTURES / "answers"


@pytest.fixture()
def make_workspace(tmp_path, plugin_root):
    """Create a real workspace from the English fixture and return its path."""
    from profile_wrap import init_wizard

    def _make(name: str = "en.json", sub: str = "ws", **override):
        answers = load_answers_fixture(name)
        for key, value in override.items():
            answers[key] = value
        summary = init_wizard.init_workspace(tmp_path / sub, answers, plugin_root=plugin_root,
                                             git=False)
        return Path(summary["workspace"])

    return _make
