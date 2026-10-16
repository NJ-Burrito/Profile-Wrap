"""Anthropic Messages API."""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from .base import Provider, ProviderError, Result, schema_instruction
from .wire import post_json

API_VERSION = "2023-06-01"


class AnthropicProvider(Provider):
    def _complete(self, system: str, messages: List[Dict[str, str]],
                  json_schema: Optional[Mapping[str, Any]], max_tokens: int, timeout: float) -> Result:
        key = self.api_key()
        sys_text = system
        if json_schema:
            sys_text = (system + "\n\n" if system else "") + schema_instruction(json_schema)
        payload: Dict[str, Any] = {"model": self.model, "max_tokens": max_tokens, "messages": messages}
        if sys_text:
            payload["system"] = sys_text
        obj = post_json(f"{self.base_url}/v1/messages",
                        {"x-api-key": key, "anthropic-version": API_VERSION}, payload, timeout, (key,))
        blocks = obj.get("content")
        if not isinstance(blocks, list):
            raise ProviderError("bad_response", "the answer had no content list")
        text = "".join(b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text")
        u = obj.get("usage") or {}
        return Result(text=text, raw_id=str(obj.get("id", "")),
                      usage={"input_tokens": int(u.get("input_tokens", 0) or 0),
                             "output_tokens": int(u.get("output_tokens", 0) or 0)})
