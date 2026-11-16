"""Integration of the 0.4.0 branches: the build prompt carries the earlier angles on the entry's subject."""
from __future__ import annotations

from profile_wrap import claude_runner as cr
from profile_wrap import config
from profile_wrap.plan import build_week as bw
from profile_wrap.plan import calendar as calmod

ROOT_PROMPTS = __import__("pathlib").Path(__file__).resolve().parents[1] / "prompts"


def _entry(slug, date, **kw):
    return dict(date=date, slug=slug, lang="en", format="text", **kw)


def test_prompt_values_lists_the_earlier_angles_of_the_subject(tmp_path):
    cal = calmod.empty()
    calmod.add_entry(cal, title="First", status="posted", subject="Widget", angle="why I built it",
                     **_entry("a", "2026-12-02"))
    calmod.add_entry(cal, title="Second", subject="widget", angle="how it works", **_entry("b", "2026-12-09"))
    calmod.save(tmp_path, cal)
    cfg = config.defaults("UTC")
    vals = bw.prompt_values(tmp_path, cfg, {"slug": "b", "date": "2026-12-09", "subject": "widget", "format": "text",
                                            "lang": "en"}, "2026-12-09T10:00:00+00:00")
    assert "- First | why I built it" in vals["prior_angles"] and "how it works" not in vals["prior_angles"]
    body = cr.prompt_body((ROOT_PROMPTS / "build.md").read_text(encoding="utf-8"))
    out = cr.render_prompt(body, vals)
    assert "Angles already used on this subject" in out and "- First | why I built it" in out and "{{" not in out


def test_an_entry_without_a_subject_gets_a_plain_line(tmp_path):
    vals = bw.prompt_values(tmp_path, config.defaults("UTC"), {"slug": "b", "format": "text"}, "x")
    assert "no subject" in vals["prior_angles"]
