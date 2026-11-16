"""The planning and setup skills: learnings feed, tool-series method, profile apply checklist, identical mirrors."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TREES = (ROOT / "skills", ROOT / ".agents" / "skills")
PROMPTS = ROOT / "prompts"
FIELD = re.compile(r"\{\{\s*([A-Za-z0-9_.]+)\s*\}\}")


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


@pytest.mark.parametrize("tree", TREES)
def test_plan_reads_learnings_but_they_never_override_facts_or_slots(tree):
    t = read(tree / "pw-plan" / "SKILL.md")
    assert "research/analysis-kb/LEARNINGS.md" in t
    assert "never overrides a fact in the register" in t and "slot rule" in t


@pytest.mark.parametrize("tree", TREES)
def test_plan_names_the_tool_series_method_and_the_reread_step(tree):
    t = read(tree / "pw-plan" / "SKILL.md")
    assert "profile_wrap.plan.calendar.prior_angles(subject)" in t
    assert "differs from every earlier post" in t
    assert "re-read it from the source" in t and "supersedes the old one" in t
    m = read(tree / "pw-plan" / "references" / "planning-method.md")
    assert "## 7. Series about a tool or project" in m and "## 8. The weekly learnings loop" in m


@pytest.mark.parametrize("tree", TREES)
def test_setup_has_the_profile_apply_checklist(tree):
    assert "references/profile-apply.md" in read(tree / "pw-setup" / "SKILL.md")
    t = read(tree / "pw-setup" / "references" / "profile-apply.md")
    for needle in ("Re-read the headline after every experience save", "Escape discards", "notify",
                   "may have a cap", "PLACEHOLDER", "by hand"):
        assert needle in t, needle


def test_profile_apply_offers_no_automation_selectors():
    t = read(ROOT / "skills" / "pw-setup" / "references" / "profile-apply.md").lower()
    for bad in ("aria-label", "selector", "cdp", "playwright", "puppeteer", "query_selector"):
        assert bad not in t


def test_mirrors_of_the_new_reference_files_are_identical():
    for rel in ("pw-setup/references/profile-apply.md", "pw-plan/references/planning-method.md"):
        assert read(ROOT / "skills" / rel) == read(ROOT / ".agents" / "skills" / rel)
    for name, marker in (("pw-setup", "## Applying a profile edit by hand"), ("pw-plan", "**Series about a tool or project.**")):
        assert marker in read(ROOT / "skills" / name / "SKILL.md")
        assert marker in read(ROOT / ".agents" / "skills" / name / "SKILL.md")


def test_edited_files_are_lf_only():
    files = [t / n / "SKILL.md" for t in TREES for n in ("pw-plan", "pw-setup")]
    files += [PROMPTS / "weekly-read.md", PROMPTS / "learnings.template.md", PROMPTS / "profile-fix.md",
              ROOT / "docs" / "ROADMAP.md", ROOT / "commands" / "week.md"]
    for p in files:
        assert b"\r" not in p.read_bytes(), p


def test_profile_fix_prompt_carries_placeholder_rule_and_apply_checks():
    t = read(PROMPTS / "profile-fix.md")
    assert "PLACEHOLDER" in t and "never reused in a post" in t and "Apply by hand" in t


def test_weekly_read_prompt_shape():
    t = read(PROMPTS / "weekly-read.md")
    assert "FOCUS:" in t and "AMEND:" in t and "no shell" in t and "Untrusted text" in t
    assert "<<<DATA" in t and "DATA>>>" in t and t.startswith("# ") and "\n---\n" in t
    head, body = t.split("\n---\n", 1)
    assert set(FIELD.findall(body)) <= set(FIELD.findall(head))
    for rule in ("`null` means not measured", "Under {{min_n}}", "Nothing you write changes a fact"):
        assert rule in body
    for bad in ("Ma" + "ya", "Thman" + "yah", "O" + ":" + "\\"):
        assert bad not in t
