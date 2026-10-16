"""Discover and run migrations against a workspace."""
from __future__ import annotations

import datetime as _dt
import importlib
import importlib.util
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Dict, List, Optional

from .. import config
from ..atomic import atomic_write_json
from ..fsutil import read_json

_NAME = re.compile(r"^(\d{4})_[a-z0-9_]+\.py$")


@dataclass
class Migration:
    id: str
    module: ModuleType

    @property
    def touches_policy(self) -> bool:
        return bool(getattr(self.module, "TOUCHES_POLICY", False))

    @property
    def description(self) -> str:
        return str(getattr(self.module, "DESCRIPTION", ""))


@dataclass
class Context:
    workspace: Path
    dry_run: bool = False

    def config_raw(self) -> Dict[str, Any]:
        return config.load_raw(self.workspace)

    def save_config(self, data: Dict[str, Any]) -> None:
        if not self.dry_run:
            atomic_write_json(config.config_path(self.workspace), data)

    def meta(self) -> Dict[str, Any]:
        return read_json(self.workspace / ".njl" / "workspace.json")

    def save_meta(self, data: Dict[str, Any]) -> None:
        if not self.dry_run:
            atomic_write_json(self.workspace / ".njl" / "workspace.json", data)


@dataclass
class Outcome:
    applied: List[str] = field(default_factory=list)
    noop: List[str] = field(default_factory=list)
    planned: List[Dict[str, Any]] = field(default_factory=list)
    pending_confirmation: Optional[Dict[str, Any]] = None
    backup: Optional[str] = None

    @property
    def exit_code(self) -> int:
        return 3 if self.pending_confirmation else 0


def discover(directory: Optional[Path] = None) -> List[Migration]:
    """Migrations in order. ``directory`` defaults to this package (shipped migrations)."""
    out: List[Migration] = []
    if directory is None:
        here = Path(__file__).resolve().parent
        for path in sorted(here.glob("[0-9][0-9][0-9][0-9]_*.py")):
            mod = importlib.import_module(f"{__package__}.{path.stem}")
            out.append(Migration(path.stem, mod))
        return out
    for path in sorted(Path(directory).iterdir()):
        if not _NAME.match(path.name):
            continue
        spec = importlib.util.spec_from_file_location(f"profile_wrap_mig_{path.stem}", path)
        if spec is None or spec.loader is None:
            continue
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        out.append(Migration(path.stem, mod))
    return out


def run(workspace: Path, migrations: Optional[List[Migration]] = None, dry_run: bool = False,
        assume_yes: bool = False, ask: Optional[Callable[[str], bool]] = None) -> Outcome:
    ws = Path(workspace)
    ctx = Context(ws, dry_run=dry_run)
    items = migrations if migrations is not None else discover()
    meta = ctx.meta()
    applied = list(meta.get("applied_migrations", []))
    out = Outcome()
    backed_up = False
    for mig in items:
        if mig.id in applied:
            continue
        changes = list(mig.module.plan(ctx))
        if not changes:
            out.noop.append(mig.id)
            applied.append(mig.id)
            continue
        entry = {"id": mig.id, "description": mig.description, "changes": changes,
                 "touches_policy": mig.touches_policy}
        if dry_run:
            out.planned.append(entry)
            continue
        if mig.touches_policy:
            prompt = (f"Migration {mig.id} changes a safety setting: {mig.description}\n  "
                      + "\n  ".join(changes) + "\nApply it?")
            approved = assume_yes or (ask(prompt) if ask else False)
            if not approved:
                out.pending_confirmation = entry
                break
        if not backed_up:
            out.backup = _backup(ws, items, ctx)
            backed_up = True
        mig.module.apply(ctx)
        out.applied.append(mig.id)
        applied.append(mig.id)
    if not dry_run:
        meta = ctx.meta()
        meta["applied_migrations"] = applied
        ctx.save_meta(meta)
    return out


def _backup(ws: Path, migrations: List[Migration], ctx: Context) -> str:
    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    dest = ws / ".njl" / "backup" / f"migrate-{stamp}"
    names = {"config/profile-wrap.json", ".njl/workspace.json"}
    for mig in migrations:
        names.update(getattr(mig.module, "FILES", []))
    for rel in sorted(names):
        src = ws / rel
        if src.is_file():
            (dest / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest / rel)
    return str(dest)
