"""The content calendar: ``strategy/calendar.json`` (source of truth) and ``strategy/calendar.md`` (generated).

Every write is atomic (temp file plus ``os.replace``) and every read-modify-write holds a lock, so a
crash or a second process can never leave half a calendar. ``calendar.md`` is generated from the
JSON, so it cannot go stale.
"""
from __future__ import annotations

import datetime as _dt
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from profile_wrap import paths, policy, schemalite
from profile_wrap.atomic import atomic_write_bytes, atomic_write_json, atomic_write_text
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

    for msg in subject_warnings(entries, cfg):
        rep.warn(msg)

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


# ----------------------------------------------------------------------------- angle dedup (no model)

ANGLE_OVERLAP_DEFAULT = 0.5
_ANGLE_STATUSES = ("planned", "built", "posted")
_WORD_RE = re.compile(r"\w+", re.UNICODE)
_STOPWORDS = frozenset(
    "a an and are as at be but by for from has have how i in into is it its my of on or our so that the "
    "their then this to was we what when why with you your not new one "
    "في من على الى إلى عن مع هذا هذه ذلك التي الذي هو هي ما لا أن ان كل او أو ثم".split())


def _tokens(text: Any) -> set:
    words = (w.lower() for w in _WORD_RE.findall(str(text or "")))
    return {w for w in words if len(w) > 2 and w not in _STOPWORDS and not w.isdigit()}


