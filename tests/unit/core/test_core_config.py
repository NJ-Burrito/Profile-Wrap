from __future__ import annotations

import copy
import json

import pytest

from njli import config, policy

from core_helpers import load_answers_fixture
from core_helpers import needs_tzdata


def cfg():
    return config.defaults("Europe/Lisbon")


def test_defaults_are_valid_and_match_the_spec():
    c = cfg()
    assert config.validate(c).ok
    assert c["posting"]["per_week"] == 3
    assert c["posting"]["min_gap_hours"] == 20
    assert c["engagement"]["comments"]["daily_cap"] == 3
    assert c["engagement"]["comments"]["like"] is False
    assert c["models"]["lead"] == {"alias": "opus", "effort": "medium"}
    assert c["posting"]["mode"] == "api_click"
    assert c["schedule"]["jobs"]["post_due"]["enabled"] is False


def test_unknown_keys_fail_at_every_depth():
    for path in ([], ["posting"], ["engagement", "comments"], ["schedule", "jobs"],
                 ["schedule", "jobs", "post_due"], ["brand", "fonts", "display"]):
        c = cfg()
        node = c
        for p in path:
            node = node[p]
        node["surprise"] = 1
        report = config.validate(c)
        assert any("surprise" in e and "unknown key" in e for e in report.errors), path


@pytest.mark.parametrize("path,value", [
    (("posting", "per_week"), 50),
    (("engagement", "comments", "daily_cap"), 50),
    (("engagement", "connect", "weekly_slots"), 6),
    (("engagement", "connect", "note_max"), 300),
    (("posting", "min_gap_hours"), 6),
])
def test_over_ceiling_values_fail_with_a_message(path, value):
    c = cfg()
    node = c
    for p in path[:-1]:
        node = node[p]
    node[path[-1]] = value
    report = config.validate(c)
    assert not report.ok
    assert any("ceiling" in e or "floor" in e for e in report.errors)


def test_type_errors_and_enums():
    c = cfg()
    c["posting"]["mode"] = "yolo"
    c["engagement"]["comments"]["like"] = "yes"
    errors = config.validate(c).errors
    assert any("posting.mode" in e for e in errors)
    assert any("like" in e for e in errors)


@needs_tzdata
def test_cross_checks():
    c = cfg()
    c["persona"]["primary_language"] = "fr"
    assert any("primary_language" in e for e in config.validate(c).errors)
    c = cfg()
    c["persona"]["pillars"] = [{"id": "P1", "name": "a", "share": 0.8},
                               {"id": "P2", "name": "b", "share": 0.8}]
    assert any("add up to" in e for e in config.validate(c).errors)
    c["persona"]["pillars"] = [{"id": "P1", "name": "a", "share": 0.3},
                               {"id": "P2", "name": "b", "share": 0.3}]
    assert any("not 1" in w for w in config.validate(c).warnings)
    c = cfg()
    c["posting"]["per_week"] = 5
    assert any("weekdays" in e for e in config.validate(c).errors)
    c = cfg()
    c["locale"]["timezone"] = "Mars/Olympus"
    assert any("IANA" in e for e in config.validate(c).errors)
    c = cfg()
    c["models"]["runner"]["auth"] = "api_key"
    assert any("api_key_env" in e for e in config.validate(c).errors)
    c = cfg()
    c["brand"]["font_source"] = "user_files"
    assert any("files is empty" in w for w in config.validate(c).warnings)


def test_modes_need_acknowledgements():
    c = cfg()
    c["posting"]["mode"] = "api_scheduled"
    assert any("api_scheduled" in e and "acknowledgement" in e for e in config.validate(c).errors)
    c = cfg()
    c["engagement"]["comments"]["mode"] = "api"
    assert any("comments_api" in e for e in config.validate(c).errors)
    c = cfg()
    c["engagement"]["reading"]["provider"] = "apify"
    assert any("apify" in e for e in config.validate(c).errors)
    c = cfg()
    c["engagement"]["comments"]["like"] = True
    assert any("like" in e for e in config.validate(c).errors)


def test_load_merges_defaults_and_split_files(make_workspace):
    ws = make_workspace()
    path = config.config_path(ws)
    raw = json.loads(path.read_text(encoding="utf-8"))
    del raw["gate"]
    path.write_text(json.dumps(raw), encoding="utf-8")
    (ws / "config" / "posting.json").write_text(json.dumps({"per_week": 4, "weekdays": [
        "mon", "tue", "thu", "fri"]}), encoding="utf-8")
    (ws / "config" / "holidays.json").write_text("{}", encoding="utf-8")  # data, not a section
    (ws / "config" / "notes.json").write_text("[]", encoding="utf-8")      # not a section either
    loaded = config.load(ws)
    assert loaded["gate"]["caption_max"] == 3000          # default restored
    assert loaded["posting"]["per_week"] == 4             # split file wins
    assert config.validate(loaded).ok


