"""Lint .github/workflows/release.yml and the PyInstaller spec without building anything.

Text checks run everywhere; structural YAML checks run when PyYAML is installed.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
WF = ROOT / ".github" / "workflows" / "release.yml"
SPEC = ROOT / "release" / "desktop" / "profile-wrap.spec"
LAUNCHER = ROOT / "release" / "desktop" / "launcher.py"
TEXT = WF.read_text(encoding="utf-8")


def _job_block(name: str) -> str:
    m = re.search(rf"^  {re.escape(name)}:\n(.*?)(?=^  [a-z][\w-]*:\n|\Z)", TEXT, re.S | re.M)
    assert m, f"job {name} missing"
    return m.group(1)


def test_tag_trigger_and_dry_run():
    assert re.search(r'push:\s*\n\s*tags:\s*\["v\*"\]', TEXT)
    assert "workflow_dispatch:" in TEXT


def test_top_level_permissions_are_read_only():
    top = TEXT.split("\njobs:")[0]
    assert re.search(r"^permissions:\n  contents: read\n", top, re.M)
    assert "write" not in top


@pytest.mark.parametrize("job", ["version", "desktop", "python-dist", "checksums", "publish-pypi", "github-release"])
def test_jobs_exist_and_are_named(job):
    assert re.search(r"^    name: .+", _job_block(job), re.M)


def test_desktop_matrix_covers_four_targets():
    block = _job_block("desktop")
    for os_name in ("windows-latest", "macos-latest", "macos-26-intel", "ubuntu-latest"):
        assert os_name in block
    assert "build.py" in block and "selftest_artifact.py" in block
    assert block.index("build.py") < block.index("selftest_artifact.py") < block.index("upload-artifact")


def test_pypi_trusted_publishing():
    block = _job_block("publish-pypi")
    assert re.search(r"^    environment: pypi$", block, re.M)
    assert re.search(r"permissions:\n      id-token: write", block)
    assert block.count("pypa/gh-action-pypi-publish@") == 1
    assert "packages-dir: dist/profile-wrap\n" in block
    assert "password" not in block and "secrets." not in block, "trusted publishing needs no token"
    assert "startsWith(github.ref, 'refs/tags/v')" in block
    # PyPI allows one project per (repository, workflow, environment): the MCP package has its own environment.
    mcp = _job_block("publish-pypi-mcp")
    assert re.search(r"^    environment: pypi-mcp$", mcp, re.M)
    assert re.search(r"permissions:\n      id-token: write", mcp)
    assert "packages-dir: dist/profile-wrap-mcp" in mcp and "secrets." not in mcp


def test_python_dist_builds_both_packages():
    block = _job_block("python-dist")
    assert "build --outdir dist/profile-wrap ." in block
    assert "build --outdir dist/profile-wrap-mcp mcp" in block


def test_checksums_and_attestation():
    block = _job_block("checksums")
    assert "sha256sum" in block and "SHA256SUMS" in block
    assert "actions/attest-build-provenance@" in block
    assert "id-token: write" in block and "attestations: write" in block


def test_release_job_is_tag_only_and_only_it_writes_contents():
    block = _job_block("github-release")
    assert "contents: write" in block
    assert "startsWith(github.ref, 'refs/tags/v')" in block
    assert "SHA256SUMS" in TEXT and "--notes-file" in block and "changelog_section.py" in block
    for job in ("version", "desktop", "python-dist", "checksums", "publish-pypi"):
        assert "contents: write" not in _job_block(job)


def test_no_secrets_and_actions_are_versioned():
    assert "secrets." not in TEXT.replace("secrets.GITHUB_TOKEN", "")
    for use in re.findall(r"uses: ([^\s]+)", TEXT):
        assert "@" in use, f"unpinned action {use}"


def test_workflow_parses_as_yaml_structurally():
    yaml = pytest.importorskip("yaml")
    data = yaml.safe_load(TEXT)
    triggers = data.get("on", data.get(True))
    assert triggers["push"]["tags"] == ["v*"] and "workflow_dispatch" in triggers
    jobs = data["jobs"]
    assert jobs["publish-pypi"]["environment"] == "pypi"
    assert jobs["publish-pypi"]["permissions"] == {"id-token": "write"}
    assert data["permissions"] == {"contents": "read"}
    assert all("name" in j for j in jobs.values())
    include = jobs["desktop"]["strategy"]["matrix"]["include"]
    assert len(include) == 4
    for j in ("checksums", "publish-pypi", "github-release"):
        assert "desktop" in jobs[j]["needs"] or "checksums" in jobs[j]["needs"]


def test_spec_is_valid_python_and_one_folder_named_profile_wrap():
    src = SPEC.read_text(encoding="utf-8")
    ast.parse(src)
    assert 'name="Profile-Wrap"' in src
    assert "COLLECT(" in src and "exclude_binaries=True" in src, "one-folder build"
    assert "launcher.py" in src
    assert "gui_assets" in src and "schema" in src and '"data"' in src
    assert 'collect_submodules("profile_wrap")' in src
    assert "keyring" in src
    assert '"fonts"' not in src and "assets/fonts" not in src, "no fonts are bundled"


def test_launcher_routes_to_gui():
    ns: dict = {"__name__": "launcher_under_test"}
    exec(compile(LAUNCHER.read_text(encoding="utf-8"), str(LAUNCHER), "exec"), ns)
    argv = ns["_argv"]
    assert argv([]) == ["gui"]
    assert argv(["--selftest"]) == ["gui", "--selftest"]
    assert argv(["demo", "run"]) == ["demo", "run"]
    assert argv(["--version"]) == ["--version"]


def test_changelog_section_extracts():
    ns: dict = {"__name__": "x"}
    p = ROOT / "release" / "desktop" / "changelog_section.py"
    exec(compile(p.read_text(encoding="utf-8"), str(p), "exec"), ns)
    text = "# C\n\n## [0.2.0] - d\n\n- a\n\n## [0.1.1] - d\n\n- b\n"
    assert ns["section"](text, "v0.2.0") == "- a"
    assert ns["section"](text, "9.9.9") is None
