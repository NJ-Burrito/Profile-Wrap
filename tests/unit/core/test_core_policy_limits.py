from __future__ import annotations

import json
from pathlib import Path

import pytest

from njli import limits, policy

REPO = Path(__file__).resolve().parents[3]


def test_caps_json_mirrors_policy():
    shipped = json.loads((REPO / "data" / "caps.json").read_text(encoding="utf-8"))
    assert shipped == limits.caps_json()


def test_schema_ceilings_match_policy():
    schema = json.loads((REPO / "schema" / "config.schema.json").read_text(encoding="utf-8"))
    props = schema["properties"]
    assert props["posting"]["properties"]["per_week"]["x-ceiling"] == policy.POSTS_PER_WEEK_MAX
    assert props["posting"]["properties"]["min_gap_hours"]["x-floor"] == policy.POST_GAP_HOURS_FLOOR
    comments = props["engagement"]["properties"]["comments"]["properties"]
    assert comments["daily_cap"]["x-ceiling"] == policy.COMMENTS_REPLIES_PER_DAY_MAX
    assert comments["gap_seconds"]["x-floor"] == policy.ACTION_GAP_SECONDS_FLOOR
    connect = props["engagement"]["properties"]["connect"]["properties"]
    assert connect["weekly_slots"]["x-ceiling"] == policy.CONNECT_SLOTS_MAX
    assert connect["note_max"]["x-ceiling"] == policy.CONNECT_NOTE_MAX


def _cfg(**posting):
    from njli import config

    cfg = config.defaults("UTC")
    cfg["posting"].update(posting)
    return cfg


@pytest.mark.parametrize("path,value,fragment", [
    ("posting.per_week", 8, "ceiling"),
    ("posting.min_gap_hours", 11, "floor"),
    ("engagement.comments.daily_cap", 11, "ceiling"),
    ("engagement.connect.weekly_slots", 6, "ceiling"),
    ("engagement.connect.note_max", 201, "ceiling"),
])
def test_check_limits_rejects_values_beyond_limit(path, value, fragment):
    from njli import config

    cfg = config.defaults("UTC")
    node = cfg
    parts = path.split(".")
    for p in parts[:-1]:
        node = node[p]
    node[parts[-1]] = value
    errors = limits.check_limits(cfg)
    assert any(path in e and fragment in e for e in errors), errors


def test_check_limits_accepts_the_limits_themselves():
    cfg = _cfg(per_week=7, min_gap_hours=12, window={"start": "09:00", "end": "20:00"})
    cfg["engagement"]["comments"]["daily_cap"] = 10
    cfg["engagement"]["comments"]["reply_reserve"] = 10
    cfg["engagement"]["connect"]["weekly_slots"] = 5
    assert limits.check_limits(cfg) == []


def test_gap_seconds_floor_and_order():
    cfg = _cfg()
    cfg["engagement"]["comments"]["gap_seconds"] = [30, 300]
    assert any("floor of 60" in e for e in limits.check_limits(cfg))
    cfg["engagement"]["comments"]["gap_seconds"] = [120, 90]
    assert any("min <= max" in e for e in limits.check_limits(cfg))


def test_reply_reserve_cannot_exceed_cap():
    cfg = _cfg()
    cfg["engagement"]["comments"]["daily_cap"] = 2
    cfg["engagement"]["comments"]["reply_reserve"] = 3
    assert any("reply_reserve" in e for e in limits.check_limits(cfg))


def test_window_too_wide_or_too_narrow_or_malformed():
    wide = limits.check_limits(_cfg(window={"start": "00:00", "end": "23:59"}))
    assert any("at most" in e for e in wide)
    narrow = limits.check_limits(_cfg(window={"start": "09:00", "end": "09:30"}))
    assert any("at least" in e for e in narrow)
    bad = limits.check_limits(_cfg(window={"start": "9am", "end": "12:00"}))
    assert any("HH:MM" in e for e in bad)
    backwards = limits.check_limits(_cfg(window={"start": "12:00", "end": "09:00"}))
    assert any("HH:MM" in e for e in backwards)


def test_window_width_depends_on_gap():
    # 24h - 20h gap - 0.5h = 3.5h = 210 min allowed; 12h gap allows 11.5h.
    assert limits.check_limits(_cfg(window={"start": "08:00", "end": "11:30"})) == []
    assert limits.check_limits(_cfg(window={"start": "08:00", "end": "11:31"}))
    assert limits.check_limits(_cfg(min_gap_hours=12, window={"start": "08:00", "end": "19:30"})) == []


def test_pause_flags_roundtrip(tmp_path):
    assert not limits.is_paused(tmp_path)
    limits.pause(tmp_path, "posting", reason="holiday")
    assert limits.is_paused(tmp_path, "posting")
    assert not limits.is_paused(tmp_path, "comments")
    assert limits.pause_flags(tmp_path) == ["posting"]
    limits.pause(tmp_path)
    assert limits.is_paused(tmp_path, "comments")
    assert limits.pause_flags(tmp_path) == ["all", "posting"]
    removed = limits.resume(tmp_path, "posting")
    assert [p.name for p in removed] == ["PAUSE.posting"]
    assert limits.is_paused(tmp_path)
    limits.resume(tmp_path, "all")
    assert limits.pause_flags(tmp_path) == []
    with pytest.raises(ValueError):
        limits.pause(tmp_path, "everything-else")


def test_policy_constants_are_the_locked_values():
    assert policy.COMMENTS_REPLIES_PER_DAY_MAX == 10
    assert policy.POSTS_PER_WEEK_MAX == 7
    assert policy.POST_GAP_HOURS_FLOOR == 12
    assert policy.CONNECT_NOTE_MAX == 200
    assert policy.LIKES_DEFAULT is False
    assert set(policy.POST_STATUSES) == {
        "draft", "revising", "hold", "queued", "missed", "needs_check", "posted", "rejected",
        "demo"}
    assert policy.LINKEDIN_ENDPOINT_ALLOWLIST == (
        "/v2/userinfo", "/rest/posts", "/rest/images", "/rest/documents")