def test_load_errors(tmp_path):
    with pytest.raises(config.ConfigError, match="njli init"):
        config.load(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "njli.json").write_text("{nope", encoding="utf-8")
    with pytest.raises(config.ConfigError, match="not valid JSON"):
        config.load(tmp_path)
    (tmp_path / "config" / "njli.json").write_text("[1]", encoding="utf-8")
    with pytest.raises(config.ConfigError, match="JSON object"):
        config.load(tmp_path)
    assert not config.validate_workspace(tmp_path).ok
    (tmp_path / "config" / "njli.json").write_text("{}", encoding="utf-8")
    (tmp_path / "config" / "posting.json").write_text("{bad", encoding="utf-8")
    with pytest.raises(config.ConfigError):
        config.load(tmp_path)


def test_bom_in_config_is_tolerated(make_workspace):
    ws = make_workspace()
    path = config.config_path(ws)
    path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())
    assert config.validate_workspace(ws).ok


def test_show():
    c = cfg()
    assert config.show(c) is c
    assert config.show(c, "posting.per_week") == 3
    with pytest.raises(KeyError):
        config.show(c, "posting.nope")
    assert config.parse_value("3") == 3
    assert config.parse_value('["a"]') == ["a"]
    assert config.parse_value("plain words") == "plain words"


def test_set_value_validates_and_persists(make_workspace):
    ws = make_workspace()
    assert config.set_value(ws, "posting.per_week", "3").ok
    ok = config.set_value(ws, "posting.min_gap_hours", "24")
    assert not ok.errors or "window" in " ".join(ok.errors)  # 24h gap leaves no window: refused
    rep = config.set_value(ws, "engagement.comments.daily_cap", "50")
    assert not rep.ok and any("ceiling" in e for e in rep.errors)
    assert config.load_raw(ws)["engagement"]["comments"]["daily_cap"] == 3  # nothing persisted
    assert config.set_value(ws, "engagement.comments.daily_cap", "5").ok
    assert config.load_raw(ws)["engagement"]["comments"]["daily_cap"] == 5
    assert config.set_value(ws, "persona.role", "Staff engineer").ok
    assert config.load_raw(ws)["persona"]["role"] == "Staff engineer"
    assert any("no such config key" in e for e in config.set_value(ws, "nope.key", "1").errors)
    assert any("no such config key" in e for e in config.set_value(ws, "posting.nope", "1").errors)
    assert any("no such config key" in e for e in config.set_value(ws, "posting.mode.x", "1").errors)
    bad = config.set_value(ws, "posting.mode", "yolo")
    assert not bad.ok


def test_ack_fields_cannot_be_set_directly(make_workspace):
    ws = make_workspace()
    for key in ("posting.api_scheduled_ack", "engagement.comments.api_ack", "ack.terms_read"):
        rep = config.set_value(ws, key, '{"date": "x", "sha256": "y"}')
        assert any("only by 'njli config ack" in e for e in rep.errors)


def test_ack_records_hash_everywhere(make_workspace, plugin_root, tmp_path):
    ws = make_workspace()
    cdir = tmp_path / "ackcfg"
    with pytest.raises(ValueError, match="unknown action"):
        config.ack(ws, "bogus", policy.ACK_PHRASE, root=plugin_root)
    with pytest.raises(ValueError, match="type exactly"):
        config.ack(ws, "api_scheduled", "yes", config_dir=cdir, root=plugin_root)
    rec = config.ack(ws, "api_scheduled", f"  {policy.ACK_PHRASE} ", config_dir=cdir,
                     root=plugin_root)
    digest = config.ack_document_hash(plugin_root)
    assert rec["sha256"] == digest
    raw = config.load_raw(ws)
    assert raw["posting"]["api_scheduled_ack"]["sha256"] == digest
    stored = json.loads((cdir / "ack.json").read_text(encoding="utf-8"))
    assert stored["api_scheduled"]["sha256"] == digest
    rows = [json.loads(ln) for ln in (ws / "data" / "acks.jsonl").read_text().splitlines()]
    assert rows[-1]["action"] == "api_scheduled"
    assert config.validate(config.load(ws), ws).ok
    # two-path action
    config.ack(ws, "comments_api", policy.ACK_PHRASE, config_dir=cdir, root=plugin_root)
    raw = config.load_raw(ws)
    assert raw["engagement"]["comments"]["api_ack"] and raw["ack"]["comments_api"]
    # likes live only in ack.json
    config.ack(ws, "likes", policy.ACK_PHRASE, config_dir=cdir, root=plugin_root)
    assert "likes" in json.loads((cdir / "ack.json").read_text(encoding="utf-8"))


