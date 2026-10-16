"""Findings: what each check reports. A finding is a plain dict so gates.json can hold it unchanged."""
from __future__ import annotations

from typing import Any

FAIL = "fail"
WARN = "warn"
OVERRIDDEN = "overridden"


def finding(check: str, severity: str, message: str, *, surface: str = "", token: str = "", **extra: Any) -> dict:
    """One finding. `token` is the exact text an override must name to waive it."""
    out: dict[str, Any] = {"check": check, "severity": severity, "surface": surface, "token": token,
                           "message": message}
    out.update(extra)
    return out


def fails(findings: list[dict]) -> list[dict]:
    return [f for f in findings if f["severity"] == FAIL]


def warns(findings: list[dict]) -> list[dict]:
    return [f for f in findings if f["severity"] == WARN]
