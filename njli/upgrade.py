"""``njli upgrade``: three-way template upgrade over the manifest's file classes.

For every managed or seeded file, ``.njl/workspace.json`` stores the base hash (what the plugin
last wrote or the user last accepted). With ``cur`` the file now, ``new`` the freshly rendered
template and ``base`` the stored hash:

  cur == base, new != base   overwrite (the old copy goes to .njl/backup/<ts>/)
  cur != base, new == base   keep (the user edited, the template did not change)
  cur != base, new != base   conflict: keep the user's file, write <file>.new, record it,
                             print a diff, exit 3 until 'upgrade --resolve'
  cur == new                 nothing to do (the base is moved up)

User-class files (config values, facts, voice, calendar, drafts, ...) are never touched.
"""
from __future__ import annotations

import datetime as _dt
import difflib
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import __version__, config, paths, policy, scaffold
from .atomic import atomic_write_bytes, atomic_write_json
from .fsutil import read_json, sha256_bytes, sha256_text
from .migrations import runner as migration_runner

CONFLICT_DIR = Path(".njl") / "conflicts"


@dataclass
class Action:
    dest: str
    action: str   # create overwrite keep conflict adopt unchanged skip_deleted
    klass: str
    diff: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {"dest": self.dest, "action": self.action, "class": self.klass}


