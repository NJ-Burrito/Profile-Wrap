from __future__ import annotations

import json
import re
import sys
import types
from pathlib import Path

import pytest

from njli import cli, handoff, policy

from core_helpers import FIXTURES, REPO, run_cli

GOOD = """# goals

- ship

## current state

- fine

## files in flight

none

## changed

none

## failed attempts

none

## next step

- go
"""


# ---------------------------------------------------------------------- handoff

def test_template_and_good_text_pass():
    assert handoff.check_text(GOOD) == ([], [])
    template = (REPO / "templates" / "handoff.template.md").read_text(encoding="utf-8")
    assert handoff.check_text(template)[0] == []


def test_missing_wrong_case_duplicate_extra_and_order():
    errors, _ = handoff.check_text(GOOD.replace("## changed\n\nnone\n\n", ""))
    assert errors == ["missing heading '## changed'"]
    errors, _ = handoff.check_text(GOOD.replace("## next step", "## Next Step"))
    assert errors == ["heading '## Next Step' must be written exactly '## next step'"]
    errors, _ = handoff.check_text(GOOD + "\n## next step\n\nmore\n")
    assert errors == ["heading '## next step' appears 2 times"]
    errors, _ = handoff.check_text(GOOD + "\n## Notes\n\nextra\n")
    assert len(errors) == 1 and "extra heading '## Notes'" in errors[0]
    swapped = GOOD.replace("## changed", "## TMP").replace("## failed attempts", "## changed") \
        .replace("## TMP", "## failed attempts")
    errors, _ = handoff.check_text(swapped)
    assert errors and "out of order" in errors[0]
    errors, _ = handoff.check_text("")
    assert len(errors) == 6


def test_sub_headings_code_fences_bom_and_crlf():
    text = GOOD.replace("- fine", "- fine\n\n### detail\n\n```\n# not a heading\n## also not\n```")
    assert handoff.check_text(text) == ([], [])
    assert handoff.check_text("﻿" + GOOD.replace("\n", "\r\n")) == ([], [])


def test_empty_sections_warn():
    errors, warnings = handoff.check_text(GOOD.replace("none\n\n## changed", "\n## changed"))
    assert errors == [] and len(warnings) == 1 and "files in flight" in warnings[0]


def test_check_file(tmp_path):
    assert "not found" in handoff.check_file(tmp_path / "nope.md")[0][0]
    f = tmp_path / "h.md"
    f.write_bytes(b"\xef\xbb\xbf" + GOOD.encode())
    assert handoff.check_file(f) == ([], [])


# -------------------------------------------------------------- CLI in process

@pytest.fixture()
def fake_root(plugin_root, monkeypatch):
    """Point the CLI at the throwaway plugin root the test workspaces were built from."""
    monkeypatch.setenv("NJLI_PLUGIN_ROOT", str(plugin_root))
    return plugin_root


def call(*argv):
    return cli.main(list(argv))


def test_no_command_prints_help_and_usage_code(capsys):
    assert call() == policy.EXIT_USAGE
    assert "usage: njli" in capsys.readouterr().out


def test_version(capsys):
    with pytest.raises(SystemExit) as exc:
        call("--version")
    assert exc.value.code == 0 and "njli" in capsys.readouterr().out


def test_config_commands(make_workspace, capsys):
    ws = make_workspace()
    assert call("config", "validate", "--workspace", str(ws)) == 0
    assert "config: valid" in capsys.readouterr().out
    assert call("config", "validate", "--workspace", str(ws), "--json") == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True
    assert call("config", "show", "posting.per_week", "--workspace", str(ws)) == 0
    assert capsys.readouterr().out.strip() == "3"
    assert call("config", "show", "posting", "--workspace", str(ws)) == 0
    assert json.loads(capsys.readouterr().out)["mode"] == "api_click"
    assert call("config", "show", "--workspace", str(ws)) == 0
    shown = json.loads(capsys.readouterr().out)
    assert "effective" in shown and shown["config"]["profile_id"] == "en-only"
    assert call("config", "show", "nope.nope", "--workspace", str(ws)) == policy.EXIT_FAIL
    assert "no such config key" in capsys.readouterr().err
    assert call("config", "set", "engagement.comments.daily_cap", "5", "--workspace", str(ws)) == 0
    assert call("config", "set", "engagement.comments.daily_cap", "50", "--workspace",
                str(ws)) == policy.EXIT_FAIL
    assert "ceiling" in capsys.readouterr().out
    assert call("config", "set", "posting.api_scheduled_ack", "{}", "--workspace", str(ws)) == policy.EXIT_FAIL


