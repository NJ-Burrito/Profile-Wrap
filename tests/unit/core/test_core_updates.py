"""The optional update notifier: semver, cache, state, opt-outs, parsing, the CLI and a real local HTTP round trip."""
from __future__ import annotations

import json
import threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from profile_wrap import __version__, cli, updates

NOW = 1_800_000_000.0


def rel(tag, body="- something new", pre=False, draft=False):
    return {"tag_name": tag, "name": tag, "body": body, "html_url": f"https://example.invalid/{tag}",
            "prerelease": pre, "draft": draft, "published_at": "2026-10-20T00:00:00Z"}


class Fake:
    """A fake HTTP layer: records calls, answers like api.github.com."""

    def __init__(self, releases=None, status=200, headers=None, raw=None, changelog="", fail=None):
        self.releases, self.status, self.headers = releases or [], status, headers or {}
        self.raw, self.changelog, self.fail, self.calls = raw, changelog, fail, []

    def __call__(self, url, headers):
        self.calls.append(url)
        if self.fail:
            raise self.fail
        if "/contents/CHANGELOG.md" in url:
            return 200, {}, self.changelog.encode()
        body = self.raw if self.raw is not None else json.dumps(self.releases).encode()
        return self.status, self.headers, body


@pytest.fixture()
def env(tmp_path):
    return {"PROFILE_WRAP_CACHE_DIR": str(tmp_path / "cache")}


def st(env, fake, now=NOW, **kw):
    return updates.status(env=env, fetch=fake, now=now, **kw)


# ----------------------------------------------------------------- versions

def test_semver_order_and_prereleases():
    assert updates.is_newer("v0.3.0", "0.2.1") and updates.is_newer("0.2.2", "0.2.1")
    assert not updates.is_newer("0.2.1", "0.2.1") and not updates.is_newer("0.2.0", "0.2.1")
    assert updates.is_newer("1.0.0", "1.0.0-rc.1") and not updates.is_newer("1.0.0-rc.1", "1.0.0")
    assert updates.is_newer("1.0.0-rc.2", "1.0.0-rc.1") and updates.is_newer("1.0.0-rc.10", "1.0.0-rc.9")
    assert not updates.is_newer("garbage", "0.2.1") and not updates.is_newer("v0.3", "0.2.1")


# ------------------------------------------------------------------- status

def test_newer_release_is_reported_with_news_newest_first(env):
    fake = Fake([rel("v0.2.0", "old"), rel("v0.3.1", "three one"), rel("v0.3.0", "three"), rel(__version__)])
    s = st(env, fake)
    assert s["available"] and s["notify"] and s["latest"] == "0.3.1" and s["source"] == "network"
    assert [r["tag"] for r in s["news"]] == ["v0.3.1", "v0.3.0"]
    assert s["news"][0]["body"] == "three one"
    assert s["method"]["id"] in {"git", "uv-tool", "pipx", "pip", "desktop", "claude-plugin"}


def test_same_and_older_say_nothing(env):
    assert not st(env, Fake([rel(f"v{__version__}"), rel("v0.1.0")]))["available"]


def test_prereleases_and_drafts_are_ignored_unless_opted_in(env, tmp_path):
    fake = Fake([rel("v9.0.0-rc.1", pre=True), rel("v9.1.0", draft=True)])
    assert not st(env, fake)["available"]
    on = dict(env, PROFILE_WRAP_UPDATE_PRERELEASES="1")
    s = st(on, fake, now=NOW + 7200)
    assert s["available"] and s["latest"] == "9.0.0-rc.1"        # the draft is never listed


def test_offline_malformed_and_rate_limited_never_raise(env, tmp_path):
    for i, fake in enumerate([Fake(fail=OSError("no route")), Fake(raw=b"{not json"), Fake(raw=b'{"a": 1}'),
                              Fake(status=403, headers={"x-ratelimit-remaining": "0"}), Fake(status=500)]):
        e = {"PROFILE_WRAP_CACHE_DIR": str(tmp_path / f"c{i}")}
        s = st(e, fake)
        assert s["source"] == "offline" and not s["notify"] and s["error"], i
    e = {"PROFILE_WRAP_CACHE_DIR": str(tmp_path / "c3")}
    assert "rate limited" in updates.read_cache(e)["error"]


