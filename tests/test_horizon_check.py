"""PW-R02: the horizon check. The next N planned days need a draft or a ledger row; an empty calendar is flagged."""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "integration" / "schedule"))
from schedhelp import make_ws  # noqa: E402

from profile_wrap import doctor  # noqa: E402
from profile_wrap.plan import calendar as cal  # noqa: E402

TODAY = dt.date(2026, 11, 2)


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("PROFILE_WRAP_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("PROFILE_WRAP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PROFILE_WRAP_TEST", "1")


def day(offset: int) -> str:
    return (TODAY + dt.timedelta(days=offset)).isoformat()


def entry(offset: int, slug: str = "", **kw):
    e = {"date": day(offset), "slug": slug or f"post-{offset}", "lang": "en", "format": "text",
         "title": f"Title {offset}", "status": "planned", "angle": "a"}
    e.update(kw)
    return e


def seed(ws, *entries):
    cal.update(ws, lambda c: c["entries"].extend(entries))


def draft(ws, slug, status="draft"):
    d = ws / "drafts" / slug
    d.mkdir(parents=True, exist_ok=True)
    (d / "meta.json").write_text(json.dumps({"slug": slug, "status": status}), encoding="utf-8")


def test_a_gap_inside_the_window_is_flagged_with_its_date(tmp_path):
    ws = make_ws(tmp_path)
    seed(ws, entry(1), entry(3))
    draft(ws, "post-1")
    h = doctor.horizon(ws, today=TODAY)
    assert h["status"] == "warn" and [m["slug"] for m in h["missing"]] == ["post-3"]
    assert day(3) in h["detail"] and "no draft" in h["detail"]


def test_a_gap_today_or_tomorrow_is_a_fail(tmp_path):
    ws = make_ws(tmp_path)
    seed(ws, entry(1))
    assert doctor.horizon(ws, today=TODAY)["status"] == "fail"
    assert doctor.horizon(ws, today=TODAY, fail_days=1)["status"] == "warn"


def test_every_planned_day_covered_passes(tmp_path):
    ws = make_ws(tmp_path)
    seed(ws, entry(0), entry(2), entry(6), entry(7))     # day 7 is outside a 7-day window
    for s in ("post-0", "post-2", "post-6"):
        draft(ws, s)
    h = doctor.horizon(ws, today=TODAY)
    assert h["status"] == "pass" and not h["missing"] and "3 planned" in h["detail"]


def test_skipped_blocked_and_posted_entries_are_not_gaps(tmp_path):
    ws = make_ws(tmp_path)
    seed(ws, entry(1, status="skipped"), entry(2, status="blocked"), entry(3, status="posted"),
         entry(4, slug="in-ledger"))
    (ws / "published").mkdir(exist_ok=True)
    (ws / "published" / "ledger.jsonl").write_text(json.dumps({"slug": "in-ledger"}) + "\n", encoding="utf-8")
    assert doctor.horizon(ws, today=TODAY)["status"] == "pass"


def test_a_rejected_draft_and_an_open_slot_count_as_missing(tmp_path):
    ws = make_ws(tmp_path)
    seed(ws, entry(3), entry(4, title="Open slot", open=True))
    draft(ws, "post-3", status="rejected")
    h = doctor.horizon(ws, today=TODAY)
    assert {m["reason"] for m in h["missing"]} == {"the draft is rejected", "open slot, not briefed"}


def test_an_empty_calendar_and_a_calendar_with_nothing_soon_are_flagged(tmp_path):
    ws = make_ws(tmp_path)
    h = doctor.horizon(ws, today=TODAY)
    assert h["status"] == "warn" and h["empty"] and "empty" in h["detail"]
    seed(ws, entry(30))
    h = doctor.horizon(ws, today=TODAY)
    assert h["status"] == "warn" and h["empty"] and "nothing planned in the next 7 days" in h["detail"]


def test_the_window_length_is_configurable(tmp_path):
    ws = make_ws(tmp_path)
    seed(ws, entry(10))
    assert doctor.horizon(ws, today=TODAY)["empty"] is True
    assert doctor.horizon(ws, today=TODAY, days=14)["status"] == "warn"
    assert doctor.horizon(ws, {"schedule": {"horizon_days": 14}}, today=TODAY)["missing"][0]["slug"] == "post-10"


def test_a_broken_calendar_is_a_warning_not_a_crash(tmp_path):
    ws = make_ws(tmp_path)
    (ws / "strategy" / "calendar.json").write_text("{not json", encoding="utf-8")
    h = doctor.horizon(ws, today=TODAY)
    assert h["status"] == "warn" and "cannot be read" in h["detail"]


def test_doctor_reports_the_horizon_check_for_a_workspace(tmp_path):
    ws = make_ws(tmp_path)
    result = doctor.run(workspace=ws)
    row = next(c for c in result["checks"] if c["id"] == "horizon")
    assert row["status"] == "warn" and "empty" in row["detail"] and row["hint"]


def test_doctor_has_no_horizon_row_without_a_workspace():
    result = doctor.run(workspace=None)
    assert all(c["id"] != "horizon" for c in result["checks"])
