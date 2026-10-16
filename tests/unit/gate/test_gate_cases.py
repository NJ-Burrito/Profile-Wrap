"""Good and bad caption fixtures, English and Arabic, run through the real gate entry point."""
from __future__ import annotations

import json
import shutil

import pytest
from gate_helpers import FIX, make_draft

from njli.gate import run_gate

CASES = json.loads((FIX / "cases.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", CASES, ids=[c["file"] for c in CASES])
def test_caption_fixture(ws, case):
    text = (FIX / case["file"]).read_text(encoding="utf-8")
    d = make_draft(ws, "d1", text, lang=case["lang"], claims=case["claims"])
    res = run_gate("d1", ws, which=lambda _t: None)
    failed = {c for c, v in res["checks"].items() if not v["ok"]}
    failed |= {f["check"] for f in res["findings"] if f["severity"] == "fail"}
    if case["expect"] == "PASS":
        assert res["summary"] == "PASS", res["fails"]
    else:
        assert res["summary"] == "FAIL"
        for name in case["expect"]:
            assert name in failed, (name, res["fails"])
    assert (d / "gates.json").is_file()
    assert json.loads((d / "gates.json").read_text(encoding="utf-8"))["summary"] == res["summary"]


def test_seven_bugs_fails_even_when_seven_is_elsewhere_in_the_register(ws):
    """The old gate passed any number found anywhere in facts.md; the claim-bound gate must not."""
    make_draft(ws, "d1", "I found 7 bugs last week.\n", claims=["F02"])  # F02 lists 7 dashboards, not bugs
    res = run_gate("d1", ws)
    assert res["summary"] == "FAIL"
    assert any(f["token"] == "7 bugs" for f in res["findings"] if f["check"] == "numbers")


def test_seven_dashboards_passes_with_the_cited_claim(ws):
    make_draft(ws, "d1", "The audit found 7 dashboards nobody opened.\n", claims=["F02"])
    assert run_gate("d1", ws)["summary"] == "PASS"


def test_arabic_indic_digits_normalise_to_the_same_number(ws):
    make_draft(ws, "d1", "The weekly review now takes ٣٠ minutes.\n", claims=["F01"])
    assert run_gate("d1", ws)["summary"] == "PASS"
    make_draft(ws, "d2", "The weekly review now takes ۳۰ minutes.\n", claims=["F01"])  # Persian digits
    assert run_gate("d2", ws)["summary"] == "PASS"
    make_draft(ws, "d3", "The weekly review now takes ٣١ minutes.\n", claims=["F01"])
    assert run_gate("d3", ws)["summary"] == "FAIL"


def test_percent_is_not_the_same_as_a_bare_number(ws):
    make_draft(ws, "d1", "The cost fell 30%.\n", claims=["F01"])  # F01 is 30 minutes, not 30 percent
    assert run_gate("d1", ws)["summary"] == "FAIL"


def test_stat_grade_a_current_and_verified_backs_a_number(ws):
    make_draft(ws, "ok", "Surveys put it at 60% of non-profits.\n", claims=["S01"])
    assert run_gate("ok", ws)["summary"] == "PASS"
    for slug, sid, why in (("old", "S02", "expired"), ("weak", "S03", "grade"), ("draft", "S04", "draft")):
        make_draft(ws, slug, "Plain sentence.\n", claims=[sid])
        res = run_gate(slug, ws)
        assert res["summary"] == "FAIL", sid
        assert any("claims" == f["check"] for f in res["findings"]), why


def test_demo_fact_cannot_back_a_live_workspace_but_can_in_a_demo_one(ws):
    from gate_helpers import write_config
    make_draft(ws, "d1", "A tiny dashboard saved 9 hours.\n", claims=["F05"])
    assert run_gate("d1", ws)["summary"] == "FAIL"
    write_config(ws, persona={"demo": True})
    assert run_gate("d1", ws)["summary"] == "PASS"


def test_fictional_draft_cannot_pass_in_a_live_workspace(ws):
    make_draft(ws, "d1", "A plain sentence.\n", meta={"fictional": True})
    res = run_gate("d1", ws)
    assert res["summary"] == "FAIL" and any("demo" in f for f in res["fails"])


def test_hook_limits_and_style_preset(ws):
    long_hook = "x" * 211
    make_draft(ws, "d1", long_hook + "\n")
    assert run_gate("d1", ws)["summary"] == "FAIL"
    make_draft(ws, "d2", "A hook line that is longer than forty characters but under the fold.\n")
    r = run_gate("d2", ws)
    assert r["summary"] == "PASS" and any("hook" in w for w in r["warnings"])
    make_draft(ws, "d3", "Plain start without emoji.\n", meta={"style": "adhd_emoji"})
    assert any("emoji" in w for w in run_gate("d3", ws)["warnings"])
    make_draft(ws, "d4", "\U0001f4ca Emoji-led hook.\n", meta={"style": "adhd_emoji"})
    assert not any("emoji" in w for w in run_gate("d4", ws)["warnings"])


def test_caption_over_the_length_limit_fails(ws):
    make_draft(ws, "d1", "Short hook.\n" + ("word " * 700))
    res = run_gate("d1", ws)
    assert any(f["token"] == "length" for f in res["findings"])


def test_meta_validation(ws):
    make_draft(ws, "d1", "ok.\n", lang="fr")
    assert any("persona.languages" in f for f in run_gate("d1", ws)["fails"])
    make_draft(ws, "d2", "ok.\n", fmt="hologram")
    assert any("meta.format" in f for f in run_gate("d2", ws)["fails"])
    d = make_draft(ws, "d3", "ok.\n")
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    del meta["pillar"], meta["claims"]
    (d / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    assert any("lacks required field" in f for f in run_gate("d3", ws)["fails"])
    make_draft(ws, "d4", "ok.\n", meta={"slug": "other"})
    assert any("differs from the folder" in f for f in run_gate("d4", ws)["fails"])
    make_draft(ws, "d5", "ok.\n", meta={"pillar": "P9"})
    assert any("pillar" in w for w in run_gate("d5", ws)["warnings"])
    make_draft(ws, "d6", "ok.\n", meta={"claims": "F01"})
    assert any("must be a list" in f for f in run_gate("d6", ws)["fails"])


def test_require_claims_false_allows_a_missing_claims_key(ws):
    from gate_helpers import write_config
    write_config(ws, gate={"numbers": {"require_claims": False}})
    d = make_draft(ws, "d1", "ok.\n")
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    del meta["claims"]
    (d / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    assert run_gate("d1", ws)["summary"] == "PASS"


def test_council_pass_is_required_when_configured(ws):
    from gate_helpers import write_config
    write_config(ws, gate={"require_council_pass": True})
    d = make_draft(ws, "d1", "ok.\n")
    assert any("review.json" in f for f in run_gate("d1", ws)["fails"])
    (d / "review.json").write_text(json.dumps({"verdict": "blockers"}), encoding="utf-8")
    assert any("blockers" in f for f in run_gate("d1", ws)["fails"])
    (d / "review.json").write_text(json.dumps({"verdict": "pass"}), encoding="utf-8")
    assert run_gate("d1", ws)["summary"] == "PASS"


def test_banned_files_from_workspace_copy_and_extra_banned(ws):
    from gate_helpers import write_config
    write_config(ws, gate={"extra_banned": ["frobnicate*"]})
    make_draft(ws, "d1", "We frobnicated the report.\n")
    assert run_gate("d1", ws)["summary"] == "FAIL"
    write_config(ws, gate={"banned_files": ["data/banned-words/missing.json"], "extra_banned": []})
    res = run_gate("d1", ws)
    assert any("banned-words file not found" in f for f in res["fails"])


def test_input_hash_changes_with_the_caption(ws):
    d = make_draft(ws, "d1", "First version.\n")
    h1 = run_gate("d1", ws)["input_sha256"]
    (d / "caption.txt").write_text("Second version.\n", encoding="utf-8")
    h2 = run_gate("d1", ws)["input_sha256"]
    assert h1 and h2 and h1 != h2


def test_workspace_copy_of_banned_words_is_found(ws, tmp_path):
    (ws / "data" / "banned-words").mkdir(parents=True)
    (ws / "data" / "banned-words" / "en.json").write_text(json.dumps({"words": ["zorp"]}), encoding="utf-8")
    shutil.copy(FIX.parents[2] / "data" / "banned-words" / "tlds.json", ws / "data" / "banned-words" / "tlds.json")
    make_draft(ws, "d1", "A zorp appears.\n")
    assert run_gate("d1", ws)["summary"] == "FAIL"
