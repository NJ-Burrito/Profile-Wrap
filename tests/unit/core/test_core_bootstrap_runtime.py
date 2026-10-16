from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from njli import __version__
from njli.bootstrap import find_python, runtime

REPO = Path(__file__).resolve().parents[3]
BIN = REPO / "bin"


# ------------------------------------------------------------- python version

@pytest.mark.parametrize("label,fix", [("windows", "winget"), ("macos", "brew install python@3.12"),
                                       ("linux", "apt")])
def test_python_39_prints_one_actionable_message(label, fix):
    message = find_python.version_message((3, 9, 18), label)
    assert message.count("\n") == 2                       # one message: headline, fix, uv option
    assert "Python 3.9.18" in message and "3.10" in message
    assert message.count("Fix:") == 1 and fix in message
    assert "uv run --python 3.12" in message


def test_current_python_has_no_message():
    assert find_python.version_message((3, 10, 0)) is None
    assert find_python.version_message((3, 13, 1)) is None
    assert find_python.version_message() is None


def test_find_prefers_override_and_skips_old(monkeypatch):
    monkeypatch.setenv("NJLI_PYTHON", sys.executable)
    cmd, ver = find_python.find()
    assert cmd == [sys.executable] and ver[:2] == sys.version_info[:2]
    monkeypatch.setenv("NJLI_PYTHON", "definitely-not-a-python")
    cmd, ver = find_python.find()
    assert cmd is None or find_python.probe(cmd)[:2] >= (3, 10)

    monkeypatch.delenv("NJLI_PYTHON")
    monkeypatch.setattr(find_python, "probe", lambda c: (3, 9, 1))
    assert find_python.find() == (None, (3, 9, 1))
    monkeypatch.setattr(find_python, "probe", lambda c: None)
    assert find_python.find() == (None, None)


def test_main_prints_command_or_message(monkeypatch, capsys):
    monkeypatch.setattr(find_python, "find", lambda: (["py", "-3.12"], (3, 12, 1)))
    assert find_python.main() == 0
    assert capsys.readouterr().out.strip() == "py -3.12"
    monkeypatch.setattr(find_python, "find", lambda: (None, (3, 9, 18)))
    assert find_python.main() == 1
    err = capsys.readouterr().err
    assert "Python 3.9.18" in err and err.count("Fix:") == 1
    monkeypatch.setattr(find_python, "find", lambda: (None, None))
    assert find_python.main() == 1
    assert "did not find any Python" in capsys.readouterr().err


def test_probe_handles_missing_and_broken_interpreters(tmp_path):
    assert find_python.probe(["no-such-interpreter-xyz"]) is None
    assert find_python.probe([sys.executable])[:2] == sys.version_info[:2]


def test_python_files_that_must_parse_on_39_have_no_new_syntax():
    import ast

    for rel in ("njli/__init__.py", "njli/bootstrap/find_python.py", "bin/njli.py"):
        tree = ast.parse((REPO / rel).read_text(encoding="utf-8"), feature_version=(3, 9))
        assert tree


# ---------------------------------------------------------------------- shims

def run_shim(args, env_extra=None, cwd=None):
    env = dict(os.environ)
    env.update({"PYTHONUTF8": "1", "NJLI_PYTHON": sys.executable})
    env.update(env_extra or {})
    return subprocess.run([sys.executable, str(BIN / "njli.py"), *args], capture_output=True,
                          text=True, env=env, cwd=cwd, timeout=60)


def test_python_shim_runs_the_cli():
    result = run_shim(["--version"])
    assert result.returncode == 0 and result.stdout.strip() == f"njli {__version__}"


def test_python_shim_on_fake_39_prints_one_message_and_exits_1():
    result = run_shim(["--version"], {"NJLI_TEST": "1", "NJLI_FAKE_PYVER": "3.9.18"})
    assert result.returncode == 1 and result.stdout == ""
    assert result.stderr.count("njli needs Python 3.10") == 1
    assert result.stderr.count("Fix:") == 1


def test_fake_version_hook_is_ignored_outside_test_mode():
    result = run_shim(["--version"], {"NJLI_FAKE_PYVER": "3.9.18"})
    assert result.returncode == 0


def test_module_entry_runs():
    env = dict(os.environ, PYTHONUTF8="1", PYTHONPATH=str(REPO))
    result = subprocess.run([sys.executable, "-m", "njli", "--version"], capture_output=True,
                            text=True, env=env, cwd=str(REPO), timeout=60)
    assert result.returncode == 0 and "njli" in result.stdout


@pytest.mark.skipif(shutil.which("sh") is None, reason="needs a POSIX shell")
def test_sh_shim_runs_with_override():
    result = subprocess.run([shutil.which("sh"), str(BIN / "njli"), "--version"],
                            capture_output=True, text=True, timeout=60,
                            env=dict(os.environ, NJLI_PYTHON=sys.executable, PYTHONUTF8="1"))
    assert result.returncode == 0 and f"njli {__version__}" in result.stdout