def test_config_validate_rejects_unknown_keys_and_ceilings(make_workspace, capsys):
    ws = make_workspace()
    path = ws / "config" / "njli.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["surprise"] = 1
    raw["posting"]["per_week"] = 12
    path.write_text(json.dumps(raw), encoding="utf-8")
    assert call("config", "validate", "--workspace", str(ws)) == policy.EXIT_FAIL
    out = capsys.readouterr().out
    assert "unknown key" in out
    raw.pop("surprise")
    path.write_text(json.dumps(raw), encoding="utf-8")
    assert call("config", "validate", "--workspace", str(ws), "--json") == policy.EXIT_FAIL
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is False and any("ceiling" in e for e in result["errors"])


def test_config_ack_rules(make_workspace, plugin_root, monkeypatch, capsys):
    ws = make_workspace()
    monkeypatch.setenv("NJLI_PLUGIN_ROOT", str(plugin_root))
    monkeypatch.setenv(policy.WORKER_ENV, "1")
    assert call("config", "ack", "likes", "--phrase", policy.ACK_PHRASE, "--workspace", str(ws)) == 1
    assert "agent cannot record" in capsys.readouterr().err
    monkeypatch.delenv(policy.WORKER_ENV)
    monkeypatch.setattr(cli, "_is_tty", lambda: False)
    assert call("config", "ack", "likes", "--workspace", str(ws)) == policy.EXIT_USAGE
    assert call("config", "ack", "likes", "--phrase", "ok", "--workspace", str(ws)) == policy.EXIT_FAIL
    assert "type exactly" in capsys.readouterr().err
    assert call("config", "ack", "likes", "--phrase", policy.ACK_PHRASE, "--workspace", str(ws)) == 0
    assert "acknowledged 'likes'" in capsys.readouterr().out
    monkeypatch.setattr(cli, "_is_tty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt="": policy.ACK_PHRASE)
    assert call("config", "ack", "terms_read", "--workspace", str(ws)) == 0


def test_doctor_command(make_workspace, capsys):
    ws = make_workspace()
    code = call("doctor", "--workspace", str(ws), "--os", "linux")
    out = capsys.readouterr().out
    assert code in (0, 1) and "njli doctor" in out and "linux" in out
    assert call("doctor", "--json", "--workspace", str(ws), "--os", "macos") in (0, 1)
    assert json.loads(capsys.readouterr().out)["os"] == "macos"


def test_doctor_fix_syncs_the_runtime_after_asking(make_workspace, monkeypatch, capsys):
    ws = make_workspace()
    monkeypatch.setattr(cli, "_is_tty", lambda: False)
    call("doctor", "--fix", "--workspace", str(ws), "--json")
    assert "fixed" not in json.loads(capsys.readouterr().out)         # no TTY, no --yes: not asked
    call("doctor", "--fix", "--yes", "--workspace", str(ws), "--json")
    result = json.loads(capsys.readouterr().out)
    assert result["fixed"] and result["fixed"][0].startswith("runtime now")
    runtime_check = next(c for c in result["checks"] if c["id"] == "runtime")
    assert runtime_check["status"] == "pass"


def test_runtime_commands(capsys):
    assert call("runtime", "status") == 0
    assert "no stable runtime" in capsys.readouterr().out
    assert call("runtime", "install") == 0
    assert "runtime installed" in capsys.readouterr().out
    assert call("runtime", "status", "--json") == 0
    status = json.loads(capsys.readouterr().out)
    assert status["drift"] is False and status["entry"]
    assert call("runtime", "sync") == 0
    assert "unchanged" in capsys.readouterr().out
    assert call("runtime", "sync", "--force", "--json") == 0
    assert json.loads(capsys.readouterr().out)["action"] == "installed"


def test_init_requires_something_to_do(capsys):
    assert call("init") == policy.EXIT_USAGE
    assert "setup skill" in capsys.readouterr().err


def test_init_answers_flow(tmp_path, capsys, plugin_root, monkeypatch):
    answers = FIXTURES / "answers" / "en.json"
    assert call("init", str(tmp_path / "w1"), "--answers", str(answers)) == policy.EXIT_USAGE
    assert "needs --yes" in capsys.readouterr().err
    code = call("init", str(tmp_path / "w1"), "--answers", str(answers), "--yes", "--no-git", "--json")
    assert code == 0
    summary = json.loads(capsys.readouterr().out)
    assert Path(summary["workspace"]) == tmp_path / "w1"
    assert call("init", str(tmp_path / "w1"), "--answers", str(answers), "--yes",
                "--no-git") == policy.EXIT_FAIL                                  # not empty now
    assert "not empty" in capsys.readouterr().err
    assert call("init", str(tmp_path / "w2"), "--answers", str(tmp_path / "nope.json"),
                "--yes") == policy.EXIT_FAIL
    capsys.readouterr()
    assert call("init", str(tmp_path / "w3"), "--answers", str(answers), "--yes", "--no-git",
                "--profile", "other") == 0
    cfg = json.loads((tmp_path / "w3" / "config" / "njli.json").read_text(encoding="utf-8"))
    assert cfg["profile_id"] == "other"


def test_init_section_flow(make_workspace, tmp_path, capsys):
    ws = make_workspace()
    assert call("init", "--section", "who", "--workspace", str(ws)) == policy.EXIT_USAGE
    capsys.readouterr()
    part = tmp_path / "part.json"
    part.write_text(json.dumps({"schema_version": 1, "who": {
        "name": "Jordan Sample", "languages": ["en"], "goal": "authority", "role": "Lead"}}))
    assert call("init", "--section", "who", "--answers", str(part), "--workspace", str(ws)) == 0
    assert json.loads((ws / "config" / "njli.json").read_text(encoding="utf-8"))[
        "persona"]["role"] == "Lead"


def test_init_demo_flow(tmp_path, capsys):
    assert call("init", "--demo", str(tmp_path / "d")) == 0
    out = capsys.readouterr().out
    assert "workspace:" in out and "next: njli doctor" in out
    assert call("config", "validate", "--workspace", str(tmp_path / "d")) == 0


def test_init_express_in_a_terminal(tmp_path, monkeypatch, capsys):
    replies = iter(["Pat Example", "pat-demo", "Analyst", "Reporting", "Leads", "en", "authority",
                    "Europe/Lisbon"])
    monkeypatch.setattr(cli, "_is_tty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(replies))
    monkeypatch.setattr(cli.init_wizard.doctor, "run", lambda **k: {
        "summary": {"fail": 0, "warn": 0, "pass": 1, "skip": 0}, "checks": []})
    assert call("init", str(tmp_path / "ex"), "--express", "--no-git") == 0
    assert (tmp_path / "ex" / "config" / "njli.json").is_file()


def test_upgrade_commands(fake_root, make_workspace, capsys):
    ws = make_workspace()
    assert call("upgrade", "--check", "--workspace", str(ws)) == 0
    assert re.search(r"summary: \d+ unchanged", capsys.readouterr().out)
    assert call("upgrade", "--apply", "--json", "--workspace", str(ws)) == 0
    assert json.loads(capsys.readouterr().out)["conflicts"] == []
    (ws / ".gitignore").write_text("# mine\n", encoding="utf-8")
    assert call("upgrade", "--dry-run", "--workspace", str(ws)) == 0
    assert call("upgrade", "--resolve", "--mine", "--workspace", str(ws)) == 0
    assert call("upgrade", "--resolve", "--theirs", "--workspace", str(ws)) == 0


def test_upgrade_exit_3_on_conflict(fake_root, make_workspace, monkeypatch, capsys):
    ws = make_workspace()
    meta_path = ws / ".njl" / "workspace.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["files"][".gitignore"]["sha256"] = "0" * 64        # base differs from both sides
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    (ws / ".gitignore").write_text("# mine\n", encoding="utf-8")
    assert call("upgrade", "--apply", "--workspace", str(ws)) == policy.EXIT_CONFLICT
    assert (ws / ".gitignore.new").exists()


def test_upgrade_outside_a_workspace(tmp_path, capsys):
    assert call("upgrade", "--check", "--workspace", str(tmp_path)) == policy.EXIT_FAIL
    assert "not an nj-linkedin workspace" in capsys.readouterr().err


def test_migrate_command(fake_root, make_workspace, capsys):
    ws = make_workspace()
    assert call("migrate", "--workspace", str(ws)) == 0
    assert "nothing to migrate" in capsys.readouterr().out
    meta_path = ws / ".njl" / "workspace.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["applied_migrations"] = []
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    raw = json.loads((ws / "config" / "njli.json").read_text(encoding="utf-8"))
    del raw["persona"]["style_preset"]
    (ws / "config" / "njli.json").write_text(json.dumps(raw), encoding="utf-8")
    assert call("migrate", "--dry-run", "--workspace", str(ws)) == 0
    assert "would apply 0001_style_preset" in capsys.readouterr().out
    assert call("migrate", "--workspace", str(ws), "--json") == 0
    assert json.loads(capsys.readouterr().out)["applied"] == ["0001_style_preset"]
    assert call("migrate", "--workspace", str(ws)) == 0


def test_migrate_reports_a_pending_confirmation(fake_root, make_workspace, monkeypatch, capsys):
    ws = make_workspace()
    outcome = types.SimpleNamespace(
        applied=[], noop=[], planned=[], backup=None, exit_code=policy.EXIT_CONFLICT,
        pending_confirmation={"id": "0200_x", "description": "d", "changes": ["c"],
                              "touches_policy": True})
    monkeypatch.setattr(cli.migration_runner, "run", lambda *a, **k: outcome)
    assert call("migrate", "--workspace", str(ws)) == policy.EXIT_CONFLICT
    assert "needs your confirmation" in capsys.readouterr().out


def test_handoff_command(make_workspace, tmp_path, capsys):
    ws = make_workspace()
    assert call("handoff", "check", "--workspace", str(ws)) == 0
    assert "handoff: ok" in capsys.readouterr().out
    bad = tmp_path / "bad.md"
    bad.write_text("# goals\n\n## changed\n")
    assert call("handoff", "check", str(bad)) == policy.EXIT_FAIL
    out = capsys.readouterr().out
    assert "missing heading '## current state'" in out
    assert call("handoff", "check", str(bad), "--json") == policy.EXIT_FAIL
    assert json.loads(capsys.readouterr().out)["ok"] is False


def test_pause_and_resume(make_workspace, capsys):
    ws = make_workspace()
    assert call("pause", "--posting", "--workspace", str(ws), "--reason", "holiday") == 0
    assert (ws / "work" / "PAUSE.posting").exists()
    assert call("pause", "--workspace", str(ws)) == 0
    assert (ws / "work" / "PAUSE").exists()
    capsys.readouterr()
    assert call("resume", "--workspace", str(ws)) == 0
    assert "PAUSE" in capsys.readouterr().out and not (ws / "work" / "PAUSE").exists()
    assert call("pause", "--comments", "--workspace", str(ws)) == 0
    assert call("resume", "--comments", "--workspace", str(ws)) == 0
    assert call("resume", "--workspace", str(ws)) == 0
    assert "nothing was paused" in capsys.readouterr().out


def test_workspace_resolution(make_workspace, monkeypatch, tmp_path):
    ws = make_workspace()
    monkeypatch.chdir(ws / "drafts")
    import argparse

    assert cli.resolve_workspace(argparse.Namespace(workspace=None, profile=None)) == ws.resolve()
    monkeypatch.chdir(tmp_path)
    resolved = cli.resolve_workspace(argparse.Namespace(workspace=None, profile="abc"))
    assert resolved.name == "abc"


def test_errors_are_one_line_not_tracebacks(tmp_path, capsys):
    code = call("config", "validate", "--workspace", str(tmp_path / "nowhere"))
    assert code == policy.EXIT_FAIL
    assert "njli init" in capsys.readouterr().out
    plugin = Path(cli.paths.plugin_root())
    assert call("config", "show", "--workspace", str(plugin / "inside")) == policy.EXIT_FAIL
    assert "inside the plugin" in capsys.readouterr().err


def test_keyboard_interrupt(monkeypatch, capsys):
    def interrupted(args):
        raise KeyboardInterrupt

    parser_main = cli.build_parser

    def patched():
        parser = parser_main()
        for action in parser._subparsers._group_actions:
            action.choices["pause"].set_defaults(func=interrupted)
        return parser

    monkeypatch.setattr(cli, "build_parser", patched)
    assert call("pause") == policy.EXIT_FAIL
    assert "interrupted" in capsys.readouterr().err


# ---------------------------------------------------------- extension loading

def test_extension_registration_conventions(monkeypatch, capsys):
    calls = []

    ext_pkg = types.ModuleType("njli.zeta")
    ext_mod = types.ModuleType("njli.zeta.cli_ext")

    def register(sub):
        calls.append("zeta")
        p = sub.add_parser("zeta", help="a command added by an extension")
        p.set_defaults(func=lambda a: 7)

    ext_mod.register = register
    solo = types.ModuleType("njli.solo")
    solo.register = lambda sub: (calls.append("solo"), sub.add_parser("solo").set_defaults(
        func=lambda a: 9))
    broken = types.ModuleType("njli.broken")

    def boom(sub):
        raise RuntimeError("register failed")

    broken.register = boom
    no_register = types.ModuleType("njli.noreg")
    monkeypatch.setitem(sys.modules, "njli.zeta", ext_pkg)
    monkeypatch.setitem(sys.modules, "njli.zeta.cli_ext", ext_mod)
    monkeypatch.setitem(sys.modules, "njli.solo", solo)
    monkeypatch.setitem(sys.modules, "njli.broken", broken)
    monkeypatch.setitem(sys.modules, "njli.noreg", no_register)
    monkeypatch.setattr(cli, "EXTENSIONS", ("zeta", "solo", "broken", "noreg", "absent"))
    assert call("zeta") == 7
    assert call("solo") == 9
    assert sorted(calls) == ["solo", "solo", "zeta", "zeta"]
    err = capsys.readouterr().err
    assert "extension 'broken' could not be loaded" in err and "register failed" in err
    assert "absent" not in err                       # a package that is not installed is silent


def test_a_broken_extension_import_is_reported_but_does_not_stop_the_core(monkeypatch, capsys):
    real = cli.importlib.import_module

    def fake(name, *a, **k):
        if name.startswith("njli.explodes"):
            raise ModuleNotFoundError("No module named 'numpy'", name="numpy")
        if name.startswith("njli.crashes"):
            raise RuntimeError("syntax problem inside the extension")
        return real(name, *a, **k)

    monkeypatch.setattr(cli.importlib, "import_module", fake)
    monkeypatch.setattr(cli, "EXTENSIONS", ("explodes", "crashes"))
    parser = cli.build_parser()
    err = capsys.readouterr().err
    assert "extension 'explodes' could not be loaded: No module named 'numpy'" in err
    assert "extension 'crashes' could not be loaded" in err
    assert parser.parse_args(["pause"]).command == "pause"          # the core still works


def test_core_pause_defers_to_an_extension_that_registers_it(monkeypatch, make_workspace):
    ws = make_workspace()
    ext = types.ModuleType("njli.schedule")
    ext_cli = types.ModuleType("njli.schedule.cli_ext")

    def register(sub):
        sub.add_parser("pause").set_defaults(func=lambda a: 42)

    ext_cli.register = register
    monkeypatch.setitem(sys.modules, "njli.schedule", ext)
    monkeypatch.setitem(sys.modules, "njli.schedule.cli_ext", ext_cli)
    monkeypatch.setattr(cli, "EXTENSIONS", ("schedule",))
    assert call("pause") == 42
    assert not (ws / "work" / "PAUSE").exists()
    monkeypatch.setattr(cli, "EXTENSIONS", ())
    assert call("pause", "--workspace", str(ws)) == 0
    assert (ws / "work" / "PAUSE").exists()


# ------------------------------------------------------------ real entry point

def test_entry_smoke_real_process_doctor_json():
    result = run_cli("doctor", "--json", "--os", "linux")
    assert result.returncode in (0, 1), result.stderr
    doc = json.loads(result.stdout)
    assert doc["os"] == "linux" and doc["schema_version"] == 1


def test_entry_smoke_init_demo_then_validate(tmp_path):
    target = tmp_path / "smoke demo"                     # a path with a space
    result = run_cli("init", "--demo", str(target), "--no-git")
    assert result.returncode == 0, result.stderr
    check = run_cli("config", "validate", "--workspace", str(target))
    assert check.returncode == 0, check.stdout + check.stderr
    handoff_check = run_cli("handoff", "check", "--workspace", str(target))
    assert handoff_check.returncode == 0
    bad = run_cli("config", "set", "posting.per_week", "99", "--workspace", str(target))
    assert bad.returncode == policy.EXIT_FAIL and "ceiling" in bad.stdout
