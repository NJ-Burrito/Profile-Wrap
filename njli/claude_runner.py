"""The only place a Claude worker is started (design-spec section 13, "Worker containment").

A worker is a headless ``claude -p`` run that:

* runs in ``work/sandbox/<job>/`` holding only its briefed inputs;
* gets its prompt on stdin, never in argv, and a scrubbed environment (``env_allow`` plus the few
  variables an OS needs to start a process);
* is started with an explicit tool list and a ``--disallowedTools`` list; no content worker gets
  Bash, and no worker gets Agent, SendMessage or a shell of any kind;
* is watched by the whole-tree allowlist guard (:mod:`njli.sandbox`): anything outside its allowlist
  is put back, and a token-shaped string in its output discards the output and fails the job;
* is killed with its whole process tree on a timeout.

Binary discovery, the flag probe (``njli claude probe``) and the failure statuses live here too.
Nothing in this module names a model: the alias comes from ``config.models``.
"""
from __future__ import annotations

import datetime as _dt
import glob
import json
import os
import re
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from . import paths, policy, sandbox
from .atomic import atomic_write_json
from .fsutil import append_jsonl
from .schedule.proctree import run_tree

# --------------------------------------------------------------------------- policy

# Result statuses. Only "ok" and "dry_run" are successes.
OK, DRY_RUN = "ok", "dry_run"
FAILED, TIMEOUT, MISSING_OUTPUT = "failed", "timeout", "missing_output"
SECRET_OUTPUT, GUARD_FAILED = "secret_output", "guard_failed"
NO_CLAUDE, UNSUPPORTED_FLAGS, BAD_ARGS = "no_claude", "unsupported_flags", "bad_args"

# kind -> (tier, tools, may edit, config key for turns, config key for timeout)
KINDS: Dict[str, Dict[str, Any]] = {
    "build": {"tier": "standard", "tools": ("Read", "Glob", "Grep", "Write"),
              "turns": "build", "timeout": "build"},
    "improve": {"tier": "standard", "tools": ("Read", "Glob", "Grep", "Write", "Edit"),
                "turns": "build", "timeout": "fix"},
    "fix": {"tier": "standard", "tools": ("Read", "Glob", "Grep", "Write", "Edit"),
            "turns": "build", "timeout": "fix"},
    "review": {"tier": "standard", "tools": ("Read", "Glob", "Grep", "Write"),
               "turns": "review", "timeout": "review"},
    "research": {"tier": "standard",
                 "tools": ("Read", "Glob", "Grep", "Write", "WebSearch", "WebFetch"),
                 "turns": "review", "timeout": "review"},
    "engage": {"tier": "economy", "tools": ("Read", "Glob", "Grep", "Write"),
               "turns": "comment", "timeout": "engage"},
    "comment": {"tier": "economy", "tools": ("Read", "Glob", "Grep", "Write"),
                "turns": "comment", "timeout": "engage"},
}
EDIT_KINDS = ("improve", "fix")
WEB_KINDS = ("research",)
ALWAYS_DENIED = ("Bash", "PowerShell", "Agent", "Task", "SendMessage", "NotebookEdit", "KillShell")
CONTENT_DENIED_EXTRA = ("WebFetch", "WebSearch")

REQUIRED_FLAGS = ("--max-turns", "--allowedTools", "--disallowedTools", "--permission-mode")
OPTIONAL_FLAGS = ("--effort", "--max-budget-usd", "--add-dir", "--settings", "--output-format",
                  "--no-session-persistence", "--model")
PROBE_FILE = "cli-probe.json"

# Variables an OS needs to start a process. None of them holds a credential.
OS_ENV = ("SystemRoot", "SYSTEMDRIVE", "COMSPEC", "PATHEXT", "TEMP", "TMP", "TMPDIR", "APPDATA",
          "LOCALAPPDATA", "PROGRAMDATA", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "SHELL", "USER",
          "LOGNAME", "LC_ALL")


class ToolPolicyError(ValueError):
    """A job asked for a tool or a kind it may not have."""


class PromptError(ValueError):
    """A prompt template has an unresolved placeholder."""


