"""The one provider interface: complete text in, complete text out.

``complete(system, messages, ...)`` returns a ``Result``. No streaming in 0.2. ``tools`` is part of
the signature so tool use can arrive later; today only a provider that declares ``supports_tools``
may receive it, and none of the API adapters does.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence


class ProviderError(Exception):
    """A classified failure. ``kind``: missing_key, unsupported, auth, rate_limit, server,
    network, timeout, bad_response, config. ``status`` is the HTTP status when there was one.
    The message never contains a key."""

    def __init__(self, kind: str, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.kind = kind
        self.status = status


@dataclass
class Result:
    text: str
    usage: Dict[str, int] = field(default_factory=dict)
    raw_id: str = ""
    provider: str = ""
    model: str = ""


@dataclass(frozen=True)
class Spec:
    id: str
    label: str
    adapter: str               # anthropic | openai_compat | gemini | claude_code
    base_url: str
    default_model: str
    needs_key: bool = True
    note: str = ""


Message = Mapping[str, str]


def check_messages(messages: Sequence[Message]) -> List[Dict[str, str]]:
    out = []
    for m in messages:
        role, content = m.get("role"), m.get("content")
        if role not in ("user", "assistant") or not isinstance(content, str):
            raise ProviderError("config", "each message needs role 'user' or 'assistant' and text content")
        out.append({"role": role, "content": content})
    if not out:
        raise ProviderError("config", "at least one message is required")
    return out


def schema_instruction(json_schema: Mapping[str, Any]) -> str:
    return ("Reply with one JSON value only, no prose and no code fence, matching this JSON Schema:\n"
            + json.dumps(json_schema, ensure_ascii=False))


class Provider:
    """Base class. Subclasses implement ``_complete``."""

    supports_tools = False

    def __init__(self, spec: Spec, model: Optional[str] = None, base_url: Optional[str] = None,
                 environ: Optional[Mapping[str, str]] = None):
        self.spec = spec
        self.model = model or spec.default_model
        self.base_url = (base_url or spec.base_url).rstrip("/")
        self.environ = environ if environ is not None else os.environ

    @property
    def id(self) -> str:
        return self.spec.id

    def api_key(self) -> str:
        """The key for this provider, or raise ``missing_key`` with the exact command to fix it."""
        from . import keystore
        if not self.spec.needs_key:
            return "ollama"  # local servers ignore the value; any non-empty string is sent
        found = keystore.get_key(self.spec.id, environ=self.environ)
        if not found:
            raise ProviderError("missing_key", keystore.missing_key_message(self.spec.id))
        return found.key

    def complete(self, system: str, messages: Sequence[Message], *,
                 json_schema: Optional[Mapping[str, Any]] = None,
                 tools: Optional[Sequence[Any]] = None,
                 max_tokens: int = 1024, timeout: float = 60.0) -> Result:
        if tools and not self.supports_tools:
            raise ProviderError("unsupported", f"{self.spec.id} does not take tools in this version; "
                                "use the claude-code provider for tool-using jobs")
        msgs = check_messages(messages)
        res = self._complete(system or "", msgs, json_schema, int(max_tokens), float(timeout))
        res.provider, res.model = self.spec.id, self.model
        return res

    def _complete(self, system: str, messages: List[Dict[str, str]],
                  json_schema: Optional[Mapping[str, Any]], max_tokens: int,
                  timeout: float) -> Result:  # pragma: no cover - abstract
        raise NotImplementedError
