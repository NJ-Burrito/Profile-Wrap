"""The same text rules for short texts: comments, replies and connection notes.

Used by njli.engage before a draft is queued. Nothing here posts or sends anything.
"""
from __future__ import annotations

from pathlib import Path

from . import numbers as nums
from .arabic import check_arabic
from .claims import load_registers, resolve_claims
from .config import load_config, resolve_workspace
from .findings import FAIL, WARN, finding
from .rules import TextContext, load_banned, scan_text
from .textnorm import is_arabic

try:  # WP1 owns policy.py; the hard ceiling for a connection note is 200 characters
    from njli import policy as _policy  # type: ignore
    NOTE_CEILING = int(_policy.CONNECT_NOTE_MAX)
except Exception:  # pragma: no cover - policy.py not present while WP2 is built alone
    NOTE_CEILING = 200

KINDS = ("comment", "reply", "note")


def check_text(text: str, kind: str = "comment", workspace: str | Path | None = None, *, cfg: dict | None = None,
               claims: list[str] | None = None) -> dict:
    """Gate one short text. Returns {"ok", "kind", "findings", "fails", "warnings"}; never raises on bad input."""
    ws = resolve_workspace(workspace)
    if cfg is None:
        cfg, _ = load_config(ws)
    g, persona = cfg["gate"], cfg["persona"]
    found: list[dict] = []
    if kind not in KINDS:
        found.append(finding("kind", FAIL, f"unknown text kind '{kind}'; use one of {', '.join(KINDS)}"))
        return _result(kind, found)
    body = text or ""
    if not body.strip():
        found.append(finding("length", FAIL, f"{kind} is empty", surface=kind))
        return _result(kind, found)
    limit = min(int(cfg["engagement"]["connect"].get("note_max", 200)), NOTE_CEILING) if kind == "note" \
        else int(cfg["engagement"]["comments"].get("max_chars", 1250))
    if len(body.strip()) > limit:
        found.append(finding("length", FAIL, f"{kind} is {len(body.strip())} characters (max {limit})", surface=kind,
                             token="length"))
    banned = load_banned(g.get("banned_files", []), ws, g.get("extra_banned", []))
    found.extend(finding("slop", FAIL, p) for p in banned.problems)
    ctx = TextContext(banned, list(persona.get("private_terms", [])), list(persona.get("never_say", [])),
                      goal=persona.get("goal", "authority"), em_dash=g["em_dash"], en_dash=g["en_dash"],
                      links_in_body="fail", hashtags_max=0 if kind == "note" else g["hashtags_max"])
    found.extend(scan_text(kind, body, ctx, is_caption=True))
    if is_arabic(body):
        found.extend(check_arabic(kind, body))
    facts, stats, reg_problems = load_registers(ws, cfg)
    specs: list = []
    if claims:
        found.extend(reg_problems)
        specs, cf = resolve_claims(claims, facts, stats, cfg)
        found.extend(cf)
    found.extend(nums.check_numbers({kind: body}, specs, min_bare=int(g["numbers"].get("min_bare_digit", 10)),
                                    number_words=g["numbers"].get("number_words", "warn")))
    return _result(kind, found)


def _result(kind: str, found: list[dict]) -> dict:
    fails = [f"{f['check']}: {f['message']}" for f in found if f["severity"] == FAIL]
    warns = [f"{f['check']}: {f['message']}" for f in found if f["severity"] == WARN]
    return {"ok": not fails, "kind": kind, "findings": found, "fails": fails, "warnings": warns}
