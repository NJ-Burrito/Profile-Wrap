"""First run lands in copy mode; existing workspaces keep the mode they have."""
from __future__ import annotations

import json
from pathlib import Path

from onboard_helpers import FIRST_RUN_ANSWERS

from profile_wrap import cli, config, i18n, init_wizard, policy


def test_a_new_workspace_starts_in_copy_mode(first_run_ws):
    cfg = config.load(first_run_ws)
    assert cfg["posting"]["mode"] == "copy"
    assert config.effective_modes(cfg, first_run_ws)["posting"] == "copy"
    assert config.validate_workspace(first_run_ws).ok


def test_the_init_summary_names_the_mode_and_points_at_copy_in_both_languages(tmp_path):
    summary = init_wizard.init_workspace(tmp_path / "w", json.loads(json.dumps(FIRST_RUN_ANSWERS)), git=False)
    assert summary["posting_mode"] == "copy"
    nxt = "\n".join(summary["next"])
    assert i18n.t("init.next.copy", "en") in nxt and i18n.t("init.next.copy", "ar") in nxt
    assert "profile-wrap copy" in nxt and "No LinkedIn developer app" in nxt


def test_init_through_the_cli_answers_flow_is_copy_mode(tmp_path, capsys):
    answers = tmp_path / "a.json"
    answers.write_text(json.dumps(FIRST_RUN_ANSWERS), encoding="utf-8")
    code = cli.main(["init", "--answers", str(answers), "--yes", "--no-git", "--workspace", str(tmp_path / "cli-ws"), "--json"])
    out = capsys.readouterr().out
    assert code == policy.EXIT_OK
    assert json.loads(out[out.index("{"):])["posting_mode"] == "copy"
    assert config.load(tmp_path / "cli-ws")["posting"]["mode"] == "copy"


def test_the_demo_keeps_the_click_mode_because_it_posts_to_a_fake_linkedin(tmp_path):
    summary = init_wizard.init_workspace(tmp_path / "demo", init_wizard.DEMO_ANSWERS, git=False)
    assert summary["posting_mode"] == "api_click"
    assert config.load(Path(summary["workspace"]))["posting"]["mode"] == "api_click"


def test_the_library_default_is_unchanged_so_nothing_is_migrated_silently():
    assert config.defaults()["posting"]["mode"] == "api_click"


def test_an_existing_workspace_with_no_mode_stored_keeps_the_old_default(first_run_ws):
    path = config.config_path(first_run_ws)
    raw = json.loads(path.read_text(encoding="utf-8"))
    del raw["posting"]["mode"]
    path.write_text(json.dumps(raw), encoding="utf-8")
    assert config.load(first_run_ws)["posting"]["mode"] == "api_click"


def test_an_existing_api_click_workspace_stays_api_click_after_a_section_edit(first_run_ws):
    config.set_value(first_run_ws, "posting.mode", '"api_click"')
    init_wizard.apply_section(first_run_ws, "cadence", dict(FIRST_RUN_ANSWERS, cadence={"per_week": 4}))
    cfg = config.load(first_run_ws)
    assert cfg["posting"]["per_week"] == 4 and cfg["posting"]["mode"] == "api_click"


def test_copy_mode_needs_no_token_and_the_post_command_still_refuses_to_send(first_run_ws):
    from profile_wrap.linkedin import post
    from onboard_helpers import gate_pass, make_draft

    make_draft(first_run_ws, "d1")
    out = post.publish(first_run_ws, "d1", config.load(first_run_ws), gate_fn=gate_pass, require_status=None)
    assert out.status != "posted" and "copy" in out.reason
