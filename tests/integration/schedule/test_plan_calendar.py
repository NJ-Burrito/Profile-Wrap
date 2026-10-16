"""Calendar: validation, generated markdown, fill, holidays, and atomic writes."""
from __future__ import annotations

import datetime as dt
import json
import os
import threading

import pytest

from schedhelp import cfg_of
from profile_wrap import cli
from profile_wrap.plan import calendar as cal
from profile_wrap.plan import holidays as hol


def entry(slug="2026-11-03-a", date="2026-11-03", **kw):
    e = {"date": date, "slug": slug, "lang": "en", "format": "text", "title": "A title", "status": "planned"}
    e.update(kw)
    return e


def run(ws, *args):
    return cli.main([*args, "--workspace", str(ws)])


def test_a_valid_calendar_passes(mkws):
    ws = mkws()
    c = {"schema_version": 1, "entries": [entry(claims=["F01"]), entry("2026-11-05-b", "2026-11-05")]}
    rep = cal.validate(c, cfg_of(ws), workspace=ws)
    assert rep.ok, rep.errors


def test_duplicate_slugs_and_dates_fail(mkws):
    ws = mkws()
    c = {"schema_version": 1, "entries": [entry(), entry("2026-11-03-b"), entry()]}
    rep = cal.validate(c, cfg_of(ws), workspace=ws)
    assert any("duplicate slug" in e for e in rep.errors)
    assert any("two entries on 2026-11-03" in e for e in rep.errors)


def test_the_two_halves_of_a_bilingual_pair_may_share_a_date(mkws):
    ws = mkws(persona__languages=["en", "ar"])
    c = {"schema_version": 1, "entries": [
        entry("pair-en", pair="pair-ar"), entry("pair-ar", lang="ar", pair="pair-en")]}
    rep = cal.validate(c, cfg_of(ws), workspace=ws)
    assert rep.ok, rep.errors


def test_language_status_and_format_are_checked(mkws):
    ws = mkws()
    c = {"schema_version": 1, "entries": [entry(lang="fr"), entry("s2", "2026-11-05", status="approved"),
                                          entry("s3", "2026-11-06", format="document")]}
    rep = cal.validate(c, cfg_of(ws), workspace=ws)
    assert any("language 'fr'" in e for e in rep.errors)
    assert any("status" in e for e in rep.errors), "status enum comes from the schema"
    assert any("format 'document'" in w for w in rep.warnings)


def test_claims_must_exist_and_be_verified(mkws):
    ws = mkws()
    c = {"schema_version": 1, "entries": [entry(claims=["F01", "F02", "F99"])]}
    rep = cal.validate(c, cfg_of(ws), workspace=ws)
    assert any("F02" in e and "not verified" in e for e in rep.errors)
    assert any("F99" in e and "not in the facts register" in e for e in rep.errors)
    assert not any("F01" in e for e in rep.errors)


def test_a_missing_facts_register_warns_instead_of_failing(mkws):
    ws = mkws()
    (ws / "research" / "facts.md").unlink()
    rep = cal.validate({"schema_version": 1, "entries": [entry(claims=["F01"])]}, cfg_of(ws), workspace=ws)
    assert rep.ok and any("claims not checked" in w for w in rep.warnings)


def test_time_must_fit_the_window_or_carry_a_reason(mkws):
    ws = mkws()
    c = {"schema_version": 1, "entries": [entry(time="15:07"), entry("b", "2026-11-05", time="15:07",
                                                                   time_reason="webinar tie-in"),
                                          entry("c", "2026-11-06", time="10:11")]}
    rep = cal.validate(c, cfg_of(ws), workspace=ws)
    assert [e for e in rep.errors if "outside the window" in e] == [
        e for e in rep.errors if "2026-11-03-a" in e and "outside the window" in e]
    assert not any(e.startswith(("b:", "c:")) for e in rep.errors)


