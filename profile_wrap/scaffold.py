"""Create a workspace from ``templates/manifest.json`` and render template variables.

Template files come in two classes (section 15):
  managed  replaced on upgrade only if the user has not edited them
  seeded   created once, then three-way merged on upgrade
An entry with ``once`` is created and then left alone (a handoff note is not a template).
An entry with ``block`` is compared by that marked block only (the CLAUDE.md structural rules).
Everything else in a workspace is user data and is never touched by an upgrade.
"""
from __future__ import annotations

import datetime as _dt
import importlib
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import __version__, config, paths, schemalite
from .atomic import atomic_write_bytes, atomic_write_json
from .fsutil import copy_tree, read_json, sha256_bytes, sha256_text

_VAR = re.compile(r"\{\{\s*([A-Za-z0-9_.@/-]+)\s*\}\}")
BLOCK_BEGIN = "<!-- njl:begin {name} -->"
BLOCK_END = "<!-- njl:end {name} -->"


class ScaffoldError(Exception):
    """A workspace cannot be created or a template cannot be rendered."""


@dataclass
class Entry:
    dest: str                 # path inside the workspace, forward slashes
    src: Path                 # file in the templates dir or the plugin
    klass: str                # managed | seeded
    render: str = "none"      # none | vars
    block: Optional[str] = None
    once: bool = False
    optional: bool = False


# --------------------------------------------------------------------- manifest

def templates_dir(plugin_root: Optional[Path] = None) -> Path:
    return (Path(plugin_root) if plugin_root else paths.plugin_root()) / "templates"


def load_manifest(plugin_root: Optional[Path] = None) -> Dict[str, Any]:
    root = Path(plugin_root) if plugin_root else paths.plugin_root()
    manifest = read_json(root / "templates" / "manifest.json")
    problems = schemalite.validate(manifest, schemalite.load_schema(
        paths.resource("schema", "manifest.schema.json")))
    if problems:
        raise ScaffoldError("templates/manifest.json is invalid: " + "; ".join(problems[:3]))
    return manifest


def expand_entries(manifest: Dict[str, Any], plugin_root: Optional[Path] = None) -> List[Entry]:
    """Turn manifest file rows into per-file entries (directories expand recursively)."""
    root = Path(plugin_root) if plugin_root else paths.plugin_root()
    out: List[Entry] = []
    for row in manifest["files"]:
        base = root if row.get("from") == "plugin" else root / "templates"
        src = base / row["src"]
        common = dict(klass=row["class"], render=row.get("render", "none"),
                      block=row.get("block"), once=row.get("once", False),
                      optional=row.get("optional", False))
        if src.is_dir():
            for path in sorted(p for p in src.rglob("*") if p.is_file()
                               and "__pycache__" not in p.parts and p.suffix != ".pyc"):
                rel = path.relative_to(src).as_posix()
                out.append(Entry(dest=f"{row['dest']}/{rel}", src=path, **common))
        elif src.is_file():
            out.append(Entry(dest=row["dest"], src=src, **common))
        elif not row.get("optional"):
            raise ScaffoldError(f"template source missing: {src}")
    return out


# --------------------------------------------------------------------- rendering

def render_vars(text: str, ctx: Dict[str, str], source: str = "template") -> str:
    def sub(match: "re.Match[str]") -> str:
        key = match.group(1)
        if key not in ctx:
            raise ScaffoldError(f"{source}: unknown template variable {{{{{key}}}}}")
        return str(ctx[key])

    return _VAR.sub(sub, text)


def build_context(cfg: Dict[str, Any], plugin_root: Optional[Path] = None,
                  created: Optional[_dt.date] = None) -> Dict[str, str]:
    root = Path(plugin_root) if plugin_root else paths.plugin_root()
    persona, posting, brand = cfg["persona"], cfg["posting"], cfg["brand"]
    fonts = brand["fonts"]
    ctx: Dict[str, str] = {
        "profile_id": cfg["profile_id"],
        "plugin_version": __version__,
        "created_date": (created or _dt.date.today()).isoformat(),
        "persona.name": persona["name"] or "Your name",
        "persona.role_suffix": f", {persona['role']}" if persona["role"] else "",
        "persona.goal": persona["goal"],
        "persona.languages_text": ", ".join(persona["languages"]),
        "persona.primary_language": persona["primary_language"],
        "locale.timezone": cfg["locale"]["timezone"],
        "posting.per_week": str(posting["per_week"]),
        "posting.window_text": f"{posting['window']['start']} to {posting['window']['end']}",
        "posting.mode": posting["mode"],
        "voice.style_preset": persona["style_preset"],
        "brand.font_text": (
            f"{fonts['display']['family']} (display), {fonts['text']['family']} (text), "
            f"{fonts['arabic']['family']} (Arabic); source: {brand['font_source']}"),
    }
    pins_path = root / "data" / "pins.json"
    if pins_path.is_file():
        pins = read_json(pins_path)
        for name, version in pins.get("npm", {}).items():
            ctx[f"pin.{name}"] = str(version)
        if "node_min" in pins:
            ctx["pin.node_min"] = str(pins["node_min"])
    return ctx


def entry_bytes(entry: Entry, ctx: Dict[str, str]) -> bytes:
    data = entry.src.read_bytes()
    if entry.render == "vars":
        data = render_vars(data.decode("utf-8"), ctx, source=entry.dest).encode("utf-8")
    return data


