from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from njli import config, handoff, init_wizard, paths, policy, scaffold, schemalite

from core_helpers import FIXTURES, REPO, load_answers_fixture

ANSWER_FILES = sorted(p.name for p in (FIXTURES / "answers").glob("*.json"))
needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def make(tmp_path, plugin_root, name, sub="ws", git=False):
    answers = load_answers_fixture(name)
    return init_wizard.init_workspace(tmp_path / sub, answers, plugin_root=plugin_root, git=git)


@pytest.mark.parametrize("name", ANSWER_FILES)
def test_each_answers_fixture_builds_a_valid_workspace(name, tmp_path, plugin_root):
    summary = make(tmp_path, plugin_root, name)
    ws = Path(summary["workspace"])
    assert config.validate_workspace(ws).ok
    assert handoff.check_file(ws / "handoff.md")[0] == []
    meta = json.loads((ws / ".njl" / "workspace.json").read_text(encoding="utf-8"))
    schema = schemalite.load_schema(REPO / "schema" / "workspace.schema.json")
    assert schemalite.validate(meta, schema) == []
    onboarding = json.loads((ws / ".njl" / "onboarding.json").read_text(encoding="utf-8"))
    assert onboarding["steps"]["who"]["status"] == "done"
    assert onboarding["steps"]["linkedin"]["status"] == "external"
    persona = json.loads((ws / "profile" / "persona.json").read_text(encoding="utf-8"))
    assert persona["name"] == load_answers_fixture(name)["who"]["name"]


def test_en_ar_fixture_lands_in_config(tmp_path, plugin_root):
    ws = Path(make(tmp_path, plugin_root, "en_ar.json")["workspace"])
    cfg = config.load(ws)
    assert cfg["persona"]["languages"] == ["en", "ar"] and cfg["persona"]["primary_language"] == "ar"
    assert cfg["posting"]["per_week"] == 5 and len(cfg["posting"]["weekdays"]) == 5
    assert cfg["posting"]["window"] == {"start": "15:00", "end": "18:29"}
    assert cfg["persona"]["style_preset"] == "adhd_emoji"
    assert cfg["locale"]["timezone"] == "Asia/Amman"
    assert cfg["locale"]["audience_regions"] == ["Gulf", "Levant"]
    claude_md = (ws / "CLAUDE.md").read_text(encoding="utf-8")
    assert "en, ar (primary: ar)" in claude_md and "adhd_emoji" in claude_md


def test_job_seeking_ofl_and_licensed_fonts(tmp_path, plugin_root):
    job = config.load(Path(make(tmp_path, plugin_root, "job_seeking.json", "a")["workspace"]))
    assert job["persona"]["goal"] == "job_seeking" and job["persona"]["style_preset"] == "impact_copy"
    ofl = config.load(Path(make(tmp_path, plugin_root, "ofl.json", "b")["workspace"]))
    assert ofl["brand"]["font_source"] == "google_ofl" and ofl["brand"]["palette"]["mode"] == "fixed"
    assert ofl["brand"]["identity"]["enabled"] and ofl["brand"]["identity"]["signature"] == "typed"
    lic = config.load(Path(make(tmp_path, plugin_root, "licensed_fonts.json", "c")["workspace"]))
    assert lic["brand"]["font_source"] == "user_files"
    assert lic["brand"]["fonts"]["display"]["files"] == ["~/fonts/LicensedDisplay-Bold.otf"]
    # the font files are references only: nothing was copied into the workspace
    assert not list((tmp_path / "c").rglob("*.otf"))