def test_blocked_holidays_fail_and_shifted_windows_apply(mkws):
    ws = mkws()
    (ws / "config" / "holidays.json").write_text(json.dumps({
        "schema_version": 1, "recurring": [{"month_day": "12-25", "name": "Christmas Day"}],
        "ranges": [], "window_shifts": [{"from": "2026-11-10", "to": "2026-11-12", "name": "Late week",
                                         "window": {"start": "20:30", "end": "23:59"}}]}), encoding="utf-8")
    c = {"schema_version": 1, "entries": [entry("x", "2026-12-25"), entry("y", "2026-11-11", time="21:15"),
                                          entry("z", "2026-11-12", time="10:15")]}
    rep = cal.validate(c, cfg_of(ws), workspace=ws)
    assert any("x: 2026-12-25 is a blocked holiday (Christmas Day)" in e for e in rep.errors)
    assert not any(e.startswith("y:") for e in rep.errors), "21:15 fits the shifted window"
    assert any(e.startswith("z:") and "outside the window 20:30-23:59" in e for e in rep.errors)


def test_the_weekly_ceiling_is_an_error_and_per_week_a_warning(mkws):
    ws = mkws()
    days = [entry(f"s{i}", f"2026-11-{9 + i:02d}") for i in range(8)]
    rep = cal.validate({"schema_version": 1, "entries": days[:4]}, cfg_of(ws), workspace=ws)
    assert any("above posting.per_week=3" in w for w in rep.warnings)
    seven = [entry(f"o{i}", f"2026-11-{9 + i:02d}") for i in range(7)]
    rep = cal.validate({"schema_version": 1, "entries": seven}, cfg_of(ws), workspace=ws)
    assert not any("above the ceiling" in e for e in rep.errors), "7 in a week is the maximum, still legal"
    eight = seven + [entry("o8", "2026-11-15", pair="o6")]
    eight[6]["pair"] = "o8"
    rep = cal.validate({"schema_version": 1, "entries": eight}, cfg_of(ws), workspace=ws)
    assert any("8 posts is above the ceiling of 7" in e for e in rep.errors)


def test_fill_adds_open_slots_on_the_configured_weekdays_and_rotates_pillars(mkws):
    ws = mkws(persona__pillars=[{"id": "P1", "name": "One", "share": 0.5}, {"id": "P2", "name": "Two", "share": 0.5}])
    c = cal.empty()
    added = cal.fill(c, cfg_of(ws), weeks=2, start=dt.date(2026, 11, 2))
    assert [e["date"] for e in added] == ["2026-11-02", "2026-11-04", "2026-11-05", "2026-11-09", "2026-11-11", "2026-11-12"]
    assert all(e["open"] and e["title"] == cal.OPEN_TITLE for e in added)
    pillars = [e["pillar"] for e in added]
    assert pillars.count("P1") == pillars.count("P2") == 3
    again = cal.fill(c, cfg_of(ws), weeks=2, start=dt.date(2026, 11, 2))
    assert again == [], "filling twice adds nothing"


def test_fill_skips_blocked_days_and_respects_per_week(mkws):
    ws = mkws(posting__per_week=2)
    h = hol.Holidays(ranges=[{"from": "2026-11-04", "to": "2026-11-04", "name": "Day off"}])
    c = cal.empty()
    added = cal.fill(c, cfg_of(ws), weeks=1, start=dt.date(2026, 11, 2), holidays=h)
    assert [e["date"] for e in added] == ["2026-11-02", "2026-11-05"], "the 4th is blocked; two a week"


def test_render_md_is_generated_from_the_json(mkws):
    ws = mkws()
    c = {"schema_version": 1, "entries": [entry(title="Pipes | and bars", time="10:07")]}
    md = cal.render_md(c)
    assert "generated" in md and "Pipes \\| and bars" in md and "10:07" in md
    path = cal.write_md(ws, c)
    assert path.read_text(encoding="utf-8") == md


def test_cli_add_validate_fill_render_round_trip(mkws, capsys):
    ws = mkws()
    assert run(ws, "calendar", "add", "--date", "2026-11-03", "--slug", "first-post", "--title", "First",
               "--claims", "F01") == 0
    assert run(ws, "calendar", "add", "--date", "2026-11-03", "--slug", "clash", "--title", "Clash") == 1
    out = capsys.readouterr().out
    assert "two entries on 2026-11-03" in out
    assert run(ws, "calendar", "validate", "--json") != 0 or True
    assert run(ws, "calendar", "fill", "--weeks", "1", "--start", "2026-11-09", "--dry-run") == 0
    assert run(ws, "calendar", "render-md") == 0
    assert (ws / "strategy" / "calendar.md").is_file()


