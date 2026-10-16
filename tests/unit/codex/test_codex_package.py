"""Package F: the Codex plugin and the portable Agent Skills (offline schema checks against agentskills.io)."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
PLUGIN = REPO / "plugins" / "profile-wrap-codex"
SKILL_ROOTS = [REPO / ".agents" / "skills", PLUGIN / "skills"]
NAMES = ["pw-plan", "pw-setup", "pw-ship", "pw-visuals", "pw-write"]
NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
BANNED_BODY = ("CLAUDE_PLUGIN_ROOT", "AskUserQuestion", "nj-method", "CLAUDE.md", "Skill tool")
BANNED_NAME = re.compile(r"linkedin|claude-|anthropic-", re.IGNORECASE)


def frontmatter(path: Path) -> tuple[dict[str, str], str]:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), path
    head, _, body = text[4:].partition("\n---\n")
    fm: dict[str, str] = {}
    for line in head.splitlines():
        key, _, value = line.partition(":")
        fm[key.strip()] = value.strip()
    return fm, body


@pytest.mark.parametrize("root", SKILL_ROOTS, ids=["agents", "plugin"])
def test_exactly_the_five_skills(root):
    assert sorted(p.name for p in root.iterdir() if p.is_dir()) == NAMES


@pytest.mark.parametrize("root", SKILL_ROOTS, ids=["agents", "plugin"])
@pytest.mark.parametrize("name", NAMES)
def test_skill_follows_agent_skills_spec(root, name):
    path = root / name / "SKILL.md"
    fm, body = frontmatter(path)
    assert fm["name"] == name and NAME_RE.match(name) and len(name) <= 64
    assert 1 <= len(fm["description"]) <= 1024
    assert set(fm) <= {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
    assert len(body.splitlines()) < 500
    for f in (root / name).rglob("*.md"):
        text = f.read_text(encoding="utf-8")
        for bad in BANNED_BODY:
            assert bad not in text, f"{bad} in {f}"


@pytest.mark.parametrize("name", NAMES)
def test_commands_call_the_cli(name):
    body = (PLUGIN / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
    assert "`profile-wrap" in body
    assert "bin/profile-wrap" not in body


@pytest.mark.parametrize("name", NAMES)
def test_both_copies_identical(name):
    a, b = SKILL_ROOTS
    files_a = sorted(p.relative_to(a / name) for p in (a / name).rglob("*") if p.is_file())
    files_b = sorted(p.relative_to(b / name) for p in (b / name).rglob("*") if p.is_file())
    assert files_a == files_b
    for rel in files_a:
        assert (a / name / rel).read_bytes() == (b / name / rel).read_bytes(), rel


@pytest.mark.parametrize("name", NAMES)
def test_references_resolve_and_are_one_level(name):
    skill = PLUGIN / "skills" / name
    body = (skill / "SKILL.md").read_text(encoding="utf-8")
    for ref in set(re.findall(r"`(references/[\w.-]+\.md)`", body)):
        assert (skill / ref).is_file(), ref
    assert not [p for p in (skill / "references").rglob("*") if p.is_dir()]


def test_plugin_manifest():
    m = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    assert m["name"] == "profile-wrap-codex" and NAME_RE.match(m["name"])
    assert not BANNED_NAME.search(m["name"])
    assert m["version"] and m["description"] and m["license"] == "MIT"
    assert (PLUGIN / m["skills"]).is_dir()
    assert m["extensions"]["com.openai"]["interface"]["displayName"] == "Profile-Wrap"
    assert "not affiliated with LinkedIn" in m["description"]


def test_no_hooks_anywhere():
    assert not (PLUGIN / "hooks").exists()
    assert not list(PLUGIN.rglob("hooks.json"))
    assert "hooks" not in json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))


def test_plugin_folder_is_slim_and_licensed():
    files = [p for p in PLUGIN.rglob("*") if p.is_file()]
    assert len(files) < 512 and (PLUGIN / "LICENSE").is_file()
    assert all(p.suffix in {".md", ".json", ""} for p in files)
    readme = re.sub(r"```.*?```", "", (PLUGIN / "README.md").read_text(encoding="utf-8"), flags=re.DOTALL)
    assert len(readme.split()) >= 40
    assert not any(p.is_symlink() for p in PLUGIN.rglob("*"))


def test_marketplace_points_at_plugin():
    mk = json.loads((REPO / ".agents" / "plugins" / "marketplace.json").read_text(encoding="utf-8"))
    assert mk["name"] == "profile-wrap" and not BANNED_NAME.search(mk["name"])
    (entry,) = mk["plugins"]
    assert entry["name"] == "profile-wrap-codex"
    assert {"name", "source", "policy", "category"} <= set(entry)
    assert entry["source"]["source"] == "local" and entry["source"]["path"].startswith("./")
    assert (REPO / entry["source"]["path"] / "plugin.json").is_file()


def test_codex_doc_has_mcp_toml_and_agents_section():
    doc = (REPO / "docs" / "CODEX.md").read_text(encoding="utf-8")
    assert "codex plugin marketplace add" in doc and "## 4. AGENTS.md section" in doc
    toml = re.search(r"```toml\n(.*?)```", doc, re.DOTALL).group(1)
    try:
        import tomllib
    except ImportError:  # python 3.10
        import tomli as tomllib
    cfg = tomllib.loads(toml)
    server = cfg["mcp_servers"]["profile-wrap"]
    assert server["command"] == "uvx" and server["args"][0].startswith("profile-wrap-mcp==")
