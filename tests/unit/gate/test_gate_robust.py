"""Missing inputs, a BOM, missing tools: readable FAIL lines, never a traceback."""
from __future__ import annotations

import json

from gate_helpers import make_draft, write_config

from njli.gate import run_gate
from njli.gate.cli_ext import register as register_gate
from njli.gate.runner import format_lines


def test_missing_facts_file_is_a_readable_fail(ws):
    (ws / "research" / "facts.md").unlink()
    make_draft(ws, "d1", "Plain sentence.\n")
    res = run_gate("d1", ws)
    assert res["summary"] == "FAIL"
    assert any("facts file not found" in f and "facts.md" in f for f in res["fails"])
    assert res["checks"]["facts"]["ok"] is False


def test_bom_in_meta_json_is_a_readable_fail_and_the_run_continues(ws):
    d = make_draft(ws, "d1", "Plain sentence.\n")
    raw = (d / "meta.json").read_bytes()
    (d / "meta.json").write_bytes(b"\xef\xbb\xbf" + raw)
    res = run_gate("d1", ws)
    assert res["summary"] == "FAIL"
    assert any("BOM" in f and "meta.json" in f for f in res["fails"])
    assert res["checks"]["caption"]["ok"]  # the other checks still ran


def test_bom_in_caption_is_caught_as_an_invisible_character(ws):
    d = make_draft(ws, "d1", "Plain sentence.\n")
    (d / "caption.txt").write_bytes(b"\xef\xbb\xbfPlain sentence.\n")
    assert any("U+FEFF" in f for f in run_gate("d1", ws)["fails"])


def test_bom_in_facts_file_warns_but_still_works(ws):
    p = ws / "research" / "facts.md"
    p.write_bytes(b"\xef\xbb\xbf" + p.read_bytes())
    make_draft(ws, "d1", "The audit found 7 dashboards.\n", claims=["F02"])
    res = run_gate("d1", ws)
    assert res["summary"] == "PASS" and any("BOM" in w for w in res["warnings"])


def test_invalid_and_non_object_meta(ws):
    d = make_draft(ws, "d1", "Plain sentence.\n")
    (d / "meta.json").write_text("{not json", encoding="utf-8")
    assert any("not valid UTF-8 JSON" in f for f in run_gate("d1", ws)["fails"])
    (d / "meta.json").write_text("[1,2]", encoding="utf-8")
    assert any("must hold a JSON object" in f for f in run_gate("d1", ws)["fails"])
    (d / "meta.json").unlink()
    assert any("meta.json is missing" in f for f in run_gate("d1", ws)["fails"])


def test_missing_caption_and_unreadable_caption(ws):
    d = make_draft(ws, "d1", "Plain sentence.\n")
    (d / "caption.txt").unlink()
    assert any("caption.txt is missing" in f for f in run_gate("d1", ws)["fails"])
    (d / "caption.txt").write_bytes(b"\xff\xfe\x00bad")
    assert any("unreadable" in f for f in run_gate("d1", ws)["fails"])
    (d / "caption.txt").write_text("   \n", encoding="utf-8")
    assert any("caption is empty" in f for f in run_gate("d1", ws)["fails"])


def test_missing_argument_and_missing_folder(ws, capsys):
    res = run_gate(None, ws)
    assert res["summary"] == "FAIL" and "no draft given" in res["fails"][0]
    assert run_gate("   ", ws)["summary"] == "FAIL"
    res = run_gate("ghost", ws)
    assert res["summary"] == "FAIL" and "draft folder not found" in res["fails"][0]
    assert not (ws / "drafts" / "ghost").exists()  # nothing written for a draft that does not exist


def test_missing_and_invalid_config(ws):
    make_draft(ws, "d1", "Plain sentence.\n")
    (ws / "config" / "njli.json").unlink()
    res = run_gate("d1", ws)
    assert any("config" in w for w in res["warnings"]) and res["summary"] == "PASS"
    (ws / "config" / "njli.json").write_text("{broken", encoding="utf-8")
    res = run_gate("d1", ws)
    assert res["summary"] == "FAIL" and any(f.startswith("config:") for f in res["fails"])


def _render_draft(ws, ext, name="out.pdf"):
    d = make_draft(ws, "d1", "Plain sentence.\n", fmt="slides", alt="alt text\n", meta={"assets": [name]},
                   slides="<html><body><p>hi</p></body></html>")
    (d / "out").mkdir()
    (d / "out" / name).write_bytes(b"%PDF-1.4 fake")
    (d / "out" / "render.json").write_text(json.dumps({"slides": 2}), encoding="utf-8")
    return d


def test_missing_tools_skip_with_warning_by_default(ws):
    _render_draft(ws, "pdf")
    res = run_gate("d1", ws, which=lambda _t: None)
    assert res["summary"] == "PASS"
    assert any("pdffonts not found" in w and "poppler" in w for w in res["warnings"])
    assert res["skipped"]


def test_missing_tools_fail_when_configured(ws):
    write_config(ws, gate={"tools_missing": "fail"})
    _render_draft(ws, "pdf")
    res = run_gate("d1", ws, which=lambda _t: None)
    assert res["summary"] == "FAIL"
    assert any("cannot check" in f and "pdffonts" in f for f in res["fails"])


def test_format_lines_and_cli_output(ws, capsys):
    import argparse
    make_draft(ws, "d1", "I found 7 bugs.\n")
    lines = format_lines(run_gate("d1", ws))
    assert lines[0] == "FAIL d1" and lines[1].startswith("  FAIL numbers")
    root = argparse.ArgumentParser()
    register_gate(root.add_subparsers(dest="cmd"))
    args = root.parse_args(["gate", "d1", "--workspace", str(ws)])
    assert args.func(args) == 1
    assert "FAIL d1" in capsys.readouterr().out
    args = root.parse_args(["gate", "d1", "--workspace", str(ws), "--json"])
    assert args.func(args) == 1
    assert json.loads(capsys.readouterr().out)["summary"] == "FAIL"
    make_draft(ws, "ok", "Plain sentence.\n")
    args = root.parse_args(["gate", "ok", "--workspace", str(ws)])
    assert args.func(args) == 0
    args = root.parse_args(["gate"])  # no slug: a FAIL line, exit 1, not a traceback
    assert args.func(args) == 1


def test_real_entry_point_njli_gate_and_facts(ws):
    """ENTRY_SMOKE: the product's own `python -m njli` loads both extensions and returns the right exit codes."""
    import os
    import subprocess
    import sys

    from gate_helpers import ROOT
    if not (ROOT / "njli" / "cli.py").is_file():
        import pytest
        pytest.skip("core CLI (WP1) not present")
    make_draft(ws, "d1", "I found 7 bugs last week.\n")
    make_draft(ws, "ok", "Plain sentence.\n")
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONPATH": str(ROOT)}
    env.pop("NJLI_WORKER", None)

    def run(*argv):
        return subprocess.run([sys.executable, "-m", "njli", *argv, "--workspace", str(ws)], capture_output=True,
                              text=True, env=env, stdin=subprocess.DEVNULL, check=False)
    bad = run("gate", "d1")
    assert bad.returncode == 1 and "'7 bugs'" in bad.stdout
    assert run("gate", "ok").returncode == 0
    assert run("facts", "lint").returncode == 0
    refused = run("facts", "verify", "F03", "--evidence", "notes/clinics.md")
    assert refused.returncode == 1 and "no interactive terminal" in refused.stderr
