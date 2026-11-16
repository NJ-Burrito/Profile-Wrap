"""The weekly report: counts and breakdowns from the ledger, metrics only where a snapshot exists.

Rules the code enforces (and the tests pin):

* a metric nobody measured is ``None`` (JSON ``null``), never 0;
* a sum or a mean uses only the posts that were measured, and the report says how many that was;
* a group with no measured post has ``null`` sums and means;
* nothing is inferred: n under :data:`MIN_N` is labelled a hypothesis in ``notes``.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import statistics
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from profile_wrap import atomic, fsutil, ledger, tzutil

SCHEMA_VERSION = 1
MIN_N = 5                       # under this many measured posts a comparison is a hypothesis
METRICS = ("reactions", "comments", "impressions")
WEEKLY_REL = Path("metrics") / "weekly"
SNAPSHOTS_REL = Path("metrics") / "track.jsonl"
GROUPS = ("pillar", "language", "weekday", "hour_band", "format", "hook_id")
WEEK_RE = re.compile(r"^(\d{4})-W(\d{2})$")
HOUR_BANDS = ((0, 6, "00-05"), (6, 12, "06-11"), (12, 15, "12-14"), (15, 18, "15-17"), (18, 24, "18-23"))
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


class TrackError(ValueError):
    """A bad week label or an unreadable input; the message is for the user."""


def parse_week(label: str) -> Tuple[int, int]:
    m = WEEK_RE.match(label.strip())
    if not m:
        raise TrackError(f"'{label}' is not an ISO week; use the form 2026-W46")
    year, week = int(m.group(1)), int(m.group(2))
    try:
        dt.date.fromisocalendar(year, week, 1)
    except ValueError:
        raise TrackError(f"'{label}' is not a real ISO week") from None
    return year, week


def week_label_for(day: dt.date) -> str:
    iso = day.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def weekly_path(workspace: Path, label: str) -> Path:
    parse_week(label)
    return Path(workspace) / WEEKLY_REL / f"{label}.json"


def _hour_band(hour: int) -> str:
    for lo, hi, name in HOUR_BANDS:
        if lo <= hour < hi:
            return name
    return HOUR_BANDS[-1][2]


def _number(value: Any) -> Optional[float]:
    """A real count, or None. A bool, a string and a negative number are not a measurement."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        return None
    return value


def _snapshots(workspace: Path) -> Dict[str, Dict[str, Any]]:
    """Latest snapshot per slug from ``metrics/track.jsonl`` (later rows win, field by field)."""
    rows, _bad = fsutil.read_jsonl(Path(workspace) / SNAPSHOTS_REL)
    latest: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        slug = row.get("slug")
        if isinstance(slug, str) and slug:
            latest[slug] = {**latest.get(slug, {}), **{k: v for k, v in row.items() if v is not None}}
    return latest


def _post_row(row: Mapping[str, Any], snap: Mapping[str, Any], when: dt.datetime) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "slug": row.get("slug"), "title": row.get("title"), "posted_at": row.get("posted_at"),
        "weekday": WEEKDAYS[when.weekday()], "hour_band": _hour_band(when.hour),
        "format": row.get("format"), "lang": row.get("lang"), "pillar": row.get("pillar") or None,
        "hook_id": row.get("hook_id") or None, "url": row.get("url"),
    }
    for name in METRICS:
        out[name] = _number(snap.get(name))
    out["measured"] = any(out[name] is not None for name in METRICS)
    return out


def _agg(values: List[Optional[float]]) -> Dict[str, Any]:
    known = [v for v in values if v is not None]
    return {"posts": len(values), "measured": len(known),
            "sum": (sum(known) if known else None),
            "mean": (round(sum(known) / len(known), 2) if known else None)}


def _group_key(post: Mapping[str, Any], group: str) -> str:
    value = post.get("lang" if group == "language" else group)
    return str(value) if value not in (None, "") else "not recorded"


def _breakdown(posts: List[Dict[str, Any]], group: str) -> Dict[str, Any]:
    keys = sorted({_group_key(p, group) for p in posts})
    return {k: {m: _agg([p[m] for p in posts if _group_key(p, group) == k]) for m in METRICS} for k in keys}


