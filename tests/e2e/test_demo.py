"""WP9 M5: the demo, its fictional data, and the README quickstart, through the real entry point."""
from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
EXAMPLES = REPO / "examples" / "demo-persona"
FICTIONAL = "Fictional demo persona Maya Rivera"


def _env(tmp: Path) -> dict:
    env = dict(os.environ)
    env.update(PYTHONUTF8="1", PROFILE_WRAP_CONFIG_DIR=str(tmp / "cfg"), PROFILE_WRAP_DATA_DIR=str(tmp / "data"),
               PROFILE_WRAP_HOME=str(tmp / "home"), PYTHONPATH=str(REPO))
    for key in ("PROFILE_WRAP_WORKSPACE", "PROFILE_WRAP_LINKEDIN_BASE", "PROFILE_WRAP_CLAUDE_BIN"):
        env.pop(key, None)
    return env


def _profile_wrap(args: list, env: dict, timeout: float = 400.0) -> "subprocess.CompletedProcess[str]":
    return subprocess.run([sys.executable, "-m", "profile_wrap"] + args, env=env, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout, cwd=str(REPO))


def test_quickstart_init_demo_yes_then_demo_run_exits_zero(tmp_path):
    """The two README quickstart lines, on a clean temp dir, with the fake LinkedIn and fake claude."""
    env = _env(tmp_path)
    init = _profile_wrap(["init", "--demo", "--yes", str(tmp_path / "first")], env)
    assert init.returncode == 0, init.stderr + init.stdout
    assert "demo data copied" in init.stdout
    run = _profile_wrap(["demo", "run", "--dir", str(tmp_path)], env)
    assert run.returncode == 0, run.stdout + run.stderr
    lines = run.stdout.splitlines()
    assert not [ln for ln in lines if ln.startswith("FAIL")], run.stdout
    steps = [ln for ln in lines if ln.startswith("PASS")]
    assert len(steps) >= 15
    for needle in ("init --demo --yes", "post --now to the fake LinkedIn", "fake claude: comment",
                   "fake claude: shortlist", "leaks scan --tree", "review allow"):
        assert any(needle in ln for ln in steps), needle
    # the deliberate failure is a pass of the feature, and nothing was left behind in the temp dir
    assert any("a-chart-nobody-asked-for" in ln and ln.startswith("PASS") for ln in steps)
    assert not list(tmp_path.glob("profile-wrap-demo-*")), "demo run must remove its temp folder"


def test_demo_up_and_down_start_and_stop_the_fake_server(tmp_path):
    env = _env(tmp_path)
    up = _profile_wrap(["demo", "up"], env, timeout=60)
    assert up.returncode == 0, up.stderr + up.stdout
    state = json.loads((tmp_path / "data" / "demo-server.json").read_text(encoding="utf-8"))
    assert state["base_url"].startswith("http://127.0.0.1:")
    assert _profile_wrap(["demo", "up"], env, timeout=60).returncode != 0   # one server at a time
    down = _profile_wrap(["demo", "down"], env, timeout=60)
    assert down.returncode == 0
    assert not (tmp_path / "data" / "demo-server.json").exists()
    deadline = time.time() + 10
    while time.time() < deadline and _alive(state["pid"]):
        time.sleep(0.2)
    assert not _alive(state["pid"])


def _alive(pid: int) -> bool:
    if sys.platform == "win32":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def test_fake_claude_speaks_enough_of_the_cli():
    fake = REPO / "profile_wrap" / "demo" / "fake_claude.py"
    helped = subprocess.run([sys.executable, str(fake), "--help"], capture_output=True, text=True)
    for flag in ("--max-turns", "--allowedTools", "--disallowedTools", "--permission-mode", "--print"):
        assert flag in helped.stdout
    assert subprocess.run([sys.executable, str(fake), "--version"], capture_output=True, text=True).returncode == 0


# ------------------------------------------------------------------ the fictional data

def _text_files():
    for p in sorted(EXAMPLES.rglob("*")):
        if p.is_file() and p.suffix != ".gif":
            yield p


def test_examples_are_fictional_and_carry_no_binaries_but_the_sample_gif():
    assert EXAMPLES.is_dir()
    binaries = [p.relative_to(EXAMPLES).as_posix() for p in EXAMPLES.rglob("*")
                if p.is_file() and p.suffix.lower() in {".gif", ".png", ".jpg", ".jpeg", ".woff", ".woff2",
                                                        ".ttf", ".otf", ".pdf", ".xlsx", ".zip"}]
    assert binaries == ["drafts/dashboard-three-numbers-too-many/out/sample.gif"]
    for path in _text_files():
        text = path.read_text(encoding="utf-8")
        if path.suffix in (".md",) and path.name not in ("sample.md",):
            assert "Maya Rivera" in text or "fictional" in text.lower() or "DEMO" in text, path
        assert ("O" + ":\\") not in text and ("C" + ":\\Users") not in text, path
        assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text), path


