"""Overrides: a human waives one named finding, with a reason, and the waiver is logged to gates.json.

meta.json carries   "overrides": [{"check": "numbers", "token": "7 bugs", "reason": "counted in the sprint board"}]
A waiver matches a finding by check name and token (case-insensitive). Reasons are required by default,
the number of waivers per post is capped, and a waiver that matches nothing is reported, not ignored.
"""
from __future__ import annotations

import datetime as _dt
from typing import Any

from .findings import FAIL, OVERRIDDEN, WARN, finding


def _norm(s: str) -> str:
    return " ".join(str(s).casefold().split())


def apply_overrides(findings: list[dict], requested, cfg: dict) -> tuple[list[dict], list[dict], list[dict]]:
    """Returns (findings with waived ones marked, override log rows, extra findings about the overrides)."""
    policy = cfg["gate"]["overrides"]
    log: list[dict] = []
    extra: list[dict] = []
    if requested in (None, [], ()):
        return findings, log, extra
    if not isinstance(requested, list):
        extra.append(finding("overrides", FAIL, "meta.overrides must be a list of {check, token, reason}"))
        return findings, log, extra
    stamp = _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()
    if not policy.get("allow", True):
        extra.append(finding("overrides", FAIL, "overrides are switched off (gate.overrides.allow=false)"))
        return findings, log, extra
    cap = int(policy.get("max_per_post", 2))
    for i, req in enumerate(requested):
        row: dict[str, Any] = {"check": "", "token": "", "reason": "", "applied": False, "matched": 0,
                               "at": stamp}
        if not isinstance(req, dict):
            extra.append(finding("overrides", FAIL, f"override #{i + 1} must be an object"))
            log.append(row)
            continue
        row.update({"check": str(req.get("check", "")), "token": str(req.get("token", "")),
                    "reason": str(req.get("reason", "")).strip()})
        if i >= cap:
            extra.append(finding("overrides", FAIL, f"override #{i + 1} ignored: at most {cap} per post",
                                 token=row["token"]))
            log.append(row)
            continue
        if policy.get("require_reason", True) and len(row["reason"]) < 8:
            extra.append(finding("overrides", FAIL, f"override of {row['check']}/{row['token']} needs a reason "
                                 f"(at least 8 characters)", token=row["token"]))
            log.append(row)
            continue
        if not row["check"] or not row["token"]:
            extra.append(finding("overrides", FAIL, f"override #{i + 1} needs both check and token"))
            log.append(row)
            continue
        for f in findings:
            if f["severity"] in (FAIL, WARN) and f["check"] == row["check"] and _norm(f["token"]) == _norm(row["token"]):
                f["severity"] = OVERRIDDEN if f["severity"] == FAIL else f["severity"]
                f["override_reason"] = row["reason"]
                row["matched"] += 1
        row["applied"] = row["matched"] > 0
        if not row["applied"]:
            extra.append(finding("overrides", WARN, f"override {row['check']}/{row['token']} matched no finding",
                                 token=row["token"]))
        log.append(row)
    return findings, log, extra
