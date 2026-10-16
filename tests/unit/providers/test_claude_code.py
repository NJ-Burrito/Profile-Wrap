"""The claude-code provider wraps claude_runner unchanged."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "integration" / "runner"))
import wsfix  # noqa: E402

from profile_wrap import claude_runner as cr  # noqa: E402
from profile_wrap.providers import ProviderError, get_provider  # noqa: E402


@pytest.fixture()
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("PROFILE_WRAP_TEST", "1")
    return wsfix.make_workspace(tmp_path)


def test_it_needs_no_key_and_runs_the_fake_cli_text_only(ws):
    p = get_provider("claude-code", workspace=ws, cfg=wsfix.base_config(), exe=wsfix.FAKE_CMD)
    assert p.api_key() == ""
    r = p.complete(f"ROOT: {ws}\nFAKE: noop", [{"role": "user", "content": "say hi"}], timeout=60)
    assert r.text == "done" and r.provider == "claude-code"
    assert (ws / "drafts" / "d1" / "placeholder.txt").read_text() == "keep\n"


def test_it_passes_through_to_run_worker_with_one_read_tool_and_a_scratch_allowlist(ws, monkeypatch):
    seen = {}

    def fake(workspace, cfg, **kw):
        seen.update(kw)
        return cr.WorkerResult(cr.OK, text="reply")
    monkeypatch.setattr(cr, "run_worker", fake)
    p = get_provider("claude-code", workspace=ws, cfg=wsfix.base_config())
    assert p.complete("sys", [{"role": "user", "content": "q"}]).text == "reply"
    assert seen["tools"] == ["Read"] and seen["allow"] == ["data/provider-scratch/**"]
    assert "sys" in seen["prompt"] and "USER: q" in seen["prompt"]


def test_a_missing_claude_binary_is_a_clear_error(ws, monkeypatch):
    monkeypatch.setattr(cr, "find_claude", lambda cfg=None: None)
    p = get_provider("claude-code", workspace=ws, cfg=wsfix.base_config())
    with pytest.raises(ProviderError) as e:
        p.complete("", [{"role": "user", "content": "q"}])
    assert "no_claude" in str(e.value)


def test_it_needs_a_workspace():
    with pytest.raises(ProviderError) as e:
        get_provider("claude-code").complete("", [{"role": "user", "content": "q"}])
    assert e.value.kind == "config"
