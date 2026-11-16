"""Volatile facts: the `volatile` marker, `facts stale`, supersede chains, and the gate's age warning."""
from __future__ import annotations

import argparse
import datetime as dt
import json

from gate_helpers import make_draft, write_config

from profile_wrap.facts import registers as reg
from profile_wrap.facts.cli_ext import register as register_facts
from profile_wrap.gate import run_gate

HEAD = ("| id | claim | numbers | source | status | verified_by | verified_at | evidence | usage | supersedes | demo | "
        "added | volatile |\n|---|---|---|---|---|---|---|---|---|---|---|---|---|\n")


def _write_facts(ws, rows: list[str]) -> None:
    (ws / "research" / "facts.md").write_text("# Facts\n\n" + HEAD + "\n".join(rows) + "\n", encoding="utf-8")


def _row(i, claim, nums, status="verified", day="2026-10-01", sup="", vol="yes"):
    return (f"| {i} | {claim} | {nums} | notes/audit.md | {status} | maya | {day} | notes/audit.md |  | {sup} | no | "
            f"{day} | {vol} |")


def _cli(argv):
    root = argparse.ArgumentParser()
    register_facts(root.add_subparsers(dest="cmd", required=True))
    args = root.parse_args(argv)
    return args.func(args)


def test_stale_lists_volatile_facts_past_the_age(ws, capsys):
    _write_facts(ws, [_row("F01", "The tool is at version 0.3.1", "0.3.1", day="2026-09-01"),
                      _row("F02", "Fresh count", "5 clinics", day="2026-11-10"),
                      _row("F03", "Stable fact", "3 clinics", day="2026-01-01", vol="no")])
    r = reg.load_register(ws / "research" / "facts.md", "fact")
    stale = reg.stale_facts(r, 14, on_date=dt.date(2026, 11, 16))
    assert [(e.id, age) for e, age in stale] == [("F01", 76)]
    assert _cli(["facts", "stale", "--workspace", str(ws), "--today", "2026-11-16"]) == 0
    out = capsys.readouterr().out
    assert "STALE F01: 76 days old" in out and "F02" not in out and "F03" not in out
    assert "supersedes the old one" in out
    assert _cli(["facts", "stale", "--days", "100", "--workspace", str(ws), "--today", "2026-11-16"]) == 0
    assert "no volatile fact is older than 100 days" in capsys.readouterr().out


def test_stale_default_is_14_days_and_json_and_skips_superseded(ws, capsys):
    _write_facts(ws, [_row("F01", "Old version", "0.1.1", status="superseded", day="2026-09-01"),
                      _row("F02", "New version 0.3.1", "0.3.1", day="2026-11-01", sup="F01")])
    assert reg.DEFAULT_STALE_DAYS == 14
    assert _cli(["facts", "stale", "--json", "--workspace", str(ws), "--today", "2026-11-16"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert [s["id"] for s in data["stale"]] == ["F02"] and data["stale"][0]["age_days"] == 15 and data["days"] == 14


def test_add_volatile_flag_marks_the_row(ws, capsys):
    assert _cli(["facts", "add", "--claim", "Latest release is 0.3.1", "--numbers", "0.3.1", "--source",
                 "https://example.com/releases", "--volatile", "--workspace", str(ws)]) == 0
    capsys.readouterr()
    r = reg.load_register(ws / "research" / "facts.md", "fact")
    assert r.get("F07").volatile and not r.get("F01").volatile
    assert _cli(["facts", "lint", "--workspace", str(ws)]) == 0


def test_lint_warns_on_a_bad_volatile_value(ws):
    _write_facts(ws, [_row("F01", "c", "1 clinic", vol="maybe")])
    issues = reg.lint_register(reg.load_register(ws / "research" / "facts.md", "fact"))
    assert any(lvl == "WARN" and "volatile" in m for lvl, m in issues)


def test_gate_warns_on_a_cited_volatile_fact_past_the_limit(ws):
    _write_facts(ws, [_row("F01", "The tool is at version 0.3.1", "0.3.1", day="2026-09-01")])
    make_draft(ws, "d1", "Shipped v0.3.1 today.\n", claims=["F01"])
    res = run_gate("d1", ws, today=dt.date(2026, 11, 16))
    assert any(f["check"] == "claims" and "volatile fact F01" in f["message"] and f["severity"] == "warn"
               for f in res["findings"])
    assert res["summary"] == "PASS"  # a warning, never a failure
    write_config(ws, gate={"volatile_max_age_days": 0})
    res = run_gate("d1", ws, today=dt.date(2026, 11, 16))
    assert not any("volatile fact" in f["message"] for f in res["findings"])


def test_gate_does_not_warn_when_the_volatile_fact_is_fresh(ws):
    _write_facts(ws, [_row("F01", "The tool is at version 0.3.1", "0.3.1", day="2026-11-15")])
    make_draft(ws, "d1", "Shipped v0.3.1 today.\n", claims=["F01"])
    res = run_gate("d1", ws, today=dt.date(2026, 11, 16))
    assert not any("volatile fact" in f["message"] for f in res["findings"])