@pytest.mark.skipif(sys.platform == "win32" or shutil.which("sh") is None,
                    reason="PATH-hiding test is POSIX only")
def test_sh_shim_with_only_python_39_prints_the_fix(tmp_path):
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    fake = fakebin / "python3"
    fake.write_text('#!/bin/sh\ncase "$*" in\n  *sys.exit*) exit 1;;\n  *) echo 3.9.18;;\nesac\n')
    fake.chmod(0o755)
    for tool in ("dirname", "uname", "cat"):
        found = shutil.which(tool)
        if found:
            (fakebin / tool).symlink_to(found)
    result = subprocess.run([shutil.which("sh"), str(BIN / "njli"), "--version"],
                            capture_output=True, text=True, timeout=60,
                            env={"PATH": str(fakebin), "HOME": str(tmp_path)})
    assert result.returncode == 1
    assert "Python 3.9.18" in result.stderr and result.stderr.count("Fix:") == 1


@pytest.mark.skipif(sys.platform != "win32", reason="Windows launcher")
def test_cmd_shim_runs_and_reports_no_python(tmp_path):
    result = subprocess.run(["cmd", "/c", str(BIN / "njli.cmd"), "--version"],
                            capture_output=True, text=True, timeout=60,
                            env=dict(os.environ, NJLI_PYTHON=sys.executable, PYTHONUTF8="1"))
    assert result.returncode == 0 and f"njli {__version__}" in result.stdout
    system_root = os.environ["SystemRoot"]
    env = {"SystemRoot": system_root, "PATH": os.path.join(system_root, "System32")}
    result = subprocess.run(["cmd", "/c", str(BIN / "njli.cmd"), "--version"],
                            capture_output=True, text=True, timeout=60, env=env)
    assert result.returncode == 1
    assert "winget" in result.stderr and result.stderr.count("Fix:") == 1


def test_cmd_shim_is_crlf_and_sh_shim_is_lf():
    assert b"\r\n" in (BIN / "njli.cmd").read_bytes()
    assert b"\r\n" not in (BIN / "njli").read_bytes()
    assert (BIN / "njli").read_bytes().startswith(b"#!/bin/sh")


# --------------------------------------------------------------------- runtime

def bare_env() -> dict:
    """A scheduler-like environment: only what Python itself needs (Windows keys are upper case)."""
    keep = {"SYSTEMROOT", "PATH", "TEMP", "TMP", "HOME"}
    return {k: v for k, v in os.environ.items() if k.upper() in keep}


@pytest.fixture()
def data(tmp_path) -> Path:
    return tmp_path / "rt-data"


def test_install_makes_current_that_a_fake_scheduler_can_run(data, tmp_path):
    info = runtime.install(data=data)
    current = data / "runtime" / "current"
    assert info["version"] == __version__ and current.exists()
    assert (current / "__main__.py").is_file() and (current / "njli" / "cli.py").is_file()
    assert (current / "schema" / "config.schema.json").is_file()
    assert (current / "RUNTIME.json").is_file()
    assert not list(current.rglob("__pycache__"))
    assert (data / "runtime" / "current.version").read_text().strip() == __version__
    # the fake scheduler: a bare environment, another working directory, the stored command
    cmd = runtime.entry_command(data)
    assert cmd[1] == str(current)
    env = bare_env()
    env["NJLI_DATA_DIR"] = str(data)
    result = subprocess.run([*cmd, "--version"], capture_output=True, text=True, cwd=str(tmp_path),
                            env=env, timeout=60)
    assert result.returncode == 0 and result.stdout.strip() == f"njli {__version__}"
    # it also runs a real command, reading templates and schemas from its own copy
    result = subprocess.run([*cmd, "handoff", "check", str(REPO / "templates" / "handoff.template.md"),
                             "--json"], capture_output=True, text=True, cwd=str(tmp_path), env=env,
                            timeout=60)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["ok"] is True


def test_runtime_copy_does_not_depend_on_the_source_tree(data, tmp_path):
    runtime.install(data=data)
    current = data / "runtime" / "current"
    env = bare_env()
    env.update(NJLI_DATA_DIR=str(data), NJLI_CONFIG_DIR=str(tmp_path / "c"), PYTHONUTF8="1")
    result = subprocess.run([sys.executable, str(current), "config", "--help"],
                            capture_output=True, text=True, cwd=str(tmp_path), env=env, timeout=60)
    assert result.returncode == 0, result.stderr