def test_scaffold_layout_matches_the_design(tmp_path, plugin_root):
    ws = Path(make(tmp_path, plugin_root, "en.json")["workspace"])
    for rel in (".njl/backup", ".njl/conflicts", "config/njli.json", "profile/exports", "research/sources",
                "strategy/weekly", "drafts/.gitkeep", "videos/.gitkeep", "brand/fonts", "published",
                "engage/inbox", "metrics/exports", "hooks/.gitkeep", "data/locks", "work/sandbox",
                "review", ".claude/agents", "CLAUDE.md", "handoff.md", "package.json",
                ".gitignore", ".gitattributes", "profile/voice.md", "profile/persona.json"):
        assert (ws / rel).exists(), rel
    pkg = json.loads((ws / "package.json").read_text(encoding="utf-8"))
    pins = json.loads((REPO / "data" / "pins.json").read_text(encoding="utf-8"))
    assert pkg["dependencies"]["hyperframes"] == pins["npm"]["hyperframes"]
    assert pkg["dependencies"]["gsap"] == pins["npm"]["gsap"]
    assert "{{" not in (ws / "package.json").read_text(encoding="utf-8")
    assert "{{" not in (ws / "CLAUDE.md").read_text(encoding="utf-8")
    assert "Jordan Sample" in (ws / "CLAUDE.md").read_text(encoding="utf-8")
    assert not any(p.suffix in (".woff", ".woff2", ".ttf", ".otf") for p in ws.rglob("*"))


def test_facts_interview_rows_become_drafts(tmp_path, plugin_root):
    ws = Path(make(tmp_path, plugin_root, "en.json")["workspace"])
    facts = (ws / "research" / "facts.md").read_text(encoding="utf-8")
    row = next(line for line in facts.splitlines() if "Closed 40 tickets in a week" in line)
    assert "| draft |" in row and "verified" not in row.lower()


def test_voice_md_uses_the_samples(tmp_path, plugin_root):
    ws = Path(make(tmp_path, plugin_root, "en.json")["workspace"])
    voice = (ws / "profile" / "voice.md").read_text(encoding="utf-8")
    assert "A short past post." in voice and "plain" in voice


@needs_git
def test_git_check_ignore_confirms_the_generated_gitignore(tmp_path, plugin_root):
    ws = Path(make(tmp_path, plugin_root, "en.json", git=True)["workspace"])
    assert (ws / ".git").is_dir()

    def ignored(rel):
        return subprocess.run(["git", "check-ignore", "-q", rel], cwd=str(ws)).returncode == 0

    must_ignore = [
        "brand/fonts/Some-Font.woff2", "brand/fonts/readme.txt", "brand/vendor/gsap/gsap.min.js",
        "sub/dir/font.ttf", "sub/font.otf", "token.json", "config/token.json", "linkedin.env",
        "apify.env", ".env", "ack.json", "engage/pending.json", "engage/inbox/post.txt",
        "published/ledger.jsonl", "published/REPORT.md", "metrics/posts.csv",
        "profile/exports/data-export.zip", "profile/voice.md", "profile/story-bank.md",
        "brand/identity/me.jpg", "brand/identity/me.png", "data/logs/runs.jsonl",
        "data/locks/x.lock", "work/PAUSE", "work/sandbox/job/x", "review/decisions.jsonl",
        ".njl/backup/20260101/CLAUDE.md", "videos/a/node_modules/x/index.js",
        "drafts/a/out/pal256.png", "drafts/a/out/x.tmp.gif",
    ]
    must_track = [
        "config/njli.json", "CLAUDE.md", "handoff.md", "research/facts.md", "drafts/a/meta.json",
        "drafts/a/caption.txt", "strategy/calendar.json", "videos/a/data/notes.json",
        "brand/identity/signature.svg", ".gitignore", "package.json", ".njl/workspace.json",
        "profile/persona.json", "review/notes.md",
    ]
    assert [r for r in must_ignore if not ignored(r)] == []
    assert [r for r in must_track if ignored(r)] == []


