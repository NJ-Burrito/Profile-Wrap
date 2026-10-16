"""Per-OS locations for the plugin, the workspace, secrets and the data dir.

Layout (section 2 of the design):
  config dir (secrets): <root>/profile-wrap/<profile>/
  data dir (code copies, caches): <root>/profile-wrap/{runtime,venv,node,vendor}/
where <root> is %APPDATA% (Windows), ~/Library/Application Support (macOS) or
${XDG_CONFIG_HOME:-~/.config} (Linux).
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Optional

from .fsutil import is_inside

APP = "profile-wrap"
RESERVED_PROFILE_IDS = {"runtime", "venv", "node", "vendor", "current"}
_PROFILE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")


class PathError(ValueError):
    """A path or profile id the CLI refuses to use."""


def os_name() -> str:
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def home() -> Path:
    return Path(os.path.expanduser("~"))


def _root() -> Path:
    name = os_name()
    if name == "windows":
        appdata = os.environ.get("APPDATA")
        return Path(appdata) if appdata else home() / "AppData" / "Roaming"
    if name == "macos":
        return home() / "Library" / "Application Support"
    xdg = os.environ.get("XDG_CONFIG_HOME")
    return Path(xdg) if xdg else home() / ".config"


def validate_profile_id(profile: str) -> str:
    if not _PROFILE_RE.match(profile) or profile in RESERVED_PROFILE_IDS:
        raise PathError(
            f"profile id '{profile}' is not allowed: use 1-40 characters from a-z, 0-9, '-' "
            f"and '_', starting with a letter or digit (not one of "
            f"{', '.join(sorted(RESERVED_PROFILE_IDS))})")
    return profile


def config_base() -> Path:
    override = os.environ.get("PROFILE_WRAP_CONFIG_DIR")
    return Path(override) if override else _root() / APP


def config_dir(profile: str = "default") -> Path:
    return config_base() / validate_profile_id(profile)


def data_dir() -> Path:
    override = os.environ.get("PROFILE_WRAP_DATA_DIR")
    return Path(override) if override else _root() / APP


def runtime_dir() -> Path:
    return data_dir() / "runtime"


def runtime_current() -> Path:
    return runtime_dir() / "current"


def legacy_config_dir() -> Path:
    """Read-only input for ``import-legacy``; nothing here is ever written."""
    return home() / ".config" / "linkedin"


def default_home() -> Path:
    override = os.environ.get("PROFILE_WRAP_HOME")
    return Path(override) if override else home() / APP


def plugin_root() -> Path:
    """Root that holds data/, schema/, templates/ (source tree or wheel payload)."""
    for env in ("PROFILE_WRAP_PLUGIN_ROOT", "CLAUDE_PLUGIN_ROOT"):
        value = os.environ.get(env)
        if value and (Path(value) / "profile_wrap").is_dir():
            return Path(value)
    here = Path(__file__).resolve().parent
    source_root = here.parent
    if (source_root / "schema").is_dir() or (source_root / "data").is_dir():
        return source_root
    payload = here / "_data"
    if payload.is_dir():
        return payload
    return source_root


def resource(*parts: str) -> Path:
    return plugin_root().joinpath(*parts)


def workspace_path(profile: str = "default", explicit: Optional[str] = None) -> Path:
    """Resolve the workspace dir; refuses a path inside the plugin dir."""
    ws = Path(explicit).expanduser() if explicit else default_home() / validate_profile_id(profile)
    ws = ws.resolve() if ws.exists() else Path(os.path.abspath(str(ws)))
    refuse_inside_plugin(ws)
    return ws


def refuse_inside_plugin(path: Path) -> None:
    root = Path(__file__).resolve().parent.parent
    for candidate in {root, plugin_root().resolve()}:
        if is_inside(path, candidate):
            raise PathError(
                f"{path} is inside the plugin directory ({candidate}). A workspace holds your "
                "data and must live elsewhere, for example ~/profile-wrap/<profile>.")


def find_workspace(start: Optional[Path] = None) -> Optional[Path]:
    """PROFILE_WRAP_WORKSPACE, else walk up from ``start`` (default cwd) to a ``.njl`` dir."""
    env = os.environ.get("PROFILE_WRAP_WORKSPACE")
    if env:
        return Path(env)
    cur = (start or Path.cwd()).resolve()
    for candidate in [cur, *cur.parents]:
        if (candidate / ".njl" / "workspace.json").is_file():
            return candidate
    return None
