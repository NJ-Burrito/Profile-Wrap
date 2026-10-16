"""WP9 M1 release files: licence, ignore rules, allow file, CI skeleton, and a self-scan of these paths."""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

from njli import leakcheck as L

REPO = Path(__file__).resolve().parents[2]

# The paths this package owns in milestone M1.
OWN = [
    "njli/leakcheck.py", "njli/compliance/__init__.py", "njli/compliance/__main__.py",
    "njli/compliance/lint.py", "njli/compliance/rules.py", "LICENSE", "NOTICE.md",
    "THIRD_PARTY.md", "SECURITY.md", ".gitignore", ".gitattributes", "release/leak-allow.json",
    ".github/workflows/ci.yml", "tests/e2e/test_leakcheck.py", "tests/e2e/test_compliance.py",
    "tests/e2e/test_release_files.py",
]


def test_own_files_exist():
    assert [p for p in OWN if not (REPO / p).is_file()] == []


def test_license_is_mit_with_contributors():
    text = (REPO / "LICENSE").read_text(encoding="utf-8")
    assert text.startswith("MIT License")
    assert "Copyright (c) 2026 nj-linkedin contributors" in text


def test_notice_and_third_party_and_security_have_content():
    for name, needle in (("NOTICE.md", "not affiliated"), ("THIRD_PARTY.md", "Lucide"), ("SECURITY.md", "vulnerability")):
        assert needle in (REPO / name).read_text(encoding="utf-8")


def test_gitignore_covers_fonts_photos_pyc_venv_dist_zipapp_secrets():
    lines = {ln.strip() for ln in (REPO / ".gitignore").read_text(encoding="utf-8").splitlines()}
    for need in ("*.woff2", "*.ttf", "*.otf", "*.jpg", "*.jpeg", "*.py[cod]", "__pycache__/", ".venv/", "dist/", "*.pyz", ".env", "token.json", "brand/fonts/"):
        assert need in lines, need


def test_allow_file_parses_and_every_entry_has_reason():
    data = json.loads((REPO / "release" / "leak-allow.json").read_text(encoding="utf-8"))
    assert data["version"] == 1
    assert L.load_allow(REPO / "release" / "leak-allow.json") == [] or all(a.reason for a in L.load_allow(REPO / "release" / "leak-allow.json"))


def test_ci_skeleton_runs_tests_compliance_and_leak_scan():
    ci = (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "pytest" in ci
    assert "njli.compliance lint" in ci
    assert "njli.leakcheck scan --tree" in ci
    for osname in ("ubuntu-latest", "macos-latest", "windows-latest"):
        assert osname in ci
    assert '"3.10"' in ci and '"3.12"' in ci
    assert not re.search(r"\bsecrets\.[A-Z_]+\s*\}\}.*\n.*run:.*echo", ci)  # secrets not echoed


def test_own_paths_are_leak_clean():
    found = L.scan_files(REPO, OWN, L.load_allow(REPO / "release" / "leak-allow.json"))
    assert found == [], [f.render() for f in found]


def test_own_paths_pass_py_compile():
    py = [str(REPO / p) for p in OWN if p.endswith(".py")]
    r = subprocess.run(["python", "-m", "py_compile", *py], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def _private_denylist():
    path = os.environ.get(L.ENV_DENYLIST)
    if not path or not Path(path).is_file():
        return None
    return L.Denylist.load(path)


def test_own_paths_contain_no_private_terms():
    """Private names are never written in the repo: terms come only from the salted-hash denylist."""
    deny = _private_denylist()
    if deny is None:
        pytest.skip(f"SKIP: no private denylist supplied (set {L.ENV_DENYLIST}); private-term check not run")
    found = [f for f in L.scan_files(REPO, OWN, denylist=deny) if f.rule == "private-term"]
    assert found == [], [f.render() for f in found]


def test_private_term_check_positive_control(tmp_path):
    """The same check, run with a fictional denylist, does catch a fictional term."""
    deny = L.Denylist.load(_write(tmp_path, L.build_denylist(["Acme Widgetry"], salt="t")))
    (tmp_path / "x.md").write_text("we met Acme Widgetry\n", encoding="utf-8")
    assert [f.rule for f in L.scan_files(tmp_path, ["x.md"], denylist=deny)] == ["private-term"]
    (tmp_path / "y.md").write_text("nothing here\n", encoding="utf-8")
    assert L.scan_files(tmp_path, ["y.md"], denylist=deny) == []


def _write(tmp_path, data):
    p = tmp_path / "deny.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def test_gitattributes_line_endings():
    lines = [ln.strip() for ln in (REPO / ".gitattributes").read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.startswith("#")]
    assert "* text=auto" in lines
    assert "bin/njli text eol=lf" in lines
    assert "*.cmd text eol=crlf" in lines
    assert "*.sh text eol=lf" in lines