@needs_git
def test_wrapup_makes_a_first_commit_and_secrets_stay_out(tmp_path, plugin_root):
    answers = load_answers_fixture("en.json")
    answers["options"] = {"git_commit": True}
    summary = init_wizard.init_workspace(tmp_path / "gitws", answers, plugin_root=plugin_root)
    ws = Path(summary["workspace"])
    log = subprocess.run(["git", "log", "--oneline"], cwd=str(ws), capture_output=True, text=True)
    assert log.returncode == 0 and "initial workspace" in log.stdout
    tracked = subprocess.run(["git", "ls-files"], cwd=str(ws), capture_output=True,
                             text=True).stdout.split()
    assert "config/njli.json" in tracked and "profile/voice.md" not in tracked
    assert any("first commit made" in n for n in summary["notes"])


def test_refuses_folder_inside_the_plugin_and_non_empty_folder(tmp_path, plugin_root):
    answers = load_answers_fixture("en.json")
    with pytest.raises(paths.PathError, match="inside the plugin"):
        init_wizard.init_workspace(paths.plugin_root() / "mine", answers, plugin_root=plugin_root,
                                   git=False)
    busy = tmp_path / "busy"
    busy.mkdir()
    (busy / "file.txt").write_text("x")
    with pytest.raises(scaffold.ScaffoldError, match="not empty"):
        init_wizard.init_workspace(busy, answers, plugin_root=plugin_root, git=False)


def test_invalid_answers_are_refused_with_the_reason(tmp_path, plugin_root):
    answers = load_answers_fixture("en.json")
    answers["cadence"] = {"per_week": 9}
    with pytest.raises(init_wizard.WizardError, match="answers.schema.json"):
        init_wizard.init_workspace(tmp_path / "a", answers, plugin_root=plugin_root, git=False)
    answers = load_answers_fixture("en.json")
    answers["cadence"] = {"per_week": 3, "window": {"start": "00:00", "end": "23:00"}}
    with pytest.raises(init_wizard.WizardError, match="invalid config"):
        init_wizard.init_workspace(tmp_path / "b", answers, plugin_root=plugin_root, git=False)
    answers = load_answers_fixture("en.json")
    answers["where"] = {"profile_id": "runtime"}
    with pytest.raises(init_wizard.WizardError, match="reserved"):
        init_wizard.init_workspace(tmp_path / "c", answers, plugin_root=plugin_root, git=False)
    assert not (tmp_path / "a").exists() and not (tmp_path / "b").exists()


def test_load_answers_file_errors(tmp_path):
    with pytest.raises(init_wizard.WizardError, match="cannot read"):
        init_wizard.load_answers(tmp_path / "missing.json")
    bad = tmp_path / "bad.json"
    bad.write_text("{nope")
    with pytest.raises(init_wizard.WizardError):
        init_wizard.load_answers(bad)
    ok = init_wizard.load_answers(FIXTURES / "answers" / "en.json")
    assert ok["who"]["name"] == "Jordan Sample"


def test_preflight_blocks_only_on_python_or_claude(tmp_path, plugin_root, monkeypatch):
    pre = init_wizard.preflight(allow_no_claude=True, plugin_root=plugin_root)
    assert pre["blockers"] == []
    monkeypatch.setattr(init_wizard.shutil, "which", lambda *a, **k: None)
    monkeypatch.setattr(init_wizard.doctor.shutil, "which", lambda *a, **k: None)
    pre = init_wizard.preflight(allow_no_claude=False, plugin_root=plugin_root)
    assert [b["id"] for b in pre["blockers"]] == ["claude"]
    with pytest.raises(init_wizard.WizardError, match="preflight failed"):
        init_wizard.init_workspace(tmp_path / "x", load_answers_fixture("en.json"),
                                   plugin_root=plugin_root, git=False, require_claude=True)
    monkeypatch.setattr(init_wizard.doctor.sys, "version_info", (3, 9, 1, "final", 0))
    pre = init_wizard.preflight(allow_no_claude=True, plugin_root=plugin_root)
    assert [b["id"] for b in pre["blockers"]] == ["python"]


