"""``Linkedin-Version`` handling: a dated table, ``auto`` selection, sunset refusal.

The table lives in ``data/linkedin-versions.json``. A newer copy written by
``profile-wrap api-versions --refresh`` goes to the data dir (never into the plugin tree) and wins when
its ``retrieved`` date is later.
"""
from __future__ import annotations

import datetime as _dt
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .. import paths
from ..atomic import atomic_write_json
from ..fsutil import read_json

VERSION_RE = re.compile(r"^\d{6}$")
VERSIONS_PAGE = "https://learn.microsoft.com/en-us/linkedin/marketing/versioning"
VERSIONS_HOST = "learn.microsoft.com"


class VersionError(Exception):
    """The configured API version cannot be used; the message says why and what to do."""


def override_path() -> Path:
    return paths.data_dir() / "linkedin-versions.json"


def load_table(plugin_table: Optional[Path] = None, override: Optional[Path] = None) -> Dict[str, Any]:
    base_path = plugin_table or paths.resource("data", "linkedin-versions.json")
    table = read_json(base_path)
    extra_path = override if override is not None else override_path()
    try:
        extra = read_json(extra_path, default={}) if Path(extra_path).exists() else {}
    except ValueError:
        extra = {}
    if isinstance(extra, dict) and str(extra.get("retrieved", "")) > str(table.get("retrieved", "")):
        table = extra
    return table


def _date(text: Any) -> Optional[_dt.date]:
    if not text:
        return None
    try:
        return _dt.date.fromisoformat(str(text))
    except ValueError:
        return None


def classify(version: str, table: Dict[str, Any], today: _dt.date, warn_days: int = 60) -> Tuple[str, Optional[int]]:
    """('ok' | 'near_sunset' | 'sunset' | 'unknown', days_left)."""
    for entry in table.get("versions", []):
        if entry.get("version") != version:
            continue
        sunset = _date(entry.get("sunset"))
        if sunset is None:
            return "ok", None
        left = (sunset - today).days
        if left < 0:
            return "sunset", left
        return ("near_sunset" if left <= warn_days else "ok"), left
    return "unknown", None


def newest_usable(table: Dict[str, Any], today: _dt.date) -> Optional[str]:
    usable = []
    for entry in table.get("versions", []):
        v = str(entry.get("version", ""))
        sunset = _date(entry.get("sunset"))
        if VERSION_RE.match(v) and (sunset is None or sunset >= today):
            usable.append(v)
    return max(usable) if usable else None


def resolve(cfg: Dict[str, Any], today: Optional[_dt.date] = None,
            table: Optional[Dict[str, Any]] = None) -> Tuple[str, List[str]]:
    """The version to send and a list of warnings. Raises ``VersionError`` for a sunset version."""
    today = today or _dt.date.today()
    table = table if table is not None else load_table()
    li = cfg.get("linkedin", {})
    wanted = str(li.get("api_version", "auto"))
    warn_days = int(li.get("sunset_warn_days", 60))
    warnings: List[str] = []
    if wanted == "auto":
        version = newest_usable(table, today)
        if version is None:
            raise VersionError(
                "every API version in data/linkedin-versions.json is past its sunset date. "
                "Run 'profile-wrap api-versions --refresh' and set linkedin.api_version.")
    else:
        if not VERSION_RE.match(wanted):
            raise VersionError(f"linkedin.api_version '{wanted}' must be 'auto' or YYYYMM")
        version = wanted
    state, left = classify(version, table, today, warn_days)
    if state == "sunset":
        raise VersionError(
            f"API version {version} is past its sunset date ({-(left or 0)} days ago). "
            "Set linkedin.api_version to 'auto' or a newer version, then run 'profile-wrap api-versions'.")
    if state == "near_sunset":
        warnings.append(f"API version {version} sunsets in {left} days; plan to move to a newer version")
    if state == "unknown":
        warnings.append(f"API version {version} is not in the dated table; "
                        "run 'profile-wrap api-versions --refresh' to check it")
    stale = _date(table.get("retrieved"))
    if stale is not None and (today - stale).days > 180:
        warnings.append(f"the version table is {(today - stale).days} days old; refresh it")
    return version, warnings


def report(cfg: Dict[str, Any], today: Optional[_dt.date] = None,
           table: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    today = today or _dt.date.today()
    table = table if table is not None else load_table()
    warn_days = int(cfg.get("linkedin", {}).get("sunset_warn_days", 60))
    rows = []
    for entry in table.get("versions", []):
        state, left = classify(str(entry.get("version")), table, today, warn_days)
        rows.append({"version": entry.get("version"), "sunset": entry.get("sunset"),
                     "state": state, "days_left": left})
    out: Dict[str, Any] = {"retrieved": table.get("retrieved"), "versions": rows}
    try:
        version, warnings = resolve(cfg, today, table)
        out.update(selected=version, warnings=warnings, ok=True)
    except VersionError as exc:
        out.update(selected=None, warnings=[str(exc)], ok=False)
    return out


def refresh(fetch: Callable[[], str], today: Optional[_dt.date] = None,
            write: bool = True) -> Dict[str, Any]:
    """Look at the versioning page text and add YYYYMM versions the table does not list.

    New versions are added with ``sunset: null`` and ``unverified: true``: a human checks the date.
    ``fetch`` returns the page text (injected so tests make no network call).
    """
    today = today or _dt.date.today()
    table = load_table()
    known = {str(e.get("version")) for e in table.get("versions", [])}
    text = fetch()
    seen = sorted({m for m in re.findall(r"\b(20\d{2}(?:0[1-9]|1[0-2]))\b", text)})
    added = [v for v in seen if v not in known and v >= max(known, default="000000")]
    if added:
        table = dict(table)
        table["versions"] = list(table.get("versions", [])) + [
            {"version": v, "sunset": None, "unverified": True} for v in added]
        table["retrieved"] = today.isoformat()
        if write:
            atomic_write_json(override_path(), table)
    return {"added": added, "known": sorted(known), "written": bool(added and write),
            "path": str(override_path()) if added and write else None}
