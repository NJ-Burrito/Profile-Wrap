"""``profile-wrap plan recipe``: suggest ``posting.window`` from where the audience is (``data/timing-recipe.json``).

The recipe is a starting point built on published studies of other people's accounts, not a promise
(see ``docs/references/timing-recipe.md``). The result always fits the width rule of the config
validator, so applying it never breaks ``profile-wrap config validate``.
"""
from __future__ import annotations

import datetime as _dt
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from profile_wrap import paths, policy, tzutil
from profile_wrap.plan.spread import fmt_hhmm, parse_hhmm


@dataclass
class Suggestion:
    start: str
    end: str
    overlap_regions: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    per_region: Dict[str, str] = field(default_factory=dict)

    @property
    def width(self) -> int:
        return parse_hhmm(self.end) - parse_hhmm(self.start)


def load_recipe() -> Dict[str, Any]:
    return json.loads(paths.resource("data", "timing-recipe.json").read_text(encoding="utf-8"))


def _to_poster_minutes(audience_tz: str, poster_tz: str, minute: int, day: _dt.date) -> int:
    """Minutes since midnight in the poster's zone for ``minute`` o'clock in the audience's zone, same date."""
    naive = _dt.datetime.combine(day, _dt.time(minute // 60, minute % 60))
    there = tzutil.localize(naive, audience_tz)
    here = there.astimezone(tzutil.get_zone(poster_tz))
    return (here.date() - day).days * 1440 + here.hour * 60 + here.minute


def suggest_window(poster_tz: str, regions: Sequence[str], day: Optional[_dt.date] = None,
                   recipe: Optional[Dict[str, Any]] = None) -> Suggestion:
    recipe = recipe or load_recipe()
    day = day or _dt.date.today()
    by_id = {r["id"]: r for r in recipe["regions"]}
    unknown = [r for r in regions if r not in by_id]
    known = [r for r in regions if r in by_id]
    sug = Suggestion("09:00", "12:29")
    if unknown:
        sug.notes.append("unknown audience regions ignored: " + ", ".join(unknown))
    if not known:
        sug.notes.append("no audience region given: the poster's own afternoon is used")
        known_tz = [poster_tz]
        labels = ["poster"]
    else:
        known_tz = [by_id[r]["tz"] for r in known]
        labels = known
    h = recipe["method"]["audience_hours_local"]
    a, b = parse_hhmm(h["start"]), parse_hhmm(h["end"])
    spans = []
    for label, tz in zip(labels, known_tz):
        lo = _to_poster_minutes(tz, poster_tz, a, day)
        hi = lo + (b - a)
        spans.append((lo, hi))
        sug.per_region[label] = f"{fmt_hhmm(lo % 1440)}-{fmt_hhmm(hi % 1440)}"
    lo = max(s[0] for s in spans)
    hi = min(s[1] for s in spans)
    if lo <= hi and (hi - lo + 1) >= policy.WINDOW_MIN_WIDTH_MINUTES:
        sug.overlap_regions = list(labels)
    else:
        why = "do not overlap" if lo > hi else f"overlap by only {hi - lo + 1} minutes"
        sug.notes.append(f"the regions' reading hours {why} in your timezone; the first region is used. "
                         "Choose which audience matters more.")
        lo, hi = spans[0]
        sug.overlap_regions = [labels[0]]
    width = min(hi - lo, int(recipe["method"]["max_width_minutes"]))
    hi = lo + width
    if lo < 0 or hi > 1439:
        sug.notes.append("the window crosses midnight in your timezone; it was moved to stay inside one day. "
                         "Check it fits when you want to post.")
        if hi > 1439:
            hi = 1439
            lo = max(0, hi - width)
        else:
            lo = max(0, lo)
            hi = lo + width
    sug.start, sug.end = fmt_hhmm(lo), fmt_hhmm(hi)
    return sug
