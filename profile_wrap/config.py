"""Workspace configuration: defaults, load, validate, set, acknowledge.

One file, ``<workspace>/config/profile-wrap.json``, holds no secrets. It is validated at every command
start against ``schema/config.schema.json`` (unknown keys fail), then against the ceilings in
``policy.py`` (a value beyond a ceiling fails with a message; it is never clamped).

``*_ack`` fields are written only by ``ack()`` (``profile-wrap config ack <action>``). Each stores the
date and the sha256 of the shipped risk text; when that text changes, the action is downgraded
to its safe mode until the user accepts again.
"""
from __future__ import annotations

import copy
import datetime as _dt
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import limits, paths, policy, schemalite, tzutil
from .atomic import atomic_write_json
from .fsutil import append_jsonl, read_json, sha256_text

CONFIG_REL = Path("config") / "profile-wrap.json"
SECTIONS = ("persona", "locale", "posting", "linkedin", "engagement", "research", "gate",
            "brand", "render", "models", "schedule", "board", "ack")
# config/<name>.json files that are data, not config sections.
NOT_SPLIT_FILES = {"profile-wrap", "holidays", "trends"}

_SCHEMA_CACHE: Dict[str, Dict[str, Any]] = {}


class ConfigError(Exception):
    """The config file is missing or not readable JSON."""


