"""The screens' logic, with no socket: keys, providers, drafts, settings."""
from __future__ import annotations

import json

import pytest

from gui_helpers import FAKE_KEY, FakeProvider
from profile_wrap import config as config_mod
from profile_wrap.gui import logic
from profile_wrap.gui.logic import GuiError
from profile_wrap.providers import ProviderError


def test_set_key_stores_in_keychain_and_returns_only_the_mask(keychain):
    out = logic.set_key("anthropic", "  " + FAKE_KEY + "\n")
    assert keychain.store[("profile-wrap", "anthropic")] == FAKE_KEY
    assert out == {"id": "anthropic", "key": "****" + FAKE_KEY[-4:], "source": "keychain"}
    assert FAKE_KEY not in json.dumps(out)


@pytest.mark.parametrize("bad", ["", "   ", "has space inside", "x" * 600, None, 12])
def test_set_key_refuses_a_bad_value(keychain, bad):
    with pytest.raises(GuiError):
        logic.set_key("openai", bad)


def test_set_key_refuses_unknown_provider_and_keyless_provider(keychain):
    with pytest.raises(GuiError):
        logic.set_key("nope", FAKE_KEY)
    with pytest.raises(GuiError):
        logic.set_key("ollama", FAKE_KEY)


def test_set_key_without_keychain_says_what_to_do_and_never_echoes(monkeypatch):
    from profile_wrap.providers import keystore
    monkeypatch.setattr(keystore, "_keyring", lambda: None)
    with pytest.raises(GuiError) as err:
        logic.set_key("anthropic", FAKE_KEY)
    assert err.value.status == 409
    assert "PROFILE_WRAP_ANTHROPIC_API_KEY" in str(err.value) and FAKE_KEY not in str(err.value)


def test_provider_rows_mask_keys_and_mark_the_one_in_use(ws, keychain):
    logic.set_key("openai", FAKE_KEY)
    logic.use_provider(ws, "openai", "gpt-x")
    data = logic.provider_rows(ws)
    rows = {r["id"]: r for r in data["providers"]}
    assert rows["openai"]["in_use"] and rows["openai"]["model"] == "gpt-x"
    assert rows["openai"]["key"] == "****" + FAKE_KEY[-4:] and rows["anthropic"]["key"] == "missing"
    assert rows["ollama"]["key"] == "not needed"
    assert FAKE_KEY not in json.dumps(data)
    assert data["keychain"] is True


def test_use_provider_saves_no_key_and_validates(ws, keychain):
    logic.set_key("anthropic", FAKE_KEY)
    logic.use_provider(ws, "anthropic", None)
    saved = (ws / "config" / "providers.json").read_text(encoding="utf-8")
    assert FAKE_KEY not in saved and "claude-sonnet" in saved
    for bad_model in ("bad model!", "", "a" * 200):
        if bad_model:
            with pytest.raises(GuiError):
                logic.use_provider(ws, "anthropic", bad_model)
    with pytest.raises(GuiError):
        logic.use_provider(ws, "anthropic", "m", "http://example.com/v1")
    assert logic.use_provider(ws, "ollama", "m", "http://localhost:11434/v1")["base_url"]


def test_test_provider_reports_status_and_hides_the_key(ws, keychain):
    ok = logic.test_provider(ws, "anthropic", FakeProvider())
    assert ok["ok"] and ok["status"] == 200 and FAKE_KEY not in json.dumps(ok)
    err = ProviderError("auth", f"rejected {FAKE_KEY}", status=401)
    bad = logic.test_provider(ws, "anthropic", FakeProvider(fail=err))
    assert bad["ok"] is False and bad["status"] == 401 and FAKE_KEY not in json.dumps(bad)


def test_next_post_prefers_a_queued_draft_then_the_calendar(ws):
    assert logic.next_post(ws)["state"] == "planned" and logic.next_post(ws)["slug"] == "plain-day"
    d = ws / "drafts" / "queued-one"
    d.mkdir(parents=True)
    (d / "meta.json").write_text(json.dumps({"slug": "queued-one", "title": "Q", "status": "queued",
                                             "scheduled_at": "2099-02-01T10:00:00+00:00"}), encoding="utf-8")
    assert logic.next_post(ws) == {"slug": "queued-one", "title": "Q", "when": "2099-02-01T10:00:00+00:00",
                                   "state": "queued"}