def test_persona_files_say_fictional():
    persona = json.loads((EXAMPLES / "profile" / "persona.json").read_text(encoding="utf-8"))
    assert persona["fictional"] is True and persona["demo"] is True
    assert persona["handle"] == "maya-rivera-demo" and persona["timezone"] == "Europe/Lisbon"
    assert FICTIONAL in (EXAMPLES / "profile" / "voice.md").read_text(encoding="utf-8")


def test_facts_register_has_twelve_demo_rows_in_every_status():
    text = (EXAMPLES / "research" / "facts.md").read_text(encoding="utf-8")
    rows = [ln for ln in text.splitlines() if re.match(r"\| F\d\d ", ln)]
    assert len(rows) == 12
    assert all("| yes |" in ln and "DEMO (fictional)" in ln for ln in rows)
    for status in ("verified", "draft", "do_not_use", "superseded"):
        assert any(f"| {status} |" in ln for ln in rows), status
    stats = (EXAMPLES / "research" / "stats.md").read_text(encoding="utf-8")
    assert len([ln for ln in stats.splitlines() if re.match(r"\| S\d\d ", ln)]) == 3
    assert "example.invalid" in stats


def test_calendar_has_fourteen_entries_seven_each_and_two_pairs():
    entries = json.loads((EXAMPLES / "strategy" / "calendar.json").read_text(encoding="utf-8"))["entries"]
    assert len(entries) == 14
    assert sum(e["lang"] == "en" for e in entries) == 7 and sum(e["lang"] == "ar" for e in entries) == 7
    pairs = {}
    for e in entries:
        if e.get("pair"):
            pairs.setdefault(e["pair"], set()).add(e["lang"])
    assert len(pairs) == 2 and all(v == {"en", "ar"} for v in pairs.values())


def test_every_draft_status_is_shown_once_and_the_ar_post_has_its_en_twin():
    statuses, metas = {}, {}
    for meta_file in (EXAMPLES / "drafts").glob("*/meta.json"):
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        assert meta["fictional"] is True and meta["slug"] == meta_file.parent.name
        statuses.setdefault(meta["status"], []).append(meta["slug"])
        metas[meta["slug"]] = meta
    assert set(statuses) == {"draft", "revising", "hold", "queued", "missed", "needs_check", "posted",
                             "rejected", "demo"}
    ar, en = metas["unopened-dashboard-ar"], metas["unopened-dashboard-en"]
    assert ar["pair"] == en["pair"] and ar["lang"] == "ar" and en["lang"] == "en"
    assert any(m["format"] == "slides" for m in metas.values()) and any(m["format"] == "gif" for m in metas.values())
    assert re.search(r"[\u0600-\u06FF]", (EXAMPLES / "drafts" / "unopened-dashboard-ar" / "caption.txt")
                     .read_text(encoding="utf-8"))
    assert "Fernhill Cycles" in (EXAMPLES / "drafts" / "a-chart-nobody-asked-for" / "caption.txt").read_text(encoding="utf-8")


