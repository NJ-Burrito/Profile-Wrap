"""The reading providers were removed in 0.4.0: the old commands and config keys say so. No network."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from profile_wrap import cli, config, policy

REPO = Path(__file__).resolve().parents[3]
URL = "https://www.linkedin.com/in/alex-example/"
LINE = "removed in 0.4.0: profile-wrap reads only through the official API"


@pytest.mark.parametrize("argv", [
    ["read", "posts", URL],
    ["read", "posts", URL, "--name", "Alex Example", "--text"],
    ["read"],
])
def test_read_is_removed_one_line_exit_2(capsys, make_workspace, argv):
    ws = make_workspace()
    code = cli.main([*argv, "--workspace", str(ws)])
    out = capsys.readouterr()
    assert code == 2
    assert out.err.strip() == LINE and out.out == ""


@pytest.mark.parametrize("action", ["public", "scraper"])
def test_reader_acknowledgements_are_removed(capsys, make_workspace, action):
    ws = make_workspace()
    code = cli.main(["config", "ack", action, "--phrase", policy.ACK_PHRASE, "--workspace", str(ws)])
    out = capsys.readouterr()
    assert code == 2 and LINE in out.err
    assert action not in policy.ACK_ACTIONS


def test_a_new_config_has_no_reading_section(make_workspace):
    ws = make_workspace()
    cfg = config.load(ws)
    assert "reading" not in cfg["engagement"]
    assert set(cfg["ack"]) == {"terms_read", "comments_api"}
    assert config.validate(cfg).ok
    assert "reading" not in config.effective_modes(cfg, ws)


def test_an_old_config_with_reader_keys_loads_and_validate_names_the_removal(make_workspace):
    ws = make_workspace()
    path = config.config_path(ws)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["engagement"]["reading"] = {"provider": "manual", "providers": []}
    raw.setdefault("ack", {})["scraping_risk"] = None
    path.write_text(json.dumps(raw), encoding="utf-8")
    cfg = config.load(ws)                       # must not crash
    report = config.validate(cfg)
    assert not report.ok and len(report.errors) == 1
    msg = report.errors[0]
    assert "removed in 0.4.0" in msg and "engagement.reading" in msg and "ack.scraping_risk" in msg
    assert "reads only through the official API" in msg


def test_config_validate_command_fails_on_an_old_config(capsys, make_workspace):
    ws = make_workspace()
    path = config.config_path(ws)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["engagement"]["reading"] = {"provider": "manual"}
    path.write_text(json.dumps(raw), encoding="utf-8")
    code = cli.main(["config", "validate", "--workspace", str(ws)])
    out = capsys.readouterr()
    assert code != 0 and "removed in 0.4.0" in (out.out + out.err)


def test_every_copy_of_the_compliance_text_is_identical():
    master = (REPO / "docs" / "references" / "compliance.md").read_bytes()
    copies = [p for p in REPO.glob("**/references/compliance.md")
              if "node_modules" not in p.parts and ".git" not in p.parts and "work" not in p.relative_to(REPO).parts]
    assert len(copies) >= 10
    stale = [str(p.relative_to(REPO)) for p in copies if p.read_bytes() != master]
    assert not stale, f"copy docs/references/compliance.md over: {stale}"
