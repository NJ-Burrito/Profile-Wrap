"""Leak check: `profile-wrap leaks scan --tree|--dist`.

Scans a source tree (or built artefacts: wheel, sdist, zipapp, plugin zip) for
things that must never reach a public repository: fonts, photos, secrets,
personal paths, emails, real LinkedIn identifiers, and terms from a private
denylist.

Private denylist: a JSON file of salted sha256 hashes, supplied from outside the
repo (`--denylist FILE` or the PROFILE_WRAP_LEAK_DENYLIST environment variable). The file
holds hashes only, so it cannot leak the terms. Text is decoded before matching
(\\u and \\x escapes, HTML entities, percent escapes, hex and base64 chunks), then
tokenised into windows of 1..N words. Denylist hits are never waivable.

Exit codes: 0 clean, 1 findings, 2 usage or configuration error.
Allow rules live in release/leak-allow.json, each with a reason.
Not in this milestone: --history (git history), gitleaks, git identities.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import fnmatch
import hashlib
import html
import io
import json
import os
import re
import secrets
import subprocess
import sys
import tarfile
import unicodedata
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Iterable, Iterator
from urllib.parse import unquote

ENV_DENYLIST = "PROFILE_WRAP_LEAK_DENYLIST"
BIG_BINARY_BYTES = 1_000_000
MAX_MEMBER_BYTES = 64 * 1024 * 1024
ARCHIVE_SUFFIXES = (".whl", ".zip", ".pyz", ".tar.gz", ".tgz", ".tar")

FONT_EXT = {".woff", ".woff2", ".ttf", ".otf", ".eot"}
PHOTO_EXT = {".jpg", ".jpeg", ".heic", ".heif", ".tif", ".tiff", ".raw", ".dng"}
MEDIA_EXT = PHOTO_EXT | {
    ".png", ".gif", ".webp", ".avif", ".bmp", ".ico", ".mp4", ".mov", ".webm",
    ".mkv", ".avi", ".mp3", ".wav", ".m4a", ".ogg", ".flac",
}
SECRET_SUFFIX = {".pem", ".key", ".p12", ".pfx", ".kdbx"}

# Rules that only a sha256 allow entry may waive.
HASH_ONLY_RULES = {"font-binary", "photo", "media-unlisted", "big-binary"}
# Rules that nothing may waive.
NEVER_WAIVABLE = {"private-term"}

_FONT_NAME = "Thman" + "yah"  # split so this file does not match its own rule

_PLACEHOLDER_WORDS = ("example", "your", "xxxx", "placeholder", "redacted", "changeme", "dummy", "fake", "sample", "<")
_OK_EMAIL_DOMAINS = ("example.com", "example.org", "example.net")
_OK_HOME_NAMES = {"runner", "user", "you", "me", "example", "username", "name", "shared", "yourname", "someone"}


@dataclass(frozen=True)
class Finding:
    rule: str
    path: str
    line: int = 0
    detail: str = ""

    def render(self) -> str:
        loc = f"{self.path}:{self.line}" if self.line else self.path
        return f"{self.rule}  {loc}" + (f"  ({self.detail})" if self.detail else "")


# ---------------------------------------------------------------- allow rules


@dataclass
class AllowRule:
    rule: str
    reason: str
    path: str | None = None
    sha256: str | None = None


class AllowError(ValueError):
    pass


def load_allow(path: Path | None) -> list[AllowRule]:
    if path is None or not Path(path).is_file():
        return []
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AllowError(f"cannot read allow file {path}: {exc}") from exc
    out: list[AllowRule] = []
    for i, e in enumerate(data.get("allow", [])):
        reason = str(e.get("reason", "")).strip()
        rule = str(e.get("rule", "")).strip()
        if not reason:
            raise AllowError(f"allow entry {i} has no reason")
        if not rule:
            raise AllowError(f"allow entry {i} has no rule")
        if rule in NEVER_WAIVABLE:
            raise AllowError(f"allow entry {i}: rule {rule} cannot be waived")
        if not e.get("path") and not e.get("sha256"):
            raise AllowError(f"allow entry {i} needs path or sha256")
        if rule in HASH_ONLY_RULES and not e.get("sha256"):
            raise AllowError(f"allow entry {i}: rule {rule} needs a sha256, not a path")
        out.append(AllowRule(rule, reason, e.get("path"), (e.get("sha256") or "").lower() or None))
    return out


def _allowed(rule: str, relpath: str, sha: str, allow: list[AllowRule]) -> bool:
    if rule in NEVER_WAIVABLE:
        return False
    for a in allow:
        if a.rule not in (rule, "*"):
            continue
        if a.sha256 and a.sha256 == sha:
            return True
        if a.path and rule not in HASH_ONLY_RULES and fnmatch.fnmatch(relpath, a.path):
            return True
    return False


# ------------------------------------------------------------------- denylist


def _norm_tokens(text: str) -> list[str]:
    return re.findall(r"[^\W_]+", unicodedata.normalize("NFKC", text).casefold())


def _h(salt: bytes, s: str) -> str:
    return hashlib.sha256(salt + b"\0" + s.encode("utf-8")).hexdigest()


def build_denylist(terms: Iterable[str], salt: str | None = None, max_words: int = 4) -> dict:
    """Return the JSON-serialisable denylist for `terms` (keep it outside the public repo)."""
    salt = salt or secrets.token_hex(16)
    sb = salt.encode()
    hashes: set[str] = set()
    for term in terms:
        toks = _norm_tokens(term)
        if not toks or len("".join(toks)) < 3:
            raise ValueError("denylist terms must have at least 3 letters or digits")
        if len(toks) > max_words:
            raise ValueError(f"term has more than {max_words} words")
        hashes.add(_h(sb, " ".join(toks)))
        hashes.add(_h(sb, "".join(toks)))
    return {"version": 1, "salt": salt, "max_words": max_words, "hashes": sorted(hashes)}


_ESC_PATTERNS = [
    (re.compile(r"\\+U([0-9a-fA-F]{8})"), lambda m: _chr(int(m.group(1), 16))),
    (re.compile(r"\\+u([0-9a-fA-F]{4})"), lambda m: _chr(int(m.group(1), 16))),
    (re.compile(r"\\+x([0-9a-fA-F]{2})"), lambda m: chr(int(m.group(1), 16))),
]
_B64_CHUNK = re.compile(r"[A-Za-z0-9+/_-]{12,}={0,2}")
_HEX_CHUNK = re.compile(r"(?:[0-9a-fA-F]{2}){6,}")


def _chr(n: int) -> str:
    try:
        return chr(n)
    except (ValueError, OverflowError):
        return ""


def _unescape(s: str) -> str:
    out = s
    for rx, fn in _ESC_PATTERNS:
        out = rx.sub(fn, out)
    if "&" in out:
        out = html.unescape(out)
    if "%" in out:
        out = unquote(out)
    # join surrogate pairs written as two \u escapes
    try:
        out = out.encode("utf-16", "surrogatepass").decode("utf-16")
    except UnicodeError:
        pass
    return out


def _printable(s: str) -> bool:
    if len(s) < 3:
        return False
    ok = sum(1 for c in s if c.isprintable() or c in "\r\n\t")
    return ok / len(s) >= 0.9


def _try_decode(raw: bytes) -> str | None:
    for enc in ("utf-8", "utf-16-le"):
        try:
            s = raw.decode(enc)
        except UnicodeError:
            continue
        if _printable(s):
            return s
    return None


def _decoded_variants(line: str, depth: int = 3) -> Iterator[str]:
    """Yield the line and everything decodable from it (escapes, base64, hex)."""
    yield line
    if depth <= 0:
        return
    un = _unescape(line)
    if un != line:
        yield from _decoded_variants(un, depth - 1)
    for m in list(_B64_CHUNK.finditer(line))[:200]:
        chunk = m.group(0).rstrip("=")
        chunk += "=" * (-len(chunk) % 4)
        for fn in (base64.b64decode, base64.urlsafe_b64decode):
            try:
                dec = _try_decode(fn(chunk))
            except (binascii.Error, ValueError):
                continue
            if dec:
                yield from _decoded_variants(dec, depth - 1)
                break
    for m in list(_HEX_CHUNK.finditer(line))[:100]:
        dec = _try_decode(bytes.fromhex(m.group(0)))
        if dec:
            yield from _decoded_variants(dec, depth - 1)


@dataclass
class Denylist:
    salt: bytes
    hashes: frozenset
    max_words: int = 4
    _cache: dict = field(default_factory=dict, repr=False)

    @classmethod
    def load(cls, path: str | Path) -> "Denylist":
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        if data.get("version") != 1 or "salt" not in data:
            raise ValueError("not a denylist file (version 1 with salt)")
        return cls(data["salt"].encode(), frozenset(data["hashes"]), int(data.get("max_words", 4)))

    def _hit(self, s: str) -> bool:
        r = self._cache.get(s)
        if r is None:
            r = _h(self.salt, s) in self.hashes
            if len(self._cache) < 200_000:
                self._cache[s] = r
        return r

    def check(self, text: str) -> bool:
        for v in _decoded_variants(text):
            toks = _norm_tokens(v)
            for i in range(len(toks)):
                for n in range(1, self.max_words + 1):
                    win = toks[i : i + n]
                    if len(win) < n:
                        break
                    joined = "".join(win)
                    if len(joined) < 3:
                        continue
                    if self._hit(" ".join(win)) or (n > 1 and self._hit(joined)):
                        return True
        return False


# ----------------------------------------------------------- generic patterns


def _bad_email(m: re.Match) -> bool:
    dom = m.group(1).lower()
    if dom in _OK_EMAIL_DOMAINS or dom.endswith(".invalid") or dom.endswith(".example") or dom in ("localhost",):
        return False
    if dom.endswith((".png", ".jpg", ".svg", ".gif", ".js", ".css", ".py", ".json", ".md")):
        return False  # e.g. icon@2x.png
    return True


def _bad_phone(m: re.Match) -> bool:
    s = m.group(0)
    digits = re.sub(r"\D", "", s)
    if not 9 <= len(digits) <= 15:
        return False
    if "555" in s and re.search(r"555[\s.-]?01\d\d", s):
        return False  # fictional range
    if set(digits) <= {"0", "1"}:
        return False
    return True


def _bad_urn(m: re.Match) -> bool:
    ident = m.group(2)
    return not (ident.upper().startswith("DEMO") or set(ident) <= {"0", "x", "X"} or len(ident) < 4 or ident.lower() in ("id", "urn", "xxx"))


def _bad_secret_assign(m: re.Match) -> bool:
    val = m.group(2)
    low = val.lower()
    if any(w in low for w in _PLACEHOLDER_WORDS):
        return False
    return bool(re.search(r"\d", val) and re.search(r"[A-Za-z]", val)) and len(val) >= 20


def _bad_home(m: re.Match) -> bool:
    name = (m.group(1) or "").lower()
    return name not in _OK_HOME_NAMES


def _bad_url(m: re.Match) -> bool:
    handle = m.group(1).lower()
    return not any(w in handle for w in ("demo", "example", "your", "handle", "username", "name", "<", "{"))


def _always(_m: re.Match) -> bool:
    return True


# (rule, compiled regex, predicate(match)->bool, applies-to-name-too)
_TEXT_RULES: list[tuple[str, re.Pattern, object]] = [
    ("token-github", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"), _always),
    ("token-anthropic", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{10,}"), _always),
    ("token-sk", re.compile(r"\bsk-(?:or-v1-|proj-)?[A-Za-z0-9_-]{24,}"), _always),
    ("token-apify", re.compile(r"\bapify_api_[A-Za-z0-9]{8,}"), _always),
    ("token-linkedin", re.compile(r"\bAQ[VUWX][A-Za-z0-9_-]{70,}"), _always),
    ("token-aws", re.compile(r"\bAKIA[0-9A-Z]{16}\b"), _always),
    ("token-slack", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"), _always),
    ("token-bearer", re.compile(r"\bBearer\s+([A-Za-z0-9._~+/-]{24,})"), lambda m: not any(w in m.group(1).lower() for w in _PLACEHOLDER_WORDS)),
    ("token-assign", re.compile(r"(?i)(client_secret|access_token|refresh_token|api[_-]?key)[\"']?\s*[=:]\s*[\"']?([A-Za-z0-9_\-.]{16,})"), _bad_secret_assign),
    ("private-key", re.compile(r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----"), _always),
    ("email", re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,})"), _bad_email),
    ("phone", re.compile(r"(?<![\w.])(?:\+\d[\d\s().-]{8,}\d|\(\d{3}\)\s?\d{3}-\d{4}|\b\d{3}-\d{3}-\d{4}\b)"), _bad_phone),
    ("home-path", re.compile(r"[A-Za-z]:[\\/]+Users[\\/]+([^\\/\s\"'<>]+)"), _bad_home),
    ("home-path", re.compile(r"(?<![\w.~-])/Users/([A-Za-z0-9._-]+)/"), _bad_home),
    ("home-path", re.compile(r"(?<![\w.~-])/home/([a-z_][a-z0-9_-]*)/"), _bad_home),
    ("drive-path", re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:\\+[A-Za-z0-9_.$]"), _always),
    ("drive-path", re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:/(?:Users|Windows|Program Files|VScode)"), _always),
    ("linkedin-urn", re.compile(r"urn:li:(person|share|ugcPost|activity|organization|member|fsd_profile):([A-Za-z0-9_-]+)"), _bad_urn),
    ("activity-id", re.compile(r"(?<![\w.])\d{19}(?![\w.])"), _always),
    ("tracking-param", re.compile(r"[?&](?:rcm|trackingId|trk|midToken)=[^\s&\"']+"), _always),
    ("tracking-param", re.compile(r"[?&]utm_[a-z]+="), _always),
    ("signed-cdn-url", re.compile(r"https?://[^\s\"'<>]*licdn\.com[^\s\"'<>]*[?&](?:e|v|t|Expires|Signature|Policy|Key-Pair-Id)=", re.I), _always),
    ("linkedin-url", re.compile(r"linkedin\.com/(?:in|pub|posts|feed/update|company)/([^\s\"')<>/?#\]]+)", re.I), _bad_url),
]
_FONT_RE = re.compile(_FONT_NAME, re.I)
_FONT_OK_PATHS = {"docs/FONTS.md"}


def _is_binary(data: bytes, ext: str) -> bool:
    return ext in MEDIA_EXT or ext in FONT_EXT or b"\0" in data[:8192]


def _scan_text(text: str, relpath: str, ctx: "_Ctx", out: list[Finding]) -> None:
    for lineno, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        seen: set[str] = set()
        for rule, rx, pred in _TEXT_RULES:
            for m in rx.finditer(line):
                if rule not in seen and pred(m):
                    seen.add(rule)
                    out.append(Finding(rule, relpath, lineno))
        if relpath not in _FONT_OK_PATHS and _FONT_RE.search(line):
            out.append(Finding("font-name", relpath, lineno, "licensed font family named outside docs/FONTS.md"))
        if ctx.denylist and ctx.denylist.check(line):
            out.append(Finding("private-term", relpath, lineno, "denylist hash match"))


@dataclass
class _Ctx:
    allow: list[AllowRule]
    denylist: Denylist | None
    dist: bool = False


def scan_blob(data: bytes, relpath: str, ctx: _Ctx) -> list[Finding]:
    """Scan one file's bytes under its (posix) relative path."""
    raw: list[Finding] = []
    pp = PurePosixPath(relpath)
    name = pp.name
    ext = pp.suffix.lower()
    sha = hashlib.sha256(data).hexdigest()

    if ext in FONT_EXT:
        raw.append(Finding("font-binary", relpath, detail="font file"))
    if ext in PHOTO_EXT:
        raw.append(Finding("photo", relpath, detail="photo file"))
    elif ext in MEDIA_EXT:
        raw.append(Finding("media-unlisted", relpath, detail="image/audio/video not in hash allowlist"))
    if ext in {".jpg", ".jpeg", ".tif", ".tiff", ".heic", ".png", ".webp"} and (b"Exif\x00\x00" in data[:65536] or b"<x:xmpmeta" in data[:65536]):
        raw.append(Finding("image-exif", relpath, detail="EXIF/XMP metadata"))
    if name in {".env", "token.json"} or (name.startswith(".env.") and not name.endswith((".example", ".sample", ".template"))) or ext in SECRET_SUFFIX or name.startswith("id_rsa") or name.startswith("id_ed25519"):
        raw.append(Finding("secret-file", relpath))
    if ext == ".pyc" or "__pycache__" in pp.parts:
        raw.append(Finding("pyc", relpath))
    if ext == ".pyz" and not ctx.dist:
        raw.append(Finding("zipapp-committed", relpath, detail="build zipapps in release, do not commit"))
    if relpath not in _FONT_OK_PATHS and _FONT_RE.search(relpath):
        raw.append(Finding("font-name", relpath, detail="in file name"))
    if ctx.denylist and ctx.denylist.check(relpath):
        raw.append(Finding("private-term", relpath, detail="in file name"))

    binary = _is_binary(data, ext)
    if binary:
        if len(data) > BIG_BINARY_BYTES and not any(f.rule in ("font-binary", "photo", "media-unlisted") for f in raw):
            raw.append(Finding("big-binary", relpath, detail=f"{len(data)} bytes"))
    else:
        text = data.decode("utf-8", errors="replace")
        _scan_text(text, relpath, ctx, raw)
    return [f for f in raw if not _allowed(f.rule, relpath, sha, ctx.allow)]


