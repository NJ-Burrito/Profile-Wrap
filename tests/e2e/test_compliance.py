"""compliance lint: forbidden code and wording fail; clean and pragma'd code passes."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from profile_wrap.compliance import lint

REPO = Path(__file__).resolve().parents[2]


def project(tmp_path: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return tmp_path


def ids(tmp_path, files):
    return {v.rule for v in lint(project(tmp_path, files))}


# Forbidden strings are assembled at run time so this file does not trip the linter itself.
BAD = [
    ("credentials", "profile_wrap/a.py", "c = 'li" + "_at'\n"),
    ("credentials", "profile_wrap/a.py", "h = 'JSESSION" + "ID'\n"),
    ("credentials", "profile_wrap/a.py", "p = input('pass" + "word: ')\n"),
    ("credentials", "skills/s/SKILL.md", "send the cook" + "ie along\n"),
    ("credentials", "profile_wrap/a.py", "x = 'Voy" + "ager'\n"),
    ("login-path", "profile_wrap/a.py", "u = '/log" + "in'\n"),
    ("login-path", "profile_wrap/a.py", "u = '/check" + "point'\n"),
    ("messaging", "profile_wrap/a.py", "u = '/messag" + "ing'\n"),
    ("messaging", "profile_wrap/a.py", "u = '/conversa" + "tions'\n"),
    ("invitations", "profile_wrap/a.py", "u = '/invita" + "tions'\n"),
    ("invitations", "profile_wrap/a.py", "u = '/growth/norm" + "Invitations'\n"),
    ("form-fill", "profile_wrap/a.py", "page.fi" + "ll('#x', 'y')\n"),
    ("form-fill", "profile_wrap/a.py", "def edit_pro" + "file(): pass\n"),
    ("ua-rotation", "profile_wrap/a.py", "import fake_user" + "agent\n"),
    ("ua-rotation", "profile_wrap/a.py", "ua = random.choice(user_" + "agents)\n"),
    ("evasion-wording", "profile_wrap/a.py", "# make it look hu" + "man\n"),
    ("evasion-wording", "skills/s/SKILL.md", "stays undetec" + "table\n"),
    ("evasion-wording", "profile_wrap/a.py", "# by" + "pass the check\n"),
    ("evasion-wording", "profile_wrap/a.py", "# eva" + "de detection\n"),
    ("vendor", "profile_wrap/a.py", "import Pub" + "lora\n"),
    ("vendor", "skills/s/SKILL.md", "use Pixf" + "aro\n"),
    ("vendor", "docs/other.md", ""),  # not scanned (outside profile_wrap/ and skills/)
    ("api-host", "profile_wrap/engage/x.py", "H = 'https://api.link" + "edin.com/rest/posts'\n"),
    ("api-endpoint", "profile_wrap/linkedin/x.py", "H = 'https://api.link" + "edin.com/v2/connections'\n"),
    ("api-endpoint", "profile_wrap/linkedin/x.py", "E = '/v2/social" + "Actions/x'\n"),
    ("browser-linkedin", "profile_wrap/visuals/r.py", "from playwright.sync_api import sync_playwright\nU = 'https://www.link" + "edin.com/feed'\n"),
]


@pytest.mark.parametrize("rule,path,text", [b for b in BAD if b[2]])
def test_forbidden_code_fails(tmp_path, rule, path, text):
    assert rule in ids(tmp_path, {path: text})


def test_clean_code_passes(tmp_path):
    files = {
        "profile_wrap/a.py": "import json\nsession = object()\nprint('a user session of work')\n",
        "profile_wrap/linkedin/api.py": "H = 'https://api.linkedin.com/v2/userinfo'\nP = '/rest/posts'\nI = '/rest/images?action=x'\nD = '/rest/documents'\n",
        "profile_wrap/engage/extra_actions.py": "# no linkedin host here\n",
        "profile_wrap/linkedin/extra_social.py": "S = '/v2/socialActions/urn'\n",
        "profile_wrap/visuals/r.py": "from playwright.sync_api import sync_playwright\nU = 'file:///tmp/slides.html'\n",
        "skills/s/SKILL.md": "Draft only. The human clicks.\n",
        "skills/s/automation-landscape.md": "Not supported: Publora, Pixfaro, Unipile.\n",
    }
    assert lint(project(tmp_path, files)) == []


def test_pragma_same_and_previous_line(tmp_path):
    kw = "pass" + "word"
    files = {
        "profile_wrap/a.py": f"print('never offer a {kw}')  # profile-wrap-compliance-allow: credentials\n",
        "profile_wrap/b.py": f"# profile-wrap-compliance-allow: credentials\nprint('never offer a {kw}')\n",
        "profile_wrap/c.py": f"# profile-wrap-compliance-allow: login-path\nprint('never offer a {kw}')\n",
    }
    found = lint(project(tmp_path, files))
    assert [v.path for v in found] == ["profile_wrap/c.py"]


def test_rule_table_dir_and_pycache_skipped(tmp_path):
    files = {"profile_wrap/compliance/rules.py": "x = 'by" + "pass'\n", "profile_wrap/__pycache__/a.txt": "by" + "pass\n"}
    assert lint(project(tmp_path, files)) == []


def test_cli_exit_codes(tmp_path):
    def run(root):
        return subprocess.run([sys.executable, "-m", "profile_wrap.compliance", "lint", "--root", str(root)], capture_output=True, text=True, cwd=REPO, encoding="utf-8")

    good = project(tmp_path / "g", {"profile_wrap/a.py": "x = 1\n"})
    assert run(good).returncode == 0
    bad = project(tmp_path / "b", {"profile_wrap/a.py": "# by" + "pass\n"})
    r = run(bad)
    assert r.returncode == 1 and "evasion-wording" in r.stdout
    assert run(tmp_path / "missing").returncode == 2
