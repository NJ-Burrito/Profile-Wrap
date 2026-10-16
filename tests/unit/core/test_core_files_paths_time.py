from __future__ import annotations

import datetime as dt
import json
import os
import sys

import pytest

from profile_wrap import atomic, fsutil, notify, paths, tzutil
from core_helpers import needs_tzdata


# ---------------------------------------------------------------- atomic / fsutil

def test_atomic_write_replaces_and_leaves_no_temp(tmp_path):
    target = tmp_path / "sub" / "f.txt"
    atomic.atomic_write_text(target, "one\n")
    atomic.atomic_write_text(target, "two\n")
    assert target.read_text(encoding="utf-8") == "two\n"
    assert [p.name for p in target.parent.iterdir()] == ["f.txt"]
    atomic.atomic_write_json(tmp_path / "j.json", {"a": "é"})
    assert json.loads((tmp_path / "j.json").read_text(encoding="utf-8")) == {"a": "é"}
    assert b"\r\n" not in (tmp_path / "j.json").read_bytes()


def test_atomic_write_failure_keeps_old_file_and_cleans_up(tmp_path, monkeypatch):
    target = tmp_path / "f.txt"
    target.write_text("old", encoding="utf-8")

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(atomic.os, "replace", boom)
    with pytest.raises(OSError):
        atomic.atomic_write_text(target, "new")
    assert target.read_text(encoding="utf-8") == "old"
    assert [p.name for p in tmp_path.iterdir()] == ["f.txt"]


def test_hashes(tmp_path):
    f = tmp_path / "x.bin"
    f.write_bytes(b"abc")
    assert fsutil.sha256_file(f) == fsutil.sha256_bytes(b"abc") == fsutil.sha256_text("abc")


def test_read_json_bom_and_default(tmp_path):
    f = tmp_path / "b.json"
    f.write_bytes(b"\xef\xbb\xbf" + b'{"a": 1}')
    assert fsutil.read_json(f) == {"a": 1}
    assert fsutil.read_json(tmp_path / "none.json", default={"d": 1}) == {"d": 1}
    with pytest.raises(FileNotFoundError):
        fsutil.read_json(tmp_path / "none.json")
    assert fsutil.read_text(f).startswith("{")


def test_jsonl_append_and_tolerant_read(tmp_path):
    f = tmp_path / "d" / "l.jsonl"
    fsutil.append_jsonl(f, {"a": 1})
    fsutil.append_jsonl(f, {"b": "é"})
    with open(f, "a", encoding="utf-8") as h:
        h.write("not json\n\n[1]\n")
    fsutil.append_jsonl(f, {"c": 3})
    rows, bad = fsutil.read_jsonl(f)
    assert rows == [{"a": 1}, {"b": "é"}, {"c": 3}]
    assert bad == [3, 5]
    assert fsutil.read_jsonl(tmp_path / "none.jsonl") == ([], [])


def test_is_inside_and_iter_files(tmp_path):
    (tmp_path / "a" / "b").mkdir(parents=True)
    (tmp_path / "a" / "b" / "f.txt").write_text("x")
    assert fsutil.is_inside(tmp_path / "a" / "b", tmp_path)
    assert fsutil.is_inside(tmp_path, tmp_path)
    assert not fsutil.is_inside(tmp_path, tmp_path / "a")
    assert not fsutil.is_inside(tmp_path.parent, tmp_path)
    assert [p.name for p in fsutil.iter_files(tmp_path)] == ["f.txt"]


def test_slugify_and_copy_tree(tmp_path):
    assert fsutil.slugify("Hello, Wörld! 2026") == "hello-w-rld-2026"
    assert fsutil.slugify("???") == "item"
    assert len(fsutil.slugify("a" * 100)) == 60
    src = tmp_path / "src"
    (src / "pkg" / "__pycache__").mkdir(parents=True)
    (src / "pkg" / "m.py").write_text("x")
    (src / "pkg" / "m.pyc").write_text("x")
    (src / "pkg" / "__pycache__" / "m.cpython.pyc").write_text("x")
    assert fsutil.copy_tree(src, tmp_path / "dst") == 1
    assert (tmp_path / "dst" / "pkg" / "m.py").exists()
    assert not (tmp_path / "dst" / "pkg" / "m.pyc").exists()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
def test_write_secret_is_private_on_posix(tmp_path):
    f = fsutil.write_secret(tmp_path / "linkedin.env", "ID=x\n")
    assert fsutil.secret_file_is_private(f) is True
    os.chmod(f, 0o644)
    assert fsutil.secret_file_is_private(f) is False
    assert fsutil.secure_file(f) and fsutil.secret_file_is_private(f)
    assert fsutil.secret_file_is_private(tmp_path / "missing") is None
    assert fsutil.secure_file(tmp_path / "missing") is False


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACLs")
def test_write_secret_on_windows_sets_an_acl(tmp_path):
    f = fsutil.write_secret(tmp_path / "linkedin.env", "ID=x\n")
    assert f.read_text(encoding="utf-8") == "ID=x\n"
    assert fsutil.secret_file_is_private(f) is None   # ACLs are not inspected


