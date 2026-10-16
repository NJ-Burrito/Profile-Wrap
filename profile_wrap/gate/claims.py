"""Resolve the claim ids a draft cites into number specs, refusing anything that is not verified."""
from __future__ import annotations

import datetime as _dt
from pathlib import Path

from profile_wrap.facts.numspec import NumSpec
from profile_wrap.facts.registers import Register, load_register

from .findings import FAIL, WARN, finding


def facts_path(ws: Path, cfg: dict) -> Path:
    return ws / cfg["persona"].get("facts_file", "research/facts.md")


def stats_path(ws: Path, cfg: dict) -> Path:
    return facts_path(ws, cfg).parent / "stats.md"


def load_registers(ws: Path, cfg: dict) -> tuple[Register, Register | None, list[dict]]:
    """Facts register (required), stats register (optional unless a stat is cited) and readable problems."""
    problems: list[dict] = []
    facts = load_register(facts_path(ws, cfg), "fact")
    for p in facts.problems:
        problems.append(finding("facts", WARN if "BOM" in p else FAIL, p, token=facts.path.name))
    stats = None
    sp = stats_path(ws, cfg)
    if sp.exists():
        stats = load_register(sp, "stat")
        for p in stats.problems:
            problems.append(finding("facts", WARN if "BOM" in p else FAIL, p, token=sp.name))
    return facts, stats, problems


def resolve_claims(claims, facts: Register, stats: Register | None, cfg: dict,
                   today: _dt.date | None = None) -> tuple[list[NumSpec], list[dict]]:
    """Number specs of the valid cited entries plus a FAIL finding per invalid citation."""
    today = today or _dt.date.today()
    findings: list[dict] = []
    specs: list[NumSpec] = []
    if claims is None:
        return specs, findings
    if not isinstance(claims, list) or not all(isinstance(c, str) for c in claims):
        findings.append(finding("claims", FAIL, "meta.claims must be a list of fact or stat ids, e.g. [\"F01\"]"))
        return specs, findings
    live = bool(not cfg["persona"].get("demo"))
    for cid in dict.fromkeys(c.strip() for c in claims):
        entry = facts.get(cid) or (stats.get(cid) if stats else None)
        if entry is None:
            where = f"{facts.path.name}" + (f" or {stats.path.name}" if stats else "")
            findings.append(finding("claims", FAIL, f"claim {cid} not found in {where}", token=cid))
            continue
        if entry.status != "verified":
            findings.append(finding("claims", FAIL,
                                    f"claim {cid} is '{entry.status}'; only a verified entry can back a post "
                                    f"(run `profile-wrap {'facts' if entry.kind == 'fact' else 'stats'} verify {cid}` in a terminal)",
                                    token=cid))
            continue
        if entry.demo and live:
            findings.append(finding("claims", FAIL, f"claim {cid} is a demo fact and cannot back a live workspace",
                                    token=cid))
            continue
        if entry.kind == "stat":
            if entry.grade != "A":
                findings.append(finding("claims", FAIL, f"stat {cid} is grade '{entry.grade}'; only grade A may be quoted",
                                        token=cid))
                continue
            exp = entry.expires
            if exp is None or exp < today:
                findings.append(finding("claims", FAIL, f"stat {cid} expired on {exp or 'an unknown date'}; refresh it",
                                        token=cid))
                continue
        specs.extend(entry.specs)
    return specs, findings
