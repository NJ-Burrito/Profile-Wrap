"""API-key shapes of the supported providers.

Imported by ``profile_wrap.leakcheck`` (rules) and by the providers' own redaction. This module
imports nothing heavy so the leak scan can load it. Each entry is ``(rule id, regex source)``.
"""
from __future__ import annotations

import re
from typing import List, Tuple

KEY_RULES: Tuple[Tuple[str, str], ...] = (
    ("token-anthropic", r"\bsk-ant-[A-Za-z0-9_-]{10,}"),
    ("token-openrouter", r"\bsk-or-v1-[A-Za-z0-9_-]{20,}"),
    ("token-sk", r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{24,}"),
    ("token-gemini", r"\bAIza[0-9A-Za-z_-]{30,}"),
)

_COMPILED: List["re.Pattern[str]"] = [re.compile(src) for _rule, src in KEY_RULES]


def looks_like_key(text: str) -> bool:
    """True when ``text`` contains something shaped like a provider API key."""
    return any(rx.search(text) for rx in _COMPILED)


def redact(text: str, secrets: Tuple[str, ...] = ()) -> str:
    """Replace known secret values and any key-shaped string with ``[REDACTED]``."""
    for s in secrets:
        if s and len(s) >= 6:
            text = text.replace(s, "[REDACTED]")
    for rx in _COMPILED:
        text = rx.sub("[REDACTED]", text)
    return text