# ------------------------------------------------------------------- walking


def _git_files(root: Path) -> list[str] | None:
    if not (root / ".git").exists():
        return None
    try:
        res = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            capture_output=True, timeout=60, check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return [p for p in res.stdout.decode("utf-8", "replace").split("\0") if p]


def _walk(root: Path) -> list[str]:
    out = []
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d != ".git"]
        for fn in fns:
            out.append(Path(dp, fn).relative_to(root).as_posix())
    return out


def list_tree(root: Path) -> list[str]:
    return sorted(set(_git_files(root) or _walk(root)))


def scan_files(root: Path, relpaths: Iterable[str], allow: list[AllowRule] | None = None, denylist: Denylist | None = None) -> list[Finding]:
    ctx = _Ctx(allow or [], denylist)
    out: list[Finding] = []
    for rel in relpaths:
        p = root / rel
        if p.is_symlink() or not p.is_file():
            continue
        out.extend(scan_blob(p.read_bytes(), rel.replace("\\", "/"), ctx))
    return out


def scan_tree(root: Path | str, allow: list[AllowRule] | None = None, denylist: Denylist | None = None) -> list[Finding]:
    root = Path(root)
    if allow is None:
        allow = load_allow(root / "release" / "leak-allow.json")
    return scan_files(root, list_tree(root), allow, denylist)


