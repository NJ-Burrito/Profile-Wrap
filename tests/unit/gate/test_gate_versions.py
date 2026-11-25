"""The `versions` check: a version-like string in a caption must match a cited verified fact."""
from __future__ import annotations

from gate_helpers import make_draft, write_config

from profile_wrap.gate import run_gate
from profile_wrap.gate.versions import version_tokens

HEAD = ("| id | claim | numbers | source | status | verified_by | verified_at | evidence | usage | supersedes | demo | "
        "added | volatile |\n|---|---|---|---|---|---|---|---|---|---|---|---|---|\n")


def _facts(ws, *rows):
    (ws / "research" / "facts.md").write_text("# Facts\n\n" + HEAD + "\n".join(rows) + "\n", encoding="utf-8")


F_NEW = ("| F01 | The tool is at version 0.3.1 | 0.3.1 | notes/audit.md | verified | maya | 2026-11-16 | "
         "notes/audit.md |  |  | no | 2026-11-16 | yes |")


def _warns(res):
    return [f for f in res["findings"] if f["check"] == "versions"]


def test_old_version_with_a_cited_newer_fact_warns(ws):
    _facts(ws, F_NEW)
    make_draft(ws, "d1", "Shipped v0.1.1 today.\n", claims=["F01"])
    res = run_gate("d1", ws)
    w = _warns(res)
    assert len(w) == 1 and w[0]["severity"] == "warn" and w[0]["token"] == "v0.1.1"
    assert "re-read the source today" in w[0]["message"]
    assert res["summary"] == "PASS" and res["checks"]["versions"]["ok"]


def test_matching_version_passes_silently(ws):
    _facts(ws, F_NEW)
    make_draft(ws, "d1", "Shipped v0.3.1 today, release 0.3.1 notes are out.\n", claims=["F01"])
    assert _warns(run_gate("d1", ws)) == []


def test_version_with_no_cited_fact_warns(ws):
    make_draft(ws, "d1", "Now at version 2.4 for everyone.\n", claims=[])
    w = _warns(run_gate("d1", ws))
    assert len(w) == 1 and "no cited fact" in w[0]["message"]


def test_mode_fail_and_off(ws):
    _facts(ws, F_NEW)
    make_draft(ws, "d1", "Shipped v0.1.1 today.\n", claims=["F01"])
    write_config(ws, gate={"versions": "fail"})
    res = run_gate("d1", ws)
    assert res["summary"] == "FAIL" and not res["checks"]["versions"]["ok"]
    write_config(ws, gate={"versions": "off"})
    assert _warns(run_gate("d1", ws)) == []


def test_platform_versions_urls_and_labels_are_not_claims():
    assert version_tokens("Needs Python 3.11 and Node 20.1.2, see https://example.com/v1.2.3.") == []
    assert version_tokens("Part v2 of the plan, step 3.") == []
    assert version_tokens("It runs on Python version 3.11.") == []
    assert [c for _, c in version_tokens("v1.2, version 3 and release 1.2.0 and 4.5.6")] == ["1.2", "3", "1.2.0", "4.5.6"]
