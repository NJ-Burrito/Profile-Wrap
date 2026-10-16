"""Holiday handling for the planner: dates that block a post and windows that shift.

``config/holidays.json`` (in the workspace) has this shape; presets in ``data/holidays.presets/``
have the same shape plus an ``id`` and a ``label``:

    {"schema_version": 1,
     "recurring": [{"month_day": "12-25", "name": "Christmas Day"}],
     "ranges": [{"from": "2027-03-10", "to": "2027-03-12", "name": "Eid al-Fitr", "approximate": true}],
     "window_shifts": [{"from": "2027-02-08", "to": "2027-03-09", "name": "Ramadan evenings",
                        "window": {"start": "20:30", "end": "23:59"}}]}

Islamic dates depend on moon sighting and can move by a day: every such entry says
``approximate`` and the user edits the file when the date is announced.
"""
from __future__ import annotations

import datetime as _dt
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from profile_wrap import paths
from profile_wrap.atomic import atomic_write_json

SCHEMA_VERSION = 1


class HolidayError(ValueError):
    pass


def _d(text: str) -> _dt.date:
    try:
        return _dt.date.fromisoformat(text)
    except (TypeError, ValueError) as exc:
        raise HolidayError(f"bad date {text!r}: use YYYY-MM-DD") from exc


@dataclass
class Holidays:
    recurring: List[Dict[str, Any]] = field(default_factory=list)
    ranges: List[Dict[str, Any]] = field(default_factory=list)
    window_shifts: List[Dict[str, Any]] = field(default_factory=list)
    preset: str = ""

    def blocked(self, day: _dt.date) -> Optional[str]:
        """The name of the holiday that blocks ``day``, or None."""
        md = f"{day.month:02d}-{day.day:02d}"
        for r in self.recurring:
            if r.get("month_day") == md:
                return str(r.get("name") or md)
        for r in self.ranges:
            if _d(r["from"]) <= day <= _d(r.get("to", r["from"])):
                return str(r.get("name") or r["from"])
        return None

    def shifted_window(self, day: _dt.date, base: Sequence[str]) -> Tuple[Tuple[str, str], Optional[str]]:
        """The window for ``day`` and the name of the shift that changed it (None when unchanged)."""
        for s in self.window_shifts:
            if _d(s["from"]) <= day <= _d(s.get("to", s["from"])):
                w = s["window"]
                return (w["start"], w["end"]), str(s.get("name") or "window shift")
        return (base[0], base[1]), None

    def problems(self) -> List[str]:
        out: List[str] = []
        for r in self.recurring:
            md = str(r.get("month_day", ""))
            try:
                _dt.date(2024, int(md[:2]), int(md[3:5]))
            except (ValueError, IndexError):
                out.append(f"recurring holiday has a bad month_day: {md!r} (use MM-DD)")
        for kind, rows in (("range", self.ranges), ("window shift", self.window_shifts)):
            for r in rows:
                try:
                    a, b = _d(r["from"]), _d(r.get("to", r["from"]))
                    if b < a:
                        out.append(f"{kind} {r.get('name', '')}: 'to' is before 'from'")
                except (KeyError, HolidayError) as exc:
                    out.append(f"{kind} is malformed: {exc}")
        return out


def parse(data: Dict[str, Any]) -> Holidays:
    return Holidays(recurring=list(data.get("recurring", [])), ranges=list(data.get("ranges", [])),
                    window_shifts=list(data.get("window_shifts", [])),
                    preset=str(data.get("id", data.get("preset", ""))))


def load(workspace: Path, cfg: Optional[Dict[str, Any]] = None) -> Holidays:
    rel = ((cfg or {}).get("locale", {}) or {}).get("holidays_file", "config/holidays.json")
    path = Path(workspace) / rel
    if not path.is_file():
        return Holidays()
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except ValueError as exc:
        raise HolidayError(f"{rel} is not valid JSON: {exc}") from exc
    return parse(data)


def presets_dir() -> Path:
    return paths.resource("data", "holidays.presets")


def list_presets() -> List[Dict[str, str]]:
    out = []
    for p in sorted(presets_dir().glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out.append({"id": p.stem, "label": str(data.get("label", p.stem))})
    return out


def load_preset(name: str) -> Dict[str, Any]:
    p = presets_dir() / f"{name}.json"
    if not p.is_file():
        known = ", ".join(x["id"] for x in list_presets()) or "none installed"
        raise HolidayError(f"unknown holidays preset {name!r} (known: {known})")
    return json.loads(p.read_text(encoding="utf-8"))


def install_preset(workspace: Path, name: str, cfg: Optional[Dict[str, Any]] = None,
                   merge: bool = True) -> Path:
    """Write (or merge into) the workspace holidays file from a preset. Atomic."""
    rel = ((cfg or {}).get("locale", {}) or {}).get("holidays_file", "config/holidays.json")
    path = Path(workspace) / rel
    preset = load_preset(name)
    data: Dict[str, Any] = {"schema_version": SCHEMA_VERSION, "preset": name, "recurring": [],
                            "ranges": [], "window_shifts": []}
    if merge and path.is_file():
        try:
            data.update(json.loads(path.read_text(encoding="utf-8-sig")))
        except ValueError:
            pass
    for key in ("recurring", "ranges", "window_shifts"):
        have = {json.dumps(x, sort_keys=True) for x in data.get(key, [])}
        for item in preset.get(key, []):
            if json.dumps(item, sort_keys=True) not in have:
                data.setdefault(key, []).append(item)
    data["preset"] = name
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, data)
    return path
