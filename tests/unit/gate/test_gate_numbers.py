"""The claim-bound number extractor: what counts as a claim, what is exempt, what proves what."""
from __future__ import annotations

import pytest

from profile_wrap.facts.numspec import NumSpec, parse_number_cell
from profile_wrap.gate import numbers as nums


def claims(text, min_bare=10):
    return [t.display for t in nums.extract(text, min_bare) if t.reason is None and not t.bare]


def reasons(text):
    return {t.raw: t.reason for t in nums.extract(text)}


@pytest.mark.parametrize("text,expected", [
    ("I found 7 bugs.", ["7 bugs"]),
    ("Revenue grew 30% this year.", ["30%"]),
    ("It took 2.5 hours.", ["2.5 hours"]),
    ("About 1,200 users joined.", ["1,200 users"]),
    ("Reached 10k users.", ["10k users"]),
    ("A 4x faster build.", ["4x faster"]),
    ("It took 30min.", ["30min"]),
    ("Costs $5 a month.", ["5"]),
    ("Up 12 percent.", ["12%"]),
])
def test_claim_numbers(text, expected):
    assert claims(text) == expected


@pytest.mark.parametrize("text,raw,reason", [
    ("Visit https://example.com/page/2026", "2026", "url"),
    ("Released 2026-10-12 at noon", "2026", "date"),
    ("Due 12/10/2026", "12", "date"),
    ("Call at 9:30am", "9", "time"),
    ("Needs version 2.0.1 or later", "2.0", "version"),
    ("Dial " + "+" + "1 555 " + "010 0199", "555", "phone/id"),
    ("Order 12345678 shipped", "12345678", "phone/id"),
    ("Open 24/7 for you", "24", "idiom"),
    ("1. First point", "1", "list marker"),
    ("  2) Second point", "2", "list marker"),
    ("1\ufe0f\u20e3 Keycap line", "1", "list marker"),
    ("Ranked #1 in class", "1", "identifier"),
    ("The 3rd attempt", "3", "ordinal"),
    ("Use 2FA everywhere", "2", "identifier"),
    ("In 2019 we changed", "2019", "year"),
    ("Since March 2021 onwards", "2021", "year"),
    ("Chapter 3 of the book", "3", "label"),
    ("Step 4 is the one", "4", "label"),
    ("Top 5 tips", "5", "label"),
    ("My son, aged 8", "8", "age"),
    ("A child of 8 years old", "8", "age"),
    ("Five ideas, 5 tips for you", "5", "list count"),
    ("Posted on 12 October", "12", "date"),
])
def test_exemptions(text, raw, reason):
    got = [t for t in nums.extract(text) if t.raw == raw][0]
    assert got.reason == reason, (text, got)


def test_a_year_with_a_unit_is_a_claim():
    assert claims("It has 2000 users") == ["2000 users"]
    assert reasons("It has 2000 users")["2000"] is None


def test_bare_small_digits_warn_instead_of_fail():
    toks = nums.extract("I tried 3 of them.", min_bare=10)
    assert toks[0].bare and toks[0].reason is None
    res = nums.check_numbers({"caption": "I tried 3 of them."}, [])
    assert [f["severity"] for f in res] == ["warn"]
    res = nums.check_numbers({"caption": "I earned 40."}, [])  # >= min_bare_digit is a claim even without a unit
    assert [f["severity"] for f in res] == ["fail"]


def test_min_bare_digit_is_configurable():
    assert nums.check_numbers({"c": "I tried 3."}, [], min_bare=2)[0]["severity"] == "fail"


def spec(text):
    return parse_number_cell(text)


def test_matching_rules():
    t = nums.extract("The audit found 7 dashboards.")[0]
    assert nums.token_matches(t, spec("7 dashboards")[0])
    assert nums.token_matches(t, spec("7")[0])              # a fact with no unit accepts any unit
    assert not nums.token_matches(t, spec("7 bugs")[0])     # different unit
    assert not nums.token_matches(t, spec("8 dashboards")[0])
    pct = nums.extract("Down 30%.")[0]
    assert nums.token_matches(pct, spec("30%")[0])
    assert not nums.token_matches(pct, spec("30 minutes")[0])
    bare = nums.extract("Down 30 minutes.")[0]
    assert not nums.token_matches(bare, spec("30%")[0])
    end = nums.extract("It took 30.")[0]                    # no unit words in the text: value match is enough
    assert nums.token_matches(end, spec("30 minutes")[0])
    mult = nums.extract("Reached 10k users.")[0]
    assert nums.token_matches(mult, spec("10,000 users")[0])
    assert nums.token_matches(nums.extract("Costs $5 a month.")[0], NumSpec(5.0, "usd", "5"))
    assert nums.token_matches(nums.extract("Ages 8 to 16 years")[0], spec("8-16")[0])


def test_ranges_match_each_end():
    specs = spec("8-16")
    res = nums.check_numbers({"c": "Used by 8-16 teams"}, specs)
    assert not [f for f in res if f["severity"] == "fail"]


def test_number_words_warn_or_fail_or_off():
    text = "We fixed seven bugs and three tips."
    warn = nums.check_numbers({"c": text}, [], number_words="warn")
    assert [f["token"] for f in warn] == ["seven bugs"] and warn[0]["severity"] == "warn"
    assert nums.check_numbers({"c": text}, [], number_words="fail")[0]["severity"] == "fail"
    assert nums.check_numbers({"c": text}, [], number_words="off") == []
    assert nums.number_word_hits("two of them, ten in the") == []  # followed by a stop word


def test_duplicate_tokens_report_once_and_surfaces_are_separate():
    res = nums.check_numbers({"caption": "7 bugs and again 7 bugs", "alt": "7 bugs"}, [])
    assert sorted((f["surface"], f["token"]) for f in res) == [("alt", "7 bugs"), ("caption", "7 bugs")]
    assert nums.check_numbers({"caption": ""}, []) == []


def test_arabic_text_digits_and_units():
    assert claims("قللنا ١٢ عميلا") == ["12 عميلا"]
    assert claims("الخطوة ٣") == []  # label word before the number
    assert claims("٣ نصائح") == []  # structural unit
    assert nums.prepare("٣٫٥") == "3.5"