@dataclass
class UpgradeResult:
    actions: List[Action] = field(default_factory=list)
    conflicts: List[Dict[str, Any]] = field(default_factory=list)
    backup: Optional[str] = None
    notes: List[str] = field(default_factory=list)
    pending_migrations: int = 0
    dry_run: bool = False

    @property
    def exit_code(self) -> int:
        return policy.EXIT_CONFLICT if self.conflicts else policy.EXIT_OK

    def counts(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for a in self.actions:
            out[a.action] = out.get(a.action, 0) + 1
        return out


def _conflict_file(ws: Path, dest: str) -> Path:
    safe = dest.replace("/", "__").replace("\\", "__")
    return ws / CONFLICT_DIR / f"{safe}.json"


def _read_conflicts(ws: Path) -> List[Dict[str, Any]]:
    folder = ws / CONFLICT_DIR
    if not folder.is_dir():
        return []
    out = []
    for path in sorted(folder.glob("*.json")):
        try:
            out.append(read_json(path))
        except ValueError:
            continue
    return out


def _current_hash(entry: scaffold.Entry, path: Path) -> Optional[str]:
    data = path.read_bytes()
    if entry.block:
        block = scaffold.extract_block(data.decode("utf-8", errors="replace"), entry.block)
        return sha256_text(block.replace("\r\n", "\n")) if block else None
    return sha256_bytes(data)


def _unified(dest: str, mine: bytes, theirs: bytes) -> str:
    try:
        a, b = mine.decode("utf-8"), theirs.decode("utf-8")
    except UnicodeDecodeError:
        return "(binary file differs)"
    return "".join(difflib.unified_diff(a.splitlines(True), b.splitlines(True),
                                        fromfile=f"{dest} (yours)", tofile=f"{dest} (new template)"))


def _stamp() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


class Upgrader:
    def __init__(self, workspace: Path, plugin_root: Optional[Path] = None):
        self.ws = Path(workspace)
        self.root = Path(plugin_root) if plugin_root else paths.plugin_root()
        if not (self.ws / ".njl" / "workspace.json").is_file():
            raise scaffold.ScaffoldError(f"{self.ws} is not an nj-linkedin workspace")
        self.meta = read_json(self.ws / ".njl" / "workspace.json")
        self.cfg = config.load(self.ws)
        self.manifest = scaffold.load_manifest(self.root)
        self.entries = [e for e in scaffold.expand_entries(self.manifest, self.root) if not e.once]
        self.ctx = scaffold.build_context(self.cfg, self.root)
        self.backup_dir: Optional[Path] = None

    # -- planning ---------------------------------------------------------
    def plan(self) -> List[Action]:
        actions: List[Action] = []
        tracked = self.meta.get("files", {})
        for entry in self.entries:
            new = scaffold.entry_bytes(entry, self.ctx)
            new_hash = scaffold.tracked_hash(entry, new)
            base = tracked.get(entry.dest, {}).get("sha256")
            path = self.ws / entry.dest
            if not path.exists():
                if base is not None and entry.klass == "seeded":
                    actions.append(Action(entry.dest, "skip_deleted", entry.klass))
                else:
                    actions.append(Action(entry.dest, "create", entry.klass))
                continue
            cur = _current_hash(entry, path)
            if base is None:
                if cur == new_hash:
                    actions.append(Action(entry.dest, "adopt", entry.klass))
                else:
                    actions.append(Action(entry.dest, "conflict", entry.klass,
                                          _unified(entry.dest, path.read_bytes(), new)))
            elif cur == base:
                if new_hash == base:
                    actions.append(Action(entry.dest, "unchanged", entry.klass))
                else:
                    actions.append(Action(entry.dest, "overwrite", entry.klass,
                                          _unified(entry.dest, path.read_bytes(), new)))
            elif new_hash == base:
                actions.append(Action(entry.dest, "keep", entry.klass))
            elif cur == new_hash:
                actions.append(Action(entry.dest, "adopt", entry.klass))
            else:
                actions.append(Action(entry.dest, "conflict", entry.klass,
                                      _unified(entry.dest, path.read_bytes(), new)))
        return actions

    # -- applying ---------------------------------------------------------
    def _backup(self, rel: str) -> None:
        src = self.ws / rel
        if not src.is_file():
            return
        if self.backup_dir is None:
            self.backup_dir = self.ws / ".njl" / "backup" / f"upgrade-{_stamp()}"
        target = self.backup_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)

    def _write_entry(self, entry: scaffold.Entry, new: bytes) -> None:
        path = self.ws / entry.dest
        if entry.block and path.exists():
            text = path.read_text(encoding="utf-8")
            block = scaffold.extract_block(new.decode("utf-8"), entry.block) or ""
            atomic_write_bytes(path, scaffold.replace_block(text, entry.block, block).encode("utf-8"))
        else:
            atomic_write_bytes(path, new)

    def apply(self, dry_run: bool = False) -> UpgradeResult:
        actions = self.plan()
        result = UpgradeResult(actions=actions, dry_run=dry_run)
        by_dest = {e.dest: e for e in self.entries}
        tracked = self.meta.setdefault("files", {})
        if dry_run:
            result.conflicts = [self._conflict_record(by_dest[a.dest], a)
                                for a in actions if a.action == "conflict"]
            result.conflicts += [c for c in _read_conflicts(self.ws)
                                 if c["dest"] not in {x["dest"] for x in result.conflicts}]
            result.pending_migrations = self._pending_migrations()
            return result
        for act in actions:
            entry = by_dest[act.dest]
            new = scaffold.entry_bytes(entry, self.ctx)
            new_hash = scaffold.tracked_hash(entry, new)
            if act.action == "create":
                self._write_entry(entry, new)
                tracked[act.dest] = {"class": entry.klass, "sha256": new_hash}
            elif act.action == "overwrite":
                self._backup(act.dest)
                self._write_entry(entry, new)
                tracked[act.dest] = {"class": entry.klass, "sha256": new_hash}
            elif act.action == "adopt":
                tracked[act.dest] = {"class": entry.klass, "sha256": new_hash}
            elif act.action == "conflict":
                record = self._conflict_record(entry, act)
                atomic_write_bytes(self.ws / (act.dest + ".new"), new)
                atomic_write_json(_conflict_file(self.ws, act.dest), record)
        result.conflicts = _read_conflicts(self.ws)
        result.backup = str(self.backup_dir) if self.backup_dir else None
        self.meta["template_version"] = self.manifest["template_version"]
        self.meta["plugin_version"] = __version__
        atomic_write_json(self.ws / ".njl" / "workspace.json", self.meta)
        result.notes.append(scaffold._render_agents(self.ws, self.cfg))
        result.pending_migrations = self._pending_migrations()
        return result

    def _conflict_record(self, entry: scaffold.Entry, act: Action) -> Dict[str, Any]:
        return {"dest": act.dest, "new": act.dest + ".new", "class": entry.klass,
                "block": entry.block, "diff": act.diff,
                "created_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")}

    def _pending_migrations(self) -> int:
        done = set(self.meta.get("applied_migrations", []))
        return len([m for m in migration_runner.discover() if m.id not in done])

    # -- resolving --------------------------------------------------------
    def resolve(self, mode: Optional[str] = None) -> UpgradeResult:
        """mode: None (resolved when you removed the .new file), 'mine' or 'theirs'."""
        if mode not in (None, "mine", "theirs"):
            raise ValueError("mode must be None, 'mine' or 'theirs'")
        result = UpgradeResult()
        by_dest = {e.dest: e for e in scaffold.expand_entries(self.manifest, self.root)}
        tracked = self.meta.setdefault("files", {})
        for rec in _read_conflicts(self.ws):
            dest = rec["dest"]
            entry = by_dest.get(dest)
            new_path = self.ws / rec["new"]
            if entry is None:  # template dropped the file: nothing to resolve against
                _conflict_file(self.ws, dest).unlink(missing_ok=True)
                new_path.unlink(missing_ok=True)
                continue
            new = scaffold.entry_bytes(entry, self.ctx)
            new_hash = scaffold.tracked_hash(entry, new)
            if mode == "theirs":
                self._backup(dest)
                self._write_entry(entry, new)
            elif mode is None and new_path.exists():
                result.conflicts.append(rec)
                continue
            new_path.unlink(missing_ok=True)
            tracked[dest] = {"class": entry.klass, "sha256": new_hash}
            _conflict_file(self.ws, dest).unlink(missing_ok=True)
            result.actions.append(Action(dest, "resolved_" + (mode or "manual"), entry.klass))
        atomic_write_json(self.ws / ".njl" / "workspace.json", self.meta)
        result.backup = str(self.backup_dir) if self.backup_dir else None
        return result


