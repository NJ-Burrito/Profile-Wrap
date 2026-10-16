"""Compliance lint on this package's own paths, the ledger library, and a leak scan of the files."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from conftest import ROOT

from profile_wrap import ledger
import importlib

lint_mod = importlib.import_module("profile_wrap.compliance.lint")


def test_compliance_lint_passes_on_the_linkedin_package_and_skill():
    found = [v for v in lint_mod.lint(ROOT)
             if v.path.startswith(("profile_wrap/linkedin/", "profile_wrap/ledger.py", "profile_wrap/demo/fake_linkedin.py",
                                   "skills/pw-ship/"))]
    assert found == [], [v.render() for v in found]


def test_only_the_extra_names_the_social_actions_route():
    hits = [p.relative_to(ROOT).as_posix() for p in (ROOT / "profile_wrap" / "linkedin").glob("*.py")
            if "socialActions" in p.read_text(encoding="utf-8")]
    assert hits == ["profile_wrap/linkedin/social_extra.py"]


def test_the_package_reaches_only_allowlisted_endpoints():
    seen = set()
    for p in (ROOT / "profile_wrap" / "linkedin").glob("*.py"):
        seen.update(re.findall(r"(?<!oauth)/(?:v2|rest)/[A-Za-z][A-Za-z0-9/_-]*", p.read_text(encoding="utf-8")))
    allowed = ("/v2/userinfo", "/rest/posts", "/rest/images", "/rest/documents", "/v2/socialActions")
    assert seen and all(s.startswith(allowed) for s in seen), seen


def test_owned_files_have_no_personal_data():
    owned = [*(ROOT / "profile_wrap" / "linkedin").glob("*.py"), ROOT / "profile_wrap" / "ledger.py",
             ROOT / "profile_wrap" / "demo" / "fake_linkedin.py", ROOT / "data" / "linkedin-versions.json",
             *(ROOT / "skills" / "pw-ship").rglob("*.md"), *(ROOT / "commands").glob("post.md"),
             *(ROOT / "commands").glob("board.md"), ROOT / "docs" / "TERMS-AND-RISK.md",
             ROOT / "docs" / "linkedin-app-setup.md",
             *(ROOT / "docs" / "references").glob("*.md")]
    # Private names are checked by `profile-wrap leaks scan` with the owner's salted denylist, never listed here.
    banned = ["O" + r":\\", "C" + r":\\Users",r"\b\+?\d{3}[ -]?\d{7,9}\b", r"[\w.]+@[\w-]+\.(?:com|net|org|io)\b",
              r"AQ[A-Za-z0-9_-]{60,}", r"\b[A-Za-z0-9]{32,}\b"]
    for path in owned:
        text = path.read_text(encoding="utf-8")
        for pat in banned:
            m = re.search(pat, text)
            assert m is None or "example" in m.group(0).lower(), f"{path.name}: {pat}: {m.group(0)}"
    assert not [p for p in ROOT.rglob("*") if p.suffix.lower() in (".woff", ".woff2", ".ttf", ".otf")
                and ".git" not in p.parts and "node_modules" not in p.parts]


def test_ledger_collapses_rows_by_key(tmp_path):
    ledger.append(tmp_path, {"slug": "a", "state": "pending", "idempotency_key": "a-1",
                             "started_at": "2026-01-01T10:00:00+00:00"})
    ledger.update(tmp_path, "a-1", state="posted", urn="urn:li:share:1",
                  url="https://www.linkedin.com/feed/update/urn:li:share:DEMO000001/",
                  posted_at="2026-01-01T10:01:00+00:00", automation={"mode": "api_click"})
    ledger.append(tmp_path, {"slug": "b", "state": "failed", "idempotency_key": "b-1"})
    (tmp_path / "published" / "ledger.jsonl").open("a", encoding="utf-8").write("{torn line\n")
    rows = ledger.entries(tmp_path)
    assert [(r["slug"], r["state"]) for r in rows] == [("a", "posted"), ("b", "failed")]
    assert rows[0]["started_at"] and rows[0]["urn"]
    assert ledger.find_slug(tmp_path, "a")["state"] == "posted"
    assert ledger.find_slug(tmp_path, "zzz") is None
    assert ledger.last_activity(tmp_path).year == 2026
    assert ledger.read_rows(tmp_path)[1] == [4]                    # the torn line is reported, not fatal


def test_ledger_rejects_an_invalid_row_without_writing(tmp_path):
    with pytest.raises(ledger.LedgerError):
        ledger.append(tmp_path, {"slug": "a", "state": "posted", "idempotency_key": "k"})   # no urn/url
    assert not (tmp_path / "published" / "ledger.jsonl").exists()
    with pytest.raises(ledger.LedgerError):
        ledger.update(tmp_path, "missing", state="failed")


def test_legacy_rows_without_a_state_count_as_posted(tmp_path):
    path = tmp_path / "published" / "ledger.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"slug": "old", "posted_at": "2026-01-01T10:00:00+00:00",
                                "urn": "urn:li:share:9"}) + "\n", encoding="utf-8")
    assert ledger.find_slug(tmp_path, "old")["state"] == "posted"
    assert ledger.last_activity(tmp_path) is not None
    assert isinstance(Path(path), Path)
