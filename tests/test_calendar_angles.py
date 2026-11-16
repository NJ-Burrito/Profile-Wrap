"""PW-05: angle dedup on a shared ``subject``, and ``prior_angles`` for the build prompt."""
from __future__ import annotations

import json

from profile_wrap import ledger
from profile_wrap.plan import calendar as calmod

CFG = {"persona": {"languages": ["en", "ar"]}, "posting": {"formats_enabled": ["text"]}}


def cal_with(*entries):
    cal = calmod.empty()
    for e in entries:
        calmod.add_entry(cal, lang="en", format="text", **e)
    return cal


def test_same_subject_similar_angle_warns():
    cal = cal_with(
        dict(date="2026-12-02", slug="a", title="T1", status="posted", subject="widget",
             angle="why I built the widget for my own team"),
        dict(date="2026-12-09", slug="b", title="T2", subject="widget",
             angle="why I built the widget for my team"))
    rep = calmod.validate(cal, CFG)
    assert rep.ok
    assert any("b: angle repeats a" in w for w in rep.warnings)


def test_different_angle_or_subject_passes():
    cal = cal_with(
        dict(date="2026-12-02", slug="a", title="T1", status="posted", subject="widget",
             angle="why I built the widget for my own team"),
        dict(date="2026-12-09", slug="b", title="T2", subject="widget",
             angle="one real failure the widget caught last month"),
        dict(date="2026-12-10", slug="c", title="T3", subject="other",
             angle="why I built the widget for my own team"))
    assert calmod.validate(cal, CFG).warnings == []


def test_pair_halves_and_skipped_entries_are_not_compared():
    cal = cal_with(
        dict(date="2026-12-02", slug="a", title="T1", subject="widget", angle="same angle words here now", pair="b"),
        dict(date="2026-12-02", slug="b", title="T2", subject="Widget", angle="same angle words here now", pair="a"),
        dict(date="2026-12-09", slug="c", title="T3", status="skipped", subject="widget",
             angle="same angle words here now"))
    rep = calmod.validate(cal, CFG)
    assert not [w for w in rep.warnings if "repeats" in w]


def test_subject_without_angle_warns_and_gap_is_optional():
    cal = cal_with(dict(date="2026-12-02", slug="a", title="T1", subject="widget"),
                   dict(date="2026-12-04", slug="b", title="T2", subject="widget", angle="a quite different idea"))
    assert any("a: subject 'widget' is set but the entry has no angle" in w for w in calmod.validate(cal, CFG).warnings)
    cfg = {**CFG, "plan": {"subject_min_gap_days": 4}}
    assert any("2 days after a" in w for w in calmod.validate(cal, cfg).warnings)


def test_overlap_threshold_comes_from_config():
    cal = cal_with(
        dict(date="2026-12-02", slug="a", title="T1", status="posted", subject="s", angle="alpha beta gamma delta"),
        dict(date="2026-12-09", slug="b", title="T2", subject="s", angle="alpha beta gamma epsilon"))
    assert calmod.angle_overlap("alpha beta gamma delta", "alpha beta gamma epsilon") == 0.6
    assert len(calmod.validate(cal, CFG).warnings) == 1                      # 0.6 is above the default 0.5
    assert calmod.validate(cal, {**CFG, "plan": {"angle_overlap_max": 0.7}}).warnings == []


def test_prior_angles_reads_calendar_and_ledger_most_recent_first(tmp_path):
    ws = tmp_path
    cal = cal_with(
        dict(date="2026-12-02", slug="a", title="First", status="posted", subject="Widget", angle="why I built it"),
        dict(date="2026-12-09", slug="b", title="Second", subject="widget", angle="how it works"),
        dict(date="2026-12-16", slug="c", title="Third", subject="widget", angle="one limit"),
        dict(date="2026-12-17", slug="d", title="Elsewhere", subject="other", angle="nope"),
        dict(date="2026-12-18", slug="e", title="Dropped", status="skipped", subject="widget", angle="skipped"))
    calmod.save(ws, cal)
    # a hand-posted draft that never entered the calendar: found through the ledger and its meta.json
    (ws / "drafts" / "old").mkdir(parents=True)
    (ws / "drafts" / "old" / "meta.json").write_text(json.dumps(
        {"slug": "old", "title": "Earlier", "subject": "widget", "angle": "the origin story"}), encoding="utf-8")
    ledger.append(ws, {"slug": "old", "state": "posted", "idempotency_key": "k", "posted_at": "2026-11-20T10:00:00+02:00",
                       "automation": {"mode": "copy", "by": "user"}})
    got = calmod.prior_angles("WIDGET", ws, exclude_slug="c")
    assert [x["slug"] for x in got] == ["b", "a", "old"]
    assert calmod.prior_angles("widget", ws, before="2026-12-09")[0]["slug"] == "a"
    assert calmod.prior_angles("", ws) == [] and calmod.prior_angles("nothing", ws) == []
    text = calmod.format_prior_angles(got)
    assert text.splitlines()[0] == "- Second | how it works"
    assert "none yet" in calmod.format_prior_angles([])
