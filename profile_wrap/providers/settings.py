"""The chosen provider and model, in ``<workspace>/config/providers.json``. Never a key.

The file is not a config section, so ``profile-wrap config validate`` ignores it.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from ..atomic import atomic_write_json
from ..fsutil import read_json
from .keypatterns import looks_like_key

REL = Path("config") / "providers.json"


def path(workspace: Path) -> Path:
    return Path(workspace) / REL


def load(workspace: Path) -> Dict[str, Any]:
    p = path(workspace)
    if not p.is_file():
        return {}
    try:
        data = read_json(p)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def save(workspace: Path, provider: str, model: str, base_url: Optional[str] = None) -> Path:
    doc: Dict[str, Any] = {"schema_version": 1, "provider": provider, "model": model}
    if base_url:
        doc["base_url"] = base_url
    if any(looks_like_key(str(v)) for v in doc.values()):
        raise ValueError("refusing to write a key-shaped value into the provider settings")
    p = path(workspace)
    p.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(p, doc)
    return p
