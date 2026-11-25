"""PW-07: ``calendar insert`` and ``calendar shift``: pinned, pairs, holidays, drafts, dry run, atomic write."""
from __future__ import annotations

import datetime as dt
import json

import pytest

from profile_wrap import cli
from profile_wrap.plan import calendar as calmod
from profile_wrap.plan import holidays as hol

CFG = {"persona": {"languages": ["en", "ar"]},
       "posting": {"weekdays": ["mon", "wed", "thu"], "per_week": 3, "formats_enabled": ["text"]},
       "locale": {"timezone": "Asia/Amman"}}
D = dt.date.fromisoformat


def make(*rows):
    cal = calmod.empty()
    for r in rows:
        r = dict(r)
        calmod.add_entry(cal, lang=r.pop("lang", "en"), format="text", title=r["slug"], **r)
    return cal


def dates(cal):
    return {e["slug"]: e["date"] for e in cal["entries"]}


def test_shift_moves_to_next_free_weekday_slot_and_keeps_order():
    cal = make(dict(date="2026-12-02", slug="a"), dict(date="2026-12-03", slug="b"), dict(date="2026-12-07", slug="c"))
    plan = calmod.reschedule(cal, CFG, start=D("2026-12-02"), days=1)
    assert dates(cal) == {"a": "2026-12-03", "b": "2026-12-07", "c": "2026-12-09"}   # wed, thu, mon -> thu, mon, wed
    assert [m.slug for m in plan.moves] == ["a", "b", "c"]


def test_entries_before_the_start_and_fixed_statuses_never_move():
    cal = make(dict(date="2026-11-30", slug="early"), dict(date="2026-12-02", slug="done", status="posted"),
               dict(date="2026-12-03", slug="skip", status="skipped"), dict(date="2026-12-07", slug="m"))
    calmod.reschedule(cal, CFG, start=D("2026-12-01"), days=1)
    assert dates(cal) == {"early": "2026-11-30", "done": "2026-12-02", "skip": "2026-12-03", "m": "2026-12-09"}


def test_pinned_entry_stays_and_others_hop_over_it():
    cal = make(dict(date="2026-12-02", slug="a"), dict(date="2026-12-03", slug="pin", pinned=True),
               dict(date="2026-12-07", slug="c"))
    calmod.reschedule(cal, CFG, start=D("2026-12-02"), days=1)
    assert dates(cal)["pin"] == "2026-12-03"
    assert dates(cal)["a"] == "2026-12-07" and dates(cal)["c"] == "2026-12-09"


def test_pair_moves_together_on_one_date_and_keeps_offset():
    cal = make(dict(date="2026-12-02", slug="en1", pair="ar1"),
               dict(date="2026-12-02", slug="ar1", lang="ar", pair="en1"),
               dict(date="2026-12-07", slug="en2", pair="ar2"),
               dict(date="2026-12-09", slug="ar2", lang="ar", pair="en2"))
    calmod.reschedule(cal, CFG, start=D("2026-12-02"), days=1)
    d = dates(cal)
    assert d["en1"] == d["ar1"] == "2026-12-03"
    assert (D(d["ar2"]) - D(d["en2"])).days == 2                                   # offset of two days kept
    assert D(d["en2"]) > D("2026-12-07")


def test_pair_with_a_pinned_half_does_not_move_and_warns():
    cal = make(dict(date="2026-12-02", slug="en1", pair="ar1"),
               dict(date="2026-12-02", slug="ar1", lang="ar", pair="en1", pinned=True))
    plan = calmod.reschedule(cal, CFG, start=D("2026-12-02"), days=1)
    assert set(dates(cal).values()) == {"2026-12-02"} and plan.moves == []
    assert any("pair" in w for w in plan.warnings)


def test_holidays_are_skipped():
    holidays = hol.Holidays(ranges=[{"from": "2026-12-03", "to": "2026-12-07", "name": "Break"}])
    cal = make(dict(date="2026-12-02", slug="a"))
    calmod.reschedule(cal, CFG, start=D("2026-12-02"), days=1, holidays=holidays)
    assert dates(cal)["a"] == "2026-12-09"


def test_days_must_be_positive():
    with pytest.raises(calmod.CalendarError):
        calmod.reschedule(make(), CFG, start=D("2026-12-02"), days=0)


def write_draft(ws, slug, status, when):
    folder = ws / "drafts" / slug
    folder.mkdir(parents=True)
    (folder / "meta.json").write_text(json.dumps({"slug": slug, "status": status, "scheduled_at": when}),
                                      encoding="utf-8")


def test_built_draft_is_redated_keeping_time_of_day_only_while_draft(tmp_path):
    write_draft(tmp_path, "a", "draft", "2026-12-02T10:17:00+03:00")
    write_draft(tmp_path, "q", "queued", "2026-12-07T11:00:00+03:00")
    cal = make(dict(date="2026-12-02", slug="a", status="built"), dict(date="2026-12-07", slug="q", status="built"))
    plan = calmod.reschedule(cal, CFG, start=D("2026-12-02"), days=1, workspace=tmp_path)
    assert dates(cal) == {"a": "2026-12-03", "q": "2026-12-07"}
    assert plan.draft_meta["a"]["scheduled_at"] == "2026-12-03T10:17:00+03:00"
    assert "q" not in plan.draft_meta and any("q: built and its draft is 'queued'" in w for w in plan.warnings)


