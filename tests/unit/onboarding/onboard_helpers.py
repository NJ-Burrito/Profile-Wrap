"""Helpers shared by the onboarding tests (a unique module name, safe next to other packages' tests)."""
from __future__ import annotations

import json
from pathlib import Path

FIRST_RUN_ANSWERS = {
    "schema_version": 1,
    "where": {"profile_id": "first-run"},
    "who": {"name": "Sam Example", "languages": ["en", "ar"], "timezone": "Europe/Lisbon", "goal": "authority"},
}


def make_draft(ws: Path, slug: str = "hello", caption: str = "A plain, true sentence.", status: str = "draft",
               first_comment: str = "", alt: str = "") -> Path:
    folder = ws / "drafts" / slug
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "meta.json").write_text(json.dumps({"slug": slug, "status": status, "format": "text", "title": "T"}),
                                      encoding="utf-8")
    (folder / "caption.txt").write_text(caption, encoding="utf-8")
    if first_comment:
        (folder / "first_comment.txt").write_text(first_comment, encoding="utf-8")
    if alt:
        (folder / "alt.txt").write_text(alt, encoding="utf-8")
    return folder


def gate_pass(slug, ws, write=False):
    return {"summary": "PASS", "fails": [], "warnings": [], "checks": {}}


def gate_fail(slug, ws, write=False):
    return {"summary": "FAIL", "fails": ["numbers: 40 tickets has no cited fact"], "warnings": [], "checks": {}}
