from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from njli import doctor, policy, schemalite
from core_helpers import needs_tzdata

REPO = Path(__file__).resolve().parents[3]
SCHEMA = schemalite.load_schema(REPO / "schema" / "doctor.schema.json")
TOOLS = ("git", "claude", "node", "npx", "ffmpeg", "ffprobe", "chrome")
EXPECTED_HINT = {"windows": "winget", "macos": "brew", "linux": "apt"}


@pytest.fixture()
def empty_path(tmp_path) -> str:
    d = tmp_path / "emptybin"
    d.mkdir()
    return str(d)


def by_id(result, cid):
    return next(c for c in result["checks"] if c["id"] == cid)


@pytest.mark.parametrize("label", doctor.OS_LABELS)
def test_json_passes_its_schema_for_every_os(label, empty_path, monkeypatch):
    monkeypatch.setenv("PATH", empty_path)
    result = doctor.run(label=label, path=empty_path)
    assert schemalite.validate(result, SCHEMA) == []
    assert result["os"] == label
    json.loads(doctor.dumps(result))


@pytest.mark.parametrize("label", doctor.OS_LABELS)
def test_hidden_tools_give_the_right_per_os_hint(label, empty_path, monkeypatch):
    monkeypatch.setenv("PATH", empty_path)
    monkeypatch.setenv("LOCALAPPDATA", empty_path)
    monkeypatch.setenv("PROGRAMFILES", empty_path)
    monkeypatch.setenv("PROGRAMFILES(X86)", empty_path)
    monkeypatch.setattr(doctor, "_chrome_locations", lambda lbl: [])
    result = doctor.run(label=label, path=empty_path)
    for tool in ("git", "node", "npx", "ffmpeg", "ffprobe", "chrome"):
        check = by_id(result, tool)
        assert check["status"] == "warn", tool
        assert check["hint"], tool
        key = EXPECTED_HINT[label]
        if tool in ("npx",):
            assert "Node" in check["hint"]
        else:
            assert key in check["hint"] or (label == "linux" and "nvm" in check["hint"]) or \
                   (tool == "chrome" and label == "macos" and "brew" in check["hint"]), \
                (tool, label, check["hint"])
    # hints never mention another OS's package manager
    for tool in ("git", "ffmpeg", "ffprobe"):
        hint = by_id(result, tool)["hint"]
        others = {k: v for k, v in EXPECTED_HINT.items() if k != label}
        if label == "linux":
            assert "brew" not in hint and "winget" not in hint
        if label == "windows":
            assert "apt" not in hint and "brew" not in hint
        if label == "macos":
            assert "winget" not in hint and "apt install" not in hint
        assert others
    claude = by_id(result, "claude")
    assert claude["status"] == "warn" and "claude-code" in claude["hint"]


def test_chrome_hint_on_macos_mentions_quarantine(empty_path, monkeypatch):
    monkeypatch.setattr(doctor, "_chrome_locations", lambda lbl: [])
    result = doctor.run(label="macos", path=empty_path)
    assert "xattr" in by_id(result, "chrome")["hint"]
    assert "arm64" in by_id(result, "chrome")["hint"]