def test_cache_is_used_for_an_hour_then_refreshed(env):
    fake = Fake([rel("v0.3.0")])
    st(env, fake)
    st(env, fake, now=NOW + 3599)
    assert len(fake.calls) == 1
    s = st(env, fake, now=NOW + 3601)
    assert len(fake.calls) == 2 and s["source"] == "network"
    st(env, fake, now=NOW + 3602, force=True)
    assert len(fake.calls) == 3


def test_a_failure_is_remembered_briefly_and_keeps_the_last_good_answer(env):
    st(env, Fake([rel("v0.3.0")]))
    bad = Fake(fail=OSError("down"))
    s = st(env, bad, now=NOW + 4000)
    assert s["available"] and s["error"]                          # stale-but-useful
    st(env, bad, now=NOW + 4100)
    assert len(bad.calls) == 1                                    # not hammered
    st(env, bad, now=NOW + 4000 + updates.FAIL_TTL_S + 1)
    assert len(bad.calls) == 2


def test_cache_only_mode_makes_no_request(env):
    fake = Fake([rel("v0.3.0")])
    assert not st(env, fake, network=False)["available"] and not fake.calls
    st(env, fake)
    assert st(env, Fake(fail=AssertionError("no network")), network=False)["available"]


def test_skip_later_and_a_newer_release_resurfaces(env):
    fake = Fake([rel("v0.3.0")])
    assert st(env, fake)["notify"]
    updates.skip("0.3.0", env)
    s = st(env, fake)
    assert s["available"] and s["skipped"] and not s["notify"]
    fake2 = Fake([rel("v0.3.1"), rel("v0.3.0")])
    assert st(env, fake2, now=NOW + 7200)["notify"]               # a newer version is news again
    updates.later("0.3.1", env, now=NOW + 7200)
    assert st(env, fake2, now=NOW + 7300)["snoozed"]
    assert st(env, fake2, now=NOW + 7200 + updates.LATER_S + 1)["notify"]


def test_toast_marker_fires_once_per_version(env):
    assert updates.mark_toasted("0.3.0", env) and not updates.mark_toasted("v0.3.0", env)
    assert updates.mark_toasted("0.3.1", env)


# ------------------------------------------------------------------ opt-outs

def test_env_opt_out_makes_no_request(env):
    fake = Fake([rel("v0.3.0")])
    s = st(dict(env, PROFILE_WRAP_NO_UPDATE_CHECK="1"), fake)
    assert s["source"] == "disabled" and not s["available"] and not fake.calls
    assert updates.check_in_background(env=dict(env, PROFILE_WRAP_NO_UPDATE_CHECK="1")) is None


def test_config_opt_out(env, tmp_path):
    from profile_wrap import config, init_wizard
    summary = init_wizard.init_workspace(tmp_path / "ws", init_wizard.DEMO_ANSWERS, git=False)
    ws = Path(summary["workspace"])
    assert config.load(ws)["updates"] == {"check": True, "prereleases": False}
    fake = Fake([rel("v0.3.0")])
    assert st(env, fake, workspace=ws)["available"]
    config.set_value(ws, "updates.check", "false")
    assert config.validate_workspace(ws).ok
    fake2 = Fake([rel("v0.3.0")])
    s = st(env, fake2, now=NOW + 9999, workspace=ws)
    assert s["source"] == "disabled" and not fake2.calls


def test_off_under_ci_and_pytest(env):
    for extra in ({"CI": "true"}, {"PYTEST_CURRENT_TEST": "x"}):
        fake = Fake([rel("v0.3.0")])
        assert st(dict(env, **extra), fake)["source"] == "disabled" and not fake.calls


# ------------------------------------------------------------------ parsing

