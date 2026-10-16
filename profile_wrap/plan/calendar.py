"""The content calendar: ``strategy/calendar.json`` (source of truth) and ``strategy/calendar.md`` (generated).

Every write is atomic (temp file plus ``os.replace``) and every read-modify-write holds a lock, so a
crash or a second process can never leave half a calendar. ``calendar.md`` is generated from the
JSON, so it cannot go stale.
"""
from __future__ import annotations

import datetime as _dt
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from profile_wrap import paths, policy, schemalite
from profile_wrap.atomic import atomic_write_json, atomic_write_text
from profile_wrap.plan import holidays as hol
from profile_wrap.plan.locking import guarded
from profile_wrap.plan.spread import parse_hhmm

CALENDAR_REL = "strategy/calendar.json"
MARKDOWN_REL = "strategy/calendar.md"
STATUSES = ("planned", "built", "posted", "skipped", "blocked")
OPEN_TITLE = "Open slot"
SCHEMA_FILE = "calendar.schema.json"


class CalendarError(ValueError):
    pass


def calendar_path(workspace: Path) -> Path:
    return Path(workspace) / CALENDAR_REL


def empty() -> Dict[str, Any]:
    return {"schema_version": policy.SCHEMA_VERSION, "entries": []}


def load(workspace: Path) -> Dict[str, Any]:
    path = calendar_path(workspace)
    if not path.is_file():
        return empty()
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except ValueError as exc:
        raise CalendarError(f"{CALENDAR_REL} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("entries", []), list):
        raise CalendarError(f"{CALENDAR_REL} must be an object with an 'entries' list")
    data.setdefault("schema_version", policy.SCHEMA_VERSION)
    data.setdefault("entries", [])
    return data


def save(workspace: Path, cal: Dict[str, Any]) -> Path:
    cal["entries"] = sorted(cal["entries"], key=lambda e: (e.get("date", ""), e.get("slug", "")))
    path = calendar_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    return atomic_write_json(path, cal)


def update(workspace: Path, fn: Callable[[Dict[str, Any]], Any], wait: float = 30.0) -> Any:
    """Read, change and write the calendar under one lock. ``fn`` mutates the dict it is given."""
    with guarded(workspace, "calendar", stale_after=600, wait=wait):
        cal = load(workspace)
        result = fn(cal)
        save(workspace, cal)
        return result


def set_status(workspace: Path, slug: str, status: str, **fields: Any) -> bool:
    if status not in STATUSES:
        raise CalendarError(f"status must be one of {', '.join(STATUSES)}, not {status!r}")

    def change(cal: Dict[str, Any]) -> bool:
        for e in cal["entries"]:
            if e.get("slug") == slug:
                e["status"] = status
                e.update(fields)
                return True
        return False

    return bool(update(workspace, change))


def find(cal: Mapping[str, Any], slug: str) -> Optional[Dict[str, Any]]:
    for e in cal.get("entries", []):
        if e.get("slug") == slug:
            return e
    return None


def is_open(entry: Mapping[str, Any]) -> bool:
    """An open slot is a placeholder made by ``fill``; it is not built until the planner briefs it."""
    return bool(entry.get("open"))


def add_entry(cal: Dict[str, Any], *, date: str, slug: str, title: str, lang: str, format: str,
              status: str = "planned", **extra: Any) -> Dict[str, Any]:
    if find(cal, slug):
        raise CalendarError(f"slug already in the calendar: {slug}")
    entry: Dict[str, Any] = {"date": date, "slug": slug, "lang": lang, "format": format,
                             "title": title, "status": status}
    entry.update({k: v for k, v in extra.items() if v not in (None, "", [])})
    cal["entries"].append(entry)
    return entry


# ----------------------------------------------------------------------------- validation

@dataclass
class Report:
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def err(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)


def _parse_date(text: str) -> Optional[_dt.date]:
    try:
        return _dt.date.fromisoformat(text)
    except (TypeError, ValueError):
        return None


def _is_pair(group: Sequence[Mapping[str, Any]]) -> bool:
    """Two entries are a bilingual pair when one names the other's slug, or both name the same pair id."""
    if len(group) != 2:
        return False
    a, b = group
    for x, y in ((a, b), (b, a)):
        if x.get("pair") and x["pair"] in (y.get("slug"), y.get("pair")):
            return True
    return False


def verified_claim_ids(workspace: Path, cfg: Mapping[str, Any]) -> Optional[Dict[str, str]]:
    """``{id: status}`` of the facts register, or None when it cannot be read."""
    try:
        from profile_wrap.facts import registers
    except ImportError:
        return None
    facts = Path(workspace) / (cfg.get("persona", {}).get("facts_file") or "research/facts.md")
    reg = registers.load_register(facts, "fact")
    if not reg.exists:
        return None
    return {e.id: ("demo" if e.demo and not cfg.get("persona", {}).get("demo") else e.status)
            for e in reg.entries}


def validate(cal: Mapping[str, Any], cfg: Mapping[str, Any], *, workspace: Optional[Path] = None,
             holidays: Optional[hol.Holidays] = None,
             claims: Optional[Mapping[str, str]] = None) -> Report:
    """Duplicates, status, language, window, holidays, claim ids, cadence."""
    rep = Report()
    try:
        schema = schemalite.load_schema(paths.resource("schema", SCHEMA_FILE))
        for msg in schemalite.validate(dict(cal), schema):
            rep.err(f"schema: {msg}")
    except (OSError, ValueError) as exc:  # a missing schema is a packaging fault, say so plainly
        rep.warn(f"calendar schema not checked: {exc}")
    entries = [e for e in cal.get("entries", []) if isinstance(e, dict)]
    holidays = holidays if holidays is not None else (hol.load(workspace, dict(cfg)) if workspace else hol.Holidays())
    if claims is None and workspace is not None:
        claims = verified_claim_ids(workspace, cfg)
    langs = set(cfg.get("persona", {}).get("languages") or [])
    formats = set(cfg.get("posting", {}).get("formats_enabled") or [])
    weekdays = list(cfg.get("posting", {}).get("weekdays") or [])
    per_week = int(cfg.get("posting", {}).get("per_week", 3))
    window = cfg.get("posting", {}).get("window", {"start": "09:00", "end": "12:29"})

    seen_slug: Dict[str, int] = {}
    by_date: Dict[str, List[Dict[str, Any]]] = {}
    for i, e in enumerate(entries):
        slug = e.get("slug", f"#{i}")
        if slug in seen_slug:
            rep.err(f"duplicate slug: {slug}")
        seen_slug[slug] = i
        by_date.setdefault(e.get("date", ""), []).append(e)
    for date, group in by_date.items():
        if len(group) > 1 and not _is_pair(group):
            rep.err(f"two entries on {date}: {', '.join(g.get('slug', '?') for g in group)} "
                    "(only the two halves of one bilingual pair may share a date)")

    for e in entries:
        slug = e.get("slug", "?")
        day = _parse_date(e.get("date", ""))
        live = e.get("status") not in ("skipped", "posted")
        if langs and e.get("lang") and e["lang"].split("-")[0] not in {ln.split("-")[0] for ln in langs}:
            rep.err(f"{slug}: language '{e['lang']}' is not in persona.languages {sorted(langs)}")
        if formats and e.get("format") and e["format"] not in formats and live:
            rep.warn(f"{slug}: format '{e['format']}' is not in posting.formats_enabled")
        if day is not None and live:
            name = holidays.blocked(day)
            if name:
                rep.err(f"{slug}: {e['date']} is a blocked holiday ({name})")
            win, _shift = holidays.shifted_window(day, (window.get("start", "09:00"), window.get("end", "12:29")))
            if weekdays and e.get("status") == "planned":
                short = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")[day.weekday()]
                if short not in weekdays:
                    rep.warn(f"{slug}: {short} is not in posting.weekdays {weekdays}")
            if e.get("time"):
                try:
                    t = parse_hhmm(e["time"])
                    if not (parse_hhmm(win[0]) <= t <= parse_hhmm(win[1])) and not e.get("time_reason"):
                        rep.err(f"{slug}: time {e['time']} is outside the window {win[0]}-{win[1]}; "
                                "add a time_reason or move it")
                except ValueError:
                    rep.err(f"{slug}: bad time '{e['time']}' (use HH:MM)")
        if claims is not None:
            for cid in e.get("claims", []) or []:
                st = claims.get(cid)
                if st is None:
                    rep.err(f"{slug}: claim {cid} is not in the facts register")
                elif st != "verified" and live and not is_open(e):
                    rep.err(f"{slug}: claim {cid} is '{st}', not verified")
        elif e.get("claims"):
            rep.warn(f"{slug}: claims not checked (no facts register)")

    weeks: Dict[str, int] = {}
    for e in entries:
        day = _parse_date(e.get("date", ""))
        if day is not None and e.get("status") in ("planned", "built", "posted"):
            iso = day.isocalendar()
            weeks[f"{iso[0]}-W{iso[1]:02d}"] = weeks.get(f"{iso[0]}-W{iso[1]:02d}", 0) + 1
    for wk, n in sorted(weeks.items()):
        if n > policy.POSTS_PER_WEEK_MAX:
            rep.err(f"{wk}: {n} posts is above the ceiling of {policy.POSTS_PER_WEEK_MAX} a week")
        elif n > per_week:
            rep.warn(f"{wk}: {n} posts is above posting.per_week={per_week}")
    return rep


# ----------------------------------------------------------------------------- generated view

def render_md(cal: Mapping[str, Any]) -> str:
    rows = sorted((e for e in cal.get("entries", []) if isinstance(e, dict)),
                  key=lambda e: (e.get("date", ""), e.get("slug", "")))
    out = ["<!-- generated by `profile-wrap calendar render-md` from calendar.json; do not edit -->",
           "# Content calendar", "",
           "| Date | Time | Lang | Format | Pillar | Title | Status |",
           "|---|---|---|---|---|---|---|"]
    for e in rows:
        title = str(e.get("title", "")).replace("|", "\\|")
        out.append(f"| {e.get('date', '')} | {e.get('time', '')} | {e.get('lang', '')} | "
                   f"{e.get('format', '')} | {e.get('pillar', '')} | {title} | {e.get('status', '')} |")
    out.append("")
    return "\n".join(out)


def write_md(workspace: Path, cal: Mapping[str, Any]) -> Path:
    path = Path(workspace) / MARKDOWN_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    return atomic_write_text(path, render_md(cal))


# ----------------------------------------------------------------------------- fill

def _weekday_short(day: _dt.date) -> str:
    return ("mon", "tue", "wed", "thu", "fri", "sat", "sun")[day.weekday()]


def fill(cal: Dict[str, Any], cfg: Mapping[str, Any], *, weeks: int, start: Optional[_dt.date] = None,
         holidays: Optional[hol.Holidays] = None) -> List[Dict[str, Any]]:
    """Add open slots for the next ``weeks`` weeks on the configured weekdays.

    Slots skip blocked holidays and days that already have an entry, keep to ``posting.per_week``,
    and rotate the pillars by their ``share``. An open slot has a placeholder title and ``open: true``;
    ``build-week`` leaves it alone until a planner replaces the title and clears the flag.
    """
    if weeks < 1:
        raise CalendarError("weeks must be at least 1")
    posting = cfg.get("posting", {})
    persona = cfg.get("persona", {})
    per_week = min(int(posting.get("per_week", 3)), policy.POSTS_PER_WEEK_MAX)
    weekdays = list(posting.get("weekdays") or ["mon", "wed", "thu"])
    lang = persona.get("primary_language") or (persona.get("languages") or ["en"])[0]
    fmts = list(posting.get("formats_enabled") or ["text"])
    pillars = [p for p in (persona.get("pillars") or []) if p.get("id")]
    holidays = holidays or hol.Holidays()
    day0 = start or _dt.date.today()
    taken = {e.get("date") for e in cal["entries"]}
    counts: Dict[str, int] = {p["id"]: 0 for p in pillars}
    for e in cal["entries"]:
        if e.get("pillar") in counts:
            counts[e["pillar"]] += 1
    added: List[Dict[str, Any]] = []
    # ISO weeks, so "per week" means the calendar week the post falls in
    per_iso: Dict[str, int] = {}
    for e in cal["entries"]:
        d = _parse_date(e.get("date", ""))
        if d is not None and e.get("status") != "skipped":
            iso = d.isocalendar()
            per_iso[f"{iso[0]}-{iso[1]}"] = per_iso.get(f"{iso[0]}-{iso[1]}", 0) + 1
    for offset in range(weeks * 7):
        day = day0 + _dt.timedelta(days=offset)
        iso = day.isocalendar()
        key = f"{iso[0]}-{iso[1]}"
        if _weekday_short(day) not in weekdays or day.isoformat() in taken:
            continue
        if per_iso.get(key, 0) >= per_week or holidays.blocked(day):
            continue
        pillar = ""
        if pillars:
            total = sum(counts.values()) + 1
            pillar = max(pillars, key=lambda p: (float(p.get("share", 0)) * total - counts[p["id"]], p["id"]))["id"]
            counts[pillar] += 1
        slug = f"{day.isoformat()}-open-slot"
        entry = add_entry(cal, date=day.isoformat(), slug=slug, title=OPEN_TITLE, lang=lang,
                          format=fmts[len(added) % len(fmts)], pillar=pillar, open=True)
        per_iso[key] = per_iso.get(key, 0) + 1
        taken.add(day.isoformat())
        added.append(entry)
    return added
