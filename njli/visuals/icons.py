"""Lucide icons (ISC): a small subset ships in brand-kit/icons; any other icon is fetched with ``njli icons add <name>``."""
from __future__ import annotations

import re
import tempfile
from pathlib import Path
from typing import Callable, List, Optional

from njli import atomic

from . import VisualsError, kit_dir
from .assets import npm_pin
from .fonts import _extract, npm_pack

NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def icon_dirs(workspace: Optional[Path]) -> List[Path]:
    """Folders searched in order: the workspace's brand/icons, then the shipped subset."""
    out: List[Path] = []
    if workspace:
        out.append(Path(workspace) / "brand" / "icons")
    out.append(kit_dir() / "icons")
    return out


def find(name: str, workspace: Optional[Path]) -> Optional[Path]:
    if not NAME_RE.match(name):
        return None
    for d in icon_dirs(workspace):
        p = d / f"{name}.svg"
        if p.is_file():
            return p
    return None


def add(name: str, workspace: Path, packer: Optional[Callable] = None) -> dict:
    """Install one Lucide icon (and the ISC licence file) into ``<workspace>/brand/icons``."""
    if not NAME_RE.match(name):
        raise VisualsError(f"{name!r} is not a Lucide icon name (lowercase letters, digits and hyphens)")
    dest = Path(workspace) / "brand" / "icons"
    dest.mkdir(parents=True, exist_ok=True)
    pack = packer or npm_pack
    with tempfile.TemporaryDirectory(prefix="njli-icons-") as tmp:
        tgz = pack(f"lucide-static@{npm_pin('lucide-static')}", Path(tmp))
        got = _extract(tgz, {f"icons/{name}.svg": f"{name}.svg", "LICENSE": "LICENSE-lucide.txt"})
    if f"{name}.svg" not in got:
        raise VisualsError(f"lucide-static has no icon named {name!r} (browse https://lucide.dev/icons)")
    atomic.atomic_write_bytes(dest / f"{name}.svg", got[f"{name}.svg"])
    if "LICENSE-lucide.txt" in got and not (dest / "LICENSE-lucide.txt").exists():
        atomic.atomic_write_bytes(dest / "LICENSE-lucide.txt", got["LICENSE-lucide.txt"])
    return {"icon": name, "path": str(dest / f"{name}.svg"), "licence": "ISC (LICENSE-lucide.txt)"}
