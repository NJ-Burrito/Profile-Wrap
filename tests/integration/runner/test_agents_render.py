"""Agent templates: validation, rendering with the tier map, and the no-shell rule."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from njli import agents_render as ar
from njli import cli, config
from njli import claude_runner as cr

ROOT = Path(__file__).resolve().parents[3]
STANDING = "Never run a shell command.\n"


def template(name="crew-demo", tier="economy", effort="low", tools="Read, Glob, Grep, Write", denied="Bash, Agent",
             body="Do the thing.\n\n<!-- include: _standing-rules.md -->\n", extra=""):
    return (f'---\nname: {name}\ndescription: "A demo, with a: colon"\ntier: {tier}\neffort: {effort}\n'
            f"tools: {tools}\ndisallowedTools: {denied}\n{extra}---\n\n{body}")


@pytest.fixture()
def tdir(tmp_path):
    d = tmp_path / "agents"
    d.mkdir()
    (d / "_standing-rules.md").write_text(STANDING, encoding="utf-8")
    (d / "crew-demo.md").write_text(template(), encoding="utf-8")
    (d / "council-demo.md").write_text(template("council-demo", "standard", "high"), encoding="utf-8")
    (d / "researcher-demo.md").write_text(
        template("researcher-demo", "standard", "medium", tools="Read, Glob, Grep, Write, WebSearch, WebFetch"), encoding="utf-8")
    return d


def cfg():
    return config.defaults("UTC")


def test_render_maps_tier_to_model_and_keeps_the_per_agent_effort(tdir, tmp_path):
    ws = tmp_path / "ws"
    rep = ar.render_all(ws, cfg(), templates_dir=tdir)
    assert rep.ok and {i.name for i in rep.items} == {"crew-demo", "council-demo", "researcher-demo"}
    crew = (ws / ".claude" / "agents" / "crew-demo.md").read_text(encoding="utf-8")
    assert "model: haiku" in crew and "effort: low" in crew and "tier:" not in crew
    council = (ws / ".claude" / "agents" / "council-demo.md").read_text(encoding="utf-8")
    assert "model: sonnet" in council and "effort: high" in council
    researcher = (ws / ".claude" / "agents" / "researcher-demo.md").read_text(encoding="utf-8")
    assert "effort: medium" in researcher, "a researcher keeps medium although the standard tier default is high"


def test_the_standing_rules_replace_the_marker_exactly_once(tdir, tmp_path):
    ws = tmp_path / "ws"
    ar.render_all(ws, cfg(), templates_dir=tdir)
    text = (ws / ".claude" / "agents" / "crew-demo.md").read_text(encoding="utf-8")
    assert "<!-- include" not in text
    assert text.count("## Standing rules") == 1 and STANDING.strip() in text
    assert ar.GENERATED_MARK in text


def test_frontmatter_is_valid_yaml_shape_and_the_description_survives_colons(tdir, tmp_path):
    ws = tmp_path / "ws"
    ar.render_all(ws, cfg(), templates_dir=tdir)
    text = (ws / ".claude" / "agents" / "crew-demo.md").read_text(encoding="utf-8")
    head = text.split("---\n")[1]
    keys = [ln.split(":", 1)[0] for ln in head.splitlines()]
    assert keys == ["name", "description", "model", "effort", "tools", "disallowedTools"]
    desc = [ln for ln in head.splitlines() if ln.startswith("description:")][0].split(":", 1)[1].strip()
    assert json.loads(desc) == "A demo, with a: colon"


def test_single_mode_maps_everything_to_one_model_and_caps_effort(tdir, tmp_path):
    c = cfg()
    c["models"]["mode"] = "single"
    c["models"]["single"] = {"alias": "sonnet", "effort": "medium"}
    ws = tmp_path / "ws"
    ar.render_all(ws, c, templates_dir=tdir)
    for name, effort in (("crew-demo", "low"), ("council-demo", "medium"), ("researcher-demo", "medium")):
        text = (ws / ".claude" / "agents" / f"{name}.md").read_text(encoding="utf-8")
        assert "model: sonnet" in text and f"effort: {effort}" in text, name


def test_changing_the_tier_map_changes_the_rendered_model_without_touching_a_template(tdir, tmp_path):
    c = cfg()
    c["models"]["economy"]["alias"] = "my-small-model"
    ws = tmp_path / "ws"
    ar.render_all(ws, c, templates_dir=tdir)
    assert "model: my-small-model" in (ws / ".claude" / "agents" / "crew-demo.md").read_text(encoding="utf-8")


def test_render_is_idempotent_and_dry_run_writes_nothing(tdir, tmp_path):
    ws = tmp_path / "ws"
    dry = ar.render_all(ws, cfg(), templates_dir=tdir, dry_run=True)
    assert {i.status for i in dry.items} == {"would-write"} and not (ws / ".claude").exists()
    first = ar.render_all(ws, cfg(), templates_dir=tdir)
    second = ar.render_all(ws, cfg(), templates_dir=tdir)
    assert {i.status for i in first.items} == {"written"} and {i.status for i in second.items} == {"unchanged"}
    assert ar.check(ws, cfg(), templates_dir=tdir) == []
    (ws / ".claude" / "agents" / "crew-demo.md").write_text("changed by hand\n" + ar.GENERATED_MARK, encoding="utf-8")
    assert ar.check(ws, cfg(), templates_dir=tdir) == ["crew-demo"]


def test_a_hand_written_agent_is_never_overwritten_without_force(tdir, tmp_path):
    ws = tmp_path / "ws"
    mine = ws / ".claude" / "agents" / "crew-demo.md"
    mine.parent.mkdir(parents=True)
    mine.write_text("my own agent\n", encoding="utf-8")
    rep = ar.render_all(ws, cfg(), templates_dir=tdir)
    assert not rep.ok and [i.status for i in rep.items if i.name == "crew-demo"] == ["refused"]
    assert mine.read_text(encoding="utf-8") == "my own agent\n"
    ar.render_all(ws, cfg(), templates_dir=tdir, force=True)
    assert ar.GENERATED_MARK in mine.read_text(encoding="utf-8")


@pytest.mark.parametrize("bad,fragment", [
    (dict(tools="Read, Bash"), "never allowed"),
    (dict(tools="Read, Agent"), "never allowed"),
    (dict(denied="Agent"), "disallowedTools must list Bash"),
    (dict(tier="lead"), "tier must be one of"),
    (dict(effort="max"), "effort must be one of"),
    (dict(extra="model: opus\n"), "must not name a model"),
    (dict(tools="Read, WebSearch"), "only researchers have web tools"),
    (dict(tools="Read, Edit", name="council-x"), "only crew agents may use Edit"),
    (dict(tools="Read, Edit, Bash", denied="Bash"), "overlap"),
    (dict(body="No include here.\n"), "include _standing-rules.md exactly once"),
    (dict(body="<!-- include: _standing-rules.md -->\n<!-- include: _standing-rules.md -->\n"), "exactly once"),
])
def test_bad_templates_are_rejected_with_a_reason(tdir, tmp_path, bad, fragment):
    name = bad.get("name", "crew-demo")
    (tdir / f"{name}.md").write_text(template(**bad), encoding="utf-8")
    rep = ar.render_all(tmp_path / "ws", cfg(), templates_dir=tdir)
    assert not rep.ok and any(fragment in p for p in rep.problems), rep.problems
    assert not (tmp_path / "ws" / ".claude").exists(), "nothing is written when a template is invalid"


def test_a_seat_may_not_have_edit_or_web(tdir, tmp_path):
    (tdir / "council-demo.md").write_text(template("council-demo", "standard", "high", tools="Read, Write, WebFetch"), encoding="utf-8")
    rep = ar.render_all(tmp_path / "ws", cfg(), templates_dir=tdir)
    assert any("only researchers have web tools" in p or "council seat may use only" in p for p in rep.problems)


def test_a_malformed_template_is_a_clear_error():
    with pytest.raises(ar.AgentError):
        ar.parse_template("no frontmatter\n", Path("x.md"))
    with pytest.raises(ar.AgentError):
        ar.parse_template("---\nname: x\nno close\n", Path("x.md"))


def test_the_shipped_templates_obey_every_rule():
    """Whatever agents the package ships right now (the other work packages add theirs) must pass."""
    templates, standing = ar.load_templates(ROOT / "agents")
    assert templates, "agents/ has templates"
    names = {t.name for t in templates}
    assert {"crew-writer", "council-editor", "council-language-voice"} <= names
    problems = [p for t in templates for p in ar.validate_template(t)]
    assert problems == []
    for t in templates:
        text, info = ar.render_agent(t, cfg(), standing)
        assert "## Standing rules" in text and "include:" not in text
        assert "Bash" not in info["tools"].split(", "), f"{t.name} must have no shell"


def test_no_content_worker_has_bash_in_any_shipped_agent_or_job_kind():
    templates, _ = ar.load_templates(ROOT / "agents")
    for t in templates:
        tools = {x.strip() for x in t.meta["tools"].split(",")}
        assert not tools & ar.NEVER_TOOLS, t.name
        assert "Bash" in {x.strip() for x in t.meta["disallowedTools"].split(",")}, t.name
    for kind in cr.KINDS:
        assert "Bash" not in cr.tools_for(kind) and "Bash" in cr.disallowed_for(kind)


def test_the_standing_rules_cover_the_required_points():
    text = (ROOT / "agents" / "_standing-rules.md").read_text(encoding="utf-8").lower()
    for needle in ("sign in to linkedin", "never post, comment, react or connect", "only the files your brief names",
                   "at most 25 lines", "amend:", "never escalate your own tier", "data", "focus", "single-writer"):
        assert needle in text, needle
    for heading in ("status", "finding", "evidence", "files-symbols", "risk", "next action"):
        assert heading in text


def test_command_line(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("NJLI_CONFIG_DIR", str(tmp_path / "cfg"))
    ws = tmp_path / "ws"
    ws.mkdir()
    assert cli.main(["agents", "list"]) == 0
    assert cli.main(["agents", "render", "--workspace", str(ws), "--check"]) == 1, "nothing rendered yet"
    assert cli.main(["agents", "render", "--workspace", str(ws)]) == 0
    capsys.readouterr()
    assert cli.main(["agents", "render", "--workspace", str(ws), "--check"]) == 0
    files = sorted(p.name for p in (ws / ".claude" / "agents").glob("*.md"))
    assert "crew-writer.md" in files and not any(f.startswith("_") for f in files)


def test_scaffold_calls_render_all(tmp_path):
    """njli.scaffold looks for render_all(workspace) or render(workspace, cfg) on this module."""
    ws = tmp_path / "ws"
    ws.mkdir()
    ar.render_all(ws)
    assert (ws / ".claude" / "agents" / "council-editor.md").is_file()


def test_build_agents_tool(tmp_path, capsys):
    import importlib.util
    spec = importlib.util.spec_from_file_location("build_agents", ROOT / "tools" / "build_agents.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.main(["--check"]) == 0
    assert "PASS" in capsys.readouterr().out
    assert mod.main(["--out", str(tmp_path / "out"), "--single"]) == 0
    out = (tmp_path / "out" / "council-editor.md").read_text(encoding="utf-8")
    assert "model: sonnet" in out
    assert mod.main(["--table"]) == 0
    assert "| Agent | Tier | Effort | Tools |" in capsys.readouterr().out