def test_status_and_drift(data):
    st = runtime.status(data=data)
    assert st["drift"] is True and "no stable runtime" in st["reason"] and st["current"] is None
    assert st["entry"] is None and st["installed"] == []
    runtime.install(data=data)
    st = runtime.status(data=data)
    assert st["drift"] is False and st["current"] == __version__ and st["entry"]
    assert st["installed"] == [__version__] and st["mode"] in ("symlink", "copy")


def test_drift_when_the_code_changes_and_sync_repairs_it(data, tmp_path):
    root = tmp_path / "srcroot"
    shutil.copytree(REPO / "njli", root / "njli", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(REPO / "data", root / "data")
    runtime.install(plugin_root=root, data=data)
    assert runtime.status(root, data)["drift"] is False
    assert runtime.sync(root, data)["action"] == "unchanged"
    (root / "njli" / "limits.py").write_text(
        (root / "njli" / "limits.py").read_text(encoding="utf-8") + "\n# patched\n", encoding="utf-8")
    st = runtime.status(root, data)
    assert st["drift"] is True and "code changed" in st["reason"]
    assert runtime.sync(root, data)["action"] == "installed"
    assert runtime.status(root, data)["drift"] is False
    assert "# patched" in (data / "runtime" / "current" / "njli" / "limits.py").read_text(
        encoding="utf-8")


def test_version_drift_is_reported(data, monkeypatch):
    runtime.install(data=data)
    monkeypatch.setattr(runtime, "__version__", "9.9.9")
    st = runtime.status(data=data)
    assert st["drift"] is True and "9.9.9" in st["reason"]


def test_reinstall_same_version_replaces_the_copy(data):
    runtime.install(data=data)
    marker = data / "runtime" / __version__ / "stale-file.txt"
    marker.write_text("x")
    runtime.install(data=data)
    assert not marker.exists()
    assert not list((data / "runtime").glob("*.tmp"))


def test_install_without_the_package_is_refused(data, tmp_path):
    with pytest.raises(FileNotFoundError):
        runtime.install(plugin_root=tmp_path / "empty", data=data)
    assert not list((data / "runtime").glob("*.tmp"))


def test_old_versions_are_pruned(data):
    rt = data / "runtime"
    for v in ("0.0.1", "0.0.2", "0.0.3", "0.0.4"):
        (rt / v).mkdir(parents=True)
    runtime.install(data=data)
    left = runtime.installed_versions(rt)
    assert __version__ in left and "0.0.1" not in left and "0.0.2" not in left
    assert "0.0.4" in left and "0.0.3" in left


def test_pyz_is_copied_and_preferred(data, tmp_path):
    pyz = tmp_path / "njli.pyz"
    pyz.write_bytes(b"PK-not-really")
    runtime.install(data=data, pyz=pyz)
    assert (data / "runtime" / "current" / "njli.pyz").is_file()
    assert runtime.entry_command(data)[1].endswith("njli.pyz")


def test_point_current_replaces_an_existing_link_or_dir(data):
    rt = data / "runtime"
    (rt / "1.0").mkdir(parents=True)
    (rt / "1.0" / "f.txt").write_text("one")
    (rt / "2.0").mkdir()
    (rt / "2.0" / "f.txt").write_text("two")
    runtime.point_current(rt, "1.0")
    assert (rt / "current" / "f.txt").read_text() == "one"
    runtime.point_current(rt, "2.0")
    assert (rt / "current" / "f.txt").read_text() == "two"
    assert (rt / "1.0" / "f.txt").read_text() == "one"            # the old version is untouched
    assert runtime.current_version(rt) == "2.0"


def test_copy_fallback_when_links_are_impossible(data, monkeypatch):
    rt = data / "runtime"
    (rt / "1.0").mkdir(parents=True)
    (rt / "1.0" / "f.txt").write_text("one")

    def no_links(*a, **k):
        raise OSError("symlinks not permitted")

    monkeypatch.setattr(runtime.os, "symlink", no_links)
    if sys.platform == "win32":
        monkeypatch.setattr(runtime.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
            a, 1, stdout="", stderr="denied"))
    assert runtime.point_current(rt, "1.0") == "copy"
    assert (rt / "current" / "f.txt").read_text() == "one"
    runtime.point_current(rt, "1.0")                               # replacing a copy works too
    assert runtime.current_version(rt) == "1.0"


def test_version_key_orders_numerically():
    assert sorted(["0.10.0", "0.9.0", "0.2.0"], key=runtime._version_key) == [
        "0.2.0", "0.9.0", "0.10.0"]


def test_current_version_falls_back_to_runtime_json(data):
    rt = data / "runtime"
    (rt / "current").mkdir(parents=True)
    (rt / "current" / "RUNTIME.json").write_text(json.dumps({"version": "3.3.3"}))
    assert runtime.current_version(rt) == "3.3.3"
    assert runtime.current_version(data / "none") is None