def test_consent_in_answers_records_hash_bound_acks(tmp_path, plugin_root):
    answers = load_answers_fixture("en.json")
    answers["consent"] = {"terms_read": policy.ACK_PHRASE}
    ws = Path(init_wizard.init_workspace(tmp_path / "c", answers, plugin_root=plugin_root,
                                         git=False)["workspace"])
    raw = config.load_raw(ws)
    assert raw["ack"]["terms_read"]["sha256"] == config.ack_document_hash(plugin_root)
    wrong = load_answers_fixture("en.json")
    wrong["consent"] = {"terms_read": "sure"}
    with pytest.raises(init_wizard.WizardError, match="consent for 'terms_read'"):
        init_wizard.init_workspace(tmp_path / "d", wrong, plugin_root=plugin_root, git=False)


def test_demo_workspace(tmp_path, plugin_root):
    summary = init_wizard.init_demo(tmp_path / "demo", plugin_root)
    ws = Path(summary["workspace"])
    cfg = config.load(ws)
    assert cfg["persona"]["demo"] is True and cfg["persona"]["name"] == "Maya Rivera"
    assert cfg["persona"]["private_terms"] == ["Fernhill Cycles"]
    assert cfg["locale"]["timezone"] == "Europe/Lisbon" and cfg["profile_id"] == "demo"
    persona = json.loads((ws / "profile" / "persona.json").read_text(encoding="utf-8"))
    assert persona["fictional"] is True
    assert "Fictional demo persona" in (ws / "profile" / "voice.md").read_text(encoding="utf-8")
    assert any("examples/demo-persona" in n for n in summary["notes"])
    # example data is copied over the workspace when the demo package exists
    examples = plugin_root / "examples" / "demo-persona" / "drafts" / "demo-post"
    examples.mkdir(parents=True)
    (examples / "meta.json").write_text("{}")
    again = init_wizard.init_demo(tmp_path / "demo2", plugin_root)
    assert (Path(again["workspace"]) / "drafts" / "demo-post" / "meta.json").is_file()


def test_demo_default_location_is_a_temp_folder(monkeypatch, tmp_path, plugin_root):
    summary = init_wizard.init_demo(plugin_root=plugin_root)
    ws = Path(summary["workspace"])
    assert "njli-demo-" in str(ws) and ws.name == "demo" and ws.is_dir()
    shutil.rmtree(ws.parent)


def test_section_reentry_updates_one_step(tmp_path, plugin_root):
    ws = Path(make(tmp_path, plugin_root, "en.json")["workspace"])
    part = {"schema_version": 1, "who": {"name": "Jordan Sample", "languages": ["en"],
                                         "goal": "authority", "role": "Staff engineer"}}
    out = init_wizard.apply_section(ws, "who", part, plugin_root)
    assert config.load_raw(ws)["persona"]["role"] == "Staff engineer"
    assert config.load_raw(ws)["locale"]["timezone"] == "America/New_York"   # kept: none given
    assert "who" in out["notes"][0]
    cad = {"schema_version": 1, "who": part["who"], "cadence": {"per_week": 4}}
    init_wizard.apply_section(ws, "cadence", cad, plugin_root)
    assert config.load(ws)["posting"]["per_week"] == 4
    voice = {"schema_version": 1, "who": part["who"],
             "voice": {"style_preset": "impact_copy", "samples": ["new sample"]}}
    init_wizard.apply_section(ws, "voice", voice, plugin_root)
    assert config.load(ws)["persona"]["style_preset"] == "impact_copy"
    assert "new sample" in (ws / "profile" / "voice.md").read_text(encoding="utf-8")
    priv = {"schema_version": 1, "who": part["who"], "privacy": {"private_terms": ["Acme"]}}
    init_wizard.apply_section(ws, "privacy", priv, plugin_root)
    assert config.load(ws)["persona"]["private_terms"] == ["Acme"]
    brand = {"schema_version": 1, "who": part["who"], "brand": {"font_source": "system"}}
    init_wizard.apply_section(ws, "brand", brand, plugin_root)
    assert config.load(ws)["brand"]["font_source"] == "system"
    models = {"schema_version": 1, "who": part["who"], "models": {"mode": "single"}}
    init_wizard.apply_section(ws, "models", models, plugin_root)
    assert config.load(ws)["models"]["mode"] == "single"
    onboarding = init_wizard.onboarding_status(ws)
    assert onboarding["steps"]["cadence"]["status"] == "done"


