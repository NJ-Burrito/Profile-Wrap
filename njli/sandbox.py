"""Worker containment: the whole-tree allowlist guard, the sandbox dir and the secret scan.

Before a worker starts, every file of the workspace is hashed (and copied aside when it is small
enough to restore). After it exits, anything changed, created or deleted outside the job's
allowlist is put back (or removed) and logged as ``RESTORED``. A file too large to copy aside that
changed is reported ``UNRESTORABLE`` and fails the job. Text the worker produced is scanned for
token-shaped strings; one hit discards the output.

Standard library only. Nothing here talks to the network.
"""
from __future__ import annotations

import fnmatch
import hashlib
import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .atomic import atomic_write_text

# Directories that are never walked (large, rebuilt, or the runner's own scratch).
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
             ".venv"}
# Workspace-relative prefixes the guard ignores: runner scratch and rotating logs.
SKIP_PREFIXES = ("work/sandbox/", "work/dryrun/", "data/logs/", "data/locks/", ".njl/backup/")
# Files inside .git that decide what runs or where it goes; guarded even though .git is skipped.
GIT_GUARDED = (".git/HEAD", ".git/config", ".git/packed-refs")
GIT_GUARDED_DIRS = (".git/hooks/",)
MAX_COPY_BYTES = 8 * 1024 * 1024


def _join(*parts: str) -> str:
    return "".join(parts)


# Token shapes. Built from pieces so this source never holds a token-shaped literal.
SECRET_PATTERNS: Tuple[Tuple[str, "re.Pattern[str]"], ...] = (
    ("linkedin-token", re.compile(r"\bAQ[VUWX][A-Za-z0-9_-]{70,}")),
    ("apify-token", re.compile(_join(r"\bapify", r"_api_", r"[A-Za-z0-9]{8,}"))),
    ("anthropic-key", re.compile(_join(r"\bsk", r"-ant-", r"[A-Za-z0-9_-]{10,}"))),
    ("generic-sk-key", re.compile(_join(r"\bsk", r"-(?:or-v1-|proj-)?", r"[A-Za-z0-9_-]{24,}"))),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}")),
    ("bearer", re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{32,}")),
    ("client-secret", re.compile(_join(r"(?i)client", r"_secret", r"[\"']?\s*[=:]\s*[\"']?",
                                       r"[A-Za-z0-9_\-.]{12,}"))),
    ("private-key", re.compile(_join(r"-----BEGIN (?:[A-Z]+ )?PRIVATE", r" KEY-----"))),
)

INJECTION_MARKERS: Tuple["re.Pattern[str]", ...] = (
    re.compile(r"(?i)ignore (all |any )?(previous|prior|above) (instructions|rules)"),
    re.compile(r"(?i)disregard (the |your )?(system|previous) (prompt|instructions)"),
    re.compile(r"(?i)you are now (a|an|in) "),
    re.compile(r"(?i)\bnew instructions?:"),
)


@dataclass
class Finding:
    rule: str
    where: str
    excerpt: str  # masked: never the secret itself


def scan_secrets(text: str, where: str = "output") -> List[Finding]:
    out: List[Finding] = []
    for name, rx in SECRET_PATTERNS:
        m = rx.search(text)
        if m:
            hit = m.group(0)
            out.append(Finding(name, where, hit[:6] + "..." + f"({len(hit)} chars)"))
    return out


def scan_injection(text: str) -> List[str]:
    return [rx.pattern for rx in INJECTION_MARKERS if rx.search(text)]


# ------------------------------------------------------------------- allowlist

def normalise_allow(patterns: Iterable[str]) -> List[str]:
    out = []
    for p in patterns:
        p = p.replace("\\", "/").strip().lstrip("./")
        if p:
            out.append(p)
    return out


def is_allowed(rel: str, allow: Sequence[str]) -> bool:
    """``rel`` is a posix path relative to the workspace.

    A pattern ending in ``/`` or ``/**`` allows a whole directory; a pattern with wildcards uses
    fnmatch; anything else is one exact file.
    """
    for pat in allow:
        if pat.endswith("/**"):
            base = pat[:-3]
            if rel == base or rel.startswith(base + "/"):
                return True
        elif pat.endswith("/"):
            if rel.startswith(pat):
                return True
        elif any(c in pat for c in "*?["):
            if fnmatch.fnmatchcase(rel, pat):
                return True
        elif rel == pat:
            return True
    return False