def _noise(posts: List[Dict[str, Any]]) -> Dict[str, Any]:
    vals = [p["reactions"] for p in posts if p["reactions"] is not None]
    if len(vals) < 2:
        return {"metric": "reactions", "n": len(vals), "median": (vals[0] if vals else None), "spread": None,
                "note": "fewer than 2 measured posts: no spread, no comparison"}
    return {"metric": "reactions", "n": len(vals), "median": statistics.median(vals),
            "spread": round(statistics.pstdev(vals), 2),
            "note": "population standard deviation of this week's measured posts; a gap between groups smaller "
                    "than the spread is noise"}


def _in_week(row: Mapping[str, Any], label: str, tz: str) -> Optional[dt.datetime]:
    stamp = row.get("posted_at")
    if not isinstance(stamp, str):
        return None
    try:
        when = tzutil.to_zone(tzutil.parse_aware(stamp), tz)
    except ValueError:
        return None
    return when if week_label_for(when.date()) == label else None


def build_report(rows: Iterable[Mapping[str, Any]], snapshots: Mapping[str, Mapping[str, Any]], label: str,
                 tz: str = "UTC", now: Optional[dt.datetime] = None) -> Dict[str, Any]:
    """The weekly report for ISO week ``label`` from merged ledger rows and per-slug snapshots."""
    year, week = parse_week(label)
    start = dt.date.fromisocalendar(year, week, 1)
    posts: List[Dict[str, Any]] = []
    for row in rows:
        if row.get("state", "posted") not in ("posted", "confirmed"):
            continue
        when = _in_week(row, label, tz)
        if when is not None:
            posts.append(_post_row(row, snapshots.get(str(row.get("slug")), {}), when))
    posts.sort(key=lambda p: str(p["posted_at"]))
    totals = {m: _agg([p[m] for p in posts]) for m in METRICS}
    not_measured = [m for m in METRICS if totals[m]["measured"] == 0]
    notes: List[str] = []
    measured = sum(1 for p in posts if p["measured"])
    if not posts:
        notes.append("no post in this week's ledger rows")
    elif measured == 0:
        notes.append("no metric was measured for any post this week: every figure is null, not 0")
    elif measured < MIN_N:
        notes.append(f"{measured} measured post(s), under {MIN_N}: any comparison is a hypothesis, not a finding")
    if 0 < measured < len(posts):
        notes.append(f"{len(posts) - measured} of {len(posts)} posts have no metrics; sums and means use only the measured ones")
    stamp = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc).isoformat(timespec="seconds")
    return {
        "schema_version": SCHEMA_VERSION, "week": label, "timezone": tz,
        "start": start.isoformat(), "end": (start + dt.timedelta(days=6)).isoformat(), "generated_at": stamp,
        "posts": posts,
        "totals": {"posts": len(posts), "measured_posts": measured, **totals},
        "breakdowns": {g: _breakdown(posts, g) for g in GROUPS},
        "not_measured": not_measured,
        "noise": _noise(posts), "min_n": MIN_N, "notes": notes,
    }


def report_for(workspace: Path, label: str, tz: str, now: Optional[dt.datetime] = None) -> Dict[str, Any]:
    rows, _bad = ledger.read_rows(workspace)
    return build_report(ledger.collapse(rows), _snapshots(workspace), label, tz, now)


def write_report(workspace: Path, report: Mapping[str, Any]) -> Path:
    path = weekly_path(workspace, str(report["week"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic.atomic_write_text(path, json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    return path


def render_lines(report: Mapping[str, Any]) -> List[str]:
    """Plain text for the terminal; null prints as 'not measured', never as 0."""
    def show(v: Any) -> str:
        return "not measured" if v is None else str(v)

    t = report["totals"]
    lines = [f"week {report['week']} ({report['start']} to {report['end']}, {report['timezone']})",
             f"posts: {t['posts']}, with metrics: {t['measured_posts']}"]
    for m in METRICS:
        lines.append(f"{m}: sum {show(t[m]['sum'])}, mean {show(t[m]['mean'])} ({t[m]['measured']} measured)")
    lines += [f"note: {n}" for n in report["notes"]]
    return lines
