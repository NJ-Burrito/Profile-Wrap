"""``profile-wrap demo run|up|down``: walk the whole pipeline on the fictional persona, offline.

``demo run`` seeds Maya Rivera (fictional) into a temp workspace and walks one week of the pipeline:

    1. init --demo, doctor, facts lint, gate (a pass, an Arabic pass, and a deliberate fail)
    2. the sample GIF (Node and ffmpeg are optional; the text and slides lane needs neither)
    3. board health check, then Allow from the command line
    4. post to the fake LinkedIn on 127.0.0.1, then ``due`` against the same fake
    5. a post draft, a comment draft and a connect shortlist from the fake ``claude``
    6. schedule install --dry-run, leaks scan

Nothing leaves the machine: the HTTP layer talks to ``127.0.0.1`` only, the model is
``profile_wrap.demo.fake_claude``, and the config and data folders are temp folders. It exits 0 only when
every step passed. ``demo up`` starts the fake LinkedIn on a free port; ``demo down`` stops it.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from .. import paths, policy

HERE = Path(__file__).resolve().parent
FAKE_CLAUDE = HERE / "fake_claude.py"
FAKE_SERVER = HERE / "fake_linkedin.py"
PASS_SLUG = "weekly-review-in-30-minutes"
AR_SLUG = "unopened-dashboard-ar"
HOLD_SLUG = "a-chart-nobody-asked-for"
GIF_SLUG = "dashboard-three-numbers-too-many"
NEW_SLUG = "faster-handoffs"
STATE_FILE = "demo-server.json"


class Report:
    def __init__(self) -> None:
        self.rows: List[Dict[str, str]] = []

    def add(self, status: str, step: str, detail: str = "") -> None:
        self.rows.append({"status": status, "step": step, "detail": detail})
        print(f"{status:<5} {step}" + (f"  ({detail})" if detail else ""), flush=True)

    @property
    def failed(self) -> List[Dict[str, str]]:
        return [r for r in self.rows if r["status"] == "FAIL"]


def _env(extra: Dict[str, str]) -> Dict[str, str]:
    env = dict(os.environ)
    env.update(extra)
    env["PYTHONUTF8"] = "1"
    src = str(Path(__file__).resolve().parents[2])
    env["PYTHONPATH"] = src + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    return env


def _profile_wrap(args: List[str], env: Dict[str, str], timeout: float = 180.0) -> "subprocess.CompletedProcess[str]":
    return subprocess.run([sys.executable, "-m", "profile_wrap"] + args, env=env, capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=timeout)


def _tail(proc: "subprocess.CompletedProcess[str]", n: int = 300) -> str:
    return ((proc.stderr or "") + (proc.stdout or "")).strip().replace("\n", " | ")[-n:]


@contextlib.contextmanager
def _patched_env(values: Dict[str, str]) -> Iterator[None]:
    saved = {k: os.environ.get(k) for k in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for k, old in saved.items():
            if old is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------- steps

def run_demo(root: Path, report: Optional[Report] = None) -> Report:
    """Run every step inside ``root`` (an empty folder). Returns the report; never raises for a step."""
    report = report or Report()
    ws = root / "workspace"
    cfg_dir, data_dir = root / "config", root / "data"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    iso = {"PROFILE_WRAP_CONFIG_DIR": str(cfg_dir), "PROFILE_WRAP_DATA_DIR": str(data_dir), "PROFILE_WRAP_HOME": str(root / "home"),
           "PROFILE_WRAP_TEST": "1"}
    env = _env({**iso})
    env.pop("PROFILE_WRAP_WORKSPACE", None)

    def cli(args: List[str], expect: int = 0, step: str = "", ok_detail: str = "") -> bool:
        proc = _profile_wrap(args + ["--workspace", str(ws)] if args[0] != "init" else args, env)
        good = proc.returncode == expect
        label = step or "profile-wrap " + " ".join(args)
        report.add("PASS" if good else "FAIL", label,
                   ok_detail if good else f"exit {proc.returncode}, wanted {expect}: {_tail(proc)}")
        return good

    # 1. workspace, doctor, facts, gates
    proc = _profile_wrap(["init", "--demo", "--yes", str(ws)], env)
    if proc.returncode != 0 or not (ws / "config" / "profile-wrap.json").is_file():
        report.add("FAIL", "init --demo --yes", _tail(proc))
        return report
    report.add("PASS", "init --demo --yes", "Maya Rivera, fictional, " + str(sum(1 for _ in ws.rglob("*.*"))) + " files")

    proc = _profile_wrap(["doctor", "--workspace", str(ws), "--json"], env)
    try:
        checks = json.loads(proc.stdout).get("checks", [])
        tally = {s: sum(1 for c in checks if c.get("status") == s) for s in ("pass", "warn", "fail")}
        report.add("PASS" if proc.returncode in (0, 1) else "FAIL", "doctor",
                   f"{tally['pass']} pass, {tally['warn']} warn, {tally['fail']} fail (machine checks, not demo faults)")
    except ValueError:
        report.add("FAIL", "doctor", _tail(proc))
    cli(["facts", "lint"], step="facts lint")

    for slug, want in ((PASS_SLUG, "PASS"), (AR_SLUG, "PASS"), (HOLD_SLUG, "FAIL")):
        proc = _profile_wrap(["gate", slug, "--workspace", str(ws), "--json"], env)
        try:
            summary = json.loads(proc.stdout).get("summary")
        except ValueError:
            summary = _tail(proc)
        what = "gate " + slug
        if want == "FAIL":
            what += " (private term, fails on purpose)"
        report.add("PASS" if summary == want else "FAIL", what, str(summary))

    # 2. visuals: the pre-rendered sample, so the text lane never needs Node
    gif = ws / "drafts" / GIF_SLUG / "out" / "sample.gif"
    node = shutil.which("node") and shutil.which("ffmpeg")
    if gif.is_file() and gif.read_bytes()[:6] in (b"GIF87a", b"GIF89a"):
        report.add("PASS", "sample GIF", f"{gif.stat().st_size} bytes; "
                   + ("Node and ffmpeg found, full render is `profile-wrap render`" if node
                      else "no Node or ffmpeg: the sample is used, the text lane still works"))
    else:
        report.add("FAIL", "sample GIF", f"missing or not a GIF: {gif}")

    # 3. board health, Allow from the CLI
    try:
        from ..board.server import BoardServer, probe_health
        with _patched_env(iso):
            server = BoardServer(ws, port=0)
            server.prepare()
            server.start_background()
            try:
                health = probe_health(server.port, timeout=5.0)
            finally:
                server.shutdown()
        report.add("PASS" if health else "FAIL", "board health", f"127.0.0.1:{server.port}" if health else "no answer")
    except Exception as exc:  # report, do not crash the walk
        report.add("FAIL", "board health", f"{type(exc).__name__}: {exc}")
    if not cli(["review", "allow", PASS_SLUG, "--yes"], step="review allow " + PASS_SLUG):
        return report

    # 4. fake LinkedIn: post, then due
    from . import fake_linkedin
    from ..linkedin import auth
    fake = fake_linkedin.FakeLinkedIn().start()
    try:
        cfg = json.loads((ws / "config" / "profile-wrap.json").read_text(encoding="utf-8"))
        tok_dir = cfg_dir / cfg.get("profile_id", "demo")
        auth.save_token(tok_dir, {"access_token": "DEMO-TOKEN-NOT-REAL", "author": "urn:li:person:DEMO000000",
                                  "name": "Maya Rivera (fictional)", "expires_at": time.time() + 30 * 86400})
        post_env = dict(env, PROFILE_WRAP_LINKEDIN_BASE=fake.base_url)
        proc = _profile_wrap(["post", PASS_SLUG, "--now", "--workspace", str(ws)], post_env)
        sent = len(fake.calls("POST", "/rest/posts"))
        report.add("PASS" if proc.returncode == 0 and sent == 1 else "FAIL",
                   "post --now to the fake LinkedIn",
                   f"{sent} post received on {fake.base_url}" if proc.returncode == 0 else _tail(proc))
        with _patched_env({**iso, "PROFILE_WRAP_LINKEDIN_BASE": fake.base_url}):
            from ..linkedin import due as due_mod
            from .. import config as config_mod, notify as notify_mod

            def quiet(title: str, message: str, workspace: Any = None, mode: str = "log") -> str:
                return notify_mod.notify(title, message, workspace, mode="log")

            original = due_mod.notify
            due_mod.notify = quiet
            try:
                outcome = due_mod.run_due(ws, config_mod.load(ws))
            finally:
                due_mod.notify = original
        report.add("PASS" if outcome.status in ("skipped", "ok", "posted") else "FAIL",
                   "due against the fake", f"{outcome.status}: {outcome.reason}"[:120])
    except Exception as exc:
        report.add("FAIL", "fake LinkedIn", f"{type(exc).__name__}: {exc}")
    finally:
        fake.stop()

    # 5. the fake claude: a post draft, a comment draft, a connect shortlist
    try:
        from .. import claude_runner, config as config_mod
        cfg = config_mod.load(ws)
        exe = [sys.executable, str(FAKE_CLAUDE)]
        with _patched_env(iso):
            jobs = (("draft", "build", f"drafts/{NEW_SLUG}/**", [f"drafts/{NEW_SLUG}/caption.txt"]),
                    ("comment", "comment", "engage/reports/**", ["engage/reports/demo-comment.md"]),
                    ("shortlist", "engage", "engage/reports/**", ["engage/reports/demo-connect-shortlist.md"]))
            for task, kind, allow, expect in jobs:
                prompt = f"ROOT: {ws}\nTASK: {task}\nSLUG: {NEW_SLUG}\n"
                res = claude_runner.run_worker(ws, cfg, job=f"demo-{task}", kind=kind, prompt=prompt,
                                               allow=[allow], expect=expect, exe=exe, timeout=60)
                report.add("PASS" if res.ok else "FAIL", f"fake claude: {task}",
                           "no model, no network" if res.ok else f"{res.status}: {res.err[:160]}")
        proc = _profile_wrap(["gate", NEW_SLUG, "--workspace", str(ws), "--json"], env)
        summary = json.loads(proc.stdout).get("summary") if proc.stdout.strip().startswith("{") else _tail(proc)
        report.add("PASS" if summary == "PASS" else "FAIL", "gate on the fake claude's draft", str(summary))
    except Exception as exc:
        report.add("FAIL", "fake claude", f"{type(exc).__name__}: {exc}")

    # 6. scheduling preview and the leak scan
    cli(["schedule", "install", "--dry-run"], step="schedule install --dry-run")
    allow_file = root / "leak-allow.demo.json"
    allow_file.write_text(json.dumps({"version": 1, "allow": [{
        "rule": "media-unlisted", "sha256": _sha(gif) if gif.is_file() else "0" * 64,
        "reason": "fictional demo sample GIF, generated by examples/make_demo_gif.py"}]}), encoding="utf-8")
    proc = _profile_wrap(["leaks", "scan", "--tree", str(ws), "--allow", str(allow_file)], env)
    report.add("PASS" if proc.returncode == 0 else "FAIL", "leaks scan --tree (demo workspace)",
               "" if proc.returncode == 0 else _tail(proc))
    return report


# ---------------------------------------------------------------------------- commands

def _cmd_run(args: argparse.Namespace) -> int:
    base = Path(args.dir) if args.dir else None
    if base is not None:
        base.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="profile-wrap-demo-", dir=str(base) if base else None)
    root = Path(tmp)
    print(f"profile-wrap demo run: fictional persona Maya Rivera, folder {root}\n", flush=True)
    started = time.time()
    try:
        report = run_demo(root)
    finally:
        if not args.keep:
            shutil.rmtree(tmp, ignore_errors=True)
    failed = report.failed
    print(f"\n{len(report.rows) - len(failed)} of {len(report.rows)} steps passed in {time.time() - started:.0f} s."
          + (f" Kept: {root}" if args.keep else ""))
    if args.json:
        print(json.dumps({"ok": not failed, "steps": report.rows}, indent=2))
    return policy.EXIT_FAIL if failed else policy.EXIT_OK


def _state_path() -> Path:
    return paths.data_dir() / STATE_FILE


def _cmd_up(args: argparse.Namespace) -> int:
    state = _state_path()
    if state.is_file():
        print(f"profile-wrap demo up: already running ({state.read_text(encoding='utf-8').strip()}). Run `profile-wrap demo down` first.",
              file=sys.stderr)
        return policy.EXIT_FAIL
    port = args.port or 0
    detach: Dict[str, Any] = ({"creationflags": 0x00000008 | 0x00000200} if sys.platform == "win32"
                              else {"start_new_session": True})
    # stdin, stderr and (after the first line) stdout are not shared with the caller, so a script that
    # waits for this command's output to end is not held open by the server that keeps running.
    proc = subprocess.Popen([sys.executable, "-u", str(FAKE_SERVER), "--port", str(port)], stdout=subprocess.PIPE,
                            stdin=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True, env=_env({}),
                            **detach)
    line = proc.stdout.readline().strip() if proc.stdout else ""
    if proc.stdout:
        proc.stdout.close()
    if not line.startswith("fake LinkedIn on "):
        proc.kill()
        print("profile-wrap demo up: the fake server did not start", file=sys.stderr)
        return policy.EXIT_FAIL
    base = line.split(" on ", 1)[1]
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(json.dumps({"pid": proc.pid, "base_url": base}), encoding="utf-8")
    print(f"fake LinkedIn on {base} (pid {proc.pid}). Stop it with `profile-wrap demo down`.")
    print(f"point the client at it: PROFILE_WRAP_TEST=1 PROFILE_WRAP_LINKEDIN_BASE={base}")
    return policy.EXIT_OK


def _cmd_down(args: argparse.Namespace) -> int:
    state = _state_path()
    if not state.is_file():
        print("profile-wrap demo down: nothing running")
        return policy.EXIT_OK
    try:
        pid = int(json.loads(state.read_text(encoding="utf-8"))["pid"])
    except (OSError, ValueError, KeyError):
        pid = 0
    if pid:
        try:
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
            else:
                os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    state.unlink(missing_ok=True)
    print(f"profile-wrap demo down: stopped pid {pid}")
    return policy.EXIT_OK


def register(subparsers: Any) -> None:
    p = subparsers.add_parser("demo", help="walk the pipeline on a fictional persona, offline")
    sub = p.add_subparsers(dest="demo_cmd", required=True)
    r = sub.add_parser("run", help="init --demo plus a whole fictional week; exits 0 when every step passed")
    r.add_argument("--keep", action="store_true", help="keep the temp folder when done")
    r.add_argument("--dir", help="make the temp folder inside this folder")
    r.add_argument("--json", action="store_true", help="also print the steps as JSON")
    r.set_defaults(func=_cmd_run)
    u = sub.add_parser("up", help="start the fake LinkedIn on a free local port")
    u.add_argument("--port", type=int, help="port (default: a free one)")
    u.set_defaults(func=_cmd_up)
    d = sub.add_parser("down", help="stop the fake LinkedIn that `demo up` started")
    d.set_defaults(func=_cmd_down)