def test_section_reentry_errors_and_pointers(tmp_path, plugin_root):
    ws = Path(make(tmp_path, plugin_root, "en.json")["workspace"])
    base = {"schema_version": 1, "who": {"name": "x", "languages": ["en"], "goal": "authority"}}
    with pytest.raises(init_wizard.WizardError, match="unknown section"):
        init_wizard.apply_section(ws, "nope", base)
    for section in ("preflight", "wrapup", "where"):
        with pytest.raises(init_wizard.WizardError, match="cannot be re-entered"):
            init_wizard.apply_section(ws, section, base)
    bad = {**base, "cadence": {"per_week": 3, "window": {"start": "00:00", "end": "23:00"}}}
    with pytest.raises(init_wizard.WizardError, match="invalid config"):
        init_wizard.apply_section(ws, "cadence", bad)
    out = init_wizard.apply_section(ws, "scheduler", base)
    assert "schedule install" in out["notes"][0]
    facts = {**base, "facts": [{"claim": "Wrote 3 posts", "number": "3", "source": "my notes"}]}
    out = init_wizard.apply_section(ws, "facts", facts)
    assert "draft" in out["notes"][0]
    consent = {**base, "consent": {"likes": policy.ACK_PHRASE}}
    out = init_wizard.apply_section(ws, "consent", consent, plugin_root)
    assert out["notes"] == ["likes: acknowledged"]


def test_express_questions():
    replies = iter(["Pat Example", "pat-demo", "Analyst", "Reporting", "Team leads", "en, ar",
                    "clients", ""])
    answers = init_wizard.express_answers(lambda prompt: next(replies))
    assert answers["who"]["languages"] == ["en", "ar"] and answers["who"]["goal"] == "clients"
    assert init_wizard.check_answers(answers)
    replies = iter(["Pat", "", "", "", "", "", "wealth", "Europe/Lisbon"])
    answers = init_wizard.express_answers(lambda prompt: next(replies))
    assert answers["who"]["goal"] == "authority" and answers["who"]["languages"] == ["en"]
    assert answers["who"]["timezone"] == "Europe/Lisbon"
    with pytest.raises(init_wizard.WizardError, match="name is required"):
        init_wizard.express_answers(lambda prompt: "")


# ----------------------------------------------------------------- scaffold unit

def test_render_vars():
    assert scaffold.render_vars("a {{x.y}} b {{ z }}", {"x.y": "1", "z": "2"}) == "a 1 b 2"
    with pytest.raises(scaffold.ScaffoldError, match="unknown template variable"):
        scaffold.render_vars("{{missing}}", {}, source="file.md")


def test_block_helpers():
    text = "head\n<!-- njl:begin s -->\nold\n<!-- njl:end s -->\ntail\n"
    assert scaffold.extract_block(text, "s") == "<!-- njl:begin s -->\nold\n<!-- njl:end s -->"
    assert scaffold.extract_block(text, "other") is None
    out = scaffold.replace_block(text, "s", "<!-- njl:begin s -->\nnew\n<!-- njl:end s -->")
    assert out == "head\n<!-- njl:begin s -->\nnew\n<!-- njl:end s -->\ntail\n"
    appended = scaffold.replace_block("no markers\n", "s", "BLOCK")
    assert appended.endswith("BLOCK\n") and "no markers" in appended


