"""The ``njli`` command line.

Core commands live here. Every other package adds its own commands through a
``register(subparsers)`` function in ``njli/<package>/cli_ext.py`` (or at module level for a
single-file package); handlers are stored with ``set_defaults(func=...)`` and return an exit
code. Exit codes: 0 ok, 1 fail, 2 usage, 3 conflicts to resolve, 4 paused.
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable, List, Optional

from . import __version__, config, doctor, handoff, init_wizard, limits, paths, policy, scaffold, upgrade
from .bootstrap import runtime as runtime_mod
from .migrations import runner as migration_runner

EXTENSIONS = (
    "facts", "gate", "plan", "research", "profile", "visuals", "linkedin", "board", "engage",
    "track", "schedule", "demo", "claude_runner", "leakcheck", "compliance", "deps",
    "import_legacy", "update", "agents_render",
)


# ----------------------------------------------------------------- utilities

def emit_json(obj: Any) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def resolve_workspace(args: argparse.Namespace) -> Path:
    explicit = getattr(args, "workspace", None)
    if explicit:
        return paths.workspace_path(getattr(args, "profile", None) or "default", explicit)
    found = paths.find_workspace()
    if found:
        return found
    return paths.workspace_path(getattr(args, "profile", None) or "default")


def _common(parser: argparse.ArgumentParser, dry_run: bool = False) -> None:
    parser.add_argument("--workspace", help="workspace folder (default: current folder, "
                                            "NJLI_WORKSPACE, or ~/nj-linkedin/<profile>)")
    parser.add_argument("--profile", help="profile id (default: default)")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    if dry_run:
        parser.add_argument("--dry-run", action="store_true", help="show what would change")


def _is_tty() -> bool:
    try:
        return sys.stdin.isatty()
    except (AttributeError, ValueError):
        return False


def _confirm(prompt: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    if not _is_tty():
        return False
    return input(prompt + " [y/N] ").strip().lower() in ("y", "yes")


# ------------------------------------------------------------------- runtime

def cmd_runtime(args: argparse.Namespace) -> int:
    action = args.runtime_cmd
    if action == "status":
        st = runtime_mod.status()
        if args.json:
            emit_json(st)
        else:
            print(f"runtime dir : {st['runtime_dir']}")
            print(f"installed   : {', '.join(st['installed']) or 'none'}")
            print(f"current     : {st['current'] or 'none'} (plugin is {st['plugin_version']})")
            print("drift       : " + (st["reason"] if st["drift"] else "none"))
            if st["entry"]:
                print("scheduler runs: " + " ".join(st["entry"]))
        return policy.EXIT_OK
    pyz = Path(args.pyz) if getattr(args, "pyz", None) else None
    if action == "install":
        result = runtime_mod.install(pyz=pyz)
    else:
        result = runtime_mod.sync(force=args.force)
    if args.json:
        emit_json(result)
    else:
        what = result.get("action", "installed")
        print(f"runtime {what}: {result.get('version', result.get('current'))} "
              f"({result.get('mode', '')})")
        print("scheduler runs: " + " ".join(result["entry"]))
    return policy.EXIT_OK


# -------------------------------------------------------------------- config

def cmd_config(args: argparse.Namespace) -> int:
    ws = resolve_workspace(args)
    sub = args.config_cmd
    if sub == "validate":
        report = config.validate_workspace(ws)
        if args.json:
            emit_json({"ok": report.ok, "errors": report.errors, "warnings": report.warnings})
        else:
            for line in report.errors:
                print(f"FAIL {line}")
            for line in report.warnings:
                print(f"WARN {line}")
            print("config: " + ("valid" if report.ok else f"{len(report.errors)} error(s)"))
        return policy.EXIT_OK if report.ok else policy.EXIT_FAIL
    if sub == "show":
        cfg = config.load(ws)
        try:
            value = config.show(cfg, args.key)
        except KeyError as exc:
            print(f"njli: {exc.args[0]}", file=sys.stderr)
            return policy.EXIT_FAIL
        eff = config.effective_modes(cfg, ws)
        if args.json or isinstance(value, (dict, list)):
            emit_json(value if args.key else {"config": value, "effective": eff})
        else:
            print(value)
        return policy.EXIT_OK
    if sub == "set":
        report = config.set_value(ws, args.key, args.value)
        for line in report.errors:
            print(f"FAIL {line}")
        for line in report.warnings:
            print(f"WARN {line}")
        if report.errors:
            return policy.EXIT_FAIL
        print(f"set {args.key}")
        return policy.EXIT_OK
    if sub == "ack":
        if os.environ.get(policy.WORKER_ENV) == "1":
            print("njli: an agent cannot record an acknowledgement; run this yourself in a "
                  "terminal", file=sys.stderr)
            return policy.EXIT_FAIL
        phrase = args.phrase
        if phrase is None:
            if not _is_tty():
                print("njli: no terminal: pass --phrase, or run this command in a terminal",
                      file=sys.stderr)
                return policy.EXIT_USAGE
            print(f"You are accepting a risk for '{args.action}'. Read the shipped risk text first "
                  "(docs/TERMS-AND-RISK.md and docs/references/compliance.md in the plugin).")
            phrase = input(f"Type exactly '{policy.ACK_PHRASE}' to accept: ")
        try:
            record = config.ack(ws, args.action, phrase)
        except ValueError as exc:
            print(f"njli: {exc}", file=sys.stderr)
            return policy.EXIT_FAIL
        print(f"acknowledged '{args.action}' ({record['date']}, text sha256 {record['sha256'][:12]})")
        return policy.EXIT_OK
    return policy.EXIT_USAGE


# -------------------------------------------------------------------- doctor

def cmd_doctor(args: argparse.Namespace) -> int:
    ws: Optional[Path] = None
    explicit = getattr(args, "workspace", None)
    found = Path(explicit) if explicit else paths.find_workspace()
    if found and (found / ".njl" / "workspace.json").is_file():
        ws = found
    elif explicit:
        ws = Path(explicit)
    result = doctor.run(workspace=ws, online=args.online, launchd_dryrun=args.launchd_dryrun,
                        label=args.os_label)
    if args.fix:
        fixed = _doctor_fix(result, args.yes)
        if fixed:
            result = doctor.run(workspace=ws, online=args.online, label=args.os_label)
            result["fixed"] = fixed
    if args.json:
        emit_json(result)
    else:
        print(doctor.render_table(result))
        for line in result.get("fixed", []):
            print("fixed: " + line)
    return doctor.exit_code(result)


def _doctor_fix(result: dict, assume_yes: bool) -> List[str]:
    """Install only into the data dir, and only after asking."""
    fixed: List[str] = []
    runtime_check = next((c for c in result["checks"] if c["id"] == "runtime"), None)
    if runtime_check and runtime_check["status"] == "warn":
        if _confirm("Update the stable runtime copy now (runtime sync)?", assume_yes):
            info = runtime_mod.sync(force=True)
            fixed.append(f"runtime now {info.get('version', '')}")
    return fixed


# ---------------------------------------------------------------------- init

def cmd_init(args: argparse.Namespace) -> int:
    try:
        if args.demo:
            summary = init_wizard.init_demo(Path(args.dir) if args.dir else None)
        elif args.section:
            ws = resolve_workspace(args)
            if not args.answers:
                print("njli: --section needs --answers <file> with that step's answers "
                      "(the setup skill writes it)", file=sys.stderr)
                return policy.EXIT_USAGE
            summary = init_wizard.apply_section(ws, args.section, init_wizard.load_answers(
                Path(args.answers)))
        else:
            if args.answers:
                answers = init_wizard.load_answers(Path(args.answers))
                if not args.yes:
                    print("njli: replaying an answers file needs --yes", file=sys.stderr)
                    return policy.EXIT_USAGE
            elif args.express and _is_tty():
                answers = init_wizard.express_answers(input)
            else:
                print("njli: nothing to ask here. Use the setup skill (/nj-linkedin:setup), "
                      "'njli init --demo' to try it, or 'njli init --answers a.json --yes'.",
                      file=sys.stderr)
                return policy.EXIT_USAGE
            if args.profile:
                answers.setdefault("where", {})["profile_id"] = args.profile
            target = Path(args.dir) if args.dir else (Path(args.workspace) if args.workspace
                                                      else None)
            summary = init_wizard.init_workspace(target, answers, git=not args.no_git,
                                                 require_claude=args.express and not args.yes)
    except (init_wizard.WizardError, scaffold.ScaffoldError, paths.PathError,
            config.ConfigError) as exc:
        print(f"njli: {exc}", file=sys.stderr)
        return policy.EXIT_FAIL
    if args.json:
        emit_json(summary)
    else:
        print(f"workspace: {summary['workspace']}")
        for note in summary["notes"]:
            print("  " + note)
        for step in summary.get("next", []):
            print("next: " + step)
    return policy.EXIT_OK


# ------------------------------------------------------------------- upgrade

def cmd_upgrade(args: argparse.Namespace) -> int:
    ws = resolve_workspace(args)
    try:
        if args.resolve:
            mode = "mine" if args.mine else ("theirs" if args.theirs else None)
            result = upgrade.resolve(ws, mode=mode)
        elif args.apply:
            result = upgrade.apply(ws)
        else:  # --check and --dry-run both preview
            result = upgrade.check(ws)
    except (scaffold.ScaffoldError, config.ConfigError) as exc:
        print(f"njli: {exc}", file=sys.stderr)
        return policy.EXIT_FAIL
    if args.json:
        emit_json({"actions": [a.as_dict() for a in result.actions],
                   "conflicts": json.loads(upgrade.conflicts_json(result)),
                   "pending_migrations": result.pending_migrations,
                   "backup": result.backup})
    else:
        print(upgrade.render_summary(result))
    return result.exit_code


def cmd_migrate(args: argparse.Namespace) -> int:
    ws = resolve_workspace(args)
    try:
        out = migration_runner.run(ws, dry_run=args.dry_run, assume_yes=args.yes,
                                   ask=lambda p: _confirm(p, False))
    except config.ConfigError as exc:
        print(f"njli: {exc}", file=sys.stderr)
        return policy.EXIT_FAIL
    if args.json:
        emit_json({"applied": out.applied, "noop": out.noop, "planned": out.planned,
                   "needs_confirmation": out.pending_confirmation, "backup": out.backup})
    else:
        for item in out.planned:
            print(f"would apply {item['id']}: {item['description']}")
        for mid in out.applied:
            print(f"applied {mid}")
        if out.pending_confirmation:
            print(f"{out.pending_confirmation['id']} changes a safety setting and needs your "
                  "confirmation: re-run with --yes after reading the changes above.")
        if not (out.applied or out.planned or out.pending_confirmation):
            print("nothing to migrate")
    return out.exit_code


# ------------------------------------------------------------------- handoff

def cmd_handoff(args: argparse.Namespace) -> int:
    target = Path(args.path) if args.path else resolve_workspace(args) / "handoff.md"
    errors, warnings = handoff.check_file(target)
    if args.json:
        emit_json({"path": str(target), "ok": not errors, "errors": errors, "warnings": warnings})
    else:
        for line in errors:
            print(f"FAIL {line}")
        for line in warnings:
            print(f"WARN {line}")
        print(f"handoff: {'ok' if not errors else 'invalid'} ({target})")
    return policy.EXIT_OK if not errors else policy.EXIT_FAIL


# --------------------------------------------------------------- pause/resume

def cmd_pause(args: argparse.Namespace) -> int:
    ws = resolve_workspace(args)
    kind = "posting" if args.posting else ("comments" if args.comments else None)
    path = limits.pause(ws, kind, reason=args.reason or "")
    print(f"paused ({kind or 'all'}): {path}")
    return policy.EXIT_OK


def cmd_resume(args: argparse.Namespace) -> int:
    ws = resolve_workspace(args)
    kind = "posting" if args.posting else ("comments" if args.comments else None)
    removed = limits.resume(ws, kind)
    print("resumed: " + (", ".join(p.name for p in removed) if removed else "nothing was paused"))
    return policy.EXIT_OK


# ------------------------------------------------------------------- parser

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="njli", description="nj-linkedin: a fact-gated, "
                                     "compliance-first LinkedIn content pipeline.")
    parser.add_argument("--version", action="version", version=f"njli {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    p = sub.add_parser("runtime", help="build and sync the stable runtime schedulers call")
    rs = p.add_subparsers(dest="runtime_cmd", required=True)
    for name, text in (("install", "copy the code to <data>/runtime/<version> and point current at it"),
                       ("sync", "install only if the runtime is missing or has drifted"),
                       ("status", "show installed versions, drift and the scheduler command")):
        q = rs.add_parser(name, help=text)
        q.add_argument("--json", action="store_true")
        if name == "install":
            q.add_argument("--pyz", help="also copy a prebuilt njli.pyz into the runtime")
        if name == "sync":
            q.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_runtime)

    p = sub.add_parser("config", help="validate, show, set or acknowledge configuration")
    cs = p.add_subparsers(dest="config_cmd", required=True)
    q = cs.add_parser("validate", help="check config/njli.json against the schema and ceilings")
    _common(q)
    q = cs.add_parser("show", help="print the effective config, or one dotted key")
    q.add_argument("key", nargs="?")
    _common(q)
    q = cs.add_parser("set", help="set one dotted key if the result is valid")
    q.add_argument("key")
    q.add_argument("value", help="JSON (true, 3, [\"a\"]) or a plain string")
    _common(q)
    q = cs.add_parser("ack", help="record a typed acknowledgement of a risk text")
    q.add_argument("action", choices=sorted(policy.ACK_ACTIONS))
    q.add_argument("--phrase", help="the typed phrase (otherwise you are prompted)")
    _common(q)
    p.set_defaults(func=cmd_config)

    p = sub.add_parser("doctor", help="check this machine and the workspace; per-OS install hints")
    _common(p)
    p.add_argument("--fix", action="store_true", help="repair what lives in the data dir (asks first)")
    p.add_argument("--yes", action="store_true", help="answer yes to --fix questions")
    p.add_argument("--online", action="store_true", help="also test network reach to LinkedIn")
    p.add_argument("--launchd-dryrun", action="store_true", help="macOS: check the PATH a plist would capture")
    p.add_argument("--os", dest="os_label", choices=doctor.OS_LABELS,
                   help="print hints for another OS (for documentation and tests)")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("init", help="create a workspace (demo, express, or replayed answers)")
    p.add_argument("dir", nargs="?", help="workspace folder")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--demo", action="store_true", help="seed the fictional demo persona, no questions")
    mode.add_argument("--express", action="store_true", help="the seven express questions in a terminal")
    p.add_argument("--answers", help="answers file (schema/answers.schema.json)")
    p.add_argument("--yes", action="store_true", help="replay --answers without questions")
    p.add_argument("--section", help="re-enter one step: " + ", ".join(init_wizard.SECTIONS))
    p.add_argument("--no-git", action="store_true", help="do not run git init")
    _common(p)
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("upgrade", help="three-way template upgrade of a workspace")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--check", action="store_true", help="preview (default)")
    g.add_argument("--dry-run", action="store_true", help="same as --check")
    g.add_argument("--apply", action="store_true", help="apply: overwrite / keep / .new")
    g.add_argument("--resolve", action="store_true", help="finish after merging the .new files")
    p.add_argument("--mine", action="store_true", help="with --resolve: keep my files, drop the .new files")
    p.add_argument("--theirs", action="store_true", help="with --resolve: take the new templates")
    _common(p)
    p.set_defaults(func=cmd_upgrade)

    p = sub.add_parser("migrate", help="run pending idempotent migrations")
    p.add_argument("--yes", action="store_true", help="confirm migrations that touch a safety setting")
    _common(p, dry_run=True)
    p.set_defaults(func=cmd_migrate)

    p = sub.add_parser("handoff", help="check handoff.md")
    hs = p.add_subparsers(dest="handoff_cmd", required=True)
    q = hs.add_parser("check", help="verify the six headings")
    q.add_argument("path", nargs="?", help="default: <workspace>/handoff.md")
    _common(q)
    p.set_defaults(func=cmd_handoff)

    _load_extensions(sub)
    for name, func, text in (("pause", cmd_pause, "stop jobs and API calls"),
                             ("resume", cmd_resume, "remove pause flags")):
        if name not in sub.choices:
            q = sub.add_parser(name, help=text)
            q.add_argument("--posting", action="store_true")
            q.add_argument("--comments", action="store_true")
            q.add_argument("--all", action="store_true")
            if name == "pause":
                q.add_argument("--reason")
            _common(q)
            q.set_defaults(func=func)
    return parser


def _load_extensions(sub: Any) -> None:
    for name in EXTENSIONS:
        for modname in (f"njli.{name}.cli_ext", f"njli.{name}"):
            try:
                mod = importlib.import_module(modname)
            except ModuleNotFoundError as exc:
                if exc.name and (modname == exc.name or modname.startswith(exc.name + ".")):
                    continue
                _warn_extension(name, exc)
                break
            except Exception as exc:  # a broken extension must not take the core down
                _warn_extension(name, exc)
                break
            register: Optional[Callable[[Any], None]] = getattr(mod, "register", None)
            if register is None:
                continue
            try:
                register(sub)
            except Exception as exc:
                _warn_extension(name, exc)
            break


def _warn_extension(name: str, exc: BaseException) -> None:
    print(f"njli: extension '{name}' could not be loaded: {exc}", file=sys.stderr)


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:
        parser.print_help()
        return policy.EXIT_USAGE
    if os.name == "nt":
        os.environ.setdefault("PYTHONUTF8", "1")
    try:
        code = func(args)
    except KeyboardInterrupt:
        print("njli: interrupted", file=sys.stderr)
        return policy.EXIT_FAIL
    except (paths.PathError, config.ConfigError, scaffold.ScaffoldError) as exc:
        print(f"njli: {exc}", file=sys.stderr)
        return policy.EXIT_FAIL
    return int(code or 0)


if __name__ == "__main__":
    sys.exit(main())