def _archive_members(data: bytes, name: str) -> Iterator[tuple[str, bytes]]:
    low = name.lower()
    if low.endswith((".tar.gz", ".tgz", ".tar")):
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as tf:
            for m in tf:
                if m.isfile() and m.size <= MAX_MEMBER_BYTES:
                    f = tf.extractfile(m)
                    if f:
                        yield m.name, f.read()
    else:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:  # zipapps carry a shebang prefix; zipfile copes
            for info in zf.infolist():
                if not info.is_dir() and info.file_size <= MAX_MEMBER_BYTES:
                    yield info.filename, zf.read(info)


def _scan_archive(data: bytes, label: str, ctx: _Ctx, out: list[Finding], depth: int = 0) -> None:
    try:
        members = list(_archive_members(data, label))
    except (zipfile.BadZipFile, tarfile.TarError, OSError) as exc:
        out.append(Finding("archive-unreadable", label, detail=type(exc).__name__))
        return
    for mname, mdata in members:
        rel = f"{label}!{mname}"
        if mname.lower().endswith(ARCHIVE_SUFFIXES) and depth < 2:
            _scan_archive(mdata, rel, ctx, out, depth + 1)
        out.extend(scan_blob(mdata, rel, ctx))
    # the archive file itself: name-level rules only
    out.extend(f for f in scan_blob(b"", label, ctx) if f.rule in ("private-term", "font-name"))