def test_manifest_loading_and_entries(plugin_root, tmp_path):
    manifest = scaffold.load_manifest(plugin_root)
    entries = scaffold.expand_entries(manifest, plugin_root)
    dests = {e.dest for e in entries}
    assert {".gitignore", ".gitattributes", "CLAUDE.md", "package.json", "handoff.md"} <= dests
    claude = next(e for e in entries if e.dest == "CLAUDE.md")
    assert claude.block == "structural" and claude.klass == "managed"
    assert next(e for e in entries if e.dest == "handoff.md").once
    # a missing required source is an error; a missing optional one is skipped
    broken = json.loads((plugin_root / "templates" / "manifest.json").read_text(encoding="utf-8"))
    broken["files"].append({"dest": "x.md", "src": "does-not-exist.md", "class": "managed"})
    (plugin_root / "templates" / "manifest.json").write_text(json.dumps(broken), encoding="utf-8")
    with pytest.raises(scaffold.ScaffoldError, match="template source missing"):
        scaffold.expand_entries(scaffold.load_manifest(plugin_root), plugin_root)
    broken["files"][-1]["optional"] = True
    (plugin_root / "templates" / "manifest.json").write_text(json.dumps(broken), encoding="utf-8")
    assert scaffold.expand_entries(scaffold.load_manifest(plugin_root), plugin_root)
    broken["files"].append({"dest": "y", "src": "y", "class": "nonsense"})
    (plugin_root / "templates" / "manifest.json").write_text(json.dumps(broken), encoding="utf-8")
    with pytest.raises(scaffold.ScaffoldError, match="manifest.json is invalid"):
        scaffold.load_manifest(plugin_root)


def test_directory_entries_expand_per_file(plugin_root):
    (plugin_root / "prompts").mkdir()
    (plugin_root / "prompts" / "build.md").write_text("build {{x}}")
    (plugin_root / "prompts" / "__pycache__").mkdir()
    (plugin_root / "prompts" / "__pycache__" / "junk.pyc").write_text("x")
    entries = scaffold.expand_entries(scaffold.load_manifest(plugin_root), plugin_root)
    prompts = [e.dest for e in entries if e.dest.startswith("prompts/")]
    assert prompts == ["prompts/build.md"]


def test_build_context_has_every_variable_the_templates_use(plugin_root):
    cfg = config.defaults("UTC")
    cfg["persona"]["name"] = "Pat"
    ctx = scaffold.build_context(cfg, plugin_root)
    for entry in scaffold.expand_entries(scaffold.load_manifest(plugin_root), plugin_root):
        if entry.render == "vars":
            scaffold.entry_bytes(entry, ctx)          # raises on any unknown variable
    assert ctx["pin.hyperframes"] and ctx["pin.node_min"] == "22"
    assert ctx["persona.role_suffix"] == ""
    cfg["persona"]["role"] = "Analyst"
    assert scaffold.build_context(cfg, plugin_root)["persona.role_suffix"] == ", Analyst"


def test_agents_render_hook_is_used_when_present(tmp_path, plugin_root, monkeypatch):
    import sys
    import types

    calls = []
    fake = types.ModuleType("njli.agents_render")
    fake.render_all = lambda ws: calls.append(Path(ws))
    monkeypatch.setitem(sys.modules, "njli.agents_render", fake)
    summary = make(tmp_path, plugin_root, "en.json")
    assert calls == [Path(summary["workspace"])]
    assert "agents rendered" in summary["notes"]
    fake.render_all = lambda ws, cfg: calls.append(cfg)       # a different signature still works
    fake2 = types.ModuleType("njli.agents_render")
    fake2.render = lambda ws, cfg: calls.append("cfg")
    monkeypatch.setitem(sys.modules, "njli.agents_render", fake2)
    make(tmp_path, plugin_root, "en.json", "ws2")
    assert "cfg" in calls

    def explode(ws):
        raise RuntimeError("boom")

    fake2.render = explode
    out = make(tmp_path, plugin_root, "en.json", "ws3")
    assert any("render failed" in n for n in out["notes"])
    monkeypatch.setitem(sys.modules, "njli.agents_render", types.ModuleType("njli.agents_render"))
    out = make(tmp_path, plugin_root, "en.json", "ws4")
    assert any("no render function" in n for n in out["notes"])