def test_generate_draft_writes_files_and_the_gate_runs(ws, keychain):
    logic.use_provider(ws, "anthropic", "m")
    fake = FakeProvider()
    out = logic.generate_draft(ws, "plain-day", factory=fake)
    assert out["caption"].startswith("Short hook") and out["provider"] == "anthropic"
    d = ws / "drafts" / "plain-day"
    assert (d / "caption.txt").read_text(encoding="utf-8").startswith("Short hook")
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    assert meta["status"] == "draft" and meta["generated_by"] == "anthropic:m" and meta["lang"] == "en"
    sent = fake.calls[0][1][0]["content"]
    assert "A plain day" in sent and "<<<DATA" in sent
    gate = logic.run_gate_for(ws, "plain-day")
    assert gate["summary"] in ("PASS", "FAIL") and "checks" in gate


def test_generate_draft_refusals(ws, keychain):
    with pytest.raises(GuiError) as e:
        logic.generate_draft(ws, "plain-day", factory=FakeProvider())
    assert e.value.status == 409 and "provider" in str(e.value)
    logic.use_provider(ws, "anthropic", "m")
    with pytest.raises(GuiError) as e:
        logic.generate_draft(ws, "gif-day", factory=FakeProvider())
    assert e.value.status == 422
    with pytest.raises(GuiError):
        logic.generate_draft(ws, "../etc", factory=FakeProvider())
    with pytest.raises(GuiError) as e:
        logic.generate_draft(ws, "missing-day", factory=FakeProvider())
    assert e.value.status == 404
    logic.generate_draft(ws, "plain-day", factory=FakeProvider())
    with pytest.raises(GuiError) as e:  # a caption exists: needs the Replace box
        logic.generate_draft(ws, "plain-day", factory=FakeProvider())
    assert e.value.status == 409
    logic.generate_draft(ws, "plain-day", overwrite=True, factory=FakeProvider(reply="plain text, not json"))
    assert (ws / "drafts" / "plain-day" / "caption.txt").read_text(encoding="utf-8").startswith("plain text")


def test_generate_draft_never_overwrites_a_queued_post(ws, keychain):
    logic.use_provider(ws, "anthropic", "m")
    d = ws / "drafts" / "plain-day"
    d.mkdir(parents=True)
    (d / "meta.json").write_text(json.dumps({"slug": "plain-day", "status": "queued"}), encoding="utf-8")
    with pytest.raises(GuiError) as e:
        logic.generate_draft(ws, "plain-day", overwrite=True, factory=FakeProvider())
    assert "queued" in str(e.value) and not (d / "caption.txt").exists()


def test_provider_failure_becomes_a_502_without_the_key(ws, keychain):
    logic.use_provider(ws, "anthropic", "m")
    with pytest.raises(GuiError) as e:
        logic.generate_draft(ws, "plain-day", factory=FakeProvider(fail=ProviderError("server", "down", status=503)))
    assert e.value.status == 502 and "503" in str(e.value)


def test_settings_posting_mode_and_jobs(ws):
    view = logic.settings_view(ws, config_mod.load(ws))
    assert "api_click" in view["posting_modes"] and any(j["name"] == "post_due" for j in view["jobs"])
    logic.set_posting_mode(ws, "copy")
    assert config_mod.load(ws)["posting"]["mode"] == "copy"
    logic.set_job(ws, "post_due", True)
    assert config_mod.load(ws)["schedule"]["jobs"]["post_due"]["enabled"] is True
    logic.set_job(ws, "post_due", False)
    assert config_mod.load(ws)["schedule"]["jobs"]["post_due"]["enabled"] is False
    for bad in (lambda: logic.set_posting_mode(ws, "evil"), lambda: logic.set_job(ws, "nope", True),
                lambda: logic.set_job(ws, "post_due", "yes")):
        with pytest.raises(GuiError):
            bad()


def test_check_workspace(ws, tmp_path):
    assert logic.check_workspace(str(ws)) == ws.resolve()
    with pytest.raises(GuiError):
        logic.check_workspace(str(tmp_path))
    with pytest.raises(GuiError):
        logic.check_workspace("")


def test_parse_reply_accepts_raw_newlines_fences_and_plain_text():
    raw = '{"caption": "Hook' + chr(10) + chr(10) + 'Line two", "alt": "Alt"}'
    assert logic.parse_reply(raw) == {"caption": "Hook" + chr(10) + chr(10) + "Line two", "alt": "Alt"}
    assert logic.parse_reply("```json" + chr(10) + raw + chr(10) + "```")["alt"] == "Alt"
    assert logic.parse_reply("just text") == {"caption": "just text", "alt": ""}
