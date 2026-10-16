"""Time zones: zoneinfo only, aware datetimes, ISO week in the configured zone.

``tzdata`` is a dependency on Windows. When it is missing the functions raise
``TimezoneUnavailable`` with the exact fix instead of a bare ZoneInfoNotFoundError.
"""
from __future__ import annotations

import datetime as dt
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional, Tuple

try:  # pragma: no cover - import guard
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore[assignment,misc]
    ZoneInfoNotFoundError = Exception  # type: ignore[assignment,misc]


class TimezoneUnavailable(RuntimeError):
    """The IANA zone cannot be loaded (unknown name, or tzdata is not installed)."""


# Windows zone names (tzutil /g) to IANA, for the common cases. Anything else falls back to UTC.
WINDOWS_TO_IANA = {
    "UTC": "UTC",
    "GMT Standard Time": "Europe/London",
    "W. Europe Standard Time": "Europe/Berlin",
    "Central Europe Standard Time": "Europe/Budapest",
    "Romance Standard Time": "Europe/Paris",
    "Central European Standard Time": "Europe/Warsaw",
    "E. Europe Standard Time": "Europe/Chisinau",
    "GTB Standard Time": "Europe/Bucharest",
    "FLE Standard Time": "Europe/Kiev",
    "Russian Standard Time": "Europe/Moscow",
    "Turkey Standard Time": "Europe/Istanbul",
    "Jordan Standard Time": "Asia/Amman",
    "Middle East Standard Time": "Asia/Beirut",
    "Syria Standard Time": "Asia/Damascus",
    "Israel Standard Time": "Asia/Jerusalem",
    "Egypt Standard Time": "Africa/Cairo",
    "Arab Standard Time": "Asia/Riyadh",
    "Arabic Standard Time": "Asia/Baghdad",
    "Arabian Standard Time": "Asia/Dubai",
    "Iran Standard Time": "Asia/Tehran",
    "Pakistan Standard Time": "Asia/Karachi",
    "India Standard Time": "Asia/Kolkata",
    "SE Asia Standard Time": "Asia/Bangkok",
    "China Standard Time": "Asia/Shanghai",
    "Singapore Standard Time": "Asia/Singapore",
    "Tokyo Standard Time": "Asia/Tokyo",
    "Korea Standard Time": "Asia/Seoul",
    "AUS Eastern Standard Time": "Australia/Sydney",
    "New Zealand Standard Time": "Pacific/Auckland",
    "South Africa Standard Time": "Africa/Johannesburg",
    "W. Central Africa Standard Time": "Africa/Lagos",
    "E. Africa Standard Time": "Africa/Nairobi",
    "Eastern Standard Time": "America/New_York",
    "Central Standard Time": "America/Chicago",
    "Mountain Standard Time": "America/Denver",
    "Pacific Standard Time": "America/Los_Angeles",
    "US Mountain Standard Time": "America/Phoenix",
    "Alaskan Standard Time": "America/Anchorage",
    "Hawaiian Standard Time": "Pacific/Honolulu",
    "Canada Central Standard Time": "America/Regina",
    "E. South America Standard Time": "America/Sao_Paulo",
    "Argentina Standard Time": "America/Argentina/Buenos_Aires",
    "Mexico Standard Time": "America/Mexico_City",
}


def get_zone(name: str):
    if ZoneInfo is None:  # pragma: no cover
        raise TimezoneUnavailable("zoneinfo needs Python 3.9 or newer")
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError) as exc:
        hint = ""
        if sys.platform == "win32":
            hint = " On Windows install the IANA database with: uv pip install tzdata"
        raise TimezoneUnavailable(
            f"time zone '{name}' cannot be loaded ({exc.__class__.__name__}).{hint}") from exc


def is_valid_timezone(name: str) -> bool:
    try:
        get_zone(name)
    except TimezoneUnavailable:
        return False
    return True


def tzdata_available() -> bool:
    return is_valid_timezone("UTC") or is_valid_timezone("Europe/Lisbon")


def detect_timezone() -> str:
    """Best-effort IANA name for this machine; ``UTC`` when nothing can be found."""
    env = os.environ.get("TZ", "").lstrip(":")
    if env and "/" in env:
        return env
    if sys.platform == "win32":
        try:
            out = subprocess.run(["tzutil", "/g"], capture_output=True, text=True, timeout=10)
            return WINDOWS_TO_IANA.get(out.stdout.strip(), "UTC")
        except (OSError, subprocess.SubprocessError):
            return "UTC"
    try:
        etc = Path("/etc/timezone")
        if etc.is_file():
            name = etc.read_text(encoding="utf-8").strip()
            if name:
                return name
        link = Path("/etc/localtime")
        if link.is_symlink():
            target = os.path.realpath(str(link))
            marker = "zoneinfo/"
            if marker in target:
                return target.split(marker, 1)[1]
    except OSError:
        pass
    return "UTC"


def now(tz_name: str) -> dt.datetime:
    return dt.datetime.now(get_zone(tz_name))


def to_zone(moment: dt.datetime, tz_name: str) -> dt.datetime:
    if moment.tzinfo is None:
        raise ValueError("naive datetime: attach an offset before converting")
    return moment.astimezone(get_zone(tz_name))


def localize(naive: dt.datetime, tz_name: str) -> dt.datetime:
    """Attach a zone to a naive wall-clock time (DST aware, fold=0)."""
    return naive.replace(tzinfo=get_zone(tz_name))


def parse_aware(text: str) -> dt.datetime:
    """Parse an ISO 8601 string that carries an offset."""
    parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"'{text}' has no UTC offset")
    return parsed


def iso_week(moment: dt.datetime, tz_name: str) -> Tuple[int, int]:
    """ISO (year, week) of ``moment`` seen in ``tz_name``."""
    local = to_zone(moment, tz_name) if moment.tzinfo else localize(moment, tz_name)
    iso = local.isocalendar()
    return iso[0], iso[1]


def iso_week_label(moment: dt.datetime, tz_name: str) -> str:
    year, week = iso_week(moment, tz_name)
    return f"{year}-W{week:02d}"


def week_start(moment: dt.datetime, tz_name: str) -> dt.datetime:
    """Monday 00:00 of the ISO week containing ``moment`` in ``tz_name``."""
    local = to_zone(moment, tz_name) if moment.tzinfo else localize(moment, tz_name)
    monday = local.date() - dt.timedelta(days=local.weekday())
    return localize(dt.datetime.combine(monday, dt.time()), tz_name)


def utc_offset_label(moment: dt.datetime) -> Optional[str]:
    off = moment.utcoffset()
    if off is None:
        return None
    minutes = int(off.total_seconds() // 60)
    sign = "+" if minutes >= 0 else "-"
    return f"{sign}{abs(minutes) // 60:02d}:{abs(minutes) % 60:02d}"
