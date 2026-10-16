"""Facts and stats registers: parser, lint, add, verify refusals, expiry, export."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys

import pytest
from gate_helpers import FIX, ROOT

from profile_wrap.facts import registers as reg
from profile_wrap.facts.cli_ext import register as register_facts
from profile_wrap.facts.numspec import norm_unit, parse_entry, parse_number_cell, unitless_entries
from profile_wrap.facts.table import join_row, parse_table, split_row


def test_table_roundtrip_keeps_text_around_the_table():
    text = "# Title\n\nIntro line.\n\n| id | claim |\n|---|---|\n| F01 | a \\| b |\n\nTrailing note.\n"
    t = parse_table(text)
    assert t.has_table and t.columns == ["id", "claim"] and t.rows[0]["claim"] == "a | b"
    assert t.render() == text
    assert split_row(join_row(["x|y", "z"])) == ["x|y", "z"]
    assert not parse_table("no table here\n").has_table
    assert parse_table("\ufeff| id |\n|---|\n| F01 |\n").bom


def test_header_aliases():
    t = parse_table("| ID | Claim | Number(s) |\n|---|---|---|\n| F01 | c | 3 |\n")
    assert t.columns == ["id", "claim", "numbers"]


@pytest.mark.parametrize("cell,expect", [
    ("30%", [(30.0, "%")]),
    ("180+ hours", [(180.0, "hour")]),
    ("8-16, since 02/2026", [(8.0, ""), (16.0, "")]),
    ("07/2025 \u2013 12/2025", []),
    ("1,200 users; 3 defects", [(1200.0, "user"), (3.0, "defect")]),
    ("$5 per month", [(5.0, "usd")]),
    ("٣٠ دقيقة", [(30.0, "دقيقة")]),
    ("12 percent", [(12.0, "%")]),
    ("n/a", []),
    ("", []),
])
def test_number_cells(cell, expect):
    assert [(s.value, s.unit) for s in parse_number_cell(cell)] == expect


def test_unit_helpers():
    assert norm_unit("Hours") == "hour" and norm_unit("studies") == "study" and norm_unit("class") == "class"
    assert norm_unit("per cent") == "%" and norm_unit("boxes") == "box"
    assert unitless_entries("7; 3 bugs") == ["7"]
    assert parse_entry("no digits here") == []


def load_fixture(ws):
    return reg.load_register(ws / "research" / "facts.md", "fact")


def test_fixture_register_lints_clean_enough(ws):
    r = load_fixture(ws)
    assert [e.id for e in r.entries] == ["F01", "F02", "F03", "F04", "F05", "F06"]
    issues = reg.lint_register(r)
    assert not [m for lvl, m in issues if lvl == "FAIL"], issues
    assert r.get("F05").demo and not r.get("F01").demo


def test_lint_catches_duplicates_missing_sources_and_chains(tmp_path):
    p = tmp_path / "facts.md"
    p.write_text("""| id | claim | numbers | source | status | supersedes | demo |
|---|---|---|---|---|---|---|
| F01 | one | 3 | s | verified | F02 | no |
| F02 | two | 4 clinics | s | verified | F01 | maybe |
| F02 | dup | 5 | | weird | F99 |  |
| X1 | bad id | | s | draft | F04 |  |
| F04 | self | | s | draft | F04 |  |
| F05 |  | 7 | s | draft |  |  |
""", encoding="utf-8")
    issues = reg.lint_register(reg.load_register(p, "fact"))
    text = "\n".join(f"{lvl} {m}" for lvl, m in issues)
    for needle in ("duplicate id", "source is required", "status 'weird'", "supersedes unknown id F99",
                   "supersedes itself", "loops back", "must look like", "empty claim", "no unit",
                   "still verified", "demo column", "verified without verified_by"):
        assert needle in text, (needle, text)


def test_lint_reports_missing_file_columns_and_bom(tmp_path):
    r = reg.load_register(tmp_path / "nope.md", "fact")
    assert not r.exists and "facts file not found" in reg.lint_register(r)[0][1]
    p = tmp_path / "f.md"
    p.write_bytes(b"\xef\xbb\xbf| id | claim |\n|---|---|\n| F01 | c |\n")
    issues = reg.lint_register(reg.load_register(p, "fact"))
    assert ("WARN", "facts file starts with a UTF-8 BOM: f.md (re-save as UTF-8 without BOM)") in issues
    assert any("missing column 'numbers'" in m for lvl, m in issues)
    p.write_text("prose only\n", encoding="utf-8")
    assert any("no pipe table" in m for lvl, m in reg.lint_register(reg.load_register(p, "fact")))
    p.write_bytes(b"\xff\xfe\xfa")
    assert any("unreadable" in m for lvl, m in reg.lint_register(reg.load_register(p, "fact")))


def test_stats_lint(ws, tmp_path):
    r = reg.load_register(ws / "research" / "stats.md", "stat")
    assert not [m for lvl, m in reg.lint_register(r) if lvl == "FAIL"]
    p = tmp_path / "stats.md"
    p.write_text("""| id | stat | numbers | source | retrieved | sample | grade | expires | kind | status |
