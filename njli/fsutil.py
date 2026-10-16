"""Small filesystem helpers shared by every package."""
from __future__ import annotations

import getpass
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple, Union

from .atomic import atomic_write_bytes, atomic_write_json, atomic_write_text  # noqa: F401

PathLike = Union[str, "os.PathLike[str]"]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_file(path: PathLike) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_text(path: PathLike) -> str:
    """Read UTF-8 text, tolerating a BOM and CRLF."""
    return Path(path).read_text(encoding="utf-8-sig")


def read_json(path: PathLike, default: Any = None) -> Any:
    """Read JSON (BOM tolerant). Missing file returns ``default`` when given."""
    p = Path(path)
    if not p.exists():
        if default is not None:
            return default
        raise FileNotFoundError(str(p))
    return json.loads(read_text(p))


def append_jsonl(path: PathLike, row: Dict[str, Any]) -> None:
    """Append one JSON object as a single ``write`` call (``O_APPEND``)."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    line = (json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    fd = os.open(str(target), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, line)
        os.fsync(fd)
    finally:
        os.close(fd)


def read_jsonl(path: PathLike) -> Tuple[List[Dict[str, Any]], List[int]]:
    """Return ``(rows, bad_line_numbers)``; one corrupt line never hides the rest."""
    rows: List[Dict[str, Any]] = []
    bad: List[int] = []
    p = Path(path)
    if not p.exists():
        return rows, bad
    for number, line in enumerate(read_text(p).splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except ValueError:
            bad.append(number)
            continue
        if isinstance(value, dict):
            rows.append(value)
        else:
            bad.append(number)
    return rows, bad


def iter_files(root: PathLike) -> Iterator[Path]:
    for dirpath, _dirs, files in os.walk(str(root)):
        for name in sorted(files):
            yield Path(dirpath) / name


def is_inside(child: PathLike, parent: PathLike) -> bool:
    """True when ``child`` is ``parent`` or below it (symlinks resolved)."""
    try:
        Path(os.path.realpath(str(child))).relative_to(Path(os.path.realpath(str(parent))))
    except ValueError:
        return False
    return True


def secure_file(path: PathLike) -> bool:
    """Restrict a file to the current user: chmod 0600, or an icacls ACL on Windows."""
    p = Path(path)
    if sys.platform == "win32":
        user = os.environ.get("USERNAME") or getpass.getuser()
        try:
            result = subprocess.run(
                ["icacls", str(p), "/inheritance:r", "/grant:r", f"{user}:(R,W)"],
                capture_output=True, text=True, timeout=20)
        except (OSError, subprocess.SubprocessError):
            return False
        return result.returncode == 0
    try:
        os.chmod(p, 0o600)
    except OSError:
        return False
    return True


def write_secret(path: PathLike, text: str) -> Path:
    """Write a secrets file atomically and lock it down to the current user."""
    target = atomic_write_text(path, text)
    secure_file(target)
    return target


def secret_file_is_private(path: PathLike) -> Optional[bool]:
    """POSIX: True when no group/other bits are set. Windows: None (not inspected)."""
    if sys.platform == "win32":
        return None
    try:
        mode = Path(path).stat().st_mode
    except OSError:
        return None
    return (mode & 0o077) == 0


def slugify(text: str, max_len: int = 60) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:max_len].strip("-") or "item"


def copy_tree(src: PathLike, dst: PathLike, ignore: Iterable[str] = ("__pycache__", "*.pyc")) -> int:
    """Copy a directory tree, skipping ignored names. Returns the file count."""
    import fnmatch
    import shutil

    count = 0
    srcp, dstp = Path(src), Path(dst)
    patterns = tuple(ignore)
    for dirpath, dirs, files in os.walk(str(srcp)):
        dirs[:] = [d for d in dirs if not any(fnmatch.fnmatch(d, p) for p in patterns)]
        rel = Path(dirpath).relative_to(srcp)
        (dstp / rel).mkdir(parents=True, exist_ok=True)
        for name in files:
            if any(fnmatch.fnmatch(name, p) for p in patterns):
                continue
            shutil.copy2(Path(dirpath) / name, dstp / rel / name)
            count += 1
    return count
