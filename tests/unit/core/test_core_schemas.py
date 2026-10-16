"""Each shipped schema accepts a good sample and rejects specific bad ones."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from profile_wrap import config, schemalite

REPO = Path(__file__).resolve().parents[3]
FIX = Path(__file__).parent / "fixtures" / "answers"


def check(name, doc):
    return schemalite.validate(doc, schemalite.load_schema(REPO / "schema" / f"{name}.schema.json"))


META = {"slug": "2026-11-02-first-post", "title": "First post", "lang": "en", "format": "gif",
        "status": "draft", "claims": ["F01"], "scheduled_at": "2026-11-02T10:15:00+00:00"}


def test_config_defaults_validate():
    assert check("config", config.defaults("Europe/Lisbon")) == []


def test_meta():
    assert check("meta", META) == []
    assert check("meta", {**META, "status": "published"})
    assert check("meta", {**META, "scheduled_at": "2026-11-02T10:15:00"})  # no offset
    assert check("meta", {k: v for k, v in META.items() if k != "claims"})


def test_calendar():
    good = {"schema_version": 1, "entries": [
        {"date": "2026-11-02", "slug": "a-post", "lang": "en", "format": "slides",
         "status": "planned", "claims": ["F01"]}]}
    assert check("calendar", good) == []
    bad = json.loads(json.dumps(good))
    bad["entries"][0]["status"] = "maybe"
    bad["entries"][0]["date"] = "tomorrow"
    assert len(check("calendar", bad)) == 2


def test_facts_row():
    row = {"id": "F01", "claim": "Closed 40 tickets", "source": "export", "status": "draft"}
    assert check("facts", row) == []
    assert check("facts", {**row, "id": "X1"})
    assert check("facts", {**row, "status": "true"})


def test_steps():
    good = {"schema_version": 1, "steps": [{"id": "s01", "title": "Headline",
                                            "open": "https://www.linkedin.com/in/demo/edit/intro/"}]}
    assert check("steps", good) == []
    good["steps"][0]["open"] = "https://evil.example/in/demo"
    assert check("steps", good)


def test_ledger_requires_posted_fields():
    pending = {"slug": "a-post", "state": "pending", "idempotency_key": "k1"}
    assert check("ledger", pending) == []
    posted = {**pending, "state": "posted"}
    assert any("missing required key" in e for e in check("ledger", posted))
    full = {**posted, "urn": "urn:li:share:DEMO000000", "url": "https://www.linkedin.com/in/demo/",
            "posted_at": "2026-11-02T10:15:00+00:00", "automation": {"mode": "api_click"}}
    assert check("ledger", full) == []
    assert check("ledger", {**full, "urn": "not-a-urn"})


def test_targets_connect_pending():
    assert check("targets", {"schema_version": 1, "targets": [
        {"name": "Pat Example", "profile_url": "https://www.linkedin.com/in/pat-example-demo/"}]}) == []
    assert check("targets", {"schema_version": 1, "targets": [
        {"name": "Pat", "profile_url": "http://example.invalid/pat"}]})
    row = {"name": "Pat Example", "profile_url": "https://www.linkedin.com/in/pat-example-demo/",
           "status": "waiting", "score": 8, "note": "x" * 200}
    assert check("connect", {"schema_version": 1, "rows": [row]}) == []
    row["note"] = "x" * 201
    assert check("connect", {"schema_version": 1, "rows": [row]})
    row.update(note="ok", score=11)
    assert check("connect", {"schema_version": 1, "rows": [row]})
    item = {"text": "A comment", "kind": "comment", "status": "pending"}
    assert check("pending", {"schema_version": 1, "items": [item]}) == []
    assert check("pending", {"schema_version": 1, "items": [{**item, "kind": "like"}]})


def test_workspace_and_manifest_and_doctor_shapes():
    assert check("workspace", {"schema_version": 1, "template_version": "1", "plugin_version": "0",
                               "profile_id": "x", "files": {
                                   ".gitignore": {"class": "managed", "sha256": "a" * 64}}}) == []
    assert check("workspace", {"schema_version": 1, "template_version": "1", "plugin_version": "0",
                               "profile_id": "x", "files": {
                                   "a": {"class": "user", "sha256": "a" * 64}}})
    manifest = json.loads((REPO / "templates" / "manifest.json").read_text(encoding="utf-8"))
    assert check("manifest", manifest) == []
    manifest["files"][0]["class"] = "user"
    assert check("manifest", manifest)
    assert check("doctor", {"schema_version": 1}) != []


@pytest.mark.parametrize("name", sorted(p.name for p in FIX.glob("*.json")))
def test_answers_fixtures_validate(name):
    doc = json.loads((FIX / name).read_text(encoding="utf-8"))
    assert check("answers", doc) == []


def test_answers_reject_unknown_and_beyond_ceiling():
    base = json.loads((FIX / "en.json").read_text(encoding="utf-8"))
    assert check("answers", {**base, "surprise": 1})
    assert check("answers", {**base, "cadence": {"per_week": 9}})
    assert check("answers", {**base, "cadence": {"comment_daily_cap": 11}})
    assert check("answers", {**base, "who": {**base["who"], "goal": "fame"}})
    assert check("answers", {"schema_version": 1})