@dataclass
class Report:
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def defaults(timezone: Optional[str] = None) -> Dict[str, Any]:
    """The default config (section 6). ``timezone`` defaults to the detected zone."""
    return {
        "schema_version": policy.SCHEMA_VERSION,
        "profile_id": "default",
        "persona": {
            "name": "", "handle": "", "role": "", "niche": "", "audience": "",
            "goal": "authority", "style_preset": "plain",
            "languages": ["en"], "primary_language": "en",
            "pillars": [{"id": "P1", "name": "", "share": 0.4}],
            "voice_file": "profile/voice.md", "facts_file": "research/facts.md",
            "story_bank": "profile/story-bank.md",
            "never_say": [], "private_terms": [], "sensitive_rules": [],
            "ai_disclosure": {"mode": "none", "text": ""}, "demo": False,
        },
        "locale": {
            "timezone": timezone or tzutil.detect_timezone(),
            "audience_regions": [], "weekend_days": ["sat", "sun"],
            "holidays_file": "config/holidays.json",
        },
        "posting": {
            "mode": "api_click", "api_scheduled_ack": None,
            "per_week": 3, "weekdays": ["mon", "wed", "thu"],
            "window": {"start": "09:00", "end": "12:29"},
            "min_gap_hours": policy.POST_GAP_HOURS_DEFAULT,
            "missed_after_hours": 6, "time_spread": True,
            "spread": {"avoid_round_minutes": True, "no_repeat_days": 14},
            "visibility": "PUBLIC", "first_comment": True,
            "formats_enabled": ["text", "slides", "gif"],
        },
        "linkedin": {
            "api_version": "auto", "redirect_uri": "http://localhost:8765/callback",
            "scopes": ["openid", "profile", "w_member_social"],
            "token_warn_days": 10, "sunset_warn_days": 60, "timeout_s": 30,
        },
        "engagement": {
            "comments": {"mode": "draft", "api_ack": None, "daily_cap": 3, "reply_reserve": 2,
                         "gap_seconds": [60, 300], "like": False, "max_chars": 1250,
                         "language": "post"},
            "replies": {"mode": "draft"},
            "reading": {"provider": "manual", "providers": [], "apify_ack": None, "public_ack": None,
                        "tavily_ack": None,
                        "apify": {"token_env": "APIFY_TOKEN", "max_calls_per_day": 20,
                                  "actor": "apimaestro~linkedin-profile-posts",
                                  "cost_per_call_usd": 0.01,
                                  "reserve_usd": policy.APIFY_RESERVE_USD},
                        "tavily": {"key_env": "TAVILY_API_KEY",
                                   "month_credits": policy.TAVILY_MONTH_CREDITS,
                                   "reserve_credits": policy.TAVILY_RESERVE_CREDITS,
                                   "cache_days": policy.TAVILY_CACHE_DAYS, "topic": "testing"},
                        "public": {"max_pages_per_day": policy.PUBLIC_READ_PAGES_PER_DAY_DEFAULT,
                                   "gap_seconds": policy.PUBLIC_READ_GAP_SECONDS_FLOOR,
                                   "profile_max_per_run": policy.PUBLIC_PROFILE_PER_RUN_DEFAULT,
                                   "profile_max_per_day": policy.PUBLIC_PROFILE_PER_DAY_DEFAULT,
                                   "profile_gap_minutes": policy.PUBLIC_PROFILE_GAP_MINUTES_DEFAULT}},
            "connect": {"enabled": True, "weekly_slots": 3, "min_score": 8,
                        "note_max": policy.CONNECT_NOTE_MAX, "pass_days": 60},
            "targets_file": "engage/targets.json", "max_post_age_hours": 168,
            "inactive_days": 30, "quota": {"tagA": 3, "tagB": 2}, "extras_waiting": 3,
            "retention_days": {"engage": 90, "connect": 180}, "strip_tracking_params": True,
        },
        "research": {"trends_file": "config/trends.json", "weekly": True,
                     "stats_expiry_days": 90, "contact": "",
                     "evidence_scale": list(policy.EVIDENCE_GRADES)},
        "gate": {
            "caption_max": 3000, "hook_max": 210, "hook_target": 40,
            "hashtags_max": 3, "links_in_body": "fail", "em_dash": "fail", "en_dash": "warn",
            "banned_files": ["data/banned-words/en.json", "data/banned-words/ar.json"],
            "extra_banned": [],
            "numbers": {"mode": "claim_bound", "require_claims": True, "min_bare_digit": 10,
                        "scan": ["caption", "first_comment", "slides", "video", "alt"],
                        "number_words": "warn"},
            "overrides": {"allow": True, "require_reason": True, "max_per_post": 2},
            "first_comment_gated": True, "require_alt_text": True, "require_council_pass": False,
            "gif": {"max_frames": 250, "max_mb": 40, "max_still_pct": 8, "flash_max_per_s": 3},
            "tools_missing": "skip_with_warning",
            "required_font_substrings": [],
        },
        "brand": {
            "font_source": "google_ofl",
            "fonts": {"display": {"family": "IBM Plex Sans", "files": []},
                      "text": {"family": "IBM Plex Sans", "files": []},
                      "arabic": {"family": "IBM Plex Sans Arabic", "files": []},
                      "licence_note": ""},
            "banned_families": [], "palette": {"mode": "per_post", "fixed": {}},
            "canvas": {"w": 1080, "h": 1350},
            "identity": {"enabled": False, "name": "", "role": "", "photo": None,
                         "signature": "none"},
        },
        "render": {"chrome_path": None, "timeout_s": 1800,
                   "gif": {"width": 1080, "fps": 25, "colors": 256, "dither": "none"},
                   "static": {"scale": 2}},
        "models": {
            "mode": "tiered",
            "lead": {"alias": "opus", "effort": "medium"},
            "standard": {"alias": "sonnet", "effort": "high"},
            "economy": {"alias": "haiku", "effort": "low"},
            "single": {"alias": "sonnet", "effort": "medium"},
            "runner": {"bin": None, "auth": "login", "api_key_env": None,
                       "max_turns": {"build": 40, "review": 20, "comment": 10},
                       "timeouts_s": {"build": 3000, "fix": 1800, "review": 900, "engage": 900},
                       "env_allow": ["PATH", "HOME", "USERPROFILE", "PYTHONUTF8", "LANG"]},
        },
        "schedule": {
            "backend": "auto", "log_rotate_mb": 5, "notify": "auto", "catchup": "missed_rule",
            "jobs": {
                "post_due": {"enabled": False, "every_min": 15},
                "build_week": {"enabled": True, "when": "THU 10:00", "jitter_min": 20},
                "research_weekly": {"enabled": True, "when": "FRI 09:00"},
                "token_check": {"enabled": True, "when": "DAILY 09:30"},
                "doctor_weekly": {"enabled": True, "when": "MON 08:00"},
                "profile_review": {"enabled": True, "every_days": 90},
                "board": {"enabled": True, "at_login": True},
                "engage_prepare": {"enabled": False, "when": "DAILY 11:00", "jitter_min": 30},
                "replies_watch": {"enabled": False, "every_min": 180},
                "connect_weekly": {"enabled": False, "when": "SUN 10:00"},
                "track_daily": {"enabled": False, "when": "DAILY 21:00"},
            },
        },
        "board": {"host": "127.0.0.1", "port": 8770, "ui_language": "en"},
        "ack": {"terms_read": None, "comments_api": None, "scraping_risk": None,
                "public_reading": None, "tavily_reading": None},
    }