def test_sample_gif_is_the_deterministic_output_of_the_script():
    spec = importlib.util.spec_from_file_location("make_demo_gif", REPO / "examples" / "make_demo_gif.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    gif = EXAMPLES / "drafts" / "dashboard-three-numbers-too-many" / "out" / "sample.gif"
    data = gif.read_bytes()
    assert data[:6] == b"GIF89a" and data == mod.build()
    assert data.count(b"\x21\xf9\x04") == mod.FRAMES                      # 10 frames x 0.2 s = 2 s
    assert int.from_bytes(data[6:8], "little") == 540


# ------------------------------------------------------------------ the docs

def _code_commands(text: str):
    for block in re.findall(r"```(?:bash|sh|console|powershell)?\n(.*?)```", text, re.S):
        for line in block.splitlines():
            line = line.strip().lstrip("$ ").strip()
            if line.startswith("profile-wrap "):
                yield line


@pytest.mark.parametrize("doc", ["docs/FOR-DEVELOPERS.md", "UPDATING.md"])
def test_every_profile_wrap_command_in_the_docs_exists(doc, tmp_path):
    """README quickstart commands are real: each ``profile-wrap <command>`` must parse (its --help exits 0)."""
    text = (REPO / doc).read_text(encoding="utf-8")
    commands = sorted({ln.split()[1] for ln in _code_commands(text)})
    assert commands, f"{doc} shows no profile-wrap commands"
    env = _env(tmp_path)
    for name in commands:
        proc = _profile_wrap([name, "-h"], env, timeout=60)
        assert proc.returncode == 0, f"{doc}: `profile-wrap {name}` is not a command: {proc.stderr[:200]}"


def test_readme_has_the_required_parts():
    """The front page is plain language: hero, promise, downloads, 3 steps, safety, FAQ, one developer link."""
    text = (REPO / "README.md").read_text(encoding="utf-8")
    for needle in ("docs/assets/hero.gif", "docs/assets/board.png", "Your LinkedIn, on autopilot.", "You stay the boss.",
                   "## 3 steps", "## What it does for you", "## Is it safe?", "## Questions",
                   "docs/FOR-DEVELOPERS.md", "docs/INSTALL-DESKTOP.md", "MIT", "not affiliated with or endorsed by LinkedIn"):
        assert needle in text, needle
    for os_name in ("Windows", "Mac (Apple chip)", "Mac (Intel chip)", "Linux"):
        assert re.search(r"\[[^\]]*" + re.escape(os_name) + r"\]\(https://github\.com/NJ-Burrito/profile-wrap/releases/latest\)", text), os_name
    assert text.count("not affiliated") == 1
    # four equal ways in, in this order (owner, 2026-10-17): plugin, skills, MCP server, desktop app
    anchors = [text.index(f'<a id="{a}"></a>') for a in ("plugin", "skills", "mcp", "app")]
    assert anchors == sorted(anchors)
    for needle in ("/plugin marketplace add NJ-Burrito/profile-wrap", "/plugin install profile-wrap@profile-wrap",
                   "codex plugin marketplace add NJ-Burrito/profile-wrap", ".agents/skills",
                   "claude mcp add profile-wrap -- uvx profile-wrap-mcp", "uv tool install profile-wrap"):
        assert needle in text, needle
    # below the install sections the page stays plain language: no code, no commands, no jargon
    rest = text[text.index("## 3 steps"):]
    assert "```" not in rest and "profile-wrap " not in rest
    low = rest.lower()
    for jargon in ("api", "cli", "uv", "pip", "gate", "token", "workspace", "terminal"):
        assert not re.search(r"\b" + jargon + r"\b", low), jargon
    assert "\u2014" not in text
    assert len(re.findall(r"^\*\*[^\n]*\?\*\*$", text, re.M)) <= 6


def test_developer_page_keeps_the_technical_and_safety_content():
    text = (REPO / "docs" / "FOR-DEVELOPERS.md").read_text(encoding="utf-8")
    for needle in ("profile-wrap init --demo --yes", "profile-wrap demo run", "## Quickstart", "## FAQ", "## Roadmap",
                   "## Licence", "MIT", "v0.2", "uv tool install profile-wrap", "profile-wrap-mcp", "CODEX.md"):
        assert needle in text, needle
    for needle in ("official api", "no dms", "own developer app", "no invites", "caps that config cannot raise", "kill switch"):
        assert needle in text.lower(), needle
    assert re.search(r"shields\.io|badge", text)


def test_plain_docs_explain_the_os_warnings():
    for doc in ("QUICKSTART.md", "docs/INSTALL-DESKTOP.md"):
        text = (REPO / doc).read_text(encoding="utf-8")
        assert "More info" in text and "Run anyway" in text and "Open" in text and "right-click" in text.lower(), doc
        assert "```" not in text, doc

def test_release_metadata_agrees_on_the_version():
    try:
        import tomllib
    except ImportError:          # Python 3.10
        import tomli as tomllib
    from profile_wrap import __version__ as version
    meta = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    assert meta["project"]["version"] == version and meta["project"]["readme"] == "README.md"
    include = meta["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]
    assert "brand-kit" in include and "examples" in include
    plugin = json.loads((REPO / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    market = json.loads((REPO / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
    assert plugin["version"] == version == market["plugins"][0]["version"]
    assert plugin["name"] == "profile-wrap" == market["plugins"][0]["name"]
    assert f"## [{version}]" in (REPO / "CHANGELOG.md").read_text(encoding="utf-8")


def test_ci_runs_tests_leak_scan_and_lint_on_three_operating_systems():
    text = (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    for needle in ("ubuntu-latest", "macos-latest", "windows-latest", "profile_wrap.compliance lint",
                   "profile_wrap.leakcheck scan --tree", "profile-wrap demo run", "profile-wrap init --demo --yes"):
        assert needle in text, needle
