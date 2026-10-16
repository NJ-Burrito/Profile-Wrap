"""The timing recipe: audience hours become a posting window that the config validator accepts."""
from __future__ import annotations

import datetime as dt
import json

import pytest

from njli import cli, config, limits
from njli.plan import timing
from njli.plan.spread import parse_hhmm

DAY = dt.date(2026, 11, 3)


def test_the_recipe_data_is_complete_and_dated():
    r = timing.load_recipe()
    assert r["schema_version"] == 1 and r["retrieved"]
    grades = {e["id"]: e["grade"] for e in r["evidence"]}
    assert grades["buffer-2026-09"] == "A" and all(g in "ABCX" for g in grades.values())
    assert all(e["url"].startswith("https://") for e in r["evidence"] if e["grade"] in "AB")
    assert {x["id"] for x in r["regions"]} >= {"us-east", "gulf", "levant", "uk"}
    assert r["not_known"], "the recipe says what it does not know"
    w = r["method"]["audience_hours_local"]
    assert parse_hhmm(w["end"]) - parse_hhmm(w["start"]) + 1 <= r["method"]["max_width_minutes"] + 1


def test_every_region_timezone_loads():
    from njli import tzutil
    for region in timing.load_recipe()["regions"]:
        assert tzutil.is_valid_timezone(region["tz"]), region


def test_same_timezone_gives_the_audience_slice_unchanged():
    s = timing.suggest_window("Asia/Dubai", ["gulf"], DAY)
    assert (s.start, s.end) == ("15:30", "18:58") or (s.start, s.end) == ("15:30", "18:59")
    assert not s.notes


def test_other_timezones_shift_the_slice_by_the_real_offset():
    s = timing.suggest_window("Europe/Lisbon", ["gulf"], dt.date(2026, 11, 3))   # Dubai is UTC+4, Lisbon UTC+0 in November
    assert s.start == "11:30"
    s2 = timing.suggest_window("Asia/Dubai", ["us-east"], dt.date(2026, 11, 3))  # New York UTC-5, Dubai UTC+4: +9 h
    assert s2.start == "00:30" or "midnight" in " ".join(s2.notes)


def test_two_regions_use_their_overlap_and_disjoint_ones_are_reported():
    s = timing.suggest_window("Europe/Lisbon", ["gulf", "levant"], DAY)
    assert s.overlap_regions == ["gulf", "levant"] and parse_hhmm(s.start) >= parse_hhmm("12:30")
    far = timing.suggest_window("Europe/Lisbon", ["us-east", "singapore"], DAY)
    assert far.notes and any("do not overlap" in n or "midnight" in n for n in far.notes)


def test_unknown_and_missing_regions_fall_back_with_a_note():
    s = timing.suggest_window("UTC", ["atlantis"], DAY)
    assert any("unknown audience regions" in n for n in s.notes) and s.start == "15:30"


@pytest.mark.parametrize("poster", ["UTC", "Asia/Tokyo", "America/Los_Angeles", "Pacific/Auckland", "Europe/Berlin"])
@pytest.mark.parametrize("regions", [["gulf"], ["us-east"], ["levant", "uk"], ["india", "australia-east"], []])
def test_the_suggestion_always_passes_the_config_validator(poster, regions):
    s = timing.suggest_window(poster, regions, DAY)
    assert 0 <= parse_hhmm(s.start) <= parse_hhmm(s.end) <= 1439
    cfg = config.defaults(poster)
    cfg["posting"]["window"] = {"start": s.start, "end": s.end}
    assert limits.check_limits(cfg) == []
    rep = config.validate(cfg)
    assert not [e for e in rep.errors if "window" in e], rep.errors


def test_the_command_prints_the_commands_to_apply_it(mkws, capsys):
    ws = mkws(locale__timezone="Europe/Lisbon")
    assert cli.main(["plan", "recipe", "--audience", "gulf", "--workspace", str(ws), "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert any(c.startswith("njli config set posting.window '{") for c in out["commands"])
    assert out["per_region"]["gulf"] and out["regions"] == ["gulf"]
    assert cli.main(["plan", "recipe", "--list", "--workspace", str(ws)]) == 0
    assert "Asia/Dubai" in capsys.readouterr().out
    # --apply writes both ends at once through the validated config path
    assert cli.main(["plan", "recipe", "--audience", "gulf", "--apply", "--workspace", str(ws)]) == 0
    capsys.readouterr()
    saved = config.load(ws)
    assert (saved["posting"]["window"]["start"], saved["posting"]["window"]["end"]) == (out["start"], out["end"])
    assert saved["locale"]["audience_regions"] == ["gulf"]
    assert config.validate(saved, ws).errors == []
