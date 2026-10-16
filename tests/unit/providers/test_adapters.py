"""Each adapter against a local mock server: request shape, parsed answer, error handling."""
from __future__ import annotations

import pytest

from prov_helpers import FAKE_ANTHROPIC, FAKE_GEMINI, FAKE_OPENAI, FAKE_OPENROUTER
from profile_wrap.providers import ProviderError, get_provider

MSGS = [{"role": "user", "content": "hello"}]


def env(provider, key):
    from profile_wrap.providers import keystore
    return {keystore.env_name(provider): key}


def test_anthropic_request_and_answer(mock, nokeychain):
    mock.reply("/v1/messages", {"id": "msg_1", "content": [{"type": "text", "text": "Hi "}, {"type": "text", "text": "there"}],
                                "usage": {"input_tokens": 5, "output_tokens": 2}})
    p = get_provider("anthropic", "m1", mock.url, environ=env("anthropic", FAKE_ANTHROPIC))
    r = p.complete("be brief", MSGS, max_tokens=50)
    assert (r.text, r.raw_id, r.provider, r.model) == ("Hi there", "msg_1", "anthropic", "m1")
    assert r.usage == {"input_tokens": 5, "output_tokens": 2}
    q = mock.last()
    assert q["headers"]["x-api-key"] == FAKE_ANTHROPIC and q["headers"]["anthropic-version"]
    assert q["json"] == {"model": "m1", "max_tokens": 50, "system": "be brief", "messages": MSGS}


def test_anthropic_json_schema_goes_into_the_system_text(mock, nokeychain):
    mock.reply("/v1/messages", {"id": "x", "content": [{"type": "text", "text": "{}"}]})
    p = get_provider("anthropic", None, mock.url, environ=env("anthropic", FAKE_ANTHROPIC))
    p.complete("", MSGS, json_schema={"type": "object"})
    assert '"type": "object"' in mock.last()["json"]["system"]


@pytest.mark.parametrize("pid,key", [("openai", FAKE_OPENAI), ("openrouter", FAKE_OPENROUTER), ("ollama", None)])
def test_openai_compat_family(mock, nokeychain, pid, key):
    mock.reply("/chat/completions", {"id": "c1", "choices": [{"message": {"content": "pong"}}],
                                      "usage": {"prompt_tokens": 3, "completion_tokens": 1}})
    p = get_provider(pid, "mm", mock.url, environ=env(pid, key) if key else {})
    r = p.complete("sys", MSGS, max_tokens=20, json_schema={"type": "object"})
    assert r.text == "pong" and r.usage == {"input_tokens": 3, "output_tokens": 1}
    q = mock.last()
    assert q["headers"]["authorization"] == "Bearer " + (key or "ollama")
    assert q["json"]["messages"][0] == {"role": "system", "content": "sys"}
    assert q["json"]["response_format"]["type"] == "json_schema"
    cap = "max_completion_tokens" if pid == "openai" else "max_tokens"
    assert q["json"][cap] == 20


def test_gemini_native_request_keeps_the_key_out_of_the_url(mock, nokeychain):
    path = "/v1beta/models/gem-1:generateContent"
    mock.reply(path, {"responseId": "g1", "candidates": [{"content": {"parts": [{"text": "yo"}]}}],
                      "usageMetadata": {"promptTokenCount": 4, "candidatesTokenCount": 2}})
    p = get_provider("gemini", "gem-1", mock.url, environ=env("gemini", FAKE_GEMINI))
    r = p.complete("sys", [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"},
                           {"role": "user", "content": "c"}], max_tokens=9)
    assert r.text == "yo" and r.raw_id == "g1" and r.usage == {"input_tokens": 4, "output_tokens": 2}
    q = mock.last()
    assert q["path"] == path and FAKE_GEMINI not in q["path"]
    assert q["headers"]["x-goog-api-key"] == FAKE_GEMINI
    assert [c["role"] for c in q["json"]["contents"]] == ["user", "model", "user"]
    assert q["json"]["systemInstruction"]["parts"][0]["text"] == "sys"
    assert q["json"]["generationConfig"]["maxOutputTokens"] == 9


