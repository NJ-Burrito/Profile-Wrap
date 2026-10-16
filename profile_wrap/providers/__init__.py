"""Model providers: one interface, adapters for Anthropic, OpenAI-compatible servers, Gemini and
the user's own ``claude`` CLI. Keys live in the OS keychain (see ``keystore``) and nowhere else.

``profile-wrap providers list|set-key|test|use`` is in ``cli_ext``. Importing this package loads no
network or keychain code.
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from .base import Provider, ProviderError, Result, Spec

SPECS: Dict[str, Spec] = {s.id: s for s in (
    Spec("anthropic", "Anthropic API", "anthropic", "https://api.anthropic.com", "claude-sonnet-5-5"),
    Spec("openai", "OpenAI", "openai_compat", "https://api.openai.com/v1", "gpt-4o-mini"),
    Spec("openrouter", "OpenRouter", "openai_compat", "https://openrouter.ai/api/v1", "openrouter/auto"),
    Spec("ollama", "Ollama (local)", "openai_compat", "http://localhost:11434/v1", "llama3.2",
         needs_key=False, note="no key; the server must be running"),
    Spec("gemini", "Google Gemini", "gemini", "https://generativelanguage.googleapis.com",
         "gemini-2.5-flash", note="create a key restricted to the Gemini API"),
    Spec("claude-code", "Claude Code (your own claude CLI)", "claude_code", "", "sonnet",
         needs_key=False, note="uses your installed claude; no key stored"),
)}


def get_provider(provider_id: str, model: Optional[str] = None, base_url: Optional[str] = None,
                 environ: Optional[Mapping[str, str]] = None, **kw: Any) -> Provider:
    spec = SPECS.get(provider_id)
    if spec is None:
        raise ProviderError("config", f"unknown provider {provider_id!r}; choose one of: "
                            + ", ".join(SPECS))
    if spec.adapter == "anthropic":
        from .adapter_anthropic import AnthropicProvider as cls
    elif spec.adapter == "openai_compat":
        from .adapter_openai_compat import OpenAICompatProvider as cls
    elif spec.adapter == "gemini":
        from .adapter_gemini import GeminiProvider as cls
    else:
        from .adapter_claude_code import ClaudeCodeProvider as cls
        return cls(spec, model, base_url, environ, **kw)
    return cls(spec, model, base_url, environ)


__all__ = ["Provider", "ProviderError", "Result", "Spec", "SPECS", "get_provider"]
