"""Bilingual pair parity: the pair is the unit, so both halves exist, cite the same claims and are gated together.

Active only when `meta.pair` names another draft folder. Deterministic and offline; it never edits the partner.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from .findings import FAIL, WARN, finding


def _claims(meta: dict) -> set[str]:
    c = meta.get("claims")
    return {x.strip() for x in c if isinstance(x, str)} if isinstance(c, list) else set()


def check_pair(slug: str, meta: dict, drafts_dir: Path, *, hash_of: Callable[[Path], str] | None = None,
               mode: str = "warn") -> list[dict]:
    """Findings for the pair named in `meta.pair`. mode: warn, fail or off."""
    partner = str(meta.get("pair") or "").strip()
    if mode == "off" or not partner:
        return []
    sev = FAIL if mode == "fail" else WARN
    out: list[dict] = []
    pdir = drafts_dir / partner
    if partner == slug:
        return [finding("pair", FAIL, "meta.pair names the draft itself", token=partner)]
    if not (pdir / "meta.json").is_file():
        return [finding("pair", sev, f"pair partner '{partner}' has no draft folder with a meta.json; write the other "
                        f"half or remove meta.pair", token=partner)]
    try:
        pmeta = json.loads((pdir / "meta.json").read_bytes().decode("utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return [finding("pair", sev, f"pair partner '{partner}' meta.json is unreadable: {exc}", token=partner)]
    if not isinstance(pmeta, dict):
        return [finding("pair", sev, f"pair partner '{partner}' meta.json is not a JSON object", token=partner)]
    if str(pmeta.get("pair") or "").strip() != slug:
        out.append(finding("pair", sev, f"pair partner '{partner}' does not name '{slug}' in its own meta.pair; "
                           f"a pair changes together, so set it on both halves", token=partner))
    mine, theirs = _claims(meta), _claims(pmeta)
    if mine != theirs:
        diff = sorted(mine ^ theirs)
        out.append(finding("pair", sev, f"the two halves cite different claims ({', '.join(diff)}); both sides "
                           f"must make the same claims", token=",".join(diff)))
    gj = pdir / "gates.json"
    if not gj.is_file():
        out.append(finding("pair", sev, f"pair partner '{partner}' has not been gated; run `profile-wrap gate {partner}`",
                           token=partner))
    elif hash_of is not None:
        try:
            old = json.loads(gj.read_bytes().decode("utf-8-sig")).get("input_sha256", "")
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, AttributeError):
            old = ""
        if old and old != hash_of(pdir):
            out.append(finding("pair", sev, f"pair partner '{partner}' changed since its last gate; re-run "
                               f"`profile-wrap gate {partner}` (the pair is gated together)", token=partner))
    return out
