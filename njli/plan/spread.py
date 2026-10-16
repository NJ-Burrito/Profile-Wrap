"""``spread_time``: a stable, per-slug posting minute inside the configured window.

The result, for one slug and one date:

* lies inside ``posting.window``;
* is not on a round 5-minute mark (when ``avoid_round`` is set);
* is not a minute already used within ``no_repeat_days`` days either side (the other posts come from
  the ledger and the calendar and are passed in as ``taken``);
* keeps ``min_gap_hours`` plus a margin for the scheduler's start lag from every neighbouring post;
* is the same on every call for the same inputs (a hash of the slug picks the candidate).

This replaces a bare hash of the slug, which produced repeats. It is audience-window spacing and load spreading,
not a disguise: ``automation.mode`` is recorded on every ledger row regardless.

When no minute meets every rule the constraints are relaxed in a fixed order (repeat, window, round
mark, gap) and the relaxations are returned in ``Spread.relaxed`` so callers can warn.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

DEFAULT_WINDOW = ("09:00", "12:29")
LAG_MINUTES = 15  # the task scheduler's start lag, added to min_gap_hours

DateLike = Union[str, _dt.date]
Taken = Mapping[DateLike, Union[str, int, Sequence[Union[str, int]]]]


def parse_hhmm(text: Union[str, int]) -> int:
    if isinstance(text, int):
        return text
    h, m = str(text).strip().split(":")
    hh, mm = int(h), int(m)
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        raise ValueError(f"bad time: {text!r}")
    return hh * 60 + mm


def fmt_hhmm(minute: int) -> str:
    return f"{minute // 60:02d}:{minute % 60:02d}"


def _date(value: DateLike) -> _dt.date:
    return value if isinstance(value, _dt.date) else _dt.date.fromisoformat(str(value))


@dataclass
class Spread:
    minute: int
    relaxed: List[str] = field(default_factory=list)

    @property
    def time(self) -> str:
        return fmt_hhmm(self.minute)


@lru_cache(maxsize=256)
def _window_minutes(start: int, end: int, avoid_round: bool) -> Tuple[int, ...]:
    return tuple(m for m in range(start, end + 1) if not (avoid_round and m % 5 == 0))


def _digest(slug: str, salt: str) -> int:
    return int.from_bytes(hashlib.sha256(f"{salt}|{slug}".encode("utf-8")).digest()[:8], "big")


def _normalise_taken(taken: Optional[Taken]) -> List[Tuple[_dt.date, int]]:
    out: List[Tuple[_dt.date, int]] = []
    for key, value in (taken or {}).items():
        values = value if isinstance(value, (list, tuple)) else [value]
        for v in values:
            out.append((_date(key), parse_hhmm(v)))
    return out


def _absolute(day: _dt.date, minute: int, tz: Optional[str]) -> float:
    """Minutes on a single time line. With a zone, DST changes are real time."""
    if tz:
        from njli import tzutil
        naive = _dt.datetime.combine(day, _dt.time(minute // 60, minute % 60))
        return tzutil.localize(naive, tz).timestamp() / 60.0
    return (day.toordinal() * 1440) + minute


def spread_detail(slug: str, date: DateLike, *, window: Sequence[str] = DEFAULT_WINDOW,
                  min_gap_hours: float = 20, no_repeat_days: int = 14, avoid_round: bool = True,
                  taken: Optional[Taken] = None, lag_minutes: int = LAG_MINUTES,
                  tz: Optional[str] = None, salt: str = "") -> Spread:
    day = _date(date)
    start, end = parse_hhmm(window[0]), parse_hhmm(window[1])
    if end < start:
        raise ValueError(f"window end {window[1]} is before its start {window[0]}")
    need = float(min_gap_hours) * 60 + lag_minutes
    others = _normalise_taken(taken)
    h = _digest(slug, salt)

    def gap_ok(minute: int) -> bool:
        here = _absolute(day, minute, tz)
        for d, m in others:
            if abs((d - day).days) > 3:
                continue
            if abs(here - _absolute(d, m, tz)) < need:
                return False
        return True

    def repeat_ok(minute: int) -> bool:
        for d, m in others:
            if m == minute and abs((d - day).days) <= no_repeat_days:
                return False
        return True

    relaxed: List[str] = []
    base = _window_minutes(start, end, avoid_round)

    def pick(cands: Sequence[int]) -> Optional[int]:
        return cands[h % len(cands)] if cands else None

    cands = [m for m in base if gap_ok(m) and repeat_ok(m)]
    chosen = pick(cands)
    if chosen is None:
        relaxed.append("repeat")
        chosen = pick([m for m in base if gap_ok(m)])
    if chosen is None:
        relaxed.append("window")
        wide = _window_minutes(0, 1439, avoid_round)
        ok = [m for m in wide if gap_ok(m)]
        if ok:  # the minutes nearest the window
            ok.sort(key=lambda m: min(abs(m - start), abs(m - end)))
            near = ok[: max(1, min(len(ok), 60))]
            chosen = near[h % len(near)]
    if chosen is None:
        relaxed.append("round")
        chosen = pick([m for m in _window_minutes(0, 1439, False) if gap_ok(m)])
    if chosen is None:
        relaxed.append("gap")
        chosen = pick(list(_window_minutes(start, end, False)))
    assert chosen is not None
    return Spread(minute=chosen, relaxed=relaxed)


def spread_time(slug: str, date: DateLike, **kwargs: Any) -> str:
    """The posting time as ``HH:MM`` (see :func:`spread_detail` for the arguments)."""
    return spread_detail(slug, date, **kwargs).time


def window_for(cfg: Mapping[str, Any]) -> Tuple[str, str]:
    w = cfg.get("posting", {}).get("window", {})
    return (w.get("start", DEFAULT_WINDOW[0]), w.get("end", DEFAULT_WINDOW[1]))


def kwargs_from_config(cfg: Mapping[str, Any]) -> Dict[str, Any]:
    posting = cfg.get("posting", {})
    spread = posting.get("spread", {})
    return {
        "window": window_for(cfg),
        "min_gap_hours": posting.get("min_gap_hours", 20),
        "no_repeat_days": spread.get("no_repeat_days", 14),
        "avoid_round": spread.get("avoid_round_minutes", True),
        "tz": cfg.get("locale", {}).get("timezone") or None,
    }