# -------------------------------------------------------------------- snapshot

def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _fingerprint(path: Path) -> Tuple[str, int, bool]:
    """(sha256, size, is_symlink). A symlink is fingerprinted by its target text."""
    if path.is_symlink():
        target = os.readlink(path)
        return hashlib.sha256(("symlink:" + target).encode("utf-8")).hexdigest(), 0, True
    return _sha256(path), path.stat().st_size, False


def _guarded(rel: str) -> bool:
    if rel in GIT_GUARDED or any(rel.startswith(d) for d in GIT_GUARDED_DIRS):
        return True
    return False


def _walk(root: Path) -> Iterable[Tuple[str, Path]]:
    root = Path(root)
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        rel_dir = Path(dirpath).relative_to(root).as_posix()
        rel_dir = "" if rel_dir == "." else rel_dir
        keep = []
        for d in dirnames:
            rel = f"{rel_dir}/{d}" if rel_dir else d
            if d == ".git":
                keep.append(d)  # walked, but only guarded files are recorded
                continue
            if d in SKIP_DIRS or any((rel + "/").startswith(p) for p in SKIP_PREFIXES):
                continue
            full = Path(dirpath) / d
            if full.is_symlink():  # a symlinked directory is one entry, never followed
                yield rel, full
                continue
            keep.append(d)
        dirnames[:] = keep
        for f in filenames:
            rel = f"{rel_dir}/{f}" if rel_dir else f
            if rel_dir == ".git" or rel.startswith(".git/"):
                if not _guarded(rel):
                    continue
            elif any(rel.startswith(p) for p in SKIP_PREFIXES):
                continue
            yield rel, Path(dirpath) / f
        if rel_dir == ".git":
            dirnames[:] = [d for d in dirnames if d == "hooks"]


@dataclass
class Snapshot:
    root: Path
    files: Dict[str, Tuple[str, int, bool]] = field(default_factory=dict)
    copies: Dict[str, Path] = field(default_factory=dict)
    dirs: set = field(default_factory=set)
    store: Optional[Path] = None

    def cleanup(self) -> None:
        if self.store and self.store.exists():
            shutil.rmtree(self.store, ignore_errors=True)


def take(root: Path, max_copy: int = MAX_COPY_BYTES) -> Snapshot:
    """Hash every guarded file; copy aside the ones small enough to restore."""
    root = Path(root)
    snap = Snapshot(root=root, store=Path(tempfile.mkdtemp(prefix="njli-snap-")))
    n = 0
    for rel, path in _walk(root):
        try:
            fp = _fingerprint(path)
        except OSError:
            continue
        snap.files[rel] = fp
        if not fp[2] and fp[1] <= max_copy:
            n += 1
            dst = snap.store / f"{n}"
            try:
                shutil.copy2(path, dst)
                snap.copies[rel] = dst
            except OSError:
                pass
    for dirpath, dirnames, _ in os.walk(root, followlinks=False):
        rel_dir = Path(dirpath).relative_to(root).as_posix()
        rel_dir = "" if rel_dir == "." else rel_dir
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and d != ".git"
                       and not (Path(dirpath) / d).is_symlink()]
        if rel_dir:
            snap.dirs.add(rel_dir)
    return snap


@dataclass
class Changes:
    created: List[str] = field(default_factory=list)
    modified: List[str] = field(default_factory=list)
    deleted: List[str] = field(default_factory=list)

    def all(self) -> List[str]:
        return self.created + self.modified + self.deleted

    def __bool__(self) -> bool:
        return bool(self.created or self.modified or self.deleted)


def diff(snap: Snapshot) -> Changes:
    now: Dict[str, Tuple[str, int, bool]] = {}
    for rel, path in _walk(snap.root):
        try:
            now[rel] = _fingerprint(path)
        except OSError:
            continue
    ch = Changes()
    for rel, fp in now.items():
        old = snap.files.get(rel)
        if old is None:
            ch.created.append(rel)
        elif old[0] != fp[0]:
            ch.modified.append(rel)
    for rel in snap.files:
        if rel not in now:
            ch.deleted.append(rel)
    for lst in (ch.created, ch.modified, ch.deleted):
        lst.sort()
    return ch


