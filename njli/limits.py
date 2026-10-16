"""Ceilings and floors applied to a config dict, and the pause flags.

A value beyond a ceiling is an error with a message. It is never clamped.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import policy


@dataclass(frozen=True)
class Limit:
    path: str
    kind: str  # "max" or "min"
    value: float
    label: str


LIMITS = (
    Limit("posting.per_week", "max", policy.POSTS_PER_WEEK_MAX, "posts per week"),
    Limit("posting.min_gap_hours", "min", policy.POST_GAP_HOURS_FLOOR, "hours between posts"),
    Limit("engagement.comments.daily_cap", "max", policy.COMMENTS_REPLIES_PER_DAY_MAX,
          "comments plus replies per day"),
    Limit("engagement.connect.weekly_slots", "max", policy.CONNECT_SLOTS_MAX,
          "connection slots waiting"),
    Limit("engagement.connect.note_max", "max", policy.CONNECT_NOTE_MAX,
          "connection note characters"),
)


def get_path(cfg: Dict[str, Any], dotted: str, default: Any = None) -> Any:
    cur: Any = cfg
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def _hhmm(text: Any) -> Optional[int]:
    try:
        hh, mm = str(text).split(":")
        h, m = int(hh), int(mm)
    except ValueError:
        return None
    if not (0 <= h <= 23 and 0 <= m <= 59):
        return None
    return h * 60 + m


def window_width_minutes(window: Dict[str, Any]) -> Optional[int]:
    start, end = _hhmm(window.get("start")), _hhmm(window.get("end"))
    if start is None or end is None or end < start:
        return None
    return end - start


def check_limits(cfg: Dict[str, Any]) -> List[str]:
    """Return error strings for every limit the config breaks."""
    errors: List[str] = []
    for lim in LIMITS:
        val = get_path(cfg, lim.path)
        if val is None or isinstance(val, bool) or not isinstance(val, (int, float)):
            continue
        if lim.kind == "max" and val > lim.value:
            errors.append(
                f"{lim.path}={val} is above the ceiling of {lim.value:g} ({lim.label}); "
                "ceilings are locked in policy.py and cannot be raised by config")
        if lim.kind == "min" and val < lim.value:
            errors.append(
                f"{lim.path}={val} is below the floor of {lim.value:g} ({lim.label}); "
                "floors are locked in policy.py and cannot be lowered by config")
    gap = get_path(cfg, "engagement.comments.gap_seconds")
    if isinstance(gap, list) and gap and isinstance(gap[0], (int, float)):
        if gap[0] < policy.ACTION_GAP_SECONDS_FLOOR:
            errors.append(
                f"engagement.comments.gap_seconds[0]={gap[0]} is below the floor of "
                f"{policy.ACTION_GAP_SECONDS_FLOOR} seconds between actions")
        if len(gap) > 1 and isinstance(gap[1], (int, float)) and gap[1] < gap[0]:
            errors.append("engagement.comments.gap_seconds must be [min, max] with min <= max")
    cap = get_path(cfg, "engagement.comments.daily_cap")
    reserve = get_path(cfg, "engagement.comments.reply_reserve")
    if isinstance(cap, int) and isinstance(reserve, int) and not isinstance(cap, bool):
        if reserve > cap:
            errors.append("engagement.comments.reply_reserve cannot exceed daily_cap "
                          "(comments and replies share one cap)")
    window = get_path(cfg, "posting.window")
    gap_h = get_path(cfg, "posting.min_gap_hours", policy.POST_GAP_HOURS_DEFAULT)
    if isinstance(window, dict) and isinstance(gap_h, (int, float)):
        width = window_width_minutes(window)
        if width is None:
            errors.append("posting.window needs start and end as HH:MM with end after start")
        else:
            limit = (24 - gap_h - policy.WINDOW_MARGIN_HOURS) * 60
            if width > limit:
                errors.append(
                    f"posting.window is {width} minutes wide; with min_gap_hours={gap_h:g} "
                    f"it may be at most {limit:g} minutes so consecutive days keep the gap")
            if width < policy.WINDOW_MIN_WIDTH_MINUTES:
                errors.append(
                    f"posting.window is {width} minutes wide; at least "
                    f"{policy.WINDOW_MIN_WIDTH_MINUTES} minutes are needed for slot spacing")
    return errors


def caps_json() -> Dict[str, Any]:
    """The document written to ``data/caps.json`` (a mirror of policy.py)."""
    doc = policy.caps()
    doc["limits"] = [
        {"path": lim.path, "kind": lim.kind, "value": lim.value, "label": lim.label}
        for lim in LIMITS
    ]
    return doc


# ---------------------------------------------------------------- pause flags

def _pause_path(workspace: Path, kind: Optional[str]) -> Path:
    name = policy.PAUSE_FILE if kind in (None, "all") else f"{policy.PAUSE_FILE}.{kind}"
    return Path(workspace) / "work" / name


def pause(workspace: Path, kind: Optional[str] = None, reason: str = "") -> Path:
    """Write a pause flag. ``kind`` is None/"all", "posting" or "comments"."""
    if kind not in (None, "all") + policy.PAUSE_KINDS:
        raise ValueError(f"unknown pause kind: {kind}")
    path = _pause_path(workspace, kind)
    path.parent.mkdir(parents=True, exist_ok=True)
    stamp = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
    path.write_text(f"paused {stamp}\n{reason}\n", encoding="utf-8")
    return path


def resume(workspace: Path, kind: Optional[str] = None) -> List[Path]:
    """Remove pause flags. With no kind (or "all") every flag is removed."""
    removed: List[Path] = []
    kinds: List[Optional[str]]
    if kind in (None, "all"):
        kinds = [None] + list(policy.PAUSE_KINDS)
    else:
        kinds = [kind]
    for k in kinds:
        path = _pause_path(workspace, k)
        if path.exists():
            path.unlink()
            removed.append(path)
    return removed


def is_paused(workspace: Path, kind: Optional[str] = None) -> bool:
    """True when the global flag, or the flag for ``kind``, exists."""
    if _pause_path(workspace, None).exists():
        return True
    return bool(kind and kind != "all" and _pause_path(workspace, kind).exists())


def pause_flags(workspace: Path) -> List[str]:
    out = []
    if _pause_path(workspace, None).exists():
        out.append("all")
    out += [k for k in policy.PAUSE_KINDS if _pause_path(workspace, k).exists()]
    return out