# Job exit codes by status, for callers that want one integer (the board adapter, the CLI).
STATUS_CODES = {OK: 0, DRY_RUN: 0, FAILED: 1, BAD_ARGS: 2, MISSING_OUTPUT: 3, SECRET_OUTPUT: 5,
                GUARD_FAILED: 6, TIMEOUT: 124, NO_CLAUDE: 127, UNSUPPORTED_FLAGS: 126}


@dataclass
class WorkerResult:
    status: str
    proc_rc: int = 0
    text: str = ""
    err: str = ""
    cost: Optional[float] = None
    seconds: float = 0.0
    model: str = ""
    restored: List[str] = field(default_factory=list)
    unrestorable: List[str] = field(default_factory=list)
    changed: List[str] = field(default_factory=list)   # files the worker legitimately wrote
    findings: List[sandbox.Finding] = field(default_factory=list)
    injection: List[str] = field(default_factory=list)
    missing: List[str] = field(default_factory=list)
    argv: List[str] = field(default_factory=list)
    ran: bool = False

    @property
    def ok(self) -> bool:
        return self.status in (OK, DRY_RUN)

    @property
    def rc(self) -> int:
        """0 on success; otherwise the process code if it failed, else the code of the status."""
        if self.ok:
            return 0
        return self.proc_rc if (self.status == FAILED and self.proc_rc) else STATUS_CODES.get(self.status, 1)

    @property
    def error(self) -> str:
        return "" if self.ok else (self.err or self.status).strip()

    def tail(self, n: int = 1500) -> str:
        return (self.text + "\n" + self.err)[-n:]


# --------------------------------------------------------------------------- prompts

_PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z0-9_.]+)\s*\}\}")


def render_prompt(template: str, values: Mapping[str, Any]) -> str:
    """Fill ``{{name}}`` fields. An unresolved field is an error, never a silent blank."""
    missing: List[str] = []

    def sub(m: "re.Match[str]") -> str:
        key = m.group(1)
        if key in values:
            return str(values[key])
        missing.append(key)
        return m.group(0)

    out = _PLACEHOLDER.sub(sub, template)
    if missing:
        raise PromptError("unresolved placeholders: " + ", ".join(sorted(set(missing))))
    return out


def defang(text: str) -> str:
    """Text for a ``<<<DATA ... DATA>>>`` block in a template: the markers cannot appear inside it."""
    return (str(text).replace("DATA>>>", "DATA> >>").replace("<<<DATA", "<< <DATA")
            .replace("NOTE>>>", "NOTE> >>").replace("<<<NOTE", "<< <NOTE"))


def untrusted(text: str) -> str:
    """Wrap text in the data markers (for templates that do not wrap their own field)."""
    return "<<<DATA\n" + defang(text) + "\nDATA>>>"


def load_prompt(workspace: Path, name: str) -> str:
    """The workspace copy (user-editable, three-way merged) wins over the plugin copy."""
    for base in (Path(workspace) / "prompts", paths.resource("prompts")):
        p = base / f"{name}.md"
        if p.is_file():
            return p.read_text(encoding="utf-8")
    raise FileNotFoundError(f"prompt template not found: {name}.md")


def prompt_body(template: str) -> str:
    """Prompt templates start with a title and a note; the body follows the first ``---`` rule."""
    parts = re.split(r"^---\s*$", template, maxsplit=1, flags=re.M)
    return parts[1].lstrip("\n") if len(parts) == 2 else template


# --------------------------------------------------------------------------- tools and model

def tools_for(kind: str) -> List[str]:
    if kind not in KINDS:
        raise ToolPolicyError(f"unknown job kind: {kind} (known: {', '.join(sorted(KINDS))})")
    return list(KINDS[kind]["tools"])


def validate_tools(kind: str, tools: Iterable[str]) -> List[str]:
    """Refuse any tool a kind may not have. Returns the cleaned list."""
    spec = KINDS.get(kind)
    if spec is None:
        raise ToolPolicyError(f"unknown job kind: {kind}")
    out = []
    for t in tools:
        t = t.strip()
        if not t:
            continue
        base = t.split("(")[0]
        if base in ALWAYS_DENIED:
            raise ToolPolicyError(f"{base} is never allowed for a worker ({kind})")
        if base == "Edit" and kind not in EDIT_KINDS:
            raise ToolPolicyError(f"Edit is only for {', '.join(EDIT_KINDS)}, not {kind}")
        if base in CONTENT_DENIED_EXTRA and kind not in WEB_KINDS:
            raise ToolPolicyError(f"{base} is only for research workers, not {kind}")
        out.append(t)
    if not out:
        raise ToolPolicyError("a worker needs an explicit, non-empty tool list")
    return out