@dataclass
class GuardReport:
    restored: List[str] = field(default_factory=list)       # "RESTORED <how> <path>"
    unrestorable: List[str] = field(default_factory=list)
    allowed: Changes = field(default_factory=Changes)       # changes inside the allowlist
    symlinks_removed: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.unrestorable

    def lines(self) -> List[str]:
        return [f"RESTORED {r}" for r in self.restored] + \
               [f"UNRESTORABLE {r}" for r in self.unrestorable]


def enforce(snap: Snapshot, allow: Sequence[str]) -> GuardReport:
    """Undo every change outside ``allow``. Symlinks inside the allowlist are removed too."""
    allow = normalise_allow(allow)
    changes = diff(snap)
    rep = GuardReport()
    root = snap.root
    for rel in changes.created + changes.modified + changes.deleted:
        path = root / rel
        if is_allowed(rel, allow):
            if rel in changes.deleted:
                rep.allowed.deleted.append(rel)
                continue
            if path.is_symlink():  # an allowed path must be a real file, never a link out
                try:
                    path.unlink()
                    rep.symlinks_removed.append(rel)
                except OSError:
                    rep.unrestorable.append(f"{rel} (symlink inside the allowlist)")
                continue
            (rep.allowed.created if rel in changes.created else rep.allowed.modified).append(rel)
            continue
        if rel in changes.created:
            try:
                if path.is_symlink() or path.is_file():
                    path.unlink()
                elif path.is_dir():
                    shutil.rmtree(path)
                rep.restored.append(f"deleted new {rel}")
            except OSError as exc:
                rep.unrestorable.append(f"{rel} ({exc})")
            continue
        copy = snap.copies.get(rel)
        if copy is None:
            rep.unrestorable.append(f"{rel} (too large to copy aside)")
            continue
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.is_symlink() or path.is_dir():
                path.unlink() if path.is_symlink() else shutil.rmtree(path)
            shutil.copy2(copy, path)
            rep.restored.append(f"{'rewrote' if rel in changes.modified else 'recreated'} {rel}")
        except OSError as exc:
            rep.unrestorable.append(f"{rel} ({exc})")
    _remove_new_empty_dirs(snap, allow, rep)
    return rep


def _remove_new_empty_dirs(snap: Snapshot, allow: Sequence[str], rep: GuardReport) -> None:
    root = snap.root
    found: List[str] = []
    for dirpath, dirnames, _ in os.walk(root, followlinks=False):
        rel_dir = Path(dirpath).relative_to(root).as_posix()
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and d != ".git"
                       and not (Path(dirpath) / d).is_symlink()]
        if rel_dir not in (".", "") and rel_dir not in snap.dirs:
            found.append(rel_dir)
    for rel in sorted(found, key=len, reverse=True):
        if is_allowed(rel + "/x", allow) or any(rel.startswith(p.rstrip("/")) for p in SKIP_PREFIXES):
            continue
        try:
            (root / rel).rmdir()
            rep.restored.append(f"removed new folder {rel}")
        except OSError:
            pass


# ------------------------------------------------------------- the sandbox dir

def sandbox_dir(workspace: Path, job: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", job)
    return Path(workspace) / "work" / "sandbox" / safe


def prepare_sandbox(workspace: Path, job: str, inputs: Dict[str, Path | str],
                    texts: Optional[Dict[str, str]] = None) -> Path:
    """A fresh ``work/sandbox/<job>/`` holding copies of the briefed inputs only.

    ``inputs`` maps a name inside the sandbox to a workspace file to copy. ``texts`` maps a name
    to text written in place (the brief). Names may not escape the sandbox.
    """
    box = sandbox_dir(workspace, job)
    if box.exists():
        shutil.rmtree(box, ignore_errors=True)
    box.mkdir(parents=True, exist_ok=True)
    for name, src in inputs.items():
        dst = _inside(box, name)
        src = Path(src)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dst, symlinks=False)
        elif src.is_file():
            shutil.copy2(src, dst)
    for name, text in (texts or {}).items():
        dst = _inside(box, name)
        dst.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(dst, text)
    return box


def _inside(box: Path, name: str) -> Path:
    dst = (box / name).resolve()
    if box.resolve() not in dst.parents and dst != box.resolve():
        raise ValueError(f"sandbox name escapes the sandbox: {name}")
    return dst