# ----------------------------------------------------------------- block helpers

def find_block(text: str, name: str) -> Optional["tuple[int, int]"]:
    begin, end = BLOCK_BEGIN.format(name=name), BLOCK_END.format(name=name)
    i = text.find(begin)
    j = text.find(end)
    if i < 0 or j < 0 or j < i:
        return None
    return i, j + len(end)


def extract_block(text: str, name: str) -> Optional[str]:
    span = find_block(text, name)
    return text[span[0]:span[1]] if span else None


def replace_block(text: str, name: str, new_block: str) -> str:
    span = find_block(text, name)
    if span is None:
        return text.rstrip("\n") + "\n\n" + new_block + "\n"
    return text[:span[0]] + new_block + text[span[1]:]


def tracked_hash(entry: Entry, data: bytes) -> str:
    """The hash recorded as an entry's base: the whole file, or just its marked block."""
    if entry.block:
        block = extract_block(data.decode("utf-8"), entry.block)
        if block is None:
            raise ScaffoldError(f"{entry.dest}: template has no '{entry.block}' block")
        return sha256_text(block.replace("\r\n", "\n"))
    return sha256_bytes(data)


# -------------------------------------------------------------------- workspace

def workspace_meta_path(workspace: Path) -> Path:
    return Path(workspace) / ".njl" / "workspace.json"


def read_meta(workspace: Path) -> Dict[str, Any]:
    return read_json(workspace_meta_path(workspace))


def _git_init(workspace: Path) -> str:
    git = shutil.which("git")
    if not git:
        return "git not found: workspace not under version control (install git, then 'git init')"
    if (workspace / ".git").exists():
        return "git repository already present"
    result = subprocess.run([git, "init", "-b", "main"], cwd=str(workspace), capture_output=True,
                            text=True, timeout=60)
    if result.returncode != 0:
        result = subprocess.run([git, "init"], cwd=str(workspace), capture_output=True,
                                text=True, timeout=60)
    return "git repository created" if result.returncode == 0 else \
        f"git init failed: {result.stderr.strip()[:120]}"


def create_workspace(workspace: Path, cfg: Dict[str, Any], plugin_root: Optional[Path] = None,
                     git: bool = True, created: Optional[_dt.datetime] = None) -> Dict[str, Any]:
    """Create folders, config, template files and ``.njl/workspace.json``."""
    ws = Path(workspace)
    paths.refuse_inside_plugin(ws)
    if ws.exists() and any(ws.iterdir()):
        raise ScaffoldError(f"{ws} is not empty; choose a new folder, or use 'profile-wrap init --section' "
                            "to change an existing workspace")
    report = config.validate(cfg)
    if report.errors:
        raise ScaffoldError("config is invalid: " + "; ".join(report.errors))
    root = Path(plugin_root) if plugin_root else paths.plugin_root()
    manifest = load_manifest(root)
    entries = expand_entries(manifest, root)
    ctx = build_context(cfg, root)

    ws.mkdir(parents=True, exist_ok=True)
    for rel in manifest.get("dirs", []):
        (ws / rel).mkdir(parents=True, exist_ok=True)
    for rel in manifest.get("gitkeep", []):
        keep = ws / rel / ".gitkeep"
        if not keep.exists():
            keep.write_text("", encoding="utf-8")

    atomic_write_json(config.config_path(ws), cfg)
    files: Dict[str, Dict[str, str]] = {}
    written: List[str] = []
    for entry in entries:
        data = entry_bytes(entry, ctx)
        atomic_write_bytes(ws / entry.dest, data)
        written.append(entry.dest)
        if not entry.once:
            files[entry.dest] = {"class": entry.klass, "sha256": tracked_hash(entry, data)}
    stamp = (created or _dt.datetime.now(_dt.timezone.utc)).isoformat(timespec="seconds")
    meta = {
        "schema_version": 1,
        "template_version": manifest["template_version"],
        "plugin_version": __version__,
        "profile_id": cfg["profile_id"],
        "created_at": stamp,
        "files": files,
        "created_schedule": [],
        "applied_migrations": _all_migration_ids(),
    }
    atomic_write_json(workspace_meta_path(ws), meta)
    notes = [_git_init(ws)] if git else []
    notes.append(_render_agents(ws, cfg))
    return {"workspace": str(ws), "files": written, "notes": notes}


def _all_migration_ids() -> List[str]:
    """A new workspace starts at the current schema: every shipped migration counts as applied."""
    from .migrations import runner

    return [m.id for m in runner.discover()]


def _render_agents(workspace: Path, cfg: Dict[str, Any]) -> str:
    """Render agent templates into .claude/agents when the agents package is installed."""
    try:
        mod = importlib.import_module("profile_wrap.agents_render")
    except ImportError:
        return "agents: not rendered (profile_wrap.agents_render is not installed yet)"
    fn = getattr(mod, "render_all", None) or getattr(mod, "render", None)
    if fn is None:
        return "agents: profile_wrap.agents_render has no render function"
    try:
        fn(workspace)
    except TypeError:
        try:
            fn(workspace, cfg)
        except Exception as exc:  # report, never crash the scaffold
            return f"agents: render failed: {exc}"
    except Exception as exc:
        return f"agents: render failed: {exc}"
    return "agents rendered"


def copy_examples(source: Path, workspace: Path) -> int:
    """Copy a prepared example tree (the demo persona data) over a fresh workspace."""
    return copy_tree(source, workspace)
