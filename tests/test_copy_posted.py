"""Copy mode closes the loop: ``copy <slug> --posted`` and ``copymode.mark_posted`` write the ledger."""
from __future__ import annotations

import json

import pytest

from profile_wrap import cli, copymode, ledger, schemalite
from profile_wrap.plan import calendar as calmod


@pytest.fixture()
def ws(tmp_path, monkeypatch):
    for name in ("PROFILE_WRAP_WORKSPACE", "PROFILE_WRAP_WORKER"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PROFILE_WRAP_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("PROFILE_WRAP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PYTHONUTF8", "1")
    root = tmp_path / "ws"
    (root / "drafts").mkdir(parents=True)
    return root


def make_draft(root, slug="d1", status="draft", first_comment="Notes here."):
    folder = root / "drafts" / slug
    folder.mkdir(parents=True)
    meta = {"slug": slug, "title": "A title", "lang": "en", "format": "text", "pillar": "P1", "status": status}
    (folder / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (folder / "caption.txt").write_text("A plain sentence about testing.\n", encoding="utf-8")
    if first_comment:
        (folder / "first_comment.txt").write_text(first_comment, encoding="utf-8")
    return folder


def make_calendar(root, slug="d1"):
    cal = calmod.empty()
    calmod.add_entry(cal, date="2026-12-02", slug=slug, title="A title", lang="en", format="text", status="built")
    calmod.save(root, cal)


def test_posted_writes_one_ledger_row_like_api_posting(ws):
    folder = make_draft(ws)
    make_calendar(ws)
    row = copymode.mark_posted("d1", "https://www.linkedin.com/feed/update/demo/urn:li:activity:0000000000/", ws=ws)
    rows = ledger.entries(ws)
    assert len(rows) == 1 and rows[0]["slug"] == "d1"
    assert row["state"] == "posted" and row["automation"] == {"mode": "copy", "by": "user"}
    assert row["urn"] == "urn:li:activity:0000000000"
    assert (row["format"], row["lang"], row["pillar"], row["title"]) == ("text", "en", "P1", "A title")
    assert row["first_comment_state"] == "none"
    assert schemalite.validate(row, schemalite.load_schema(
        __import__("profile_wrap.paths", fromlist=["x"]).resource("schema", "ledger.schema.json"))) == []
    meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
    assert meta["status"] == "posted" and meta["url"].startswith("https://www.linkedin.com/")
    entry = calmod.find(calmod.load(ws), "d1")
    assert entry["status"] == "posted" and entry["posted_at"] == row["posted_at"]
    report = calmod.validate(calmod.load(ws), {"persona": {"languages": ["en"]}}, workspace=ws)
    assert report.ok


def test_posted_without_url_is_allowed_and_second_call_refuses(ws):
    make_draft(ws, first_comment="")
    row = copymode.mark_posted("d1", ws=ws)
    assert "url" not in row and "first_comment" not in row
    with pytest.raises(copymode.PostedRefused, match="already in the ledger"):
        copymode.mark_posted("d1", ws=ws)
    assert len(ledger.entries(ws)) == 1


def test_posted_refusals_write_nothing(ws):
    make_draft(ws)
    with pytest.raises(copymode.PostedRefused, match="no draft"):
        copymode.mark_posted("nope", ws=ws)
    with pytest.raises(copymode.PostedRefused, match="valid draft name"):
        copymode.mark_posted("../x", ws=ws)
    with pytest.raises(copymode.PostedRefused, match="https://www.linkedin.com/"):
        copymode.mark_posted("d1", "http://evil.example.invalid/x", ws=ws)
    assert ledger.entries(ws) == []
    assert not calmod.calendar_path(ws).exists()   # no calendar is created as a side effect


def test_posted_after_needs_check_points_to_resolve(ws):
    make_draft(ws)
    ledger.append(ws, {"slug": "d1", "state": "needs_check", "idempotency_key": "k1", "started_at": ledger.now_iso()})
    with pytest.raises(copymode.PostedRefused, match="--resolve --posted"):
        copymode.mark_posted("d1", ws=ws)


def test_cli_posted_flag(ws, capsys):
    make_draft(ws)
    assert cli.main(["copy", "d1", "--posted", "--url", "https://www.linkedin.com/posts/demo-1", "--workspace", str(ws)]) == 0
    assert "recorded d1 as posted" in capsys.readouterr().out
    assert cli.main(["copy", "d1", "--posted", "--workspace", str(ws)]) == 1
    assert "already in the ledger" in capsys.readouterr().err
    assert cli.main(["copy", "d1", "--url", "https://www.linkedin.com/x", "--workspace", str(ws)]) == 2
    assert len(ledger.entries(ws)) == 1