def scan_dist(paths: Iterable[Path | str], allow: list[AllowRule] | None = None, denylist: Denylist | None = None) -> list[Finding]:
    """Scan built artefacts. A directory is searched for archives (recursively)."""
    ctx = _Ctx(allow or [], denylist, dist=True)
    out: list[Finding] = []
    files: list[Path] = []
    for p in map(Path, paths):
        if p.is_dir():
            files.extend(sorted(q for q in p.rglob("*") if q.is_file() and str(q).lower().endswith(ARCHIVE_SUFFIXES)))
        elif p.is_file():
            files.append(p)
        else:
            out.append(Finding("dist-missing", str(p)))
    for f in files:
        data = f.read_bytes()
        if str(f).lower().endswith(ARCHIVE_SUFFIXES):
            _scan_archive(data, f.name, ctx, out)
        else:
            out.extend(scan_blob(data, f.name, ctx))
    return out


# ------------------------------------------------------------------------ CLI


def _load_denylist(arg: str | None, required: bool) -> Denylist | None:
    path = arg or os.environ.get(ENV_DENYLIST)
    if not path:
        if required:
            raise SystemExit(_err("a private denylist is required here (--denylist FILE or PROFILE_WRAP_LEAK_DENYLIST)"))
        print("leaks: no private denylist supplied, private-term scan skipped", file=sys.stderr)
        return None
    try:
        return Denylist.load(path)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise SystemExit(_err(f"cannot load denylist: {exc}"))