def check(workspace: Path, plugin_root: Optional[Path] = None) -> UpgradeResult:
    """Dry run: what ``--apply`` would do."""
    return Upgrader(workspace, plugin_root).apply(dry_run=True)


def apply(workspace: Path, plugin_root: Optional[Path] = None) -> UpgradeResult:
    return Upgrader(workspace, plugin_root).apply()


def resolve(workspace: Path, plugin_root: Optional[Path] = None,
            mode: Optional[str] = None) -> UpgradeResult:
    return Upgrader(workspace, plugin_root).resolve(mode)


def render_summary(result: UpgradeResult, show_diff: bool = True) -> str:
    lines = []
    for a in result.actions:
        if a.action in ("unchanged",):
            continue
        lines.append(f"  {a.action:<12} {a.dest}")
        if show_diff and a.diff and a.action in ("overwrite", "conflict"):
            lines.append("".join("      " + ln for ln in a.diff.splitlines(True)).rstrip("\n"))
    counts = result.counts()
    lines.append("summary: " + (", ".join(f"{v} {k}" for k, v in sorted(counts.items())) or "no files"))
    if result.conflicts:
        lines.append(f"{len(result.conflicts)} conflict(s): your file was kept and a .new file "
                     "written next to it. Merge, delete the .new file, then 'njli upgrade --resolve'.")
    if result.pending_migrations:
        lines.append(f"{result.pending_migrations} migration(s) pending: run 'njli migrate'.")
    return "\n".join(lines)


def conflicts_json(result: UpgradeResult) -> str:
    return json.dumps([{k: v for k, v in c.items() if k != "diff"} for c in result.conflicts],
                      indent=2)
