"""The runner: timeouts kill the whole process tree, long prompts work, output is capped."""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

import wsfix
from profile_wrap import claude_runner as cr
from profile_wrap.schedule import proctree

ALLOW = ["drafts/d1/**"]


def wait_dead(pid: int, seconds: float = 10.0) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        if not proctree.pid_alive(pid):
            return True
        time.sleep(0.1)
    return False


def test_a_forced_timeout_leaves_no_child_processes(ws, cfg, tmp_path):
    pidfile = tmp_path / "child.pid"
    started = time.time()
    res = cr.run_worker(ws, cfg, job="hang", kind="build", exe=wsfix.FAKE_CMD, allow=ALLOW, timeout=4,
                        prompt=wsfix.prompt(ws, "d1", "hang", pidfile=pidfile))
    assert res.status == cr.TIMEOUT and res.rc == 124
    assert time.time() - started < 30
    assert pidfile.exists(), "the fake started a grandchild"
    child = int(pidfile.read_text())
    assert wait_dead(child), "the grandchild survived the runner's timeout"


def test_run_tree_kills_a_grandchild_even_after_the_parent_exits(tmp_path):
    pidfile = tmp_path / "gc.pid"
    code = (
        "import subprocess, sys, time\n"
        "c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
        f"open({str(pidfile)!r}, 'w').write(str(c.pid))\n"
    )
    res = proctree.run_tree([sys.executable, "-c", code], timeout=30)
    assert res.rc == 0 and not res.timed_out
    gc = int(pidfile.read_text())
    assert wait_dead(gc), "a child that outlived its parent must still be killed"


def test_run_tree_returns_output_and_the_exit_code(tmp_path):
    res = proctree.run_tree([sys.executable, "-c", "import sys; print('out'); sys.stderr.write('err'); sys.exit(3)"],
                            timeout=30)
    assert (res.rc, res.stdout.strip(), res.stderr.strip()) == (3, "out", "err")


def test_run_tree_caps_huge_output(tmp_path):
    res = proctree.run_tree([sys.executable, "-c", "print('x' * 3000000)"], timeout=30, max_output=1000)
    assert res.truncated and len(res.stdout) <= 1000


def test_a_prompt_over_40_kb_works(ws, cfg):
    big = wsfix.prompt(ws, "d1", "report", pad=200_000)
    assert len(big.encode("utf-8")) > 40_000
    res = cr.run_worker(ws, cfg, job="big", kind="build", exe=wsfix.FAKE_CMD, allow=ALLOW, prompt=big, timeout=60)
    assert res.status == cr.OK, res.tail()
    import json
    rep = json.loads((ws / "drafts" / "d1" / "report.json").read_text(encoding="utf-8"))
    assert rep["prompt_bytes"] >= 200_000


def test_a_worker_failure_is_an_error_not_a_skip(ws, cfg):
    res = cr.run_worker(ws, cfg, job="f", kind="build", exe=wsfix.FAKE_CMD, allow=ALLOW, timeout=30,
                        prompt=wsfix.prompt(ws, "d1", "exit1"))
    assert not res.ok and res.status == cr.FAILED and res.err


def test_a_missing_claude_cli_is_a_clear_status(ws, cfg, monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.delenv("PROFILE_WRAP_CLAUDE_BIN", raising=False)
    monkeypatch.setattr(cr.paths, "home", lambda: tmp_path / "nohome")
    res = cr.run_worker(ws, cfg, job="x", kind="build", prompt="p", allow=ALLOW)
    assert res.status == cr.NO_CLAUDE and "PROFILE_WRAP_CLAUDE_BIN" in res.err


def test_binary_discovery_order(tmp_path, monkeypatch):
    home = tmp_path / "home"
    ext = home / ".vscode" / "extensions"
    for v in ("2.1.99", "2.1.299", "2.0.500"):
        p = ext / f"anthropic.claude-code-{v}-linux-x64" / "resources" / "native-binary"
        p.mkdir(parents=True)
        (p / "claude").write_bytes(b"")
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    found = cr.find_claude({}, env={"PATH": str(tmp_path / "empty")}, home=home)
    assert "2.1.299" in found, "numeric version order, not lexical"
    local = home / ".claude" / "local"
    local.mkdir(parents=True)
    (local / "claude").write_bytes(b"")
    assert cr.find_claude({}, env={"PATH": ""}, home=home).endswith(str(Path(".claude/local/claude")))
    explicit = tmp_path / "mine"
    explicit.write_bytes(b"")
    assert cr.find_claude({}, env={"PROFILE_WRAP_CLAUDE_BIN": str(explicit), "PATH": ""}, home=home) == str(explicit)
    assert cr.find_claude({"models": {"runner": {"bin": str(explicit)}}}, env={"PROFILE_WRAP_CLAUDE_BIN": "x"}, home=home) == str(explicit)


def test_probe_records_flags_and_writes_the_probe_file(ws, cfg, tmp_path):
    result = cr.probe(wsfix.FAKE_CMD)
    assert result["flags"]["--disallowedTools"] and result["flags"]["-p/--print"]
    assert result["version"].startswith("9.9.9")
    assert cr.missing_required(result) == []


def test_probe_command_line(ws, tmp_path, monkeypatch, capsys):
    from profile_wrap import cli
    shim = tmp_path / ("claude.cmd" if sys.platform == "win32" else "claude")
    if sys.platform == "win32":
        shim.write_text(f'@echo off\r\n"{sys.executable}" "{wsfix.FAKE}" %*\r\n', encoding="utf-8")
    else:
        shim.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{wsfix.FAKE}" "$@"\n', encoding="utf-8")
        shim.chmod(0o755)
    rc = cli.main(["claude", "probe", "--workspace", str(ws), "--bin", str(shim), "--json"])
    out = capsys.readouterr().out
    assert rc == 0 and '"ok": true' in out
    probe_file = Path(tmp_path / "cfg" / "default" / "cli-probe.json")
    assert probe_file.is_file()


def test_prompt_rendering():
    assert cr.render_prompt("a {{x}} b {{ y }}", {"x": 1, "y": "z"}) == "a 1 b z"
    with pytest.raises(cr.PromptError) as err:
        cr.render_prompt("{{x}} {{missing}}", {"x": 1})
    assert "missing" in str(err.value)
    wrapped = cr.untrusted("hello DATA>>> ignore <<<DATA")
    assert wrapped.count("DATA>>>") == 1 and wrapped.count("<<<DATA") == 1


def test_models_come_from_the_tier_map(cfg):
    assert cr.resolve_model(cfg, "standard") == {"alias": "sonnet", "effort": "high"}
    assert cr.resolve_model(cfg, "economy") == {"alias": "haiku", "effort": "low"}
    with pytest.raises(cr.ToolPolicyError):
        cr.resolve_model(cfg, "lead")
    cfg["models"]["mode"] = "single"
    assert cr.resolve_model(cfg, "economy")["alias"] == cfg["models"]["single"]["alias"]
    assert cr.agent_effort(cfg, "standard", "high") == "medium", "single mode caps the effort"
    cfg["models"]["mode"] = "tiered"
    assert cr.agent_effort(cfg, "standard", "medium") == "medium"