def _err(msg: str) -> int:
    print(f"leaks: {msg}", file=sys.stderr)
    return 2


def run_scan(args: argparse.Namespace) -> int:
    try:
        deny = _load_denylist(args.denylist, args.require_denylist)
        allow_path = Path(args.allow) if args.allow else None
        if args.dist:
            if allow_path is None and Path("release/leak-allow.json").is_file():
                allow_path = Path("release/leak-allow.json")
            findings = scan_dist(args.dist, load_allow(allow_path), deny)
            what = "dist"
        else:
            root = Path(args.tree or ".")
            if not root.is_dir():
                return _err(f"not a directory: {root}")
            allow = load_allow(allow_path or root / "release" / "leak-allow.json")
            findings = scan_files(root, list_tree(root), allow, deny)
            what = "tree"
    except AllowError as exc:
        return _err(str(exc))
    if args.json:
        print(json.dumps([f.__dict__ for f in findings], indent=2))
    else:
        for f in findings:
            print(f.render())
        print(f"leaks scan --{what}: {'FAIL' if findings else 'PASS'} ({len(findings)} findings)")
    return 1 if findings else 0


def run_denylist_build(args: argparse.Namespace) -> int:
    terms = [t.strip() for t in Path(args.terms).read_text(encoding="utf-8-sig").splitlines() if t.strip() and not t.startswith("#")]
    try:
        data = build_denylist(terms)
    except ValueError as exc:
        return _err(str(exc))
    Path(args.out).write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"wrote {len(data['hashes'])} hashes to {args.out} (keep it outside the public repo)")
    return 0


