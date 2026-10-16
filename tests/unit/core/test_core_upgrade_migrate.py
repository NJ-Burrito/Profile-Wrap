from __future__ import annotations

import json
from pathlib import Path

import pytest

from njli import config, policy, scaffold, upgrade
from njli.migrations import runner

from core_helpers import load_answers_fixture


@pytest.fixture()
def v1(tmp_path, plugin_root):
    """A workspace scaffolded from the v1 templates (the plugin_root copy), plus that root."""
    from njli import init_wizard

    summary = init_wizard.init_workspace(tmp_path / "ws", load_answers_fixture("en.json"),
                                         plugin_root=plugin_root, git=False)
    return Path(summary["workspace"]), plugin_root


def edit(path: Path, fn):
    path.write_text(fn(path.read_text(encoding="utf-8")), encoding="utf-8", newline="\n")


def actions(result):
    return {a.dest: a.action for a in result.actions}


def test_unchanged_templates_change_nothing(v1):
    ws, root = v1
    result = upgrade.apply(ws, root)
    assert set(actions(result).values()) == {"unchanged"}
    assert result.exit_code == 0 and result.conflicts == [] and result.backup is None


def test_three_way_overwrite_keep_and_new_conflict(v1):
    ws, root = v1
    # v2 templates: three files change
    edit(root / "templates" / "workspace" / "gitignore", lambda t: t + "/extra-v2/\n")
    edit(root / "templates" / "workspace" / "gitattributes", lambda t: t + "*.svg text\n")
    edit(root / "templates" / "workspace" / "package.json",
         lambda t: t.replace('"private": true,', '"private": true,\n  "license": "MIT",'))
    # the user edits: gitattributes (template also changed -> conflict is for package.json only)
    edit(ws / "package.json", lambda t: t.replace('"type": "module",', '"type": "module",\n  "x": 1,'))
    (ws / "voice-notes.txt").write_text("mine")
    before_voice = (ws / "profile" / "voice.md").read_text(encoding="utf-8")

    preview = upgrade.check(ws, root)
    assert actions(preview)[".gitignore"] == "overwrite"
    assert actions(preview)["package.json"] == "conflict"
    assert not (ws / "package.json.new").exists()                  # dry run writes nothing
    assert "extra-v2" not in (ws / ".gitignore").read_text(encoding="utf-8")

    result = upgrade.apply(ws, root)
    got = actions(result)
    assert got[".gitignore"] == "overwrite"       # untouched by the user, template changed
    assert got[".gitattributes"] == "overwrite"
    assert got["package.json"] == "conflict"      # both changed
    assert got["CLAUDE.md"] == "unchanged"
    assert result.exit_code == policy.EXIT_CONFLICT
    assert "/extra-v2/" in (ws / ".gitignore").read_text(encoding="utf-8")
    # the user's package.json is kept, and the new template sits beside it
    assert '"x": 1' in (ws / "package.json").read_text(encoding="utf-8")
    assert '"license": "MIT"' in (ws / "package.json.new").read_text(encoding="utf-8")
    assert [c["dest"] for c in result.conflicts] == ["package.json"]
    assert "package.json (yours)" in result.conflicts[0]["diff"]
    # the overwritten file was backed up first
    assert result.backup and (Path(result.backup) / ".gitignore").is_file()
    assert "/extra-v2/" not in (Path(result.backup) / ".gitignore").read_text(encoding="utf-8")
    # user data was never touched
    assert (ws / "profile" / "voice.md").read_text(encoding="utf-8") == before_voice
    assert (ws / "voice-notes.txt").read_text() == "mine"
    summary = upgrade.render_summary(result)
    assert "conflict(s)" in summary and "upgrade --resolve" in summary
    assert json.loads(upgrade.conflicts_json(result))[0]["dest"] == "package.json"


def test_user_edit_with_unchanged_template_is_kept(v1):
    ws, root = v1
    edit(ws / ".gitattributes", lambda t: t + "# mine\n")
    result = upgrade.apply(ws, root)
    assert actions(result)[".gitattributes"] == "keep"
    assert result.exit_code == 0
    assert "# mine" in (ws / ".gitattributes").read_text(encoding="utf-8")


