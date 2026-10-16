"""Sandbox containment against the hostile ``fake_claude`` behaviours (design-spec section 14)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runner"))
import wsfix  # noqa: E402

from profile_wrap import claude_runner as cr  # noqa: E402

ALLOW = ["drafts/d1/**"]
EXPECT = ["drafts/d1/caption.txt", "drafts/d1/meta.json"]


def run(ws, cfg, *behaviours, expect=EXPECT, **kw):
    return cr.run_worker(ws, cfg, job="hostile", kind="build", exe=wsfix.FAKE_CMD, allow=ALLOW,
                         expect=expect, prompt=wsfix.prompt(ws, "d1", *behaviours), timeout=60, **kw)


def test_a_clean_worker_passes_and_writes_only_its_files(ws, cfg):
    before = wsfix.tree_state(ws)
    res = run(ws, cfg, "ok")
    assert res.status == cr.OK, res.tail()
    assert res.changed == ["drafts/d1/caption.txt", "drafts/d1/meta.json"]
    after = wsfix.tree_state(ws)
    assert {k for k in after if k not in before} == {"drafts/d1/caption.txt", "drafts/d1/meta.json"}
    assert not (ws / "work" / "sandbox" / "hostile").exists(), "the sandbox dir is removed"


@pytest.mark.parametrize("behaviour,path,kind", [
    ("edit_facts", "research/facts.md", "rewrote"),
    ("edit_other_draft", "drafts/other/caption.txt", "rewrote"),
    ("delete_file", "profile/voice.md", "recreated"),
    ("add_script", "scripts/evil.py", "deleted new"),
    ("git_config", ".git/config", "rewrote"),
    ("git_hook", ".git/hooks/pre-commit", "deleted new"),
])
def test_everything_outside_the_allowlist_is_reverted_and_logged(ws, cfg, behaviour, path, kind):
    before = wsfix.tree_state(ws)
    res = run(ws, cfg, "ok", behaviour)
    assert res.status == cr.OK, res.tail()
    assert any(line.startswith("RESTORED") and kind in line and path in line for line in res.restored), res.restored
    after = wsfix.tree_state(ws)
    # the git hook is not in tree_state's walk filter, so compare the other files byte for byte
    for rel, data in before.items():
        assert after.get(rel) == data, rel
    assert not (ws / ".git" / "hooks" / "pre-commit").exists()
    assert not (ws / "scripts" / "evil.py").exists()


def test_a_new_folder_outside_the_allowlist_disappears(ws, cfg):
    res = run(ws, cfg, "ok", "new_dir")
    assert res.status == cr.OK
    assert not (ws / "stash").exists()
    assert any("stash" in line for line in res.restored)


def test_all_hostile_edits_at_once(ws, cfg):
    before = wsfix.tree_state(ws)
    res = run(ws, cfg, "ok", "edit_facts", "add_script", "edit_other_draft", "delete_file",
              "new_dir", "git_config", "git_hook")
    assert res.status == cr.OK
    assert len(res.restored) >= 7
    assert {k: v for k, v in wsfix.tree_state(ws).items() if k in before} == before


def test_prompt_injection_in_the_output_is_flagged_not_obeyed(ws, cfg):
    before = wsfix.tree_state(ws)
    res = run(ws, cfg, "ok", "inject")
    assert res.status == cr.OK
    assert res.injection, "the marker is reported"
    assert "verified" in res.text  # the text is returned as data
    assert wsfix.tree_state(ws).get("research/facts.md") == before["research/facts.md"]


@pytest.mark.parametrize("behaviour", ["token_stdout", "secret_assign"])
def test_a_secret_shaped_string_in_the_output_fails_the_job(ws, cfg, behaviour):
    res = run(ws, cfg, "ok", behaviour)
    assert res.status == cr.SECRET_OUTPUT
    assert not res.ok and res.rc == 5
    assert res.findings and all("..." in f.excerpt for f in res.findings), "findings are masked"
    assert "AQV" not in res.text and "Abc123" not in res.text
    assert not (ws / "drafts" / "d1" / "caption.txt").exists(), "the output files are discarded too"
    assert res.changed == []


def test_a_secret_shaped_string_in_a_written_file_fails_the_job(ws, cfg):
    res = run(ws, cfg, "token_file")
    assert res.status == cr.SECRET_OUTPUT
    assert any(f.where == "drafts/d1/caption.txt" for f in res.findings)
    assert not (ws / "drafts" / "d1" / "caption.txt").exists()


def test_secret_shaped_stderr_is_redacted_in_the_result(ws, cfg, tmp_path):
    from profile_wrap.sandbox import scan_secrets
    token = "AQV" + "x9" * 60
    assert scan_secrets(token)
    assert "[REDACTED]" in cr.redact("log line " + token)


def test_a_symlink_in_the_allowlist_is_removed(ws, cfg):
    res = run(ws, cfg, "ok", "symlink")
    link = ws / "drafts" / "d1" / "link.txt"
    if not link.exists() and not link.is_symlink():
        if "link.txt" in " ".join(res.changed + res.restored):
            pytest.fail("link reported but missing")
    assert not link.is_symlink()
    assert res.status in (cr.OK,)


def test_a_changed_file_too_large_to_copy_aside_is_unrestorable(ws, cfg, monkeypatch):
    from profile_wrap import sandbox
    big = ws / "brand" / "big.bin"
    big.parent.mkdir(parents=True, exist_ok=True)
    big.write_bytes(b"0" * 4096)
    monkeypatch.setattr(sandbox, "MAX_COPY_BYTES", 1024)
    monkeypatch.setattr(sandbox, "take", lambda root, max_copy=1024, _t=sandbox.take: _t(root, 1024))
    # a worker that rewrites the big file: use the facts file route by pointing the behaviour at it
    f = ws / "research" / "facts.md"
    f.write_bytes(b"x" * 4096)
    res = run(ws, cfg, "ok", "edit_facts")
    assert res.status == cr.GUARD_FAILED
    assert any("research/facts.md" in u for u in res.unrestorable)


def test_the_environment_is_scrubbed_and_the_prompt_is_not_in_argv(ws, cfg, monkeypatch):
    monkeypatch.setenv("LINKEDIN_CLIENT_SECRET", "must-not-reach-the-worker")
    monkeypatch.setenv("GITHUB_TOKEN", "must-not-reach-the-worker")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-not-reach-the-worker")
    res = run(ws, cfg, "report")
    assert res.status == cr.OK, res.tail()
    import json
    rep = json.loads((ws / "drafts" / "d1" / "report.json").read_text(encoding="utf-8"))
    env = {k.upper() for k in rep["env"]}
    assert "LINKEDIN_CLIENT_SECRET" not in env and "GITHUB_TOKEN" not in env
    assert "ANTHROPIC_API_KEY" not in env
    assert "PYTHONUTF8" in env and "PROFILE_WRAP_WORKER" in env
    joined = " ".join(rep["argv"])
    assert "ROOT:" not in joined and "FAKE:" not in joined, "the prompt travels on stdin"
    assert Path(rep["cwd"]).resolve() == (ws / "work" / "sandbox" / "hostile").resolve()


def test_api_key_mode_passes_only_the_named_key(ws, cfg, monkeypatch):
    cfg["models"]["runner"].update({"auth": "api_key", "api_key_env": "MY_KEY_VAR"})
    monkeypatch.setenv("MY_KEY_VAR", "k-123")
    env = cr.scrub_env(cfg)
    assert env["ANTHROPIC_API_KEY"] == "k-123" and "MY_KEY_VAR" not in env


def test_flags_reach_the_cli_as_specified(ws, cfg):
    res = run(ws, cfg, "report")
    argv = res.argv
    assert argv[argv.index("--permission-mode") + 1] == "dontAsk"
    assert "Bash" in argv[argv.index("--disallowedTools") + 1].split(",")
    assert argv[argv.index("--allowedTools") + 1] == "Read,Glob,Grep,Write"
    assert "-p" in argv and "--max-turns" in argv


def test_a_missing_required_flag_fails_closed(ws, cfg, tmp_path):
    fake = tmp_path / "fake_claude.py"
    fake.write_text((wsfix.FAKE).read_text(encoding="utf-8"), encoding="utf-8")
    fake.with_suffix(".missing").write_text("--disallowedTools\n", encoding="utf-8")
    res = cr.run_worker(ws, cfg, job="hostile", kind="build", exe=[sys.executable, str(fake)], allow=ALLOW,
                        prompt=wsfix.prompt(ws, "d1", "ok"), timeout=30)
    assert res.status == cr.UNSUPPORTED_FLAGS and "--disallowedTools" in res.err
    assert not res.ran and not (ws / "drafts" / "d1" / "caption.txt").exists()


def test_a_failing_worker_is_an_error_with_stderr(ws, cfg):
    res = run(ws, cfg, "exit1")
    assert res.status == cr.FAILED and res.rc == 1 and "boom" in res.err


def test_an_error_result_inside_json_is_a_failure(ws, cfg):
    res = run(ws, cfg, "is_error")
    assert res.status == cr.FAILED and "error_max_turns" in res.err


def test_missing_expected_output_is_reported(ws, cfg):
    res = run(ws, cfg, "no_output")
    assert res.status == cr.MISSING_OUTPUT and res.rc == 3
    assert set(res.missing) == set(EXPECT)


def test_a_stale_file_does_not_count_as_output(ws, cfg):
    old = ws / "drafts" / "d1" / "caption.txt"
    old.write_text("old\n", encoding="utf-8")
    os.utime(old, (1_000_000_000, 1_000_000_000))
    res = run(ws, cfg, "no_output", expect=["drafts/d1/caption.txt"])
    assert res.status == cr.MISSING_OUTPUT


def test_unknown_kind_and_forbidden_tools_are_refused_before_anything_runs(ws, cfg):
    res = cr.run_worker(ws, cfg, job="x", kind="nope", prompt="p", allow=ALLOW, exe=wsfix.FAKE_CMD)
    assert res.status == cr.BAD_ARGS
    for tools in (["Read", "Bash"], ["Read", "Agent"], ["Read", "Edit"], ["Read", "WebFetch"]):
        res = cr.run_worker(ws, cfg, job="x", kind="build", prompt="p", allow=ALLOW, exe=wsfix.FAKE_CMD,
                            tools=tools)
        assert res.status == cr.BAD_ARGS and not res.ran, tools


def test_a_worker_must_have_an_allowlist(ws, cfg):
    res = cr.run_worker(ws, cfg, job="x", kind="build", prompt="p", allow=[], exe=wsfix.FAKE_CMD)
    assert res.status == cr.BAD_ARGS


def test_every_kind_gets_the_right_tools():
    for kind, spec in cr.KINDS.items():
        tools = cr.validate_tools(kind, spec["tools"])
        assert "Bash" not in tools and "Agent" not in tools
        assert ("Edit" in tools) == (kind in cr.EDIT_KINDS)
        assert ("WebFetch" in tools) == (kind in cr.WEB_KINDS)
        denied = cr.disallowed_for(kind)
        assert "Bash" in denied and not set(tools) & set(denied)


def test_the_board_adapter_shape(ws, cfg):
    res = cr.run_job(wsfix.prompt(ws, "d1", "ok"), name="improve-d1", tools="Read,Glob,Grep,Edit,Write",
                     root=ws, allow=[ws / "drafts" / "d1"], expect=ws / "drafts" / "d1" / "caption.txt",
                     timeout=60, cfg=cfg, exe=wsfix.FAKE_CMD)
    assert res.rc == 0 and res.error == "" and res.status == cr.OK
    bad = cr.run_job("p", name="x", tools="Read,Bash", root=ws, allow=[ws / "drafts" / "d1"], cfg=cfg,
                     exe=wsfix.FAKE_CMD)
    assert bad.rc == 2 and "Bash" in bad.error


def test_dry_run_starts_nothing(ws, cfg):
    res = cr.run_worker(ws, cfg, job="x", kind="build", prompt="p", allow=ALLOW, dry_run=True,
                        exe=["definitely-not-a-program"])
    assert res.status == cr.DRY_RUN and res.ok and not res.ran
    assert not (ws / "work" / "sandbox" / "x").exists()


def test_the_run_is_logged_without_the_prompt(ws, cfg):
    run(ws, cfg, "ok")
    log = (ws / "data" / "logs" / "runner.jsonl").read_text(encoding="utf-8")
    assert '"job":"hostile"' in log and "ROOT:" not in log
