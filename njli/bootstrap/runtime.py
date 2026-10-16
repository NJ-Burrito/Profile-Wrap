"""Build and sync the stable runtime: a code copy that scheduled jobs call.

``runtime install`` copies the source tree into ``<data>/runtime/<version>/`` and points
``<data>/runtime/current`` at it (symlink, else a Windows junction, else a plain copy). The
copy has a ``__main__.py``, so ``<python> <data>/runtime/current <args>`` runs njli; that is
the command a scheduler stores. A plugin update never breaks running jobs: they keep calling
the stable copy until ``runtime sync`` replaces it.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .. import __version__, paths
from ..atomic import atomic_write_json, atomic_write_text
from ..fsutil import copy_tree

COPY_DIRS = ("njli", "data", "schema", "templates", "prompts", "agents", "brand-kit", "docs")
KEEP_OLD_VERSIONS = 2

LAUNCHER = '''"""Stable runtime entry point: python <this directory> <njli arguments>."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ["NJLI_PLUGIN_ROOT"] = HERE
os.environ.setdefault("PYTHONUTF8", "1")

from njli.bootstrap import find_python  # noqa: E402

message = find_python.version_message()
if message:
    sys.stderr.write(message + "\\n")
    sys.exit(1)

from njli.cli import main  # noqa: E402

