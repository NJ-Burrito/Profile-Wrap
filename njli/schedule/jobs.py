"""The job model: what ``schedule.jobs`` in the config means and which command each job runs.

A job has a name, a ``njli`` argv, a time rule and a hard timeout. Time rules come from the config
keys ``when`` ("THU 10:00", "DAILY 09:30"), ``every_min``, ``every_days`` and ``at_login``.
"""
from __future__ import annotations

import datetime as _dt
import os
import re
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

WEEKDAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
DEFAULT_ENABLED = ("build_week", "research_weekly", "token_check", "doctor_weekly",
                   "profile_review", "board")
ENGAGEMENT_JOBS = ("engage_prepare", "replies_watch", "connect_weekly")

# job -> (argv after "njli", pause kind or None, timeout seconds, needs the network)
JOB_TABLE: Dict[str, Dict[str, Any]] = {
    "post_due":        {"argv": ["due"], "pause": "posting", "timeout": 600, "model": False},
    "build_week":      {"argv": ["build-week"], "pause": None, "timeout": 3 * 3600, "model": True},
    "research_weekly": {"argv": ["research", "trends"], "pause": None, "timeout": 1800, "model": True},
    "token_check":     {"argv": ["auth", "check"], "pause": None, "timeout": 120, "model": False},
    "doctor_weekly":   {"argv": ["doctor", "--json"], "pause": None, "timeout": 300, "model": False},
    "profile_review":  {"argv": ["profile", "remind"], "pause": None, "timeout": 300, "model": False},
    "board":           {"argv": ["board"], "pause": None, "timeout": 0, "model": False},
    "engage_prepare":  {"argv": ["engage", "prepare"], "pause": "comments", "timeout": 1800, "model": True},
    "replies_watch":   {"argv": ["engage", "replies"], "pause": "comments", "timeout": 1800, "model": True},
    "connect_weekly":  {"argv": ["engage", "connect"], "pause": "comments", "timeout": 1800, "model": True},
    "track_daily":     {"argv": ["track"], "pause": None, "timeout": 900, "model": False},
}
# The board is a long-lived server: no timeout, restart on failure, started at login.
LONG_LIVED = ("board",)


class ScheduleError(ValueError):
    pass


@dataclass(frozen=True)
class Rule:
    """When a job fires. Exactly one of ``interval_min``, ``weekday``/``daily``, ``interval_days``, ``login``."""
    kind: str                    # interval | weekly | daily | days | login
    hour: int = 0
    minute: int = 0
    weekday: Optional[int] = None  # 0 = Monday
    interval_min: int = 0
    interval_days: int = 0

    def describe(self) -> str:
        if self.kind == "interval":
            return f"every {self.interval_min} min"
        if self.kind == "weekly":
            return f"{WEEKDAYS[self.weekday or 0]} {self.hour:02d}:{self.minute:02d}"
        if self.kind == "daily":
            return f"daily {self.hour:02d}:{self.minute:02d}"
        if self.kind == "days":
            return f"every {self.interval_days} days (checked daily {self.hour:02d}:{self.minute:02d})"
        return "at login"


@dataclass
class Job:
    name: str
    argv: List[str]
    rule: Rule
    timeout_s: int
    jitter_min: int = 0
    wake: bool = False
    pause_kind: Optional[str] = None
    long_lived: bool = False
    min_interval_days: int = 0
    uses_model: bool = False

    def task_name(self, profile: str) -> str:
        return f"njli-{profile}-{self.name}"


_WHEN = re.compile(r"^(?:(MON|TUE|WED|THU|FRI|SAT|SUN|DAILY)\s+)?(\d{1,2}):(\d{2})$", re.I)


def parse_when(text: str) -> Rule:
    m = _WHEN.match(str(text).strip())
    if not m:
        raise ScheduleError(f"bad schedule time {text!r}: use 'THU 10:00' or 'DAILY 09:30'")
    day, hh, mm = m.group(1), int(m.group(2)), int(m.group(3))
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        raise ScheduleError(f"bad time of day in {text!r}")
    if day is None or day.upper() == "DAILY":
        return Rule("daily", hour=hh, minute=mm)
    return Rule("weekly", hour=hh, minute=mm, weekday=WEEKDAYS.index(day.upper()))