def test_upgrade_is_idempotent(v1):
    ws, root = v1
    edit(root / "templates" / "workspace" / "gitignore", lambda t: t + "/extra-v2/\n")
    first = upgrade.apply(ws, root)
    assert actions(first)[".gitignore"] == "overwrite"
    second = upgrade.apply(ws, root)
    assert set(actions(second).values()) == {"unchanged"}
    assert second.backup is None


def test_claude_md_block_is_managed_and_preferences_are_not(v1):
    ws, root = v1
    mine = (ws / "CLAUDE.md").read_text(encoding="utf-8").rstrip("\n") + "\n- My own rule: no puns.\n"
    (ws / "CLAUDE.md").write_text(mine, encoding="utf-8", newline="\n")
    edit(root / "templates" / "CLAUDE.template.md",
         lambda t: t.replace("- Deletions go to the recycle bin or trash, never `rm -rf`.",
                             "- Deletions go to the recycle bin or trash, never `rm -rf`.\n- New v2 rule."))
    result = upgrade.apply(ws, root)
    assert actions(result)["CLAUDE.md"] == "overwrite"
    text = (ws / "CLAUDE.md").read_text(encoding="utf-8")
    assert "- New v2 rule." in text and "My own rule: no puns." in text
    assert text.count("njl:begin structural") == 1
    # editing the block yourself and then getting a new block is a conflict
    edit(ws / "CLAUDE.md", lambda t: t.replace("- New v2 rule.", "- My changed rule."))
    edit(root / "templates" / "CLAUDE.template.md", lambda t: t.replace("- New v2 rule.", ""))
    edit(root / "templates" / "CLAUDE.template.md",
         lambda t: t.replace("never `rm -rf`.", "never `rm -rf`.\n- Another v3 rule."))
    result = upgrade.apply(ws, root)
    assert actions(result)["CLAUDE.md"] == "conflict"
    assert "- My changed rule." in (ws / "CLAUDE.md").read_text(encoding="utf-8")
    assert "- Another v3 rule." in (ws / "CLAUDE.md.new").read_text(encoding="utf-8")


def test_new_managed_file_is_created_and_seeded_deletions_are_respected(v1):
    ws, root = v1
    manifest_path = root / "templates" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"].append({"dest": "NOTES-v2.md", "src": "v2-notes.md", "class": "managed"})
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (root / "templates" / "v2-notes.md").write_text("# v2 notes for {{persona.name}}\n")
    manifest["files"][-1]["render"] = "vars"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (ws / "package.json").unlink()                       # the user deleted a seeded file
    (ws / ".gitattributes").unlink()                     # ...and a managed one
    result = upgrade.apply(ws, root)
    got = actions(result)
    assert got["NOTES-v2.md"] == "create"
    assert (ws / "NOTES-v2.md").read_text(encoding="utf-8") == "# v2 notes for Jordan Sample\n"
    assert got["package.json"] == "skip_deleted" and not (ws / "package.json").exists()
    assert got[".gitattributes"] == "create" and (ws / ".gitattributes").exists()
    meta = json.loads((ws / ".njl" / "workspace.json").read_text(encoding="utf-8"))
    assert "NOTES-v2.md" in meta["files"]


def test_untracked_existing_file_is_adopted_or_conflicts(v1):
    ws, root = v1
    meta_path = ws / ".njl" / "workspace.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    del meta["files"][".gitignore"], meta["files"][".gitattributes"]
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    edit(ws / ".gitattributes", lambda t: t + "# local\n")
    result = upgrade.apply(ws, root)
    got = actions(result)
    assert got[".gitignore"] == "adopt"          # identical to the template: just recorded
    assert got[".gitattributes"] == "conflict"   # unknown base and different: never overwrite
    assert (ws / ".gitattributes.new").exists()


def test_converged_edit_is_adopted(v1):
    ws, root = v1
    edit(root / "templates" / "workspace" / "gitignore", lambda t: t + "/extra-v2/\n")
    edit(ws / ".gitignore", lambda t: t + "/extra-v2/\n")        # the user made the same change
    result = upgrade.apply(ws, root)
    assert actions(result)[".gitignore"] == "adopt"
    assert upgrade.apply(ws, root).conflicts == []


def conflicted(v1):
    ws, root = v1
    edit(root / "templates" / "workspace" / "package.json",
         lambda t: t.replace('"private": true,', '"private": true,\n  "license": "MIT",'))
    edit(ws / "package.json", lambda t: t.replace('"type": "module",', '"type": "module",\n  "x": 1,'))
    assert upgrade.apply(ws, root).exit_code == policy.EXIT_CONFLICT
    return ws, root


