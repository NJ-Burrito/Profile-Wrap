"""Text rules (links, hashtags, dashes, slop lists) and the short-text gate for comments and notes."""
from __future__ import annotations

import json

import pytest
from gate_helpers import make_draft, write_config

from profile_wrap.gate import check_text, rules
from profile_wrap.gate.arabic import check_arabic, is_arabic_lang
from profile_wrap.gate.config import deep_merge, find_data_file, load_config, read_json, resolve_workspace
from profile_wrap.gate.textnorm import fold, html_text, is_arabic, normalise_digits, strip_invisible


def banned():
    return rules.load_banned(["data/banned-words/en.json", "data/banned-words/ar.json"], None)


def ctx(**kw):
    return rules.TextContext(banned(), kw.pop("private", []), kw.pop("never", []), **kw)


def checks(text, **kw):
    return {(f["check"], f["severity"]) for f in rules.scan_text("caption", text, ctx(**kw), is_caption=True)}


@pytest.mark.parametrize("text", [
    "see example.com", "see https://example.com/x", "see www.example.org", "go to example.io/start", "my.site.dev rocks",
    "visit Example.COM today", "docs at example.ai.", "shop.example.co.uk is up",
])
def test_links_detected(text):
    assert rules.find_links(text, banned().tlds), text


@pytest.mark.parametrize("text", [
    "open main.py and README.md", "Node.js and Vue.js", "e.g. this", "Okay.It works", "version 2.5 is out",
    "mail me at maya@example.invalid", "i.e. now", "a.m. and p.m.", "price 3.50 today",
])
def test_not_links(text):
    assert rules.find_links(text, banned().tlds) == [], text


def test_file_names_with_a_path_or_scheme_are_still_links():
    assert rules.find_links("see main.py/raw", banned().tlds)
    assert rules.find_links("see https://example.com/main.py", banned().tlds)


def test_hashtags_count_arabic_and_skip_numbers():
    ok = checks("#one #two #three")
    assert ("hashtags", "fail") not in ok
    assert ("hashtags", "fail") in checks("#a #b #c #d")
    assert ("hashtags", "fail") in checks("#بيانات #تحليل #أرقام #عمل")
    assert ("hashtags", "fail") not in checks("Ranked #1 and #2 and #3 and #4 and #5")
    assert ("hashtags", "fail") not in checks("#a #b #c #d", hashtags_max=5)


def test_dash_policy_is_configurable():
    assert ("em_dash", "fail") in checks("a \u2014 b")
    assert ("em_dash", "warn") in checks("a \u2014 b", em_dash="warn")
    assert not [c for c in checks("a \u2014 b", em_dash="off") if c[0] == "em_dash"]
    assert ("em_dash", "fail") in checks("a -- b")
    assert ("en_dash", "warn") in checks("8\u201316")
    assert ("en_dash", "fail") in checks("8\u201316", en_dash="fail")
    assert not [c for c in checks("8\u201316", en_dash="off") if c[0] == "en_dash"]


def test_slop_patterns_and_job_seeking_goal():
    assert ("slop", "fail") in checks("Honestly this is a game-changer for teams.")
    assert ("slop", "fail") in checks("It isn't about tools, it's about habits.")
    assert ("slop", "warn") in checks("This is not just a tool but a habit.")
    assert ("job_seeking", "fail") in checks("I am open to work.")
    assert ("job_seeking", "fail") not in checks("I am open to work.", goal="job_seeking")
    assert ("job_seeking", "fail") in checks("أبحث عن وظيفة جديدة")


def test_private_terms_match_across_case_spacing_and_invisible_characters():
    c = ctx(private=["Acme  Clinic", ""], never=["  "])
    for text in ("at ACME CLINIC today", "at acme\u00a0clinic today", "at Ac\u200bme Clinic"):
        found = rules.scan_text("alt", text, c)
        assert any(f["check"] == "private_terms" for f in found), text
    assert not rules.scan_text("alt", "at the clinic", c)
    assert not rules.scan_text("alt", "", c)


def test_phone_like_text_warns_and_bidi_in_non_arabic_warns():
    found = rules.scan_text("caption", "Call " + "+" + "1 555 " + "010 0199" + " now", ctx(), is_caption=True)
    assert any(f["check"] == "contact" and f["severity"] == "warn" for f in found)
    found = rules.scan_text("caption", "Hello\u200f world", ctx(), is_caption=True)
    assert any(f["check"] == "invisible" and f["severity"] == "warn" for f in found)


def test_term_pattern_stems_and_arabic_clitics():
    p = rules._term_pattern("delv*")
    assert p.search("they delved deep") and not p.search("shelve")
    ar = rules._term_pattern("التحول الرقمي")
    assert ar.search(fold("والتحول الرقمي"))
    assert fold("أحمد") == fold("احمد")  # alef variants
    assert fold("م\u064eر\u0652ح\u064eبا") == "مرحبا"


