"""Atomic file writes: temp file in the same directory, then ``os.replace``."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Union

PathLike = Union[str, "os.PathLike[str]"]


def atomic_write_bytes(path: PathLike, data: bytes) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=target.name + ".", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, target)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return target


def atomic_write_text(path: PathLike, text: str, encoding: str = "utf-8") -> Path:
    # Newlines are written as given: files stay byte-stable across operating systems.
    return atomic_write_bytes(path, text.encode(encoding))


def atomic_write_json(path: PathLike, obj: Any, indent: int = 2) -> Path:
    text = json.dumps(obj, indent=indent, ensure_ascii=False, sort_keys=False) + "\n"
    return atomic_write_text(path, text)