def disallowed_for(kind: str) -> List[str]:
    denied = list(ALWAYS_DENIED)
    if kind not in WEB_KINDS:
        denied += list(CONTENT_DENIED_EXTRA)
    if kind not in EDIT_KINDS:
        denied.append("Edit")
    return denied


def resolve_model(cfg: Mapping[str, Any], tier: str) -> Dict[str, str]:
    """Model alias and effort for a tier, from ``config.models``. The lead tier is the user's own."""
    if tier not in ("standard", "economy"):
        raise ToolPolicyError(f"workers run on the standard or economy tier, not {tier!r}")
    models = cfg.get("models", {})
    if models.get("mode") == "single":
        one = models.get("single", {})
        return {"alias": str(one.get("alias", "")), "effort": str(one.get("effort", "medium"))}
    entry = models.get(tier, {})
    return {"alias": str(entry.get("alias", "")), "effort": str(entry.get("effort", "medium"))}


EFFORT_ORDER = ("low", "medium", "high")


def agent_effort(cfg: Mapping[str, Any], tier: str, template_effort: Optional[str]) -> str:
    """Per-agent effort: the template's own, capped by the single-tier effort in single mode."""
    base = resolve_model(cfg, tier)["effort"]
    eff = template_effort or base
    if cfg.get("models", {}).get("mode") == "single" and eff in EFFORT_ORDER and base in EFFORT_ORDER:
        eff = EFFORT_ORDER[min(EFFORT_ORDER.index(eff), EFFORT_ORDER.index(base))]
    return eff


# --------------------------------------------------------------------------- binary and probe

def _version_key(path: str) -> tuple:
    m = re.search(r"claude-code-(\d+(?:\.\d+)*)", path.replace("\\", "/"))
    return tuple(int(x) for x in m.group(1).split(".")) if m else ()


def find_claude(cfg: Optional[Mapping[str, Any]] = None,
                env: Optional[Mapping[str, str]] = None,
                home: Optional[Path] = None) -> Optional[str]:
    """``models.runner.bin``, ``NJLI_CLAUDE_BIN``, PATH, ``~/.claude/local``, then the editor extension."""
    env = os.environ if env is None else env
    home = home or paths.home()
    configured = ((cfg or {}).get("models", {}).get("runner", {}) or {}).get("bin")
    for candidate in (configured, env.get("NJLI_CLAUDE_BIN")):
        if candidate and Path(candidate).exists():
            return str(candidate)
    found = shutil.which("claude", path=env.get("PATH"))
    if found:
        return found
    for name in ("claude", "claude.exe", "claude.cmd"):
        p = home / ".claude" / "local" / name
        if p.is_file():
            return str(p)
    pattern = str(home / ".vscode*" / "extensions" / "anthropic.claude-code-*" /
                  "resources" / "native-binary" / "claude*")
    hits = sorted((h for h in glob.glob(pattern) if Path(h).is_file()), key=_version_key)
    return hits[-1] if hits else None


def probe_path(profile: str) -> Path:
    return paths.config_dir(profile) / PROBE_FILE


