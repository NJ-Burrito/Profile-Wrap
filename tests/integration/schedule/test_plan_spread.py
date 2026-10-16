"""``spread_time`` property tests (design-spec section 14).

The full sweep of 10,000 slugs x 365 days is behind NJLI_FULL_PROPERTY=1 (it takes minutes); the
default run does the same checks on smaller samples.
"""
from __future__ import annotations

import datetime as dt
import os
import random
import string

import pytest

from njli.plan import spread
from njli.plan.spread import fmt_hhmm, parse_hhmm, spread_detail, spread_time

WINDOW = ("09:00", "12:29")
GAP_MIN = 20 * 60 + spread.LAG_MINUTES
FULL = os.environ.get("NJLI_FULL_PROPERTY") == "1"


def slugs(n: int, seed: int = 7):
    rnd = random.Random(seed)
    for _ in range(n):
        yield "".join(rnd.choice(string.ascii_lowercase + string.digits + "-") for _ in range(rnd.randint(6, 40)))


def chain(slug_iter, days: int, start=dt.date(2026, 1, 1), **kw):
    """One post a day: each slug gets the next day, seeing the earlier days as neighbours."""
    taken, out = {}, []
    for i, slug in zip(range(days), slug_iter):
        day = start + dt.timedelta(days=i)
        det = spread_detail(slug, day, taken=taken, **kw)
        taken[day.isoformat()] = det.time
        out.append((day, slug, det))
    return out


def test_every_slug_lands_inside_the_window_and_off_the_round_marks():
    lo, hi = parse_hhmm(WINDOW[0]), parse_hhmm(WINDOW[1])
    for slug in slugs(10_000 if FULL else 3_000):
        t = parse_hhmm(spread_time(slug, "2026-03-03", window=WINDOW))
        assert lo <= t <= hi, slug
        assert t % 5 != 0, (slug, fmt_hhmm(t))


def test_the_time_is_stable_per_slug():
    for slug in slugs(500):
        a = spread_time(slug, "2026-05-05")
        assert all(spread_time(slug, "2026-05-05") == a for _ in range(3))
    kw = dict(window=WINDOW)
    assert spread_time("alpha", "2026-05-05", **kw) == spread_time("alpha", dt.date(2026, 5, 5), **kw)


def test_different_slugs_do_not_all_pick_the_same_minute():
    minutes = {spread_time(s, "2026-05-05") for s in slugs(400)}
    assert len(minutes) > 100, "the old hash produced repeats; this one must spread"


def test_a_year_of_daily_posts_never_repeats_a_minute_within_14_days_and_keeps_the_gap():
    n_streams = 3 if not FULL else 27
    for stream in range(n_streams):
        rows = chain(slugs(365, seed=stream), 365, no_repeat_days=14)
        assert all(not det.relaxed for _d, _s, det in rows), "no rule had to be relaxed"
        times = [(d, parse_hhmm(det.time)) for d, _s, det in rows]
        for i, (d, m) in enumerate(times):
            assert parse_hhmm(WINDOW[0]) <= m <= parse_hhmm(WINDOW[1])
            for j in range(max(0, i - 14), i):
                assert times[j][1] != m, f"minute {fmt_hhmm(m)} repeated within 14 days ({times[j][0]} and {d})"
            if i:
                prev_d, prev_m = times[i - 1]
                gap = (d - prev_d).days * 1440 + m - prev_m
                assert gap >= GAP_MIN, f"gap {gap} min is under {GAP_MIN} on {d}"


@pytest.mark.skipif(not FULL, reason="set NJLI_FULL_PROPERTY=1 for the full 10,000 x 365 sweep")
def test_full_sweep_10000_slugs_x_365_days():
    lo, hi = parse_hhmm(WINDOW[0]), parse_hhmm(WINDOW[1])
    base = dt.date(2026, 1, 1)
    count = 0
    for slug in slugs(10_000, seed=99):
        for k in range(365):  # every day of the year, per slug
            t = parse_hhmm(spread_time(slug, base + dt.timedelta(days=k)))
            assert lo <= t <= hi and t % 5 != 0
            count += 1
    assert count == 10_000 * 365


def test_a_wider_window_and_a_longer_gap_are_respected():
    rows = chain(slugs(60, seed=3), 60, window=("08:00", "11:10"), min_gap_hours=21, no_repeat_days=7)
    need = 21 * 60 + spread.LAG_MINUTES
    for (d0, _s0, a), (d1, _s1, b) in zip(rows, rows[1:]):
        gap = 1440 + parse_hhmm(b.time) - parse_hhmm(a.time)
        assert gap >= need
        assert not a.relaxed and not b.relaxed


def test_neighbours_push_the_slot_so_the_gap_holds_even_with_a_very_wide_window():
    taken = {"2026-06-09": "12:29", "2026-06-11": "09:01"}
    det = spread_detail("some-slug", "2026-06-10", window=("09:00", "23:00"), taken=taken)
    m = parse_hhmm(det.time)
    assert m >= parse_hhmm("12:29") + GAP_MIN - 1440 and m <= parse_hhmm("09:01") + 1440 - GAP_MIN
    assert not det.relaxed


def test_when_nothing_fits_the_rules_are_relaxed_in_order_and_reported():
    # one narrow window and a long gap: the post the day before leaves no legal minute
    det = spread_detail("x", "2026-06-10", window=("09:00", "09:20"), min_gap_hours=24.5,
                        taken={"2026-06-09": "09:10"})
    assert det.relaxed[:2] == ["repeat", "window"] and det.minute >= parse_hhmm("09:55")
    assert 0 <= det.minute <= 1439


def test_daylight_saving_is_counted_in_real_time():
    # Berlin springs forward on 2026-03-29: the wall-clock gap understates the real one by an hour.
    taken = {"2026-03-28": "12:29"}
    plain = parse_hhmm(spread_time("dst-slug", "2026-03-29", taken=taken))
    zoned = parse_hhmm(spread_time("dst-slug", "2026-03-29", taken=taken, tz="Europe/Berlin"))
    assert plain >= 9 * 60
    real_gap = (zoned - parse_hhmm("12:29")) + 1440 - 60  # an hour was skipped overnight
    assert real_gap >= GAP_MIN or zoned > parse_hhmm(WINDOW[1])


def test_bad_input_is_a_readable_error():
    with pytest.raises(ValueError):
        parse_hhmm("25:00")
    with pytest.raises(ValueError):
        spread_time("a", "2026-01-01", window=("12:00", "09:00"))


def test_config_adapter_reads_the_posting_block():
    cfg = {"posting": {"window": {"start": "10:00", "end": "11:00"}, "min_gap_hours": 22,
                       "spread": {"avoid_round_minutes": False, "no_repeat_days": 3}},
           "locale": {"timezone": "UTC"}}
    kw = spread.kwargs_from_config(cfg)
    assert kw == {"window": ("10:00", "11:00"), "min_gap_hours": 22, "no_repeat_days": 3,
                  "avoid_round": False, "tz": "UTC"}
    t = parse_hhmm(spread_time("s", "2026-02-02", **kw))
    assert parse_hhmm("10:00") <= t <= parse_hhmm("11:00")
