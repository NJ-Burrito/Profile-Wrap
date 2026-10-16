"""OpenAI chat completions, and every server that speaks it (OpenRouter, Ollama)."""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from .base import Provider, ProviderError, Result
from .wire import post_json


class OpenAICompatProvider(Provider):
    def _complete(self, system: str, messages: List[Dict[str, str]],
                  json_schema: Optional[Mapping[str, Any]], max_tokens: int, timeout: float) -> Result:
        key = self.api_key()
        msgs = ([{"role": "system", "content": system}] if system else []) + messages
        payload: Dict[str, Any] = {"model": self.model, "messages": msgs}
        # OpenAI's current name for the cap; the other servers still read max_tokens.
        payload["max_completion_tokens" if self.spec.id == "openai" else "max_tokens"] = max_tokens
        if json_schema:
            payload["response_format"] = {"type": "json_schema",
                                          "json_schema": {"name": "reply", "schema": dict(json_schema)}}
        obj = post_json(f"{self.base_url}/chat/completions", {"Authorization": f"Bearer {key}"},
                        payload, timeout, (key,))
        choices = obj.get("choices")
        try:
            text = choices[0]["message"]["content"] or ""
        except (TypeError, IndexError, KeyError):
            raise ProviderError("bad_response", "the answer had no choices[0].message.content") from None
        u = obj.get("usage") or {}
        return Result(text=text, raw_id=str(obj.get("id", "")),
                      usage={"input_tokens": int(u.get("prompt_tokens", 0) or 0),
                             "output_tokens": int(u.get("completion_tokens", 0) or 0)})