def probe(binary: "str | Sequence[str]", *, timeout: float = 60.0,
          env: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
    """Ask the CLI which flags it knows (``--help``) and record its version.

    ``binary`` is a path or a command given as several words (tests run ``python fake_claude.py``).
    """
    parts = [binary] if isinstance(binary, str) else list(binary)
    base_env = dict(os.environ if env is None else env)
    help_res = run_tree(parts + ["--help"], timeout=timeout, env=base_env)
    ver_res = run_tree(parts + ["--version"], timeout=timeout, env=base_env)
    text = help_res.stdout + help_res.stderr
    flags = {f: (f in text) for f in REQUIRED_FLAGS + OPTIONAL_FLAGS}
    flags["-p/--print"] = ("--print" in text) or bool(re.search(r"(^|\s)-p[,\s]", text))
    return {
        "schema_version": policy.SCHEMA_VERSION,
        "bin": " ".join(parts),
        "version": (ver_res.stdout.strip() or ver_res.stderr.strip())[:80],
        "help_rc": help_res.rc,
        "checked_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "flags": flags,
    }


def missing_required(result: Mapping[str, Any]) -> List[str]:
    flags = result.get("flags", {})
    need = list(REQUIRED_FLAGS) + ["-p/--print"]
    return [f for f in need if not flags.get(f)]


def load_probe(profile: str, parts: Sequence[str]) -> Optional[Dict[str, Any]]:
    try:
        data = json.loads(probe_path(profile).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if data.get("bin") != " ".join(parts):
        return None
    try:
        stamp = _dt.datetime.fromisoformat(data["checked_at"]).timestamp()
        if any(os.path.isfile(x) and os.path.getmtime(x) > stamp for x in parts):
            return None  # the binary (or the fake script) changed after the probe
    except (OSError, KeyError, ValueError):
        return None
    return data


# --------------------------------------------------------------------------- environment

def scrub_env(cfg: Mapping[str, Any], source: Optional[Mapping[str, str]] = None,
              extra: Optional[Mapping[str, str]] = None) -> Dict[str, str]:
    """Only ``env_allow`` (plus what an OS needs to start a process). No LinkedIn secrets, no shell tokens."""
    src = os.environ if source is None else source
    runner = (cfg.get("models", {}) or {}).get("runner", {}) or {}
    allow = list(runner.get("env_allow") or [])
    lower = {k.lower(): k for k in src}
    env: Dict[str, str] = {}
    for name in allow + list(OS_ENV):
        key = lower.get(name.lower())
        if key is not None:
            env[name if sys.platform != "win32" else key] = src[key]
    if runner.get("auth") == "api_key" and runner.get("api_key_env"):
        value = src.get(runner["api_key_env"])
        if value:
            env["ANTHROPIC_API_KEY"] = value
    env["PYTHONUTF8"] = "1"
    env[policy.WORKER_ENV] = "1"
    if extra:
        env.update(extra)
    return env


def settings_for(workspace: Path, profile: str, extra_deny: Sequence[str] = ()) -> Dict[str, Any]:
    """Permission deny rules: the config dir (secrets), ``~/.ssh`` and the workspace's ``.git``."""
    def rule(tool: str, p: Path) -> str:
        return f"{tool}(//{p.as_posix().lstrip('/')}/**)"

    cfg_dir = paths.config_dir(profile)
    ssh = paths.home() / ".ssh"
    git = Path(workspace) / ".git"
    deny = [rule("Read", cfg_dir), rule("Read", ssh), rule("Read", git),
            rule("Write", git), rule("Edit", git), rule("Write", cfg_dir), rule("Edit", cfg_dir)]
    deny += list(extra_deny)
    return {"permissions": {"deny": deny}}


# --------------------------------------------------------------------------- argv

def build_argv(binary: "str | Sequence[str]", *, alias: str, effort: str, tools: Sequence[str],
               disallowed: Sequence[str], max_turns: int, add_dirs: Sequence[Path],
               settings: Optional[Path], flags: Mapping[str, bool],
               max_budget_usd: Optional[float] = None) -> List[str]:
    """The argument vector. The prompt is not in it: it goes through stdin."""
    argv = ([binary] if isinstance(binary, str) else list(binary)) + ["-p", "--model", alias]
    if flags.get("--effort", True) and effort:
        argv += ["--effort", effort]
    argv += ["--max-turns", str(int(max_turns)),
             "--allowedTools", ",".join(tools),
             "--disallowedTools", ",".join(disallowed),
             "--permission-mode", "dontAsk",
             "--output-format", "json"]
    if flags.get("--no-session-persistence", True):
        argv += ["--no-session-persistence"]
    if max_budget_usd is not None and flags.get("--max-budget-usd", True):
        argv += ["--max-budget-usd", f"{float(max_budget_usd):g}"]
    if settings is not None and flags.get("--settings", True):
        argv += ["--settings", str(settings)]
    if add_dirs and flags.get("--add-dir", True):
        argv += ["--add-dir"] + [str(d) for d in add_dirs]
    return argv


def _dirs_from_allow(workspace: Path, allow: Sequence[str]) -> List[Path]:
    out: List[Path] = []
    for pat in allow:
        base = pat[:-3] if pat.endswith("/**") else pat.rstrip("/") if pat.endswith("/") else None
        if base and not any(c in base for c in "*?["):
            p = Path(workspace) / base
            p.mkdir(parents=True, exist_ok=True)
            out.append(p)
    return out


def _text_of(path: Path, cap: int = 2_000_000) -> str:
    try:
        if path.stat().st_size > cap:
            return ""
        return path.read_bytes().decode("utf-8", errors="ignore")
    except OSError:
        return ""


def redact(text: str) -> str:
    for _name, rx in sandbox.SECRET_PATTERNS:
        text = rx.sub("[REDACTED]", text)
    return text


def _log(workspace: Path, row: Dict[str, Any]) -> None:
    try:
        append_jsonl(Path(workspace) / "data" / "logs" / "runner.jsonl", row)
    except OSError:
        pass


# --------------------------------------------------------------------------- the runner

def run_worker(workspace: Path, cfg: Mapping[str, Any], *, job: str, kind: str, prompt: str,
               allow: Sequence[str], expect: Sequence[str] = (), inputs: Optional[Mapping[str, Any]] = None,
               tier: Optional[str] = None, exe: Optional[Sequence[str]] = None,
               timeout: Optional[float] = None, max_turns: Optional[int] = None,
               tools: Optional[Sequence[str]] = None, dry_run: bool = False,
               max_budget_usd: Optional[float] = None, keep_sandbox: bool = False,
               env: Optional[Mapping[str, str]] = None, profile: Optional[str] = None,
               effort: Optional[str] = None) -> WorkerResult:
    """Run one worker under containment. Never raises for a failed worker: read ``.status``.

    ``allow`` lists workspace-relative paths the worker may change (a folder as ``drafts/x/**``,
    a file as ``research/trends/w.md``). ``expect`` lists files that must exist afterwards.
    ``exe`` replaces binary discovery (tests pass the fake CLI here).
    """
    workspace = Path(workspace)
    profile = profile or cfg.get("profile_id", "default")
    try:
        spec = KINDS[kind]
    except KeyError:
        return WorkerResult(BAD_ARGS, err=f"unknown job kind: {kind}")
    try:
        tool_list = validate_tools(kind, tools if tools is not None else tools_for(kind))
        model = resolve_model(cfg, tier or spec["tier"])
        if effort:
            model = dict(model, effort=effort)
    except ToolPolicyError as exc:
        return WorkerResult(BAD_ARGS, err=str(exc))
    runner_cfg = (cfg.get("models", {}) or {}).get("runner", {}) or {}
    turns = int(max_turns or (runner_cfg.get("max_turns") or {}).get(spec["turns"], 20))
    limit = float(timeout or (runner_cfg.get("timeouts_s") or {}).get(spec["timeout"], 900))
    allow = sandbox.normalise_allow(allow)
    if not allow:
        return WorkerResult(BAD_ARGS, err="a worker needs a non-empty allowlist")
    base = WorkerResult(DRY_RUN, model=model["alias"])
    if dry_run:  # no binary lookup, no sandbox, no model call
        base.err = f"dry run: would run {job} ({kind}) on {model['alias']}"
        return base

    binary_parts: Optional[List[str]] = list(exe) if exe else None
    if binary_parts is None:
        found = find_claude(cfg)
        if not found:
            return WorkerResult(NO_CLAUDE, err="claude CLI not found. Set models.runner.bin or "
                                "NJLI_CLAUDE_BIN, or install it (see docs/TROUBLESHOOTING.md)")
        binary_parts = [found]
    cached = load_probe(profile, binary_parts)
    if cached is None:
        try:
            cached = probe(binary_parts, env=scrub_env(cfg))
        except OSError as exc:
            return WorkerResult(NO_CLAUDE, err=f"could not run the claude CLI: {exc}")
        try:
            pf = probe_path(profile)
            pf.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(pf, cached)
        except OSError:
            pass
    missing_flags = missing_required(cached)
    if missing_flags:
        return WorkerResult(UNSUPPORTED_FLAGS, err="this claude CLI lacks required flags: " +
                            ", ".join(missing_flags) + ". Run `njli claude probe` after updating it.")
    flags = dict(cached.get("flags", {}))

    texts = {"settings.json": json.dumps(settings_for(workspace, profile), indent=2)}
    box = sandbox.prepare_sandbox(workspace, job, dict(inputs or {}), texts)
    add_dirs = _dirs_from_allow(workspace, allow)
    argv = build_argv(binary_parts, alias=model["alias"], effort=model["effort"], tools=tool_list,
                      disallowed=disallowed_for(kind), max_turns=turns, add_dirs=add_dirs,
                      settings=box / "settings.json", flags=flags, max_budget_usd=max_budget_usd)
    snap = sandbox.take(workspace)
    started = time.time()
    res = WorkerResult(FAILED, model=model["alias"], argv=argv, ran=True)
    try:
        run = run_tree(argv, input_text=prompt, timeout=limit, cwd=box,
                       env=scrub_env(cfg, extra=env))
    finally:
        guard = sandbox.enforce(snap, allow)  # also after a crash of the runner itself
    res.proc_rc, res.seconds = run.rc, run.seconds
    res.err = redact(run.stderr)[-4000:]
    text, cost = run.stdout, None
    try:
        parsed = json.loads(run.stdout)
        if isinstance(parsed, dict):
            text = str(parsed.get("result") or "")
            cost = parsed.get("total_cost_usd")
            if run.rc == 0 and parsed.get("is_error"):
                res.proc_rc = 1
                res.err += f"\nclaude reported an error: {parsed.get('subtype') or parsed.get('terminal_reason')}"
    except ValueError:
        pass
    res.cost = cost if isinstance(cost, (int, float)) else None
    res.restored = [f"RESTORED {r}" for r in guard.restored]
    res.unrestorable = list(guard.unrestorable)
    res.changed = sorted(guard.allowed.created + guard.allowed.modified)
    res.injection = sandbox.scan_injection(text)

    # Secret scan: the text the worker returned and every file it legitimately wrote.
    findings = sandbox.scan_secrets(run.stdout, "stdout")
    for rel in res.changed:
        findings += sandbox.scan_secrets(_text_of(workspace / rel), rel)
    res.text = redact(text)
    if findings:
        res.findings = findings
        _discard(snap, guard, workspace)
        res.changed = []
        res.status = SECRET_OUTPUT
        res.err += "\nsecret-shaped output discarded: " + ", ".join(f"{f.rule} in {f.where}" for f in findings)
    elif not guard.ok:
        res.status = GUARD_FAILED
        res.err += "\nfiles outside the allowlist could not be restored: " + "; ".join(guard.unrestorable)
    elif run.timed_out:
        res.status = TIMEOUT
        res.err += f"\ntimed out after {limit:g}s; the process tree was killed"
    elif res.proc_rc != 0:
        res.status = FAILED
    else:
        missing = [e for e in expect
                   if not (workspace / e).exists() or (workspace / e).stat().st_mtime < started - 2]
        if missing:
            res.missing, res.status = missing, MISSING_OUTPUT
            res.err += "\nexpected output missing: " + ", ".join(missing)
        else:
            res.status = OK
    if not keep_sandbox:
        shutil.rmtree(box, ignore_errors=True)
    snap.cleanup()
    _log(workspace, {"at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
                     "job": job, "kind": kind, "model": model["alias"], "status": res.status,
                     "rc": res.rc, "seconds": round(res.seconds, 1), "cost_usd": res.cost,
                     "restored": len(res.restored), "findings": [f.rule for f in findings],
                     "turns": turns})
    return res


def _discard(snap: "sandbox.Snapshot", guard: "sandbox.GuardReport", workspace: Path) -> None:
    """Put back every allowlisted change too, so a secret-shaped file never survives."""
    for rel in guard.allowed.created:
        p = workspace / rel
        try:
            p.unlink()
        except OSError:
            pass
    for rel in guard.allowed.modified + guard.allowed.deleted:
        copy = snap.copies.get(rel)
        if copy is not None:
            target = workspace / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(copy, target)


def run_job(prompt: str, *, name: str, tools: "str | Sequence[str]", root: Path,
            allow: Iterable[Any], expect: Any = (), timeout: Optional[float] = None,
            effort: Optional[str] = None, max_turns: Optional[int] = None,
            log_path: Optional[Path] = None, kind: str = "improve",
            cfg: Optional[Mapping[str, Any]] = None, **kw: Any) -> WorkerResult:
    """Function-call shape the review board uses: ``run_job(prompt, name=..., tools=..., root=...)``.

    Paths in ``allow`` and ``expect`` may be absolute (inside ``root``) or workspace-relative.
    The result has ``.rc`` (0 on success) and ``.error``.
    """
    from . import config as cfgmod
    root = Path(root)

    def rel(p: Any) -> str:
        q = Path(str(p))
        if q.is_absolute():
            try:
                return q.resolve().relative_to(root.resolve()).as_posix()
            except ValueError:
                return "?outside-workspace?"
        return q.as_posix()

    if cfg is None:
        try:
            cfg = cfgmod.load(root)
        except Exception:  # a broken config must not hide the job's own failure
            cfg = cfgmod.defaults()
    expect_list = [expect] if isinstance(expect, (str, Path)) else list(expect or [])
    tool_list = [t for t in (tools.split(",") if isinstance(tools, str) else tools) if t.strip()]
    allow_rel = []
    for a in allow:
        r = rel(a)
        if r.startswith("?"):
            return WorkerResult(BAD_ARGS, err=f"allowlist path outside the workspace: {a}")
        allow_rel.append(r if (r.endswith("/") or r.endswith("/**") or "." in Path(r).name) else r + "/**")
    res = run_worker(root, cfg, job=name, kind=kind, prompt=prompt, allow=allow_rel,
                     expect=[rel(e) for e in expect_list], tools=tool_list, timeout=timeout,
                     effort=effort, max_turns=max_turns, **kw)
    if log_path:
        try:
            with open(log_path, "a", encoding="utf-8") as fh:
                fh.write(f"[{name}] status={res.status} rc={res.rc}\n{res.text}\n{res.err}\n")
        except OSError:
            pass
    return res


# --------------------------------------------------------------------------- command line

def _cmd_probe(args: Any) -> int:
    from .cli import resolve_workspace, emit_json
    from . import config as cfgmod
    ws = resolve_workspace(args)
    cfg = cfgmod.load(ws) if (ws / "config").exists() else cfgmod.defaults()
    profile = cfg.get("profile_id", "default")
    binary = args.bin or find_claude(cfg)
    if not binary:
        msg = "claude CLI not found: set models.runner.bin or NJLI_CLAUDE_BIN, or install it"
        print(emit_json({"ok": False, "error": msg}) if args.json else "FAIL " + msg)
        return policy.EXIT_FAIL
    result = probe(binary)
    miss = missing_required(result)
    if not args.dry_run:
        pf = probe_path(profile)
        pf.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(pf, result)
    if args.json:
        emit_json({"ok": not miss, "missing": miss, **result})
    else:
        print(f"claude CLI: {binary} ({result['version'] or 'version unknown'})")
        for flag, ok in sorted(result["flags"].items()):
            print(f"  {'yes' if ok else 'NO ':3} {flag}")
        print(("FAIL missing required flags: " + ", ".join(miss)) if miss else "PASS all required flags present")
    return policy.EXIT_FAIL if miss else policy.EXIT_OK


def register(subparsers: Any) -> None:
    p = subparsers.add_parser("claude", help="the Claude CLI used by workers")
    sub = p.add_subparsers(dest="claude_cmd", required=True)
    pr = sub.add_parser("probe", help="record which flags this claude CLI supports")
    pr.add_argument("--workspace")
    pr.add_argument("--profile")
    pr.add_argument("--json", action="store_true")
    pr.add_argument("--dry-run", action="store_true", help="probe but do not write cli-probe.json")
    pr.add_argument("--bin", help="path to the claude CLI (default: discovery)")
    pr.set_defaults(func=_cmd_probe)