# ------------------------------------------------------------------ loading

def deep_merge(base: Dict[str, Any], over: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def config_path(workspace: Path) -> Path:
    return Path(workspace) / CONFIG_REL


def load_raw(workspace: Path) -> Dict[str, Any]:
    path = config_path(workspace)
    if not path.is_file():
        raise ConfigError(f"{path} not found; run 'profile-wrap init' first")
    try:
        data = read_json(path)
    except ValueError as exc:
        raise ConfigError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must contain a JSON object")
    return data


def _split_files(workspace: Path) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    cfg_dir = Path(workspace) / "config"
    if not cfg_dir.is_dir():
        return out
    for path in sorted(cfg_dir.glob("*.json")):
        name = path.stem
        if name in NOT_SPLIT_FILES or name not in SECTIONS:
            continue
        try:
            data = read_json(path)
        except ValueError as exc:
            raise ConfigError(f"{path} is not valid JSON: {exc}") from exc
        if isinstance(data, dict):
            out[name] = data
    return out


def load(workspace: Path) -> Dict[str, Any]:
    """Defaults, then ``profile-wrap.json``, then optional split files ``config/<section>.json``."""
    raw = load_raw(workspace)
    merged = deep_merge(defaults(raw.get("locale", {}).get("timezone")), raw)
    return deep_merge(merged, _split_files(workspace))


def schema() -> Dict[str, Any]:
    path = paths.resource("schema", "config.schema.json")
    key = str(path)
    if key not in _SCHEMA_CACHE:
        _SCHEMA_CACHE[key] = schemalite.load_schema(path)
    return _SCHEMA_CACHE[key]


# --------------------------------------------------------------- validation

def validate(cfg: Dict[str, Any], workspace: Optional[Path] = None) -> Report:
    report = Report()
    report.errors.extend(schemalite.validate(cfg, schema()))
    if report.errors:
        return report
    report.errors.extend(limits.check_limits(cfg))

    if cfg["profile_id"] in paths.RESERVED_PROFILE_IDS:
        report.errors.append(f"profile_id '{cfg['profile_id']}' is reserved; choose another")
    persona = cfg["persona"]
    if persona["primary_language"] not in persona["languages"]:
        report.errors.append("persona.primary_language must be one of persona.languages")
    shares = sum(p.get("share", 0) for p in persona["pillars"])
    if shares > 1.001:
        report.errors.append(f"persona.pillars shares add up to {shares:g}; they must not exceed 1")
    elif len(persona["pillars"]) > 1 and abs(shares - 1.0) > 0.001:
        report.warnings.append(f"persona.pillars shares add up to {shares:g}, not 1")

    tz = cfg["locale"]["timezone"]
    if tzutil.tzdata_available():
        if not tzutil.is_valid_timezone(tz):
            report.errors.append(f"locale.timezone '{tz}' is not an IANA zone name")
    else:
        report.warnings.append("tzdata is not installed; the time zone could not be checked "
                               "(uv pip install tzdata)")

    posting = cfg["posting"]
    if len(posting["weekdays"]) < posting["per_week"]:
        report.errors.append(
            f"posting.per_week={posting['per_week']} needs at least that many posting.weekdays "
            f"(found {len(posting['weekdays'])})")
    if posting["mode"] == "api_scheduled" and not posting["api_scheduled_ack"]:
        report.errors.append(
            "posting.mode=api_scheduled needs an acknowledgement: run "
            "'profile-wrap config ack api_scheduled'")
    comments = cfg["engagement"]["comments"]
    if comments["mode"] == "api" and not comments["api_ack"]:
        report.errors.append("engagement.comments.mode=api needs 'profile-wrap config ack comments_api'")
    if cfg["engagement"]["reading"]["provider"] == "apify" and not \
            cfg["engagement"]["reading"]["apify_ack"]:
        report.errors.append("engagement.reading.provider=apify needs 'profile-wrap config ack apify'")
    reading = cfg["engagement"]["reading"]
    if reading["provider"] not in ("manual", "export", "apify", "public"):
        report.errors.append("engagement.reading.provider must be manual, export, apify or public")
    if reading["provider"] == "public" and not reading.get("public_ack"):
        report.errors.append("engagement.reading.provider=public needs 'profile-wrap config ack public'")
    chain = reading.get("providers")
    if not isinstance(chain, list) or any(p not in policy.READING_CHAIN_PROVIDERS for p in chain) \
            or len(set(chain)) != len(chain):
        report.errors.append("engagement.reading.providers must be a list without repeats drawn from "
                             + ", ".join(policy.READING_CHAIN_PROVIDERS))
    else:
        if "public" in chain and chain[-1] != "public":
            report.errors.append("engagement.reading.providers: 'public' must come last (it is the "
                                 "rate-limited fallback)")
        for name in chain:
            if not reading.get(f"{name}_ack"):
                report.errors.append(f"engagement.reading.providers lists {name}: run "
                                     f"'profile-wrap config ack {name}'")
    tav = reading.get("tavily") or {}
    mc, rc, cd = tav.get("month_credits"), tav.get("reserve_credits"), tav.get("cache_days")
    if not isinstance(mc, int) or isinstance(mc, bool) or mc < 1 or mc > policy.TAVILY_MONTH_CREDITS * 100:
        report.errors.append("engagement.reading.tavily.month_credits must be a positive integer")
    if not isinstance(rc, int) or isinstance(rc, bool) or rc < 0 or (isinstance(mc, int) and rc >= mc):
        report.errors.append("engagement.reading.tavily.reserve_credits must be 0 or more and below month_credits")
    if not isinstance(cd, int) or isinstance(cd, bool) or cd < 0:
        report.errors.append("engagement.reading.tavily.cache_days must be 0 or more")
    if not isinstance(tav.get("key_env"), str) or not tav.get("key_env") \
            or tav["key_env"].startswith("tvly-"):
        report.errors.append("engagement.reading.tavily.key_env must be the NAME of an environment "
                             "variable (the key itself never goes in the config)")
    api = reading.get("apify") or {}
    cost, res = api.get("cost_per_call_usd"), api.get("reserve_usd")
    if not isinstance(cost, (int, float)) or isinstance(cost, bool) or cost <= 0:
        report.errors.append("engagement.reading.apify.cost_per_call_usd must be above 0")
    if not isinstance(res, (int, float)) or isinstance(res, bool) or res < 0:
        report.errors.append("engagement.reading.apify.reserve_usd must be 0 or more")
    pub = reading.get("public") or {}
    pages, gap = pub.get("max_pages_per_day"), pub.get("gap_seconds")
    if not isinstance(pages, int) or isinstance(pages, bool) or not 1 <= pages <= policy.PUBLIC_READ_PAGES_PER_DAY_MAX:
        report.errors.append(
            f"engagement.reading.public.max_pages_per_day must be 1 to {policy.PUBLIC_READ_PAGES_PER_DAY_MAX}")
    if not isinstance(gap, (int, float)) or isinstance(gap, bool) or gap < policy.PUBLIC_READ_GAP_SECONDS_FLOOR:
        report.errors.append(
            f"engagement.reading.public.gap_seconds must be at least {policy.PUBLIC_READ_GAP_SECONDS_FLOOR}")
    for key in ("profile_max_per_run", "profile_max_per_day"):
        v = pub.get(key)
        if not isinstance(v, int) or isinstance(v, bool) or not 1 <= v <= policy.PUBLIC_PROFILE_PER_DAY_MAX:
            report.errors.append(
                f"engagement.reading.public.{key} must be 1 to {policy.PUBLIC_PROFILE_PER_DAY_MAX}")
    pg = pub.get("profile_gap_minutes")
    if not isinstance(pg, (int, float)) or isinstance(pg, bool) or pg < policy.PUBLIC_PROFILE_GAP_MINUTES_FLOOR:
        report.errors.append("engagement.reading.public.profile_gap_minutes must be at least "
                             f"{policy.PUBLIC_PROFILE_GAP_MINUTES_FLOOR}")
    if comments["like"] and not cfg["ack"]["comments_api"]:
        report.errors.append("engagement.comments.like=true needs 'profile-wrap config ack comments_api'")

    brand = cfg["brand"]
    if brand["font_source"] == "user_files":
        for role in ("display", "text", "arabic"):
            if not brand["fonts"][role]["files"]:
                report.warnings.append(
                    f"brand.font_source=user_files but brand.fonts.{role}.files is empty")
    if cfg["models"]["runner"]["auth"] == "api_key" and not \
            cfg["models"]["runner"]["api_key_env"]:
        report.errors.append("models.runner.auth=api_key needs models.runner.api_key_env "
                             "(the name of the environment variable, never the key itself)")

    if workspace is not None:
        for key, status in ack_statuses(cfg, workspace).items():
            if status[0] == "stale":
                report.warnings.append(
                    f"acknowledgement '{key}' no longer matches the current risk text; that "
                    "action is downgraded until you accept again")
    return report


def validate_workspace(workspace: Path) -> Report:
    try:
        cfg = load(workspace)
    except ConfigError as exc:
        return Report(errors=[str(exc)])
    return validate(cfg, workspace)


# -------------------------------------------------------------- show / set

def show(cfg: Dict[str, Any], key: Optional[str] = None) -> Any:
    if not key:
        return cfg
    cur: Any = cfg
    for part in key.split("."):
        if not isinstance(cur, dict) or part not in cur:
            raise KeyError(f"no such config key: {key}")
        cur = cur[part]
    return cur


def parse_value(raw: str) -> Any:
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def _is_ack_path(dotted: str) -> bool:
    leaf = dotted.split(".")[-1]
    return leaf.endswith("_ack") or dotted.startswith("ack.")


def set_value(workspace: Path, key: str, raw: str) -> Report:
    """Set one dotted key in ``config/profile-wrap.json`` if the result validates."""
    if _is_ack_path(key):
        return Report(errors=[f"{key} is written only by 'profile-wrap config ack <action>'"])
    stored = load_raw(workspace)
    merged = deep_merge(defaults(stored.get("locale", {}).get("timezone")), stored)
    parts = key.split(".")
    node: Any = merged
    for part in parts[:-1]:
        if not isinstance(node, dict) or part not in node:
            return Report(errors=[f"no such config key: {key}"])
        node = node[part]
    if not isinstance(node, dict) or parts[-1] not in node:
        return Report(errors=[f"no such config key: {key}"])
    node[parts[-1]] = parse_value(raw)
    report = validate(merged, workspace)
    if report.errors:
        return report
    atomic_write_json(config_path(workspace), merged)
    return report


# ------------------------------------------------------------ acknowledgements

def _normal(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def ack_document_hash(root: Optional[Path] = None) -> Optional[str]:
    """sha256 over the shipped compliance and risk documents (LF normalised)."""
    base = Path(root) if root else paths.plugin_root()
    chunks = []
    for rel in policy.ACK_DOCUMENTS:
        path = base / rel
        if not path.is_file():
            return None
        chunks.append(_normal(path.read_text(encoding="utf-8-sig")))
    return sha256_text("\n\x00\n".join(chunks))


def _set_path(cfg: Dict[str, Any], dotted: str, value: Any) -> None:
    parts = dotted.split(".")
    node = cfg
    for part in parts[:-1]:
        node = node[part]
    node[parts[-1]] = value


def _ack_file(profile_id: str, config_dir: Optional[Path]) -> Path:
    return (Path(config_dir) if config_dir else paths.config_dir(profile_id)) / "ack.json"


def ack(workspace: Path, action: str, phrase: str, config_dir: Optional[Path] = None,
        root: Optional[Path] = None, today: Optional[_dt.datetime] = None) -> Dict[str, Any]:
    """Record a typed acknowledgement bound to the sha256 of the shipped risk text."""
    if action not in policy.ACK_ACTIONS:
        raise ValueError(f"unknown action '{action}'; choose from "
                         f"{', '.join(sorted(policy.ACK_ACTIONS))}")
    if phrase.strip() != policy.ACK_PHRASE:
        raise ValueError(f"type exactly: {policy.ACK_PHRASE}")
    digest = ack_document_hash(root)
    if digest is None:
        raise ValueError("the risk documents (docs/references/compliance.md and "
                         "docs/TERMS-AND-RISK.md) were not found; cannot record an acknowledgement")
    stamp = (today or _dt.datetime.now(_dt.timezone.utc)).isoformat(timespec="seconds")
    record = {"date": stamp, "sha256": digest}
    stored = load_raw(workspace)
    full = deep_merge(defaults(stored.get("locale", {}).get("timezone")), stored)
    for dotted in policy.ACK_ACTIONS[action]:
        _set_path(full, dotted, dict(record))
    atomic_write_json(config_path(workspace), full)
    profile_id = full["profile_id"]
    path = _ack_file(profile_id, config_dir)
    try:
        existing = read_json(path, default={})
    except ValueError:
        existing = {}
    existing[action] = dict(record)
    atomic_write_json(path, existing)
    append_jsonl(Path(workspace) / "data" / "acks.jsonl", {"action": action, **record})
    return record


def ack_statuses(cfg: Dict[str, Any], workspace: Optional[Path] = None,
                 config_dir: Optional[Path] = None, root: Optional[Path] = None
                 ) -> Dict[str, Tuple[str, str]]:
    """action -> ('valid'|'stale'|'missing', reason)."""
    digest = ack_document_hash(root)
    try:
        stored = read_json(_ack_file(cfg["profile_id"], config_dir), default={})
    except ValueError:
        stored = {}
    out: Dict[str, Tuple[str, str]] = {}
    for action, targets in policy.ACK_ACTIONS.items():
        records = []
        for dotted in targets:
            node: Any = cfg
            for part in dotted.split("."):
                node = node.get(part) if isinstance(node, dict) else None
            records.append(node)
        if not targets:
            records = [stored.get(action)]
        if any(r is None for r in records):
            out[action] = ("missing", "not acknowledged")
            continue
        if digest is None:
            out[action] = ("stale", "risk documents not found")
        elif all(isinstance(r, dict) and r.get("sha256") == digest for r in records):
            out[action] = ("valid", "matches the current risk text")
        else:
            out[action] = ("stale", "the risk text changed since you accepted it")
    return out


def effective_modes(cfg: Dict[str, Any], workspace: Optional[Path] = None,
                    config_dir: Optional[Path] = None, root: Optional[Path] = None
                    ) -> Dict[str, Any]:
    """The modes that actually apply once stale or missing acknowledgements downgrade them."""
    status = ack_statuses(cfg, workspace, config_dir, root)
    notes: List[str] = []
    posting = cfg["posting"]["mode"]
    if posting == "api_scheduled" and status["api_scheduled"][0] != "valid":
        posting = "api_click"
        notes.append("posting downgraded to api_click: " + status["api_scheduled"][1])
    comments = cfg["engagement"]["comments"]["mode"]
    if comments == "api" and status["comments_api"][0] != "valid":
        comments = "draft"
        notes.append("comments downgraded to draft: " + status["comments_api"][1])
    reading = cfg["engagement"]["reading"]["provider"]
    if reading == "apify" and status["apify"][0] != "valid":
        reading = "manual"
        notes.append("reading downgraded to manual: " + status["apify"][1])
    if reading == "public" and status["public"][0] != "valid":
        reading = "manual"
        notes.append("reading downgraded to manual: " + status["public"][1])
    chain: List[str] = []
    for name in (cfg["engagement"]["reading"].get("providers") or []):
        if status[name][0] == "valid":
            chain.append(name)
        else:
            notes.append(f"reading provider {name} skipped: " + status[name][1])
    if not chain and reading in policy.READING_CHAIN_PROVIDERS:
        chain = [reading]
    if chain:
        reading = chain[0]
    likes = bool(cfg["engagement"]["comments"]["like"]) and status["comments_api"][0] == "valid"
    if workspace is not None and limits.is_paused(Path(workspace), "posting"):
        notes.append("posting is paused")
    return {"posting": posting, "comments": comments, "reading": reading, "reading_chain": chain,
            "likes": likes, "notes": notes}


def ack_valid(cfg: Dict[str, Any], action: str, **kw: Any) -> bool:
    return ack_statuses(cfg, **kw)[action][0] == "valid"


def write_initial(workspace: Path, cfg: Dict[str, Any]) -> Report:
    """Validate and write a complete config (used by scaffold)."""
    report = validate(cfg)
    if report.errors:
        return report
    atomic_write_json(config_path(workspace), cfg)
    return report


def env_flag(name: str) -> bool:
    return os.environ.get(name) == "1"