def angle_overlap(a: Any, b: Any) -> float:
    """Share of words two angle texts have in common, 0.0 to 1.0 (Jaccard on lower-cased words, stopwords out)."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _subject_key(subject: Any) -> str:
    return " ".join(str(subject or "").lower().split())


def _angle_text(entry: Mapping[str, Any]) -> str:
    return " ".join(str(entry.get(k) or "") for k in ("angle", "hook"))


def _partners(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
    """True when the two entries are the halves of one bilingual pair."""
    return _is_pair([a, b]) if a is not b else False


def subject_warnings(entries: Sequence[Mapping[str, Any]], cfg: Mapping[str, Any]) -> List[str]:
    """Warnings for entries that repeat an earlier angle on the same ``subject``.

    An entry is compared with the posted, built and planned entries dated before it (or the same day and
    an earlier slug). Pair halves are not compared with each other. ``plan.angle_overlap_max`` (default
    0.5) is the highest word overlap that passes; ``plan.subject_min_gap_days`` (default off) is an
    optional minimum gap in days between two entries on one subject.
    """
    plan = cfg.get("plan", {}) if isinstance(cfg.get("plan", {}), Mapping) else {}
    limit = float(plan.get("angle_overlap_max", ANGLE_OVERLAP_DEFAULT))
    min_gap = int(plan.get("subject_min_gap_days", 0) or 0)
    live = [e for e in entries if e.get("subject") and e.get("status") in _ANGLE_STATUSES]
    live.sort(key=lambda e: (e.get("date", ""), e.get("slug", "")))
    out: List[str] = []
    for i, e in enumerate(live):
        slug, key = e.get("slug", "?"), _subject_key(e["subject"])
        if e.get("status") == "planned" and not is_open(e) and not str(e.get("angle") or "").strip():
            out.append(f"{slug}: subject '{e['subject']}' is set but the entry has no angle")
        for old in live[:i]:
            if _subject_key(old["subject"]) != key or _partners(old, e):
                continue
            score = angle_overlap(_angle_text(old), _angle_text(e))
            if score > limit:
                out.append(f"{slug}: angle repeats {old.get('slug', '?')} ({old.get('date', '')}) on subject "
                           f"'{e['subject']}' (word overlap {score:.0%}, limit {limit:.0%}); pick a new angle")
            d_old, d_new = _parse_date(old.get("date", "")), _parse_date(e.get("date", ""))
            if min_gap and d_old and d_new and 0 <= (d_new - d_old).days < min_gap:
                out.append(f"{slug}: {(d_new - d_old).days} days after {old.get('slug', '?')} on subject "
                           f"'{e['subject']}' (plan.subject_min_gap_days is {min_gap})")
    return out


def prior_angles(subject: str, workspace: Optional[Path] = None, *, exclude_slug: str = "",
                 before: str = "") -> List[Dict[str, str]]:
    """Angles already used or planned for ``subject``, most recent first.

    Reads the calendar (posted, built and planned entries) and, for posted drafts that are in the ledger but
    not in the calendar, their ``meta.json``. Each item has ``slug``, ``date``, ``status``, ``title`` and
    ``angle``. ``exclude_slug`` leaves one entry out (the one being built); ``before`` (YYYY-MM-DD) keeps only
    earlier dates. Deterministic, no model.
    """
    key = _subject_key(subject)
    if not key:
        return []
    if workspace is None:
        from profile_wrap import paths

        workspace = paths.find_workspace() or paths.workspace_path("default")
    ws = Path(workspace)
    found: Dict[str, Dict[str, str]] = {}
    for e in load(ws).get("entries", []):
        if not isinstance(e, dict) or _subject_key(e.get("subject")) != key:
            continue
        if e.get("status") not in _ANGLE_STATUSES or e.get("slug") == exclude_slug:
            continue
        found[e["slug"]] = {"slug": e["slug"], "date": str(e.get("date", "")), "status": str(e["status"]),
                            "title": str(e.get("title", "")), "angle": str(e.get("angle", ""))}
    try:
        from profile_wrap import ledger
        from profile_wrap.fsutil import read_json

        for row in ledger.entries(ws):
            slug = row.get("slug")
            if not slug or slug in found or slug == exclude_slug or row.get("state") not in ledger.LIVE_STATES:
                continue
            meta = read_json(ws / "drafts" / slug / "meta.json", {}) or {}
            if not isinstance(meta, dict) or _subject_key(meta.get("subject")) != key:
                continue
            found[slug] = {"slug": slug, "date": str(row.get("posted_at") or row.get("started_at") or "")[:10],
                           "status": "posted", "title": str(row.get("title") or meta.get("title") or ""),
                           "angle": str(meta.get("angle", ""))}
    except (ImportError, OSError, ValueError):
        pass
    items = [x for x in found.values() if not before or not x["date"] or x["date"] < before]
    return sorted(items, key=lambda x: (x["date"], x["slug"]), reverse=True)


def format_prior_angles(items: Sequence[Mapping[str, str]]) -> str:
    """The text for ``{{prior_angles}}``: one ``- title | angle`` line each, or a plain 'none yet' line."""
    if not items:
        return "(none yet: this is the first post on this subject)"
    lines = (f"- {x.get('title') or x.get('slug')} | {x.get('angle') or '(no angle recorded)'}" for x in items)
    return "\n".join(lines)


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


# ----------------------------------------------------------------------------- insert and shift

_FIXED_STATUSES = ("posted", "skipped", "blocked")
_MAX_SEARCH_DAYS = 800


@dataclass
class Move:
    slug: str
    old_date: str
    new_date: str
    draft_from: str = ""   # scheduled_at before, when the draft is re-dated
    draft_to: str = ""

    def line(self) -> str:
        old, new = _dt.date.fromisoformat(self.old_date), _dt.date.fromisoformat(self.new_date)
        out = f"{self.slug}: {self.old_date} ({_weekday_short(old)}) -> {self.new_date} ({_weekday_short(new)})"
        if self.draft_to:
            out += f"; draft scheduled_at {self.draft_from} -> {self.draft_to}"
        return out


@dataclass
class ReschedulePlan:
    moves: List[Move] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    inserted: Optional[Dict[str, Any]] = None
    draft_meta: Dict[str, Dict[str, Any]] = field(default_factory=dict)  # slug -> new meta.json content

    @property
    def changed(self) -> bool:
        return bool(self.moves or self.inserted)

    def as_dict(self) -> Dict[str, Any]:
        return {"moves": [m.__dict__ for m in self.moves], "warnings": self.warnings, "inserted": self.inserted}

    def lines(self) -> List[str]:
        out = [f"insert {self.inserted['slug']} on {self.inserted['date']}"] if self.inserted else []
        out += [f"move {m.line()}" for m in self.moves]
        out += [f"WARN {w}" for w in self.warnings]
        return out


def _draft_meta(workspace: Optional[Path], slug: str) -> Optional[Dict[str, Any]]:
    if workspace is None:
        return None
    path = Path(workspace) / "drafts" / slug / "meta.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _units(entries: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    """Group entries into units that move together: a bilingual pair is one unit (any dates)."""
    by_slug = {e.get("slug"): e for e in entries}
    seen: set = set()
    units: List[List[Dict[str, Any]]] = []
    for e in sorted(entries, key=lambda x: (x.get("date", ""), x.get("slug", ""))):
        if id(e) in seen:
            continue
        unit = [e]
        seen.add(id(e))
        partner = by_slug.get(e.get("pair")) if e.get("pair") else None
        if partner is None and e.get("pair"):
            partner = next((x for x in entries if x is not e and x.get("pair") == e["pair"]), None)
        if partner is None:
            partner = next((x for x in entries if x is not e and x.get("pair") == e.get("slug")), None)
        if partner is not None and id(partner) not in seen:
            unit.append(partner)
            seen.add(id(partner))
        units.append(unit)
    return units


def _local_redate(old: str, new_day: _dt.date, tz: str) -> str:
    """``old`` (an ISO time with offset) moved to ``new_day`` keeping the local time of day."""
    from profile_wrap import tzutil

    local = tzutil.to_zone(tzutil.parse_aware(old), tz)
    naive = _dt.datetime.combine(new_day, local.timetz().replace(tzinfo=None))
    return tzutil.localize(naive, tz).isoformat(timespec="seconds")


def reschedule(cal: Dict[str, Any], cfg: Mapping[str, Any], *, start: _dt.date, days: int = 1,
               cascade_only: bool = False, reserved: Sequence[_dt.date] = (),
               holidays: Optional[hol.Holidays] = None,
               workspace: Optional[Path] = None) -> ReschedulePlan:
    """Move entries dated ``start`` or later ``days`` days on, to the next free valid day. Mutates ``cal``.

    * ``posted``, ``skipped``, ``blocked`` and ``pinned: true`` entries never move, and neither does a built
      entry whose draft is no longer a ``draft`` (queued, held, posted): that is reported as a warning.
    * A bilingual pair moves as one unit and keeps its offset between the halves.
    * A new day must be in ``posting.weekdays`` (when set), not a blocked holiday, and free.
    * Order is kept: a unit never lands before the one that was ahead of it.
    * ``cascade_only`` moves a unit only when its day is taken (used by ``insert``).
    * A built entry whose draft is still a ``draft`` gets its ``scheduled_at`` re-dated, same time of day.
    """
    if days < 1:
        raise CalendarError("days must be at least 1")
    holidays = holidays if holidays is not None else hol.Holidays()
    weekdays = list(cfg.get("posting", {}).get("weekdays") or [])
    tz = cfg.get("locale", {}).get("timezone") or "UTC"
    plan = ReschedulePlan()
    entries = [e for e in cal.get("entries", []) if isinstance(e, dict)]

    def movable(e: Dict[str, Any]) -> bool:
        if e.get("pinned") or e.get("status") in _FIXED_STATUSES:
            return False
        if e.get("status") == "built":
            meta = _draft_meta(workspace, e.get("slug", ""))
            if meta is not None and meta.get("status") != "draft":
                plan.warnings.append(f"{e.get('slug')}: built and its draft is '{meta.get('status')}', not moved")
                return False
        return True

    fixed: List[Dict[str, Any]] = []
    moving: List[List[Dict[str, Any]]] = []
    for unit in _units(entries):
        dates = [_parse_date(m.get("date", "")) for m in unit]
        if any(d is None for d in dates) or min(d for d in dates if d) < start:
            fixed.extend(unit)
            continue
        ok = [movable(m) for m in unit]
        if all(ok):
            moving.append(unit)
        else:
            if any(ok) and len(unit) == 2:
                plan.warnings.append(f"{unit[0].get('slug')} and {unit[1].get('slug')} are a pair and one half "
                                     "cannot move, so neither moves")
            fixed.extend(unit)
    occupied = {m.get("date") for m in fixed} | {d.isoformat() for d in reserved}
    last: Optional[_dt.date] = None
    for unit in moving:
        base = _parse_date(unit[0]["date"])
        assert base is not None
        offsets = [(_parse_date(m["date"]) - base).days for m in unit]  # type: ignore[operator]
        own = {m["date"] for m in unit}
        if cascade_only and not (own & occupied):
            occupied |= own
            last = base
            continue
        target = base + _dt.timedelta(days=days)
        if last is not None and target <= last:
            target = last + _dt.timedelta(days=1)
        for step in range(_MAX_SEARCH_DAYS):
            cand = target + _dt.timedelta(days=step)
            spots = [cand + _dt.timedelta(days=o) for o in offsets]
            if all(s.isoformat() not in occupied and not holidays.blocked(s)
                   and (not weekdays or _weekday_short(s) in weekdays) for s in spots):
                break
        else:
            raise CalendarError(f"no free day found for {unit[0].get('slug')} within {_MAX_SEARCH_DAYS} days")
        for m, spot in zip(unit, spots):
            move = Move(m["slug"], m["date"], spot.isoformat())
            m["date"] = spot.isoformat()
            occupied.add(m["date"])
            if m.get("status") == "built":
                meta = _draft_meta(workspace, m["slug"])
                if meta is not None and meta.get("scheduled_at"):
                    try:
                        new_at = _local_redate(str(meta["scheduled_at"]), spot, tz)
                    except ValueError:
                        plan.warnings.append(f"{m['slug']}: draft scheduled_at is not a valid time, left as is")
                    else:
                        move.draft_from, move.draft_to = str(meta["scheduled_at"]), new_at
                        plan.draft_meta[m["slug"]] = {**meta, "scheduled_at": new_at}
            plan.moves.append(move)
        last = cand
    return plan


def insert_entry(cal: Dict[str, Any], cfg: Mapping[str, Any], *, date: str, slug: str, title: str, lang: str,
                 format: str, status: str = "planned", holidays: Optional[hol.Holidays] = None,
                 workspace: Optional[Path] = None, **extra: Any) -> ReschedulePlan:
    """Add an entry on ``date``; if movable entries hold that day, push them (and what they bump) to the next
    free valid days. Refuses when the day is a blocked holiday or taken by an entry that cannot move."""
    holidays = holidays if holidays is not None else hol.Holidays()
    day = _parse_date(date)
    if day is None:
        raise CalendarError(f"bad date {date!r}: use YYYY-MM-DD")
    name = holidays.blocked(day)
    if name:
        raise CalendarError(f"{date} is a blocked holiday ({name})")
    entry = add_entry(cal, date=date, slug=slug, title=title, lang=lang, format=format, status=status, **extra)
    cal["entries"].remove(entry)  # placed below, after the others have moved
    holders = [e for e in cal["entries"] if e.get("date") == date and not _is_pair([e, entry])]
    plan = ReschedulePlan()
    if holders:
        plan = reschedule(cal, cfg, start=day, days=1, cascade_only=True, reserved=[day],
                          holidays=holidays, workspace=workspace)
        still = [e for e in cal["entries"] if e.get("date") == date and not _is_pair([e, entry])]
        if still:
            raise CalendarError(f"{date} is taken by {', '.join(e['slug'] for e in still)}, which cannot move "
                                "(posted, skipped, blocked, pinned or already queued)")
    cal["entries"].append(entry)
    plan.inserted = entry
    return plan


def apply_reschedule(workspace: Path, build: Callable[[Dict[str, Any]], ReschedulePlan], *, what: str,
                     dry_run: bool = False, wait: float = 30.0) -> ReschedulePlan:
    """Run ``build(cal)`` on the calendar and write the result: draft meta files, then the calendar, as one
    change under the calendar lock. If the calendar write fails the draft files are put back."""
    ws = Path(workspace)
    if dry_run:
        return build(load(ws))
    with guarded(ws, "calendar", stale_after=600, wait=wait):
        cal = load(ws)
        plan = build(cal)
        if not plan.changed:
            return plan
        done: Dict[str, bytes] = {}
        try:
            for slug, meta in plan.draft_meta.items():
                path = ws / "drafts" / slug / "meta.json"
                old = path.read_bytes()
                atomic_write_json(path, meta)
                done[slug] = old
            note = f"{what}: {len(plan.moves)} moved" + (f", inserted {plan.inserted['slug']}" if plan.inserted else "")
            cal.setdefault("changes", []).append({"date": _dt.date.today().isoformat(), "what": note})
            save(ws, cal)
        except BaseException:
            for slug, old in done.items():
                atomic_write_bytes(ws / "drafts" / slug / "meta.json", old)
            raise
    return plan