CHANGELOG = """# Changelog

## [Unreleased]

### Added
- not yet

## [0.3.0] - 2026-10-20

### Added
- A thing.

## [0.2.5] - 2026-10-10

### Fixed
- Another.

## [0.2.1] - 2026-10-01

### Fixed
- Old.
"""


def test_changelog_sections_between_installed_and_latest():
    got = updates.parse_changelog(CHANGELOG, "0.2.1", "0.3.0")
    assert [r["tag"] for r in got] == ["v0.3.0", "v0.2.5"]
    assert "A thing." in got[0]["body"] and "Old." not in json.dumps(got)
    assert updates.parse_changelog(CHANGELOG, "0.3.0") == []


def test_empty_release_notes_fall_back_to_the_changelog(env):
    fake = Fake([rel("v0.3.0", body=""), rel("v0.2.5", body="  ")], changelog=CHANGELOG)
    s = st(env, fake)
    assert s["latest"] == "0.3.0" and [r["tag"] for r in s["news"]] == ["v0.3.0", "v0.2.5"]
    assert "A thing." in s["news"][0]["body"]
    assert any("contents/CHANGELOG.md" in c for c in fake.calls)


def test_notice_and_one_line_are_plain_text(env):
    s = st(env, Fake([rel("v0.3.0", "- one\n- two")]))
    text = updates.notice(s)
    assert "0.3.0" in text and "- one" in text and "optional" in text.lower()
    assert "update news" in updates.one_line(s)
    assert "argv" not in updates.public_status(s)["method"]


# ------------------------------------------------------------ install method

@pytest.mark.parametrize("kw,env,expect,cmd", [
    ({"frozen": True}, {}, "desktop", ""),
    ({}, {"CLAUDE_PLUGIN_ROOT": "/p"}, "claude-plugin", ""),
    ({"prefix": "\\".join(["D:", "tools", "uv", "tools", "profile-wrap"])}, {}, "uv-tool", "uv tool upgrade profile-wrap"),
    ({"prefix": "/".join(["", "opt", "pipx", "venvs", "profile-wrap"])}, {}, "pipx", "pipx upgrade profile-wrap"),
    ({"prefix": "/usr"}, {}, "pip", "uv pip install --upgrade profile_wrap"),
])
def test_install_method_detection(tmp_path, kw, env, expect, cmd):
    m = updates.detect_method(env=env, repo_root=tmp_path, **kw)
    assert m["id"] == expect and (not cmd or m["command"] == cmd)
    assert m["runs"] is bool(cmd)


def test_git_clone_command(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "pyproject.toml").write_text("[project]\n")
    m = updates.detect_method(env={}, prefix="/x/.venv", repo_root=tmp_path)
    assert m["id"] == "git" and m["argv"][0][:2] == ["git", "-C"] and m["argv"][1][0] == "uv"


# ----------------------------------------------- the CLI, through main()

