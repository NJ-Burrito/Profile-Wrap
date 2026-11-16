"""Version-like strings must match a cited fact; cited volatile facts must be fresh.

A caption that says "v0.1.1" while the register says 0.3.1 is the stale-fact failure the gate exists to stop.
The gate cannot fetch a repository: it proves a version agrees with your register, and that the register entry
was confirmed recently enough. Re-reading the source is the human or agent step (see `facts stale`).
"""
from __future__ import annotations

import datetime as _dt
import re

from profile_wrap.facts.registers import Entry, Register, fact_checked_on

from .findings import FAIL, WARN, finding

# Products whose version is not a claim about the user's work (kept in line with the exemptions in numbers.py).
_PLATFORMS = {"python", "node", "nodejs", "npm", "chrome", "chromium", "firefox", "safari", "edge", "windows",
              "macos", "ios", "ipados", "android", "linux", "ubuntu", "debian", "java", "jdk", "go", "golang",
              "rust", "ruby", "php", "gpt", "claude", "gemini", "llama", "excel", "word", "office", "pdf",
              "html", "css", "http", "tls", "ssl", "ipv"}
_URL = re.compile(r"(?:https?://|www\.)\S+|\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b", re.IGNORECASE)
_DOTTED = r"\d+(?:\.\d+)+"
# "v1.2", "version 3", "release 1.2.0" (prefixed) or a bare "1.2.3" (three or more parts)
_VERSION = re.compile(
    rf"(?<![\w.])(?P<prefix>(?:version|release|ver\.?)\s*v?\s*|v)(?P<num>{_DOTTED}|\d+)(?![\w]|\.\d)"
    rf"|(?<![\w.\-/])(?P<bare>\d+\.\d+\.\d+(?:\.\d+)?)(?![\w]|\.\d)", re.IGNORECASE)
_PREV_WORD = re.compile(r"([A-Za-z]+)\W*$")


def _core(token: str) -> str:
    """The numeric core of a version token: 'v0.3.1' -> '0.3.1'."""
    m = re.search(r"\d+(?:\.\d+)*", token)
    return m.group(0) if m else token


def version_tokens(text: str) -> list[tuple[str, str]]:
    """(matched text, numeric core) for every version-like string, skipping URLs and platform versions."""
    t = _URL.sub(" ", text)
    out: list[tuple[str, str]] = []
    for m in _VERSION.finditer(t):
        raw = m.group(0).strip()
        num = m.group("num") or m.group("bare")
        prefix = (m.group("prefix") or "").strip().casefold()
        if prefix == "v" and "." not in num:
            continue  # a bare "v2" is a label, not a version claim
        before = t[:m.start()]
        pm = _PREV_WORD.search(before[-30:])
        if pm and pm.group(1).casefold() in _PLATFORMS:
            continue
        out.append((raw, _core(num)))
    return out


def _fact_text(e: Entry) -> str:
    return " ".join([e.text, e.numbers_raw, e.source, e.row.get("evidence", "")])


def _supports(core: str, corpus: str) -> bool:
    if "." in core:
        return re.search(rf"(?<![\d.]){re.escape(core)}(?![\d]|\.\d)", corpus) is not None
    return re.search(rf"(?:v|version|release)\s*{re.escape(core)}(?![\d]|\.\d)", corpus, re.IGNORECASE) is not None


def cited_entries(claims, facts: Register, stats: Register | None) -> list[Entry]:
    """The verified facts and stats a draft cites (invalid citations are reported by the claims check)."""
    out: list[Entry] = []
    if not isinstance(claims, list):
        return out
    for cid in dict.fromkeys(c.strip() for c in claims if isinstance(c, str)):
        e = facts.get(cid) or (stats.get(cid) if stats else None)
        if e is not None and e.status == "verified":
            out.append(e)
    return out


def check_versions(surfaces: dict[str, str], cited: list[Entry], mode: str = "warn") -> list[dict]:
    """A version-like string must appear in a cited verified fact. mode: warn, fail or off."""
    if mode == "off":
        return []
    sev = FAIL if mode == "fail" else WARN
    corpus = " ".join(_fact_text(e) for e in cited)
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for surface, text in surfaces.items():
        for raw, core in version_tokens(text):
            if (surface, core) in seen:
                continue
            seen.add((surface, core))
            if _supports(core, corpus):
                continue
            if cited:
                msg = (f"version '{raw}' is not in any cited fact; re-read the source today and cite a fact that "
                       f"says it (or supersede the old fact)")
            else:
                msg = f"version '{raw}' with no cited fact; add a verified fact for it and cite it in meta.claims"
            out.append(finding("versions", sev, msg, surface=surface, token=raw))
    return out


def check_volatile_age(cited: list[Entry], max_days: int | None, today: _dt.date | None = None) -> list[dict]:
    """WARN for each cited volatile fact last confirmed more than max_days ago (0 or None turns it off)."""
    if not max_days or max_days < 0:
        return []
    when = today or _dt.date.today()
    out: list[dict] = []
    for e in cited:
        if e.kind != "fact" or not e.volatile:
            continue
        d = fact_checked_on(e)
        age = (when - d).days if d is not None else None
        if age is None or age > max_days:
            how = "has no date" if age is None else f"was last confirmed {age} days ago"
            out.append(finding("claims", WARN,
                               f"volatile fact {e.id} {how} (limit {max_days}); re-read its source today, then add a "
                               f"fact that supersedes it", token=e.id))
    return out
