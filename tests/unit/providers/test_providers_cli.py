"""`profile-wrap providers list|set-key|test|use` end to end, with a mock server."""
from __future__ import annotations

import io
import json

import pytest

from prov_helpers import FAKE_ANTHROPIC, FAKE_OPENAI
from profile_wrap import cli, config


@pytest.fixture()
def run(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "EXTENSIONS", tuple(cli.EXTENSIONS) + ("providers",))
    ws = tmp_path / "ws"
    ws.mkdir()

    def go(*argv, stdin=None):
        if stdin is not None:
            monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
        rc = cli.main(["providers", *argv, "--workspace", str(ws)])
        out = capsys.readouterr()
        return rc, out.out, out.err
    go.ws = ws
    return go


def test_list_shows_all_providers_and_masks_keys(run, keychain):
    keychain.set_password("profile-wrap", "anthropic", FAKE_ANTHROPIC)
    rc, out, _ = run("list")
    assert rc == 0
    for pid in ("anthropic", "openai", "openrouter", "ollama", "gemini", "claude-code"):
        assert pid in out
    assert "****" + FAKE_ANTHROPIC[-4:] in out and FAKE_ANTHROPIC not in out
    rc, out, _ = run("list", "--json")
    rows = {r["id"]: r for r in json.loads(out)["providers"]}
    assert rows["anthropic"]["source"] == "keychain" and rows["openai"]["key"] == "missing"
    assert rows["ollama"]["key"] == "not needed"


def test_set_key_from_stdin_stores_in_the_keychain_and_prints_four_characters(run, keychain):
    rc, out, err = run("set-key", "openai", "--stdin", stdin=FAKE_OPENAI + "\n")
    assert rc == 0 and keychain.store[("profile-wrap", "openai")] == FAKE_OPENAI
    assert FAKE_OPENAI not in out + err and FAKE_OPENAI[-4:] in out


def test_set_key_without_a_keychain_fails_with_the_env_instruction(run, nokeychain):
    rc, out, err = run("set-key", "openai", "--stdin", stdin=FAKE_OPENAI + "\n")
    assert rc == 1 and "PROFILE_WRAP_OPENAI_API_KEY" in err and FAKE_OPENAI not in out + err


def test_a_key_cannot_be_given_on_the_command_line(run):
    with pytest.raises(SystemExit):
        run("set-key", "openai", FAKE_OPENAI)


def test_use_records_provider_and_model_but_never_a_key(run, keychain):
    keychain.set_password("profile-wrap", "openai", FAKE_OPENAI)
    rc, out, _ = run("use", "openai", "--model", "m-1")
    assert rc == 0
    text = (run.ws / "config" / "providers.json").read_text(encoding="utf-8")
    assert json.loads(text) == {"schema_version": 1, "provider": "openai", "model": "m-1"}
    assert FAKE_OPENAI not in text
    rc, out, _ = run("list", "--json")
    assert [r["id"] for r in json.loads(out)["providers"] if r["in_use"]] == ["openai"]


def test_use_without_a_key_warns_but_records(run, nokeychain):
    rc, out, err = run("use", "anthropic")
    assert rc == 0 and "providers set-key anthropic" in err


def test_the_settings_file_is_not_a_config_section(run):
    run("use", "ollama")
    assert "providers" not in config.SECTIONS


def test_test_passes_against_a_mock_server(run, mock, keychain):
    keychain.set_password("profile-wrap", "openai", FAKE_OPENAI)
    mock.reply("/chat/completions", {"id": "1", "choices": [{"message": {"content": "OK"}}]})
    assert run("use", "openai", "--base-url", mock.url)[0] == 0
    rc, out, err = run("test")
    assert rc == 0 and out.startswith("PASS openai") and FAKE_OPENAI not in out + err


def test_test_reports_the_status_not_the_key_on_failure(run, mock, keychain):
    keychain.set_password("profile-wrap", "openai", FAKE_OPENAI)
    mock.reply("/chat/completions", {"error": "nope " + FAKE_OPENAI}, status=401)
    run("use", "openai", "--base-url", mock.url)
    rc, out, err = run("test")
    assert rc == 1 and "status 401" in err and FAKE_OPENAI not in out + err


def test_test_with_a_missing_key_exits_non_zero_with_an_actionable_line(run, nokeychain):
    rc, out, err = run("test", "anthropic")
    assert rc == 1
    assert "providers set-key anthropic" in err and "PROFILE_WRAP_ANTHROPIC_API_KEY" in err


def test_test_without_a_choice_says_what_to_run(run):
    rc, _, err = run("test")
    assert rc == 1 and "providers use" in err


def test_ollama_needs_no_key(run, mock, nokeychain):
    mock.reply("/chat/completions", {"id": "1", "choices": [{"message": {"content": "OK"}}]})
    run("use", "ollama", "--base-url", mock.url)
    assert run("test")[0] == 0