def test_load_banned_problems(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{nope", encoding="utf-8")
    pat = tmp_path / "pat.json"
    pat.write_text(json.dumps({"patterns": [{"id": "x", "regex": "("}, {"nope": 1}]}), encoding="utf-8")
    b = rules.load_banned([str(bad), str(pat), "data/banned-words/none.json"], None, extra=["", "zap"])
    msgs = " | ".join(b.problems)
    assert "unreadable" in msgs and "pattern invalid" in msgs and "not found" in msgs
    assert any(t == "zap" for t, _ in b.words)


def test_textnorm_helpers():
    assert normalise_digits("٣٠ ۴۵") == "30 45"
    assert strip_invisible("a\u200b\u200eb\u200dc") == "abc"
    assert is_arabic("م") and not is_arabic("abc")
    html = "<html><head><title>x</title></head><body><p>Hi</p><img alt='A chart'><br/><script>1</script></body></html>"
    assert "A chart" in html_text(html) and "Hi" in html_text(html) and "1" not in html_text(html)
    assert html_text("<p>unclosed <b>tag").split() == ["unclosed", "tag"]


def test_arabic_language_detection_and_hygiene_helpers():
    assert is_arabic_lang("ar") and is_arabic_lang("ar-JO") and is_arabic_lang("ar+en") and not is_arabic_lang("en")
    assert not check_arabic("caption", "English only, with a comma.")
    mixed = check_arabic("caption", "١٢ and 12 مرحبا")
    assert any("mixed numeral" in f["message"] for f in mixed)
    assert any("semicolon" in f["message"] for f in check_arabic("caption", "مرحبا;"))


def test_config_helpers(tmp_path, monkeypatch):
    assert deep_merge({"a": {"b": 1, "c": 2}}, {"a": {"b": 9}, "d": 1}) == {"a": {"b": 9, "c": 2}, "d": 1}
    monkeypatch.setenv("PROFILE_WRAP_WORKSPACE", str(tmp_path))
    assert resolve_workspace() == tmp_path.resolve()
    assert resolve_workspace(tmp_path / "x") == (tmp_path / "x").resolve()
    p = tmp_path / "j.json"
    p.write_bytes(b"\xef\xbb\xbf{\"a\": 1}")
    assert read_json(p) == ({"a": 1}, "BOM")
    assert read_json(tmp_path / "none.json")[0] is None
    p.write_text("[", encoding="utf-8")
    assert "not valid" in read_json(p)[1]
    monkeypatch.setenv("PROFILE_WRAP_DATA_ROOT", str(tmp_path))
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "x.json").write_text("{}", encoding="utf-8")
    assert find_data_file("data/x.json") == tmp_path / "data" / "x.json"
    assert find_data_file("data/none.json") is None
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "profile-wrap.json").write_text("[1]", encoding="utf-8")
    cfg, problems = load_config(tmp_path)
    assert problems and cfg["gate"]["hashtags_max"] == 3


# ---- short texts: comments, replies, connection notes
def test_comment_passes_and_fails():
    ok = check_text("Good point. I stopped guessing and started measuring.", "comment")
    assert ok["ok"] and ok["kind"] == "comment"
    bad = check_text("Great post, see https://example.com #a #b", "comment")
    assert not bad["ok"] and any("link" in f for f in bad["fails"])


def test_note_length_is_capped_at_200_and_hashtags_are_not_allowed(ws):
    assert check_text("x" * 200, "note", ws)["ok"]
    too_long = check_text("x" * 201, "note", ws)
    assert not too_long["ok"] and any("max 200" in f for f in too_long["fails"])
    write_config(ws, engagement={"connect": {"note_max": 500}})
    assert not check_text("x" * 201, "note", ws)["ok"]  # config cannot lift the ceiling
    assert not check_text("Hi #data", "note", ws)["ok"]


def test_comment_private_terms_numbers_and_arabic(ws):
    assert not check_text("We did this at Lantern Data.", "reply", ws)["ok"]
    res = check_text("The audit found 7 dashboards.", "comment", ws)
    assert not res["ok"]
    assert check_text("The audit found 7 dashboards.", "comment", ws, claims=["F02"])["ok"]
    res = check_text("The audit found 7 dashboards.", "comment", ws, claims=["F99"])
    assert not res["ok"] and any("F99" in f for f in res["fails"])
    assert not check_text("التقرير, ثم القرار", "comment", ws)["ok"]
    assert not check_text("   ", "comment", ws)["ok"]
    assert not check_text("hello", "dm", ws)["ok"]


def test_draft_with_comment_max_chars_from_config(ws):
    write_config(ws, engagement={"comments": {"max_chars": 20}})
    assert not check_text("This comment is longer than twenty characters.", "comment", ws)["ok"]
    make_draft(ws, "d1", "ok.\n")
