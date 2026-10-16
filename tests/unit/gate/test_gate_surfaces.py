"""Every text surface is scanned; overrides are capped, need a reason and are logged to gates.json."""
from __future__ import annotations

import json

import pytest
from gate_helpers import make_draft, write_config

from njli.gate import run_gate

SLIDES = """<!doctype html><html><head><title>t</title><style>.x{width:1080px}</style>
<script>var n = 4242;</script></head>
<body><section><h1>Weekly review</h1><p>We found 7 bugs.</p><img src="a.png" alt="Chart of 18 clinics"></section></body></html>"""


def fails_for(res, surface, check):
    return [f for f in res["findings"] if f["surface"] == surface and f["check"] == check and f["severity"] == "fail"]


def test_numbers_are_scanned_in_slides_alt_and_first_comment(ws):
    make_draft(ws, "d1", "Plain sentence.\n", fmt="slides", slides=SLIDES, alt="A chart of 9 hours saved.\n",
               first_comment="Details: 21 clinics took part.\n", meta={"assets": []})
    res = run_gate("d1", ws, which=lambda _t: None)
    assert fails_for(res, "slides", "numbers"), res["fails"]
    assert {f["token"] for f in fails_for(res, "slides", "numbers")} >= {"7 bugs", "18 clinics"}
    assert fails_for(res, "alt", "numbers")
    assert fails_for(res, "first_comment", "numbers")
    assert set(res["surfaces"]) >= {"caption", "slides", "alt", "first_comment"}
    assert not any(f["token"] == "4242" for f in res["findings"])  # script content is not visible text


def test_numbers_in_video_project_text_are_scanned(ws):
    vp = ws / "videos" / "d1"
    vp.mkdir(parents=True)
    (vp / "index.html").write_text("<html><body><h1>Saved 12 hours</h1><script>x=99</script></body></html>",
                                   encoding="utf-8")
    (vp / "narration.txt").write_text("And 5 clinics agreed.", encoding="utf-8")
    (vp / "node_modules").mkdir()
    (vp / "node_modules" / "x.html").write_text("<p>77 things</p>", encoding="utf-8")
    make_draft(ws, "d1", "Plain sentence.\n", fmt="gif", alt="alt text\n", meta={"video_project": "videos/d1",
                                                                            "assets": []})
    res = run_gate("d1", ws, which=lambda _t: None)
    toks = {f["token"] for f in fails_for(res, "video", "numbers")}
    assert "12 hours" in toks and "5 clinics" in toks and "77 things" not in toks


def test_a_missing_video_project_is_a_readable_fail(ws):
    make_draft(ws, "d1", "Plain sentence.\n", fmt="gif", alt="alt\n", meta={"video_project": "videos/nope", "assets": []})
    assert any("video_project not found" in f for f in run_gate("d1", ws, which=lambda _t: None)["fails"])


def test_private_terms_fail_on_every_text_surface(ws):
    make_draft(ws, "d1", "Plain sentence.\n", fmt="slides", alt="Photo at Lantern Data office\n",
               first_comment="Thanks to the Acme Clinic team\n",
               slides="<html><body><p>Built for lantern  data</p></body></html>", meta={"assets": []})
    vp = ws / "videos" / "d1"
    vp.mkdir(parents=True)
    (vp / "index.html").write_text("<html><body><p>ACME CLINIC</p></body></html>", encoding="utf-8")
    d = ws / "drafts" / "d1"
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    meta["video_project"] = "videos/d1"
    (d / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    res = run_gate("d1", ws, which=lambda _t: None)
    for surface in ("alt", "first_comment", "slides", "video"):
        assert fails_for(res, surface, "private_terms"), surface
    # a zero-width character cannot hide a private term
    make_draft(ws, "d2", "Built at Lan\u200btern Data.\n")
    assert fails_for(run_gate("d2", ws), "caption", "private_terms")


def test_alt_text_required_for_visual_formats(ws):
    make_draft(ws, "d1", "ok.\n", fmt="slides", meta={"assets": []})
    assert any(f["check"] == "alt" for f in run_gate("d1", ws, which=lambda _t: None)["findings"])
    write_config(ws, gate={"require_alt_text": False})
    assert not any(f["check"] == "alt" for f in run_gate("d1", ws, which=lambda _t: None)["findings"])


def test_first_comment_may_hold_a_link_but_not_slop(ws):
    make_draft(ws, "d1", "Plain.\n", first_comment="Checklist: https://example.com/c\n")
    assert run_gate("d1", ws)["summary"] == "PASS"
    make_draft(ws, "d2", "Plain.\n", first_comment="Let me delve into it.\n")
    assert run_gate("d2", ws)["summary"] == "FAIL"
    write_config(ws, gate={"first_comment_gated": False})
    assert run_gate("d2", ws)["summary"] == "PASS"


def test_override_waives_a_number_and_is_logged(ws):
    d = make_draft(ws, "d1", "I found 7 bugs last week.\n", meta={"overrides": [
        {"check": "numbers", "token": "7 bugs", "reason": "counted on the sprint board, screenshot kept"}]})
    res = run_gate("d1", ws)
    assert res["summary"] == "PASS"
    assert res["overrides"][0]["applied"] and res["overrides"][0]["matched"] == 1
    saved = json.loads((d / "gates.json").read_text(encoding="utf-8"))
    assert saved["overrides"][0]["reason"].startswith("counted")
    assert any(f["severity"] == "overridden" and f["override_reason"] for f in saved["findings"])


@pytest.mark.parametrize("override,needle", [
    ({"check": "numbers", "token": "7 bugs", "reason": "x"}, "needs a reason"),
    ({"check": "numbers", "token": "", "reason": "long enough reason"}, "needs both check and token"),
    ("not an object", "must be an object"),
])
def test_bad_overrides_fail(ws, override, needle):
    make_draft(ws, "d1", "I found 7 bugs last week.\n", meta={"overrides": [override]})
    res = run_gate("d1", ws)
    assert res["summary"] == "FAIL" and any(needle in f for f in res["fails"])


def test_override_cap_and_switch(ws):
    ov = [{"check": "numbers", "token": t, "reason": "a sufficiently long reason"}
          for t in ("1 bugs", "2 bugs", "3 bugs")]
    make_draft(ws, "d1", "We saw 11 bugs, 12 bugs and 13 bugs.\n",
               meta={"overrides": [{"check": "numbers", "token": f"{n} bugs", "reason": "a sufficiently long reason"}
                                   for n in (11, 12, 13)]})
    res = run_gate("d1", ws)
    assert res["summary"] == "FAIL" and any("at most 2 per post" in f for f in res["fails"])
    write_config(ws, gate={"overrides": {"allow": False}})
    make_draft(ws, "d2", "We saw 11 bugs.\n", meta={"overrides": ov[:1]})
    assert any("switched off" in f for f in run_gate("d2", ws)["fails"])


def test_override_that_matches_nothing_is_reported(ws):
    make_draft(ws, "d1", "Plain.\n", meta={"overrides": [
        {"check": "numbers", "token": "9 bugs", "reason": "a sufficiently long reason"}]})
    res = run_gate("d1", ws)
    assert res["summary"] == "PASS" and any("matched no finding" in w for w in res["warnings"])
    make_draft(ws, "d2", "Plain.\n", meta={"overrides": "nope"})
    assert any("must be a list" in f for f in run_gate("d2", ws)["fails"])