def _populate(leaks: argparse.ArgumentParser) -> None:
    sub = leaks.add_subparsers(dest="leaks_cmd", required=True)
    s = sub.add_parser("scan", help="scan a tree or built artefacts for leaks")
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--tree", nargs="?", const=".", metavar="DIR", help="scan a source tree (default .)")
    g.add_argument("--dist", nargs="+", metavar="PATH", help="scan wheel, sdist, zipapp or plugin zip contents")
    s.add_argument("--allow", metavar="FILE", help="allow rules (default release/leak-allow.json)")
    s.add_argument("--denylist", metavar="FILE", help=f"salted-hash denylist (or ${ENV_DENYLIST})")
    s.add_argument("--require-denylist", action="store_true", help="fail (exit 2) when no denylist is supplied; use in release gates")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=run_scan)
    b = sub.add_parser("denylist-build", help="hash a terms file into a denylist (run outside the public repo)")
    b.add_argument("terms", help="text file, one term per line")
    b.add_argument("out")
    b.set_defaults(func=run_denylist_build)


def register(subparsers) -> None:
    """Add `leaks` to the profile-wrap subparsers. Handlers are set as args.func(args) -> exit code."""
    _populate(subparsers.add_parser("leaks", help="leak check for the public repo"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="profile-wrap leaks")
    _populate(ap)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