def rule_for(name: str, spec: Mapping[str, Any]) -> Rule:
    if spec.get("at_login"):
        return Rule("login")
    if spec.get("every_min"):
        n = int(spec["every_min"])
        if n < 1:
            raise ScheduleError(f"{name}: every_min must be at least 1")
        return Rule("interval", interval_min=n)
    if spec.get("every_days"):
        n = int(spec["every_days"])
        if n < 1:
            raise ScheduleError(f"{name}: every_days must be at least 1")
        return Rule("days", hour=9, minute=0, interval_days=n)
    if spec.get("when"):
        return parse_when(spec["when"])
    raise ScheduleError(f"{name}: needs one of when, every_min, every_days or at_login")


def wanted(cfg: Mapping[str, Any], name: str) -> bool:
    """Is the job enabled, by config and by the mode rules (post_due needs api_scheduled and its ack)?"""
    spec = (cfg.get("schedule", {}).get("jobs", {}) or {}).get(name, {})
    if not spec.get("enabled"):
        return False
    if name == "post_due":
        from njli import config as cfgmod
        modes = cfgmod.effective_modes(dict(cfg))
        return modes.get("posting") == "api_scheduled"
    return True


def jobs_from_config(cfg: Mapping[str, Any], only: Optional[Sequence[str]] = None,
                     include_disabled: bool = False) -> List[Job]:
    specs = cfg.get("schedule", {}).get("jobs", {}) or {}
    out: List[Job] = []
    for name in sorted(specs):
        if only and name not in only:
            continue
        if name not in JOB_TABLE:
            raise ScheduleError(f"unknown job: {name} (known: {', '.join(sorted(JOB_TABLE))})")
        if not include_disabled and not wanted(cfg, name):
            continue
        spec = specs[name]
        info = JOB_TABLE[name]
        rule = rule_for(name, spec)
        out.append(Job(name=name, argv=list(info["argv"]), rule=rule, timeout_s=int(info["timeout"]),
                       jitter_min=int(spec.get("jitter_min", 0) or 0), wake=bool(spec.get("wake", False)),
                       pause_kind=info["pause"], long_lived=name in LONG_LIVED,
                       min_interval_days=rule.interval_days if rule.kind == "days" else 0,
                       uses_model=bool(info["model"])))
    return out


# --------------------------------------------------------------------- invoking njli itself

def _launcher() -> Optional[Path]:
    """The zipapp or runtime folder this process was started from, or None when it runs from source."""
    main = sys.argv[0] if sys.argv else ""
    if not main:
        return None
    p = Path(main)
    if zipfile.is_zipfile(main) or (p.is_dir() and (p / "__main__.py").is_file()):
        return p.resolve()
    return None


def njli_argv(*args: str) -> List[str]:
    """The command that runs ``njli <args>`` the way this process was started (zipapp, runtime folder or source)."""
    launcher = _launcher()
    if launcher is not None:
        return [sys.executable, str(launcher), *args]
    return [sys.executable, "-m", "njli", *args]


def njli_env(extra: Optional[Mapping[str, str]] = None) -> Dict[str, str]:
    """Environment for a child ``njli``: UTF-8, and the package on the path when running from source."""
    import njli
    env = dict(os.environ)
    if _launcher() is None:
        root = str(Path(njli.__file__).resolve().parent.parent)
        env["PYTHONPATH"] = root + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env["PYTHONUTF8"] = "1"
    if extra:
        env.update(extra)
    return env


# --------------------------------------------------------------------- local-time conversion

def to_local_rule(rule: Rule, config_tz: str, local_tz: str,
                  reference: Optional[_dt.date] = None) -> Tuple[Rule, bool]:
    """Re-express a rule given in the configured timezone in the machine's own timezone.

    OS schedulers fire in machine local time. Returns the rule and whether it changed. The offset is
    taken at ``reference`` (default: today), so a daylight saving change between the two zones can
    still move the job by an hour; ``schedule plan`` says so.
    """
    if rule.kind in ("interval", "login") or config_tz == local_tz:
        return rule, False
    from njli import tzutil
    day = reference or _dt.date.today()
    if rule.kind == "weekly":  # the next date with that weekday
        day = day + _dt.timedelta(days=((rule.weekday or 0) - day.weekday()) % 7)
    src = tzutil.localize(_dt.datetime.combine(day, _dt.time(rule.hour, rule.minute)), config_tz)
    dst = src.astimezone(tzutil.get_zone(local_tz))
    if rule.kind == "weekly":
        new = Rule("weekly", hour=dst.hour, minute=dst.minute, weekday=dst.weekday())
    else:
        new = Rule(rule.kind, hour=dst.hour, minute=dst.minute, interval_days=rule.interval_days)
    return new, (new.hour, new.minute, new.weekday) != (rule.hour, rule.minute, rule.weekday)
