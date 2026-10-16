"""Key storage: keychain first, environment fallback, nothing on disk, masked display."""
from __future__ import annotations

import pytest

from prov_helpers import FAKE_ANTHROPIC
from profile_wrap.providers import keystore


def test_env_name():
    assert keystore.env_name("anthropic") == "PROFILE_WRAP_ANTHROPIC_API_KEY"
    assert keystore.env_name("claude-code") == "PROFILE_WRAP_CLAUDE_CODE_API_KEY"


def test_mask_shows_only_the_last_four():
    m = keystore.mask(FAKE_ANTHROPIC)
    assert m == "****" + FAKE_ANTHROPIC[-4:] and FAKE_ANTHROPIC[:-4] not in m
    assert keystore.mask("abc") == "****"


def test_set_get_delete_through_the_keychain(keychain):
    keystore.set_key("openai", "  " + FAKE_ANTHROPIC + "\n")
    found = keystore.get_key("openai", environ={})
    assert (found.key, found.source) == (FAKE_ANTHROPIC, "keychain")
    assert keystore.delete_key("openai") and keystore.get_key("openai", environ={}) is None


def test_keychain_wins_over_env_and_env_is_the_fallback(keychain):
    env = {"PROFILE_WRAP_GEMINI_API_KEY": "from-env-0000"}
    assert keystore.get_key("gemini", environ=env).source == "env"
    keychain.set_password(keystore.SERVICE, "gemini", "from-chain-0000")
    assert keystore.get_key("gemini", environ=env).key == "from-chain-0000"


def test_headless_without_keychain_reads_env_and_set_key_says_what_to_do(nokeychain):
    assert keystore.get_key("openai", environ={}) is None
    f = keystore.get_key("openai", environ={"PROFILE_WRAP_OPENAI_API_KEY": "  k-123456  "})
    assert (f.key, f.source) == ("k-123456", "env")
    with pytest.raises(keystore.KeystoreError) as e:
        keystore.set_key("openai", "k-123456")
    assert "PROFILE_WRAP_OPENAI_API_KEY" in str(e.value) and "k-123456" not in str(e.value)


def test_a_broken_keychain_reads_as_no_key_and_never_prompts(monkeypatch):
    class Broken:
        def get_password(self, *a):
            raise RuntimeError("locked")
    monkeypatch.setattr(keystore, "_keyring", lambda: Broken())
    assert keystore.get_key("anthropic", environ={}) is None


def test_empty_key_is_refused(keychain):
    with pytest.raises(keystore.KeystoreError):
        keystore.set_key("openai", "   ")