# ----------------------------------------------------------------------- paths

def test_profile_id_rules():
    assert paths.validate_profile_id("my-profile_1") == "my-profile_1"
    for bad in ("", "Upper", "-x", "has space", "a" * 41, "runtime", "venv", "current", "../x"):
        with pytest.raises(paths.PathError):
            paths.validate_profile_id(bad)


def test_dirs_follow_env_overrides(tmp_path):
    assert paths.config_dir("p") == tmp_path / "cfgdir" / "p"
    assert paths.data_dir() == tmp_path / "datadir"
    assert paths.runtime_current() == tmp_path / "datadir" / "runtime" / "current"
    assert paths.default_home() == tmp_path / "home"
    assert paths.workspace_path("p") == tmp_path / "home" / "p"


@pytest.mark.parametrize("platform,expected", [
    ("win32", "windows"), ("darwin", "macos"), ("linux", "linux")])
def test_os_name_and_roots(monkeypatch, tmp_path, platform, expected):
    monkeypatch.delenv("PROFILE_WRAP_CONFIG_DIR")
    monkeypatch.delenv("PROFILE_WRAP_DATA_DIR")
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setattr(paths, "home", lambda: tmp_path / "h")
    assert paths.os_name() == expected
    root = {"windows": tmp_path / "appdata", "macos": tmp_path / "h" / "Library" /
            "Application Support", "linux": tmp_path / "xdg"}[expected]
    assert paths.config_dir("p") == root / "profile-wrap" / "p"
    assert paths.data_dir() == root / "profile-wrap"


def test_default_roots_without_env(monkeypatch, tmp_path):
    monkeypatch.delenv("PROFILE_WRAP_CONFIG_DIR")
    monkeypatch.setattr(paths, "home", lambda: tmp_path / "h")
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    assert paths.config_dir("p") == tmp_path / "h" / "AppData" / "Roaming" / "profile-wrap" / "p"
    monkeypatch.setattr(sys, "platform", "linux")
    assert paths.config_dir("p") == tmp_path / "h" / ".config" / "profile-wrap" / "p"
    assert paths.legacy_config_dir() == tmp_path / "h" / ".config" / "linkedin"


def test_workspace_cannot_be_inside_the_plugin(tmp_path):
    root = paths.plugin_root()
    with pytest.raises(paths.PathError, match="inside the plugin"):
        paths.workspace_path("p", str(root / "my-workspace"))
    with pytest.raises(paths.PathError):
        paths.refuse_inside_plugin(root)
    assert paths.workspace_path("p", str(tmp_path / "ok")) == tmp_path / "ok"


def test_plugin_root_resolution(monkeypatch, tmp_path):
    assert (paths.plugin_root() / "profile_wrap").is_dir()
    fake = tmp_path / "fakeplugin"
    (fake / "profile_wrap").mkdir(parents=True)
    monkeypatch.setenv("PROFILE_WRAP_PLUGIN_ROOT", str(fake))
    assert paths.plugin_root() == fake
    assert paths.resource("schema", "x.json") == fake / "schema" / "x.json"
    monkeypatch.setenv("PROFILE_WRAP_PLUGIN_ROOT", str(tmp_path / "nonexistent"))
    assert (paths.plugin_root() / "profile_wrap").is_dir()    # falls back to the source tree


def test_find_workspace(tmp_path, monkeypatch):
    ws = tmp_path / "w"
    (ws / ".njl").mkdir(parents=True)
    (ws / ".njl" / "workspace.json").write_text("{}")
    deep = ws / "drafts" / "a"
    deep.mkdir(parents=True)
    assert paths.find_workspace(deep) == ws
    assert paths.find_workspace(tmp_path) is None
    monkeypatch.setenv("PROFILE_WRAP_WORKSPACE", str(tmp_path / "elsewhere"))
    assert paths.find_workspace(deep) == tmp_path / "elsewhere"


# --------------------------------------------------------------------- tzutil

@needs_tzdata
def test_dst_and_offsets_for_three_zones():
    ny = tzutil.localize(dt.datetime(2026, 3, 7, 12), "America/New_York")
    ny2 = tzutil.localize(dt.datetime(2026, 3, 9, 12), "America/New_York")
    assert tzutil.utc_offset_label(ny) == "-05:00" and tzutil.utc_offset_label(ny2) == "-04:00"
    lis_winter = tzutil.localize(dt.datetime(2026, 1, 15, 10), "Europe/Lisbon")
    lis_summer = tzutil.localize(dt.datetime(2026, 7, 15, 10), "Europe/Lisbon")
    assert tzutil.utc_offset_label(lis_winter) == "+00:00"
    assert tzutil.utc_offset_label(lis_summer) == "+01:00"
    amman = tzutil.localize(dt.datetime(2026, 10, 16, 15, 30), "Asia/Amman")
    assert tzutil.utc_offset_label(amman) == "+03:00"      # Jordan stays on +03:00 year round
    assert tzutil.utc_offset_label(dt.datetime(2026, 1, 1)) is None


