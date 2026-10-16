"""leakcheck catches every provider key shape, and the providers never write one to disk."""
from __future__ import annotations

import pytest

from prov_helpers import FAKE_ANTHROPIC, FAKE_GEMINI, FAKE_OPENAI, FAKE_OPENROUTER
from profile_wrap import leakcheck
from profile_wrap.providers import keypatterns, settings

KEY_RULES = {"token-anthropic", "token-sk", "token-openrouter", "token-gemini"}


@pytest.mark.parametrize("key", [FAKE_ANTHROPIC, FAKE_OPENAI, FAKE_OPENROUTER, FAKE_GEMINI,
                                 "sk-" + "A1b2C3d4" * 4])
def test_the_scan_flags_each_key_shape(tmp_path, key):
    (tmp_path / "notes.txt").write_text(f"line one\nthe value is {key}\n", encoding="utf-8")
    rules = {f.rule for f in leakcheck.scan_tree(tmp_path)}
    assert rules & KEY_RULES, rules


def test_gemini_and_openrouter_have_their_own_rules(tmp_path):
    (tmp_path / "a.txt").write_text(FAKE_GEMINI + "\n" + FAKE_OPENROUTER + "\n", encoding="utf-8")
    rules = {f.rule for f in leakcheck.scan_tree(tmp_path)}
    assert {"token-gemini", "token-openrouter"} <= rules


def test_ordinary_text_is_clean(tmp_path):
    (tmp_path / "a.txt").write_text("The sky-blue task-list is OK. AI zebra. Use sk- as a prefix.\n", encoding="utf-8")
    assert [f for f in leakcheck.scan_tree(tmp_path) if f.rule in KEY_RULES] == []


def test_redact_removes_values_and_shapes():
    out = keypatterns.redact(f"a {FAKE_GEMINI} b short-secret-1 c", ("short-secret-1",))
    assert FAKE_GEMINI not in out and "short-secret-1" not in out and out.count("[REDACTED]") == 2


def test_settings_refuse_a_key_shaped_value(tmp_path):
    with pytest.raises(ValueError):
        settings.save(tmp_path, "openai", FAKE_OPENAI)
    assert not settings.path(tmp_path).exists()
