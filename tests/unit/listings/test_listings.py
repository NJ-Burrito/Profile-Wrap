"""Listing texts: product name, no LinkedIn in names, links point at the project repo."""
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
LISTINGS = sorted((ROOT / "docs" / "listings").glob("*.md"))
REPO = "https://github.com/NJ-Burrito/profile-wrap"
OWN_HOSTS = ("github.com/NJ-Burrito/profile-wrap", "raw.githubusercontent.com/NJ-Burrito/profile-wrap")
# External sites a listing may link to (directories, not the product).
EXTERNAL_OK = ("pypi.org/project/profile-wrap-mcp", "claude.ai/directory/manage", "mcp.so/submit", "glama.ai")


def test_five_listings_exist():
    names = {p.stem for p in LISTINGS}
    assert names == {"official-mcp-registry", "mcp-so", "glama", "smithery", "anthropic-plugin-directory"}


@pytest.mark.parametrize("path", LISTINGS, ids=lambda p: p.stem)
def test_names_profile_wrap_and_disclaims(path):
    text = path.read_text(encoding="utf-8")
    assert "Profile-Wrap" in text
    assert "not affiliated with LinkedIn" in text.lower() or "Not affiliated with LinkedIn" in text


@pytest.mark.parametrize("path", LISTINGS, ids=lambda p: p.stem)
def test_no_linkedin_in_product_name(path):
    text = path.read_text(encoding="utf-8")
    m = re.search(r"## Name\s+(.+?)\n", text)
    assert m, "missing Name section"
    assert "linkedin" not in m.group(1).lower()
    assert "claude-" not in m.group(1).lower() and "anthropic-" not in m.group(1).lower()


@pytest.mark.parametrize("path", LISTINGS, ids=lambda p: p.stem)
def test_links_point_at_repo(path):
    text = path.read_text(encoding="utf-8")
    assert REPO in text
    for url in re.findall(r"https?://[^\s)>\]]+", text):
        ok = any(h in url for h in OWN_HOSTS) or any(h in url for h in EXTERNAL_OK)
        assert ok, f"unexpected link {url} in {path.name}"
        if "github.com/" in url:
            assert "github.com/NJ-Burrito/profile-wrap" in url, url


@pytest.mark.parametrize("path", LISTINGS, ids=lambda p: p.stem)
def test_screenshots_exist(path):
    text = path.read_text(encoding="utf-8")
    shots = re.findall(r"`(docs/assets/[^`]+)`", text)
    assert shots
    for s in shots:
        assert (ROOT / s).is_file(), s


def test_privacy_and_distribution_content():
    priv = (ROOT / "docs" / "PRIVACY.md").read_text(encoding="utf-8").lower()
    for needle in ("keychain", "telemetry", "official linkedin api", "not affiliated with linkedin"):
        assert needle in priv
    dist = (ROOT / "docs" / "DISTRIBUTION.md").read_text(encoding="utf-8")
    for needle in ("mcp-publisher login github", "mcp-publisher publish", "release.yml", "pypi",
                   "the maintainer", "Lead/CI", "2026-10-16", "not affiliated with LinkedIn"):
        assert needle in dist


def test_root_glama_json():
    data = json.loads((ROOT / "glama.json").read_text(encoding="utf-8"))
    assert data["maintainers"] == ["NJ-Burrito"]


def test_plugin_privacy_url_points_at_privacy_md():
    pj = json.loads((ROOT / "plugins/profile-wrap/.claude-plugin/plugin.json").read_text(encoding="utf-8"))
    url = pj["privacyPolicyUrl"]
    assert url.startswith(REPO + "/") and url.endswith("/main/docs/PRIVACY.md")