@needs_tzdata
def test_to_zone_and_parse_aware():
    moment = tzutil.parse_aware("2026-10-16T12:00:00Z")
    assert tzutil.to_zone(moment, "Asia/Amman").hour == 15
    with pytest.raises(ValueError):
        tzutil.parse_aware("2026-10-16T12:00:00")
    with pytest.raises(ValueError):
        tzutil.to_zone(dt.datetime(2026, 1, 1), "UTC")


@needs_tzdata
def test_iso_week_uses_the_configured_zone_at_midnight():
    # 2026-10-18 is a Sunday; 23:30 UTC is already Monday 2026-10-19 in Amman (+03:00).
    moment = dt.datetime(2026, 10, 18, 23, 30, tzinfo=dt.timezone.utc)
    assert tzutil.iso_week(moment, "UTC") == (2026, 42)
    assert tzutil.iso_week(moment, "Asia/Amman") == (2026, 43)
    assert tzutil.iso_week_label(moment, "Asia/Amman") == "2026-W43"
    # a year boundary: 2026-12-31 is in ISO week 53 of 2026; 2027-01-01 too
    new_year = dt.datetime(2027, 1, 1, 0, 30, tzinfo=dt.timezone.utc)
    assert tzutil.iso_week(new_year, "UTC") == (2026, 53)
    assert tzutil.iso_week(dt.datetime(2026, 10, 19, 9), "UTC") == (2026, 43)   # naive = local


@needs_tzdata
def test_week_start_is_monday_midnight_local():
    moment = tzutil.localize(dt.datetime(2026, 10, 16, 15), "Asia/Amman")        # a Friday
    start = tzutil.week_start(moment, "Asia/Amman")
    assert (start.year, start.month, start.day, start.hour, start.weekday()) == (2026, 10, 12, 0, 0)
    assert tzutil.week_start(dt.datetime(2026, 10, 16, 15), "UTC").day == 12


@needs_tzdata
def test_validity_and_errors(monkeypatch):
    assert tzutil.is_valid_timezone("Europe/Lisbon")
    assert not tzutil.is_valid_timezone("Mars/Olympus")
    assert tzutil.tzdata_available()
    with pytest.raises(tzutil.TimezoneUnavailable, match="cannot be loaded"):
        tzutil.get_zone("Mars/Olympus")
    assert tzutil.now("UTC").tzinfo is not None


@needs_tzdata
def test_detect_timezone_paths(monkeypatch, tmp_path):
    monkeypatch.setenv("TZ", ":Asia/Amman")
    assert tzutil.detect_timezone() == "Asia/Amman"
    monkeypatch.delenv("TZ")
    assert tzutil.detect_timezone() in tzutil.WINDOWS_TO_IANA.values() or \
        tzutil.is_valid_timezone(tzutil.detect_timezone())
    for name in tzutil.WINDOWS_TO_IANA.values():
        assert tzutil.is_valid_timezone(name), name


def test_detect_timezone_windows_uses_tzutil(monkeypatch):
    import subprocess

    monkeypatch.delenv("TZ", raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
        a, 0, stdout="Jordan Standard Time\n", stderr=""))
    assert tzutil.detect_timezone() == "Asia/Amman"
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
        a, 0, stdout="Unknown Zone\n", stderr=""))
    assert tzutil.detect_timezone() == "UTC"

    def missing(*a, **k):
        raise OSError("no tzutil")

    monkeypatch.setattr(subprocess, "run", missing)
    assert tzutil.detect_timezone() == "UTC"


# ---------------------------------------------------------------------- notify

def test_notify_log_mode_writes_the_board_banner(tmp_path):
    channel = notify.notify("Token", "7 days left", workspace=tmp_path, mode="log")
    assert channel == "log"
    rows, bad = fsutil.read_jsonl(tmp_path / "data" / "logs" / "notifications.jsonl")
    assert rows[0]["title"] == "Token" and rows[0]["channel"] == "log" and bad == []


@pytest.mark.parametrize("platform,attr", [("win32", "_windows_toast"), ("darwin", "_mac_notice"),
                                           ("linux", "_linux_notice")])
def test_notify_picks_the_os_channel_and_falls_back(monkeypatch, tmp_path, platform, attr):
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(notify, attr, lambda t, m: True)
    expected = {"win32": "toast", "darwin": "osascript", "linux": "notify-send"}[platform]
    assert notify.notify("t", "m", tmp_path) == expected
    monkeypatch.setattr(notify, attr, lambda t, m: False)
    assert notify.notify("t", "m", tmp_path) == "log"

    def explode(t, m):
        raise OSError("no desktop")

    monkeypatch.setattr(notify, attr, explode)
    assert notify.notify("t", "m") == "log"          # never raises


def test_notify_helpers_without_tools(monkeypatch):
    monkeypatch.setattr(notify.shutil, "which", lambda name: None)
    assert not notify._windows_toast("a", "b")
    assert not notify._mac_notice("a", "b")
    assert not notify._linux_notice("a", "b")
    assert notify._ps_escape("it's\nok") == "it''s ok"