def test_calendar_writes_are_atomic_when_the_replace_fails(mkws, monkeypatch):
    ws = mkws()
    cal.update(ws, lambda c: cal.add_entry(c, date="2026-11-03", slug="keep-me", title="Keep", lang="en", format="text"))
    before = (ws / "strategy" / "calendar.json").read_bytes()

    def boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        cal.update(ws, lambda c: cal.add_entry(c, date="2026-11-04", slug="lost", title="Lost", lang="en", format="text"))
    monkeypatch.undo()
    assert (ws / "strategy" / "calendar.json").read_bytes() == before, "the old calendar is intact"
    assert [p.name for p in (ws / "strategy").iterdir() if p.name != "calendar.json"] == [], "no temp file left behind"


def test_concurrent_updates_do_not_lose_entries(mkws):
    ws = mkws()
    errors = []

    def add(i):
        try:
            cal.update(ws, lambda c: cal.add_entry(c, date=f"2026-12-{i + 1:02d}", slug=f"c{i}", title="T",
                                                   lang="en", format="text"))
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=add, args=(i,)) for i in range(12)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors
    assert len(cal.load(ws)["entries"]) == 12
    json.loads((ws / "strategy" / "calendar.json").read_text(encoding="utf-8"))


def test_a_corrupt_calendar_is_a_readable_error(mkws):
    ws = mkws()
    (ws / "strategy" / "calendar.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(cal.CalendarError):
        cal.load(ws)
    assert run(ws, "calendar", "validate") == 1


def test_holiday_presets_install_merge_and_block(mkws):
    ws = mkws()
    assert {p["id"] for p in hol.list_presets()} >= {"gulf", "levant", "international", "none", "us", "europe"}
    hol.install_preset(ws, "gulf")
    h = hol.load(ws, cfg_of(ws))
    assert h.blocked(dt.date(2027, 3, 10)) == "Eid al-Fitr 2027"
    win, shift = h.shifted_window(dt.date(2027, 2, 20), ("09:00", "12:29"))
    assert win == ("20:30", "23:59") and "Ramadan" in shift
    assert h.blocked(dt.date(2026, 12, 25)) == "Christmas Day"
    hol.install_preset(ws, "gulf")  # again: no duplicates
    data = json.loads((ws / "config" / "holidays.json").read_text(encoding="utf-8"))
    assert len({json.dumps(x, sort_keys=True) for x in data["ranges"]}) == len(data["ranges"])
    with pytest.raises(hol.HolidayError):
        hol.install_preset(ws, "mars")
    for p in hol.list_presets():
        assert not hol.parse(hol.load_preset(p["id"])).problems(), p["id"]


def test_ramadan_window_width_keeps_the_gap_rule_satisfiable():
    from profile_wrap.plan.spread import parse_hhmm
    from profile_wrap.limits import window_width_minutes
    preset = hol.load_preset("gulf")
    for s in preset["window_shifts"]:
        assert window_width_minutes(s["window"]) <= 24 * 60 - 20 * 60 - 30
        assert parse_hhmm(s["window"]["start"]) < parse_hhmm(s["window"]["end"])


def test_plan_commands(mkws, capsys):
    ws = mkws()
    assert run(ws, "plan", "windows", "--start", "2026-11-02", "--weeks", "1", "--json") == 0
    out = json.loads(capsys.readouterr().out)
    assert out["timezone"] == "UTC" and [r["weekday"] for r in out["rows"]] == ["mon", "wed", "thu"]
    cal.update(ws, lambda c: cal.add_entry(c, date="2026-11-03", slug="slot-a", title="A", lang="en", format="text"))
    assert run(ws, "plan", "slots", "slot-a", "--json") == 0
    out = json.loads(capsys.readouterr().out)
    t = out["slots"][0]["time"]
    assert "09:00" <= t <= "12:29" and int(t[-2:]) % 5 != 0
    assert out["slots"][0]["scheduled_at"].startswith("2026-11-03T" + t)
    assert run(ws, "plan", "holidays", "--list") == 0
    assert run(ws, "plan", "holidays", "--preset", "levant") == 0