def test_gemini_blocked_answer_is_a_bad_response(mock, nokeychain):
    mock.reply("/v1beta/models/g:generateContent", {"promptFeedback": {"blockReason": "SAFETY"}})
    p = get_provider("gemini", "g", mock.url, environ=env("gemini", FAKE_GEMINI))
    with pytest.raises(ProviderError) as e:
        p.complete("", MSGS)
    assert e.value.kind == "bad_response"


@pytest.mark.parametrize("status,kind", [(401, "auth"), (403, "auth"), (429, "rate_limit"), (503, "server"), (400, "bad_response")])
def test_http_errors_are_classified_and_never_echo_the_key(mock, nokeychain, status, kind):
    # a hostile or sloppy server that echoes the key back must not get it into our error
    mock.reply("/v1/messages", {"error": {"message": f"bad key {FAKE_ANTHROPIC}"}}, status=status)
    p = get_provider("anthropic", "m", mock.url, environ=env("anthropic", FAKE_ANTHROPIC))
    with pytest.raises(ProviderError) as e:
        p.complete("", MSGS)
    assert e.value.kind == kind and e.value.status == status
    assert FAKE_ANTHROPIC not in str(e.value) and "[REDACTED]" in str(e.value)


def test_not_json_answer(mock, nokeychain):
    mock.reply("/v1/messages", "<html>", status=200)
    p = get_provider("anthropic", "m", mock.url, environ=env("anthropic", FAKE_ANTHROPIC))
    with pytest.raises(ProviderError) as e:
        p.complete("", MSGS)
    assert e.value.kind == "bad_response"


def test_redirect_is_not_followed(mock, nokeychain):
    mock.reply("/v1/messages", "", status=302, headers={"Location": mock.url + "/elsewhere"})
    p = get_provider("anthropic", "m", mock.url, environ=env("anthropic", FAKE_ANTHROPIC))
    with pytest.raises(ProviderError):
        p.complete("", MSGS)
    assert all(r["path"] != "/elsewhere" for r in mock.requests)


def test_plain_http_is_refused_off_localhost(nokeychain):
    p = get_provider("openai", "m", "http://example.org/v1", environ=env("openai", FAKE_OPENAI))
    with pytest.raises(ProviderError) as e:
        p.complete("", MSGS)
    assert e.value.kind == "config"


def test_unreachable_server_is_a_network_error(nokeychain):
    p = get_provider("ollama", "m", "http://127.0.0.1:9", environ={})
    with pytest.raises(ProviderError) as e:
        p.complete("", MSGS, timeout=3)
    assert e.value.kind in ("network", "timeout")


@pytest.mark.parametrize("pid", ["anthropic", "openai", "openrouter", "gemini"])
def test_missing_key_raises_an_actionable_error_before_any_request(mock, nokeychain, pid):
    p = get_provider(pid, "m", mock.url, environ={})
    with pytest.raises(ProviderError) as e:
        p.complete("", MSGS)
    assert e.value.kind == "missing_key"
    assert f"providers set-key {pid}" in str(e.value) and f"PROFILE_WRAP_{pid.upper()}_API_KEY" in str(e.value)
    assert mock.requests == []


def test_tools_are_refused_for_api_adapters(mock, nokeychain):
    p = get_provider("openai", "m", mock.url, environ=env("openai", FAKE_OPENAI))
    with pytest.raises(ProviderError) as e:
        p.complete("", MSGS, tools=[{"name": "x"}])
    assert e.value.kind == "unsupported"


def test_bad_messages_and_unknown_provider():
    with pytest.raises(ProviderError):
        get_provider("nope")
    p = get_provider("openai", environ={})
    with pytest.raises(ProviderError):
        p.complete("", [])
    with pytest.raises(ProviderError):
        p.complete("", [{"role": "system", "content": "x"}])
