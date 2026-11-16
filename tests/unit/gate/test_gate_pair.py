"""pair parity: both halves exist, cite the same claims, and are gated together."""
from __future__ import annotations

from gate_helpers import make_draft, write_config

from profile_wrap.gate import run_gate


def _pair(res):
    return [f for f in res["findings"] if f["check"] == "pair"]


def _both(ws, claims_en=("F01",), claims_ar=("F06",)):
    make_draft(ws, "en", "Weekly review takes 30 minutes.\n", claims=list(claims_en), meta={"pair": "ar"})
    make_draft(ws, "ar", "المراجعة الأسبوعية تأخذ 30 دقيقة.\n", lang="ar", claims=list(claims_ar), meta={"pair": "en"})


def test_no_pair_means_no_pair_check(ws):
    make_draft(ws, "en", "A plain sentence.\n")
    assert _pair(run_gate("en", ws)) == []


def test_missing_partner_warns(ws):
    make_draft(ws, "en", "A plain sentence.\n", meta={"pair": "ar"})
    f = _pair(run_gate("en", ws))
    assert len(f) == 1 and f[0]["severity"] == "warn" and "no draft folder" in f[0]["message"]


def test_different_claims_warn_and_strict_fails(ws):
    _both(ws, claims_en=("F01",), claims_ar=("F01", "F02"))
    run_gate("ar", ws)
    res = run_gate("en", ws)
    assert any("different claims" in f["message"] and "F02" in f["message"] for f in _pair(res))
    assert res["summary"] == "PASS"
    write_config(ws, gate={"pair": "fail"})
    assert run_gate("en", ws)["summary"] == "FAIL"


def test_same_claims_gated_together_is_clean(ws):
    _both(ws, claims_en=("F01",), claims_ar=("F01",))
    run_gate("ar", ws)
    assert _pair(run_gate("en", ws)) == []


def test_partner_edited_after_its_gate_warns(ws):
    _both(ws, claims_en=("F01",), claims_ar=("F01",))
    run_gate("ar", ws)
    run_gate("en", ws)
    (ws / "drafts" / "ar" / "caption.txt").write_text("نص معدل بعد الفحص.\n", encoding="utf-8")
    f = _pair(run_gate("en", ws))
    assert len(f) == 1 and "changed since its last gate" in f[0]["message"]
    run_gate("ar", ws)  # re-gating the partner clears it
    assert _pair(run_gate("en", ws)) == []


def test_partner_never_gated_and_not_reciprocal(ws):
    make_draft(ws, "en", "A plain sentence.\n", meta={"pair": "ar"})
    make_draft(ws, "ar", "جملة بسيطة.\n", lang="ar")
    msgs = " | ".join(f["message"] for f in _pair(run_gate("en", ws)))
    assert "has not been gated" in msgs and "does not name" in msgs


def test_mode_off(ws):
    make_draft(ws, "en", "A plain sentence.\n", meta={"pair": "ar"})
    write_config(ws, gate={"pair": "off"})
    assert _pair(run_gate("en", ws)) == []