@pytest.fixture()
def cli_env(monkeypatch, tmp_path):
    monkeypatch.setenv("PROFILE_WRAP_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("PROFILE_WRAP_TEST", "1")
    monkeypatch.setenv("PROFILE_WRAP_UPDATE_API_BASE", "http://127.0.0.1:9")   # makes the check eligible under pytest
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
    fake = Fake([rel("v0.3.0", "- Brand new thing")])
    monkeypatch.setattr(updates, "_default_fetch", fake)
    return fake


def test_cli_check_news_json_skip_later(cli_env, capsys):
    assert cli.main(["update", "check"]) == 0
    out = capsys.readouterr().out
    assert "0.3.0 is available" in out and "optional" in out and "Brand new thing" not in out
    assert cli.main(["update", "news"]) == 0
    assert "Brand new thing" in capsys.readouterr().out
    assert cli.main(["update", "check", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["latest"] == "0.3.0" and data["notify"] and "argv" not in data["method"]
    assert cli.main(["update", "skip"]) == 0 and "skipped" in capsys.readouterr().out
    cli.main(["update", "check", "--json"])
    assert json.loads(capsys.readouterr().out)["skipped"] is True
    assert cli.main(["update", "later"]) == 0 and "24 hours" in capsys.readouterr().out


def test_cli_hook_prints_only_when_there_is_news_and_never_fails(cli_env, capsys, monkeypatch, tmp_path):
    assert cli.main(["update", "check", "--hook"]) == 0
    out = capsys.readouterr().out
    assert "update available" in out and "Brand new thing" in out
    cli.main(["update", "skip"])
    capsys.readouterr()
    assert cli.main(["update", "check", "--hook"]) == 0 and capsys.readouterr().out == ""
    monkeypatch.setattr(updates, "_default_fetch", Fake(fail=OSError("offline")))
    monkeypatch.setenv("PROFILE_WRAP_CACHE_DIR", str(tmp_path / "empty-cache"))
    assert cli.main(["update", "check", "--hook"]) == 0 and capsys.readouterr().out == ""


def test_cli_apply_asks_first_and_runs_only_on_yes(cli_env, capsys, monkeypatch):
    ran = []
    import subprocess
    monkeypatch.setattr(subprocess, "run", lambda argv, **k: ran.append(argv) or subprocess.CompletedProcess(argv, 0))
    monkeypatch.setattr(updates, "detect_method", lambda *a, **k: {
        "id": "uv-tool", "label": "uv tool", "argv": [["uv", "tool", "upgrade", "profile-wrap"]],
        "command": "uv tool upgrade profile-wrap", "note": "", "runs": True})
    assert cli.main(["update", "apply"]) == 0             # not a tty: no prompt answer, so nothing runs
    assert not ran and "Not run" in capsys.readouterr().out
    assert cli.main(["update", "apply", "--yes"]) == 0
    assert ran == [["uv", "tool", "upgrade", "profile-wrap"]]


def test_cli_apply_for_plugin_and_desktop_only_prints(cli_env, capsys, monkeypatch):
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", "/p")
    assert cli.main(["update", "apply", "--yes"]) == 0
    assert "/plugin update profile-wrap" in capsys.readouterr().out


def test_startup_line_only_on_a_tty_and_not_with_json(cli_env, capsys, monkeypatch):
    monkeypatch.setattr("sys.stderr.isatty", lambda: True, raising=False)
    updates.startup_notice(["doctor"], as_json=False)
    assert "0.3.0 is available" in capsys.readouterr().err
    updates.startup_notice(["doctor"], as_json=True)
    updates.startup_notice(["update", "check"], as_json=False)
    assert capsys.readouterr().err == ""


# -------------------------------------- real HTTP round trip (the real caller)

class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        self.server.seen.append((self.path, self.headers.get("User-Agent"), self.headers.get("Authorization")))
        body = json.dumps([rel("v0.3.0", "- over real http")]).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def test_real_http_layer_against_a_loopback_fixture(tmp_path, monkeypatch, capsys):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    srv.seen = []
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        monkeypatch.setenv("PROFILE_WRAP_CACHE_DIR", str(tmp_path / "cache"))
        monkeypatch.setenv("PROFILE_WRAP_TEST", "1")
        monkeypatch.setenv("PROFILE_WRAP_UPDATE_API_BASE", f"http://127.0.0.1:{srv.server_address[1]}")
        assert cli.main(["update", "news"]) == 0
        out = capsys.readouterr().out
        assert "0.3.0 is available" in out and "over real http" in out
        path, agent, auth = srv.seen[0]
        assert path.startswith("/repos/NJ-Burrito/profile-wrap/releases") and agent == f"profile-wrap/{__version__}"
        assert auth is None                                    # public read, never a token
    finally:
        srv.shutdown()
        srv.server_close()


def test_the_override_base_is_ignored_outside_test_mode(tmp_path):
    e = {"PROFILE_WRAP_UPDATE_API_BASE": "http://127.0.0.1:9"}
    assert updates._override_base(e) is None
    assert updates._override_base(dict(e, PROFILE_WRAP_TEST="1")) == "http://127.0.0.1:9"
    assert updates._override_base({"PROFILE_WRAP_TEST": "1", "PROFILE_WRAP_UPDATE_API_BASE": "https://evil.example"}) is None