def test_tools_found_on_path_pass(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name in ("git", "node", "npx", "ffmpeg", "ffprobe", "claude", "uv", "pdftotext"):
        exe = bindir / (name + (".exe" if sys.platform == "win32" else ""))
        exe.write_text("#!/bin/sh\n")
        exe.chmod(0o755)
    result = doctor.run(label="linux", path=str(bindir))
    for tool in ("git", "node", "npx", "ffmpeg", "ffprobe", "claude", "uv", "poppler"):
        assert by_id(result, tool)["status"] == "pass", tool
        assert by_id(result, tool)["hint"] == ""


def test_claude_can_come_from_the_env_override(tmp_path, monkeypatch, empty_path):
    fake = tmp_path / "fake-claude"
    fake.write_text("x")
    monkeypatch.setenv("NJLI_CLAUDE_BIN", str(fake))
    assert by_id(doctor.run(path=empty_path), "claude")["status"] == "pass"


def test_chrome_discovery_order(tmp_path, monkeypatch, empty_path):
    chrome = tmp_path / "mychrome"
    chrome.write_text("x")
    monkeypatch.setenv("NJLI_BROWSER", str(chrome))
    assert by_id(doctor.run(path=empty_path), "chrome")["detail"] == str(chrome)
    monkeypatch.delenv("NJLI_BROWSER")
    d = doctor.Doctor(path=empty_path, cfg={"render": {"chrome_path": str(chrome)}})
    assert d._chrome() == str(chrome)


def test_python_check_and_summary_counts(empty_path):
    result = doctor.run(path=empty_path)
    assert by_id(result, "python")["status"] == "pass"
    total = sum(result["summary"].values())
    assert total == len(result["checks"])
    assert doctor.exit_code(result) == (policy.EXIT_FAIL if result["summary"]["fail"] else 0)
    text = doctor.render_table(result)
    assert "njli doctor" in text and "pass" in text


def test_exit_code_is_fail_when_a_check_fails():
    assert doctor.exit_code({"summary": {"fail": 1}}) == policy.EXIT_FAIL
    assert doctor.exit_code({"summary": {"fail": 0}}) == policy.EXIT_OK


def test_unknown_os_label_is_refused():
    with pytest.raises(ValueError):
        doctor.Doctor(label="plan9")


@needs_tzdata
def test_workspace_checks(make_workspace, empty_path):
    ws = make_workspace()
    result = doctor.run(workspace=ws, path=empty_path)
    assert schemalite.validate(result, SCHEMA) == []
    assert by_id(result, "config")["status"] == "pass"
    assert by_id(result, "pause")["status"] == "pass"
    assert by_id(result, "schedule")["status"] == "warn"
    from njli import limits

    limits.pause(ws, "posting")
    result = doctor.run(workspace=ws, path=empty_path)
    assert by_id(result, "pause")["status"] == "warn" and "posting" in by_id(result, "pause")["detail"]


def test_not_a_workspace_fails(tmp_path, empty_path):
    result = doctor.run(workspace=tmp_path, path=empty_path)
    assert by_id(result, "workspace")["status"] == "fail"
    assert "njli init" in by_id(result, "workspace")["hint"]


def test_invalid_config_is_a_fail(make_workspace, empty_path):
    ws = make_workspace()
    path = ws / "config" / "njli.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["posting"]["per_week"] = 99
    path.write_text(json.dumps(raw), encoding="utf-8")
    result = doctor.run(workspace=ws, path=empty_path)
    assert by_id(result, "config")["status"] == "fail"
    assert "ceiling" in by_id(result, "config")["detail"]


def test_user_gates_and_failed_jobs_are_flagged(make_workspace, empty_path):
    ws = make_workspace()
    (ws / "hooks").mkdir(exist_ok=True)
    (ws / "hooks" / "gate_custom.py").write_text("# user code\n")
    from njli import fsutil

    fsutil.append_jsonl(ws / "data" / "logs" / "runs.jsonl", {"job": "build_week", "exit": 0})
    fsutil.append_jsonl(ws / "data" / "logs" / "runs.jsonl", {"job": "post_due", "exit": 1})
    result = doctor.run(workspace=ws, path=empty_path)
    assert by_id(result, "user_gates")["status"] == "warn"
    assert "gate_custom.py" in by_id(result, "user_gates")["detail"]
    assert by_id(result, "job_logs")["status"] == "warn"
    assert "post_due" in by_id(result, "job_logs")["detail"]


def test_token_expiry_levels(make_workspace, empty_path):
    import datetime as dt

    ws = make_workspace()
    cfg_dir = Path(os.environ["NJLI_CONFIG_DIR"]) / "en-only"
    cfg_dir.mkdir(parents=True)
    token = cfg_dir / "token.json"

    def status(expires):
        token.write_text(json.dumps({"expires_at": expires}), encoding="utf-8")
        return by_id(doctor.run(workspace=ws, path=empty_path), "token")

    now = dt.datetime.now(dt.timezone.utc)
    assert status((now + dt.timedelta(days=40)).isoformat())["status"] == "pass"
    assert status((now + dt.timedelta(days=3)).isoformat())["status"] == "warn"
    assert status((now - dt.timedelta(days=1)).isoformat())["status"] == "fail"
    assert status((now + dt.timedelta(days=40)).timestamp())["status"] == "pass"
    token.write_text(json.dumps({"obtained_at": now.isoformat(), "expires_in": 5184000}))
    assert by_id(doctor.run(workspace=ws, path=empty_path), "token")["status"] == "pass"
    token.write_text("{}")
    assert by_id(doctor.run(workspace=ws, path=empty_path), "token")["status"] == "warn"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
def test_loose_secret_permissions_fail(make_workspace, empty_path):
    ws = make_workspace()
    cfg_dir = Path(os.environ["NJLI_CONFIG_DIR"]) / "en-only"
    cfg_dir.mkdir(parents=True)
    secret = cfg_dir / "linkedin.env"
    secret.write_text("ID=x\n")
    secret.chmod(0o644)
    result = doctor.run(workspace=ws, path=empty_path)
    assert by_id(result, "secrets")["status"] == "fail"
    secret.chmod(0o600)
    assert by_id(doctor.run(workspace=ws, path=empty_path), "secrets")["status"] == "pass"


def test_api_version_table_age(tmp_path, empty_path):
    import datetime as dt

    root = tmp_path / "root"
    (root / "data").mkdir(parents=True)
    table = root / "data" / "linkedin-versions.json"
    old = (dt.date.today() - dt.timedelta(days=120)).isoformat()
    table.write_text(json.dumps({"updated": old}))
    assert by_id(doctor.run(plugin_root=root, path=empty_path), "api_version")["status"] == "warn"
    table.write_text(json.dumps({"updated": dt.date.today().isoformat()}))
    assert by_id(doctor.run(plugin_root=root, path=empty_path), "api_version")["status"] == "pass"
    table.write_text(json.dumps({"versions": []}))
    assert by_id(doctor.run(plugin_root=root, path=empty_path), "api_version")["status"] == "warn"
    table.unlink()
    assert by_id(doctor.run(plugin_root=root, path=empty_path), "api_version")["status"] == "skip"


def test_online_check_uses_the_probe(monkeypatch, empty_path):
    monkeypatch.setattr(doctor.http, "reachable", lambda host, *a, **k: (False, "offline"))
    result = doctor.run(path=empty_path, online=True)
    assert by_id(result, "network")["status"] == "warn" and by_id(result, "network")["hint"]
    monkeypatch.setattr(doctor.http, "reachable", lambda host, *a, **k: (True, "ok"))
    assert by_id(doctor.run(path=empty_path, online=True), "network")["status"] == "pass"
    assert by_id(doctor.run(path=empty_path), "network")["status"] == "skip"


def test_launchd_dryrun(empty_path):
    other = doctor.run(label="linux", path=empty_path, launchd_dryrun=True)
    assert by_id(other, "launchd")["status"] == "skip"
    mac = doctor.run(label="macos", path=empty_path, launchd_dryrun=True)
    assert by_id(mac, "launchd")["status"] == "warn" and "brew" in by_id(mac, "launchd")["hint"]
    assert not any(c["id"] == "launchd" for c in doctor.run(path=empty_path)["checks"])


def test_pdf_tools_matter_only_when_documents_are_enabled(empty_path):
    d = doctor.Doctor(label="linux", path=empty_path,
                      cfg={"posting": {"formats_enabled": ["text", "document"]}})
    assert by_id(d.run(), "poppler")["status"] == "warn"
    assert by_id(doctor.run(label="linux", path=empty_path), "poppler")["status"] == "skip"


def test_compliance_lint_check_reports_a_violation_and_a_crash(tmp_path, empty_path, monkeypatch):
    import types

    fake = types.SimpleNamespace(lint=lambda root: ["v1", "v2"])
    monkeypatch.setitem(sys.modules, "njli.compliance.lint", fake)
    assert by_id(doctor.run(path=empty_path), "compliance")["status"] == "fail"
    fake.lint = lambda root: []
    assert by_id(doctor.run(path=empty_path), "compliance")["status"] == "pass"

    def crash(root):
        raise RuntimeError("boom")

    fake.lint = crash
    assert by_id(doctor.run(path=empty_path), "compliance")["status"] == "warn"


def test_runtime_check_levels(tmp_path, empty_path):
    result = doctor.run(path=empty_path)
    assert by_id(result, "runtime")["status"] == "warn"
    assert "runtime install" in by_id(result, "runtime")["hint"]


def test_windows_missing_tzdata_is_a_fail(monkeypatch, empty_path):
    monkeypatch.setattr(doctor.tzutil, "tzdata_available", lambda: False)
    assert by_id(doctor.run(label="windows", path=empty_path), "tzdata")["status"] == "fail"
    assert by_id(doctor.run(label="linux", path=empty_path), "tzdata")["status"] == "warn"


def test_python_too_old_is_a_fail(monkeypatch, empty_path):
    class Old(tuple):
        pass

    monkeypatch.setattr(doctor.sys, "version_info", (3, 9, 18, "final", 0))
    result = doctor.run(path=empty_path)
    assert by_id(result, "python")["status"] == "fail"
    assert "winget" in by_id(result, "python")["hint"] or "brew" in by_id(result, "python")["hint"] \
        or "apt" in by_id(result, "python")["hint"]