def cli_ws(tmp_path, monkeypatch, entries):
    monkeypatch.setenv("PROFILE_WRAP_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("PROFILE_WRAP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("PROFILE_WRAP_WORKSPACE", raising=False)
    # the CLI's default config takes the machine's zone (UTC on CI); pin it so the expected +03:00 holds anywhere
    monkeypatch.setattr("profile_wrap.tzutil.detect_timezone", lambda: "Asia/Amman")
    ws = tmp_path / "ws"
    ws.mkdir()
    calmod.save(ws, make(*entries))
    return ws


def run(ws, *args):
    return cli.main(["calendar", *args, "--workspace", str(ws)])


def test_cli_shift_dry_run_prints_diff_and_writes_nothing(tmp_path, monkeypatch, capsys):
    ws = cli_ws(tmp_path, monkeypatch, [dict(date="2026-12-02", slug="a"), dict(date="2026-12-03", slug="b")])
    before = calmod.calendar_path(ws).read_bytes()
    assert run(ws, "shift", "--from", "2026-12-02", "--days", "1", "--dry-run") == 0
    out = capsys.readouterr().out
    assert "move a: 2026-12-02 (wed) -> 2026-12-03 (thu)" in out and "dry run: nothing was written" in out
    assert calmod.calendar_path(ws).read_bytes() == before


def test_cli_shift_writes_changes_log_redates_draft_and_validates(tmp_path, monkeypatch, capsys):
    ws = cli_ws(tmp_path, monkeypatch, [dict(date="2026-12-02", slug="a", status="built"),
                                        dict(date="2026-12-03", slug="b")])
    write_draft(ws, "a", "draft", "2026-12-02T10:17:00+03:00")
    assert run(ws, "shift", "--from", "2026-12-02", "--days", "1") == 0
    cal = calmod.load(ws)
    assert dates(cal) == {"a": "2026-12-03", "b": "2026-12-07"}
    assert cal["changes"][-1]["what"].startswith("shift from 2026-12-02 by 1 days")
    meta = json.loads((ws / "drafts" / "a" / "meta.json").read_text(encoding="utf-8"))
    assert meta["scheduled_at"] == "2026-12-03T10:17:00+03:00"
    assert (ws / "strategy" / "calendar.md").is_file()
    capsys.readouterr()
    assert run(ws, "validate") == 0


def test_cli_insert_on_taken_date_pushes_later_planned_entries(tmp_path, monkeypatch, capsys):
    ws = cli_ws(tmp_path, monkeypatch, [dict(date="2026-12-02", slug="a"), dict(date="2026-12-03", slug="b"),
                                        dict(date="2026-12-07", slug="c")])
    assert run(ws, "insert", "2026-12-02", "--slug", "new", "--title", "New", "--subject", "widget",
               "--angle", "x") == 0
    assert dates(calmod.load(ws)) == {"new": "2026-12-02", "a": "2026-12-03", "b": "2026-12-07", "c": "2026-12-09"}
    assert calmod.find(calmod.load(ws), "new")["subject"] == "widget"
    capsys.readouterr()
    assert run(ws, "validate") == 0


def test_insert_on_a_free_date_moves_nothing_and_a_pair_half_may_share_the_date(tmp_path, monkeypatch):
    ws = cli_ws(tmp_path, monkeypatch, [dict(date="2026-12-02", slug="en1", pair="ar1"),
                                        dict(date="2026-12-07", slug="c")])
    assert run(ws, "insert", "2026-12-03", "--slug", "x", "--title", "X") == 0
    assert run(ws, "insert", "2026-12-02", "--slug", "ar1", "--title", "A", "--pair", "en1") == 0
    d = dates(calmod.load(ws))
    assert d["x"] == "2026-12-03" and d["c"] == "2026-12-07" and d["ar1"] == d["en1"] == "2026-12-02"


def test_insert_refuses_a_pinned_day_a_holiday_and_a_duplicate_slug(tmp_path, monkeypatch, capsys):
    ws = cli_ws(tmp_path, monkeypatch, [dict(date="2026-12-02", slug="a", pinned=True)])
    (ws / "config").mkdir()
    (ws / "config" / "holidays.json").write_text(json.dumps(
        {"schema_version": 1, "ranges": [{"from": "2026-12-09", "name": "Closed"}]}), encoding="utf-8")
    before = calmod.calendar_path(ws).read_bytes()
    assert run(ws, "insert", "2026-12-02", "--slug", "n", "--title", "N") == 1
    assert "which cannot move" in capsys.readouterr().out
    assert run(ws, "insert", "2026-12-09", "--slug", "n", "--title", "N") == 1
    assert "blocked holiday (Closed)" in capsys.readouterr().out
    assert run(ws, "insert", "2026-12-03", "--slug", "a", "--title", "N") == 1
    assert "slug already in the calendar" in capsys.readouterr().out
    assert calmod.calendar_path(ws).read_bytes() == before


def test_failed_calendar_write_restores_the_draft_files(tmp_path, monkeypatch):
    write_draft(tmp_path, "a", "draft", "2026-12-02T10:17:00+03:00")
    calmod.save(tmp_path, make(dict(date="2026-12-02", slug="a", status="built")))
    meta_before = (tmp_path / "drafts" / "a" / "meta.json").read_bytes()
    cal_before = calmod.calendar_path(tmp_path).read_bytes()

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(calmod, "save", boom)
    with pytest.raises(OSError):
        calmod.apply_reschedule(tmp_path, lambda cal: calmod.reschedule(
            cal, CFG, start=D("2026-12-02"), days=1, workspace=tmp_path), what="shift")
    assert (tmp_path / "drafts" / "a" / "meta.json").read_bytes() == meta_before
    assert calmod.calendar_path(tmp_path).read_bytes() == cal_before