def test_ack_needs_the_documents(make_workspace, tmp_path):
    ws = make_workspace()
    empty = tmp_path / "noplugin"
    empty.mkdir()
    assert config.ack_document_hash(empty) is None
    with pytest.raises(ValueError, match="not found"):
        config.ack(ws, "terms_read", policy.ACK_PHRASE, root=empty)


def test_changed_risk_text_downgrades_the_action(make_workspace, plugin_root, tmp_path):
    ws = make_workspace()
    cdir = tmp_path / "ackcfg"
    config.ack(ws, "api_scheduled", policy.ACK_PHRASE, config_dir=cdir, root=plugin_root)
    config.set_value(ws, "posting.mode", "api_scheduled")
    cfg_now = config.load(ws)
    modes = config.effective_modes(cfg_now, ws, cdir, plugin_root)
    assert modes["posting"] == "api_scheduled" and modes["notes"] == []
    assert config.ack_valid(cfg_now, "api_scheduled", config_dir=cdir, root=plugin_root)
    # an update changes the shipped text
    (plugin_root / "docs" / "TERMS-AND-RISK.md").write_text("# changed\n", encoding="utf-8")
    modes = config.effective_modes(cfg_now, ws, cdir, plugin_root)
    assert modes["posting"] == "api_click"
    assert any("downgraded" in n for n in modes["notes"])
    status = config.ack_statuses(cfg_now, ws, cdir, plugin_root)
    assert status["api_scheduled"][0] == "stale"
    report = config.validate(cfg_now, ws)
    assert report.ok and any("downgraded until you accept again" in w for w in report.warnings)
    # accepting again restores it
    config.ack(ws, "api_scheduled", policy.ACK_PHRASE, config_dir=cdir, root=plugin_root)
    assert config.effective_modes(config.load(ws), ws, cdir, plugin_root)["posting"] == "api_scheduled"


def test_effective_modes_for_comments_reading_likes(make_workspace, plugin_root, tmp_path):
    ws = make_workspace()
    cdir = tmp_path / "ackcfg"
    c = config.load(ws)
    c["engagement"]["comments"]["mode"] = "api"
    c["engagement"]["reading"]["provider"] = "apify"
    c["engagement"]["comments"]["like"] = True
    modes = config.effective_modes(c, ws, cdir, plugin_root)
    assert modes["comments"] == "draft" and modes["reading"] == "manual" and modes["likes"] is False
    assert len(modes["notes"]) == 2
    # missing documents make every ack stale, never valid
    status = config.ack_statuses(
        {**c, "ack": {"terms_read": {"date": "d", "sha256": "0" * 64}, "comments_api": None,
                      "scraping_risk": None}}, ws, cdir, tmp_path / "none")
    assert status["terms_read"][0] == "stale"
    from njli import limits
    limits.pause(ws, "posting")
    assert "posting is paused" in config.effective_modes(c, ws, cdir, plugin_root)["notes"]


def test_corrupt_ack_json_is_treated_as_missing(make_workspace, plugin_root, tmp_path):
    ws = make_workspace()
    cdir = tmp_path / "ackcfg"
    cdir.mkdir()
    (cdir / "ack.json").write_text("{bad", encoding="utf-8")
    status = config.ack_statuses(config.load(ws), ws, cdir, plugin_root)
    assert status["likes"][0] == "missing"
    config.ack(ws, "likes", policy.ACK_PHRASE, config_dir=cdir, root=plugin_root)  # overwrites
    assert config.ack_statuses(config.load(ws), ws, cdir, plugin_root)["likes"][0] == "valid"


def test_write_initial_validates(tmp_path):
    bad = cfg()
    bad["posting"]["per_week"] = 99
    assert not config.write_initial(tmp_path, bad).ok
    assert not config.config_path(tmp_path).exists()
    assert config.write_initial(tmp_path, cfg()).ok
    assert config.config_path(tmp_path).exists()


def test_deep_merge_does_not_alias():
    base = {"a": {"b": [1]}}
    out = config.deep_merge(base, {"a": {"c": 2}})
    out["a"]["b"].append(2)
    assert base == {"a": {"b": [1]}}
    assert out["a"]["c"] == 2


def test_licensed_fonts_answers_become_user_files_config():
    from njli import init_wizard

    c = init_wizard.answers_to_config(load_answers_fixture("licensed_fonts.json"))
    assert c["brand"]["font_source"] == "user_files"
    assert c["brand"]["fonts"]["arabic"]["family"] == "Licensed Arabic"
    assert config.validate(c).ok
    d = copy.deepcopy(c)
    d["brand"]["fonts"]["text"]["files"] = []
    assert any("files is empty" in w for w in config.validate(d).warnings)