def test_resolve_after_merging_by_hand(v1):
    ws, root = conflicted(v1)
    pending = upgrade.resolve(ws, root)
    assert pending.exit_code == policy.EXIT_CONFLICT          # the .new file is still there
    assert upgrade.apply(ws, root).exit_code == policy.EXIT_CONFLICT   # and it stays until resolved
    (ws / "package.json.new").unlink()                         # the user merged and removed it
    done = upgrade.resolve(ws, root)
    assert done.exit_code == 0 and actions(done) == {"package.json": "resolved_manual"}
    assert upgrade.apply(ws, root).exit_code == 0
    assert '"x": 1' in (ws / "package.json").read_text(encoding="utf-8")
    assert not list((ws / ".njl" / "conflicts").glob("*.json"))


def test_resolve_keep_mine(v1):
    ws, root = conflicted(v1)
    result = upgrade.resolve(ws, root, mode="mine")
    assert actions(result) == {"package.json": "resolved_mine"} and result.exit_code == 0
    assert '"x": 1' in (ws / "package.json").read_text(encoding="utf-8")
    assert not (ws / "package.json.new").exists()
    assert upgrade.apply(ws, root).exit_code == 0


def test_resolve_take_theirs(v1):
    ws, root = conflicted(v1)
    result = upgrade.resolve(ws, root, mode="theirs")
    assert actions(result) == {"package.json": "resolved_theirs"}
    text = (ws / "package.json").read_text(encoding="utf-8")
    assert '"license": "MIT"' in text and '"x": 1' not in text
    assert result.backup and (Path(result.backup) / "package.json").is_file()
    assert upgrade.apply(ws, root).exit_code == 0
    with pytest.raises(ValueError):
        upgrade.resolve(ws, root, mode="ours")


def test_resolve_when_the_template_dropped_the_file(v1):
    ws, root = conflicted(v1)
    manifest_path = root / "templates" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"] = [f for f in manifest["files"] if f["dest"] != "package.json"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    result = upgrade.resolve(ws, root)
    assert result.exit_code == 0 and not (ws / "package.json.new").exists()


def test_pending_migrations_are_reported(v1):
    ws, root = v1
    meta_path = ws / ".njl" / "workspace.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["applied_migrations"] = []
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    result = upgrade.apply(ws, root)
    assert result.pending_migrations >= 1
    assert "njli migrate" in upgrade.render_summary(result)


def test_not_a_workspace(tmp_path, plugin_root):
    with pytest.raises(scaffold.ScaffoldError, match="not an nj-linkedin workspace"):
        upgrade.check(tmp_path, plugin_root)


def test_workspace_meta_records_versions(v1):
    ws, root = v1
    manifest_path = root / "templates" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["template_version"] = "2"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    upgrade.apply(ws, root)
    meta = json.loads((ws / ".njl" / "workspace.json").read_text(encoding="utf-8"))
    assert meta["template_version"] == "2"


# ------------------------------------------------------------------- migrations