sys.exit(main())
'''


def _replace(src: Path, dst: Path, attempts: int = 8) -> None:
    """``os.replace`` with retries: on Windows a virus scanner or indexer can hold a freshly
    written directory for a moment and the rename fails with 'access denied'."""
    for attempt in range(attempts):
        try:
            os.replace(str(src), str(dst))
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.25 * (attempt + 1))


def tree_hash(root: Path) -> str:
    """Hash of every file the runtime copies (names and bytes), for drift detection."""
    digest = hashlib.sha256()
    for name in COPY_DIRS:
        base = Path(root) / name
        if not base.is_dir():
            continue
        for dirpath, dirs, files in os.walk(str(base)):
            dirs[:] = sorted(d for d in dirs if d != "__pycache__")
            for fname in sorted(files):
                if fname.endswith(".pyc"):
                    continue
                path = Path(dirpath) / fname
                digest.update(str(path.relative_to(root)).replace("\\", "/").encode("utf-8"))
                digest.update(path.read_bytes())
    return digest.hexdigest()


def _is_link_or_junction(path: Path) -> bool:
    if path.is_symlink():
        return True
    if sys.platform == "win32" and path.exists():
        try:
            attrs = os.stat(str(path), follow_symlinks=False).st_file_attributes  # type: ignore[attr-defined]
        except (OSError, AttributeError):
            return False
        return bool(attrs & 0x400)  # FILE_ATTRIBUTE_REPARSE_POINT
    return False


def _remove_current(current: Path) -> None:
    if _is_link_or_junction(current):
        try:
            os.unlink(str(current))
        except (PermissionError, IsADirectoryError, OSError):
            os.rmdir(str(current))
    elif current.is_dir():
        shutil.rmtree(str(current))
    elif current.exists():
        current.unlink()


def point_current(runtime: Path, version: str) -> str:
    """Make ``runtime/current`` equal ``runtime/<version>``. Returns the mode used."""
    target = runtime / version
    current = runtime / "current"
    if current.exists() or current.is_symlink():
        _remove_current(current)
    mode = "copy"
    try:
        os.symlink(str(target), str(current), target_is_directory=True)
        mode = "symlink"
    except (OSError, NotImplementedError):
        if sys.platform == "win32":
            result = subprocess.run(["cmd", "/c", "mklink", "/J", str(current), str(target)],
                                    capture_output=True, text=True, timeout=30)
            if result.returncode == 0 and current.exists():
                mode = "junction"
        if mode == "copy":
            copy_tree(target, current)
    atomic_write_text(runtime / "current.version", version + "\n")
    return mode


def _read_meta(path: Path) -> Dict[str, Any]:
    try:
        return json.loads((path / "RUNTIME.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def installed_versions(runtime: Path) -> List[str]:
    if not runtime.is_dir():
        return []
    return sorted(p.name for p in runtime.iterdir()
                  if p.is_dir() and p.name != "current" and not p.name.endswith(".tmp"))


def current_version(runtime: Path) -> Optional[str]:
    marker = runtime / "current.version"
    if marker.is_file():
        text = marker.read_text(encoding="utf-8").strip()
        return text or None
    meta = _read_meta(runtime / "current")
    return meta.get("version")


def entry_command(data: Optional[Path] = None) -> List[str]:
    """The command prefix a scheduler stores: ``[interpreter, <runtime>/current]``."""
    runtime = (data or paths.data_dir()) / "runtime"
    meta = _read_meta(runtime / "current")
    interpreter = meta.get("python") or sys.executable
    pyz = runtime / "current" / "njli.pyz"
    return [interpreter, str(pyz if pyz.is_file() else runtime / "current")]


def status(plugin_root: Optional[Path] = None, data: Optional[Path] = None) -> Dict[str, Any]:
    root = Path(plugin_root) if plugin_root else paths.plugin_root()
    runtime = (data or paths.data_dir()) / "runtime"
    cur = current_version(runtime)
    meta = _read_meta(runtime / "current") if cur else {}
    src_hash = tree_hash(root)
    drift = None
    reason = ""
    if cur is None:
        drift, reason = True, "no stable runtime installed"
    elif cur != __version__:
        drift, reason = True, f"runtime/current is {cur}, plugin is {__version__}"
    elif meta.get("tree_hash") and meta["tree_hash"] != src_hash:
        drift, reason = True, "code changed since runtime/current was built"
    else:
        drift = False
    return {
        "runtime_dir": str(runtime),
        "installed": installed_versions(runtime),
        "current": cur,
        "plugin_version": __version__,
        "drift": drift,
        "reason": reason,
        "mode": "symlink" if _is_link_or_junction(runtime / "current") else
                ("copy" if cur else None),
        "entry": entry_command(data) if cur else None,
    }


def install(plugin_root: Optional[Path] = None, data: Optional[Path] = None,
            interpreter: Optional[str] = None, pyz: Optional[Path] = None) -> Dict[str, Any]:
    """Copy the source tree to ``runtime/<version>`` and repoint ``current``."""
    root = Path(plugin_root) if plugin_root else paths.plugin_root()
    base = data or paths.data_dir()
    runtime = base / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    if not (root / "njli").is_dir():
        raise FileNotFoundError(f"{root} does not contain the njli package")
    version = __version__
    staging = Path(tempfile.mkdtemp(prefix=f"{version}.", suffix=".tmp", dir=str(runtime)))
    try:
        files = 0
        for name in COPY_DIRS:
            src = root / name
            if src.is_dir():
                files += copy_tree(src, staging / name)
        atomic_write_text(staging / "__main__.py", LAUNCHER)
        if pyz is not None and Path(pyz).is_file():
            shutil.copy2(str(pyz), str(staging / "njli.pyz"))
        meta = {
            "version": version,
            "python": interpreter or sys.executable,
            "installed_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
            "tree_hash": tree_hash(root),
            "files": files,
        }
        atomic_write_json(staging / "RUNTIME.json", meta)
        target = runtime / version
        if target.exists():
            old = runtime / f"{version}.old.tmp"
            if old.exists():
                shutil.rmtree(str(old))
            _replace(target, old)
            _replace(staging, target)
            shutil.rmtree(str(old), ignore_errors=True)
        else:
            _replace(staging, target)
    except BaseException:
        shutil.rmtree(str(staging), ignore_errors=True)
        raise
    mode = point_current(runtime, version)
    pruned = prune(runtime, keep=KEEP_OLD_VERSIONS, current=version)
    return {"version": version, "runtime_dir": str(runtime), "mode": mode, "files": files,
            "pruned": pruned, "entry": entry_command(base)}


def prune(runtime: Path, keep: int, current: str) -> List[str]:
    others = [v for v in installed_versions(runtime) if v != current]
    removed = []
    for version in sorted(others, key=_version_key)[:-keep] if keep else others:
        shutil.rmtree(str(runtime / version), ignore_errors=True)
        removed.append(version)
    return removed


def _version_key(text: str):
    parts = []
    for piece in text.replace("-", ".").split("."):
        parts.append((0, int(piece)) if piece.isdigit() else (-1, 0))
    return parts


def sync(plugin_root: Optional[Path] = None, data: Optional[Path] = None,
         force: bool = False) -> Dict[str, Any]:
    """Install only when the runtime is missing or has drifted."""
    st = status(plugin_root, data)
    if st["drift"] or force:
        result = install(plugin_root, data)
        result["action"] = "installed"
        return result
    st["action"] = "unchanged"
    return st
