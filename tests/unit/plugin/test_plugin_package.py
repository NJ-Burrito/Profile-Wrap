"""Package D: the slim directory plugin and the marketplace file that points at it."""
from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
PLUGIN = REPO / "plugins" / "profile-wrap"
KEBAB = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
RESERVED = {"claude", "anthropic", "official", "plugin", "mcp", "test"}
IMAGE_OK = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".woff", ".woff2", ".ttf", ".otf"}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def files() -> list[Path]:
    return [p for p in PLUGIN.rglob("*") if p.is_file()]


def frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{path} has no frontmatter"
    block = text.split("---\n", 2)[1]
    out = {}
    for line in block.splitlines():
        if ":" in line and not line.startswith(" "):
            key, _, val = line.partition(":")
            out[key.strip()] = val.strip()
    return out


def test_manifest_required_and_directory_fields():
    m = load(PLUGIN / ".claude-plugin" / "plugin.json")
    assert m["name"] == "profile-wrap" and KEBAB.match(m["name"]) and len(m["name"]) <= 64
    assert m["name"] not in RESERVED
    assert m["version"] == "0.2.1"
    assert m["license"] == "MIT"
    assert m["description"] and m["author"]["name"] and m["keywords"]
    for key in ("homepage", "repository", "documentationUrl", "supportUrl", "privacyPolicyUrl", "termsOfServiceUrl", "icon"):
        assert m[key].startswith("https://"), key
    assert "not affiliated with linkedin" in m["description"].lower()


def test_names_avoid_brand_words():
    for name in [load(PLUGIN / ".claude-plugin" / "plugin.json")["name"]] + [p.name for p in (PLUGIN / "skills").iterdir()] \
            + [p.stem for p in (PLUGIN / "commands").glob("*.md")]:
        low = name.lower()
        assert "linkedin" not in low and not low.startswith(("claude-", "anthropic-")), name


def test_marketplace_points_at_slim_plugin():
    mk = load(REPO / ".claude-plugin" / "marketplace.json")
    assert mk["name"] and mk["owner"]["name"]
    assert not mk["name"].startswith(("anthropic-", "claudeai-")) and mk["name"] != "claude-plugins-official"
    (entry,) = mk["plugins"]
    assert entry["name"] == load(PLUGIN / ".claude-plugin" / "plugin.json")["name"]
    assert entry["source"] == "./plugins/profile-wrap"
    assert (REPO / entry["source"] / ".claude-plugin" / "plugin.json").is_file()
    assert entry["version"] == load(PLUGIN / ".claude-plugin" / "plugin.json")["version"]


def test_skills_follow_agent_skills_format():
    skills = sorted(p for p in (PLUGIN / "skills").iterdir() if p.is_dir())
    assert len(skills) == 5
    for d in skills:
        fm = frontmatter(d / "SKILL.md")
        assert fm["name"] == d.name and re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", fm["name"]) and len(fm["name"]) <= 64
        assert 1 <= len(fm["description"]) <= 1024
        assert len((d / "SKILL.md").read_text(encoding="utf-8").splitlines()) < 500


def test_commands_have_description():
    cmds = list((PLUGIN / "commands").glob("*.md"))
    assert {c.stem for c in cmds} == {"setup", "week", "board", "post", "pause", "doctor"}
    for c in cmds:
        assert frontmatter(c)["description"]


def test_no_unresolvable_plugin_root_paths():
    """Every ${CLAUDE_PLUGIN_ROOT}/... path used by a skill or command exists inside the slim plugin."""
    pat = re.compile(r"\$\{CLAUDE_PLUGIN_ROOT\}/([A-Za-z0-9_./-]+)")
    for p in files():
        if p.suffix == ".md":
            for rel in pat.findall(p.read_text(encoding="utf-8")):
                assert (PLUGIN / rel.rstrip(".,")).exists(), f"{p.name}: {rel}"


def test_mcp_launcher_is_pinned_and_https_only():
    cfg = load(PLUGIN / ".mcp.json")["mcpServers"]["profile-wrap"]
    assert cfg["command"] == "uvx"
    assert cfg["args"] == ["profile-wrap-mcp==0.2.1"]
    assert not any(str(a).startswith("http://") for a in cfg["args"])


def test_directory_limits_and_hygiene():
    fs = files()
    assert len(fs) < 512
    assert not any(p.is_symlink() for p in PLUGIN.rglob("*"))
    for p in fs:
        assert p.suffix.lower() in IMAGE_OK | {".md", ".json"} or p.name == "LICENSE", p
        assert p.stat().st_size < 256 * 1024, p
        assert p.name != ".DS_Store"
    assert not (PLUGIN / "bin").exists()
    assert [p.name for p in (PLUGIN / "hooks").rglob("*") if p.is_file()] == ["hooks.json"]
    assert not (PLUGIN / ".gitattributes").exists()
    assert "MIT License" in (PLUGIN / "LICENSE").read_text(encoding="utf-8")


def test_readme_requirements():
    text = (PLUGIN / "README.md").read_text(encoding="utf-8")
    prose = re.sub(r"```.*?```", "", text, flags=re.S)
    assert len(re.findall(r"\w+", prose)) >= 40
    low = text.lower()
    for needle in ("install", "privacy", "not affiliated with"):
        assert needle in low, needle


def test_submission_checklist_exists():
    text = (PLUGIN / "SUBMISSION.md").read_text(encoding="utf-8")
    assert "claude.ai/directory/manage" in text and "[ ]" in text


def test_session_hook_is_the_optional_update_check_only():
    hooks = load(PLUGIN / "hooks" / "hooks.json")["hooks"]
    assert list(hooks) == ["SessionStart"]
    cmd = hooks["SessionStart"][0]["hooks"][0]
    assert cmd["type"] == "command" and "profile-wrap update check --hook" in cmd["command"]
    assert "command -v profile-wrap" in cmd["command"] and cmd["command"].rstrip().endswith("exit 0")
    assert cmd["timeout"] <= 10
    assert not re.search(r"curl|wget|http|install", cmd["command"])
