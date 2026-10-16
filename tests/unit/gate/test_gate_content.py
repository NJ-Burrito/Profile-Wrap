"""The shipped data, templates, skill, prompts and agents: shape checks and a leak scan of WP2's own paths."""
from __future__ import annotations

import json
import re

import pytest
from gate_helpers import ROOT

from profile_wrap.facts import registers as reg
from profile_wrap.gate import check_text, rules

OWNED_DIRS = ["profile_wrap/facts", "profile_wrap/gate", "data/banned-words", "skills/pw-write", "tests/unit/gate",
              "tests/fixtures/captions"]
OWNED_FILES = ["data/hook-formulas.json", "templates/facts.example.md", "templates/voice.example.md",
               "templates/story-bank.example.md", "prompts/review.md", "prompts/comment-gate-notes.md",
               "docs/GATES.md", "agents/crew-writer.md", "agents/council-editor.md",
               "agents/council-language-voice.md"]


def owned_files():
    out = [ROOT / f for f in OWNED_FILES]
    for d in OWNED_DIRS:
        out += [p for p in (ROOT / d).rglob("*") if p.is_file() and "__pycache__" not in p.parts
                and p.suffix != ".pyc"]
    return out


def test_every_owned_file_exists_and_is_text():
    files = owned_files()
    assert len(files) > 40
    for p in files:
        assert p.is_file(), p
        assert p.suffix.lower() not in {".ttf", ".otf", ".woff", ".woff2", ".eot", ".png", ".jpg", ".jpeg", ".gif"}, p
        p.read_text(encoding="utf-8")  # must be valid UTF-8


FORBIDDEN = [
    (re.compile(r"[A-Za-z]:\\\\?(?:Users|VScode)", re.IGNORECASE), "local absolute path"),
    (re.compile(r"/(?:Users|home)/[a-z0-9_.-]+/", re.IGNORECASE), "local absolute path"),
    (re.compile(r"(?:sk-ant-|apify_api_|ghp_|AQ[A-Za-z0-9_-]{30,}|xox[bp]-)"), "token shape"),
    (re.compile(r"(?<![\w-])\+\d[\d\s().-]{8,}\d|\(\d{2,4}\)\s?\d{3}[\d\s.-]{4,}|\b\d{10,}\b"), "phone-like number"),
    (re.compile(r"urn:li:(?:person|share|ugcPost|activity):(?!DEMO000000)\w+"), "real-looking LinkedIn urn"),
    (re.compile(r"linkedin\.com/(?:in|posts|feed)/"), "real LinkedIn URL"),
]
EMAIL = re.compile(r"[\w.+-]+@([\w-]+(?:\.[\w-]+)+)")


@pytest.mark.parametrize("path", owned_files(), ids=lambda p: str(p.relative_to(ROOT)).replace("\\", "/"))
def test_leak_scan(path):
    text = path.read_text(encoding="utf-8")
    if path.name == "test_gate_content.py":  # this file holds the patterns themselves
        return
    for pat, why in FORBIDDEN:
        for m in pat.finditer(text):
            pytest.fail(f"{path.name}: {why}: {m.group(0)!r}")
    for m in EMAIL.finditer(text):
        assert m.group(1).split(".")[0] == "example" or m.group(1).endswith(("example.invalid", "example.com")), (
            f"{path.name}: email {m.group(0)}")


def test_banned_word_files_load_and_compile():
    b = rules.load_banned(["data/banned-words/en.json", "data/banned-words/ar.json"], None)
    assert not b.problems
    assert len(b.words) > 100 and len(b.patterns) >= 6 and len(b.job_seeking) >= 10
    assert {"com", "io", "ai", "uk", "jo"} <= b.tlds and len(b.tlds) > 250
    for name in ("en", "ar"):
        data = json.loads((ROOT / "data" / "banned-words" / f"{name}.json").read_text(encoding="utf-8"))
        assert data["lang"] == name and data["schema_version"] == 1
        assert len(set(data["words"])) == len(data["words"])


def test_hook_formulas_are_twenty_unique_and_their_examples_pass_the_gate(ws):
    data = json.loads((ROOT / "data" / "hook-formulas.json").read_text(encoding="utf-8"))
    forms = data["formulas"]
    assert len(forms) == 20 and len({f["id"] for f in forms}) == 20
    for f in forms:
        assert f["fictional"] is True
        assert {"id", "name", "structure_en", "structure_ar", "good_for", "engagement", "never_for",
                "example_en"} <= set(f)
        res = check_text(f["example_en"], "comment", ws)
        assert res["ok"], (f["id"], res["fails"])
    md = (ROOT / "skills" / "pw-write" / "references" / "hook-formulas.md").read_text(encoding="utf-8")
    assert all(f"`{f['id']}`" in md for f in forms)


def test_example_templates_parse_and_lint_clean():
    r = reg.load_register(ROOT / "templates" / "facts.example.md", "fact")
    assert [e.id for e in r.entries] == ["F01", "F02", "F03", "F04"]
    assert not [m for lvl, m in reg.lint_register(r) if lvl == "FAIL"]
    assert all(e.demo for e in r.entries)  # demo facts never pass in a live workspace
    for name in ("voice.example.md", "story-bank.example.md"):
        text = (ROOT / "templates" / name).read_text(encoding="utf-8")
        assert "fictional" in text.splitlines()[0].lower()


def test_skill_agents_and_prompts_have_the_expected_shape():
    skill = (ROOT / "skills" / "pw-write" / "SKILL.md").read_text(encoding="utf-8")
    assert skill.startswith("---\nname: pw-write\ndescription:")
    assert "docs/references/compliance.md" in skill
    for ref in ("caption-rules", "impact-copy", "adhd-style-preset", "no-slop", "arabic-hygiene", "council",
                "hook-formulas"):
        assert (ROOT / "skills" / "pw-write" / "references" / f"{ref}.md").is_file()
        assert f"references/{ref}.md" in skill
    for agent in ("crew-writer", "council-editor", "council-language-voice"):
        text = (ROOT / "agents" / f"{agent}.md").read_text(encoding="utf-8")
        head = text.split("---")[1]
        assert f"name: {agent}" in head and "tier:" in head and "tools:" in head
        assert "Bash" in head.split("disallowedTools:")[1]  # content workers get no Bash
        assert "Bash" not in head.split("disallowedTools:")[0].split("tools:")[1]
        assert "_standing-rules.md" in text
    review = (ROOT / "prompts" / "review.md").read_text(encoding="utf-8")
    assert "{{slug}}" in review and "<<<DATA" in review
    assert "200 characters" in (ROOT / "prompts" / "comment-gate-notes.md").read_text(encoding="utf-8")


def test_gates_doc_covers_every_check_name():
    doc = (ROOT / "docs" / "GATES.md").read_text(encoding="utf-8")
    for name in ("meta", "facts", "claims", "numbers", "private_terms", "links", "hashtags", "arabic", "render",
                 "PROFILE_WRAP_WORKER", "overrides", "gates.json", "tools_missing", "hooks/gate_"):
        assert name in doc, name