|---|---|---|---|---|---|---|---|---|---|
| S01 | a | 5% | not a url | yesterday | n=1 | Z | soon | first_party | draft |
""", encoding="utf-8")
    text = " ".join(m for _, m in reg.lint_register(reg.load_register(p, "stat")))
    for needle in ("grade 'Z'", "kind should be third_party", "should be a URL", "expires must be",
                   "retrieved must be"):
        assert needle in text


def test_add_creates_files_and_ids(tmp_path):
    p = tmp_path / "research" / "facts.md"
    e1 = reg.add_entry(p, "fact", text="First claim", numbers="3 clinics", source="notes/a.md")
    e2 = reg.add_entry(p, "fact", text="Second | claim", numbers="4 hours", source="notes/b.md")
    assert (e1.id, e2.id) == ("F01", "F02") and e1.status == "draft"
    r = reg.load_register(p, "fact")
    assert r.get("F02").text == "Second | claim"
    assert not [m for lvl, m in reg.lint_register(r) if lvl == "FAIL"]
    with pytest.raises(ValueError):
        reg.add_entry(p, "fact", text="x", numbers="", source="s", ident="F01")
    with pytest.raises(ValueError):
        reg.add_entry(p, "fact", text="x", numbers="", source="s", ident="BAD")
    with pytest.raises(ValueError):
        reg.add_entry(p, "fact", text="", numbers="", source="s")
    # an existing file with only prose gets a fresh table
    q = tmp_path / "prose.md"
    q.write_text("just words\n", encoding="utf-8")
    assert reg.add_entry(q, "fact", text="c", numbers="", source="s").id == "F01"
    s = reg.add_entry(tmp_path / "stats.md", "stat", text="A stat", numbers="9%", source="https://example.com",
                      extra={"grade": "A", "retrieved": "2026-01-01", "expires": "2026-04-01"})
    assert s.id == "S01"


class Tty:
    def __init__(self, ok): self.ok = ok
    def __call__(self): return self.ok


def verify(ws, ident="F03", evidence="notes/clinics.md", **kw):
    kw.setdefault("tty", Tty(True))
    kw.setdefault("ask", lambda prompt: ident)
    return reg.verify_entry(ws / "research" / "facts.md", "fact", ident, evidence, workspace=ws, **kw)


def test_verify_refuses_without_a_tty(ws):
    with pytest.raises(reg.VerifyRefused, match="no interactive terminal"):
        verify(ws, tty=Tty(False))
    assert load_fixture(ws).get("F03").status == "draft"


def test_verify_refuses_when_profile_wrap_worker_is_set_even_with_a_tty(ws):
    with pytest.raises(reg.VerifyRefused, match="PROFILE_WRAP_WORKER=1"):
        verify(ws, env={"PROFILE_WRAP_WORKER": "1"})
    assert load_fixture(ws).get("F03").status == "draft"


def test_verify_success_records_who_when_and_evidence(ws):
    e = verify(ws, verifier="maya", on_date=dt.date(2026, 10, 2))
    assert e.status == "verified" and e.row["verified_by"] == "maya" and e.row["verified_at"] == "2026-10-02"
    assert e.row["evidence"] == "notes/clinics.md"
    assert verify(ws, "F04", "https://example.com/proof").row["evidence"].startswith("https://")


def test_verify_refusals_evidence_confirmation_unknown_id(ws):
    with pytest.raises(reg.VerifyRefused, match="evidence file not found"):
        verify(ws, evidence="notes/missing.md")
    with pytest.raises(reg.VerifyRefused, match="--evidence is required"):
        verify(ws, evidence=" ")
    with pytest.raises(reg.VerifyRefused, match="confirmation did not match"):
        verify(ws, ask=lambda p: "yes")
    with pytest.raises(reg.VerifyRefused, match="F77 not found"):
        verify(ws, "F77")
    assert load_fixture(ws).get("F03").status == "draft"
    assert reg.is_tty() in (True, False)  # never raises under pytest capture


def test_stats_expire_and_verify(ws):
    path = ws / "research" / "stats.md"
    changed = reg.expire_stats(path, on_date=dt.date(2026, 10, 16), dry_run=True)
    assert changed == ["S02"] and reg.load_register(path, "stat").get("S02").status == "verified"
    assert reg.expire_stats(path, on_date=dt.date(2026, 10, 16)) == ["S02"]
    assert reg.load_register(path, "stat").get("S02").status == "expired"
    assert reg.expire_stats(path, on_date=dt.date(2026, 10, 16)) == []
    e = reg.verify_entry(path, "stat", "S04", "https://example.com/new", workspace=ws, tty=Tty(True),
                         ask=lambda p: "S04")
    assert e.status == "verified"
    assert reg.default_expiry(dt.date(2026, 1, 1), 90) == dt.date(2026, 4, 1)


def test_export(ws):
    rows = reg.export_entries(load_fixture(ws), verified_only=True)
    ids = {r["id"] for r in rows}
    assert "F03" not in ids and "F01" in ids
    assert rows[0]["numbers_parsed"][0]["unit"] == "minute"


def _parser():
    root = argparse.ArgumentParser()
    register_facts(root.add_subparsers(dest="cmd", required=True))
    return root


def run_cli(argv):
    args = _parser().parse_args(argv)
    return args.func(args)


def test_cli_add_lint_export(ws, capsys):
    base = ["--workspace", str(ws)]
    assert run_cli(["facts", "add", "--claim", "New claim", "--numbers", "5 clinics", "--source", "notes/x.md"] + base) == 0
    assert "added F07 as draft" in capsys.readouterr().out
    assert run_cli(["facts", "add", "--claim", "Dup", "--source", "s", "--id", "F07"] + base) == 1
    assert "FAIL" in capsys.readouterr().out
    assert run_cli(["facts", "lint"] + base) == 0
    out = capsys.readouterr().out
    assert "PASS facts.md: 7 entries" in out
    assert run_cli(["facts", "lint", "--json"] + base) == 0
    assert json.loads(capsys.readouterr().out)["entries"] == 7
    assert run_cli(["facts", "export", "--verified-only"] + base) == 0
    assert "F01" in capsys.readouterr().out
    (ws / "research" / "facts.md").unlink()
    assert run_cli(["facts", "export"] + base) == 1
    assert run_cli(["facts", "lint"] + base) == 1


def test_cli_stats(ws, capsys):
    base = ["--workspace", str(ws)]
    assert run_cli(["stats", "add", "--stat", "S", "--numbers", "50%", "--url", "https://example.com/s",
                    "--grade", "a", "--retrieved", "2026-10-01"] + base) == 0
    out = capsys.readouterr().out
    assert "added S05" in out and "expires 2026-12-30" in out
    assert run_cli(["stats", "add", "--stat", "S", "--url", "u", "--grade", "Q"] + base) == 1
    assert run_cli(["stats", "add", "--stat", "S", "--url", "u", "--grade", "A", "--retrieved", "bad"] + base) == 1
    assert run_cli(["stats", "add", "--stat", "S", "--url", "u", "--grade", "A", "--expires", "bad"] + base) == 1
    capsys.readouterr()
    assert run_cli(["stats", "expire", "--dry-run", "--today", "2026-10-16"] + base) == 0
    assert "would expire S02" in capsys.readouterr().out
    assert run_cli(["stats", "expire", "--today", "2026-10-16", "--json"] + base) == 0
    assert json.loads(capsys.readouterr().out)["expired"] == ["S02"]
    assert run_cli(["stats", "expire", "--today", "2026-10-16"] + base) == 0
    assert "no stat has passed" in capsys.readouterr().out
    assert run_cli(["stats", "lint"] + base) == 0


def _verify_subprocess(ws, env_extra):
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONPATH": str(ROOT), **env_extra}
    code = ("import argparse,sys;from profile_wrap.facts.cli_ext import register;p=argparse.ArgumentParser();"
            "register(p.add_subparsers(dest='c',required=True));a=p.parse_args(sys.argv[1:]);sys.exit(a.func(a))")
    return subprocess.run([sys.executable, "-c", code, "facts", "verify", "F03", "--evidence", "notes/clinics.md",
                           "--workspace", str(ws)], capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL)


def test_verify_through_the_real_cli_refuses_without_a_tty(ws):
    r = _verify_subprocess(ws, {})
    assert r.returncode == 1 and "no interactive terminal" in r.stderr
    assert load_fixture(ws).get("F03").status == "draft"


def test_verify_through_the_real_cli_refuses_when_profile_wrap_worker_is_set(ws):
    r = _verify_subprocess(ws, {"PROFILE_WRAP_WORKER": "1"})
    assert r.returncode == 1 and "PROFILE_WRAP_WORKER=1" in r.stderr
    assert load_fixture(ws).get("F03").status == "draft"


def test_fixture_files_exist():
    assert (FIX / "facts.md").is_file()