def write_migration(folder: Path, name: str, body: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(body, encoding="utf-8")


POLICY_MIGRATION = '''
DESCRIPTION = "lower the comment cap to 2"
TOUCHES_POLICY = True
FILES = ["config/njli.json"]

def plan(ctx):
    cfg = ctx.config_raw()
    if cfg["engagement"]["comments"]["daily_cap"] != 2:
        return ["engagement.comments.daily_cap: %s -> 2" % cfg["engagement"]["comments"]["daily_cap"]]
    return []

def apply(ctx):
    cfg = ctx.config_raw()
    cfg["engagement"]["comments"]["daily_cap"] = 2
    cfg["engagement"]["comments"]["reply_reserve"] = 1
    ctx.save_config(cfg)
'''

PLAIN_MIGRATION = '''
DESCRIPTION = "add a note"

def plan(ctx):
    return [] if "migrated" in ctx.config_raw()["persona"]["role"] else ["role gets a suffix"]

def apply(ctx):
    cfg = ctx.config_raw()
    cfg["persona"]["role"] += " (migrated)"
    ctx.save_config(cfg)
'''


def test_shipped_migration_is_idempotent_and_dry_runnable(v1):
    ws, _ = v1
    raw = config.load_raw(ws)
    del raw["persona"]["style_preset"]
    config.config_path(ws).write_text(json.dumps(raw), encoding="utf-8")
    meta_path = ws / ".njl" / "workspace.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["applied_migrations"] = []
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    dry = runner.run(ws, dry_run=True)
    assert [p["id"] for p in dry.planned] == ["0001_style_preset"] and dry.applied == []
    assert "style_preset" not in config.load_raw(ws)["persona"]
    assert json.loads(meta_path.read_text(encoding="utf-8"))["applied_migrations"] == []

    first = runner.run(ws)
    assert first.applied == ["0001_style_preset"] and first.exit_code == 0
    assert config.load_raw(ws)["persona"]["style_preset"] == "plain"
    assert first.backup and (Path(first.backup) / "config" / "njli.json").is_file()
    second = runner.run(ws)
    assert second.applied == [] and second.noop == [] and second.backup is None
    # forgetting the bookkeeping does not double-apply: plan() sees nothing to do
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["applied_migrations"] = []
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    third = runner.run(ws)
    assert third.applied == [] and third.noop == ["0001_style_preset"]


def test_policy_touching_migration_asks_and_shows_the_diff(v1, tmp_path):
    ws, _ = v1
    folder = tmp_path / "migs"
    write_migration(folder, "0100_lower_cap.py", POLICY_MIGRATION)
    write_migration(folder, "0101_plain.py", PLAIN_MIGRATION)
    items = runner.discover(folder)
    assert [m.id for m in items] == ["0100_lower_cap", "0101_plain"]
    assert items[0].touches_policy and not items[1].touches_policy

    asked = []
    refused = runner.run(ws, items, ask=lambda prompt: asked.append(prompt) or False)
    assert refused.exit_code == policy.EXIT_CONFLICT and refused.applied == []
    assert refused.pending_confirmation["id"] == "0100_lower_cap"
    assert "engagement.comments.daily_cap: 3 -> 2" in asked[0] and "safety setting" in asked[0]
    assert config.load_raw(ws)["engagement"]["comments"]["daily_cap"] == 3   # nothing changed
    assert "(migrated)" not in config.load_raw(ws)["persona"]["role"]          # order is kept

    no_ask = runner.run(ws, items)                      # no way to ask: refuse
    assert no_ask.exit_code == policy.EXIT_CONFLICT

    approved = runner.run(ws, items, ask=lambda prompt: True)
    assert approved.applied == ["0100_lower_cap", "0101_plain"] and approved.exit_code == 0
    cfg = config.load_raw(ws)
    assert cfg["engagement"]["comments"]["daily_cap"] == 2 and "(migrated)" in cfg["persona"]["role"]
    assert config.validate(config.load(ws)).ok
    assert runner.run(ws, items).applied == []                                  # idempotent


def test_assume_yes_confirms_policy_migrations(v1, tmp_path):
    ws, _ = v1
    folder = tmp_path / "migs"
    write_migration(folder, "0100_lower_cap.py", POLICY_MIGRATION)
    out = runner.run(ws, runner.discover(folder), assume_yes=True)
    assert out.applied == ["0100_lower_cap"]


def test_dry_run_changes_nothing_even_for_policy_migrations(v1, tmp_path):
    ws, _ = v1
    folder = tmp_path / "migs"
    write_migration(folder, "0100_lower_cap.py", POLICY_MIGRATION)
    out = runner.run(ws, runner.discover(folder), dry_run=True)
    assert out.planned[0]["touches_policy"] is True and out.exit_code == 0
    assert config.load_raw(ws)["engagement"]["comments"]["daily_cap"] == 3


def test_discover_ignores_files_that_are_not_migrations(tmp_path):
    folder = tmp_path / "migs"
    write_migration(folder, "README.md", "x")
    write_migration(folder, "helper.py", "x = 1")
    write_migration(folder, "0005_ok.py", PLAIN_MIGRATION)
    assert [m.id for m in runner.discover(folder)] == ["0005_ok"]


def test_new_workspaces_start_with_every_migration_applied(v1):
    ws, _ = v1
    meta = json.loads((ws / ".njl" / "workspace.json").read_text(encoding="utf-8"))
    assert "0001_style_preset" in meta["applied_migrations"]
